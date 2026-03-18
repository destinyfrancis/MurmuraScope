"""Time Series Forecaster for HKSimEngine.

Produces point forecasts with 80%/95% CI for HK economic indicators.

Tasks implemented:
  2.2 — VAR multivariate (see var_forecaster.py); forecast_multivariate()
  2.3 — Auto-model selection (AutoARIMA / AutoETS / Naive via holdout MAPE)
  2.4 — Rolling window backtesting via forecast_rolling()
  2.5 — Seasonality: per-metric season_length + Q1/Q4 adjustments
"""

from __future__ import annotations

import dataclasses
import math
from typing import Any

import numpy as np

from backend.app.models.forecast import ForecastPoint, ForecastResult
from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("time_series_forecaster")

# ---------------------------------------------------------------------------
# Optional statsforecast dependency
# ---------------------------------------------------------------------------

try:
    from statsforecast import StatsForecast
    from statsforecast.models import AutoARIMA, AutoETS, Naive

    HAS_STATSFORECAST = True
    logger.info("statsforecast available — AutoARIMA / AutoETS / Naive enabled")
except ImportError:
    HAS_STATSFORECAST = False
    logger.info("statsforecast not installed — using naive fallback forecaster")

# ---------------------------------------------------------------------------
# Metric → DB mapping
# ---------------------------------------------------------------------------

# Maps forecast metric names to (category, metric) tuples in hk_data_snapshots.
# Special case: "hsi_level" is stored in market_data (ticker="HSI", close col).
METRIC_DB_MAP: dict[str, tuple[str, str]] = {
    "ccl_index": ("property", "ccl_index"),
    "unemployment_rate": ("employment", "unemployment_rate"),
    "hsi_level": ("finance", "hsi_level"),
    "cpi_yoy": ("price_index", "cpi_yoy"),
    "gdp_growth": ("gdp", "gdp_growth_rate"),
    "consumer_confidence": ("sentiment", "consumer_confidence"),
    "hibor_1m": ("interest_rate", "hibor_1m"),
    "prime_rate": ("interest_rate", "prime_rate"),
    "net_migration": ("migration", "net_migration"),
    "retail_sales_index": ("retail", "retail_sales_index"),
    "tourist_arrivals": ("tourism", "tourist_arrivals"),
}

SUPPORTED_METRICS: frozenset[str] = frozenset(METRIC_DB_MAP)

_MIN_ARIMA_POINTS = 16       # min points for AutoARIMA
_MIN_VAR_POINTS: int = 32    # min points per series for VAR multivariate forecast
_MIN_AUTO_SELECT_POINTS = 24  # trigger auto-model selection
_HOLDOUT_WINDOW = 4           # holdout MAPE evaluation window
_DEFAULT_SEASON = 4           # default quarterly seasonal period

# Task 2.5 — season_length per metric (4=quarterly, 12=monthly)
_SEASONAL_METRICS: dict[str, int] = {
    "ccl_index": 4, "unemployment_rate": 4, "gdp_growth": 4,
    "consumer_confidence": 4, "hsi_level": 12, "cpi_yoy": 12,
    "hibor_1m": 4, "prime_rate": 4, "net_migration": 4,
    "retail_sales_index": 4, "tourist_arrivals": 4,
}

# Q1 Lunar New Year + Q4 year-end seasonal adjustments (metric, quarter, delta)
_SEASONAL_ADJUSTMENTS: dict[str, list[tuple[int, float]]] = {
    "ccl_index": [(1, -0.005)],
    "consumer_confidence": [(1, +0.015), (4, +0.010)],
    "unemployment_rate": [(4, -0.002)],
    "gdp_growth": [(4, +0.003)],
}

_DEFAULT_ROLLING_WINDOW = 24  # Task 2.4: quarters per rolling window

# ---------------------------------------------------------------------------
# Period label helpers
# ---------------------------------------------------------------------------


def _quarter_label(base_year: int, base_q: int, offset: int) -> str:
    """Return a quarter label like '2025-Q1' given a base quarter and offset."""
    total_q = base_q - 1 + offset  # 0-indexed
    year = base_year + total_q // 4
    q = (total_q % 4) + 1
    return f"{year}-Q{q}"


def _annual_label(base_year: int, offset: int) -> str:
    return str(base_year + offset)


def _parse_quarter(label: str) -> tuple[int, int] | None:
    """Parse 'YYYY-QN' → (year, quarter) or None on failure."""
    parts = label.split("-")
    if len(parts) == 2 and parts[1].startswith("Q"):
        try:
            return int(parts[0]), int(parts[1][1])
        except (ValueError, IndexError):
            return None
    return None


