"""Supply chain cascade propagation for kg_driven simulations.

When an upstream entity fails (bankruptcy, strike, disruption), downstream
entities connected via supply-chain KG edges receive a cascading revenue shock.

Design:
  - Cascade threshold: any upstream failure propagates downstream
  - Propagation factor: 40% of upstream impact reaches each downstream entity
  - Recovery delay: 3 rounds to find alternate sourcing
  - Bullwhip amplification: each hop amplifies impact by 10%
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("supply_chain_cascade")

# Supply-chain edge types that represent upstream-downstream dependency
_SUPPLY_EDGE_TYPES = frozenset(
    {
        "SUPPLIES_TO",
        "BUYS_FROM",
        "DEPENDS_ON",
        "DISTRIBUTES",
    }
)

# Bullwhip amplification per hop (10%)
_BULLWHIP_FACTOR = 0.10

# Default recovery rounds before alternate sourcing kicks in
_DEFAULT_RECOVERY_ROUNDS = 3


@dataclass(frozen=True)
class CascadeEffect:
    """Immutable record of a supply chain cascade impact on a downstream entity."""

    target_entity_id: str
    revenue_impact: float  # negative = loss
    source_entity_id: str
    hop_distance: int
    recovery_rounds: int  # rounds until effect fades


async def propagate_supply_chain_shock(
    session_id: str,
    failed_entity_ids: frozenset[str],
    propagation_factor: float = 0.4,
    max_hops: int = 3,
) -> tuple[CascadeEffect, ...]:
    """Propagate failure through supply chain KG edges.

    Args:
        session_id: Simulation session UUID.
        failed_entity_ids: Set of entity IDs that have failed/disrupted.
        propagation_factor: Fraction of upstream impact that propagates
            to each downstream entity (default 0.4 = 40%).
        max_hops: Maximum propagation depth (default 3).

    Returns:
        Frozen tuple of CascadeEffect objects describing downstream impacts.
    """
    # Load all supply-chain edges for this session
    async with get_db() as db:
        cursor = await db.execute(
            """SELECT source_id, target_id, relation_type
               FROM kg_edges
               WHERE session_id = ?""",
            (session_id,),
        )
        all_edges = await cursor.fetchall()

    # Build adjacency map: source → [(target, relation_type)]
    adjacency: dict[str, list[str]] = {}
    for edge in all_edges:
        rel_type = edge["relation_type"]
        if rel_type in _SUPPLY_EDGE_TYPES:
            source = edge["source_id"]
            target = edge["target_id"]
            adjacency.setdefault(source, []).append(target)

    if not adjacency:
        return ()

    # BFS cascade propagation
    effects: list[CascadeEffect] = []
    # Track: (entity_id, impact_magnitude, hop) — impact_magnitude is positive (loss fraction)
    current_wave: list[tuple[str, float, str]] = [(eid, 1.0, eid) for eid in failed_entity_ids]
    visited: set[str] = set(failed_entity_ids)

    for hop in range(1, max_hops + 1):
        next_wave: list[tuple[str, float, str]] = []

        for failed_id, upstream_impact, original_source in current_wave:
            downstream_targets = adjacency.get(failed_id, [])

            for target_id in downstream_targets:
                if target_id in visited:
                    continue
                visited.add(target_id)

                # Bullwhip: each hop amplifies by 10%
                bullwhip = 1.0 + _BULLWHIP_FACTOR * (hop - 1)
                revenue_loss = -(upstream_impact * propagation_factor * bullwhip)

                effect = CascadeEffect(
                    target_entity_id=target_id,
                    revenue_impact=round(revenue_loss, 4),
                    source_entity_id=original_source,
                    hop_distance=hop,
                    recovery_rounds=_DEFAULT_RECOVERY_ROUNDS,
                )
                effects.append(effect)
                next_wave.append((target_id, abs(revenue_loss), original_source))

        if not next_wave:
            break
        current_wave = next_wave

    logger.info(
        "Supply chain cascade: session=%s failed=%d effects=%d max_hop_reached=%d",
        session_id,
        len(failed_entity_ids),
        len(effects),
        max(e.hop_distance for e in effects) if effects else 0,
    )

    return tuple(effects)
