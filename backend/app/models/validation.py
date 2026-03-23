"""Validation and confidence models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ConfidenceResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    backtest_vs_naive: float
    backtest_vs_arima: float = 0.0
    mc_band_width: float = 0.0
    agent_consensus: float = 0.0
    sensitivity_score: float = 0.0
    confidence_level: Literal["high", "medium", "low"] = "medium"
    confidence_score: float = 0.5
    explanation_zh: str = ""
    source_validation: str | None = None
