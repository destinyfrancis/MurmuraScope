"""Domain pack and data connector models."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


class DraftDomainPack(BaseModel):
    """Mutable draft of a domain pack, produced by LLM generation or user editing.

    Validated on construction — all min-count rules are enforced.
    Immutable after construction (frozen=True).
    """

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    description: str = ""
    regions: list[str]
    occupations: list[str]
    income_brackets: list[str]
    shocks: list[str]
    metrics: list[str]
    persona_template: str
    sentiment_keywords: list[str]
    locale: str = "en-US"
    source: Literal["builtin", "generated", "user_edited"] = "generated"

    @field_validator("regions")
    @classmethod
    def regions_min(cls, v: list[str]) -> list[str]:
        if len(v) < 3:
            raise ValueError("regions must have at least 3 items")
        return v

    @field_validator("shocks")
    @classmethod
    def shocks_min(cls, v: list[str]) -> list[str]:
        if len(v) < 4:
            raise ValueError("shocks must have at least 4 items")
        return v

    @field_validator("metrics")
    @classmethod
    def metrics_min(cls, v: list[str]) -> list[str]:
        if len(v) < 3:
            raise ValueError("metrics must have at least 3 items")
        return v

    @field_validator("sentiment_keywords")
    @classmethod
    def keywords_min(cls, v: list[str]) -> list[str]:
        if len(v) < 20:
            raise ValueError("sentiment_keywords must have at least 20 items")
        return v


class APISourceConfig(BaseModel):
    """Configuration for an external API data source connector."""

    model_config = ConfigDict(frozen=True)

    url: str
    auth_type: Literal["none", "bearer", "api_key_header", "api_key_query"] = "none"
    auth_value: str | None = None
    json_path: str = "$"
    polling_hours: int = 24


class FieldMapping(BaseModel):
    """Maps a source field from an external API to an internal metric."""

    model_config = ConfigDict(frozen=True)

    source_field: str
    target_metric: str
    transform: Literal["raw", "yoy_pct", "mom_pct", "cumsum", "normalize"] = "raw"
    confidence: float = 0.0
