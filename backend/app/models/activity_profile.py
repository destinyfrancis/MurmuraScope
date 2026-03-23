"""Temporal activity profile for simulation agents.

Each agent has a 24-dimensional activity vector where index i represents
the probability of the agent being active during hour i of the day
(0 = midnight, 8 = 8 AM, 20 = 8 PM).

Chronotypes:
  - morning_lark: peaks 06–10 AM (elderly, retirees)
  - standard:     peaks 09 AM and 19–22 PM (office workers)
  - evening_owl:  peaks 19 PM–midnight (students, young adults)
  - night_shift:  peaks 00–04 AM and 20–23 PM (manual/transport workers)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Chronotype = Literal["morning_lark", "standard", "evening_owl", "night_shift"]

VALID_CHRONOTYPES: frozenset[str] = frozenset({"morning_lark", "standard", "evening_owl", "night_shift"})

_ACTIVITY_VECTOR_LEN: int = 24


@dataclass(frozen=True)
class ActivityProfile:
    """Immutable 24-dim temporal activity profile for a simulation agent.

    Attributes:
        agent_id: Matches agent_profiles.id.
        chronotype: Determines the shape of the daily activity curve.
        activity_vector: 24 floats in [0.0, 1.0], one per clock hour.
            Index 0 = midnight, index 8 = 8 AM, index 20 = 8 PM.
        base_activity_rate: Per-agent scaling factor in (0.0, 1.0].
            A rate of 0.65 means the agent participates ~65 % of
            their peak-hour rounds after the curve is applied.
    """

    agent_id: int
    chronotype: Chronotype
    activity_vector: tuple[float, ...]  # exactly 24 elements
    base_activity_rate: float

    def __post_init__(self) -> None:
        if len(self.activity_vector) != _ACTIVITY_VECTOR_LEN:
            raise ValueError(
                f"activity_vector must have exactly {_ACTIVITY_VECTOR_LEN} elements, got {len(self.activity_vector)}"
            )
        if self.chronotype not in VALID_CHRONOTYPES:
            raise ValueError(f"Unknown chronotype: {self.chronotype!r}. Valid: {sorted(VALID_CHRONOTYPES)}")
        if not (0.0 < self.base_activity_rate <= 1.0):
            raise ValueError(f"base_activity_rate must be in (0.0, 1.0], got {self.base_activity_rate}")

    def probability_at_hour(self, hour: int) -> float:
        """Activation probability at a given clock hour (0–23).

        Returns activity_vector[hour] × base_activity_rate.
        Falls back to 0.0 for out-of-range hour values.
        """
        if not 0 <= hour <= 23:
            return 0.0
        return self.activity_vector[hour] * self.base_activity_rate
