"""Agent Decision Engine orchestrator.

Coordinates rule-based eligibility filtering with LLM batch deliberation,
persists results to the ``agent_decisions`` table, and feeds aggregate
outcomes back into the macro state.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any, Awaitable, Callable

from backend.app.models.decision import AgentDecision, DecisionType, DecisionSummary
from backend.app.services.agent_factory import AgentProfile
from backend.app.services.decision_deliberator import DecisionDeliberator
from backend.app.services.decision_rules import filter_eligible_agents
from backend.app.services.macro_state import MacroState
from backend.app.utils.db import get_db
from backend.app.utils.llm_client import LLMClient
from backend.app.utils.logger import get_logger

logger = get_logger("decision_engine")

# ---------------------------------------------------------------------------
# DDL (created lazily on first use)
# ---------------------------------------------------------------------------

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS agent_decisions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT    NOT NULL,
    agent_id      INTEGER NOT NULL,
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
# Macro impact constants
# (how aggregate decisions shift macro indicators each round)
# ---------------------------------------------------------------------------

# ~0.1 CCL point per 100 transactions/month (HK monthly avg ~4,000 transactions)
_BUY_PROPERTY_CCL_DELTA: float = 0.3   # per 10 net-buy decisions

# 1 agent represents total_population / agent_count real people
# e.g. 100 agents = 1 agent ≈ 75,000 people; 10 net-emigrate ≈ 750,000 movement
_EMIGRATE_NET_MIG_DELTA: int = -50      # per 10 net-emigrate decisions (thousands)

# Individual retail investors have negligible HSI impact — institutional flows dominate
# Set to 0; kept as named constant for future institutional investor modelling
_INVEST_STOCKS_HSI_DELTA: float = 0.0   # retail investor impact ≈ 0

# HAVE_CHILD → small positive confidence boost (optimism signal)
_HAVE_CHILD_CONFIDENCE_DELTA: float = 0.2  # per 10 net-births

# ADJUST_SPENDING → spending cuts signal weak confidence
_ADJUST_SPENDING_CONFIDENCE_DELTA: float = -0.3  # per 10 net-cutters


# ---------------------------------------------------------------------------
# DecisionEngine
# ---------------------------------------------------------------------------

class DecisionEngine:
    """Orchestrates multi-type agent decision processing per simulation round."""

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        hook_config: "HookConfig | None" = None,
    ) -> None:
        from backend.app.models.simulation_config import HookConfig  # noqa: PLC0415
        self._deliberator = DecisionDeliberator(llm_client)
        self._schema_initialised = False
        hc = hook_config or HookConfig()
        self._sample_rate = hc.decision_sample_rate
        self._sample_cap = hc.decision_cap

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    async def process_round_decisions(
        self,
        session_id: str,
        round_number: int,
        profiles_by_id: dict[int, AgentProfile],
        macro_state: MacroState,
        macro_state_updater: Callable[[dict[str, float]], Awaitable[None]] | None = None,
        domain_pack_id: str = "hk_city",
    ) -> dict[str, Any]:
        """Run the full decision pipeline for one simulation round.

        Steps:
        1. Ensure DB schema exists.
        2. For each ``DecisionType``, filter eligible agents.
        3. Send eligible agents to LLM deliberation in batches.
        4. Persist all decisions to ``agent_decisions`` table.
        5. Derive macro state adjustments from aggregate decisions.
        6. Return a summary dict.

        Args:
            session_id: Simulation session UUID.
            round_number: Current round number.
            profiles_by_id: Map of agent_id → AgentProfile.
            macro_state: Current macro-economic state.

        Returns:
            Summary dict with counts per decision type.
        """
        await self._ensure_schema()

        all_profiles = list(profiles_by_id.values())
        all_decisions: list[AgentDecision] = []

        # Phase 3: Load emotional states to apply multipliers
        emotional_states: dict[int, Any] = {}
        dissonance_scores: dict[int, float] = {}
        try:
            from backend.app.services.emotional_engine import EmotionalEngine  # noqa: PLC0415
            from backend.app.utils.db import get_db as _get_db  # noqa: PLC0415
            eng = EmotionalEngine()
            async with _get_db() as _db:
                emotional_states = await eng.load_states(session_id, round_number, _db)
                # Load dissonance scores for this round
                cursor = await _db.execute(
                    """SELECT agent_id, dissonance_score FROM cognitive_dissonance
                    WHERE session_id = ? AND round_number = ?""",
                    (session_id, round_number),
                )
                for row in await cursor.fetchall():
                    dissonance_scores[int(row[0])] = float(row[1])
        except Exception:
            pass  # Emotional state coupling is optional — proceed without it

        # Build parallel tasks for all decision types that have eligible agents
        tasks = []
        for dt in DecisionType:
            eligible = filter_eligible_agents(all_profiles, macro_state, dt.value)
            # Phase 3: apply emotional state sampling adjustments
            eligible = _apply_emotional_sampling(eligible, dt.value, emotional_states, dissonance_scores)
            if eligible:
                tasks.append(self._deliberator.deliberate_batch(
                    eligible_agents=eligible,
                    macro_state=macro_state,
                    decision_type=dt.value,
                    session_id=session_id,
                    round_number=round_number,
                ))

        if tasks:
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in batch_results:
                if isinstance(result, Exception):
                    logger.error("Decision batch failed: %s", result)
                elif isinstance(result, list):
                    all_decisions.extend(result)

        if all_decisions:
            await self._store_decisions(all_decisions)

        # Build summary
        summary = _build_summary(session_id, round_number, all_decisions)

        # Derive macro adjustments (use pack deltas if available)
        try:
            from backend.app.domain.base import DomainPackRegistry  # noqa: PLC0415
            pack = DomainPackRegistry.get(domain_pack_id)
            impact_deltas = pack.macro_impact_deltas
        except (KeyError, ImportError):
            impact_deltas = None
        macro_adjustments = _derive_macro_adjustments(all_decisions, impact_deltas)
        if macro_adjustments:
            logger.info(
                "Macro adjustments from decisions session=%s round=%d: %s",
                session_id,
                round_number,
                macro_adjustments,
            )
            if macro_state_updater is not None:
                await macro_state_updater(macro_adjustments)

        # Include adjustments in summary so callers can apply them
        summary["macro_adjustments"] = macro_adjustments

        logger.info(
            "Decision engine: session=%s round=%d total=%d types=%d",
            session_id,
            round_number,
            summary["total_decisions"],
            len(summary["counts_by_type"]),
        )
        return summary

    async def get_decision_summary(
        self,
        session_id: str,
        round_number: int | None = None,
    ) -> DecisionSummary:
        """Retrieve aggregate decision counts for a session.

        Args:
            session_id: Simulation session UUID.
            round_number: If provided, filter to that round only.

        Returns:
            ``DecisionSummary`` with counts by type and action.
        """
        await self._ensure_schema()

        async with get_db() as db:
            if round_number is not None:
                cursor = await db.execute(
                    """
                    SELECT decision_type, action, COUNT(*) AS cnt
                    FROM agent_decisions
                    WHERE session_id = ? AND round_number = ?
                    GROUP BY decision_type, action
                    """,
                    (session_id, round_number),
                )
            else:
                cursor = await db.execute(
                    """
                    SELECT decision_type, action, COUNT(*) AS cnt
                    FROM agent_decisions
                    WHERE session_id = ?
                    GROUP BY decision_type, action
                    """,
                    (session_id,),
                )
            rows = await cursor.fetchall()

        counts_by_type: dict[str, dict[str, int]] = {}
        total = 0
        for row in rows:
            dt = row["decision_type"]
            action = row["action"]
            cnt = row["cnt"]
            if dt not in counts_by_type:
                counts_by_type[dt] = {}
            counts_by_type[dt][action] = cnt
            total += cnt

        return DecisionSummary(
            session_id=session_id,
            round_number=round_number,
            counts_by_type=counts_by_type,
            total_decisions=total,
        )

    async def get_agent_decisions(
        self,
        session_id: str,
        agent_id: int | None = None,
        round_number: int | None = None,
        decision_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Retrieve raw decision records for a session with optional filters.

        Args:
            session_id: Simulation session UUID.
            agent_id: Filter by specific agent.
            round_number: Filter by round.
            decision_type: Filter by decision type.
            limit: Max records to return.

        Returns:
            List of decision dicts.
        """
        await self._ensure_schema()

        clauses = ["session_id = ?"]
        params: list[Any] = [session_id]

        if agent_id is not None:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        if round_number is not None:
            clauses.append("round_number = ?")
            params.append(round_number)
        if decision_type is not None:
            clauses.append("decision_type = ?")
            params.append(decision_type)

        where = " AND ".join(clauses)
        params.append(limit)

        async with get_db() as db:
            cursor = await db.execute(
                f"""
                SELECT id, session_id, agent_id, round_number,
                       decision_type, action, reasoning, confidence, created_at
                FROM agent_decisions
                WHERE {where}
                ORDER BY round_number DESC, id DESC
                LIMIT ?
                """,
                tuple(params),
            )
            rows = await cursor.fetchall()

        return [dict(row) for row in rows]

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    async def _ensure_schema(self) -> None:
        """Create agent_decisions table if it does not exist (idempotent)."""
        if self._schema_initialised:
            return
        async with get_db() as db:
            await db.execute(_CREATE_TABLE_SQL)
            await db.execute(_CREATE_INDEX_SQL)
            await db.commit()
        self._schema_initialised = True
        logger.debug("agent_decisions schema ensured")

    async def _store_decisions(self, decisions: list[AgentDecision]) -> None:
        """Batch insert decisions into agent_decisions table."""
        rows = [
            (
                d.session_id,
                d.agent_id,
                d.round_number,
                d.decision_type,
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
        logger.debug("Stored %d decisions to DB", len(rows))


# ---------------------------------------------------------------------------
# Phase 3: Emotional state multipliers
# ---------------------------------------------------------------------------

def _apply_emotional_sampling(
    eligible: list[AgentProfile],
    decision_type: str,
    emotional_states: dict[int, Any],
    dissonance_scores: dict[int, float],
) -> list[AgentProfile]:
    """Filter or expand eligible agents based on emotional state multipliers.

    Rules (Phase 3 spec):
    - valence < -0.5 AND arousal > 0.7 → emigrate/protest probability ×1.5
      (implemented as increasing inclusion odds by keeping duplicates — here
      we use a simpler probability re-sample approach)
    - valence > 0.5 AND arousal < 0.3 → invest/buy probability ×1.3
    - dissonance_score > 0.7 → do_nothing probability ×1.5 (remove from eligible)

    For simplicity we use weighted random sampling rather than modifying
    the deliberation probabilities directly: agents with boosted probability
    are included with probability min(1, base_p × multiplier).

    Args:
        eligible: Agents eligible for this decision type.
        decision_type: Decision type string.
        emotional_states: Latest VAD states per agent_id.
        dissonance_scores: Latest dissonance scores per agent_id.

    Returns:
        Potentially filtered list of eligible agents.
    """
    import random as _random  # noqa: PLC0415

    if not emotional_states and not dissonance_scores:
        return eligible

    _HIGH_AROUSAL_TYPES = ("emigrate", "protest")
    _CALM_POSITIVE_TYPES = ("invest_stocks", "buy_property")
    _DO_NOTHING_TYPES = ("do_nothing",)

    result = []
    for profile in eligible:
        state = emotional_states.get(profile.id)
        dissonance = dissonance_scores.get(profile.id, 0.0)

        # High dissonance → much more likely to do nothing → remove from other types
        if dissonance > 0.7 and decision_type not in _DO_NOTHING_TYPES:
            # With 30% probability, skip (replaced by do_nothing tendency)
            if _random.random() < 0.3:
                continue

        if state is not None:
            valence = state.valence
            arousal = state.arousal

            if decision_type in _HIGH_AROUSAL_TYPES:
                # valence < -0.5 AND arousal > 0.7 → 1.5× inclusion odds
                if valence < -0.5 and arousal > 0.7:
                    # Include twice to boost sampling probability
                    result.append(profile)
                    if _random.random() < 0.5:  # net × 1.5
                        result.append(profile)
                    continue

            if decision_type in _CALM_POSITIVE_TYPES:
                # valence > 0.5 AND arousal < 0.3 → 1.3× inclusion odds
                if valence > 0.5 and arousal < 0.3:
                    result.append(profile)
                    if _random.random() < 0.3:  # net × 1.3
                        result.append(profile)
                    continue

        result.append(profile)

    return result


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _build_summary(
    session_id: str,
    round_number: int,
    decisions: list[AgentDecision],
) -> dict[str, Any]:
    """Build a summary dict from a list of AgentDecision objects."""
    counts: dict[str, dict[str, int]] = {}
    for d in decisions:
        if d.decision_type not in counts:
            counts[d.decision_type] = {}
        counts[d.decision_type][d.action] = counts[d.decision_type].get(d.action, 0) + 1

    return {
        "session_id": session_id,
        "round_number": round_number,
        "total_decisions": len(decisions),
        "counts_by_type": counts,
    }


def _derive_macro_adjustments(
    decisions: list[AgentDecision],
    impact_deltas: Any | None = None,
) -> dict[str, float]:
    """Compute macro-level adjustments implied by aggregate decisions.

    Does not mutate MacroState directly — the caller (simulation_runner) is
    responsible for applying these via ``MacroController.apply_overrides``.

    Args:
        decisions: List of agent decisions for the round.
        impact_deltas: Optional MacroImpactDeltas from a DomainPack.
            Falls back to module-level constants when None.

    Returns a dict of field_name → delta (can be positive or negative).
    """
    # Resolve delta values (pack overrides or module-level constants)
    ccl_delta = getattr(impact_deltas, "buy_property_ccl_delta", _BUY_PROPERTY_CCL_DELTA)
    mig_delta = getattr(impact_deltas, "emigrate_net_mig_delta", _EMIGRATE_NET_MIG_DELTA)
    hsi_delta = getattr(impact_deltas, "invest_stocks_hsi_delta", _INVEST_STOCKS_HSI_DELTA)
    child_delta = getattr(impact_deltas, "have_child_confidence_delta", _HAVE_CHILD_CONFIDENCE_DELTA)
    spend_delta = getattr(impact_deltas, "adjust_spending_confidence_delta", _ADJUST_SPENDING_CONFIDENCE_DELTA)

    adjustments: dict[str, float] = {}

    # Property: net buyers vs waiters
    property_decisions = [d for d in decisions if d.decision_type == DecisionType.BUY_PROPERTY]
    net_buyers = sum(1 for d in property_decisions if d.action == "buy") - \
                 sum(1 for d in property_decisions if d.action in ("rent_more", "sell"))
    if net_buyers != 0:
        adjustments["ccl_index"] = round((net_buyers / 10) * ccl_delta, 2)

    # Emigration: net emigrants
    emigrate_decisions = [d for d in decisions if d.decision_type == DecisionType.EMIGRATE]
    net_emigrants = sum(1 for d in emigrate_decisions if d.action == "emigrate") - \
                    sum(1 for d in emigrate_decisions if d.action == "stay")
    if net_emigrants != 0:
        adjustments["net_migration"] = float(
            (net_emigrants / 10) * mig_delta
        )

    # Investment: retail investors have negligible HSI impact (institutional flows dominate)
    invest_decisions = [d for d in decisions if d.decision_type == DecisionType.INVEST]
    net_investors = sum(1 for d in invest_decisions if d.action in ("invest_stocks", "diversify")) - \
                    sum(1 for d in invest_decisions if d.action == "hold_cash")
    if net_investors != 0 and hsi_delta != 0.0:
        adjustments["hsi_level"] = round((net_investors / 10) * hsi_delta, 2)

    # Child-bearing: net births → small positive confidence signal
    child_decisions = [d for d in decisions if d.decision_type == DecisionType.HAVE_CHILD]
    net_births = sum(1 for d in child_decisions if d.action == "have_child") - \
                 sum(1 for d in child_decisions if d.action in ("delay", "no_child"))
    if net_births != 0:
        adjustments["consumer_confidence"] = adjustments.get("consumer_confidence", 0.0) + \
            round((net_births / 10) * child_delta, 2)

    # Spending adjustment: net cutters → negative confidence feedback
    spending_decisions = [d for d in decisions if d.decision_type == DecisionType.ADJUST_SPENDING]
    net_cutters = sum(1 for d in spending_decisions if d.action in ("cut_spending", "save_more")) - \
                  sum(1 for d in spending_decisions if d.action in ("spend_more", "upgrade"))
    if net_cutters != 0:
        adjustments["consumer_confidence"] = adjustments.get("consumer_confidence", 0.0) + \
            round((net_cutters / 10) * spend_delta, 2)

    # Employment change: quit/lie_flat → unemployment rises; strike → GDP/confidence fall
    employment_decisions = [d for d in decisions if d.decision_type == DecisionType.EMPLOYMENT_CHANGE]
    net_quit = sum(1 for d in employment_decisions if d.action in ("quit", "lie_flat"))
    net_strike = sum(1 for d in employment_decisions if d.action == "strike")
    if net_quit > 0:
        # Each quit/lie_flat agent represents ~0.002 unemployment rate rise
        adjustments["unemployment_rate"] = adjustments.get("unemployment_rate", 0.0) + \
            round(net_quit * 0.002, 4)
    if net_strike > 0:
        # Strikes reduce GDP growth and dent consumer confidence
        adjustments["gdp_growth"] = adjustments.get("gdp_growth", 0.0) - \
            round(net_strike * 0.001, 4)
        adjustments["consumer_confidence"] = adjustments.get("consumer_confidence", 0.0) - \
            round(net_strike * 0.5, 2)

    # Relocate: GBA relocations reduce net_migration slightly (emigration proxy)
    relocate_decisions = [d for d in decisions if d.decision_type == DecisionType.RELOCATE]
    gba_relocators = sum(1 for d in relocate_decisions if d.action == "relocate_gba")
    if gba_relocators > 0:
        adjustments["net_migration"] = adjustments.get("net_migration", 0.0) + \
            float((gba_relocators / 10) * -10)

    return adjustments
