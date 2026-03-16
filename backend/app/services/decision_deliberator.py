"""LLM batch deliberation for agent decisions with social contagion.

Sends batches of eligible agents to Fireworks Minimax and parses the
structured JSON output into AgentDecision records.

Social Contagion: Before deliberation, queries memory_triples and
agent_decisions for trusted peers' distress signals (emigration, job loss,
spending cuts). When trusted peers show high distress, this context is
injected into the LLM prompt to enable panic/herd behaviour that can
override stable macro indicators.

Retry strategy: 1 retry with exponential backoff (2s, 4s) before falling
back to stochastic conservative defaults.
"""

from __future__ import annotations

import asyncio
import json
import random
from dataclasses import dataclass, replace
from typing import Any

import aiosqlite

from backend.app.models.decision import AgentDecision, DecisionType, DECISION_ACTIONS
from backend.app.services.agent_factory import AgentProfile
from backend.app.services.macro_state import MacroState
from backend.app.utils.db import get_db
from backend.app.utils.llm_client import LLMClient
from backend.app.utils.logger import get_logger
from backend.prompts.decision_prompts import build_deliberation_prompt

logger = get_logger("decision_deliberator")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_BATCH_SIZE: int = 10
_DEFAULT_PROVIDER: str = "fireworks"
_DEFAULT_CONFIDENCE: float = 0.5
_MAX_RETRIES: int = 1
_BASE_BACKOFF_SEC: float = 2.0

# Predicates in memory_triples that signal peer distress
_DISTRESS_PREDICATES: tuple[str, ...] = (
    "worries_about", "emigrated", "lost_job", "decreases",
    "opposes", "causes",
)

# Decision actions that signal peer distress (for social contagion)
_DISTRESS_ACTIONS: dict[str, tuple[str, ...]] = {
    DecisionType.EMIGRATE: ("emigrate",),
    DecisionType.CHANGE_JOB: ("change_job", "retire_early"),
    DecisionType.ADJUST_SPENDING: ("cut_spending", "increase_savings"),
    DecisionType.BUY_PROPERTY: ("sell", "rent_more"),
    DecisionType.INVEST: ("hold_cash",),
    DecisionType.HAVE_CHILD: ("no_child", "delay"),
}

# Trust threshold for "highly trusted peer"
_TRUSTED_PEER_THRESHOLD: float = 0.3

# Contagion confidence boost: when ≥3 trusted peers show distress
_CONTAGION_CONFIDENCE_BOOST: float = 0.15


@dataclass(frozen=True)
class PeerDistressSignal:
    """Immutable record of a trusted peer's distress signal."""

    peer_agent_id: int
    peer_username: str
    signal_type: str  # 'triple' or 'decision'
    detail: str
    trust_score: float


@dataclass(frozen=True)
class SocialContagionContext:
    """Immutable social contagion context for an agent's decision."""

    agent_id: int
    distress_signals: tuple[PeerDistressSignal, ...]
    distress_ratio: float  # fraction of trusted peers showing distress
    contagion_active: bool  # True if ≥3 trusted peers show distress

    def to_prompt_section(self) -> str:
        """Format as a Chinese prompt section for LLM injection."""
        if not self.contagion_active or not self.distress_signals:
            return ""

        lines = ["【社交傳染警報 SOCIAL CONTAGION】"]
        lines.append(
            f"你信任嘅朋友/同事中，{len(self.distress_signals)} 個人"
            f"（{self.distress_ratio:.0%}）正經歷困擾："
        )
        for sig in self.distress_signals[:5]:  # Max 5 signals in prompt
            lines.append(f"  - @{sig.peer_username} (信任度 {sig.trust_score:.2f}): {sig.detail}")

        lines.append("")
        lines.append(
            "⚠️ 重要：當你信任嘅人大量出現困擾行為（移民、裁員、減開支），"
            "即使宏觀數據穩定，你都應該認真考慮跟隨佢哋嘅決定。"
            "群體恐慌可以超越理性分析 — 如果身邊人都驚，你更加應該驚。"
        )
        return "\n".join(lines)


