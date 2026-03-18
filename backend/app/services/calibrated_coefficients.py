"""Calibrated Coefficients loader for HKSimEngine.

Reads sentiment → indicator regression coefficients from
``data/calibration_coefficients.json`` (produced by CalibrationPipeline).
Falls back to hardcoded defaults when the file is absent or malformed.

Usage::

    cc = CalibratedCoefficients()
    await cc.load()
    coef = cc.get("consumer_confidence", "negative_ratio")  # -0.3 (default)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.app.utils.logger import get_logger

logger = get_logger("calibrated_coefficients")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_DEFAULT_COEF_PATH = _PROJECT_ROOT / "data" / "calibration_coefficients.json"

# ---------------------------------------------------------------------------
# Default (fallback) coefficients
# ---------------------------------------------------------------------------

# Alias map: alternative names → canonical names used in calibration JSON.
# Allows both "gdp_growth" and "gdp_growth_rate" to resolve correctly.
_INDICATOR_ALIASES: dict[str, str] = {
    "gdp_growth": "gdp_growth_rate",
    "gdp_growth_rate": "gdp_growth",
}

_DEFAULTS: dict[str, dict[str, float]] = {
    "consumer_confidence": {
        "negative_ratio": -0.3,
        "positive_ratio": 0.2,
    },
    "gdp_growth": {
        "negative_ratio": -0.001,
    },
    "hsi_level": {
        "positive_ratio": 0.001,
        "stock_market_positive": 0.002,
    },
    "ccl_index": {
        "property_negative": -0.001,
    },
    "unemployment_rate": {
        "employment_negative": 0.001,
        "negative_ratio": 0.0008,
    },
    "net_migration": {
        "emigration_freq": -100.0,
    },
}


# ---------------------------------------------------------------------------
# CalibratedCoefficients
# ---------------------------------------------------------------------------


class CalibratedCoefficients:
    """Runtime loader for calibrated OLS regression coefficients.

    Attributes:
        _coefficients: Nested dict {indicator → {sentiment_metric → float}}.
        _loaded: Whether coefficients have been successfully loaded.
        _source: Where the coefficients were loaded from ("file" or "defaults").
    """

    def __init__(self, coef_path: Path | None = None) -> None:
        self._coef_path: Path = coef_path or _DEFAULT_COEF_PATH
        self._coefficients: dict[str, dict[str, float]] = {}
        self._extended: dict[str, dict[str, dict[str, Any]]] = {}
        self._loaded: bool = False
        self._source: str = "unloaded"

    async def load(self) -> None:
        """Load coefficients from JSON file, falling back to defaults.

        Safe to call multiple times — re-reads the file each time to pick up
        fresh calibration runs.  Handles both plain float values and extended
        dicts with ``slope``, ``std_err``, ``r_squared``, etc.
        """
        loaded = self._read_file()
        if loaded is not None:
            self._coefficients, self._extended = self._parse_loaded(loaded)
            self._source = "file"
            logger.info(
                "Loaded calibration coefficients from %s (%d indicators)",
                self._coef_path, len(self._coefficients),
            )
        else:
            self._coefficients = {k: dict(v) for k, v in _DEFAULTS.items()}
            self._extended = {}
            self._source = "defaults"
            logger.info(
                "Using default calibration coefficients (%d indicators)",
                len(self._coefficients),
            )

        self._loaded = True

    def load_sync(self) -> None:
        """Synchronous version of load() for use in non-async contexts."""
        loaded = self._read_file()
        if loaded is not None:
            self._coefficients, self._extended = self._parse_loaded(loaded)
            self._source = "file"
        else:
            self._coefficients = {k: dict(v) for k, v in _DEFAULTS.items()}
            self._extended = {}
            self._source = "defaults"
        self._loaded = True

    def get(self, indicator: str, sentiment_metric: str) -> float:
        """Return the regression coefficient for *(indicator, sentiment_metric)*.

        Auto-loads defaults if load() has not been called yet.

        Args:
            indicator: Economic indicator name (e.g. ``"consumer_confidence"``).
            sentiment_metric: Sentiment variable (e.g. ``"negative_ratio"``).

        Returns:
            Regression coefficient (float). Returns 0.0 if no match found.
        """
        if not self._loaded:
            # Auto-load defaults synchronously on first access
            self.load_sync()

        indicator_coefs = self._coefficients.get(indicator, {})
        coef = indicator_coefs.get(sentiment_metric)
        if coef is None:
            # Try alias resolution (e.g. "gdp_growth" ↔ "gdp_growth_rate")
            alias = _INDICATOR_ALIASES.get(indicator)
            if alias:
                coef = self._coefficients.get(alias, {}).get(sentiment_metric)
        if coef is None:
            # Also check defaults (with alias fallback)
            coef = _DEFAULTS.get(indicator, {}).get(sentiment_metric)
            if coef is None:
                alias = _INDICATOR_ALIASES.get(indicator)
                if alias:
                    coef = _DEFAULTS.get(alias, {}).get(sentiment_metric)
        return float(coef) if coef is not None else 0.0

    def get_all(self, indicator: str) -> dict[str, float]:
        """Return all sentiment → coefficient mappings for an indicator.

        Args:
            indicator: Economic indicator name.

        Returns:
            Dict of {sentiment_metric → coefficient}. Empty dict if not found.
        """
        if not self._loaded:
            self.load_sync()

        # Merge defaults with loaded (loaded takes precedence)
        defaults = _DEFAULTS.get(indicator, {})
        loaded = self._coefficients.get(indicator, {})
        return {**defaults, **loaded}

    def get_all_by_sentiment(self, sentiment_metric: str) -> dict[str, float]:
        """Return all indicator → coefficient mappings for one sentiment metric.

        Inverts the normal (indicator → sentiment → coeff) lookup direction.
        Useful for sensitivity analysis that sweeps a single sentiment parameter.

        Args:
            sentiment_metric: Sentiment variable name (e.g. ``"negative_ratio"``).

        Returns:
            Dict of {indicator → coefficient}. Empty dict if not found.
        """
        if not self._loaded:
            self.load_sync()

        result: dict[str, float] = {}
        all_indicators = set(self._coefficients) | set(_DEFAULTS)
        for indicator in all_indicators:
            coef = self.get(indicator, sentiment_metric)
            if coef != 0.0:
                result[indicator] = coef
        return result

    def list_indicators(self) -> list[str]:
        """Return all known indicator names."""
        if not self._loaded:
            self.load_sync()
        all_indicators = set(self._coefficients) | set(_DEFAULTS)
        return sorted(all_indicators)

    def list_sentiment_metrics(self, indicator: str) -> list[str]:
        """Return all sentiment metrics for a given indicator."""
        coefs = self.get_all(indicator)
        return sorted(coefs)

    @property
    def source(self) -> str:
        """Where the current coefficients were loaded from."""
        return self._source

    @property
    def is_loaded(self) -> bool:
        """Whether coefficients have been loaded (from file or defaults)."""
        return self._loaded

    def to_dict(self) -> dict[str, Any]:
        """Return the full coefficient table as a plain dict."""
        if not self._loaded:
            self.load_sync()
        return {
            k: dict(v)
            for k, v in self._coefficients.items()
        }

    def get_extended(
        self, indicator: str, sentiment_metric: str,
    ) -> dict[str, Any]:
        """Return extended OLS stats for a coefficient pair.

        Keys may include: slope, intercept, r_squared, p_value, std_err,
        ci_lower, ci_upper, granger_p, adf_p.

        Args:
            indicator: Economic indicator name.
            sentiment_metric: Sentiment variable.

        Returns:
            Dict of extended stats, or empty dict if unavailable.
        """
        if not self._loaded:
            self.load_sync()
        return dict(self._extended.get(indicator, {}).get(sentiment_metric, {}))

    def get_std_err(self, indicator: str, sentiment_metric: str) -> float:
        """Return the OLS standard error for a coefficient pair.

        Returns 0.0 if not available.
        """
        ext = self.get_extended(indicator, sentiment_metric)
        val = ext.get("std_err", 0.0)
        return float(val) if val is not None else 0.0

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_loaded(
        data: dict,
    ) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, dict[str, Any]]]]:
        """Parse loaded JSON into slopes and extended stats.

        Handles two formats per sentiment_metric entry:
        - Plain float: the slope value directly.
        - Extended dict: ``{"slope": ..., "std_err": ..., ...}``.

        Returns:
            Tuple of (coefficients, extended) dicts.
        """
        coefficients: dict[str, dict[str, float]] = {}
        extended: dict[str, dict[str, dict[str, Any]]] = {}

        for indicator, metrics in data.items():
            if indicator.startswith("_") or not isinstance(metrics, dict):
                continue
            coefficients[indicator] = {}
            extended[indicator] = {}
            for sent_metric, value in metrics.items():
                if isinstance(value, dict) and "slope" in value:
                    coefficients[indicator][sent_metric] = float(value["slope"])
                    extended[indicator][sent_metric] = dict(value)
                elif isinstance(value, (int, float)):
                    coefficients[indicator][sent_metric] = float(value)

        return coefficients, extended

    def _read_file(self) -> dict | None:
        """Read and parse the calibration JSON file.

        Returns:
            Parsed dict, or None if file not found or invalid.
        """
        if not self._coef_path.exists():
            logger.debug(
                "Calibration file not found at %s — will use defaults", self._coef_path
            )
            return None

        try:
            raw = self._coef_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict):
                logger.warning("Calibration file has unexpected format — using defaults")
                return None
            return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read calibration file: %s — using defaults", exc)
            return None


# ---------------------------------------------------------------------------
# Module-level singleton for convenience
# ---------------------------------------------------------------------------

_global_instance: CalibratedCoefficients | None = None


def get_calibrated_coefficients() -> CalibratedCoefficients:
    """Return the module-level singleton CalibratedCoefficients instance.

    The instance is lazily created and auto-loaded with defaults.
    Call ``await instance.load()`` to refresh from the JSON file.
    """
    global _global_instance  # noqa: PLW0603
    if _global_instance is None:
        _global_instance = CalibratedCoefficients()
    return _global_instance
