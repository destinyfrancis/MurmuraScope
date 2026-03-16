"""Frozen dataclasses for stock/index forecast domain objects."""

from __future__ import annotations

import dataclasses
from typing import Any


@dataclasses.dataclass(frozen=True)
class TickerInfo:
    """Metadata for a tracked ticker."""

    ticker: str
    name: str
    asset_type: str  # hk_stock | hk_index | us_stock | us_index
    sector_tag: str
    market: str  # HK | US

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "asset_type": self.asset_type,
            "sector_tag": self.sector_tag,
            "market": self.market,
        }


@dataclasses.dataclass(frozen=True)
class SignalContribution:
    """Breakdown of one simulation signal's contribution to forecast shift."""

    signal_name: str
    signal_value: float
    weight: float
    contribution: float  # signal_value * weight
    direction: str  # "bullish" | "bearish" | "neutral"

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_name": self.signal_name,
            "signal_value": round(self.signal_value, 4),
            "weight": round(self.weight, 4),
            "contribution": round(self.contribution, 4),
            "direction": self.direction,
        }


@dataclasses.dataclass(frozen=True)
class StockForecastPoint:
    """One weekly forecast data point."""

    week: str  # "YYYY-WNN"
    close: float
    lower_80: float
    upper_80: float
    lower_95: float
    upper_95: float
    sentiment_adjusted: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "week": self.week,
            "close": round(self.close, 2),
            "lower_80": round(self.lower_80, 2),
            "upper_80": round(self.upper_80, 2),
            "lower_95": round(self.lower_95, 2),
            "upper_95": round(self.upper_95, 2),
            "sentiment_adjusted": self.sentiment_adjusted,
        }


@dataclasses.dataclass(frozen=True)
class StockForecastResult:
    """Full forecast result for one ticker."""

    ticker: str
    asset_type: str
    name: str
    horizon: int
    points: tuple[StockForecastPoint, ...]
    model_used: str  # "AutoARIMA" | "NaiveDrift"
    fit_quality: str  # "good" | "fair" | "poor"
    data_quality: str  # "sufficient" | "insufficient"
    signal_shift: float  # composite shift applied [-0.12, +0.12]
    signal_breakdown: tuple[SignalContribution, ...]
    session_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "asset_type": self.asset_type,
            "name": self.name,
            "horizon": self.horizon,
            "points": [p.to_dict() for p in self.points],
            "model_used": self.model_used,
            "fit_quality": self.fit_quality,
            "data_quality": self.data_quality,
            "signal_shift": round(self.signal_shift, 4),
            "signal_breakdown": [s.to_dict() for s in self.signal_breakdown],
            "session_id": self.session_id,
        }


@dataclasses.dataclass(frozen=True)
class StockBacktestResult:
    """Walk-forward backtest result for one ticker."""

    ticker: str
    mape: float
    rmse: float
    directional_accuracy: float
    n_obs: int
    train_end: str  # "YYYY-WNN"
    horizon: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "mape": round(self.mape, 4),
            "rmse": round(self.rmse, 2),
            "directional_accuracy": round(self.directional_accuracy, 4),
            "n_obs": self.n_obs,
            "train_end": self.train_end,
            "horizon": self.horizon,
        }
