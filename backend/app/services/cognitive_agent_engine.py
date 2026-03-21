# backend/app/services/cognitive_agent_engine.py
"""Cognitive Agent Engine — full LLM deliberation every round.

Active in kg_driven mode only. Manages deliberation for the 30-100 high-importance
stakeholder agents (political leaders, institutions, media outlets) that drive narrative emergence.

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
from backend.app.utils.prompt_security import sanitize_agent_field, sanitize_scenario_description

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
Recent events you are aware of: {recent_events}{memory_block}{feed_block}{trust_block}
Your current faction: {faction}
Risk appetite: {risk_appetite_block}{emotional_block}{relationship_block}{strategy_block}

Decide your action this round. Return JSON with:
- decision: (string slug) your chosen action
- reasoning: (1-3 sentences) why you chose this, referencing your relationships and past experience if relevant
- belief_updates: (dict) metric_id → small delta (-0.3 to 0.3) reflecting how events changed your views
- stance_statement: (1 sentence) public statement or action you take
- topic_tags: (list of 2-4 strings) topics this decision touches, e.g. ["移民","就業","制度","個人自由","家庭","身份認同"]
- emotional_reaction: (string, 5-15 chars) brief emotional state, e.g. "憤怒", "焦慮", "希望", "無奈", "決心"

Return JSON: {{"decision": ..., "reasoning": ..., "belief_updates": {{...}}, "stance_statement": ..., "topic_tags": [...], "emotional_reaction": ...}}"""


@dataclass(frozen=True)
class DeliberationResult:
    agent_id: str
    decision: str
    reasoning: str
    belief_updates: dict[str, float]  # keys = subset of active_metrics
    stance_statement: str
    topic_tags: tuple[str, ...] = ()
    """Topics this deliberation touches — used for topic evolution analysis."""
    emotional_reaction: str = ""
    """Brief emotional state during this deliberation — used for report interviews."""


