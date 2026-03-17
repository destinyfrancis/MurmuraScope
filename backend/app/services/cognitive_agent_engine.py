# backend/app/services/cognitive_agent_engine.py
"""Tier 1 Cognitive Agent Engine — full LLM deliberation every round.

Active in kg_driven mode only. Manages deliberation for the 30-100 high-importance
agents (political leaders, institutions, media outlets) that drive narrative emergence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.utils.llm_client import LLMClient
from backend.app.utils.logger import get_logger

logger = get_logger(__name__)

_DELIBERATION_SYSTEM = """\
You are simulating a specific actor in a scenario. Respond as that actor would,
given their role, beliefs, and the current world events. Be concise and decisive.
Return only valid JSON."""

_DELIBERATION_USER = """\
Scenario: {scenario_description}
Active metrics: {active_metrics}

You are: {name} ({role})
Your current beliefs: {current_beliefs}
Recent events you are aware of: {recent_events}
Your current faction: {faction}

Decide your action this round. Return JSON with:
- decision: (string slug) your chosen action
- reasoning: (1-3 sentences) why you chose this
- belief_updates: (dict) metric_id → small delta (-0.3 to 0.3) reflecting how events changed your views
- stance_statement: (1 sentence) public statement or action you take

Return JSON: {{"decision": ..., "reasoning": ..., "belief_updates": {{...}}, "stance_statement": ...}}"""


@dataclass(frozen=True)
class DeliberationResult:
    agent_id: str
    decision: str
    reasoning: str
    belief_updates: dict[str, float]  # keys = subset of active_metrics
    stance_statement: str


class CognitiveAgentEngine:
    """Manage Tier 1 full-LLM deliberation for key agents each round."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm = llm_client or LLMClient()

    async def deliberate(
        self,
        agent_context: dict[str, Any],
        scenario_description: str,
        active_metrics: tuple[str, ...],
    ) -> DeliberationResult:
        """Run full LLM deliberation for one Tier 1 agent.

        Args:
            agent_context: Dict with agent_id, name, role, current_beliefs,
                recent_events, faction.
            scenario_description: Short scenario summary.
            active_metrics: Metric IDs from UniversalScenarioConfig.

        Returns:
            DeliberationResult. Never raises — returns safe default on failure.
        """
        agent_id = str(agent_context.get("agent_id", "unknown"))
        user_content = _DELIBERATION_USER.format(
            scenario_description=scenario_description[:300],
            active_metrics=list(active_metrics),
            name=agent_context.get("name", agent_id),
            role=agent_context.get("role", "actor"),
            current_beliefs=agent_context.get("current_beliefs", {}),
            recent_events=agent_context.get("recent_events", [])[-3:],
            faction=agent_context.get("faction", "none"),
        )
        messages = [
            {"role": "system", "content": _DELIBERATION_SYSTEM},
            {"role": "user", "content": user_content},
        ]

        try:
            raw = await self._llm.chat_json(messages, max_tokens=512, temperature=0.5)
        except Exception as exc:
            logger.warning("CognitiveAgentEngine: LLM failed for %s: %s", agent_id, exc)
            return _default_result(agent_id)

        active_set = set(active_metrics)
        raw_updates = raw.get("belief_updates", {})
        belief_updates = {
            k: max(-0.3, min(0.3, float(v)))
            for k, v in raw_updates.items()
            if k in active_set and isinstance(v, (int, float))
        }

        return DeliberationResult(
            agent_id=agent_id,
            decision=str(raw.get("decision", "observe")),
            reasoning=str(raw.get("reasoning", "")),
            belief_updates=belief_updates,
            stance_statement=str(raw.get("stance_statement", "")),
        )


def _default_result(agent_id: str) -> DeliberationResult:
    return DeliberationResult(
        agent_id=agent_id,
        decision="observe",
        reasoning="No deliberation available.",
        belief_updates={},
        stance_statement="",
    )
