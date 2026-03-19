"""Time configuration for simulation temporal mapping.

Inspired by MiroFish/OASIS time engine: LLM infers scenario-appropriate
time granularity (e.g. social media → 72h/60min per round;
geopolitics → 30d/1d per round). User can override.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TimeConfig:
    """Immutable time mapping for a simulation session.

    Attributes:
        total_simulated_hours: Total real-world hours the simulation covers.
        minutes_per_round: How many real-world minutes each round represents.
        round_label_unit: Display unit for round labels ("hour", "day", "week", "month").
        rationale: LLM-generated explanation for the chosen time mapping.
    """

    total_simulated_hours: int
    minutes_per_round: int
    round_label_unit: str
    rationale: str

    def round_label(self, round_number: int) -> str:
        """Human-readable label for a round number."""
        unit_display = {
            "hour": "Hour",
            "day": "Day",
            "week": "Week",
            "month": "Month",
        }
        return f"{unit_display.get(self.round_label_unit, self.round_label_unit)} {round_number}"

    def to_dict(self) -> dict:
        """Serialise for storage in session config_json."""
        return {
            "total_simulated_hours": self.total_simulated_hours,
            "minutes_per_round": self.minutes_per_round,
            "round_label_unit": self.round_label_unit,
            "rationale": self.rationale,
        }
