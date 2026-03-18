"""Universal decision engine for domain-agnostic simulation.

Unlike the HK-specific DecisionEngine which uses rule-based eligibility
filters, this engine uses LLM-driven eligibility and deliberation for
arbitrary scenario-generated decision types.

All public methods are async. All result types are frozen dataclasses.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from backend.app.utils.db import get_db
from backend.app.utils.llm_client import LLMClient
from backend.app.utils.logger import get_logger
from backend.app.utils.prompt_security import sanitize_scenario_description

if TYPE_CHECKING:
    from backend.app.models.universal_agent_profile import UniversalAgentProfile

logger = get_logger("universal_decision_engine")

# ---------------------------------------------------------------------------
# Try to import universal scenario models (may not exist yet if parallel
# agent hasn't finished — tests provide mock versions)
# ---------------------------------------------------------------------------

try:
    from backend.app.models.universal_scenario import (  # noqa: F401
        UniversalDecisionType,
        UniversalImpactRule,
        UniversalScenarioConfig,
    )
    _SCENARIO_MODELS_AVAILABLE = True
except ImportError:
    _SCENARIO_MODELS_AVAILABLE = False
    logger.warning(
        "backend.app.models.universal_scenario not yet available — "
        "UniversalDecisionEngine will accept duck-typed scenario configs."
    )

# ---------------------------------------------------------------------------
# Cost-control sampling constants
# ---------------------------------------------------------------------------

_SAMPLE_RATE: float = 0.20   # 20 % of eligible agents per decision type
_SAMPLE_CAP: int = 30        # hard cap per decision type

# ---------------------------------------------------------------------------
# Result dataclasses (frozen for immutability)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UniversalAgentDecision:
    """One agent's decision in a universal simulation round."""

    session_id: str
    agent_id: str           # UniversalAgentProfile.id (str, not int!)
    round_number: int
    decision_type_id: str   # UniversalDecisionType.id
    action: str             # one of UniversalDecisionType.possible_actions
    reasoning: str
    confidence: float       # 0.0–1.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be in [0.0, 1.0], got {self.confidence!r}"
            )


@dataclass(frozen=True)
class UniversalRoundResult:
    """Aggregate result of processing one simulation round's decisions."""

    session_id: str
    round_number: int
    decisions: tuple[UniversalAgentDecision, ...]
    metric_deltas: dict[str, float]       # metric_id → cumulative delta
    total_decisions: int
    counts_by_type: dict[str, dict[str, int]]  # {decision_type_id: {action: count}}


# ---------------------------------------------------------------------------
# UniversalDecisionEngine
# ---------------------------------------------------------------------------


