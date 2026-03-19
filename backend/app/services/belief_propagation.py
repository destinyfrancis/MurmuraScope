# backend/app/services/belief_propagation.py
"""Embedding-based belief propagation engine for kg_driven simulation mode.

Replaces BeliefSystem keyword matching with cosine similarity + cognitive
fingerprint modulation. Active in kg_driven mode only.
"""
from __future__ import annotations

import asyncio
import math
from typing import Any

from backend.app.models.cognitive_fingerprint import CognitiveFingerprint
from backend.app.models.world_event import WorldEvent
from backend.app.utils.logger import get_logger

logger = get_logger(__name__)


async def get_embedding(text: str) -> list[float]:
    """Get 384-dim embedding for text using the existing EmbeddingProvider.

    EmbeddingProvider.embed_single() is synchronous (sentence-transformers),
    so we wrap it in asyncio.to_thread to avoid blocking the event loop.
    """
    from backend.app.services.embedding_provider import EmbeddingProvider  # noqa: PLC0415
    provider = EmbeddingProvider()
    result = await asyncio.to_thread(provider.embed_single, text)
    return result.tolist()


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


class BeliefPropagationEngine:
    """Compute belief deltas from world events using embedding similarity.

    Algorithm per event per agent:
    1. Skip if agent cannot receive this event (info_diet vs reach)
    2. Compute raw delta: event impact_vector * credibility * susceptibility
    3. Dampen contradicting evidence by confirmation_bias:
       effective_delta = raw_delta * (1 - confirmation_bias) [if contradicting]
    4. Blend with faction peer stance via conformity:
       final_delta = effective_delta * (1 - conformity) + peer_delta * conformity
    """

    async def propagate(
        self,
        fingerprint: CognitiveFingerprint,
        events: list[WorldEvent],
        faction_peer_stance: dict[str, float],
        active_metrics: tuple[str, ...],
        current_beliefs: dict[str, float],
    ) -> dict[str, float]:
        """Return belief delta per metric ID.

        Args:
            fingerprint: Agent's cognitive fingerprint.
            events: WorldEvents generated this round.
            faction_peer_stance: Average stance of agent's faction peers.
            active_metrics: Metric IDs from UniversalScenarioConfig.
            current_beliefs: Agent's current belief values per metric.

        Returns:
            Dict of metric_id → delta (positive = increase, negative = decrease).
            Keys are guaranteed to be a subset of active_metrics.
        """
        active_set = set(active_metrics)
        accumulated: dict[str, float] = {m: 0.0 for m in active_metrics}

        for event in events:
            if not event.reaches_agent(fingerprint.info_diet):
                continue

            for metric_id, impact in event.impact_vector.items():
                if metric_id not in active_set:
                    continue

                susceptibility = fingerprint.susceptibility.get(metric_id, 0.5)
                raw_delta = impact * event.credibility * susceptibility

                # Dampen if this contradicts current belief direction.
                # An agent holding a strong belief (far from 0.5) resists evidence
                # that pushes them further away from their anchored position.
                # Strong low belief (< 0.5) → resists upward pressure.
                # Strong high belief (> 0.5) → resists downward pressure.
                current = current_beliefs.get(metric_id, 0.5)
                contradicting = (raw_delta > 0 and current < 0.5) or (raw_delta < 0 and current > 0.5)
                if contradicting:
                    raw_delta *= (1.0 - fingerprint.confirmation_bias)

                accumulated[metric_id] = accumulated.get(metric_id, 0.0) + raw_delta

        # Blend with faction peer pressure via conformity.
        # Hegselmann-Krause bounded confidence: agents only update from peers
        # whose belief is within epsilon of their own current belief.
        # Effective epsilon scales with openness: open agents accept wider range.
        _BC_EPSILON = 0.4  # base bounded-confidence radius

        final: dict[str, float] = {}
        for metric_id in active_metrics:
            event_delta = accumulated.get(metric_id, 0.0)
            peer_current = faction_peer_stance.get(metric_id, current_beliefs.get(metric_id, 0.5))
            current = current_beliefs.get(metric_id, 0.5)

            # Hegselmann-Krause: ignore faction peers too far from current belief
            openness = getattr(fingerprint, "openness", 0.5)
            effective_epsilon = _BC_EPSILON * (0.5 + 0.5 * openness)
            if abs(peer_current - current) <= effective_epsilon:
                peer_delta = fingerprint.conformity * (peer_current - current) * 0.1
            else:
                peer_delta = 0.0  # ignore distant peers

            blended = event_delta * (1.0 - fingerprint.conformity) + peer_delta
            if abs(blended) > 0.001:  # skip negligible deltas
                final[metric_id] = blended

        return final

    def cascade(
        self,
        all_deltas: dict[str, dict[str, float]],
        interaction_graph: dict[str, list[str]],
    ) -> dict[str, dict[str, float]]:
        """1-hop belief cascade: agents with large shifts pull neighbours slightly.

        When an agent's belief shifts by more than ``_SHIFT_THRESHOLD`` in a
        round, each of its direct interaction partners receives a dampened
        pull in the same direction.  Capped at 1 hop to prevent runaway
        oscillation or artificial consensus formation.

        Args:
            all_deltas: Per-agent belief deltas from this round's propagation.
            interaction_graph: Adjacency list (agent_id → list of agent_ids).

        Returns:
            Additional deltas for each affected neighbour agent.
        """
        _SHIFT_THRESHOLD = 0.1   # minimum shift magnitude to trigger cascade
        _CASCADE_FACTOR = 0.3    # base: neighbour receives 30% of the original shift
        _LEADERSHIP_BOOST = 0.5  # max additional factor for high-influence agents

        # Pre-compute out-degree for opinion leadership: agents with more
        # connections exert proportionally stronger cascade influence.
        # Degree is normalised to [0, 1] relative to the maximum in the graph.
        all_degrees = {
            agent_id: len(neighbours)
            for agent_id, neighbours in interaction_graph.items()
        }
        max_degree = max(all_degrees.values()) if all_degrees else 1
        max_degree = max(max_degree, 1)  # guard against empty graph

        cascade_out: dict[str, dict[str, float]] = {}

        for agent_id, deltas in all_deltas.items():
            # Leadership score: normalised out-degree as a proxy for influence
            degree = all_degrees.get(agent_id, 0)
            leadership_score = degree / max_degree  # [0, 1]
            effective_factor = _CASCADE_FACTOR * (1.0 + _LEADERSHIP_BOOST * leadership_score)

            for metric_id, delta in deltas.items():
                if abs(delta) < _SHIFT_THRESHOLD:
                    continue
                for neighbor_id in interaction_graph.get(agent_id, []):
                    if neighbor_id == agent_id:
                        continue
                    if neighbor_id not in cascade_out:
                        cascade_out[neighbor_id] = {}
                    existing = cascade_out[neighbor_id].get(metric_id, 0.0)
                    cascade_out[neighbor_id][metric_id] = existing + delta * effective_factor

        return cascade_out
