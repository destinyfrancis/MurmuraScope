"""Retrospective Validation Pipeline for HKSimEngine.

Validates simulation macro predictions against historical HK data by:
1. Loading actual data from hk_data_snapshots for a date range
2. Generating predicted trajectories using calibrated coefficients
3. Computing accuracy metrics (directional accuracy, Pearson r, MAPE)
4. Persisting results to validation_runs table

Usage::

    validator = RetrospectiveValidator()
    results = await validator.validate("2020-Q1", "2020-Q4")
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import numpy as np

from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("retrospective_validator")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALIDATABLE_METRICS: frozenset[str] = frozenset({
    "ccl_index",
    "unemployment_rate",
    "hsi_level",
    "cpi_yoy",
    "gdp_growth",
    "consumer_confidence",
    "net_migration",
    "hibor_1m",
    "retail_sales_index",
    "tourist_arrivals",
})

# Maps metric names to (category, db_metric) pairs in hk_data_snapshots.
_METRIC_DB_MAP: dict[str, tuple[str, str]] = {
    "ccl_index": ("property", "ccl_index"),
    "unemployment_rate": ("employment", "unemployment_rate"),
    "hsi_level": ("finance", "hsi_level"),
    "cpi_yoy": ("price_index", "cpi_yoy"),
    "gdp_growth": ("gdp", "gdp_growth_rate"),
    "consumer_confidence": ("sentiment", "consumer_confidence"),
    "net_migration": ("population", "net_migration"),
    "hibor_1m": ("interest_rate", "hibor_1m"),
    "retail_sales_index": ("retail", "retail_sales_index"),
    "tourist_arrivals": ("tourism", "tourist_arrivals"),
}

# Simple per-quarter drift rates for trajectory generation.
# These represent typical quarterly change factors applied to the
# previous value to project the next quarter.
_DEFAULT_DRIFT: dict[str, float] = {
    "ccl_index": 0.0,
    "unemployment_rate": 0.0,
    "hsi_level": 0.0,
    "cpi_yoy": 0.0,
    "gdp_growth": 0.0,
    "consumer_confidence": 0.0,
    "net_migration": 0.0,
    "hibor_1m": 0.0,
    "retail_sales_index": 0.0,
    "tourist_arrivals": 0.0,
}

_PERIOD_PATTERN = re.compile(r"^\d{4}-Q[1-4]$")

MIN_METRICS_REQUIRED = 4


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationResult:
    """Result of validating one metric over a date range."""

    metric: str
    directional_accuracy: float
    pearson_r: float
    mape: float
    timing_offset_quarters: int
    n_observations: int
    period_start: str
    period_end: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_period(period: str) -> tuple[int, int]:
    """Parse '2020-Q1' into (2020, 1). Raises ValueError on bad format."""
    if not _PERIOD_PATTERN.match(period):
        raise ValueError(
            f"Invalid period format '{period}'. Expected YYYY-QN (e.g. 2020-Q1)."
        )
    year_str, q_str = period.split("-Q")
    return int(year_str), int(q_str)


def _period_to_sortable(period: str) -> int:
    """Convert '2020-Q1' to an integer for sorting: 2020*4 + 1 = 8081."""
    year, quarter = _parse_period(period)
    return year * 4 + quarter


def _enumerate_periods(start: str, end: str) -> list[str]:
    """Return a sorted list of quarterly periods from start to end (inclusive)."""
    s_year, s_q = _parse_period(start)
    e_year, e_q = _parse_period(end)

    periods: list[str] = []
    year, quarter = s_year, s_q
    while (year, quarter) <= (e_year, e_q):
        periods.append(f"{year}-Q{quarter}")
        quarter += 1
        if quarter > 4:
            quarter = 1
            year += 1
    return periods


def _find_best_timing_offset(
    predicted: list[float],
    actual: list[float],
    max_offset: int = 4,
) -> int:
    """Find the quarter offset that maximises Pearson r between predicted and actual.

    Returns 0 if no offset improves correlation, or if arrays are too short.
    """
    n = len(predicted)
    if n < 3:
        return 0

    best_offset = 0
    best_r = -2.0

    for offset in range(-max_offset, max_offset + 1):
        if offset >= 0:
            p_slice = predicted[:n - offset] if offset > 0 else predicted
            a_slice = actual[offset:] if offset > 0 else actual
        else:
            abs_off = abs(offset)
            p_slice = predicted[abs_off:]
            a_slice = actual[:n - abs_off]

        if len(p_slice) < 2 or len(a_slice) < 2:
            continue

        min_len = min(len(p_slice), len(a_slice))
        p_arr = np.array(p_slice[:min_len], dtype=np.float64)
        a_arr = np.array(a_slice[:min_len], dtype=np.float64)

        if np.std(p_arr) < 1e-12 or np.std(a_arr) < 1e-12:
            continue

        r = float(np.corrcoef(p_arr, a_arr)[0, 1])
        if not np.isnan(r) and r > best_r:
            best_r = r
            best_offset = offset

    return best_offset


# ---------------------------------------------------------------------------
# Main service
# ---------------------------------------------------------------------------


class RetrospectiveValidator:
    """Validates macro predictions against historical HK data."""

    async def validate(
        self,
        period_start: str,
        period_end: str,
        metrics: list[str] | None = None,
    ) -> list[ValidationResult]:
        """Run retrospective validation for a date range.

        Args:
            period_start: Start period (e.g. '2020-Q1').
            period_end: End period (e.g. '2020-Q4').
            metrics: Optional list of metrics to validate. If None, all
                available metrics are used.

        Returns:
            List of ValidationResult, one per successfully validated metric.

        Raises:
            ValueError: If period format is invalid or range is backwards.
        """
        # Validate period format
        _parse_period(period_start)
        _parse_period(period_end)

        if _period_to_sortable(period_start) >= _period_to_sortable(period_end):
            raise ValueError(
                f"period_start ({period_start}) must be before period_end ({period_end})."
            )

        # Filter to requested metrics
        target_metrics = (
            [m for m in metrics if m in VALIDATABLE_METRICS]
            if metrics is not None
            else sorted(VALIDATABLE_METRICS)
        )

        if not target_metrics:
            raise ValueError(
                f"No valid metrics requested. Available: {sorted(VALIDATABLE_METRICS)}"
            )

        # Load historical data
        historical = await self._load_historical_series(period_start, period_end)

        # Check minimum data threshold
        loadable_count = sum(
            1 for m in target_metrics if m in historical and len(historical[m]) >= 2
        )
        if loadable_count < MIN_METRICS_REQUIRED:
            logger.warning(
                "Insufficient historical data: %d metrics loadable (need %d)",
                loadable_count,
                MIN_METRICS_REQUIRED,
            )
            return []

        # Load calibrated coefficients for drift adjustment
        from backend.app.services.calibrated_coefficients import (  # noqa: PLC0415
            CalibratedCoefficients,
        )

        coefficients = CalibratedCoefficients()
        await coefficients.load()

        await self._ensure_table()

        results: list[ValidationResult] = []
        periods = _enumerate_periods(period_start, period_end)

        for metric in target_metrics:
            series = historical.get(metric)
            if not series or len(series) < 2:
                logger.debug("Skipping metric %s: insufficient data points", metric)
                continue

            actual_values = [v for _, v in series]
            predicted_values = self._generate_trajectory(
                metric, actual_values[0], len(actual_values), coefficients
            )

            accuracy_metrics = await self._compute_metrics(
                predicted_values, actual_values
            )

            timing_offset = _find_best_timing_offset(predicted_values, actual_values)

            result = ValidationResult(
                metric=metric,
                directional_accuracy=accuracy_metrics["directional_accuracy"],
                pearson_r=accuracy_metrics["pearson_r"],
                mape=accuracy_metrics["mape"],
                timing_offset_quarters=timing_offset,
                n_observations=len(actual_values),
                period_start=period_start,
                period_end=period_end,
            )
            results.append(result)

        if results:
            await self._persist_results(results)

        logger.info(
            "Retrospective validation complete: %d metrics validated for %s to %s",
            len(results),
            period_start,
            period_end,
        )
        return results

    async def _load_historical_series(
        self,
        period_start: str,
        period_end: str,
    ) -> dict[str, list[tuple[str, float]]]:
        """Load time series from hk_data_snapshots for the given period range.

        Returns:
            Dict mapping metric name to sorted list of (period, value) tuples.
        """
        periods = _enumerate_periods(period_start, period_end)
        if not periods:
            return {}

        placeholders = ",".join("?" for _ in periods)

        # Build (category, metric) pairs to query
        query_pairs: list[tuple[str, str, str]] = []
        for metric_name, (category, db_metric) in _METRIC_DB_MAP.items():
            query_pairs.append((metric_name, category, db_metric))

        result: dict[str, list[tuple[str, float]]] = {}

        try:
            async with get_db() as db:
                for metric_name, category, db_metric in query_pairs:
                    cursor = await db.execute(
                        f"""
                        SELECT period, value
                        FROM hk_data_snapshots
                        WHERE category = ? AND metric = ?
                          AND period IN ({placeholders})
                        ORDER BY period
                        """,
                        (category, db_metric, *periods),
                    )
                    rows = await cursor.fetchall()

                    if rows:
                        series: list[tuple[str, float]] = []
                        for row in rows:
                            period_val = (
                                row[0] if isinstance(row, (list, tuple)) else row["period"]
                            )
                            value = (
                                row[1] if isinstance(row, (list, tuple)) else row["value"]
                            )
                            series.append((str(period_val), float(value)))

                        # Sort by period
                        series.sort(key=lambda x: _period_to_sortable(x[0]))
                        result[metric_name] = series

        except Exception:
            logger.exception("_load_historical_series: DB read failed")

        logger.debug(
            "Loaded historical series: %d metrics with data",
            len(result),
        )
        return result

    async def _compute_metrics(
        self,
        predicted: list[float],
        actual: list[float],
    ) -> dict[str, float]:
        """Compute validation metrics between predicted and actual series.

        Returns dict with keys: directional_accuracy, pearson_r, mape.
        """
        n = min(len(predicted), len(actual))
        if n == 0:
            return {"directional_accuracy": 0.0, "pearson_r": 0.0, "mape": 0.0}

        p_arr = np.array(predicted[:n], dtype=np.float64)
        a_arr = np.array(actual[:n], dtype=np.float64)

        # Replace NaN/Inf with 0
        p_arr = np.where(np.isfinite(p_arr), p_arr, 0.0)
        a_arr = np.where(np.isfinite(a_arr), a_arr, 0.0)

        # --- Directional accuracy ---
        if n >= 2:
            p_diff = np.diff(p_arr)
            a_diff = np.diff(a_arr)
            # Count where both go same direction (or both zero)
            same_direction = np.sum(np.sign(p_diff) == np.sign(a_diff))
            directional_accuracy = float(same_direction / len(p_diff))
        else:
            directional_accuracy = 0.0

        # --- Pearson r ---
        if n >= 2 and np.std(p_arr) > 1e-12 and np.std(a_arr) > 1e-12:
            corr_matrix = np.corrcoef(p_arr, a_arr)
            pearson_r = float(corr_matrix[0, 1])
            if np.isnan(pearson_r):
                pearson_r = 0.0
        else:
            pearson_r = 0.0

        # --- MAPE ---
        # Avoid division by zero: skip actuals that are zero
        nonzero_mask = np.abs(a_arr) > 1e-12
        if np.any(nonzero_mask):
            abs_pct_errors = np.abs(
                (a_arr[nonzero_mask] - p_arr[nonzero_mask]) / a_arr[nonzero_mask]
            )
            mape = float(np.mean(abs_pct_errors))
        else:
            mape = 0.0

        return {
            "directional_accuracy": round(directional_accuracy, 4),
            "pearson_r": round(pearson_r, 4),
            "mape": round(mape, 4),
        }

    async def _persist_results(self, results: list[ValidationResult]) -> None:
        """Write validation results to the validation_runs table."""
        if not results:
            return

        await self._ensure_table()

        try:
            async with get_db() as db:
                for r in results:
                    await db.execute(
                        """
                        INSERT INTO validation_runs
                            (period_start, period_end, metric,
                             directional_accuracy, pearson_r, mape,
                             timing_offset_quarters, n_rounds)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            r.period_start,
                            r.period_end,
                            r.metric,
                            r.directional_accuracy,
                            r.pearson_r,
                            r.mape,
                            r.timing_offset_quarters,
                            r.n_observations,
                        ),
                    )
                await db.commit()

            logger.info("Persisted %d validation results", len(results))
        except Exception:
            logger.exception("_persist_results: DB write failed")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_trajectory(
        metric: str,
        initial_value: float,
        n_steps: int,
        coefficients: Any,
    ) -> list[float]:
        """Generate a predicted trajectory using calibrated drift coefficients.

        Uses a simple autoregressive model:
            value(t+1) = value(t) * (1 + drift)

        where drift is sourced from calibrated coefficients when available,
        falling back to the default drift rate for the metric.

        All sentiment→slope mappings for the indicator are retrieved via
        ``get_all()``, and the slope with the largest absolute value (most
        statistically significant relationship) is selected as the drift.
        """
        # Retrieve all sentiment→slope pairs for this indicator and select the
        # most significant one (largest |slope|).  Fall back to the per-metric
        # default when no non-zero coefficient exists.
        all_slopes: dict[str, float] = coefficients.get_all(metric)
        non_zero = {k: v for k, v in all_slopes.items() if abs(v) >= 1e-12}
        if non_zero:
            drift = max(non_zero.values(), key=abs)
        else:
            drift = _DEFAULT_DRIFT.get(metric, 0.0)

        trajectory: list[float] = [initial_value]
        current = initial_value

        for _ in range(n_steps - 1):
            current = current * (1.0 + drift)
            trajectory.append(round(current, 6))

        return trajectory

    @staticmethod
    async def _ensure_table() -> None:
        """Create validation_runs table if it does not exist."""
        try:
            async with get_db() as db:
                await db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS validation_runs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        period_start TEXT NOT NULL,
                        period_end TEXT NOT NULL,
                        metric TEXT NOT NULL,
                        directional_accuracy REAL,
                        pearson_r REAL,
                        mape REAL,
                        timing_offset_quarters INTEGER,
                        n_rounds INTEGER,
                        created_at TEXT DEFAULT (datetime('now'))
                    )
                    """
                )
                await db.commit()
        except Exception:
            logger.exception("_ensure_table: could not create validation_runs")
