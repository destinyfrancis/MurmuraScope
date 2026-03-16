"""VAR (Vector Autoregression) multi-variable forecaster for HKSimEngine.

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

        # Johansen cointegration test (informational — VAR still fitted)
        var_diagnostics: dict = {}
        try:
            from statsmodels.tsa.vector_ar.vecm import coint_johansen  # noqa: PLC0415
            johansen_result = coint_johansen(data_matrix, det_order=0, k_ar_diff=1)
            trace_stats = johansen_result.lr1.tolist()
            crit_5pct = johansen_result.cvt[:, 1].tolist()  # 5% critical values
            is_cointegrated = any(t > c for t, c in zip(trace_stats, crit_5pct))
            var_diagnostics["johansen_cointegrated"] = is_cointegrated
            var_diagnostics["johansen_trace_stats"] = [round(t, 4) for t in trace_stats]
            var_diagnostics["johansen_crit_5pct"] = [round(c, 4) for c in crit_5pct]
            if is_cointegrated:
                coint_rank = sum(
                    1 for t, c in zip(trace_stats, crit_5pct) if t > c
                )
                var_diagnostics["coint_rank"] = coint_rank
                logger.info(
                    "VAR group=%s: Johansen test indicates cointegration "
                    "(rank=%d), fitting VECM",
                    group_name, coint_rank,
                )
        except Exception as exc:
            logger.debug("Johansen test skipped for group=%s: %s", group_name, exc)
            var_diagnostics["johansen_cointegrated"] = None
            is_cointegrated = False

        try:
            if is_cointegrated:
                coint_rank = var_diagnostics.get("coint_rank", 1)
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
                        "VECM failed for group=%s (rank=%d): %s — falling back to VAR",
                        group_name, coint_rank, vecm_exc,
                    )
                    forecasts = self._fit_and_forecast(
                        group_name=group_name,
                        metrics_order=metrics_order,
                        data_matrix=data_matrix,
                        period_labels=period_labels,
                        horizon=horizon,
                    )
                    var_diagnostics["model_type"] = "VAR"
                    var_diagnostics["vecm_fallback_reason"] = str(vecm_exc)
            else:
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
