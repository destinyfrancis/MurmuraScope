# backend/app/services/cognitive_agent_engine.py
"""Tier 1 Cognitive Agent Engine — full LLM deliberation every round.

Active in kg_driven mode only. Manages deliberation for the 30-100 high-importance
agents (political leaders, institutions, media outlets) that drive narrative emergence.

Phase 2 enrichment: agent_context now accepts optional fields:
  persona, goals, stance_axes, key_relationships, emotional_state, attachment_style
These are injected into the deliberation prompt when present, enabling richer
character-driven decisions (especially for relationship-oriented scenarios).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.utils.llm_client import LLMClient
from backend.app.utils.logger import get_logger

logger = get_logger(__name__)

_DELIBERATION_SYSTEM = """\
You are simulating a specific actor in a scenario. Respond as that actor would,
given their role, beliefs, emotional state, relationships, and current world events.
Be concise and decisive. Return only valid JSON."""

_DELIBERATION_USER = """\
Scenario: {scenario_description}
Active metrics: {active_metrics}

You are: {name} ({role}){persona_block}
Your core goals: {goals}
Your current beliefs: {current_beliefs}
Recent events you are aware of: {recent_events}
Your current faction: {faction}{emotional_block}{relationship_block}

Decide your action this round. Return JSON with:
- decision: (string slug) your chosen action
- reasoning: (1-3 sentences) why you chose this, referencing your relationships if relevant
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
                Optional enriched fields (Phase 2):
                  persona (str), goals (list[str]), stance_axes (list[tuple]),
                  key_relationships (list[dict]), emotional_state (dict),
                  attachment_style (dict with style/anxiety/avoidance).
            scenario_description: Short scenario summary.
            active_metrics: Metric IDs from UniversalScenarioConfig.

        Returns:
            DeliberationResult. Never raises — returns safe default on failure.
        """
        agent_id = str(agent_context.get("agent_id", "unknown"))
        user_content = _build_deliberation_prompt(
            agent_context=agent_context,
            scenario_description=scenario_description,
            active_metrics=active_metrics,
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


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _build_deliberation_prompt(
    agent_context: dict[str, Any],
    scenario_description: str,
    active_metrics: tuple[str, ...],
) -> str:
    """Build the enriched deliberation prompt string.

    Gracefully handles both the legacy context format (name, role, faction only)
    and the enriched format (Phase 2: persona, goals, relationships, emotional state).
    """
    agent_id = str(agent_context.get("agent_id", "unknown"))

    # Persona block (optional)
    persona = agent_context.get("persona", "")
    persona_block = f"\nPersona: {persona[:200]}" if persona else ""

    # Goals
    goals = agent_context.get("goals", [])
    goals_str = ", ".join(str(g) for g in goals[:5]) if goals else "none specified"

    # Emotional state block (optional)
    emotional_state = agent_context.get("emotional_state") or {}
    if emotional_state:
        val = float(emotional_state.get("valence", 0.0))
        aro = float(emotional_state.get("arousal", 0.3))
        emotional_block = f"\nEmotional state: valence={val:.2f}, arousal={aro:.2f}"
    else:
        emotional_block = ""

    # Relationship block (optional)
    key_relationships = agent_context.get("key_relationships") or []
    attachment = agent_context.get("attachment_style") or {}
    relationship_block = _build_relationship_block(key_relationships, attachment)

    return _DELIBERATION_USER.format(
        scenario_description=scenario_description[:300],
        active_metrics=list(active_metrics),
        name=agent_context.get("name", agent_id),
        role=agent_context.get("role", "actor"),
        persona_block=persona_block,
        goals=goals_str,
        current_beliefs=agent_context.get("current_beliefs", {}),
        recent_events=agent_context.get("recent_events", [])[-3:],
        faction=agent_context.get("faction", "none"),
        emotional_block=emotional_block,
        relationship_block=relationship_block,
    )


def _build_relationship_block(
    key_relationships: list[dict[str, Any]],
    attachment: dict[str, Any],
) -> str:
    """Build the relationship context string for the prompt."""
    if not key_relationships and not attachment:
        return ""

    lines: list[str] = ["\nRelationships:"]

    if attachment:
        style = attachment.get("style", "secure")
        anxiety = float(attachment.get("anxiety", 0.2))
        avoidance = float(attachment.get("avoidance", 0.2))
        lines.append(
            f"  Attachment style: {style} (anxiety={anxiety:.2f}, avoidance={avoidance:.2f})"
        )

    for rel in key_relationships[:5]:
        other = rel.get("other_id", "?")
        rel_type = rel.get("rel_type", "associate")
        intimacy = float(rel.get("intimacy", 0.1))
        trust = float(rel.get("trust", 0.0))
        commitment = float(rel.get("commitment", 0.1))
        lines.append(
            f"  - {other} [{rel_type}]: intimacy={intimacy:.2f}, "
            f"trust={trust:.2f}, commitment={commitment:.2f}"
        )

    return "\n".join(lines)


def _default_result(agent_id: str) -> DeliberationResult:
    return DeliberationResult(
        agent_id=agent_id,
        decision="observe",
        reasoning="No deliberation available.",
        belief_updates={},
        stance_statement="",
    )
