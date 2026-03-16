"""StockForecaster — 12-week ARIMA forecast with simulation signal overlay.

Loads weekly OHLCV history from market_data (granularity='weekly'),
fits AutoARIMA (statsforecast) or falls back to naive drift,
then applies a composite signal shift derived from SimulationSignals.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Any

from backend.app.models.stock_forecast import (
    SignalContribution,
    StockForecastPoint,
    StockForecastResult,
)
from backend.app.services.signal_extractor import SimulationSignalExtractor, SimulationSignals
from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger
from backend.data_pipeline.stock_downloader import TICKER_REGISTRY

logger = get_logger("stock_forecaster")

# ---------------------------------------------------------------------------
# Optional statsforecast
# ---------------------------------------------------------------------------

try:
    from statsforecast import StatsForecast
    from statsforecast.models import AutoARIMA, Naive

    HAS_STATSFORECAST = True
    logger.info("statsforecast available for stock forecasting")
except ImportError:
    HAS_STATSFORECAST = False
    logger.info("statsforecast not installed — using naive drift fallback")

# ---------------------------------------------------------------------------
# Signal weights per asset_type (economic theory-motivated)
# ---------------------------------------------------------------------------

SIGNAL_WEIGHTS: dict[str, dict[str, float]] = {
    "hk_index": {
        "sentiment_net": 0.035,
        "sentiment_momentum": 0.025,
        "negative_virality": -0.030,
        "property_sentiment": 0.020,
        "finance_sentiment": 0.040,
        "emotional_valence": 0.015,
        "arousal_concentration": -0.020,
        "contagion_velocity": -0.015,
        "emigration_rate": -0.050,
        "invest_ratio": 0.030,
        "spending_cut_ratio": -0.025,
        "polarization_index": -0.020,
        "echo_chamber_modularity": -0.015,
        "filter_bubble_severity": -0.010,
        "trust_erosion_rate": -0.025,
        "hsi_sim_change": 0.080,
        "consumer_confidence_sim": 0.020,
        "credit_stress": -0.040,
        "taiwan_strait_risk": -0.060,
        "ensemble_hsi_p50": 0.050,
        "ensemble_skew": 0.010,
        "decision_entropy": -0.010,
    },
    "hk_stock": {
        "sentiment_net": 0.030,
        "sentiment_momentum": 0.020,
        "negative_virality": -0.025,
        "property_sentiment": 0.060,    # boosted for property-sensitive stocks
        "finance_sentiment": 0.045,
        "emotional_valence": 0.012,
        "arousal_concentration": -0.018,
        "contagion_velocity": -0.012,
        "buy_property_ratio": 0.035,
        "emigration_rate": -0.045,
        "invest_ratio": 0.025,
        "spending_cut_ratio": -0.020,
        "polarization_index": -0.018,
        "echo_chamber_modularity": -0.012,
        "filter_bubble_severity": -0.008,
        "trust_erosion_rate": -0.022,
        "hsi_sim_change": 0.070,
        "ccl_sim_change": 0.040,
        "consumer_confidence_sim": 0.018,
        "credit_stress": -0.035,
        "taiwan_strait_risk": -0.055,
        "ensemble_hsi_p50": 0.040,
    },
    "us_index": {
        "sentiment_net": 0.015,
        "finance_sentiment": 0.020,
        "emotional_valence": 0.010,
        "negative_virality": -0.010,
        "polarization_index": -0.008,
        "hsi_sim_change": 0.025,        # HK↔US correlation
        "taiwan_strait_risk": -0.080,   # major geopolitical risk to US tech
        "credit_stress": -0.020,
        "invest_ratio": 0.015,
        "emigration_rate": -0.010,
        "ensemble_hsi_p50": 0.015,
        "ensemble_skew": 0.008,
    },
    "us_stock": {
        "sentiment_net": 0.012,
        "finance_sentiment": 0.018,
        "emotional_valence": 0.008,
        "negative_virality": -0.008,
        "taiwan_strait_risk": -0.070,
        "credit_stress": -0.018,
        "invest_ratio": 0.012,
        "hsi_sim_change": 0.020,
        "ensemble_hsi_p50": 0.012,
        "polarization_index": -0.006,
        "arousal_concentration": -0.010,
    },
}

MIN_WEEKS_REQUIRED = 20


# ---------------------------------------------------------------------------
# Helper: week label arithmetic
# ---------------------------------------------------------------------------

def _week_sort_key(week_label: str) -> int:
    """Convert 'YYYY-WNN' to a sortable integer YYYYNN."""
    try:
        year, wpart = week_label.split("-W")
        return int(year) * 100 + int(wpart)
    except ValueError:
        return 0


def _week_label_offset(base_label: str, offset: int) -> str:
    """Compute a week label offset from base_label by `offset` weeks.

    Uses ISO week arithmetic: converts to days, adds offset*7, back to ISO.
    """
    import datetime

    try:
        year, wpart = base_label.split("-W")
        iso_year, iso_week = int(year), int(wpart)
        # ISO week 1 day 1 = Monday of week 1
        jan4 = datetime.date(iso_year, 1, 4)
        week1_monday = jan4 - datetime.timedelta(days=jan4.isoweekday() - 1)
        base_friday = week1_monday + datetime.timedelta(weeks=iso_week - 1, days=4)
        target_friday = base_friday + datetime.timedelta(weeks=offset)
        iso = target_friday.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    except Exception:
        return f"{base_label}+{offset}"


# ---------------------------------------------------------------------------
# StockForecaster
# ---------------------------------------------------------------------------

class StockForecaster:
    """Produces 12-week forecasts for stocks/indices, optionally signal-adjusted."""

    def __init__(self) -> None:
        self._extractor = SimulationSignalExtractor()

    async def forecast(
        self,
        ticker: str,
        horizon: int = 12,
        session_id: str | None = None,
    ) -> StockForecastResult:
        """Main entry point. Loads history, fits model, applies signal overlay."""
        if ticker not in TICKER_REGISTRY:
            raise ValueError(f"Unknown ticker: {ticker}. Register it in TICKER_REGISTRY first.")

        meta = TICKER_REGISTRY[ticker]
        asset_type = meta["asset_type"]

        history = await self._load_weekly_history(ticker)

        if len(history) < MIN_WEEKS_REQUIRED:
            logger.warning(
                "Insufficient history for %s: %d weeks (need %d)",
                ticker, len(history), MIN_WEEKS_REQUIRED,
            )
            empty_points: tuple[StockForecastPoint, ...] = ()
            return StockForecastResult(
                ticker=ticker,
                asset_type=asset_type,
                name=meta["name"],
                horizon=horizon,
                points=empty_points,
                model_used="none",
                fit_quality="poor",
                data_quality="insufficient",
                signal_shift=0.0,
                signal_breakdown=(),
                session_id=session_id,
            )

        # Extract simulation signals if session_id provided
        signals: SimulationSignals | None = None
        if session_id:
            try:
                signals = await self._extractor.extract(session_id)
            except Exception as exc:
                logger.warning("Signal extraction failed for session %s: %s", session_id, exc)

        # Fit forecast model
        if HAS_STATSFORECAST:
            points, model_used, fit_quality = self._forecast_arima_weekly(history, horizon)
        else:
            points, model_used, fit_quality = self._forecast_naive_weekly(history, horizon)

        # Apply signal overlay
        signal_shift = 0.0
        signal_breakdown: tuple[SignalContribution, ...] = ()
        if signals is not None and points:
            points, signal_shift = self._apply_signal_overlay(points, signals, asset_type)
            signal_breakdown = self._compute_signal_breakdown(signals, asset_type)

        return StockForecastResult(
            ticker=ticker,
            asset_type=asset_type,
            name=meta["name"],
            horizon=horizon,
            points=tuple(points),
            model_used=model_used,
            fit_quality=fit_quality,
            data_quality="sufficient",
            signal_shift=signal_shift,
            signal_breakdown=signal_breakdown,
            session_id=session_id,
        )

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    async def _load_weekly_history(self, ticker: str) -> list[tuple[str, float]]:
        """Load (week_label, close) from market_data where granularity='weekly'."""
        async with get_db() as db:
            rows = await db.execute_fetchall(
                """SELECT date, close FROM market_data
                   WHERE ticker = ? AND granularity = 'weekly' AND close > 0
                   ORDER BY date ASC""",
                (ticker,),
            )
        return [(r[0], float(r[1])) for r in rows]

    # ------------------------------------------------------------------
    # ARIMA forecast
    # ------------------------------------------------------------------

    def _forecast_arima_weekly(
        self,
        history: list[tuple[str, float]],
        horizon: int,
    ) -> tuple[list[StockForecastPoint], str, str]:
        """Fit AutoARIMA on weekly close history, return forecast points."""
        try:
            import pandas as pd
            import numpy as np

            closes = [c for _, c in history]
            n = len(closes)

            sf = StatsForecast(
                models=[AutoARIMA(season_length=52, approximation=True)],
                freq="W",
                n_jobs=1,
            )

            df = pd.DataFrame({
                "unique_id": ["ticker"] * n,
                "ds": pd.date_range(end=pd.Timestamp.now(), periods=n, freq="W-FRI"),
                "y": closes,
            })
            sf.fit(df)

            pred = sf.predict(h=horizon, level=[80, 95])

            # Assess fit quality via in-sample residual std relative to mean
            fitted_vals = sf.fitted_values_
            if fitted_vals is not None and len(fitted_vals) > 0:
                residuals = np.array(closes[-len(fitted_vals):]) - fitted_vals["mean"].values
                cv = float(np.std(residuals) / abs(np.mean(closes))) if np.mean(closes) != 0 else 1.0
                fit_quality = "good" if cv < 0.05 else ("fair" if cv < 0.15 else "poor")
            else:
                fit_quality = "fair"

            base_week = history[-1][0]
            points: list[StockForecastPoint] = []
            for i, row in enumerate(pred.itertuples(), start=1):
                week = _week_label_offset(base_week, i)
                close_val = float(getattr(row, "AutoARIMA", getattr(row, "mean", closes[-1])))
                lo80 = float(getattr(row, "AutoARIMA-lo-80", close_val * 0.95))
                hi80 = float(getattr(row, "AutoARIMA-hi-80", close_val * 1.05))
                lo95 = float(getattr(row, "AutoARIMA-lo-95", close_val * 0.90))
                hi95 = float(getattr(row, "AutoARIMA-hi-95", close_val * 1.10))
                points.append(StockForecastPoint(
                    week=week,
                    close=max(close_val, 0.01),
                    lower_80=max(lo80, 0.01),
                    upper_80=max(hi80, 0.01),
                    lower_95=max(lo95, 0.01),
                    upper_95=max(hi95, 0.01),
                    sentiment_adjusted=False,
                ))

            return points, "AutoARIMA", fit_quality

        except Exception as exc:
            logger.warning("AutoARIMA failed, falling back to naive drift: %s", exc)
            return self._forecast_naive_weekly(history, horizon)

    # ------------------------------------------------------------------
    # Naive drift forecast
    # ------------------------------------------------------------------

    def _forecast_naive_weekly(
        self,
        history: list[tuple[str, float]],
        horizon: int,
    ) -> tuple[list[StockForecastPoint], str, str]:
        """Random walk with drift + linearly widening CI bands."""
        closes = [c for _, c in history]
        n = len(closes)
        last_close = closes[-1]

        # Drift: average weekly return over full history
        if n >= 2:
            drift = (closes[-1] / closes[0]) ** (1.0 / (n - 1)) - 1.0
        else:
            drift = 0.0

        # Weekly volatility estimate
        if n >= 4:
            returns = [(closes[i] / closes[i - 1] - 1.0) for i in range(1, min(n, 53))]
            vol = float(_std(returns))
        else:
            vol = 0.02  # 2% default weekly vol

        base_week = history[-1][0]
        points: list[StockForecastPoint] = []
        for t in range(1, horizon + 1):
            projected = last_close * ((1 + drift) ** t)
            # CI widens with sqrt(t)
            half_80 = projected * vol * 1.282 * math.sqrt(t)
            half_95 = projected * vol * 1.960 * math.sqrt(t)
            week = _week_label_offset(base_week, t)
            points.append(StockForecastPoint(
                week=week,
                close=max(projected, 0.01),
                lower_80=max(projected - half_80, 0.01),
                upper_80=max(projected + half_80, 0.01),
                lower_95=max(projected - half_95, 0.01),
                upper_95=max(projected + half_95, 0.01),
                sentiment_adjusted=False,
            ))

        return points, "NaiveDrift", "fair"

    # ------------------------------------------------------------------
    # Signal overlay
    # ------------------------------------------------------------------

    def _apply_signal_overlay(
        self,
        points: list[StockForecastPoint],
        signals: SimulationSignals,
        asset_type: str,
    ) -> tuple[list[StockForecastPoint], float]:
        """Apply composite signal shift to forecast points with exponential decay.

        composite_shift = sum(signal_value * weight), clamped to [-0.12, +0.12].
        Adjusted close = base * (1 + clamped_shift * exp(-0.05 * t))
        """
        weights = SIGNAL_WEIGHTS.get(asset_type, SIGNAL_WEIGHTS["hk_index"])
        signal_dict = dataclasses.asdict(signals)

        raw_shift = sum(
            signal_dict.get(sig, 0.0) * w
            for sig, w in weights.items()
            if isinstance(signal_dict.get(sig, 0.0), (int, float))
        )
        clamped_shift = max(-0.12, min(0.12, raw_shift))

        adjusted: list[StockForecastPoint] = []
        for t, pt in enumerate(points, start=1):
            factor = 1.0 + clamped_shift * math.exp(-0.05 * t)
            new_close = pt.close * factor
            new_lo80 = pt.lower_80 * factor
            new_hi80 = pt.upper_80 * factor
            new_lo95 = pt.lower_95 * factor
            new_hi95 = pt.upper_95 * factor
            adjusted.append(dataclasses.replace(
                pt,
                close=max(new_close, 0.01),
                lower_80=max(new_lo80, 0.01),
                upper_80=max(new_hi80, 0.01),
                lower_95=max(new_lo95, 0.01),
                upper_95=max(new_hi95, 0.01),
                sentiment_adjusted=True,
            ))

        return adjusted, round(clamped_shift, 4)

    # ------------------------------------------------------------------
    # Signal breakdown
    # ------------------------------------------------------------------

    def _compute_signal_breakdown(
        self,
        signals: SimulationSignals,
        asset_type: str,
    ) -> tuple[SignalContribution, ...]:
        """Compute per-signal contribution, sorted by |contribution| desc, top 10."""
        weights = SIGNAL_WEIGHTS.get(asset_type, SIGNAL_WEIGHTS["hk_index"])
        signal_dict = dataclasses.asdict(signals)

        contributions: list[SignalContribution] = []
        for sig_name, weight in weights.items():
            val = signal_dict.get(sig_name, 0.0)
            if not isinstance(val, (int, float)):
                continue
            contrib = float(val) * weight
            direction = "bullish" if contrib > 0.001 else ("bearish" if contrib < -0.001 else "neutral")
            contributions.append(SignalContribution(
                signal_name=sig_name,
                signal_value=float(val),
                weight=weight,
                contribution=contrib,
                direction=direction,
            ))

        # Sort by absolute contribution descending, take top 10
        top = sorted(contributions, key=lambda c: abs(c.contribution), reverse=True)[:10]
        return tuple(top)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _std(values: list[float]) -> float:
    """Population standard deviation."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance)
