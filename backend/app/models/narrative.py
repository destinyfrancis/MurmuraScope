"""Natural language report models for trend narrative generation."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class TrendBlock(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str
    direction: Literal["up", "down", "stable", "volatile"]
    confidence: Literal["high", "medium", "low"]
    narrative: str
    evidence: list[str] = []
    counter_signals: list[str] = []


class TrendNarrative(BaseModel):
    model_config = ConfigDict(frozen=True)

    executive_summary: str
    trends: list[TrendBlock]
    deep_dive_summary: str = ""
    methodology_note: str | None = None
    generated_at: datetime | None = None
