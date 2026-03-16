"""Cognitive dissonance detector and resolver (Phase 3).

Detects when agent beliefs are internally inconsistent or contradict recent
actions, then selects and applies a resolution strategy modulated by the
agent's Big Five personality traits.
"""
from __future__ import annotations

import json
import random
from dataclasses import replace
from typing import Any

from backend.app.models.emotional_state import (
    BELIEF_CORRELATIONS,
    Belief,
    CognitiveDissonance,
)
from backend.app.utils.logger import get_logger

logger = get_logger("cognitive_dissonance")

# Map of decision action → belief topic that could conflict
_ACTION_BELIEF_MAP: dict[str, dict[str, float]] = {
    # Emigrating while being bullish on social stability
    "emigrate": {"social_stability": 0.3, "economy_outlook": 0.3},
    # Buying property while being bearish on property
    "buy_property": {"property_outlook": -0.3},
    # Selling property while being bullish on property
    "sell_property": {"property_outlook": 0.3},
    # Investing stocks while bearish on economy
    "invest_stocks": {"economy_outlook": -0.3},
    # Protest action while trusting government
    "protest": {"government_trust": 0.4},
    # Quit job while expecting stable economy
    "quit": {"economy_outlook": 0.3},
    # Having a child while pessimistic about economy or stability
    "have_child": {"economy_outlook": -0.2, "social_stability": -0.2},
}


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class DissonanceDetector:
    """Detect and resolve cognitive dissonance for simulation agents."""

    BELIEF_CONFLICT_WEIGHT: float = 0.6
    ACTION_BELIEF_WEIGHT: float = 0.4
    CONFLICT_THRESHOLD: float = 0.3        # Minimum stance diff × correlation to flag

    # Base resolution probabilities (modulated by personality)
    BASE_DENIAL_PROB: float = 0.4
    BASE_RATIONALIZATION_PROB: float = 0.3
    BASE_BELIEF_CHANGE_PROB: float = 0.2
    BASE_NONE_PROB: float = 0.1

    def detect(
        self,
        beliefs: list[Belief],
        recent_actions: list[str],
        profile: Any,
        rng: random.Random | None = None,
    ) -> CognitiveDissonance:
        """Detect cognitive dissonance from belief-belief conflicts and action-belief gaps.

        Algorithm:
        1. Check all belief pairs against BELIEF_CORRELATIONS matrix.
           Conflict score for pair (A, B) = max(0, expected_correlation_sign × stance_A × stance_B × (-1))
           i.e. positive expected correlation but opposite stances → conflict
        2. Check action-belief gap for each recent action using _ACTION_BELIEF_MAP.
        3. Composite score = 0.6 × belief_conflict + 0.4 × action_belief_gap
        4. Choose resolution strategy probabilistically (personality-modulated).

        Args:
            beliefs: Current belief list for the agent.
            recent_actions: Action types from this round (decision engine outputs).
            profile: AgentProfile with Big Five fields.
            rng: Optional RNG for deterministic strategy selection.

        Returns:
            :class:`CognitiveDissonance` dataclass (frozen).
        """
        _rng = rng or random
        belief_map = {b.topic: b for b in beliefs}

        # --- Belief-belief conflict ---
        conflict_scores: list[float] = []
        conflicting_pairs: list[tuple[str, str]] = []

        for (topic_a, topic_b), expected_corr in BELIEF_CORRELATIONS.items():
            belief_a = belief_map.get(topic_a)
            belief_b = belief_map.get(topic_b)
            if belief_a is None or belief_b is None:
                continue

            # Conflict = expected positive correlation but stances are opposite
            # Or expected negative correlation but stances are same sign
            actual_product = belief_a.stance * belief_b.stance
            expected_sign = 1.0 if expected_corr > 0 else -1.0
            conflict_contribution = max(0.0, -(expected_sign * actual_product) * abs(expected_corr))

            if conflict_contribution > self.CONFLICT_THRESHOLD * abs(expected_corr):
                conflict_scores.append(conflict_contribution)
                conflicting_pairs.append((topic_a, topic_b))

        belief_conflict_score = (
            sum(conflict_scores) / len(conflict_scores) if conflict_scores else 0.0
        )
        belief_conflict_score = _clamp(belief_conflict_score, 0.0, 1.0)

        # --- Action-belief gap ---
        action_gap_scores: list[float] = []
        for action in recent_actions:
            expected_beliefs = _ACTION_BELIEF_MAP.get(action, {})
            for topic, conflict_threshold_stance in expected_beliefs.items():
                belief = belief_map.get(topic)
                if belief is None:
                    continue
                # Gap: action implies belief stance in a direction; agent's actual stance conflicts
                # conflict_threshold_stance > 0 means action conflicts when agent's stance > threshold
                # conflict_threshold_stance < 0 means action conflicts when agent's stance < threshold
                if conflict_threshold_stance > 0 and belief.stance > conflict_threshold_stance:
                    gap = (belief.stance - conflict_threshold_stance) * belief.confidence
                    action_gap_scores.append(_clamp(gap, 0.0, 1.0))
                elif conflict_threshold_stance < 0 and belief.stance < conflict_threshold_stance:
                    gap = (conflict_threshold_stance - belief.stance) * belief.confidence
                    action_gap_scores.append(_clamp(gap, 0.0, 1.0))

        action_belief_gap = (
            sum(action_gap_scores) / len(action_gap_scores) if action_gap_scores else 0.0
        )
        action_belief_gap = _clamp(action_belief_gap, 0.0, 1.0)

        # --- Composite dissonance score ---
        dissonance_score = _clamp(
            self.BELIEF_CONFLICT_WEIGHT * belief_conflict_score
            + self.ACTION_BELIEF_WEIGHT * action_belief_gap,
            0.0,
            1.0,
        )

        # --- Resolution strategy (personality-modulated) ---
        strategy = self._choose_strategy(dissonance_score, profile, _rng)

        return CognitiveDissonance(
            agent_id=getattr(profile, "id", 0),
            session_id="",  # caller fills in
            round_number=0,  # caller fills in
            dissonance_score=round(dissonance_score, 4),
            conflicting_pairs=tuple(conflicting_pairs),
            action_belief_gap=round(action_belief_gap, 4),
            resolution_strategy=strategy,
        )

    def _choose_strategy(
        self,
        dissonance_score: float,
        profile: Any,
        rng: random.Random,
    ) -> str:
        """Choose resolution strategy probabilistically, modulated by Big Five.

        - High neuroticism → more denial (avoidance)
        - High openness → more belief_change (adaptability)
        - High agreeableness → more rationalization (social harmony)
        - Low dissonance → often 'none'

        Args:
            dissonance_score: Composite dissonance intensity.
            profile: AgentProfile.
            rng: Random instance.

        Returns:
            Strategy string: 'denial' | 'rationalization' | 'belief_change' | 'none'.
        """
        if dissonance_score < 0.1:
            return "none"

        neuroticism = _clamp(float(getattr(profile, "neuroticism", 0.5)), 0.0, 1.0)
        openness = _clamp(float(getattr(profile, "openness", 0.5)), 0.0, 1.0)
        agreeableness = _clamp(float(getattr(profile, "agreeableness", 0.5)), 0.0, 1.0)

        # Adjust base probabilities
        denial_p = self.BASE_DENIAL_PROB + 0.15 * (neuroticism - 0.5)
        rationalization_p = self.BASE_RATIONALIZATION_PROB + 0.1 * (agreeableness - 0.5)
        belief_change_p = self.BASE_BELIEF_CHANGE_PROB + 0.15 * (openness - 0.5)
        none_p = self.BASE_NONE_PROB

        # Scale by dissonance severity (low dissonance → more 'none')
        none_p = none_p + (1.0 - dissonance_score) * 0.2

        # Normalise
        total = denial_p + rationalization_p + belief_change_p + none_p
        if total < 1e-9:
            return "none"

        r = rng.random() * total
        cumulative = 0.0
        for strategy, prob in [
            ("denial", denial_p),
            ("rationalization", rationalization_p),
            ("belief_change", belief_change_p),
            ("none", none_p),
        ]:
            cumulative += prob
            if r <= cumulative:
                return strategy
        return "none"

    def apply_resolution(
        self,
        dissonance: CognitiveDissonance,
        beliefs: list[Belief],
    ) -> tuple[list[Belief], float]:
        """Apply resolution strategy to the agent's beliefs.

        Resolution strategies:
        - denial: Return unchanged beliefs + arousal_delta=0.1 (suppressed anxiety)
        - rationalization: Reduce weaker conflicting belief's confidence by ×0.7
        - belief_change: Shift weaker conflicting belief toward consistency
        - none: Return unchanged beliefs, no arousal delta

        Args:
            dissonance: Detected cognitive dissonance record.
            beliefs: Current belief list.

        Returns:
            Tuple of (updated_beliefs, arousal_delta_for_next_round).
        """
        strategy = dissonance.resolution_strategy
        belief_map = {b.topic: (i, b) for i, b in enumerate(beliefs)}
        updated = list(beliefs)

        if strategy == "denial":
            # Beliefs unchanged; arousal spike next round
            return updated, 0.1

        if strategy == "rationalization" and dissonance.conflicting_pairs:
            # Find weaker belief in first conflicting pair and reduce confidence
            topic_a, topic_b = dissonance.conflicting_pairs[0]
            idx_a, belief_a = belief_map.get(topic_a, (None, None))
            idx_b, belief_b = belief_map.get(topic_b, (None, None))

            if belief_a is not None and belief_b is not None:
                # Weaker = lower confidence
                if belief_a.confidence <= belief_b.confidence:
                    updated[idx_a] = replace(
                        belief_a,
                        confidence=round(belief_a.confidence * 0.7, 4),
                    )
                else:
                    updated[idx_b] = replace(
                        belief_b,
                        confidence=round(belief_b.confidence * 0.7, 4),
                    )
            return updated, 0.0

        if strategy == "belief_change" and dissonance.conflicting_pairs:
            topic_a, topic_b = dissonance.conflicting_pairs[0]
            idx_a, belief_a = belief_map.get(topic_a, (None, None))
            idx_b, belief_b = belief_map.get(topic_b, (None, None))

            if belief_a is not None and belief_b is not None:
                # Shift weaker belief toward the direction consistent with the pair correlation
                from backend.app.models.emotional_state import BELIEF_CORRELATIONS  # noqa: PLC0415
                expected_corr = BELIEF_CORRELATIONS.get(
                    (topic_a, topic_b),
                    BELIEF_CORRELATIONS.get((topic_b, topic_a), 0.0),
                )
                if belief_a.confidence <= belief_b.confidence:
                    # Shift belief_a toward the direction consistent with belief_b
                    target_stance = belief_b.stance * (1.0 if expected_corr > 0 else -1.0)
                    delta = 0.1 * (target_stance - belief_a.stance)
                    updated[idx_a] = replace(
                        belief_a,
                        stance=round(max(-1.0, min(1.0, belief_a.stance + delta)), 4),
                    )
                else:
                    target_stance = belief_a.stance * (1.0 if expected_corr > 0 else -1.0)
                    delta = 0.1 * (target_stance - belief_b.stance)
                    updated[idx_b] = replace(
                        belief_b,
                        stance=round(max(-1.0, min(1.0, belief_b.stance + delta)), 4),
                    )
            return updated, 0.0

        # strategy == "none"
        return updated, 0.0

    async def batch_detect_and_resolve(
        self,
        session_id: str,
        round_number: int,
        agent_beliefs: dict[int, list[Belief]],
        agent_actions: dict[int, list[str]],
        profiles: dict[int, Any],
        db: Any,
    ) -> tuple[dict[int, CognitiveDissonance], dict[int, float]]:
        """Run detect + resolve for all agents in one pass.

        Args:
            session_id: Simulation session UUID.
            round_number: Current round number.
            agent_beliefs: Current beliefs per agent.
            agent_actions: Recent action strings per agent.
            profiles: AgentProfile objects keyed by agent_id.
            db: Open aiosqlite connection.

        Returns:
            Tuple of:
            - dissonance_results: {agent_id: CognitiveDissonance}
            - pending_arousal_deltas: {agent_id: float} for next-round arousal injection
        """
        dissonance_results: dict[int, CognitiveDissonance] = {}
        pending_arousal_deltas: dict[int, float] = {}

        for agent_id, beliefs in agent_beliefs.items():
            profile = profiles.get(agent_id)
            if profile is None or not beliefs:
                continue

            actions = agent_actions.get(agent_id, [])
            raw = self.detect(beliefs, actions, profile)

            # Fill in session/round from context
            dissonance = replace(
                raw,
                session_id=session_id,
                round_number=round_number,
                agent_id=agent_id,
            )

            # Apply resolution — may update beliefs in place
            _updated_beliefs, arousal_delta = self.apply_resolution(dissonance, beliefs)

            dissonance_results[agent_id] = dissonance
            if arousal_delta > 0:
                pending_arousal_deltas[agent_id] = arousal_delta

        await self.persist_dissonance(list(dissonance_results.values()), db)
        return dissonance_results, pending_arousal_deltas

    async def persist_dissonance(
        self,
        results: list[CognitiveDissonance],
        db: Any,
    ) -> None:
        """Persist cognitive dissonance records to ``cognitive_dissonance`` table."""
        if not results:
            return
        rows = [
            (
                r.session_id,
                r.agent_id,
                r.round_number,
                r.dissonance_score,
                json.dumps(list(r.conflicting_pairs)),
                r.action_belief_gap,
                r.resolution_strategy,
            )
            for r in results
        ]
        await db.executemany(
            """INSERT OR REPLACE INTO cognitive_dissonance
               (session_id, agent_id, round_number, dissonance_score,
                conflicting_pairs_json, action_belief_gap, resolution_strategy)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        await db.commit()