class UniversalDecisionEngine:
    """Process agent decisions for any scenario using LLM-driven logic.

    Design principles:
    1. No hardcoded decision types — uses UniversalDecisionType from ScenarioConfig.
    2. No rule-based eligibility — entity_type matching is the only fast filter;
       everything else is LLM-driven.
    3. Batch processing — sends groups of agents to LLM for deliberation.
    4. Impact aggregation — applies UniversalImpactRule to update metrics.
    """

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm = llm_client or LLMClient()
        self._schema_initialised = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def process_round_decisions(
        self,
        session_id: str,
        round_number: int,
        agents: list[UniversalAgentProfile],
        scenario_config: Any,           # UniversalScenarioConfig (duck-typed)
        current_metrics: dict[str, float],
        recent_events: str = "",
    ) -> UniversalRoundResult:
        """Process all decisions for one simulation round.

        Steps:
        1. Ensure DB schema exists.
        2. For each decision type in scenario_config:
           a. Filter agents by applicable_entity_types (fast, no LLM).
           b. Sample agents (cost control: 20% sample, cap 30).
           c. Send batch to LLM for deliberation.
        3. Aggregate decisions across all types.
        4. Apply impact rules to compute metric deltas.
        5. Store decisions to DB.
        6. Return UniversalRoundResult.

        Args:
            session_id: Simulation session UUID.
            round_number: Current simulation round number.
            agents: List of UniversalAgentProfile objects.
            scenario_config: UniversalScenarioConfig with decision types and
                impact rules.
            current_metrics: Current metric values keyed by metric_id.
            recent_events: Narrative string describing recent round events.

        Returns:
            Frozen UniversalRoundResult with all decisions and metric deltas.
        """
        await self._ensure_schema()

        if not agents:
            logger.debug(
                "process_round_decisions: no agents — skipping (session=%s round=%d)",
                session_id,
                round_number,
            )
            return UniversalRoundResult(
                session_id=session_id,
                round_number=round_number,
                decisions=(),
                metric_deltas={},
                total_decisions=0,
                counts_by_type={},
            )

        decision_types = list(scenario_config.decision_types)
        all_decisions: list[UniversalAgentDecision] = []

        for dt in decision_types:
            eligible = _filter_by_entity_type(agents, dt)
            if not eligible:
                logger.debug(
                    "No eligible agents for decision_type=%s (session=%s)",
                    dt.id,
                    session_id,
                )
                continue

            sampled = _sample_agents(eligible, _SAMPLE_RATE, _SAMPLE_CAP)
            logger.debug(
                "Decision type=%s eligible=%d sampled=%d (session=%s round=%d)",
                dt.id,
                len(eligible),
                len(sampled),
                session_id,
                round_number,
            )

            try:
                batch_decisions = await self._deliberate_batch(
                    agents=sampled,
                    decision_type=dt,
                    current_metrics=current_metrics,
                    recent_events=recent_events,
                )
                # Stamp with session + round metadata
                stamped = [
                    UniversalAgentDecision(
                        session_id=session_id,
                        agent_id=d.agent_id,
                        round_number=round_number,
                        decision_type_id=dt.id,
                        action=d.action,
                        reasoning=d.reasoning,
                        confidence=d.confidence,
                    )
                    for d in batch_decisions
                ]
                all_decisions.extend(stamped)
            except Exception as exc:
                logger.error(
                    "Deliberation failed for decision_type=%s session=%s: %s",
                    dt.id,
                    session_id,
                    exc,
                )

        if all_decisions:
            await self._store_decisions(all_decisions)

        metric_deltas = _compute_metric_deltas(
            all_decisions, list(scenario_config.impact_rules)
        )
        counts_by_type = _build_counts_by_type(all_decisions)

        logger.info(
            "UniversalDecisionEngine: session=%s round=%d total_decisions=%d types=%d",
            session_id,
            round_number,
            len(all_decisions),
            len(counts_by_type),
        )

        return UniversalRoundResult(
            session_id=session_id,
            round_number=round_number,
            decisions=tuple(all_decisions),
            metric_deltas=metric_deltas,
            total_decisions=len(all_decisions),
            counts_by_type=counts_by_type,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _deliberate_batch(
        self,
        agents: list[UniversalAgentProfile],
        decision_type: Any,             # UniversalDecisionType (duck-typed)
        current_metrics: dict[str, float],
        recent_events: str,
    ) -> list[UniversalAgentDecision]:
        """Send a batch of agents to LLM for decision deliberation.

        The LLM prompt includes:
        - Decision type description and possible actions.
        - Each agent's persona, goals, capabilities, stance.
        - Current metric values (scenario state).
        - Recent events narrative.

        Invalid actions (not in decision_type.possible_actions) are silently
        filtered out to prevent downstream errors.

        Args:
            agents: Sampled agents eligible for this decision type.
            decision_type: UniversalDecisionType being deliberated.
            current_metrics: Current scenario metric values.
            recent_events: Narrative of recent round events.

        Returns:
            List of UniversalAgentDecision objects (session_id and round_number
            are placeholders — caller stamps them after return).
        """
        from backend.prompts.universal_decision_prompts import (
            UNIVERSAL_DELIBERATION_SYSTEM,
            UNIVERSAL_DELIBERATION_USER,
        )

        dt_payload: dict[str, Any] = {
            "id": decision_type.id,
            "label": decision_type.label,
            "description": decision_type.description,
            "possible_actions": list(decision_type.possible_actions),
        }
        if decision_type.applicable_entity_types:
            dt_payload["applicable_entity_types"] = list(
                decision_type.applicable_entity_types
            )

        agents_payload = [_agent_to_prompt_dict(a) for a in agents]
        metrics_payload = {k: round(v, 4) for k, v in current_metrics.items()}

        safe_recent_events = (
            sanitize_scenario_description(recent_events)
            if recent_events
            else "No notable recent events."
        )
        user_content = UNIVERSAL_DELIBERATION_USER.format(
            metrics_json=json.dumps(metrics_payload, ensure_ascii=False, indent=2),
            recent_events=safe_recent_events,
            decision_type_json=json.dumps(dt_payload, ensure_ascii=False, indent=2),
            agents_json=json.dumps(agents_payload, ensure_ascii=False, indent=2),
            agent_count=len(agents),
        )

        messages = [
            {"role": "system", "content": UNIVERSAL_DELIBERATION_SYSTEM},
            {"role": "user", "content": user_content},
        ]

        raw: dict[str, Any] = await self._llm.chat_json(messages)

        raw_decisions: list[dict[str, Any]] = raw.get("decisions", [])
        valid_actions = set(decision_type.possible_actions)
        agent_ids = {a.id for a in agents}
        results: list[UniversalAgentDecision] = []

        for entry in raw_decisions:
            agent_id = str(entry.get("agent_id", ""))
            action = str(entry.get("action", ""))
            reasoning = str(entry.get("reasoning", ""))
            raw_confidence = entry.get("confidence", 0.5)

            if agent_id not in agent_ids:
                logger.warning(
                    "LLM returned unknown agent_id=%r for decision_type=%s — skipped",
                    agent_id,
                    decision_type.id,
                )
                continue

            if action not in valid_actions:
                logger.warning(
                    "LLM returned invalid action=%r for decision_type=%s (valid: %s) — skipped",
                    action,
                    decision_type.id,
                    ", ".join(sorted(valid_actions)),
                )
                continue

            try:
                confidence = float(raw_confidence)
                confidence = max(0.0, min(1.0, confidence))
            except (TypeError, ValueError):
                confidence = 0.5

            results.append(
                UniversalAgentDecision(
                    session_id="",       # caller will stamp
                    agent_id=agent_id,
                    round_number=0,      # caller will stamp
                    decision_type_id=decision_type.id,
                    action=action,
                    reasoning=reasoning,
                    confidence=confidence,
                )
            )

        logger.debug(
            "_deliberate_batch: decision_type=%s agents_in=%d valid_out=%d",
            decision_type.id,
            len(agents),
            len(results),
        )
        return results

    async def _ensure_schema(self) -> None:
        """Create agent_decisions table + index if not present (idempotent)."""
        if self._schema_initialised:
            return
        async with get_db() as db:
            await db.execute(_CREATE_TABLE_SQL)
            await db.execute(_CREATE_INDEX_SQL)
            await db.commit()
        self._schema_initialised = True
        logger.debug("agent_decisions schema ensured (universal engine)")

    async def _store_decisions(
        self,
        decisions: list[UniversalAgentDecision],
    ) -> None:
        """Batch insert decisions into agent_decisions table.

        Uses TEXT columns for agent_id, decision_type, and action so the
        existing schema supports both integer HK agent IDs and string
        universal agent IDs without migration.
        """
        rows = [
            (
                d.session_id,
                d.agent_id,
                d.round_number,
                d.decision_type_id,
                d.action,
                d.reasoning,
                d.confidence,
            )
            for d in decisions
        ]
        async with get_db() as db:
            await db.executemany(
                """
                INSERT INTO agent_decisions
                    (session_id, agent_id, round_number,
                     decision_type, action, reasoning, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            await db.commit()
        logger.debug("Stored %d universal decisions to DB", len(rows))


# ---------------------------------------------------------------------------
# DDL (reuses existing agent_decisions table from DecisionEngine)
# ---------------------------------------------------------------------------

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS agent_decisions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT    NOT NULL,
    agent_id      TEXT    NOT NULL,
    round_number  INTEGER NOT NULL,
    decision_type TEXT    NOT NULL,
    action        TEXT    NOT NULL,
    reasoning     TEXT,
    confidence    REAL    NOT NULL DEFAULT 0.5,
    created_at    TEXT    DEFAULT (datetime('now'))
);
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_decision_session
    ON agent_decisions(session_id, round_number);
"""

# ---------------------------------------------------------------------------
# Module-level pure helpers
# ---------------------------------------------------------------------------


def _filter_by_entity_type(
    agents: list[UniversalAgentProfile],
    decision_type: Any,
) -> list[UniversalAgentProfile]:
    """Return agents whose entity_type matches the decision type's filter.

    If applicable_entity_types is empty, all agents are eligible.

    Args:
        agents: Full agent list.
        decision_type: UniversalDecisionType with applicable_entity_types tuple.

    Returns:
        Filtered list of eligible agents.
    """
    allowed = decision_type.applicable_entity_types
    if not allowed:
        return list(agents)
    allowed_set = set(allowed)
    return [a for a in agents if a.entity_type in allowed_set]


def _sample_agents(
    eligible: list[UniversalAgentProfile],
    rate: float,
    cap: int,
) -> list[UniversalAgentProfile]:
    """Sample a cost-controlled subset of eligible agents.

    Takes max(1, floor(len(eligible) * rate)) agents, capped at `cap`.

    Args:
        eligible: Eligible agent list.
        rate: Fraction to sample (e.g. 0.20 for 20 %).
        cap: Hard maximum number of agents.

    Returns:
        Sampled list — preserves original relative ordering via random.sample.
    """
    n = min(cap, max(1, int(len(eligible) * rate)))
    if n >= len(eligible):
        return list(eligible)
    return random.sample(eligible, n)


def _agent_to_prompt_dict(agent: UniversalAgentProfile) -> dict[str, Any]:
    """Serialise a UniversalAgentProfile to a prompt-friendly dict.

    Args:
        agent: Agent profile to serialise.

    Returns:
        Dict suitable for JSON serialisation in the LLM prompt.
    """
    return {
        "id": agent.id,
        "name": agent.name,
        "entity_type": agent.entity_type,
        "persona": agent.persona,
        "goals": list(agent.goals),
        "capabilities": list(agent.capabilities),
        "stance_axes": {name: val for name, val in agent.stance_axes},
        "big_five": {
            "openness": round(agent.openness, 2),
            "conscientiousness": round(agent.conscientiousness, 2),
            "extraversion": round(agent.extraversion, 2),
            "agreeableness": round(agent.agreeableness, 2),
            "neuroticism": round(agent.neuroticism, 2),
        },
    }


def _compute_metric_deltas(
    decisions: list[UniversalAgentDecision],
    impact_rules: list[Any],     # list[UniversalImpactRule]
) -> dict[str, float]:
    """Aggregate metric deltas from decisions using impact rules.

    For each (decision_type_id, action) pair, finds all matching rules and
    computes delta = (net_count / 10) * rule.delta_per_10.  Multiple rules
    for the same metric are summed.

    Args:
        decisions: All agent decisions for the round.
        impact_rules: List of UniversalImpactRule objects from scenario config.

    Returns:
        Dict of metric_id → total delta (may be positive or negative).
    """
    # Count actions per (decision_type_id, action) key
    action_counts: dict[tuple[str, str], int] = {}
    for d in decisions:
        key = (d.decision_type_id, d.action)
        action_counts[key] = action_counts.get(key, 0) + 1

    metric_deltas: dict[str, float] = {}

    for rule in impact_rules:
        key = (rule.decision_type_id, rule.action)
        count = action_counts.get(key, 0)
        if count == 0:
            continue
        delta = (count / 10.0) * rule.delta_per_10
        metric_deltas[rule.metric_id] = (
            metric_deltas.get(rule.metric_id, 0.0) + delta
        )

    # Round to 4 dp for clean output
    return {k: round(v, 4) for k, v in metric_deltas.items()}


def _build_counts_by_type(
    decisions: list[UniversalAgentDecision],
) -> dict[str, dict[str, int]]:
    """Build a {decision_type_id: {action: count}} summary dict.

    Args:
        decisions: All agent decisions for the round.

    Returns:
        Nested count dict.
    """
    counts: dict[str, dict[str, int]] = {}
    for d in decisions:
        if d.decision_type_id not in counts:
            counts[d.decision_type_id] = {}
        counts[d.decision_type_id][d.action] = (
            counts[d.decision_type_id].get(d.action, 0) + 1
        )
    return counts
