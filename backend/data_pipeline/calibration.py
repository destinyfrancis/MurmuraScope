"""Calibration Pipeline for MurmuraScope.

Fits OLS regression coefficients mapping social sentiment ratios to economic
indicator changes. Outputs calibration_coefficients.json which is consumed by
CalibratedCoefficients at runtime.

Usage::

    pipeline = CalibrationPipeline()
    coefficients = await pipeline.run_calibration()
    # → writes data/calibration_coefficients.json
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("calibration")

# ---------------------------------------------------------------------------
# Optional scipy dependency
# ---------------------------------------------------------------------------

try:
    from scipy import stats as scipy_stats

    HAS_SCIPY = True
    logger.info("scipy available — OLS regression enabled")
except ImportError:
    HAS_SCIPY = False
    logger.info("scipy not installed — using numpy lstsq fallback for OLS")

try:
    from statsmodels.tsa.stattools import adfuller, grangercausalitytests

    HAS_STATSMODELS = True
except ImportError:
    HAS_STATSMODELS = False

try:
    from statsmodels.tsa.stattools import kpss as _kpss_test

    HAS_KPSS = True
except ImportError:
    HAS_KPSS = False

# ---------------------------------------------------------------------------
# Paths & Constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_OUTPUT_PATH = _PROJECT_ROOT / "data" / "calibration_coefficients.json"

# Minimum number of (x, y) pairs needed for a reliable OLS fit
_MIN_REGRESSION_POINTS = 6

# FDR-corrected p-value threshold (Benjamini-Hochberg).
_P_THRESHOLD_RAW = 0.05
_R_SQUARED_THRESHOLD = 0.30

# Sentiment metrics extracted from social_sentiment table.
# Actual schema columns: positive_ratio, negative_ratio, neutral_ratio,
# thread_count, total_engagement. Only use existing columns.
_SENTIMENT_METRICS = ("positive_ratio", "negative_ratio", "neutral_ratio")

# Economic indicator → change variable mappings.
# Only reference sentiment metrics that exist in social_sentiment table.
_INDICATOR_PAIRS: list[tuple[str, str, str]] = [
    # (sentiment_metric, economic_category, economic_metric)
    ("negative_ratio", "employment", "unemployment_rate"),
    ("negative_ratio", "sentiment", "consumer_confidence"),
    ("positive_ratio", "sentiment", "consumer_confidence"),
    ("negative_ratio", "property", "price_index_all_classes"),
    ("positive_ratio", "gdp", "gdp_growth_rate"),
    ("negative_ratio", "gdp", "gdp_growth_rate"),
    ("negative_ratio", "interest_rate", "hibor_1m"),
    ("positive_ratio", "finance", "hsi_level"),
    ("negative_ratio", "finance", "hsi_level"),
    ("negative_ratio", "population", "net_migration"),
    ("negative_ratio", "retail_tourism", "retail_sales_index"),
    ("negative_ratio", "retail_tourism", "tourist_arrivals"),
    ("negative_ratio", "price_index", "cpi_yoy"),
]

# Fallback hardcoded coefficients (used when no data or scipy unavailable).
# Only references sentiment metrics that exist in social_sentiment table
# (positive_ratio, negative_ratio, neutral_ratio).
_FALLBACK_COEFFICIENTS: dict[str, dict[str, float]] = {
    "consumer_confidence": {"negative_ratio": -0.3, "positive_ratio": 0.2},
    "gdp_growth_rate": {"negative_ratio": -0.001, "positive_ratio": 0.0008},
    "unemployment_rate": {"negative_ratio": 0.0008},
    "price_index_all_classes": {"negative_ratio": -0.001},
    "net_migration": {"negative_ratio": -100},
    "hibor_1m": {"negative_ratio": 0.0001},
    "hsi_level": {"positive_ratio": 50.0, "negative_ratio": -80.0},
    "retail_sales_index": {"negative_ratio": -0.5},
    "tourist_arrivals": {"negative_ratio": -5000},
    "cpi_yoy": {"negative_ratio": 0.001},
}


# ---------------------------------------------------------------------------
# Benjamini-Hochberg FDR Correction
# ---------------------------------------------------------------------------


def _apply_fdr_correction(
    p_values: list[tuple[str, float]],
    alpha: float = 0.05,
) -> set[str]:
    """Apply Benjamini-Hochberg step-up FDR correction.

    Args:
        p_values: List of (pair_name, p_value) tuples.
        alpha: Family-wise error rate to control (default 0.05).

    Returns:
        Set of pair names that pass the BH-FDR correction.
    """
    if not p_values:
        return set()

    m = len(p_values)
    # Sort by p-value ascending
    sorted_pairs = sorted(p_values, key=lambda x: x[1])

    # Find the largest rank i where p_i <= (i / m) * alpha
    max_rank = 0
    for i, (_, p_val) in enumerate(sorted_pairs, start=1):
        threshold = (i / m) * alpha
        if p_val <= threshold:
            max_rank = i

    # All pairs with rank <= max_rank are significant
    significant = {sorted_pairs[j][0] for j in range(max_rank)}
    return significant


# ---------------------------------------------------------------------------
# CalibrationPipeline
# ---------------------------------------------------------------------------


class CalibrationPipeline:
    """OLS regression pipeline for sentiment → indicator calibration."""

    def __init__(self, output_path: Path | None = None) -> None:
        self._output_path = output_path or _OUTPUT_PATH

    async def run_calibration(self) -> dict[str, dict[str, float]]:
        """Run full calibration pipeline.

        1. Load aligned (sentiment, indicator) data from DB.
        2. Run OLS for each (sentiment_metric, indicator) pair.
        3. Merge with fallback defaults for any missing pairs.
        4. Write coefficients to JSON file.

        Returns:
            Nested dict: {indicator → {sentiment_metric → coefficient}}.
        """
        logger.info("Starting calibration pipeline")

        # Load raw data
        sentiment_series = await self._load_sentiment_series()
        indicator_series = await self._load_indicator_series()

        if not sentiment_series or not indicator_series:
            logger.warning("Insufficient data for calibration — using fallback coefficients")
            self._write_output(_FALLBACK_COEFFICIENTS)
            await self._persist_to_db(_FALLBACK_COEFFICIENTS)
            return _FALLBACK_COEFFICIENTS

        # Check for synthetic data
        synthetic_warning = False
        synthetic_pct_value = 1.0  # assume worst case until measured
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    "SELECT COUNT(*), SUM(CASE WHEN source = 'synthetic_historical' THEN 1 ELSE 0 END) "
                    "FROM social_sentiment"
                )
                row = await cursor.fetchone()
                if row and row[0] > 0:
                    synthetic_pct_value = (row[1] or 0) / row[0]
                    if synthetic_pct_value > 0.5:
                        logger.warning(
                            "%.0f%% of sentiment data is synthetic — coefficients unreliable",
                            synthetic_pct_value * 100,
                        )
                        synthetic_warning = True
                else:
                    synthetic_pct_value = 0.0
        except Exception:
            pass

        # Run stationarity tests (extract values from period-indexed tuples)
        stationarity_results: list[dict[str, Any]] = []
        for sent_metric in _SENTIMENT_METRICS:
            if sent_metric in sentiment_series:
                values = [v for _, v in sentiment_series[sent_metric]]
                stationarity_results.append(self._adf_test(values, sent_metric))

        # Run Granger causality tests (temporally aligned)
        granger_results: list[dict[str, Any]] = []
        for sent_metric, category, econ_metric in _INDICATOR_PAIRS:
            x_raw = sentiment_series.get(sent_metric, [])
            y_raw = indicator_series.get((category, econ_metric), [])
            if x_raw and y_raw:
                x_aligned, y_aligned = self._align_series_by_period(x_raw, y_raw)
                if x_aligned and y_aligned:
                    granger_result = self._granger_test(
                        x_aligned,
                        y_aligned,
                        f"{sent_metric} → {econ_metric}",
                    )
                    granger_results.append(granger_result)

        # Run OLS for each pair (collect all results, defer p-value filtering to FDR)
        all_ols_results: list[tuple[str, str, dict[str, Any]]] = []
        for sent_metric, category, econ_metric in _INDICATOR_PAIRS:
            x_raw = sentiment_series.get(sent_metric, [])
            y_raw = indicator_series.get((category, econ_metric), [])
            if x_raw and y_raw:
                x_aligned, y_aligned = self._align_series_by_period(x_raw, y_raw)
            else:
                x_aligned, y_aligned = [], []
            ols_result = self._run_ols_pair(
                x_aligned,
                y_aligned,
                f"{sent_metric} → {econ_metric}",
            )
            if ols_result is not None:
                all_ols_results.append((sent_metric, econ_metric, ols_result))

        # Apply Benjamini-Hochberg FDR correction across all OLS pairs
        p_value_pairs: list[tuple[str, float]] = [
            (f"{sm} → {em}", res.get("p_value", 1.0)) for sm, em, res in all_ols_results if "p_value" in res
        ]
        significant_pairs = _apply_fdr_correction(p_value_pairs, alpha=_P_THRESHOLD_RAW)

        fitted: dict[str, dict[str, float]] = {}
        fitted_details: dict[str, dict[str, dict[str, Any]]] = {}
        for sent_metric, econ_metric, ols_result in all_ols_results:
            pair_label = f"{sent_metric} → {econ_metric}"
            # Keep pairs that pass FDR, or those without p-value (numpy lstsq)
            if "p_value" in ols_result and pair_label not in significant_pairs:
                logger.info(
                    "OLS %s: p=%.4f — not significant after BH-FDR, using fallback",
                    pair_label,
                    ols_result.get("p_value", 1.0),
                )
                continue
            if econ_metric not in fitted:
                fitted[econ_metric] = {}
                fitted_details[econ_metric] = {}
            fitted[econ_metric][sent_metric] = ols_result["slope"]
            fitted_details[econ_metric][sent_metric] = ols_result

        # Merge with fallback defaults (fallback fills missing entries)
        merged = self._merge_with_fallback(fitted, _FALLBACK_COEFFICIENTS)

        # Build extended output: top-level entries include full OLS stats
        # (slope, intercept, r_squared, p_value, std_err, ci_lower, ci_upper,
        # granger_p, adf_p) when available; fallback entries keep only slope.
        granger_lookup: dict[str, float | None] = {}
        for gr in granger_results:
            label = gr.get("label", "")
            granger_lookup[label] = gr.get("p_value")

        adf_lookup: dict[str, float | None] = {}
        for ar in stationarity_results:
            adf_lookup[ar.get("metric", "")] = ar.get("p_value")

        extended_indicators: dict[str, Any] = {}
        for indicator in merged:
            extended_indicators[indicator] = {}
            for sent_metric, slope_val in merged[indicator].items():
                detail = fitted_details.get(indicator, {}).get(sent_metric)
                if detail is not None:
                    # Full OLS stats available
                    granger_key = f"{sent_metric} → {indicator}"
                    entry: dict[str, Any] = {
                        "slope": detail.get("slope", slope_val),
                        "intercept": detail.get("intercept", 0.0),
                        "r_squared": detail.get("r_squared", 0.0),
                        "p_value": detail.get("p_value", 1.0),
                        "std_err": detail.get("std_err", 0.0),
                        "ci_lower": detail.get("ci_lower", 0.0),
                        "ci_upper": detail.get("ci_upper", 0.0),
                        "granger_p": granger_lookup.get(granger_key),
                        "adf_p": adf_lookup.get(sent_metric),
                    }
                    extended_indicators[indicator][sent_metric] = entry
                else:
                    # Fallback — only slope known
                    extended_indicators[indicator][sent_metric] = slope_val

        # Build metadata
        result: dict[str, Any] = {
            "_meta": {
                "n_sentiment_periods": len(next(iter(sentiment_series.values()), [])),
                "calibrated_pairs": [f"{sm} → {em}" for (sm, _, em) in _INDICATOR_PAIRS],
                "method": "OLS" if HAS_SCIPY else "numpy_lstsq",
                "correction_method": "BH-FDR",
                "fdr_alpha": _P_THRESHOLD_RAW,
                "fdr_significant_pairs": sorted(significant_pairs),
                "r_squared_threshold": _R_SQUARED_THRESHOLD,
                "n_tests": len(_INDICATOR_PAIRS),
                "stationarity_tests": stationarity_results,
                "granger_tests": granger_results,
                "synthetic_data_warning": synthetic_warning,
                "synthetic_pct": round(synthetic_pct_value, 4),
            },
            **extended_indicators,
        }

        self._write_output(result)
        await self._persist_to_db(merged)
        logger.info(
            "Calibration complete — %d indicators fitted (BH-FDR alpha=%.2f, %d/%d significant, R²>%.2f), output: %s",
            len(fitted),
            _P_THRESHOLD_RAW,
            len(significant_pairs),
            len(p_value_pairs),
            _R_SQUARED_THRESHOLD,
            self._output_path,
        )
        return merged

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    async def _load_sentiment_series(
        self,
    ) -> dict[str, list[tuple[str, float]]]:
        """Load per-period sentiment ratios from social_sentiment table.

        Returns dict: {metric_name → [(period, value), ...]}, ordered by period.
        Period labels are preserved for temporal alignment with indicator series.
        """
        series: dict[str, list[tuple[str, float]]] = {m: [] for m in _SENTIMENT_METRICS}
        try:
            async with get_db() as db:
                # Check if table exists
                cursor = await db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='social_sentiment'"
                )
                if not await cursor.fetchone():
                    logger.warning("social_sentiment table not found — skipping sentiment load")
                    return {}

                # Only query columns that actually exist in social_sentiment:
                # positive_ratio, negative_ratio, neutral_ratio, thread_count,
                # total_engagement. Aggregate across categories per period.
                cursor = await db.execute(
                    """
                    SELECT period,
                           AVG(positive_ratio)  AS positive_ratio,
                           AVG(negative_ratio)  AS negative_ratio,
                           AVG(neutral_ratio)   AS neutral_ratio
                    FROM social_sentiment
                    GROUP BY period
                    ORDER BY period ASC
                    """
                )
                rows = await cursor.fetchall()

            for row in rows:
                period = str(row[0]) if row[0] else ""
                if not period:
                    continue
                for idx, col in enumerate(_SENTIMENT_METRICS):
                    val = row[idx + 1]  # +1 to skip period column
                    if val is not None:
                        try:
                            series[col].append((period, float(val)))
                        except (TypeError, ValueError):
                            pass

            logger.info(
                "Loaded sentiment series: %d periods",
                len(series.get("negative_ratio", [])),
            )
        except Exception:
            logger.exception("_load_sentiment_series failed")

        return {k: v for k, v in series.items() if v}

    async def _load_indicator_series(
        self,
    ) -> dict[tuple[str, str], list[tuple[str, float]]]:
        """Load economic indicators from hk_data_snapshots.

        hk_data_snapshots schema: category, metric, value, unit, period, source, source_url
        There is NO data_json column — values are stored in individual columns.

        Returns dict: {(category, metric) → [(period, value), ...]}, ordered by period ASC.
        Period labels are preserved for temporal alignment with sentiment series.
        """
        needed_categories = {cat for _, cat, _ in _INDICATOR_PAIRS}
        series: dict[tuple[str, str], list[tuple[str, float]]] = {}

        try:
            async with get_db() as db:
                cursor = await db.execute(
                    """
                    SELECT category, metric, period, value
                    FROM hk_data_snapshots
                    WHERE category IN ({})
                    ORDER BY category, metric, period ASC
                    """.format(",".join("?" * len(needed_categories))),
                    list(needed_categories),
                )
                rows = await cursor.fetchall()

            for row in rows:
                cat = str(row[0])
                metric_name = str(row[1])
                period = str(row[2]) if row[2] else ""
                value = row[3]
                if value is None or not period:
                    continue
                try:
                    key = (cat, metric_name)
                    if key not in series:
                        series[key] = []
                    series[key].append((period, float(value)))
                except (TypeError, ValueError):
                    pass

            # Warn about categories with zero data
            for cat in needed_categories:
                found = any(k[0] == cat for k in series)
                if not found:
                    logger.warning("Calibration: category '%s' has zero rows in hk_data_snapshots", cat)

        except Exception:
            logger.exception("_load_indicator_series failed")

        return series

    # ------------------------------------------------------------------
    # Regression
    # ------------------------------------------------------------------

    @staticmethod
    def _align_series_by_period(
        x_series: list[tuple[str, float]],
        y_series: list[tuple[str, float]],
    ) -> tuple[list[float], list[float]]:
        """Align two period-indexed series, keeping only overlapping periods.

        Returns two lists of equal length containing only values from periods
        present in BOTH series, ordered by period label.
        """
        x_by_period = {p: v for p, v in x_series}
        y_by_period = {p: v for p, v in y_series}
        common_periods = sorted(set(x_by_period) & set(y_by_period))
        x_aligned = [x_by_period[p] for p in common_periods]
        y_aligned = [y_by_period[p] for p in common_periods]
        return x_aligned, y_aligned

    @staticmethod
    def _adf_test(series: list[float], name: str) -> dict[str, Any]:
        """Run Augmented Dickey-Fuller stationarity test.

        Also runs KPSS as a complement when available. Both must agree
        for a confident stationarity determination:
        - ADF rejects (p < 0.05) AND KPSS does NOT reject (p > 0.05) → stationary
        - Otherwise → inconclusive or non-stationary
        """
        if not HAS_STATSMODELS or len(series) < 8:
            return {"metric": name, "p_value": None, "is_stationary": None, "skipped": True}
        try:
            result = adfuller(np.array(series), autolag="AIC")
            adf_p = float(result[1])
            adf_stationary = adf_p < 0.05

            # KPSS complement: null hypothesis is stationarity (opposite of ADF)
            kpss_p: float | None = None
            kpss_stationary: bool | None = None
            if HAS_KPSS:
                try:
                    kpss_stat, kpss_p_val, _, _ = _kpss_test(
                        np.array(series),
                        regression="c",
                        nlags="auto",
                    )
                    kpss_p = float(kpss_p_val)
                    # KPSS: fail to reject (p > 0.05) means stationary
                    kpss_stationary = kpss_p > 0.05
                except Exception:
                    logger.debug("KPSS test failed for %s — using ADF result only", name)

            # Both tests must agree for confident determination
            if kpss_stationary is not None:
                is_stationary = adf_stationary and kpss_stationary
            else:
                is_stationary = adf_stationary

            return {
                "metric": name,
                "adf_statistic": float(result[0]),
                "p_value": adf_p,
                "kpss_p": kpss_p,
                "is_stationary": is_stationary,
                "lags_used": int(result[2]),
            }
        except Exception:
            return {"metric": name, "p_value": None, "is_stationary": None, "error": True}

    @staticmethod
    def _granger_test(
        x_series: list[float],
        y_series: list[float],
        label: str,
        max_lag: int = 4,
    ) -> dict[str, Any]:
        """Run Granger causality test with pre-whitening.

        Both series are checked for stationarity via ADF before testing.
        Non-stationary series are first-differenced to ensure valid Granger
        test assumptions.
        """
        if not HAS_STATSMODELS:
            return {"label": label, "p_value": None, "skipped": True}

        n = min(len(x_series), len(y_series))
        if n < max_lag + 5:
            return {"label": label, "p_value": None, "insufficient_data": True}

        try:
            x_arr = np.array(x_series[:n], dtype=np.float64)
            y_arr = np.array(y_series[:n], dtype=np.float64)

            # Pre-whiten: difference non-stationary series before Granger test
            x_differenced = False
            y_differenced = False
            if len(x_arr) >= 8:
                try:
                    if adfuller(x_arr, autolag="AIC")[1] > 0.05:
                        x_arr = np.diff(x_arr)
                        x_differenced = True
                except Exception:
                    pass
            if len(y_arr) >= 8:
                try:
                    if adfuller(y_arr, autolag="AIC")[1] > 0.05:
                        y_arr = np.diff(y_arr)
                        y_differenced = True
                except Exception:
                    pass

            # Re-align after potentially asymmetric differencing
            min_len = min(len(x_arr), len(y_arr))
            x_arr = x_arr[-min_len:]
            y_arr = y_arr[-min_len:]

            if min_len < max_lag + 5:
                return {"label": label, "p_value": None, "insufficient_data": True}

            data = np.column_stack([y_arr, x_arr])
            results = grangercausalitytests(data, maxlag=max_lag, verbose=False)
            best_p = 1.0
            best_lag = 1
            for lag, test_result in results.items():
                p_val = test_result[0]["ssr_ftest"][1]
                if p_val < best_p:
                    best_p = p_val
                    best_lag = lag
            return {
                "label": label,
                "best_lag": best_lag,
                "p_value": float(best_p),
                "is_significant": best_p < 0.10,
                "x_differenced": x_differenced,
                "y_differenced": y_differenced,
            }
        except Exception:
            return {"label": label, "p_value": None, "error": True}

    @staticmethod
    def _run_ols_pair(
        x_series: list[float],
        y_series: list[float],
        label: str,
    ) -> dict[str, Any] | None:
        """Run OLS regression of y on x. Returns coefficient dict with stats.

        Uses first-differences to convert levels → changes (more stationary).
        Applies p-value and R² filtering: p < 0.05 AND R² > 0.05.
        Falls back to numpy lstsq if scipy is unavailable.

        Returns:
            Dict with slope, r_squared, p_value, std_err, ci_lower, ci_upper.
            Or None if insufficient data or fails quality checks.
        """
        n = min(len(x_series), len(y_series))
        if n < _MIN_REGRESSION_POINTS:
            logger.debug("Skipping OLS for %s: only %d points", label, n)
            return None

        x = np.array(x_series[:n], dtype=np.float64)
        y = np.array(y_series[:n], dtype=np.float64)

        # Only first-difference series that are non-stationary (ADF p > 0.05)
        if HAS_STATSMODELS and len(x) >= 8:
            try:
                x_adf_p = adfuller(x, autolag="AIC")[1]
            except Exception:
                x_adf_p = 1.0  # assume non-stationary on failure
            try:
                y_adf_p = adfuller(y, autolag="AIC")[1]
            except Exception:
                y_adf_p = 1.0
            dx = np.diff(x) if x_adf_p > 0.05 else x
            dy = np.diff(y) if y_adf_p > 0.05 else y
        else:
            # No statsmodels — fall back to differencing as before
            dx = np.diff(x)
            dy = np.diff(y)

        # Align lengths after potentially asymmetric differencing
        min_len = min(len(dx), len(dy))
        dx = dx[-min_len:]
        dy = dy[-min_len:]

        if len(dx) < _MIN_REGRESSION_POINTS - 1:
            return None

        try:
            if HAS_SCIPY:
                slope, intercept, r_value, p_value, std_err = scipy_stats.linregress(dx, dy)
                r_squared = r_value**2
                ci_lower = slope - 1.96 * std_err
                ci_upper = slope + 1.96 * std_err
                logger.debug(
                    "OLS %s: slope=%.4f r²=%.3f p=%.4f std_err=%.4f",
                    label,
                    slope,
                    r_squared,
                    p_value,
                    std_err,
                )

                # p-value filtering deferred to FDR correction in run_calibration()
                if r_squared < _R_SQUARED_THRESHOLD:
                    logger.info(
                        "OLS %s: R²=%.4f < %.2f — weak fit, using fallback",
                        label,
                        r_squared,
                        _R_SQUARED_THRESHOLD,
                    )
                    return None

                result = {
                    "slope": float(slope),
                    "intercept": float(intercept),
                    "r_squared": float(r_squared),
                    "p_value": float(p_value),
                    "std_err": float(std_err),
                    "ci_lower": float(ci_lower),
                    "ci_upper": float(ci_upper),
                    "n_observations": int(len(dx)),
                }
            else:
                A = np.column_stack([dx, np.ones_like(dx)])
                coeffs, _, _, _ = np.linalg.lstsq(A, dy, rcond=None)
                slope = coeffs[0]
                result = {"slope": float(slope), "n_observations": int(len(dx))}
                logger.debug("numpy OLS %s: slope=%.4f", label, slope)

            # Sanity check
            if math.isnan(result["slope"]) or math.isinf(result["slope"]) or abs(result["slope"]) > 1e6:
                logger.warning("OLS %s: unrealistic slope=%.4f, discarding", label, result["slope"])
                return None

            return result
        except Exception:
            logger.exception("OLS failed for %s", label)
            return None

    # ------------------------------------------------------------------
    # Merge & IO
    # ------------------------------------------------------------------

    @staticmethod
    def _merge_with_fallback(
        fitted: dict[str, dict[str, float]],
        fallback: dict[str, dict[str, float]],
    ) -> dict[str, dict[str, float]]:
        """Merge fitted coefficients with fallback defaults.

        Fitted coefficients take priority; fallback fills missing entries.
        """
        merged: dict[str, dict[str, float]] = {}
        all_indicators = set(fitted) | set(fallback)
        for indicator in all_indicators:
            if indicator.startswith("_"):
                continue
            merged[indicator] = {
                **fallback.get(indicator, {}),
                **fitted.get(indicator, {}),  # fitted overrides fallback
            }
        return merged

    def _write_output(self, coefficients: dict) -> None:
        """Write calibration coefficients to JSON file."""
        try:
            self._output_path.parent.mkdir(parents=True, exist_ok=True)
            self._output_path.write_text(
                json.dumps(coefficients, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info("Wrote calibration coefficients to %s", self._output_path)
        except Exception:
            logger.exception("Failed to write calibration output to %s", self._output_path)

    async def _persist_to_db(self, coefficients: dict[str, dict[str, float]]) -> None:
        """Persist calibration results to the calibration_results DB table.

        Schema: id, label, params_json, rmse, data_period, created_at
        Inserts one row per indicator so results are queryable per metric.
        """
        try:
            async with get_db() as db:
                # Ensure table exists (matches schema.sql definition)
                await db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS calibration_results (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        label TEXT NOT NULL,
                        params_json TEXT NOT NULL,
                        rmse REAL,
                        data_period TEXT,
                        created_at TEXT DEFAULT (datetime('now'))
                    )
                    """
                )
                for indicator, params in coefficients.items():
                    if indicator.startswith("_"):
                        continue
                    await db.execute(
                        """
                        INSERT INTO calibration_results (label, params_json, data_period)
                        VALUES (?, ?, ?)
                        """,
                        (
                            indicator,
                            json.dumps(params, ensure_ascii=False),
                            "1997-Q1:2025-Q4",
                        ),
                    )
                await db.commit()
            logger.info(
                "Persisted %d calibration results to DB",
                len([k for k in coefficients if not k.startswith("_")]),
            )
        except Exception:
            logger.exception("Failed to persist calibration results to DB")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


async def _run_cli() -> None:
    """Standalone calibration runner."""

    pipeline = CalibrationPipeline()
    coefficients = await pipeline.run_calibration()
    print(f"Calibration complete. Indicators: {list(coefficients)}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(_run_cli())
