# backend/app/services/consensus_debate_engine.py
"""Consensus debate engine for multi-agent structured argumentation.

Implements a firewall-protected debate mechanism where stakeholder agents
engage in pairwise cross-challenges on active topics, producing
measurable belief shifts and consensus scores.

Pipeline per debate round:
  1. Select active topics with highest belief divergence
  2. Sample cross-faction agent pairs (maximise stance distance)
  3. Sequential pairwise LLM debate (agent A argues → agent B responds)
  4. Extract belief deltas → update agent_beliefs
  5. Compute per-topic consensus score (0 = polarised, 1 = unanimous)
  6. Persist debate records to debate_rounds table

Cost control:
  - Only stakeholder agents participate (top 30-100)
  - Max 15 debate pairs per round (configurable)
  - Runs every N rounds (default 3, configurable)
  - Max tokens capped at 1024 per debate call
"""

from __future__ import annotations

import json
import statistics
import uuid
from dataclasses import dataclass
from typing import Any

from backend.app.utils.db import get_db
from backend.app.utils.llm_client import LLMClient, get_agent_provider_model
from backend.app.utils.logger import get_logger
from backend.prompts.consensus_debate_prompts import DEBATE_SYSTEM, DEBATE_USER

logger = get_logger("consensus_debate_engine")

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

_MAX_DEBATE_PAIRS = 15
_MAX_TOPICS_PER_ROUND = 5
_DIVERGENCE_THRESHOLD = 0.15  # min stance gap to trigger debate
_DEFAULT_TRIGGER_EVERY = 3  # rounds between debates
# Audit fix (2026-03-20): cap total accumulated delta per agent-topic-round.
# Per-exchange clamp is [-0.15, 0.15], but an agent debating 3 times on the
# same topic could accumulate up to 0.45 — unrealistic within one round.
_MAX_TOTAL_DELTA_PER_TOPIC_PER_ROUND: float = 0.20


# ---------------------------------------------------------------------------
# Frozen result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DebateExchange:
    """One pairwise exchange between two agents on a topic."""

    agent_a_id: str
    agent_b_id: str
    topic: str
    agent_a_delta: float
    agent_b_delta: float
    agent_a_response_type: str
    agent_b_response_type: str
    agent_a_argument: str
    agent_b_argument: str


