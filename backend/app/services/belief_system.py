"""Belief system: Bayesian belief updates with confirmation bias (Phase 3).

Maintains 6 core belief topics for each agent. Updates apply confirmation bias
modulated by the agent's openness trait (Big Five). Beliefs are persisted to
the ``belief_states`` table.
"""
from __future__ import annotations

import math
import re
from dataclasses import replace
from typing import Any

from backend.app.models.emotional_state import (
    CORE_BELIEF_TOPICS,
    Belief,
    BeliefState,
)
from backend.app.utils.logger import get_logger

logger = get_logger("belief_system")

# ---------------------------------------------------------------------------
# Keyword maps for rule-based stance extraction from text
# ---------------------------------------------------------------------------

_TOPIC_KEYWORDS: dict[str, dict[str, list[str]]] = {
    "property_outlook": {
        "positive": ["樓市向好", "升市", "樓價上升", "買樓", "投資物業", "property rising",
                     "house prices up", "real estate boom", "purchase property"],
        "negative": ["樓市下跌", "跌市", "樓價下降", "賣樓", "負資產", "property crash",
                     "house prices down", "real estate bust", "sell property"],
    },
    "economy_outlook": {
        "positive": ["經濟復甦", "增長", "繁榮", "就業增加", "GDP增長", "economic recovery",
                     "growth", "boom", "jobs growth", "GDP growth"],
        "negative": ["經濟衰退", "下跌", "失業", "蕭條", "裁員", "recession", "downturn",
                     "unemployment", "depression", "layoffs"],
    },
    "immigration_stance": {
        "positive": ["移民好", "歡迎移民", "多元文化", "open immigration", "welcome immigrants",
                     "multicultural", "diversity"],
        "negative": ["反移民", "移民問題", "外來人口", "限制移民", "anti-immigration",
                     "immigration problem", "restrict immigration", "limit migrants"],
    },
    "government_trust": {
        "positive": ["信任政府", "政府做得好", "支持政府", "有效施政", "trust government",
                     "government doing well", "support government", "effective policy"],
        "negative": ["不信任政府", "政府失職", "反對政府", "腐敗", "distrust government",
                     "government failure", "oppose government", "corruption"],
    },
    "social_stability": {
        "positive": ["社會穩定", "和諧", "秩序", "安全", "social stability", "harmony",
                     "order", "safety", "peaceful"],
        "negative": ["社會動盪", "不安", "示威", "衝突", "social unrest", "instability",
                     "protest", "conflict", "turmoil"],
    },
    "ai_impact": {
        "positive": ["人工智能好", "AI機遇", "科技進步", "自動化好處", "AI benefits",
                     "tech opportunity", "automation advantage", "AI positive"],
        "negative": ["人工智能威脅", "AI搶工", "科技失業", "自動化壞處", "AI threat",
                     "AI taking jobs", "tech unemployment", "automation risk"],
    },
}


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp *value* to [lo, hi]."""
    return max(lo, min(hi, value))


class BeliefSystem:
    """Manages agent belief updates using Bayesian inference with confirmation bias."""

    CONFIRMATION_BIAS_BOOST: float = 1.3    # Weight multiplier when evidence matches prior
    CONFIRMATION_BIAS_RESIST: float = 0.6   # Weight multiplier when evidence contradicts prior
    # Confidence gain per confirming evidence unit.
    # Calibrated to Anderson (1981) Information Integration Theory:
    # social media posts are weak-weight stimuli (~0.05–0.10 on a 0–1 scale).
    # With effective_weight ≈ 0.5 (average openness × bias), each post shifts
    # confidence by ~0.025, so ~40 congruent posts reach max confidence —
    # consistent with Festinger (1957) attitude crystallisation timescales.
    CONFIDENCE_INCREMENT: float = 0.05
    CONFIDENCE_DECREMENT_FACTOR: float = 0.7  # Reduction multiplier when evidence contradicts prior
    _CONFIDENCE_FLOOR: float = 0.1          # Minimum confidence (beliefs never vanish entirely)

    def initialize_beliefs(
        self,
        agent_id: int,
        session_id: str,
        profile: Any,
        rng: Any = None,
    ) -> list[Belief]:
        """Create initial belief set from agent profile attributes.

        Initial stances are derived from:
        - property_outlook: from district + income
        - economy_outlook: from income + occupation
        - immigration_stance: from age + political_stance
        - government_trust: from political_stance
        - social_stability: from district
        - ai_impact: from age + occupation

        Args:
            agent_id: DB agent ID (unused here but available for future use).
            session_id: Simulation session UUID (unused here).
            profile: AgentProfile with demographic and Big Five fields.
            rng: Optional random.Random for noise (not used in deterministic init).

        Returns:
            List of 6 :class:`Belief` objects, one per core topic.
        """
        import random as _random  # noqa: PLC0415
        _rng = rng or _random

        political_stance = float(getattr(profile, "political_stance", 0.5))
        age = int(getattr(profile, "age", 35))
        occupation = getattr(profile, "occupation", "")
        income_bracket = getattr(profile, "income_bracket", "中收入")
        district = getattr(profile, "district", "")
        openness = float(getattr(profile, "openness", 0.5))

        # --- property_outlook ---
        # Higher income → more bullish; lower income → more bearish
        income_scores = {
            "低收入": -0.4, "中低收入": -0.1, "中收入": 0.1,
            "中高收入": 0.3, "高收入": 0.5,
        }
        prop_stance = income_scores.get(income_bracket, 0.0)
        # Adjust for district (e.g. expensive districts → residents may be more cynical)
        if district in ("中西區", "灣仔", "南區"):
            prop_stance -= 0.1  # expensive areas, feel the pinch more
        beliefs = [Belief(topic="property_outlook", stance=_clamp(prop_stance, -1.0, 1.0),
                          confidence=0.4 + 0.1 * openness)]

        # --- economy_outlook ---
        # Tech/finance workers → slightly more optimistic; manual workers → less
        tech_occs = ("IT", "金融", "科技", "engineer", "finance", "tech")
        manual_occs = ("服務業", "製造業", "建造業", "food", "service", "construction")
        econ_stance = 0.0
        if any(o in occupation for o in tech_occs):
            econ_stance = 0.2
        elif any(o in occupation for o in manual_occs):
            econ_stance = -0.1
        # Higher income boosts optimism
        econ_stance += income_scores.get(income_bracket, 0.0) * 0.5
        beliefs.append(Belief(topic="economy_outlook", stance=_clamp(econ_stance, -1.0, 1.0),
                               confidence=0.45))

        # --- immigration_stance ---
        # Younger agents more open; older more cautious
        # Political stance: pan-dem (1) → more open; pro-est (0) → more restrictive
        age_factor = -0.2 if age > 55 else (0.1 if age < 35 else 0.0)
        pol_factor = (political_stance - 0.5) * 0.4
        imm_stance = age_factor + pol_factor
        beliefs.append(Belief(topic="immigration_stance", stance=_clamp(imm_stance, -1.0, 1.0),
                               confidence=0.5))

        # --- government_trust ---
        # Directly derived from political stance: pro-establishment → trusts government
        # Political stance 0 (建制) → high trust; 1 (民主) → low trust
        gov_stance = 0.3 - 0.6 * political_stance
        beliefs.append(Belief(topic="government_trust", stance=_clamp(gov_stance, -1.0, 1.0),
                               confidence=0.5))

        # --- social_stability ---
        # New Territories districts tend to be slightly more conservative
        nt_districts = ("沙田", "元朗", "屯門", "北區", "大埔", "西貢", "葵青", "荃灣")
        stability_bias = 0.1 if district in nt_districts else 0.0
        # More stable view with higher income
        stability_stance = stability_bias + income_scores.get(income_bracket, 0.0) * 0.3
        beliefs.append(Belief(topic="social_stability", stance=_clamp(stability_stance, -1.0, 1.0),
                               confidence=0.4))

        # --- ai_impact ---
        # Younger + tech workers → more positive on AI; older + manual → more concerned
        tech_ai_bonus = 0.2 if any(o in occupation for o in tech_occs) else 0.0
        age_ai = -0.15 if age > 55 else (0.15 if age < 30 else 0.0)
        ai_stance = tech_ai_bonus + age_ai
        beliefs.append(Belief(topic="ai_impact", stance=_clamp(ai_stance, -1.0, 1.0),
                               confidence=0.35))

        return beliefs

    # ------------------------------------------------------------------
    # Domain transforms: [-1, +1] stance <-> (0, 1) probability
    # ------------------------------------------------------------------

    @staticmethod
    def _stance_to_prob(stance: float) -> float:
        """Map [-1, +1] stance to (0, 1) probability domain."""
        return max(0.02, min(0.98, (stance + 1.0) / 2.0))

    @staticmethod
    def _prob_to_stance(prob: float) -> float:
        """Map (0, 1) probability back to [-1, +1] stance domain."""
        return max(-0.98, min(0.98, prob * 2.0 - 1.0))

    # ------------------------------------------------------------------
    # Bayesian core
    # ------------------------------------------------------------------

    @staticmethod
    def _bayesian_core(prior: float, likelihood_ratio: float) -> float:
        """Core Bayes update on [0,1] probability scale.

        P(H|E) = P(H) * LR / (P(H) * LR + (1 - P(H)))
        """
        prior = max(0.02, min(0.98, prior))
        if likelihood_ratio <= 0:
            return prior
        numerator = prior * likelihood_ratio
        denominator = numerator + (1.0 - prior)
        if denominator < 1e-9:
            return prior
        return max(0.02, min(0.98, numerator / denominator))

    def compute_likelihood_ratio(
        self,
        evidence_stance: float,
        evidence_weight: float,
        belief_stance: float,
        confirmation_bias: float = 0.5,
    ) -> float:
        """Compute likelihood ratio from evidence.

        Always returns LR >= 1 representing evidence strength.
        Confirmation bias modulates the magnitude:
        - Same-direction evidence gets a bias boost (larger LR)
        - Opposite-direction evidence gets dampened (smaller LR, closer to 1)

        Direction is handled by the caller (bayesian_update) by choosing
        which probability space to apply the LR in.
        """
        if evidence_weight < 1e-9:
            return 1.0
        base_lr = 1.0 + abs(evidence_stance) * evidence_weight
        same_direction = (evidence_stance >= 0) == (belief_stance >= 0)
        bias_factor = confirmation_bias * 0.3
        if same_direction:
            return base_lr * (1.0 + bias_factor)
        else:
            # Dampen contradicting evidence: LR stays >= 1 but is reduced
            dampened = 1.0 + (base_lr - 1.0) * max(0.0, 1.0 - bias_factor)
            return max(1.0, dampened)

    # ------------------------------------------------------------------
    # Primary update method: true Bayesian
    # ------------------------------------------------------------------

    def bayesian_update(
        self,
        belief: Belief,
        evidence_stance: float,
        evidence_weight: float,
        openness: float,
    ) -> Belief:
        """True Bayesian belief update on [-1, +1] stance scale.

        Transforms: stance -> probability -> Bayes update -> probability -> stance

        Args:
            belief: Current belief to update.
            evidence_stance: Stance in evidence (-1..+1).
            evidence_weight: Credibility/weight of evidence (0..1 typically).
            openness: Agent Big Five openness (0..1).

        Returns:
            Updated :class:`Belief` (frozen -- new object).
        """
        if evidence_weight < 1e-9:
            return belief

        confirmation_bias = max(0.0, 1.0 - openness)
        lr = self.compute_likelihood_ratio(
            evidence_stance, evidence_weight, belief.stance, confirmation_bias,
        )

        prob = self._stance_to_prob(belief.stance)

        # The LR is always >= 1 (evidence strength).  Direction is determined
        # by the sign of evidence_stance:
        #   positive evidence → push prob toward 1 (stance toward +1)
        #   negative evidence → push prob toward 0 (stance toward -1)
        #
        # For negative evidence we work in the complementary space:
        #   apply LR to (1 - prob), which increases (1 - prob) and thus
        #   decreases prob, moving stance toward -1.
        if evidence_stance < 0:
            complement = 1.0 - prob
            posterior_complement = self._bayesian_core(complement, lr)
            posterior_prob = 1.0 - posterior_complement
            posterior_prob = max(0.02, min(0.98, posterior_prob))
        else:
            posterior_prob = self._bayesian_core(prob, lr)

        new_stance = self._prob_to_stance(posterior_prob)

        same_direction = (evidence_stance >= 0) == (belief.stance >= 0)
        if same_direction:
            new_confidence = min(1.0, belief.confidence + self.CONFIDENCE_INCREMENT * evidence_weight)
        else:
            reduction = self.CONFIDENCE_INCREMENT * evidence_weight * self.CONFIDENCE_DECREMENT_FACTOR
            new_confidence = max(self._CONFIDENCE_FLOOR, belief.confidence - reduction)

        return replace(
            belief,
            stance=round(new_stance, 4),
            confidence=round(new_confidence, 4),
            evidence_count=belief.evidence_count + 1,
        )

    def update_belief(
        self,
        belief: Belief,
        evidence_stance: float,
        evidence_weight: float,
        openness: float,
    ) -> Belief:
        """Apply a single piece of evidence via true Bayesian update.

        Delegates to :meth:`bayesian_update`. Kept for backward compatibility.
        """
        return self.bayesian_update(belief, evidence_stance, evidence_weight, openness)

    # ------------------------------------------------------------------
    # Legacy linear-weighted update (kept as fallback)
    # ------------------------------------------------------------------

    def update_belief_legacy(
        self,
        belief: Belief,
        evidence_stance: float,
        evidence_weight: float,
        openness: float,
    ) -> Belief:
        """Legacy linear-weighted belief update with confirmation bias.

        Confirmation bias is modulated by the agent's openness:
        - Low openness -> stronger confirmation bias
        - High openness -> near-unbiased update

        Formula:
            effective_weight = evidence_weight * bias_factor
            posterior = (confidence * prior + effective_weight * evidence) /
                        (confidence + effective_weight)
            new_confidence = min(1.0, confidence + INCREMENT * effective_weight)

        Args:
            belief: Current belief to update.
            evidence_stance: Stance in evidence (-1..+1).
            evidence_weight: Credibility/weight of evidence (0..1 typically).
            openness: Agent Big Five openness (0..1).

        Returns:
            Updated :class:`Belief` (frozen -- new object).
        """
        # Sigmoid confirmation bias: extreme beliefs resist/boost more strongly.
        # The sigmoid steepness k grows with confirmation_bias (default 0.5) and
        # is dampened by openness, so open-minded agents converge toward 1.0.
        # distance_from_center measures how extreme the current stance is (0..1).
        distance_from_center = abs(belief.stance)  # stance in [-1, 1]
        k = 4.0 * 0.5 * (1.0 - openness * 0.5)  # steepness; openness dampens
        # sigmoid in (0.5, 1.0) -- higher at extremes, lower near center
        sigmoid_val = 1.0 / (1.0 + math.exp(-k * distance_from_center))
        # Map to bias multiplier: same direction -> boost (>1), opposing -> resist (<1)
        same_direction = (evidence_stance >= 0) == (belief.stance >= 0)
        if same_direction:
            # Scale sigmoid [0.5, 1.0] -> boost [1.0, BOOST]
            effective_bias = 1.0 + (self.CONFIRMATION_BIAS_BOOST - 1.0) * (sigmoid_val - 0.5) * 2.0
        else:
            # Scale sigmoid [0.5, 1.0] -> resist [1.0, RESIST] (inverted: more extreme = more resist)
            effective_bias = 1.0 - (1.0 - self.CONFIRMATION_BIAS_RESIST) * (sigmoid_val - 0.5) * 2.0

        effective_weight = evidence_weight * effective_bias

        # Linear weighted posterior
        denom = belief.confidence + effective_weight
        if denom < 1e-9:
            return belief

        new_stance = (belief.confidence * belief.stance + effective_weight * evidence_stance) / denom
        # Confirming evidence builds confidence; contradictory evidence erodes it.
        if same_direction:
            new_confidence = min(1.0, belief.confidence + self.CONFIDENCE_INCREMENT * effective_weight)
        else:
            reduction = self.CONFIDENCE_INCREMENT * effective_weight * self.CONFIDENCE_DECREMENT_FACTOR
            new_confidence = max(self._CONFIDENCE_FLOOR, belief.confidence - reduction)

        return replace(
            belief,
            stance=_clamp(round(new_stance, 4), -1.0, 1.0),
            confidence=round(new_confidence, 4),
            evidence_count=belief.evidence_count + 1,
        )

    async def batch_update_from_feed(
        self,
        session_id: str,
        round_number: int,
        agent_beliefs: dict[int, list[Belief]],
        feed_data: dict[int, list[str]],
        trust_scores: dict[tuple[int, int], float],
        profiles: dict[int, Any],
        db: Any,
        simulation_mode: str = "hk_demographic",
    ) -> dict[int, list[Belief]]:
        """Update all agents' beliefs from feed posts this round.

        For each agent, scans their feed posts for topic-relevant stances
        using :meth:`extract_stance` and applies Bayesian updates.

        In ``kg_driven`` mode this method is a no-op: beliefs are managed
        directly by :class:`BeliefPropagationEngine` via WorldEvents, so
        the HK-specific keyword pipeline should not run.

        Args:
            session_id: Simulation session UUID.
            round_number: Current round number.
            agent_beliefs: Current beliefs keyed by agent_id.
            feed_data: Posts seen by each agent: {agent_id: [post_text, ...]}.
            trust_scores: Trust edge weights {(reader_id, author_id): score}.
            profiles: AgentProfile objects keyed by agent_id.
            db: Open aiosqlite connection.
            simulation_mode: ``"hk_demographic"`` (default) or ``"kg_driven"``.

        Returns:
            Updated beliefs keyed by agent_id.
        """
        if simulation_mode == "kg_driven":
            # kg_driven mode: BeliefPropagationEngine handles belief updates
            # via WorldEvents. This keyword-matching pipeline is a no-op.
            return dict(agent_beliefs)
        updated: dict[int, list[Belief]] = {}

        for agent_id, beliefs in agent_beliefs.items():
            profile = profiles.get(agent_id)
            openness = float(getattr(profile, "openness", 0.5)) if profile else 0.5
            posts = feed_data.get(agent_id, [])

            current_beliefs = list(beliefs)

            for post_text in posts:
                for i, belief in enumerate(current_beliefs):
                    stance = self.extract_stance(post_text, belief.topic)
                    if stance is None:
                        continue
                    # Weight by evidence quality (default 0.3, boosted if trustworthy source)
                    weight = 0.3
                    new_belief = self.update_belief(belief, stance, weight, openness)
                    current_beliefs[i] = new_belief

            updated[agent_id] = current_beliefs
            await self.persist_beliefs(session_id, agent_id, current_beliefs, round_number, db)

        return updated

    def extract_stance(self, text: str, topic: str) -> float | None:
        """Rule-based stance extraction from post text for a given topic.

        Returns a stance float in [-1, +1] if the topic is mentioned,
        or ``None`` if the text contains no relevant signals.

        Args:
            text: Post content to analyse.
            topic: One of :data:`CORE_BELIEF_TOPICS`.

        Returns:
            Stance float or None.
        """
        if not text or topic not in _TOPIC_KEYWORDS:
            return None

        text_lower = text.lower()
        keywords = _TOPIC_KEYWORDS[topic]

        pos_hits = sum(1 for kw in keywords.get("positive", []) if kw.lower() in text_lower)
        neg_hits = sum(1 for kw in keywords.get("negative", []) if kw.lower() in text_lower)

        if pos_hits == 0 and neg_hits == 0:
            return None

        total = pos_hits + neg_hits
        # Stance: fraction of positive hits mapped to [-1, +1]
        return round(((pos_hits - neg_hits) / total), 2)

    async def persist_beliefs(
        self,
        session_id: str,
        agent_id: int,
        beliefs: list[Belief],
        round_number: int,
        db: Any,
    ) -> None:
        """Persist agent beliefs to ``belief_states`` table.

        Uses ``INSERT OR REPLACE`` for idempotency.
        """
        if not beliefs:
            return
        rows = [
            (session_id, agent_id, b.topic, b.stance, b.confidence,
             b.evidence_count, round_number)
            for b in beliefs
        ]
        await db.executemany(
            """INSERT OR REPLACE INTO belief_states
               (session_id, agent_id, topic, stance, confidence, evidence_count, round_number)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        await db.commit()

    async def load_beliefs(
        self,
        session_id: str,
        agent_id: int,
        round_number: int,
        db: Any,
    ) -> list[Belief]:
        """Load beliefs for one agent at a specific round.

        Args:
            session_id: Simulation session UUID.
            agent_id: DB agent ID.
            round_number: Round to load from.
            db: Open aiosqlite connection.

        Returns:
            List of :class:`Belief` objects (may be empty if no data).
        """
        cursor = await db.execute(
            """SELECT topic, stance, confidence, evidence_count
               FROM belief_states
               WHERE session_id = ? AND agent_id = ? AND round_number = ?""",
            (session_id, agent_id, round_number),
        )
        rows = await cursor.fetchall()
        return [
            Belief(
                topic=str(r[0]),
                stance=float(r[1]),
                confidence=float(r[2]),
                evidence_count=int(r[3]),
                last_updated=round_number,
            )
            for r in rows
        ]