# ---------------------------------------------------------------------------
# TimeSeriesForecaster
# ---------------------------------------------------------------------------


class TimeSeriesForecaster:
    """Produce point forecasts and prediction intervals for HK economic metrics.

    Usage::

        forecaster = TimeSeriesForecaster()
        result = await forecaster.forecast("ccl_index", horizon=8)
        print(result.to_dict())
    """

    def __init__(self) -> None:
        # Cache fitted models: metric -> (data_length, fitted_sf_object, model_name)
        self._model_cache: dict[str, tuple[int, Any, str]] = {}

    async def forecast(
        self,
        metric: str,
        horizon: int = 12,
        domain_pack_id: str = "hk_city",
    ) -> ForecastResult:
        """Forecast *metric* for *horizon* periods ahead.

        Model selection strategy (Task 2.3):
          - n >= 20 and statsforecast available → auto-select best of
            AutoARIMA / AutoETS / Naive via holdout MAPE on last 4 points.
          - 12 <= n < 20 and statsforecast available → AutoARIMA directly.
          - n < 12 or no statsforecast → naive trend extrapolation.

        Args:
            metric: One of the keys in SUPPORTED_METRICS.
            horizon: Number of future periods to forecast (1–24).
            domain_pack_id: Domain pack to resolve metric DB mapping from.

        Returns:
            ForecastResult containing point forecasts + CI bands.

        Raises:
            ValueError: If metric is not supported.
        """
        # Build metric map: prefer pack, fallback to module-level METRIC_DB_MAP
        metric_db_map = METRIC_DB_MAP
        try:
            from backend.app.domain.base import DomainPackRegistry  # noqa: PLC0415
            pack = DomainPackRegistry.get(domain_pack_id)
            if pack.metrics:
                metric_db_map = {
                    m.name: (m.db_category, m.db_metric) for m in pack.metrics
                }
        except (KeyError, ImportError):
            pass

        if metric not in metric_db_map:
            available = ", ".join(sorted(metric_db_map))
            raise ValueError(f"Unsupported metric '{metric}'. Available: {available}")

        horizon = max(1, min(horizon, 24))

        history = await self._load_history(metric)
        n = len(history)
        logger.info(
            "Forecasting metric=%s horizon=%d n_historical=%d",
            metric, horizon, n,
        )

        # Minimum data threshold — refuse forecast with <_MIN_ARIMA_POINTS real data points
        if n < _MIN_ARIMA_POINTS:
            dq = "no_data" if n == 0 else "insufficient"
            logger.warning(
                "Refusing forecast for metric=%s — only %d data points (minimum %d required)",
                metric, n, _MIN_ARIMA_POINTS,
            )
            return ForecastResult(
                metric=metric,
                horizon=horizon,
                points=[],
                model_used="none",
                fit_quality=0.0,
                data_quality=dq,
            )

        # Classify data quality
        data_quality = "real_data" if n >= 20 else "partial_real"

        # Structural break detection — truncate training window if breaks found
        break_detection = None
        try:
            from backend.app.services.structural_break_detector import (  # noqa: PLC0415
                detect_structural_breaks,
            )
            break_detection = detect_structural_breaks(
                [v for _, v in history],
                min_series_length=20,
            )
            if break_detection.has_breaks and break_detection.recommended_start_index > 0:
                logger.info(
                    "Structural break detected for metric=%s — "
                    "truncating training window from index %d (was %d obs, now %d obs)",
                    metric,
                    break_detection.recommended_start_index,
                    len(history),
                    len(history) - break_detection.recommended_start_index,
                )
                history = history[break_detection.recommended_start_index:]
                n = len(history)
        except Exception as _bd_exc:
            logger.debug("Structural break detection skipped: %s", _bd_exc)

        if not HAS_STATSFORECAST or n < _MIN_ARIMA_POINTS:
            result = self._forecast_naive(metric, history, horizon)
            result = dataclasses.replace(result, data_quality=data_quality)
            if break_detection is not None:
                result = dataclasses.replace(
                    result,
                    diagnostics={**(result.diagnostics or {}), "break_detection": break_detection},
                )
            return result

        if n >= _MIN_AUTO_SELECT_POINTS:
            best_model_name = self._auto_select_model(history, metric)
            logger.info("Auto-selected model=%s for metric=%s", best_model_name, metric)
            result = self._forecast_with_model(metric, history, horizon, best_model_name)
            return dataclasses.replace(result, data_quality=data_quality)

        # 12 <= n < 20: use AutoARIMA directly (legacy behaviour)
        result = self._forecast_arima(metric, history, horizon)
        return dataclasses.replace(result, data_quality=data_quality)

    async def list_supported_metrics(self) -> list[str]:
        """Return list of supported metric names."""
        return sorted(METRIC_DB_MAP)

    # ------------------------------------------------------------------
    # Task 2.2 — VAR multivariate forecast
    # ------------------------------------------------------------------

    async def forecast_multivariate(
        self,
        group_name: str,
        horizon: int = 4,
    ) -> dict[str, ForecastResult] | None:
        """Return VAR cross-indicator forecasts for a named group.

        Delegates to VARForecaster. Returns None when insufficient data or
        statsmodels is unavailable.

        Args:
            group_name: Key from var_forecaster.VAR_GROUPS.
            horizon: Periods ahead to forecast (1–24).

        Returns:
            Dict metric → ForecastResult, or None on failure.
        """
        from backend.app.services.var_forecaster import (  # noqa: PLC0415
            VAR_GROUPS, VARForecaster,
        )

        if group_name not in VAR_GROUPS:
            available = ", ".join(sorted(VAR_GROUPS))
            raise ValueError(
                f"Unknown VAR group '{group_name}'. Available: {available}"
            )

        horizon = max(1, min(horizon, 24))
        group_metrics = VAR_GROUPS[group_name]

        series: dict[str, list[tuple[str, float]]] = {}
        qualified: int = 0
        for metric in group_metrics:
            if metric not in METRIC_DB_MAP:
                logger.debug("VAR group=%s: metric=%s not in DB map, skipping", group_name, metric)
                continue
            hist = await self._load_history(metric)
            series[metric] = hist
            if len(hist) >= _MIN_VAR_POINTS:
                qualified += 1

        # Allow partial VAR with 2 qualified metrics (instead of requiring all 3)
        if qualified < 2:
            logger.info(
                "VAR group=%s: only %d metrics have ≥%d obs (need ≥2), falling back",
                group_name, qualified, _MIN_VAR_POINTS,
            )
            return None

        # Filter to only qualified metrics for partial VAR
        if qualified < len(group_metrics):
            series = {m: s for m, s in series.items() if len(s) >= _MIN_VAR_POINTS}
            logger.info(
                "VAR group=%s: partial VAR with %d/%d metrics: %s",
                group_name, len(series), len(group_metrics), list(series.keys()),
            )

        var = VARForecaster()
        result = var.forecast_group(group_name, series, horizon)
        if result is None:
            return None

        return result.forecasts

    # ------------------------------------------------------------------
    # Task 2.4 — Rolling window forecast (backtesting)
    # ------------------------------------------------------------------

    async def forecast_rolling(
        self,
        metric: str,
        window_size: int = _DEFAULT_ROLLING_WINDOW,
        horizon: int = 1,
    ) -> list[ForecastPoint]:
        """Re-train every quarter on a sliding window and accumulate predictions.

        Produces backtesting predictions: trains on window, predicts horizon
        steps ahead.  Each point is labelled with the actual future period so
        results are directly comparable with real history values.

        Args:
            metric: One of the keys in SUPPORTED_METRICS.
            window_size: Number of most-recent observations used per training.
            horizon: Steps ahead to predict at each step (1–4).

        Returns:
            List of ForecastPoint sorted by period (oldest first).

        Raises:
            ValueError: If metric is not supported.
        """
        if metric not in METRIC_DB_MAP:
            available = ", ".join(sorted(METRIC_DB_MAP))
            raise ValueError(f"Unsupported metric '{metric}'. Available: {available}")

        horizon = max(1, min(horizon, 4))
        window_size = max(horizon + _MIN_ARIMA_POINTS, min(window_size, 200))

        history = await self._load_history(metric)
        n = len(history)

        if n < window_size + horizon:
            logger.info(
                "Rolling forecast for metric=%s: only %d obs, returning empty list",
                metric, n,
            )
            return []

        rolling_points: list[ForecastPoint] = []

        for end in range(window_size, n - horizon + 1):
            window = history[end - window_size: end]
            target_period = history[end + horizon - 1][0]

            if HAS_STATSFORECAST and len(window) >= _MIN_ARIMA_POINTS:
                try:
                    fc = self._forecast_arima(metric, window, horizon)
                    pt = fc.points[horizon - 1]
                    rolling_points.append(ForecastPoint(
                        period=target_period,
                        value=pt.value,
                        lower_80=pt.lower_80,
                        upper_80=pt.upper_80,
                        lower_95=pt.lower_95,
                        upper_95=pt.upper_95,
                    ))
                except Exception as exc:
                    logger.debug(
                        "Rolling ARIMA failed at end=%d for metric=%s: %s",
                        end, metric, exc,
                    )
                    pt = self._naive_one_step(metric, window, horizon, target_period)
                    rolling_points.append(pt)
            else:
                pt = self._naive_one_step(metric, window, horizon, target_period)
                rolling_points.append(pt)

        return rolling_points

    # ------------------------------------------------------------------
    # Task 2.5 — Seasonality helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_season_length(metric: str) -> int:
        """Return the seasonal period for *metric* (4 or 12)."""
        return _SEASONAL_METRICS.get(metric, _DEFAULT_SEASON)

    @staticmethod
    def _apply_seasonal_adjustment(
        points: list[ForecastPoint],
        metric: str,
        last_period: str,
    ) -> list[ForecastPoint]:
        """Apply Q1/Q4 seasonal dummies; returns new ForecastPoint objects."""
        adjustments = _SEASONAL_ADJUSTMENTS.get(metric)
        if not adjustments:
            return points

        adjusted: list[ForecastPoint] = []
        for pt in points:
            parsed = _parse_quarter(pt.period)
            if parsed is None:
                adjusted.append(pt)
                continue

            _year, quarter = parsed
            adj_factor = 0.0
            for q, delta in adjustments:
                if q == quarter:
                    adj_factor += delta

            if adj_factor == 0.0:
                adjusted.append(pt)
                continue

            v = pt.value
            adjusted.append(ForecastPoint(
                period=pt.period,
                value=round(v + adj_factor * abs(v), 6),
                lower_80=round(pt.lower_80 + adj_factor * abs(pt.lower_80), 6),
                upper_80=round(pt.upper_80 + adj_factor * abs(pt.upper_80), 6),
                lower_95=round(pt.lower_95 + adj_factor * abs(pt.lower_95), 6),
                upper_95=round(pt.upper_95 + adj_factor * abs(pt.upper_95), 6),
            ))

        return adjusted

    # ------------------------------------------------------------------
    # Model auto-selection (Task 2.3)
    # ------------------------------------------------------------------

    def _auto_select_model(
        self,
        history: list[tuple[str, float]],
        metric: str = "",
    ) -> str:
        """Select best model via holdout MAPE on last *_HOLDOUT_WINDOW* points.

        Candidates: AutoARIMA, AutoETS, Naive.
        Returns the candidate name with the lowest holdout MAPE.
        Falls back to "AutoARIMA" if evaluation fails for all candidates.
        """
        if not HAS_STATSFORECAST:
            return "naive"

        season_length = self._get_season_length(metric) if metric else _DEFAULT_SEASON

        n = len(history)
        holdout = min(_HOLDOUT_WINDOW, n // 5)  # at most 20% of series
        holdout = max(holdout, 1)

        train_history = history[: n - holdout]
        test_vals = np.array([v for _, v in history[n - holdout:]], dtype=np.float64)

        import pandas as pd  # noqa: PLC0415

        def _build_df(hist: list[tuple[str, float]]) -> "pd.DataFrame":
            periods = [h[0] for h in hist]
            values = np.array([h[1] for h in hist], dtype=np.float64)
            first = periods[0] if periods else "2019-Q1"
            try:
                parts = first.split("-")
                start_year = int(parts[0])
                start_q = int(parts[1][1]) if len(parts) > 1 and parts[1].startswith("Q") else 1
                start_month = (start_q - 1) * 3 + 1
                start_date = f"{start_year}-{start_month:02d}-01"
            except (ValueError, IndexError):
                start_date = "2019-01-01"
            return pd.DataFrame({
                "unique_id": ["hk"] * len(values),
                "ds": pd.date_range(start_date, periods=len(values), freq="QS"),
                "y": values,
            })

        candidates: list[tuple[str, Any]] = [
            ("AutoARIMA", AutoARIMA(season_length=season_length)),
            ("AutoETS", AutoETS(season_length=season_length)),
            ("Naive", Naive()),
        ]

        best_name = "AutoARIMA"
        best_mape = float("inf")

        train_df = _build_df(train_history)

        for model_name, model_obj in candidates:
            try:
                sf = StatsForecast(models=[model_obj], freq="QE", n_jobs=1)
                sf.fit(train_df)
                fc_df = sf.predict(h=holdout)
                preds = fc_df.iloc[:, -1].values[:holdout].astype(np.float64)
                actuals = test_vals[: len(preds)]
                with np.errstate(divide="ignore", invalid="ignore"):
                    ape = np.where(
                        actuals != 0,
                        np.abs((actuals - preds) / actuals),
                        0.0,
                    )
                mape = float(np.mean(ape)) * 100
                logger.debug(
                    "Model selection: model=%s holdout_mape=%.2f%%", model_name, mape
                )
                if mape < best_mape:
                    best_mape = mape
                    best_name = model_name
            except Exception as exc:  # noqa: BLE001
                logger.debug("Model selection: %s failed — %s", model_name, exc)

        return best_name

    def _forecast_with_model(
        self,
        metric: str,
        history: list[tuple[str, float]],
        horizon: int,
        model_name: str,
    ) -> ForecastResult:
        """Dispatch to the appropriate statsforecast model by name.

        Falls back to naive if the selected model fails.
        """
        if model_name == "AutoETS":
            return self._forecast_ets(metric, history, horizon)
        elif model_name == "Naive":
            return self._forecast_naive(metric, history, horizon)
        else:
            return self._forecast_arima(metric, history, horizon)

    def _forecast_ets(
        self,
        metric: str,
        history: list[tuple[str, float]],
        horizon: int,
    ) -> ForecastResult:
        """Fit AutoETS with metric-specific season_length; apply seasonal dummies."""
        import pandas as pd  # noqa: PLC0415

        season_length = self._get_season_length(metric)
        periods = [h[0] for h in history]
        values = np.array([h[1] for h in history], dtype=np.float64)

        last_label = periods[-1] if periods else "2024-Q1"
        next_labels = self._next_period_labels(last_label, horizon)

        try:
            first_label = periods[0] if periods else "2019-Q1"
            try:
                parts = first_label.split("-")
                start_year = int(parts[0])
                start_q = (
                    int(parts[1][1]) if len(parts) > 1 and parts[1].startswith("Q") else 1
                )
                start_month = (start_q - 1) * 3 + 1
                start_date = f"{start_year}-{start_month:02d}-01"
            except (ValueError, IndexError):
                start_date = "2019-01-01"

            # Use monthly frequency when season_length=12, else quarterly
            pd_freq = "MS" if season_length == 12 else "QS"

            df = pd.DataFrame({
                "unique_id": ["hk"] * len(values),
                "ds": pd.date_range(start_date, periods=len(values), freq=pd_freq),
                "y": values,
            })
            sf_freq = "ME" if season_length == 12 else "QE"
            sf = StatsForecast(
                models=[AutoETS(season_length=season_length)], freq=sf_freq, n_jobs=1
            )
            sf.fit(df)
            forecast_df = sf.predict(h=horizon, level=[80, 95])

            points: list[ForecastPoint] = []
            for i in range(horizon):
                row = forecast_df.iloc[i]
                pt_val = float(row.get("AutoETS", row.iloc[-1]))
                points.append(ForecastPoint(
                    period=next_labels[i],
                    value=pt_val,
                    lower_80=float(row.get("AutoETS-lo-80", pt_val * 0.95)),
                    upper_80=float(row.get("AutoETS-hi-80", pt_val * 1.05)),
                    lower_95=float(row.get("AutoETS-lo-95", pt_val * 0.92)),
                    upper_95=float(row.get("AutoETS-hi-95", pt_val * 1.08)),
                ))

            # Task 2.5: apply seasonal adjustment after fitting
            points = self._apply_seasonal_adjustment(points, metric, last_label)

            mape = self._compute_mape(values)

            diagnostics: dict = {
                "model_selected": "AutoETS",
                "n_observations": len(values),
            }
            try:
                from statsmodels.stats.diagnostic import acorr_ljungbox  # noqa: PLC0415
                resid = values - np.concatenate([[values[0]], values[:-1]])
                lb_lags = min(10, max(1, len(resid) // 5))
                lb_result = acorr_ljungbox(resid, lags=lb_lags, return_df=True)
                diagnostics["ljung_box_p"] = float(lb_result["lb_pvalue"].iloc[-1])
            except Exception:
                diagnostics["ljung_box_p"] = None

            # Phase 6C: structural break detection
            try:
                from backend.app.services.validation_suite import validate_structural_breaks  # noqa: PLC0415
                diagnostics["structural_breaks"] = validate_structural_breaks(
                    series=values.tolist(),
                    periods=periods,
                )
            except Exception:
                diagnostics["structural_breaks"] = []

            return ForecastResult(
                metric=metric,
                horizon=horizon,
                points=points,
                model_used="AutoETS",
                fit_quality=mape,
                diagnostics=diagnostics,
            )
        except Exception as exc:
            logger.warning("AutoETS failed for metric=%s (%s), falling back to naive", metric, exc)
            return self._forecast_naive(metric, history, horizon)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _load_history(self, metric: str) -> list[tuple[str, float]]:
        """Load (period, value) pairs from DB; falls back to hardcoded baseline."""
        category, metric_key = METRIC_DB_MAP[metric]
        records: list[tuple[str, float]] = []

        try:
            async with get_db() as db:
                if metric == "hsi_level":
                    # HSI is stored in market_data table, not hk_data_snapshots
                    cursor = await db.execute(
                        """
                        SELECT date, close
                        FROM market_data
                        WHERE ticker = 'HSI'
                        ORDER BY date ASC
                        """,
                    )
                    rows = await cursor.fetchall()
                    for row in rows:
                        date_str = str(row[0])
                        try:
                            val = float(row[1])
                            # Convert date to quarterly period label if needed
                            # e.g. "2024-03" or "2024-03-31" → "2024-Q1"
                            parts = date_str.split("-")
                            if len(parts) >= 2:
                                year = int(parts[0])
                                month = int(parts[1])
                                quarter = (month - 1) // 3 + 1
                                period_label = f"{year}-Q{quarter}"
                            else:
                                period_label = date_str
                            records.append((period_label, val))
                        except (TypeError, ValueError):
                            continue
                else:
                    cursor = await db.execute(
                        """
                        SELECT period, value
                        FROM hk_data_snapshots
                        WHERE category = ? AND metric = ?
                        ORDER BY period ASC
                        """,
                        (category, metric_key),
                    )
                    rows = await cursor.fetchall()
                    for row in rows:
                        period_label = str(row[0])
                        try:
                            val = float(row[1])
                            records.append((period_label, val))
                        except (TypeError, ValueError):
                            continue

        except Exception:
            logger.warning(
                "Could not load history for metric=%s from DB, using fallback", metric
            )

        if not records:
            logger.warning(
                "No real data available for metric=%s — forecast will be refused", metric
            )

        return records

    def _forecast_arima(
        self,
        metric: str,
        history: list[tuple[str, float]],
        horizon: int,
    ) -> ForecastResult:
        """Fit AutoARIMA with metric-specific season_length; apply seasonal dummies."""
        season_length = self._get_season_length(metric)
        periods = [h[0] for h in history]
        values = np.array([h[1] for h in history], dtype=np.float64)

        last_label = periods[-1] if periods else "2024-Q1"
        next_labels = self._next_period_labels(last_label, horizon)

        try:
            # Use monthly frequency when season_length=12, else quarterly
            pd_freq = "MS" if season_length == 12 else "QS"
            sf_freq = "ME" if season_length == 12 else "QE"

            import pandas as pd  # noqa: PLC0415
            first_label = periods[0] if periods else "2019-Q1"
            try:
                parts = first_label.split("-")
                start_year = int(parts[0])
                start_q = int(parts[1][1]) if len(parts) > 1 and parts[1].startswith("Q") else 1
                start_month = (start_q - 1) * 3 + 1
                start_date = f"{start_year}-{start_month:02d}-01"
            except (ValueError, IndexError):
                start_date = "2019-01-01"

            df = pd.DataFrame({
                "unique_id": ["hk"] * len(values),
                "ds": pd.date_range(start_date, periods=len(values), freq=pd_freq),
                "y": values,
            })

            # Check model cache: reuse fitted model if data length changed by <=2
            cached = self._model_cache.get(metric)
            if cached is not None:
                cached_len, cached_sf, cached_name = cached
                if abs(len(values) - cached_len) <= 2 and cached_name == "AutoARIMA":
                    sf = cached_sf
                else:
                    models = [AutoARIMA(season_length=season_length)]
                    sf = StatsForecast(models=models, freq=sf_freq, n_jobs=1)
                    sf.fit(df)
                    self._model_cache[metric] = (len(values), sf, "AutoARIMA")
            else:
                models = [AutoARIMA(season_length=season_length)]
                sf = StatsForecast(models=models, freq=sf_freq, n_jobs=1)
                sf.fit(df)
                self._model_cache[metric] = (len(values), sf, "AutoARIMA")

            forecast_df = sf.predict(h=horizon, level=[80, 95])

            points: list[ForecastPoint] = []
            for i in range(horizon):
                row = forecast_df.iloc[i]
                pt = ForecastPoint(
                    period=next_labels[i],
                    value=float(row.get("AutoARIMA", row.iloc[-1])),
                    lower_80=float(row.get("AutoARIMA-lo-80", row.iloc[-1] * 0.95)),
                    upper_80=float(row.get("AutoARIMA-hi-80", row.iloc[-1] * 1.05)),
                    lower_95=float(row.get("AutoARIMA-lo-95", row.iloc[-1] * 0.92)),
                    upper_95=float(row.get("AutoARIMA-hi-95", row.iloc[-1] * 1.08)),
                )
                points.append(pt)

            # Task 2.5: apply seasonal adjustment after fitting
            points = self._apply_seasonal_adjustment(points, metric, last_label)

            mape = self._compute_mape(values)

            # Residual diagnostics: Ljung-Box test for autocorrelation
            diagnostics: dict = {
                "model_selected": "AutoARIMA",
                "n_observations": len(values),
            }
            try:
                from statsmodels.stats.diagnostic import acorr_ljungbox  # noqa: PLC0415
                resid = values - np.concatenate([[values[0]], values[:-1]])  # naive residuals
                lb_lags = min(10, max(1, len(resid) // 5))
                lb_result = acorr_ljungbox(resid, lags=lb_lags, return_df=True)
                diagnostics["ljung_box_p"] = float(lb_result["lb_pvalue"].iloc[-1])
                if diagnostics["ljung_box_p"] < 0.05:
                    logger.info(
                        "Ljung-Box p=%.4f < 0.05 for metric=%s — residual autocorrelation detected",
                        diagnostics["ljung_box_p"], metric,
                    )
            except Exception:
                diagnostics["ljung_box_p"] = None

            # Jarque-Bera + ARCH residual diagnostics
            resid_arr = values - np.concatenate([[values[0]], values[:-1]])
            residual_diag = self._diagnose_residuals(resid_arr)
            if residual_diag is not None:
                diagnostics["residual_diagnostics"] = residual_diag

            # Phase 6C: structural break detection
            try:
                from backend.app.services.validation_suite import validate_structural_breaks  # noqa: PLC0415
                diagnostics["structural_breaks"] = validate_structural_breaks(
                    series=values.tolist(),
                    periods=periods,
                )
            except Exception:
                diagnostics["structural_breaks"] = []

            return ForecastResult(
                metric=metric,
                horizon=horizon,
                points=points,
                model_used="AutoARIMA",
                fit_quality=mape,
                diagnostics=diagnostics,
            )
        except Exception as exc:
            logger.warning(
                "AutoARIMA failed for metric=%s (%s), falling back to naive", metric, exc
            )
            return self._forecast_naive(metric, history, horizon)

    def _forecast_naive(
        self,
        metric: str,
        history: list[tuple[str, float]],
        horizon: int,
    ) -> ForecastResult:
        """Random Walk with Drift fallback forecast.

        Computes drift as the mean of first differences and uses the
        standard deviation of diffs to produce widening CI bands that
        grow proportionally to sqrt(h).
        """
        if not history:
            return ForecastResult(
                metric=metric,
                horizon=horizon,
                points=[],
                model_used="rw_drift",
                fit_quality=0.0,
                data_quality="no_data",
            )

        periods = [h[0] for h in history]
        values = [h[1] for h in history]
        last_label = periods[-1] if periods else "2024-Q1"
        next_labels = self._next_period_labels(last_label, horizon)

        last_val = float(values[-1])

        # Compute drift and volatility from first differences
        if len(values) >= 2:
            diffs = [values[i] - values[i - 1] for i in range(1, len(values))]
            drift = float(np.mean(diffs))
            sigma = float(np.std(diffs, ddof=1)) if len(diffs) >= 2 else abs(drift) * 0.5
        else:
            drift = 0.0
            sigma = abs(last_val) * 0.05 if last_val != 0 else 0.01

        # Floor sigma to avoid degenerate zero-width intervals
        sigma = max(sigma, abs(last_val * 0.01) if last_val != 0 else 0.01)

        points: list[ForecastPoint] = []
        for h in range(1, horizon + 1):
            pt_val = last_val + drift * h
            spread_80 = sigma * math.sqrt(h) * 1.28
            spread_95 = sigma * math.sqrt(h) * 1.96
            points.append(ForecastPoint(
                period=next_labels[h - 1],
                value=round(pt_val, 4),
                lower_80=round(pt_val - spread_80, 4),
                upper_80=round(pt_val + spread_80, 4),
                lower_95=round(pt_val - spread_95, 4),
                upper_95=round(pt_val + spread_95, 4),
            ))

        # Task 2.5: apply seasonal adjustment to RW drift forecasts too
        points = self._apply_seasonal_adjustment(points, metric, last_label)

        return ForecastResult(
            metric=metric,
            horizon=horizon,
            points=points,
            model_used="rw_drift",
            fit_quality=0.0,
        )

    def _naive_one_step(
        self,
        metric: str,
        window: list[tuple[str, float]],
        horizon: int,
        target_period: str,
    ) -> ForecastPoint:
        """Produce a single naive forecast point for a target period."""
        result = self._forecast_naive(metric, window, horizon)
        pt = result.points[horizon - 1]
        # Relabel with the actual target period
        return ForecastPoint(
            period=target_period,
            value=pt.value,
            lower_80=pt.lower_80,
            upper_80=pt.upper_80,
            lower_95=pt.lower_95,
            upper_95=pt.upper_95,
        )

    @staticmethod
    def _compute_mape(values: np.ndarray) -> float:
        """Compute MAPE using leave-one-out on last 20% of the series."""
        n = len(values)
        if n < 4:
            return 0.0
        test_start = max(1, int(n * 0.8))
        actuals = values[test_start:]
        preds = values[test_start - 1: n - 1]  # naive 1-step
        with np.errstate(divide="ignore", invalid="ignore"):
            ape = np.where(actuals != 0, np.abs((actuals - preds) / actuals), 0.0)
        return float(np.mean(ape) * 100)

    @staticmethod
    def _diagnose_residuals(residuals: "np.ndarray") -> "dict | None":
        """Run Jarque-Bera normality test and Engle's ARCH test on residuals.

        Args:
            residuals: 1-D numpy array of forecast residuals (actual - predicted).

        Returns:
            Dict with diagnostic statistics, or None if scipy/statsmodels unavailable.

        Keys:
            jarque_bera_stat: JB test statistic.
            jarque_bera_pvalue: JB p-value (> 0.05 → residuals are approx normal).
            arch_stat: ARCH LM test statistic.
            arch_pvalue: ARCH LM p-value.
            has_arch_effects: True when ARCH p < 0.05.
            is_normal: True when JB p > 0.05.
        """
        try:
            from scipy.stats import jarque_bera  # noqa: PLC0415
            from statsmodels.stats.diagnostic import het_arch  # noqa: PLC0415
        except ImportError:
            logger.debug("_diagnose_residuals: scipy/statsmodels not available, skipping")
            return None

        try:
            arr = np.asarray(residuals, dtype=np.float64)
            if len(arr) < 8:
                return None

            # Jarque-Bera normality test
            jb_stat, jb_pvalue = jarque_bera(arr)

            # Engle's ARCH LM test (default 5 lags)
            arch_lags = min(5, len(arr) // 5)
            arch_stat, arch_pvalue, _f_stat, _f_pvalue = het_arch(arr, nlags=arch_lags)

            return {
                "jarque_bera_stat": float(jb_stat),
                "jarque_bera_pvalue": float(jb_pvalue),
                "arch_stat": float(arch_stat),
                "arch_pvalue": float(arch_pvalue),
                "has_arch_effects": bool(arch_pvalue < 0.05),
                "is_normal": bool(jb_pvalue > 0.05),
            }
        except Exception as exc:
            logger.debug("_diagnose_residuals failed: %s", exc)
            return None

    @staticmethod
    def _next_period_labels(last_period: str, horizon: int) -> list[str]:
        """Generate *horizon* period labels after *last_period*.

        Supports 'YYYY-QN' quarterly labels and plain 'YYYY' annual labels.
        Falls back to ordinal labels (t+1, t+2, …) for unrecognised formats.
        """
        labels: list[str] = []
        parts = last_period.split("-")
        if len(parts) == 2 and parts[1].startswith("Q"):
            # Quarterly: 2024-Q1 → 2024-Q2, …
            try:
                base_year = int(parts[0])
                base_q = int(parts[1][1])
                for i in range(1, horizon + 1):
                    labels.append(_quarter_label(base_year, base_q, i))
                return labels
            except (ValueError, IndexError):
                pass
        if len(parts) == 1:
            # Annual: 2023 → 2024, …
            try:
                base_year = int(parts[0])
                for i in range(1, horizon + 1):
                    labels.append(_annual_label(base_year, i))
                return labels
            except ValueError:
                pass
        # Fallback: ordinal
        return [f"t+{i}" for i in range(1, horizon + 1)]

    # _hardcoded_baseline() REMOVED — no synthetic data allowed.
    # If no real data is available, forecast methods return empty results.
