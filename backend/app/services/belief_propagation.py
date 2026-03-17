# backend/app/services/belief_propagation.py
"""Embedding-based belief propagation engine for kg_driven simulation mode.

Replaces BeliefSystem keyword matching with cosine similarity + cognitive
fingerprint modulation. Active in kg_driven mode only.
"""
from __future__ import annotations

import math
from typing import Any

from backend.app.models.cognitive_fingerprint import CognitiveFingerprint
from backend.app.models.world_event import WorldEvent
from backend.app.utils.logger import get_logger

logger = get_logger(__name__)


def get_embedding(text: str) -> list[float]:
    """Get 384-dim embedding for text using the existing EmbeddingProvider.

    EmbeddingProvider.embed_single() is synchronous (sentence-transformers).
    Call directly — do NOT await.
    """
    from backend.app.services.embedding_provider import EmbeddingProvider  # noqa: PLC0415
    provider = EmbeddingProvider()
    return provider.embed_single(text).tolist()


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

        # Blend with faction peer pressure via conformity
        final: dict[str, float] = {}
        for metric_id in active_metrics:
            event_delta = accumulated.get(metric_id, 0.0)
            peer_current = faction_peer_stance.get(metric_id, current_beliefs.get(metric_id, 0.5))
            current = current_beliefs.get(metric_id, 0.5)
            peer_delta = peer_current - current  # direction peer is pulling

            blended = (
                event_delta * (1.0 - fingerprint.conformity)
                + peer_delta * fingerprint.conformity * 0.1  # conformity has gentle pull
            )
            if abs(blended) > 0.001:  # skip negligible deltas
                final[metric_id] = blended

        return final
