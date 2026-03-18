"""Prompt templates for relationship simulation.

Used by:
- CognitiveAgentEngine.deliberate() — enriched context injection
- (Future) Relationship narrative generation

All templates are plain strings; no LLM calls in this module.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# CognitiveAgentEngine enriched context block
# ---------------------------------------------------------------------------

RELATIONSHIP_CONTEXT_BLOCK = """\
Your attachment style: {attachment_style} (anxiety={anxiety:.2f}, avoidance={avoidance:.2f})
Key relationships:
{relationship_summary}"""

RELATIONSHIP_SUMMARY_LINE = "  - {other_id} [{rel_type}]: intimacy={intimacy:.2f}, trust={trust:.2f}, commitment={commitment:.2f}"

# ---------------------------------------------------------------------------
# Enriched deliberation prompt (replaces _DELIBERATION_USER in cognitive_agent_engine)
# ---------------------------------------------------------------------------

ENRICHED_DELIBERATION_SYSTEM = """\
You are simulating a specific actor in a scenario. Respond as that actor would,
given their role, beliefs, emotional state, relationships, and current world events.
Be concise and decisive. Return only valid JSON."""

ENRICHED_DELIBERATION_USER = """\
Scenario: {scenario_description}
Active metrics: {active_metrics}

You are: {name} ({role})
Persona: {persona}
Your core goals: {goals}
Your current beliefs: {current_beliefs}
Recent events you are aware of: {recent_events}
Your current faction: {faction}
Emotional state: valence={valence:.2f}, arousal={arousal:.2f}
{attachment_block}

Decide your action this round. Return JSON with:
- decision: (string slug) your chosen action
- reasoning: (1-3 sentences) why you chose this, referencing your relationships if relevant
- belief_updates: (dict) metric_id → small delta (-0.3 to 0.3) reflecting how events changed your views
- stance_statement: (1 sentence) public statement or action you take

Return JSON: {{"decision": ..., "reasoning": ..., "belief_updates": {{...}}, "stance_statement": ...}}"""
