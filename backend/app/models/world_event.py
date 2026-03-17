# backend/app/models/world_event.py
"""WorldEvent model for per-round scenario event generation."""
from __future__ import annotations
from dataclasses import dataclass

_VALID_EVENT_TYPES: frozenset[str] = frozenset(
    {"shock", "rumor", "official", "grassroots"}
)


@dataclass(frozen=True)
class WorldEvent:
    """Immutable world event generated each simulation round.

    Active in kg_driven mode only. Drives information asymmetry between
    agents based on their info_diet vs event reach tags.
    """

    event_id: str
    round_number: int
    content: str
    event_type: str   # shock | rumor | official | grassroots
    # Info diet tags that receive this event. ("ALL",) = broadcast to all.
    reach: tuple[str, ...]
    # Metric ID → delta mapping. Keys validated against active scenario metrics.
    impact_vector: dict[str, float]
    # 0.0–1.0; modulates agent adoption rate.
    credibility: float

    def __post_init__(self) -> None:
        if self.event_type not in _VALID_EVENT_TYPES:
            raise ValueError(
                f"event_type must be one of {sorted(_VALID_EVENT_TYPES)}, "
                f"got '{self.event_type}'"
            )
        if not self.reach:
            raise ValueError("reach must not be empty")
        if not (0.0 <= self.credibility <= 1.0):
            raise ValueError(
                f"credibility must be in [0, 1], got {self.credibility}"
            )

    def reaches_agent(self, info_diet: tuple[str, ...] | list[str]) -> bool:
        """Return True if this event is visible to an agent with the given info_diet."""
        if "ALL" in self.reach:
            return True
        return bool(set(self.reach) & set(info_diet))