class CognitiveAgentEngine:
    """Manage full-LLM deliberation for key stakeholder agents each round."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm = llm_client or LLMClient()

    async def deliberate(
        self,
        agent_context: dict[str, Any],
        scenario_description: str,
        active_metrics: tuple[str, ...],
        provider: str | None = None,
        model: str | None = None,
    ) -> DeliberationResult:
        """Run full LLM deliberation for one stakeholder agent.

        Args:
            agent_context: Dict with agent_id, name, role, current_beliefs,
                recent_events, faction.
                Optional enriched fields (Phase 2):
                  persona (str), goals (list[str]), stance_axes (list[tuple]),
                  key_relationships (list[dict]), emotional_state (dict),
                  attachment_style (dict with style/anxiety/avoidance).
            scenario_description: Short scenario summary.
            active_metrics: Metric IDs from UniversalScenarioConfig.
            provider: Optional LLM provider override (from get_agent_model).
            model: Optional LLM model override (from get_agent_model).

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

        llm_kwargs: dict[str, Any] = {"max_tokens": 1024, "temperature": 0.5}
        if provider is not None:
            llm_kwargs["provider"] = provider
        if model is not None:
            llm_kwargs["model"] = model

        try:
            raw = await self._llm.chat_json(messages, **llm_kwargs)
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

        # Extract topic_tags: filter to strings only, cap at 4
        raw_tags = raw.get("topic_tags", [])
        topic_tags: tuple[str, ...] = ()
        if isinstance(raw_tags, list):
            topic_tags = tuple(str(t) for t in raw_tags if isinstance(t, str))[:4]

        # Extract emotional_reaction: cap at 50 chars
        emotional_reaction = str(raw.get("emotional_reaction", ""))[:50]

        return DeliberationResult(
            agent_id=agent_id,
            decision=str(raw.get("decision", "observe")),
            reasoning=str(raw.get("reasoning", "")),
            belief_updates=belief_updates,
            stance_statement=str(raw.get("stance_statement", "")),
            topic_tags=topic_tags,
            emotional_reaction=emotional_reaction,
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
    safe_persona = sanitize_agent_field(persona) if persona else ""
    persona_block = f"\nPersona: {safe_persona}" if safe_persona else ""

    # Goals
    goals = agent_context.get("goals", [])
    goals_str = (
        ", ".join(sanitize_agent_field(str(g)) for g in goals[:5])
        if goals
        else "none specified"
    )

    # Emotional state block (optional)
    emotional_state = agent_context.get("emotional_state") or {}
    if emotional_state:
        val = float(emotional_state.get("valence", 0.0))
        aro = float(emotional_state.get("arousal", 0.3))
        emotional_block = f"\nEmotional state: valence={val:.2f}, arousal={aro:.2f}"
    else:
        emotional_block = ""

    # Risk appetite — derived from emotional state (Task 2.5)
    risk_appetite = _compute_risk_appetite(emotional_state)
    if risk_appetite < 0.35:
        risk_appetite_block = f"{risk_appetite:.2f} (cautious — prefer low-risk, defensive choices)"
    elif risk_appetite > 0.65:
        risk_appetite_block = f"{risk_appetite:.2f} (bold — willing to take aggressive or high-stakes actions)"
    else:
        risk_appetite_block = f"{risk_appetite:.2f} (neutral — weigh upside and downside evenly)"

    # Relationship block (optional) — with directive disposition (Task 2.4)
    key_relationships = agent_context.get("key_relationships") or []
    attachment = agent_context.get("attachment_style") or {}
    relationship_block = _build_relationship_block(key_relationships, attachment)

    # Memory block — top salient memories retrieved by caller (Task 2.6)
    recent_memories = agent_context.get("recent_memories", "")
    memory_block = f"\nYour relevant past memories:\n{recent_memories}" if recent_memories else ""

    # Feed context block — top feed items from social feed (Task 7)
    feed_context = agent_context.get("feed_context", "")
    feed_block = f"\nYour social feed this round:\n{feed_context}" if feed_context else ""

    # Trust context block — trusted/distrusted agents (Task 10)
    trust_context = agent_context.get("trust_context", "")
    trust_block = f"\nYour trust network:\n{trust_context}" if trust_context else ""

    # Strategy block — multi-round plan injected by StrategicPlanner (Phase 4)
    strategic_context = agent_context.get("strategic_context", "")
    strategy_block = strategic_context if strategic_context else ""

    safe_scenario = sanitize_scenario_description(scenario_description)
    safe_name = sanitize_agent_field(str(agent_context.get("name", agent_id)))
    safe_role = sanitize_agent_field(str(agent_context.get("role", "actor")))

    return _DELIBERATION_USER.format(
        scenario_description=safe_scenario,
        active_metrics=list(active_metrics),
        name=safe_name,
        role=safe_role,
        persona_block=persona_block,
        goals=goals_str,
        current_beliefs=agent_context.get("current_beliefs", {}),
        recent_events=agent_context.get("recent_events", [])[-3:],
        memory_block=memory_block,
        feed_block=feed_block,
        trust_block=trust_block,
        faction=agent_context.get("faction", "none"),
        risk_appetite_block=risk_appetite_block,
        emotional_block=emotional_block,
        relationship_block=relationship_block,
        strategy_block=strategy_block,
    )


def _compute_risk_appetite(emotional_state: dict[str, Any]) -> float:
    """Derive a risk appetite scalar [0, 1] from VAD emotional state.

    High arousal + negative valence → risk averse (0.2).
    High arousal + positive valence → risk seeking (0.8).
    Low arousal or neutral → risk neutral (0.5).
    """
    valence = float(emotional_state.get("valence", 0.0))  # -1 to 1
    arousal = float(emotional_state.get("arousal", 0.3))  # 0 to 1

    if arousal > 0.6:
        if valence < -0.2:
            return 0.2   # anxious / fearful → very cautious
        if valence > 0.2:
            return 0.8   # excited / enthusiastic → bold
    return 0.5


def _build_relationship_block(
    key_relationships: list[dict[str, Any]],
    attachment: dict[str, Any],
) -> str:
    """Build the relationship context string for the prompt.

    Appends a directive disposition line so the LLM receives explicit
    behavioural guidance from relationship state (Task 2.4).
    """
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

    high_trust = 0
    crisis = 0
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
        if trust > 0.3:
            high_trust += 1
        if trust < -0.3:
            crisis += 1

    # Directive disposition line
    if crisis > 0:
        disposition = "defensive"
        directive = "protect your interests and maintain boundaries"
    elif high_trust >= 2:
        disposition = "cooperative"
        directive = "seek alliance and support trusted allies"
    else:
        disposition = "neutral"
        directive = "weigh options independently before committing"
    lines.append(
        f"  Relationship disposition: {disposition} — {directive}."
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