_DEFAULT_ACTION_FALLBACKS: dict[str, str] = {
    DecisionType.BUY_PROPERTY: "wait",
    DecisionType.EMIGRATE: "stay",
    DecisionType.CHANGE_JOB: "stay",
    DecisionType.INVEST: "hold_cash",
    DecisionType.HAVE_CHILD: "delay",
    DecisionType.ADJUST_SPENDING: "maintain",
}

# Stochastic fallback distributions: {decision_type: [(action, weight), ...]}
# When LLM fails after retries, agents pick from this weighted distribution
# instead of all defaulting to the same conservative action.
_STOCHASTIC_FALLBACK_DIST: dict[str, tuple[tuple[str, float], ...]] = {
    DecisionType.BUY_PROPERTY: (
        ("wait", 0.60), ("rent_more", 0.25), ("sell", 0.05), ("buy", 0.10),
    ),
    DecisionType.EMIGRATE: (
        ("stay", 0.70), ("consider_later", 0.20), ("emigrate", 0.10),
    ),
    DecisionType.CHANGE_JOB: (
        ("stay", 0.65), ("upskill", 0.25), ("change_job", 0.08), ("retire_early", 0.02),
    ),
    DecisionType.INVEST: (
        ("hold_cash", 0.50), ("diversify", 0.25), ("invest_stocks", 0.15),
        ("invest_property", 0.05), ("invest_crypto", 0.05),
    ),
    DecisionType.HAVE_CHILD: (
        ("delay", 0.60), ("no_child", 0.30), ("have_child", 0.10),
    ),
    DecisionType.ADJUST_SPENDING: (
        ("maintain", 0.50), ("cut_spending", 0.30), ("increase_savings", 0.15),
        ("spend_more", 0.05),
    ),
}


# ---------------------------------------------------------------------------
# Deliberator
# ---------------------------------------------------------------------------

