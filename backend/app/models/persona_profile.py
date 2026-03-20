"""Persona profile models for interview-grounded agent initialization.

Allows researchers to upload CSV/JSON files with real participant data
to initialize agents from actual interview/survey responses rather than
purely LLM-generated synthetic profiles.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator


class PersonaProfile(BaseModel):
    """A single participant profile from survey or interview data."""

    model_config = ConfigDict(frozen=True)

    name: str
    role: str
    age: int | None = None
    occupation: str | None = None
    beliefs: str | None = None
    goals: str | None = None
    political_stance: float | None = None  # 0.0 (pro-establishment) … 1.0 (pro-democracy)
    personality_traits: dict[str, float] | None = None  # Big Five keys in [0, 1]
    background: str | None = None

    @field_validator("political_stance")
    @classmethod
    def _clamp_stance(cls, v: float | None) -> float | None:
        if v is None:
            return v
        return max(0.0, min(1.0, v))

    @field_validator("name", "role")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name and role must not be empty")
        return v.strip()