@dataclass(frozen=True)
class DebateRoundResult:
    """Aggregate result of one debate round across all topics."""

    round_number: int
    exchanges: tuple[DebateExchange, ...]
    consensus_scores: dict[str, float]  # topic → consensus score [0, 1]
    topics_debated: int
    pairs_debated: int


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class ConsensusDebateEngine:
    """Structured multi-agent debate with Knowledge Firewall protection.

    Args:
        llm_client: Optional pre-configured LLMClient.
        trigger_every: Run debates every N rounds (default 3).
        max_pairs: Max pairwise debates per topic (default 15).
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        trigger_every: int = _DEFAULT_TRIGGER_EVERY,
        max_pairs: int = _MAX_DEBATE_PAIRS,
    ) -> None:
        self._llm = llm_client or LLMClient()
        self._trigger_every = trigger_every
        self._max_pairs = max_pairs

    def should_trigger(self, round_num: int) -> bool:
        """Return True if debate should run this round."""
        return round_num > 0 and round_num % self._trigger_every == 0

    async def run_debate(
        self,
        session_id: str,
        round_num: int,
        stakeholder_agents: list[dict[str, Any]],
        agent_beliefs: dict[str, dict[str, float]],
        scenario_description: str,
        agent_profiles: dict[str, dict[str, Any]] | None = None,
    ) -> DebateRoundResult:
        """Execute one round of structured debate across divergent topics.

        Args:
            session_id: Simulation session identifier.
            round_num: Current simulation round.
            stakeholder_agents: List of stakeholder agent dicts (id, name, role, faction).
            agent_beliefs: agent_id → {metric_id → stance float}.
            scenario_description: Seed text excerpt for LLM context.
            agent_profiles: Optional agent_id → {persona, goals, ...} enrichment.

        Returns:
            DebateRoundResult with all exchanges and consensus scores.
        """
        if not stakeholder_agents or not agent_beliefs:
            return DebateRoundResult(
                round_number=round_num,
                exchanges=(),
                consensus_scores={},
                topics_debated=0,
                pairs_debated=0,
            )

        # Step 1: Find topics with highest belief divergence
        topics = self._select_divergent_topics(agent_beliefs, stakeholder_agents)
        if not topics:
            logger.debug("ConsensusDebate: no divergent topics at round %d", round_num)
            return DebateRoundResult(
                round_number=round_num,
                exchanges=(),
                consensus_scores={},
                topics_debated=0,
                pairs_debated=0,
            )

        # Step 2-3: Run pairwise debates per topic
        all_exchanges: list[DebateExchange] = []
        belief_deltas: dict[str, dict[str, float]] = {}  # agent_id → {topic → delta}

        for topic in topics[:_MAX_TOPICS_PER_ROUND]:
            pairs = self._select_pairs(stakeholder_agents, agent_beliefs, topic)
            for agent_a, agent_b in pairs:
                exchange = await self._run_pairwise_debate(
                    agent_a=agent_a,
                    agent_b=agent_b,
                    topic=topic,
                    agent_beliefs=agent_beliefs,
                    scenario_description=scenario_description,
                    agent_profiles=agent_profiles,
                )
                if exchange is not None:
                    all_exchanges.append(exchange)
                    # Accumulate deltas
                    belief_deltas.setdefault(agent_a["id"], {})[topic] = (
                        belief_deltas.get(agent_a["id"], {}).get(topic, 0.0)
                        + exchange.agent_a_delta
                    )
                    belief_deltas.setdefault(agent_b["id"], {})[topic] = (
                        belief_deltas.get(agent_b["id"], {}).get(topic, 0.0)
                        + exchange.agent_b_delta
                    )

        # Step 4: Compute consensus scores
        consensus_scores = self._compute_consensus(
            agent_beliefs, stakeholder_agents, topics[:_MAX_TOPICS_PER_ROUND]
        )

        # Step 5: Persist to DB
        await self._persist_debate_records(
            session_id, round_num, all_exchanges, consensus_scores
        )

        result = DebateRoundResult(
            round_number=round_num,
            exchanges=tuple(all_exchanges),
            consensus_scores=consensus_scores,
            topics_debated=len(topics[:_MAX_TOPICS_PER_ROUND]),
            pairs_debated=len(all_exchanges),
        )

        logger.info(
            "ConsensusDebate: round=%d topics=%d pairs=%d avg_consensus=%.2f",
            round_num,
            result.topics_debated,
            result.pairs_debated,
            (
                statistics.mean(consensus_scores.values())
                if consensus_scores
                else 0.0
            ),
        )
        return result

    def get_belief_deltas(
        self, result: DebateRoundResult
    ) -> dict[str, dict[str, float]]:
        """Extract per-agent belief deltas from a debate result.

        Accumulates deltas across all exchanges, then clamps the total
        per-agent per-topic to ``±_MAX_TOTAL_DELTA_PER_TOPIC_PER_ROUND``
        (0.20).  This prevents an agent that debates 3+ times on the same
        topic in one round from shifting stance by more than 0.20 total,
        which would be psychologically unrealistic within a single round.

        Returns:
            agent_id → {topic → clamped_total_delta}
        """
        deltas: dict[str, dict[str, float]] = {}
        for ex in result.exchanges:
            deltas.setdefault(ex.agent_a_id, {})[ex.topic] = (
                deltas.get(ex.agent_a_id, {}).get(ex.topic, 0.0) + ex.agent_a_delta
            )
            deltas.setdefault(ex.agent_b_id, {})[ex.topic] = (
                deltas.get(ex.agent_b_id, {}).get(ex.topic, 0.0) + ex.agent_b_delta
            )
        # Clamp accumulated totals
        cap = _MAX_TOTAL_DELTA_PER_TOPIC_PER_ROUND
        return {
            agent_id: {
                topic: max(-cap, min(cap, delta))
                for topic, delta in topic_deltas.items()
            }
            for agent_id, topic_deltas in deltas.items()
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _select_divergent_topics(
        self,
        agent_beliefs: dict[str, dict[str, float]],
        stakeholder_agents: list[dict[str, Any]],
    ) -> list[str]:
        """Find topics with highest stance standard deviation among stakeholder agents."""
        stakeholder_ids = {a["id"] for a in stakeholder_agents}
        topic_stances: dict[str, list[float]] = {}

        for agent_id, beliefs in agent_beliefs.items():
            if agent_id not in stakeholder_ids:
                continue
            for topic, stance in beliefs.items():
                topic_stances.setdefault(topic, []).append(stance)

        # Rank by std dev (higher = more divergent)
        scored: list[tuple[str, float]] = []
        for topic, stances in topic_stances.items():
            if len(stances) < 2:
                continue
            std = statistics.stdev(stances)
            if std >= _DIVERGENCE_THRESHOLD:
                scored.append((topic, std))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [topic for topic, _ in scored]

    def _select_pairs(
        self,
        stakeholder_agents: list[dict[str, Any]],
        agent_beliefs: dict[str, dict[str, float]],
        topic: str,
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """Select debate pairs maximising stance distance on a topic."""
        # Sort agents by stance on this topic
        agents_with_stance = []
        for agent in stakeholder_agents:
            beliefs = agent_beliefs.get(agent["id"], {})
            if topic in beliefs:
                agents_with_stance.append((agent, beliefs[topic]))

        if len(agents_with_stance) < 2:
            return []

        agents_with_stance.sort(key=lambda x: x[1])

        # Pair from opposite ends (most divergent pairs)
        pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
        n = len(agents_with_stance)
        left, right = 0, n - 1
        while left < right and len(pairs) < self._max_pairs:
            a_agent, a_stance = agents_with_stance[left]
            b_agent, b_stance = agents_with_stance[right]
            if abs(a_stance - b_stance) >= _DIVERGENCE_THRESHOLD:
                pairs.append((a_agent, b_agent))
            left += 1
            right -= 1

        return pairs

    async def _run_pairwise_debate(
        self,
        agent_a: dict[str, Any],
        agent_b: dict[str, Any],
        topic: str,
        agent_beliefs: dict[str, dict[str, float]],
        scenario_description: str,
        agent_profiles: dict[str, dict[str, Any]] | None = None,
    ) -> DebateExchange | None:
        """Run a single pairwise debate: A argues → B responds → both update."""
        a_id = agent_a["id"]
        b_id = agent_b["id"]
        a_stance = agent_beliefs.get(a_id, {}).get(topic, 0.5)
        b_stance = agent_beliefs.get(b_id, {}).get(topic, 0.5)
        a_profile = (agent_profiles or {}).get(a_id, {})
        b_profile = (agent_profiles or {}).get(b_id, {})

        try:
            # Agent A presents their position
            a_argument = await self._get_debate_response(
                agent=agent_a,
                agent_stance=a_stance,
                agent_beliefs=agent_beliefs.get(a_id, {}),
                agent_profile=a_profile,
                opponent=agent_b,
                opponent_stance=b_stance,
                opponent_argument=(
                    f"I believe the current trajectory on {topic} "
                    f"warrants a stance of {b_stance:.2f}."
                ),
                topic=topic,
                scenario_description=scenario_description,
            )
            if a_argument is None:
                return None

            # Agent B responds to A's argument
            b_argument = await self._get_debate_response(
                agent=agent_b,
                agent_stance=b_stance,
                agent_beliefs=agent_beliefs.get(b_id, {}),
                agent_profile=b_profile,
                opponent=agent_a,
                opponent_stance=a_stance,
                opponent_argument=a_argument.get("argument", ""),
                topic=topic,
                scenario_description=scenario_description,
            )
            if b_argument is None:
                return None

            return DebateExchange(
                agent_a_id=a_id,
                agent_b_id=b_id,
                topic=topic,
                agent_a_delta=float(a_argument.get("belief_delta", 0.0)),
                agent_b_delta=float(b_argument.get("belief_delta", 0.0)),
                agent_a_response_type=a_argument.get("response_type", "rebut"),
                agent_b_response_type=b_argument.get("response_type", "rebut"),
                agent_a_argument=a_argument.get("argument", ""),
                agent_b_argument=b_argument.get("argument", ""),
            )
        except Exception:
            logger.exception(
                "ConsensusDebate: pairwise debate failed for %s vs %s on %s",
                a_id, b_id, topic,
            )
            return None

    async def _get_debate_response(
        self,
        agent: dict[str, Any],
        agent_stance: float,
        agent_beliefs: dict[str, float],
        agent_profile: dict[str, Any],
        opponent: dict[str, Any],
        opponent_stance: float,
        opponent_argument: str,
        topic: str,
        scenario_description: str,
    ) -> dict[str, Any] | None:
        """Call LLM for one side of a debate exchange."""
        system_content = DEBATE_SYSTEM.format(
            agent_name=agent.get("name", agent["id"]),
            agent_role=agent.get("role", "participant"),
            agent_persona=agent_profile.get("persona", "No persona available."),
            topic=topic,
            agent_stance=agent_stance,
        )
        user_content = DEBATE_USER.format(
            scenario_description=scenario_description[:2000],
            agent_memories=agent_profile.get("recent_memories", "No memories available."),
            agent_beliefs_json=json.dumps(agent_beliefs, indent=2),
            opponent_name=opponent.get("name", opponent["id"]),
            opponent_role=opponent.get("role", "participant"),
            topic=topic,
            opponent_stance=opponent_stance,
            opponent_argument=opponent_argument[:500],
            agent_name=agent.get("name", agent["id"]),
        )

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]

        provider, model = get_agent_provider_model()
        try:
            result = await self._llm.chat_json(
                messages,
                provider=provider,
                model=model,
                temperature=0.5,
                max_tokens=1024,
            )
            # Clamp belief_delta to [-0.15, 0.15]
            delta = float(result.get("belief_delta", 0.0))
            result["belief_delta"] = max(-0.15, min(0.15, delta))
            return result
        except Exception:
            logger.exception("ConsensusDebate: LLM call failed for %s", agent["id"])
            return None

    def _compute_consensus(
        self,
        agent_beliefs: dict[str, dict[str, float]],
        stakeholder_agents: list[dict[str, Any]],
        topics: list[str],
    ) -> dict[str, float]:
        """Compute consensus score per topic (1 - normalised std dev).

        Returns 1.0 for perfect consensus, 0.0 for maximum polarisation.
        """
        stakeholder_ids = {a["id"] for a in stakeholder_agents}
        scores: dict[str, float] = {}

        for topic in topics:
            stances = [
                agent_beliefs[aid][topic]
                for aid in stakeholder_ids
                if aid in agent_beliefs and topic in agent_beliefs.get(aid, {})
            ]
            if len(stances) < 2:
                scores[topic] = 1.0
                continue
            std = statistics.stdev(stances)
            # Max theoretical std for [0,1] uniform = 0.289
            # Normalise: 0 std = 1.0 consensus, 0.289+ std = 0.0 consensus
            scores[topic] = max(0.0, 1.0 - (std / 0.289))

        return scores

    async def _persist_debate_records(
        self,
        session_id: str,
        round_num: int,
        exchanges: list[DebateExchange],
        consensus_scores: dict[str, float],
    ) -> None:
        """Persist debate exchanges and consensus scores to DB."""
        if not exchanges:
            return
        try:
            async with get_db() as db:
                # Persist individual exchanges
                rows = [
                    (
                        str(uuid.uuid4()),
                        session_id,
                        round_num,
                        ex.topic,
                        ex.agent_a_id,
                        ex.agent_b_id,
                        ex.agent_a_delta,
                        ex.agent_b_delta,
                        ex.agent_a_response_type,
                        ex.agent_b_response_type,
                        ex.agent_a_argument[:500],
                        ex.agent_b_argument[:500],
                    )
                    for ex in exchanges
                ]
                await db.executemany(
                    """INSERT INTO debate_rounds
                       (id, session_id, round_number, topic,
                        agent_a_id, agent_b_id,
                        agent_a_delta, agent_b_delta,
                        agent_a_response_type, agent_b_response_type,
                        agent_a_argument, agent_b_argument)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    rows,
                )
                # Persist consensus scores
                for topic, score in consensus_scores.items():
                    await db.execute(
                        """INSERT INTO consensus_scores
                           (id, session_id, round_number, topic, score)
                           VALUES (?, ?, ?, ?, ?)""",
                        (str(uuid.uuid4()), session_id, round_num, topic, score),
                    )
                await db.commit()
        except Exception:
            logger.exception("ConsensusDebate: DB persist failed for session %s", session_id)
