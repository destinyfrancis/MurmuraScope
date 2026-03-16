"""Agent consensus → probability estimator.

Converts simulation agent beliefs, decisions, and sentiment into
a probability estimate for Polymarket contract outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("consensus_estimator")

# Mapping from contract topics to belief system topics
_QUESTION_TOPIC_MAP: dict[str, str] = {
    "property": "property_outlook",
    "housing": "property_outlook",
    "real estate": "property_outlook",
    "economy": "economy_outlook",
    "recession": "economy_outlook",
    "gdp": "economy_outlook",
    "immigration": "immigration_stance",
    "migration": "immigration_stance",
    "emigration": "immigration_stance",
    "government": "government_trust",
    "policy": "government_trust",
    "regulation": "government_trust",
    "stability": "social_stability",
    "protest": "social_stability",
    "unrest": "social_stability",
    "ai": "ai_impact",
    "artificial intelligence": "ai_impact",
    "automation": "ai_impact",
}

# Decision types that indicate directional bets
_BULLISH_DECISIONS = frozenset({"buy_property", "invest_stocks", "have_child", "spend_more", "seek_promotion"})
_BEARISH_DECISIONS = frozenset({"emigrate", "cut_spending", "hold_cash", "quit", "lie_flat", "strike"})


@dataclass(frozen=True)
class ConsensusEstimate:
    """Immutable probability estimate from agent consensus."""
    probability: float          # P(YES) ∈ [0, 1]
    confidence: float           # [0, 1] — how confident the estimate is
    supporting_agents: int      # agents supporting YES
    opposing_agents: int        # agents supporting NO
    neutral_agents: int         # undecided agents
    belief_signal: float        # [-1, 1] from belief system
    decision_signal: float      # [-1, 1] from agent decisions
    sentiment_signal: float     # [-1, 1] from sentiment ratio
    evidence_summary: str       # human-readable explanation


class ConsensusEstimator:
    """Estimates event probability from agent simulation state."""

    async def estimate_probability(
        self,
        session_id: str,
        contract_question: str,
        signal_weights: dict[str, float] | None = None,
    ) -> ConsensusEstimate:
        """Estimate P(YES) for a contract question from simulation state.

        Combines three signals:
        1. Belief signal — agent belief stances on relevant topics
        2. Decision signal — directional life decisions
        3. Sentiment signal — overall positive/negative ratio

        *signal_weights* can override default weights (belief=0.40, decision=0.35,
        sentiment=0.25). When None, uses defaults or loads from domain pack.

        Returns a ConsensusEstimate with probability, confidence, and breakdown.
        """
        weights = signal_weights or {"belief": 0.40, "decision": 0.35, "sentiment": 0.25}

        belief_signal = await self._compute_belief_signal(session_id, contract_question)
        decision_signal = await self._compute_decision_signal(session_id)
        sentiment_signal = await self._compute_sentiment_signal(session_id)

        # Weighted combination → raw signal in [-1, 1]
        raw_signal = (
            weights.get("belief", 0.40) * belief_signal
            + weights.get("decision", 0.35) * decision_signal
            + weights.get("sentiment", 0.25) * sentiment_signal
        )

        # Map [-1, 1] signal to [0, 1] probability
        # 0 signal → 0.5 (no edge), +1 → 0.85 (cap), -1 → 0.15 (floor)
        probability = 0.5 + raw_signal * 0.35
        probability = max(0.05, min(0.95, probability))

        # Confidence based on signal agreement and magnitude
        signals = [belief_signal, decision_signal, sentiment_signal]
        same_direction = sum(1 for s in signals if s * raw_signal > 0)
        confidence = (same_direction / 3) * min(1.0, abs(raw_signal) * 2)

        # Count agents by direction
        supporting, opposing, neutral = await self._count_agent_directions(
            session_id, contract_question
        )

        evidence = self._build_evidence_summary(
            belief_signal, decision_signal, sentiment_signal, probability
        )

        return ConsensusEstimate(
            probability=round(probability, 4),
            confidence=round(confidence, 4),
            supporting_agents=supporting,
            opposing_agents=opposing,
            neutral_agents=neutral,
            belief_signal=round(belief_signal, 4),
            decision_signal=round(decision_signal, 4),
            sentiment_signal=round(sentiment_signal, 4),
            evidence_summary=evidence,
        )

    async def _compute_belief_signal(
        self, session_id: str, question: str
    ) -> float:
        """Extract belief signal from agent belief_states table."""
        question_lower = question.lower()

        # Find the most relevant belief topic
        matched_topic = None
        for keyword, topic in _QUESTION_TOPIC_MAP.items():
            if keyword in question_lower:
                matched_topic = topic
                break

        if not matched_topic:
            return 0.0

        try:
            async with get_db() as db:
                cursor = await db.execute(
                    """SELECT AVG(stance), COUNT(*) FROM belief_states
                       WHERE session_id = ? AND topic = ?""",
                    (session_id, matched_topic),
                )
                row = await cursor.fetchone()
                if row and row[0] is not None and row[1] > 0:
                    return float(row[0])  # already in [-1, 1]
        except Exception:
            logger.debug("belief_states query failed session=%s", session_id)

        return 0.0

    async def _compute_decision_signal(self, session_id: str) -> float:
        """Extract directional signal from agent decisions."""
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    """SELECT action, COUNT(*) as cnt FROM agent_decisions
                       WHERE session_id = ?
                       GROUP BY action""",
                    (session_id,),
                )
                rows = await cursor.fetchall()
        except Exception:
            logger.debug("agent_decisions query failed session=%s", session_id)
            return 0.0

        bullish_count = 0
        bearish_count = 0
        for row in rows:
            action = row[0] or ""
            count = row[1] or 0
            if action in _BULLISH_DECISIONS:
                bullish_count += count
            elif action in _BEARISH_DECISIONS:
                bearish_count += count

        total = bullish_count + bearish_count
        if total == 0:
            return 0.0

        # Returns [-1, 1]: positive = bullish consensus
        return (bullish_count - bearish_count) / total

    async def _compute_sentiment_signal(self, session_id: str) -> float:
        """Extract sentiment signal from simulation_actions."""
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    """SELECT sentiment, COUNT(*) FROM simulation_actions
                       WHERE session_id = ? AND action_type = 'post'
                       GROUP BY sentiment""",
                    (session_id,),
                )
                rows = await cursor.fetchall()
        except Exception:
            logger.debug("simulation_actions sentiment query failed session=%s", session_id)
            return 0.0

        counts: dict[str, int] = {}
        for row in rows:
            counts[row[0] or "neutral"] = row[1] or 0

        pos = counts.get("positive", 0)
        neg = counts.get("negative", 0)
        total = pos + neg
        if total == 0:
            return 0.0

        return (pos - neg) / total

    async def _count_agent_directions(
        self, session_id: str, question: str
    ) -> tuple[int, int, int]:
        """Count agents by directional alignment."""
        question_lower = question.lower()
        matched_topic = None
        for keyword, topic in _QUESTION_TOPIC_MAP.items():
            if keyword in question_lower:
                matched_topic = topic
                break

        if not matched_topic:
            return 0, 0, 0

        try:
            async with get_db() as db:
                cursor = await db.execute(
                    """SELECT stance FROM belief_states
                       WHERE session_id = ? AND topic = ?""",
                    (session_id, matched_topic),
                )
                rows = await cursor.fetchall()
        except Exception:
            return 0, 0, 0

        supporting = sum(1 for r in rows if r[0] and float(r[0]) > 0.1)
        opposing = sum(1 for r in rows if r[0] and float(r[0]) < -0.1)
        neutral = len(rows) - supporting - opposing
        return supporting, opposing, neutral

    @staticmethod
    def _build_evidence_summary(
        belief: float, decision: float, sentiment: float, prob: float
    ) -> str:
        """Build human-readable evidence summary."""
        parts: list[str] = []

        if abs(belief) > 0.1:
            direction = "正面" if belief > 0 else "負面"
            parts.append(f"信念系統偏{direction}（{belief:+.2f}）")

        if abs(decision) > 0.1:
            direction = "樂觀" if decision > 0 else "悲觀"
            parts.append(f"決策傾向{direction}（{decision:+.2f}）")

        if abs(sentiment) > 0.1:
            direction = "正面" if sentiment > 0 else "負面"
            parts.append(f"輿情{direction}（{sentiment:+.2f}）")

        if not parts:
            return f"信號中性，預測概率 {prob:.1%}"

        return "、".join(parts) + f" → 預測概率 {prob:.1%}"