class DecisionDeliberator:
    """Batch LLM deliberation for agent decisions with social contagion."""

    def __init__(
        self, llm_client: LLMClient | None = None, seed: int = 42
    ) -> None:
        self._client = llm_client or LLMClient()
        self._rng = random.Random(seed)

    async def query_social_contagion(
        self,
        session_id: str,
        agent_id: int,
        decision_type: str,
        recent_rounds: int = 3,
    ) -> SocialContagionContext:
        """Query trusted peers' distress signals for social contagion.

        Checks two sources:
        1. memory_triples: predicates like 'worries_about', 'emigrated', 'lost_job'
           from highly trusted peers.
        2. agent_decisions: recent decisions from trusted peers that indicate
           distress (emigrate, cut_spending, layoff, etc.).

        Args:
            session_id: Session UUID.
            agent_id: The agent making the decision.
            decision_type: The decision type being deliberated.
            recent_rounds: How many recent rounds to look back.

        Returns:
            Immutable SocialContagionContext.
        """
        signals: list[PeerDistressSignal] = []

        try:
            async with get_db() as db:
                # 1. Find highly trusted peers (trust_score >= threshold)
                cursor = await db.execute(
                    """
                    SELECT ar.agent_b_id, ar.trust_score,
                           COALESCE(ap.oasis_username, 'agent_' || ar.agent_b_id) AS username
                    FROM agent_relationships ar
                    LEFT JOIN agent_profiles ap
                           ON ap.id = ar.agent_b_id AND ap.session_id = ar.session_id
                    WHERE ar.session_id = ?
                      AND ar.agent_a_id = ?
                      AND ar.trust_score >= ?
                    ORDER BY ar.trust_score DESC
                    LIMIT 20
                    """,
                    (session_id, agent_id, _TRUSTED_PEER_THRESHOLD),
                )
                trusted_peers = await cursor.fetchall()

                if not trusted_peers:
                    return SocialContagionContext(
                        agent_id=agent_id,
                        distress_signals=(),
                        distress_ratio=0.0,
                        contagion_active=False,
                    )

                trusted_ids = [r[0] for r in trusted_peers]
                peer_info = {
                    r[0]: (float(r[1]), str(r[2]))
                    for r in trusted_peers
                }

                # 2. Query memory_triples for distress predicates from trusted peers
                if trusted_ids:
                    placeholders = ",".join("?" * len(trusted_ids))
                    cursor = await db.execute(
                        f"""
                        SELECT DISTINCT mt.agent_id, mt.predicate, mt.object
                        FROM memory_triples mt
                        WHERE mt.session_id = ?
                          AND mt.agent_id IN ({placeholders})
                          AND mt.predicate IN ({",".join("?" * len(_DISTRESS_PREDICATES))})
                        ORDER BY mt.round_number DESC
                        LIMIT 30
                        """,
                        (session_id, *trusted_ids, *_DISTRESS_PREDICATES),
                    )
                    triple_rows = await cursor.fetchall()

                    for row in triple_rows:
                        peer_id = row[0]
                        predicate = row[1]
                        obj = row[2] or ""
                        trust, username = peer_info.get(peer_id, (0.0, f"agent_{peer_id}"))
                        signals.append(PeerDistressSignal(
                            peer_agent_id=peer_id,
                            peer_username=username,
                            signal_type="triple",
                            detail=f"{predicate}: {obj}",
                            trust_score=trust,
                        ))

                # 3. Query agent_decisions for recent distress actions from trusted peers
                distress_actions = _DISTRESS_ACTIONS.get(decision_type, ())
                if trusted_ids and distress_actions:
                    placeholders = ",".join("?" * len(trusted_ids))
                    action_placeholders = ",".join("?" * len(distress_actions))
                    cursor = await db.execute(
                        f"""
                        SELECT ad.agent_id, ad.decision_type, ad.action, ad.reasoning
                        FROM agent_decisions ad
                        WHERE ad.session_id = ?
                          AND ad.agent_id IN ({placeholders})
                          AND ad.action IN ({action_placeholders})
                          AND ad.round_number >= (
                              SELECT COALESCE(MAX(round_number), 0) - ?
                              FROM agent_decisions WHERE session_id = ?
                          )
                        ORDER BY ad.round_number DESC
                        LIMIT 20
                        """,
                        (
                            session_id,
                            *trusted_ids,
                            *distress_actions,
                            recent_rounds,
                            session_id,
                        ),
                    )
                    decision_rows = await cursor.fetchall()

                    seen_peers: set[int] = set()
                    for row in decision_rows:
                        peer_id = row[0]
                        if peer_id in seen_peers:
                            continue  # One signal per peer per query
                        seen_peers.add(peer_id)
                        dt = row[1]
                        action = row[2]
                        reasoning = (row[3] or "")[:80]
                        trust, username = peer_info.get(peer_id, (0.0, f"agent_{peer_id}"))
                        signals.append(PeerDistressSignal(
                            peer_agent_id=peer_id,
                            peer_username=username,
                            signal_type="decision",
                            detail=f"決定 {action} ({reasoning})",
                            trust_score=trust,
                        ))

        except Exception:
            logger.exception(
                "query_social_contagion failed session=%s agent=%d", session_id, agent_id
            )
            return SocialContagionContext(
                agent_id=agent_id,
                distress_signals=(),
                distress_ratio=0.0,
                contagion_active=False,
            )

        # Deduplicate signals by peer_agent_id (keep highest trust)
        best_by_peer: dict[int, PeerDistressSignal] = {}
        for sig in signals:
            existing = best_by_peer.get(sig.peer_agent_id)
            if existing is None or sig.trust_score > existing.trust_score:
                best_by_peer[sig.peer_agent_id] = sig

        unique_signals = tuple(
            sorted(best_by_peer.values(), key=lambda s: s.trust_score, reverse=True)
        )
        distress_ratio = (
            len(unique_signals) / len(trusted_ids)
            if trusted_ids
            else 0.0
        )
        contagion_active = len(unique_signals) >= 3

        return SocialContagionContext(
            agent_id=agent_id,
            distress_signals=unique_signals,
            distress_ratio=round(distress_ratio, 4),
            contagion_active=contagion_active,
        )

    async def deliberate_batch(
        self,
        eligible_agents: list[AgentProfile],
        macro_state: MacroState,
        decision_type: str,
        session_id: str,
        round_number: int,
        batch_size: int = _DEFAULT_BATCH_SIZE,
    ) -> list[AgentDecision]:
        """Deliberate decisions for a list of eligible agents in batches.

        Before LLM deliberation, queries social contagion context for each
        agent. When ≥3 trusted peers show distress, injects contagion context
        into the prompt to enable herd behaviour.

        Args:
            eligible_agents: Agents pre-filtered by the rule engine.
            macro_state: Current macro-economic snapshot.
            decision_type: The ``DecisionType`` value being deliberated.
            session_id: Simulation session identifier.
            round_number: Current simulation round.
            batch_size: Max agents per LLM call (default 10).

        Returns:
            List of ``AgentDecision`` records for all processed agents.
        """
        if not eligible_agents:
            return []

        # Query social contagion for each agent (batched DB queries)
        contagion_map: dict[int, SocialContagionContext] = {}
        for agent in eligible_agents:
            ctx = await self.query_social_contagion(
                session_id, agent.id, decision_type
            )
            if ctx.contagion_active:
                contagion_map[agent.id] = ctx

        if contagion_map:
            logger.info(
                "Social contagion active for %d/%d agents, type=%s session=%s",
                len(contagion_map), len(eligible_agents), decision_type, session_id,
            )

        all_decisions: list[AgentDecision] = []
        # Split into batches
        for start in range(0, len(eligible_agents), batch_size):
            chunk = eligible_agents[start : start + batch_size]
            batch_decisions = await self._deliberate_one_batch(
                chunk, macro_state, decision_type, session_id, round_number,
                contagion_map=contagion_map,
            )
            all_decisions.extend(batch_decisions)

        logger.info(
            "Deliberated %d decisions for type=%s session=%s round=%d",
            len(all_decisions),
            decision_type,
            session_id,
            round_number,
        )
        return all_decisions

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    async def _deliberate_one_batch(
        self,
        agents: list[AgentProfile],
        macro_state: MacroState,
        decision_type: str,
        session_id: str,
        round_number: int,
        contagion_map: dict[int, SocialContagionContext] | None = None,
    ) -> list[AgentDecision]:
        """Call LLM for one batch and parse JSON output.

        Retries once with exponential backoff (2s, 4s) before falling back to
        stochastic conservative defaults.

        If any agent in the batch has active social contagion, the contagion
        context is appended to the prompt to enable herd behaviour.
        """
        # Build contagion sections for agents in this batch
        contagion_sections: list[str] = []
        if contagion_map:
            for agent in agents:
                ctx = contagion_map.get(agent.id)
                if ctx is not None and ctx.contagion_active:
                    section = ctx.to_prompt_section()
                    if section:
                        contagion_sections.append(
                            f"--- agent_id={agent.id} 社交傳染 ---\n{section}"
                        )

        messages = build_deliberation_prompt(
            agents, macro_state, decision_type,
            contagion_context="\n\n".join(contagion_sections) if contagion_sections else None,
        )
        agent_id_set = {p.id for p in agents}

        raw: Any = None
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                raw = await self._client.chat_json(
                    messages,
                    provider=_DEFAULT_PROVIDER,
                    temperature=0.4,
                    max_tokens=4096,
                )
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    backoff = _BASE_BACKOFF_SEC * (2 ** attempt)
                    logger.warning(
                        "LLM attempt %d/%d failed for decision_type=%s session=%s — retrying in %.1fs",
                        attempt + 1, _MAX_RETRIES + 1, decision_type, session_id, backoff,
                    )
                    await asyncio.sleep(backoff)

        if last_exc is not None:
            logger.exception(
                "LLM call failed after %d attempts for decision_type=%s session=%s round=%d — using stochastic fallbacks",
                _MAX_RETRIES + 1,
                decision_type,
                session_id,
                round_number,
            )
            return self._build_fallback_decisions(agents, decision_type, session_id, round_number)

        # Parse the returned JSON
        items = _extract_list(raw)
        if items is None:
            logger.warning(
                "Unexpected LLM response shape for decision_type=%s — using fallbacks. raw=%s",
                decision_type,
                str(raw)[:200],
            )
            return self._build_fallback_decisions(agents, decision_type, session_id, round_number)

        decisions: list[AgentDecision] = []
        seen_ids: set[int] = set()

        for item in items:
            agent_id = _safe_int(item.get("agent_id"))
            if agent_id is None or agent_id not in agent_id_set:
                continue
            if agent_id in seen_ids:
                continue  # deduplicate

            action = _validate_action(
                str(item.get("action", "")), decision_type
            )
            reasoning = str(item.get("reasoning", ""))[:300]
            confidence = _clamp_float(item.get("confidence", _DEFAULT_CONFIDENCE))

            decisions.append(
                AgentDecision(
                    session_id=session_id,
                    agent_id=agent_id,
                    round_number=round_number,
                    decision_type=decision_type,
                    action=action,
                    reasoning=reasoning,
                    confidence=confidence,
                )
            )
            seen_ids.add(agent_id)

        # Fill in any agents the LLM omitted
        for p in agents:
            if p.id not in seen_ids:
                decisions.append(
                    self._make_fallback(p, decision_type, session_id, round_number)
                )

        return decisions

    def _build_fallback_decisions(
        self,
        agents: list[AgentProfile],
        decision_type: str,
        session_id: str,
        round_number: int,
    ) -> list[AgentDecision]:
        return [
            self._make_fallback(p, decision_type, session_id, round_number)
            for p in agents
        ]

    def _stochastic_fallback(self, decision_type: str) -> dict[str, Any]:
        """Choose a conservative action from a weighted distribution.

        Uses self._rng for reproducible randomness.  Each call samples one
        action from the type-specific distribution defined in
        ``_STOCHASTIC_FALLBACK_DIST``.

        Args:
            decision_type: The DecisionType value.

        Returns:
            Dict with ``action``, ``reasoning``, and ``confidence`` keys.
        """
        dist = _STOCHASTIC_FALLBACK_DIST.get(decision_type)
        if dist is None:
            action = _DEFAULT_ACTION_FALLBACKS.get(decision_type, "maintain")
        else:
            actions, weights = zip(*dist)
            action = self._rng.choices(actions, weights=weights, k=1)[0]

        # Lower confidence for non-default choices to signal uncertainty
        default_action = _DEFAULT_ACTION_FALLBACKS.get(decision_type, "maintain")
        confidence = 0.45 if action == default_action else 0.30

        return {
            "action": action,
            "reasoning": "（LLM 回應缺失，使用隨機保守策略）",
            "confidence": confidence,
        }

    def _make_fallback(
        self,
        profile: AgentProfile,
        decision_type: str,
        session_id: str,
        round_number: int,
    ) -> AgentDecision:
        fb = self._stochastic_fallback(decision_type)
        return AgentDecision(
            session_id=session_id,
            agent_id=profile.id,
            round_number=round_number,
            decision_type=decision_type,
            action=fb["action"],
            reasoning=fb["reasoning"],
            confidence=fb["confidence"],
        )


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _extract_list(raw: Any) -> list[dict[str, Any]] | None:
    """Extract a list of dicts from the LLM response.

    Handles both top-level list and wrapped formats like {"decisions": [...]}
    or {"results": [...]}.
    """
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("decisions", "results", "data", "agents"):
            val = raw.get(key)
            if isinstance(val, list):
                return val
    return None


def _safe_int(val: Any) -> int | None:
    """Convert val to int, returning None on failure."""
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _clamp_float(val: Any, lo: float = 0.0, hi: float = 1.0) -> float:
    """Convert val to float clamped to [lo, hi]."""
    try:
        return max(lo, min(hi, float(val)))
    except (TypeError, ValueError):
        return _DEFAULT_CONFIDENCE


def _validate_action(action: str, decision_type: str) -> str:
    """Return action if it is in the allowed set, else the fallback."""
    allowed = DECISION_ACTIONS.get(decision_type, frozenset())
    if action in allowed:
        return action
    fallback = _DEFAULT_ACTION_FALLBACKS.get(decision_type, "maintain")
    logger.debug(
        "Invalid action '%s' for type=%s → using fallback '%s'",
        action,
        decision_type,
        fallback,
    )
    return fallback
