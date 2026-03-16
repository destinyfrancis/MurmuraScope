"""Network evolution event models (Phase 1C).

All dataclasses are frozen (immutable) per project coding style.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class NetworkEvent:
    """A single structural change event in the social network.

    Attributes:
        session_id: Simulation session UUID.
        round_number: Round in which the event was detected.
        event_type: One of TIE_FORMED | TIE_DISSOLVED | BRIDGE_DETECTED |
            TRIADIC_CLOSURE | CLUSTER_SHIFT.
        agent_a_username: Primary agent involved in the event.
        agent_b_username: Secondary agent (if applicable).
        trust_delta: Change in trust score triggering the event.
        details: Extra context (cluster IDs, stance similarity, etc.).
    """

    session_id: str
    round_number: int
    event_type: str
    agent_a_username: str
    agent_b_username: str = ""
    trust_delta: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NetworkEvolutionStats:
    """Aggregate network topology statistics for one simulation round.

    Attributes:
        session_id: Simulation session UUID.
        round_number: Round number for this snapshot.
        ties_formed: Number of new positive trust ties (trust crossed 0.3).
        ties_dissolved: Number of dissolved trust ties (trust dropped below -0.1).
        bridges_detected: Agents connecting ≥2 distinct clusters.
        triadic_closures: A→B + B→C chains where A→C was suggested.
        cluster_shifts: Agents that moved to a different cluster.
        density: Edge density = edges / possible_edges.
        avg_trust: Mean trust score across all agent pairs.
    """

    session_id: str
    round_number: int
    ties_formed: int = 0
    ties_dissolved: int = 0
    bridges_detected: int = 0
    triadic_closures: int = 0
    cluster_shifts: int = 0
    density: float = 0.0
    avg_trust: float = 0.0
