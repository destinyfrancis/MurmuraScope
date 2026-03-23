# backend/app/services/strategic_planner.py
"""Strategic multi-round planning for stakeholder agents.

Phase 4 addition.  Stakeholder agents produce a 3-round ahead plan every
``_PLAN_HORIZON`` rounds instead of only reacting to the current state.
The plan is stored in KGSessionState.agent_strategies and injected into the
deliberation prompt on subsequent rounds, giving agents persistent strategic
intent rather than pure reactive decisions.

Information warfare extension:
  If an agent's relationship trust score is critically low (< _DISTRUST_THRESHOLD),
  the planner flags the agent's stance as "contested" and marks their stance_statement
  as potentially adversarial.  This is surfaced in the API but does NOT alter the
  core belief propagation — the interpreter must decide how to weight contested agents.

Usage::

    planner = StrategicPlanner()
    await planner.update_plans(kg_state, stakeholder_agents, round_num, scenario_description)
    # kg_state.agent_strategies is updated in-place
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.utils.llm_client import LLMClient
from backend.app.utils.logger import get_logger
from backend.app.utils.prompt_security import sanitize_agent_field, sanitize_scenario_description

logger = get_logger(__name__)

# Re-plan every N rounds
_PLAN_HORIZON = 3

# Minimum trust score below which an agent's stance is flagged "contested"
_DISTRUST_THRESHOLD = -0.3

_STRATEGY_SYSTEM = """\
You are simulating a strategic political/social actor who plans multiple rounds ahead.
Given their current situation, produce a concrete 3-round action plan.
Be concise. Return only valid JSON."""

_STRATEGY_USER = """\
Scenario: {scenario_description}

You are: {name} ({role})
Your current faction: {faction}
Your current beliefs: {current_beliefs}
Your recent decision: {last_decision}
Recent world events: {recent_events}

