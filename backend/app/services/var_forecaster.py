"""VAR (Vector Autoregression) multi-variable forecaster for MurmuraScope.

Implements Task 2.2: cross-indicator relationships such as
  HIBOR↑ → CCL↓,  unemployment↑ → consumer_confidence↓,  etc.

Used by TimeSeriesForecaster.forecast_multivariate() when ≥3 indicators in a
group each have ≥20 periods of history.

All public data structures are frozen (immutable) per project coding style.
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass

import numpy as np

from backend.app.models.forecast import ForecastPoint, ForecastResult
from backend.app.utils.logger import get_logger

logger = get_logger("var_forecaster")

# ---------------------------------------------------------------------------
# Optional statsmodels dependency
# ---------------------------------------------------------------------------

try:
    from statsmodels.tsa.api import VAR as _VAR_Model  # noqa: N811
    from statsmodels.tsa.vector_ar.vecm import VECM as _VECM_Model  # noqa: N811

    HAS_STATSMODELS = True
except ImportError:
    HAS_STATSMODELS = False
    logger.info("statsmodels not installed — VAR forecaster unavailable")

try:
    from statsmodels.tsa.stattools import kpss as _kpss_test

    HAS_KPSS = True
except ImportError:
    HAS_KPSS = False

# ---------------------------------------------------------------------------
# VAR group definitions
# ---------------------------------------------------------------------------

# Each group is a tuple of metric names that should be modelled together.
# Relationships captured:
#   Property group:    HIBOR ↑ → CCL ↓;  GDP growth ↑ → CCL ↑
#   Labour group:      unemployment ↑ → consumer_confidence ↓;
#                      GDP growth ↑ → unemployment ↓
#   Market group:      HIBOR ↑ → HSI ↓;  GDP growth ↑ → HSI ↑
VAR_GROUPS: dict[str, tuple[str, ...]] = {
    "property": ("hibor_1m", "ccl_index", "gdp_growth"),
    "labour": ("unemployment_rate", "consumer_confidence", "gdp_growth"),
    "market": ("hibor_1m", "hsi_level", "gdp_growth"),
}

# Minimum observations per series required to fit VAR
_MIN_VAR_POINTS = 20

# Maximum VAR lag order (keep small for short macro series)
_MAX_VAR_LAG = 4

# ---------------------------------------------------------------------------
# Stationarity pre-check (ADF + KPSS dual test)
# ---------------------------------------------------------------------------

_ADF_SIGNIFICANCE = 0.05
_KPSS_SIGNIFICANCE = 0.05
_MAX_DIFF_ORDER = 2


@dataclass(frozen=True)
class _StationarityInfo:
    """Per-metric stationarity check result (internal).

    Attributes:
        metric: Metric name.
        is_stationary: Whether the series is stationary after any needed differencing.
        diff_order: Differencing order applied (0, 1, or 2).
        adf_p: ADF test p-value at the final diff_order.
        kpss_p: KPSS test p-value at the final diff_order (None if unavailable).
    """

    metric: str
    is_stationary: bool
    diff_order: int
    adf_p: float
    kpss_p: float | None


def _check_stationarity(
    series: np.ndarray,
    metric_name: str,
) -> _StationarityInfo:
    """Check stationarity via ADF + KPSS dual test.

    Both tests must agree for a confident determination:
    - ADF rejects (p < 0.05) AND KPSS does NOT reject (p > 0.05) -> stationary
    - If non-stationary, try differencing and re-test (up to d=2)

    Returns:
        _StationarityInfo with (is_stationary, diff_order).
        (True, 0) if stationary in levels.
        (True, 1) if stationary after 1st differencing.
        (True, 2) if stationary after 2nd differencing.
        (False, 0) if still non-stationary after d=2.
    """
    from statsmodels.tsa.stattools import adfuller  # noqa: PLC0415

    def _is_stationary_at(arr: np.ndarray) -> tuple[bool, float, float | None]:
        """Run ADF + KPSS on *arr*. Returns (stationary, adf_p, kpss_p)."""
        if len(arr) < 8 or np.std(arr) == 0.0:
            return False, 1.0, None

        adf_result = adfuller(arr, autolag="AIC")
        adf_p = float(adf_result[1])
        adf_ok = adf_p < _ADF_SIGNIFICANCE

        kpss_p: float | None = None
        if HAS_KPSS:
            try:
                _, kpss_p_val, _, _ = _kpss_test(arr, regression="c", nlags="auto")
                kpss_p = float(kpss_p_val)
                kpss_ok = kpss_p > _KPSS_SIGNIFICANCE
                # Both must agree
                return adf_ok and kpss_ok, adf_p, kpss_p
            except Exception:
                logger.debug(
                    "KPSS test failed for %s — falling back to ADF only",
                    metric_name,
                )

        # ADF-only fallback
        return adf_ok, adf_p, kpss_p

    current = series.copy()
    last_adf_p: float = 1.0
    last_kpss_p: float | None = None

    for d in range(_MAX_DIFF_ORDER + 1):
        if d > 0:
            current = np.diff(current)
        if len(current) < 8:
            break

        stationary, last_adf_p, last_kpss_p = _is_stationary_at(current)
        if stationary:
            return _StationarityInfo(
                metric=metric_name,
                is_stationary=True,
                diff_order=d,
                adf_p=last_adf_p,
                kpss_p=last_kpss_p,
            )

    # Still non-stationary after max differencing
    return _StationarityInfo(
        metric=metric_name,
        is_stationary=False,
        diff_order=0,
        adf_p=last_adf_p,
        kpss_p=last_kpss_p,
    )


def _apply_differencing(data_matrix: np.ndarray, diff_order: int) -> np.ndarray:
    """Apply *diff_order* rounds of first-differencing along axis 0.

    Returns a new array (never mutates the input).
    """
    result = data_matrix
    for _ in range(diff_order):
        result = np.diff(result, axis=0)
    return result


def _invert_differencing(
    forecasted: np.ndarray,
    original_tail: np.ndarray,
    diff_order: int,
) -> np.ndarray:
    """Invert differencing on forecasted values using the original series tail.

    Args:
        forecasted: (horizon, K) array of forecasts in differenced space.
        original_tail: Tail of the original (undifferenced) series. Must have
            at least *diff_order* rows. Shape (>=diff_order, K).
        diff_order: Number of differencing rounds to undo.

    Returns:
        (horizon, K) array of forecasts in level space.
    """
    if diff_order == 0:
        return forecasted

    # Build the integration anchors from the original data tail
    # For d=1: anchor = last original value
    # For d=2: we need to undo two levels of cumsum
    result = forecasted.copy()
    # We need d rows from the tail for anchoring
    anchors = original_tail[-diff_order:]  # shape (diff_order, K)

    for d_inv in range(diff_order):
        # Undo one level of differencing: cumulative sum anchored to prior level
        # The anchor for this inversion is the last value of the series at the
        # current differencing level. For the first inversion (innermost diff),
        # we use the diff^(diff_order-1) of the original tail.
        if diff_order == 1:
            anchor_row = original_tail[-1]  # shape (K,)
        elif diff_order == 2 and d_inv == 0:
            # First inversion: anchor is last first-difference of original
            anchor_row = original_tail[-1] - original_tail[-2]  # shape (K,)
        else:
            # Second inversion (d_inv=1, diff_order=2): anchor is last level
            anchor_row = original_tail[-1]  # shape (K,)

        level = np.empty_like(result)
        prev = anchor_row
        for h in range(result.shape[0]):
            prev = prev + result[h]
            level[h] = prev
        result = level

    return result


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VARForecastResult:
    """Multivariate forecast for a VAR group.

    Attributes:
        group: VAR group name (e.g. ``"property"``).
        metrics: Ordered list of metric names in this group.
        forecasts: Mapping metric → ForecastResult (one per metric).
        lag_order: Lag order selected by AIC.
        n_obs: Number of observations used for training.
        diagnostics: Model diagnostics (cointegration, stability, etc.).
    """

    group: str
    metrics: tuple[str, ...]
    forecasts: dict[str, ForecastResult]
    lag_order: int
    n_obs: int
    diagnostics: dict = dataclasses.field(default_factory=dict)


# ---------------------------------------------------------------------------
# VARForecaster
# ---------------------------------------------------------------------------


class VARForecaster:
    """Fit a VAR model for a set of related HK economic indicators.

    Usage::

        var = VARForecaster()
        result = var.forecast_group(
            group_name="property",
            series={
                "hibor_1m": [("2020-Q1", 0.03), ...],
                "ccl_index": [("2020-Q1", 155.0), ...],
                "gdp_growth": [("2020-Q1", 0.025), ...],
            },
            horizon=4,
        )
    """

    def forecast_group(
        self,
        group_name: str,
        series: dict[str, list[tuple[str, float]]],
        horizon: int = 4,
    ) -> VARForecastResult | None:
        """Fit VAR on *series* and return multivariate forecasts.

        Returns ``None`` if VAR is unavailable or insufficient data.
        All series must have the same period labels and ≥20 observations.

        Args:
            group_name: Key from VAR_GROUPS (used for logging + result label).
            series: Mapping metric name → sorted list of (period, value) pairs.
            horizon: Periods ahead to forecast (1–24).

        Returns:
            VARForecastResult with per-metric ForecastResult objects, or None.
        """
        if not HAS_STATSMODELS:
            logger.debug("VAR unavailable — statsmodels not installed")
            return None

        horizon = max(1, min(horizon, 24))

        # Align and validate series lengths
        aligned = self._align_series(series)
        if aligned is None:
            return None

        metrics_order, data_matrix, period_labels = aligned
        n_obs = data_matrix.shape[0]

        if n_obs < _MIN_VAR_POINTS:
            logger.debug(
                "VAR skipped for group=%s: only %d obs (need %d)",
                group_name, n_obs, _MIN_VAR_POINTS,
            )
            return None

        # ----- Stationarity pre-check (ADF + KPSS) -----
        stationarity_infos: list[_StationarityInfo] = []
        for k_idx, metric in enumerate(metrics_order):
            info = _check_stationarity(data_matrix[:, k_idx], metric)
            stationarity_infos.append(info)
            logger.debug(
                "Stationarity %s: stationary=%s d=%d adf_p=%.4f kpss_p=%s",
                metric, info.is_stationary, info.diff_order,
                info.adf_p, info.kpss_p,
            )

        any_non_stationary = any(
            info.diff_order > 0 or not info.is_stationary
            for info in stationarity_infos
        )

        var_diagnostics: dict = {
            "stationarity": {
                info.metric: {
                    "is_stationary": info.is_stationary,
                    "diff_order": info.diff_order,
                    "adf_p": round(info.adf_p, 6),
                    "kpss_p": round(info.kpss_p, 6) if info.kpss_p is not None else None,
                }
                for info in stationarity_infos
            },
        }

        # ----- Johansen cointegration test -----
        # Run on ORIGINAL (undifferenced) data. Cointegration is a property
        # of I(1) series sharing a long-run equilibrium; differencing first
        # would destroy that relationship.
        is_cointegrated = False
        if any_non_stationary:
            try:
                from statsmodels.tsa.vector_ar.vecm import coint_johansen  # noqa: PLC0415
                johansen_result = coint_johansen(data_matrix, det_order=0, k_ar_diff=1)
                trace_stats = johansen_result.lr1.tolist()
                crit_5pct = johansen_result.cvt[:, 1].tolist()
                is_cointegrated = any(t > c for t, c in zip(trace_stats, crit_5pct))
                var_diagnostics["johansen_cointegrated"] = is_cointegrated
                var_diagnostics["johansen_trace_stats"] = [round(t, 4) for t in trace_stats]
                var_diagnostics["johansen_crit_5pct"] = [round(c, 4) for c in crit_5pct]
                if is_cointegrated:
                    coint_rank = sum(
                        1 for t, c in zip(trace_stats, crit_5pct) if t > c
                    )
                    # Clamp rank to [1, K-1] — full rank means no cointegration
                    n_vars = len(metrics_order)
                    if coint_rank >= n_vars:
                        is_cointegrated = False
                        var_diagnostics["johansen_cointegrated"] = False
                        logger.info(
                            "VAR group=%s: Johansen full rank (%d/%d) — "
                            "treating as stationary, no cointegration",
                            group_name, coint_rank, n_vars,
                        )
                    else:
                        var_diagnostics["coint_rank"] = coint_rank
                        logger.info(
                            "VAR group=%s: Johansen test indicates cointegration "
                            "(rank=%d), fitting VECM on original data",
                            group_name, coint_rank,
                        )
            except Exception as exc:
                logger.debug("Johansen test skipped for group=%s: %s", group_name, exc)
                var_diagnostics["johansen_cointegrated"] = None
        else:
            var_diagnostics["johansen_cointegrated"] = None

        # ----- Model selection based on stationarity + cointegration -----
        # Decision tree:
        #   1. Cointegrated -> VECM on original data (VECM handles I(1) internally)
        #   2. Non-stationary, not cointegrated -> difference, then VAR
        #   3. Already stationary -> VAR on original data
        original_data_matrix = data_matrix
        group_diff_order = 0

        if is_cointegrated:
            # VECM on original (undifferenced) data — it handles differencing
            # internally via the error correction term.
            group_diff_order = 0
            var_diagnostics["group_diff_order"] = 0

            coint_rank = var_diagnostics.get("coint_rank", 1)
            try:
                try:
                    forecasts = self._fit_vecm_and_forecast(
                        group_name=group_name,
                        metrics_order=metrics_order,
                        data_matrix=data_matrix,
                        period_labels=period_labels,
                        horizon=horizon,
                        coint_rank=coint_rank,
                    )
                    var_diagnostics["model_type"] = "VECM"
                except Exception as vecm_exc:
                    logger.warning(
                        "VECM failed for group=%s (rank=%d): %s — "
                        "falling back to differenced VAR",
                        group_name, coint_rank, vecm_exc,
                    )
                    var_diagnostics["vecm_fallback_reason"] = str(vecm_exc)
                    # Fall back to differenced VAR
                    group_diff_order = 1
                    diff_data = _apply_differencing(data_matrix, 1)
                    if diff_data.shape[0] < _MIN_VAR_POINTS:
                        return None
                    forecasts = self._fit_and_forecast(
                        group_name=group_name,
                        metrics_order=metrics_order,
                        data_matrix=diff_data,
                        period_labels=period_labels,
                        horizon=horizon,
                    )
                    var_diagnostics["model_type"] = "VAR"
                    var_diagnostics["group_diff_order"] = 1
            except Exception as exc:
                logger.warning(
                    "VAR fitting failed for group=%s: %s", group_name, exc
                )
                return None
        else:
            # Non-cointegrated: apply differencing if needed
            if any_non_stationary:
                group_diff_order = max(
                    (info.diff_order for info in stationarity_infos if info.is_stationary),
                    default=0,
                )
                # If no series became stationary, use d=1 as best-effort
                if all(not info.is_stationary for info in stationarity_infos):
                    group_diff_order = 1
                    logger.warning(
                        "VAR group=%s: all series non-stationary after d=%d — "
                        "applying d=1 as best-effort fallback",
                        group_name, _MAX_DIFF_ORDER,
                    )

            var_diagnostics["group_diff_order"] = group_diff_order

            if group_diff_order > 0:
                data_matrix = _apply_differencing(data_matrix, group_diff_order)
                n_obs = data_matrix.shape[0]
                logger.info(
                    "VAR group=%s: differenced d=%d, %d obs remaining",
                    group_name, group_diff_order, n_obs,
                )
                if n_obs < _MIN_VAR_POINTS:
                    logger.debug(
                        "VAR skipped for group=%s after differencing: "
                        "only %d obs (need %d)",
                        group_name, n_obs, _MIN_VAR_POINTS,
                    )
                    return None

            try:
                forecasts = self._fit_and_forecast(
                    group_name=group_name,
                    metrics_order=metrics_order,
                    data_matrix=data_matrix,
                    period_labels=period_labels,
                    horizon=horizon,
                )
                var_diagnostics["model_type"] = "VAR"
            except Exception as exc:
                logger.warning(
                    "VAR fitting failed for group=%s: %s", group_name, exc
                )
                return None

        # Invert differencing on forecasted values to get level forecasts
        if group_diff_order > 0:
            forecasts = _invert_forecast_differencing(
                forecasts=forecasts,
                metrics_order=metrics_order,
                original_data=original_data_matrix,
                diff_order=group_diff_order,
            )

        # VAR stability check — unstable model means unreliable forecasts
        is_stable = getattr(self, "_last_is_stable", True)
        var_diagnostics["is_stable"] = is_stable
        if not is_stable:
            logger.warning(
                "VAR group=%s is UNSTABLE — forecasts may be unreliable, returning None",
                group_name,
            )
            return None

        lag_order = getattr(self, "_last_lag_order", 1)
        return VARForecastResult(
            group=group_name,
            metrics=tuple(metrics_order),
            forecasts=forecasts,
            lag_order=lag_order,
            n_obs=n_obs,
            diagnostics=var_diagnostics,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _align_series(
        self,
        series: dict[str, list[tuple[str, float]]],
    ) -> tuple[list[str], np.ndarray, list[str]] | None:
        """Return (metrics_order, data_matrix, common_periods) or None.

        Finds the common period labels across all metrics, orders the data
        chronologically, and returns a (T, K) numpy array.
        """
        if not series:
            return None

        # Collect sets of periods per metric
        period_sets: list[set[str]] = [
            {p for p, _ in vals} for vals in series.values()
        ]
        # Intersect to find common periods
        common_periods: set[str] = period_sets[0].copy()
        for ps in period_sets[1:]:
            common_periods &= ps

        if not common_periods:
            logger.debug("VAR: no common periods across series")
            return None

        # Sort periods (lexicographic works for 'YYYY-QN' and 'YYYY' labels)
        sorted_periods = sorted(common_periods)
        metrics_order = list(series.keys())

        rows: list[list[float]] = []
        for period in sorted_periods:
            row: list[float] = []
            for metric in metrics_order:
                lookup = {p: v for p, v in series[metric]}
                val = lookup.get(period)
                if val is None:
                    break
                row.append(float(val))
            else:
                rows.append(row)

        if not rows:
            return None

        data_matrix = np.array(rows, dtype=np.float64)  # shape (T, K)
        return metrics_order, data_matrix, sorted_periods

    def _fit_and_forecast(
        self,
        group_name: str,
        metrics_order: list[str],
        data_matrix: np.ndarray,
        period_labels: list[str],
        horizon: int,
    ) -> dict[str, ForecastResult]:
        """Fit VAR, select lag by AIC, and produce per-metric ForecastResults."""
        from statsmodels.tsa.api import VAR as _VAR_Model  # noqa: N811, PLC0415

        model = _VAR_Model(data_matrix)

        # Select lag order via AIC, bounded to avoid over-fitting short series
        n_obs = data_matrix.shape[0]
        max_lag = min(_MAX_VAR_LAG, (n_obs - 1) // (len(metrics_order) + 1))
        max_lag = max(max_lag, 1)

        try:
            lag_results = model.select_order(maxlags=max_lag)
            lag_order = lag_results.selected_orders['aic']
        except Exception:
            lag_order = 1

        lag_order = max(1, lag_order)
        self._last_lag_order = lag_order  # stash for result

        fitted = model.fit(lag_order)
        logger.info(
            "VAR group=%s lag=%d AIC=%.2f",
            group_name, lag_order, fitted.aic,
        )

        # Stability check — store for caller to inspect
        try:
            self._last_is_stable = bool(fitted.is_stable())
        except Exception:
            self._last_is_stable = True  # assume stable if check fails

        # Point forecasts (shape: horizon × K)
        fc_mean = fitted.forecast(data_matrix[-lag_order:], steps=horizon)

        # Forecast error variance → confidence intervals
        # sigma_u = fitted.sigma_u is the innovation covariance (K × K)
        sigma_u = fitted.sigma_u  # (K, K)

        last_label = period_labels[-1]
        next_labels = _next_period_labels(last_label, horizon)

        forecasts: dict[str, ForecastResult] = {}
        for k_idx, metric in enumerate(metrics_order):
            # Build up variance of h-step forecast error (approximate)
            variance_h = np.zeros(horizon, dtype=np.float64)
            msi_matrices = fitted.mse(horizon)  # (horizon, K, K)
            for h in range(horizon):
                variance_h[h] = float(msi_matrices[h][k_idx, k_idx])

            points: list[ForecastPoint] = []
            for h in range(horizon):
                pt_val = float(fc_mean[h, k_idx])
                std_h = float(np.sqrt(max(variance_h[h], 0.0)))

                spread_80 = std_h * 1.28
                spread_95 = std_h * 1.96

                # Floor to 1% of abs value
                floor = abs(pt_val) * 0.01 if pt_val != 0 else 1e-6
                spread_80 = max(spread_80, floor)
                spread_95 = max(spread_95, floor * 1.5)

                points.append(ForecastPoint(
                    period=next_labels[h],
                    value=round(pt_val, 6),
                    lower_80=round(pt_val - spread_80, 6),
                    upper_80=round(pt_val + spread_80, 6),
                    lower_95=round(pt_val - spread_95, 6),
                    upper_95=round(pt_val + spread_95, 6),
                ))

            forecasts[metric] = ForecastResult(
                metric=metric,
                horizon=horizon,
                points=points,
                model_used=f"VAR({lag_order})",
                fit_quality=float(fitted.aic),
            )

        return forecasts

    def _fit_vecm_and_forecast(
        self,
        group_name: str,
        metrics_order: list[str],
        data_matrix: np.ndarray,
        period_labels: list[str],
        horizon: int,
        coint_rank: int,
    ) -> dict[str, ForecastResult]:
        """Fit VECM and produce per-metric ForecastResults.

        Uses the cointegration rank from the Johansen test to fit a VECM
        (Vector Error Correction Model), which is the appropriate model when
        series are cointegrated (share a long-run equilibrium).

        Args:
            group_name: VAR group name for logging.
            metrics_order: Ordered list of metric names.
            data_matrix: (T, K) array of observed values.
            period_labels: Period labels for the observations.
            horizon: Forecast steps ahead.
            coint_rank: Cointegration rank from Johansen test.

        Returns:
            Mapping metric name -> ForecastResult.
        """
        n_obs = data_matrix.shape[0]
        n_vars = len(metrics_order)

        # Select lag order (for differenced series), bounded to avoid overfitting
        max_lag = min(_MAX_VAR_LAG, (n_obs - 1) // (n_vars + 1))
        max_lag = max(max_lag, 2)
        lag_diff = max(max_lag - 1, 1)

        # Clamp coint_rank to valid range [1, K-1]
        coint_rank = max(1, min(coint_rank, n_vars - 1))

        vecm = _VECM_Model(data_matrix, k_ar_diff=lag_diff, coint_rank=coint_rank, deterministic="ci")
        fitted = vecm.fit()

        self._last_lag_order = lag_diff + 1  # effective lag in levels
        self._last_is_stable = True  # VECM stability assumed if fit succeeds

        logger.info(
            "VECM group=%s lag_diff=%d coint_rank=%d",
            group_name, lag_diff, coint_rank,
        )

        # Point forecasts: shape (horizon, K)
        fc_mean = fitted.predict(steps=horizon)

        # Forecast error variance from innovation covariance
        sigma_u = fitted.sigma_u  # (K, K)

        last_label = period_labels[-1]
        next_labels = _next_period_labels(last_label, horizon)

        forecasts: dict[str, ForecastResult] = {}
        for k_idx, metric in enumerate(metrics_order):
            innovation_var = float(sigma_u[k_idx, k_idx])

            points: list[ForecastPoint] = []
            for h in range(horizon):
                pt_val = float(fc_mean[h, k_idx])
                # Variance grows approximately linearly with horizon
                std_h = float(np.sqrt(max(innovation_var * (h + 1), 0.0)))

                spread_80 = std_h * 1.28
                spread_95 = std_h * 1.96

                # Floor to 1% of absolute value
                floor = abs(pt_val) * 0.01 if pt_val != 0 else 1e-6
                spread_80 = max(spread_80, floor)
                spread_95 = max(spread_95, floor * 1.5)

                points.append(ForecastPoint(
                    period=next_labels[h],
                    value=round(pt_val, 6),
                    lower_80=round(pt_val - spread_80, 6),
                    upper_80=round(pt_val + spread_80, 6),
                    lower_95=round(pt_val - spread_95, 6),
                    upper_95=round(pt_val + spread_95, 6),
                ))

            forecasts[metric] = ForecastResult(
                metric=metric,
                horizon=horizon,
                points=points,
                model_used=f"VECM(lag={lag_diff + 1},r={coint_rank})",
                fit_quality=0.0,  # VECM has no single AIC equivalent
                diagnostics={
                    "model_type": "VECM",
                    "coint_rank": coint_rank,
                    "lag_diff": lag_diff,
                },
            )

        return forecasts


# ---------------------------------------------------------------------------
# Differencing inversion for forecasts
# ---------------------------------------------------------------------------


def _invert_forecast_differencing(
    forecasts: dict[str, ForecastResult],
    metrics_order: list[str],
    original_data: np.ndarray,
    diff_order: int,
) -> dict[str, ForecastResult]:
    """Invert differencing on all ForecastResult point values.

    Reconstructs level-space forecasts from differenced-space forecasts
    using the tail of the original undifferenced data as anchors.

    Returns a new dict of ForecastResult objects (immutable — no mutation).
    """
    if diff_order == 0:
        return forecasts

    # Build a (horizon, K) matrix of differenced forecasts
    first_key = metrics_order[0]
    horizon = len(forecasts[first_key].points)
    n_metrics = len(metrics_order)

    diff_fc = np.zeros((horizon, n_metrics), dtype=np.float64)
    for k_idx, metric in enumerate(metrics_order):
        for h, pt in enumerate(forecasts[metric].points):
            diff_fc[h, k_idx] = pt.value

    # Invert to level space
    level_fc = _invert_differencing(diff_fc, original_data, diff_order)

    # Rebuild ForecastResult objects with corrected values and intervals
    new_forecasts: dict[str, ForecastResult] = {}
    for k_idx, metric in enumerate(metrics_order):
        old_result = forecasts[metric]
        new_points: list[ForecastPoint] = []
        for h, old_pt in enumerate(old_result.points):
            # Shift intervals by the same offset as the point value
            offset = level_fc[h, k_idx] - old_pt.value
            new_points.append(ForecastPoint(
                period=old_pt.period,
                value=round(level_fc[h, k_idx], 6),
                lower_80=round(old_pt.lower_80 + offset, 6),
                upper_80=round(old_pt.upper_80 + offset, 6),
                lower_95=round(old_pt.lower_95 + offset, 6),
                upper_95=round(old_pt.upper_95 + offset, 6),
            ))
        new_forecasts[metric] = ForecastResult(
            metric=old_result.metric,
            horizon=old_result.horizon,
            points=new_points,
            model_used=old_result.model_used,
            fit_quality=old_result.fit_quality,
            diagnostics=old_result.diagnostics,
        )

    return new_forecasts


# ---------------------------------------------------------------------------
# Period label utility (duplicated here to avoid circular import)
# ---------------------------------------------------------------------------


def _next_period_labels(last_period: str, horizon: int) -> list[str]:
    """Generate *horizon* period labels after *last_period* (quarterly/annual)."""
    labels: list[str] = []
    parts = last_period.split("-")
    if len(parts) == 2 and parts[1].startswith("Q"):
        try:
            base_year = int(parts[0])
            base_q = int(parts[1][1])
            for i in range(1, horizon + 1):
                total_q = base_q - 1 + i
                year = base_year + total_q // 4
                q = (total_q % 4) + 1
                labels.append(f"{year}-Q{q}")
            return labels
        except (ValueError, IndexError):
            pass
    if len(parts) == 1:
        try:
            base_year = int(parts[0])
            return [str(base_year + i) for i in range(1, horizon + 1)]
        except ValueError:
            pass
    return [f"t+{i}" for i in range(1, horizon + 1)]