Produce a 3-round strategic plan. Return JSON:
{{
  "plan": "(1-2 sentences) your overarching strategic objective for the next 3 rounds",
  "round_1_intent": "(slug) intended decision next round",
  "round_2_intent": "(slug) intended decision in 2 rounds",
  "round_3_intent": "(slug) intended decision in 3 rounds",
  "information_posture": "transparent" | "strategic" | "adversarial"
}}"""


@dataclass(frozen=True)
class AgentStrategy:
    """Immutable strategic plan for one stakeholder agent."""

    agent_id: str
    plan: str
    round_1_intent: str
    round_2_intent: str
    round_3_intent: str
    information_posture: str  # "transparent" | "strategic" | "adversarial"
    created_round: int
    is_contested: bool  # True if trust score < _DISTRUST_THRESHOLD


class StrategicPlanner:
    """Generate and maintain multi-round strategic plans for stakeholder agents."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm = llm_client or LLMClient()

    async def update_plans(
        self,
        kg_state: Any,  # KGSessionState
        stakeholder_agents: list[dict[str, Any]],
        round_num: int,
        scenario_description: str,
    ) -> None:
        """Refresh strategic plans for all stakeholder agents.

        Plans are refreshed every _PLAN_HORIZON rounds.  On off-rounds, the
        existing plan is carried forward unchanged.

        Mutates ``kg_state.agent_strategies`` in-place.

        Args:
            kg_state: KGSessionState instance for this session.
            stakeholder_agents: List of stakeholder agent context dicts.
            round_num: Current simulation round.
            scenario_description: Scenario summary for prompt context.
        """
        if round_num % _PLAN_HORIZON != 0:
            return  # off-round — carry forward existing plans

        safe_scenario = sanitize_scenario_description(scenario_description)

        for agent in stakeholder_agents:
            agent_id = str(agent.get("agent_id", ""))
            if not agent_id:
                continue

            strategy = await self._plan_for_agent(agent, safe_scenario, round_num, kg_state)
            kg_state.agent_strategies[agent_id] = {
                "plan": strategy.plan,
                "round_1_intent": strategy.round_1_intent,
                "round_2_intent": strategy.round_2_intent,
                "round_3_intent": strategy.round_3_intent,
                "information_posture": strategy.information_posture,
                "is_contested": strategy.is_contested,
                "created_round": round_num,
            }

        logger.info(
            "StrategicPlanner: updated plans for %d stakeholder agents at round %d",
            len(stakeholder_agents),
            round_num,
        )

    def get_strategy_context(
        self,
        kg_state: Any,
        agent_id: str,
        current_round: int,
    ) -> str:
        """Return a strategy context string to inject into the deliberation prompt.

        Returns empty string if no plan exists or plan is stale (> horizon rounds old).
        """
        plan = kg_state.agent_strategies.get(agent_id)
        if not plan:
            return ""

        age = current_round - plan.get("created_round", 0)
        if age > _PLAN_HORIZON * 2:
            return ""  # stale plan — ignore

        contested_note = " [CONTESTED SOURCE]" if plan.get("is_contested") else ""
        return (
            f"\nYour current strategic plan{contested_note}: {plan['plan']} "
            f"(This round intent: {plan.get('round_1_intent', 'observe')}; "
            f"posture: {plan.get('information_posture', 'transparent')})"
        )

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    async def _plan_for_agent(
        self,
        agent: dict[str, Any],
        safe_scenario: str,
        round_num: int,
        kg_state: Any,
    ) -> AgentStrategy:
        agent_id = str(agent.get("agent_id", "unknown"))
        name = sanitize_agent_field(str(agent.get("name", agent_id)))
        role = sanitize_agent_field(str(agent.get("role", "actor")))
        faction = kg_state.agent_factions.get(agent_id, agent.get("faction", "none"))
        current_beliefs = kg_state.agent_beliefs.get(agent_id, {})
        recent_events = kg_state.current_round_events[-2:] if kg_state.current_round_events else []

        # Detect contested status from relationship trust
        is_contested = _check_contested(agent, kg_state, agent_id)

        # Last decision from agent_strategies (if exists)
        last_plan = kg_state.agent_strategies.get(agent_id, {})
        last_decision = last_plan.get("round_1_intent", "observe")

        user_content = _STRATEGY_USER.format(
            scenario_description=safe_scenario,
            name=name,
            role=role,
            faction=faction,
            current_beliefs=current_beliefs,
            last_decision=last_decision,
            recent_events=[str(e) for e in recent_events],
        )

        messages = [
            {"role": "system", "content": _STRATEGY_SYSTEM},
            {"role": "user", "content": user_content},
        ]

        try:
            raw = await self._llm.chat_json(messages, max_tokens=300, temperature=0.4)
        except Exception as exc:
            logger.debug("StrategicPlanner: LLM failed for %s: %s", agent_id, exc)
            return _default_strategy(agent_id, round_num, is_contested)

        return AgentStrategy(
            agent_id=agent_id,
            plan=str(raw.get("plan", "maintain current position")),
            round_1_intent=str(raw.get("round_1_intent", "observe")),
            round_2_intent=str(raw.get("round_2_intent", "observe")),
            round_3_intent=str(raw.get("round_3_intent", "observe")),
            information_posture=_validated_posture(raw.get("information_posture", "transparent")),
            created_round=round_num,
            is_contested=is_contested,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_contested(
    agent: dict[str, Any],
    kg_state: Any,
    agent_id: str,
) -> bool:
    """Return True if the agent has critically low trust in any key relationship."""
    rel_states = kg_state.relationship_states
    for (a, b), rel in rel_states.items():
        if a == agent_id or b == agent_id:
            trust = getattr(rel, "trust", None)
            if trust is not None and float(trust) < _DISTRUST_THRESHOLD:
                return True
    return False


def _validated_posture(raw: Any) -> str:
    valid = {"transparent", "strategic", "adversarial"}
    s = str(raw).lower()
    return s if s in valid else "transparent"


def _default_strategy(agent_id: str, round_num: int, is_contested: bool) -> AgentStrategy:
    return AgentStrategy(
        agent_id=agent_id,
        plan="maintain current position and monitor developments",
        round_1_intent="observe",
        round_2_intent="observe",
        round_3_intent="observe",
        information_posture="transparent",
        created_round=round_num,
        is_contested=is_contested,
    )
