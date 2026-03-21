"""Prompt templates for KG-driven universal agent generation.

These prompts are intentionally domain-agnostic — they contain no references
to Hong Kong or any specific geography.  They work for any scenario that has
been encoded as a knowledge graph: geopolitical conflicts, corporate
competition, historical events, social movements, etc.

Two-stage pipeline
------------------
Stage 1 — Eligibility filter
    Given raw KG nodes, identify which ones should become simulation agents
    (concrete actors) vs. abstract concepts.

Stage 2 — Profile generation
    Given eligible nodes + KG edges + original seed text, generate a full
    UniversalAgentProfile for each agent, including persona, goals,
    capabilities, stance axes, and Big Five personality traits.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Stage 1: Eligibility Filter
# ---------------------------------------------------------------------------

AGENT_ELIGIBLE_FILTER_SYSTEM = """\
You are an expert knowledge graph analyst specialising in multi-agent simulation design.

Your task is to examine a list of knowledge graph nodes and determine which nodes \
represent concrete, autonomous actors that can meaningfully participate in a simulation \
as independent agents.

KNOWLEDGE FIREWALL — CRITICAL:
You must reason ONLY from the provided seed text and knowledge graph data.
Do NOT use your training knowledge about events, outcomes, or plot developments \
that occur AFTER the time horizon described in the seed text.
If the seed text covers a novel's first three books, do NOT reference or use \
knowledge of subsequent books. If it describes events up to a specific date, \
do NOT use knowledge of what happened after that date. Predictions and agent \
characterisation must emerge from the provided data, not from foreknowledge.

INCLUDE as agents:
- Individual persons (politicians, executives, activists, historical figures)
- Nation-states or governments acting as unified actors
- Military organisations or armed groups
- Companies or corporations
- Media outlets or news organisations
- Political parties or movements
- Non-governmental organisations (NGOs)
- Religious or cultural institutions when they act as decision-making bodies
- Fictional factions, secret societies, magical organisations, family clans
- Criminal networks, underground movements, resistance groups
- Supernatural or non-human entities when they act as autonomous decision-makers
- Any entity that has goals, makes decisions, and can take actions

EXCLUDE from agents (these are context nodes, not actors):
- Abstract concepts (e.g. "Trade War", "Climate Change", "Inflation")
- Events (e.g. "2008 Financial Crisis", "Election Day")
- Locations used purely as geography (e.g. "South China Sea" as a place)
- Economic indicators or metrics
- Ideologies or doctrines (e.g. "Liberalism", "Islamism") unless they are embodied \
  by a specific organisation
- Time periods or eras

Return ONLY valid JSON with no markdown, no code fences, no extra text.
Output schema:
{
  "eligible": [
    {
      "node_id": "<original KG node id>",
      "label": "<node label>",
      "entity_type": "<one of: Person | Country | Military | Organization | \
MediaOutlet | PoliticalFigure | Company | NGO | Institution | Faction | \
Family | SecretSociety | Creature | Supernatural>",
      "reason": "<one sentence explaining why this node is an eligible agent>"
    }
  ],
  "excluded": [
    {
      "node_id": "<original KG node id>",
      "label": "<node label>",
      "reason": "<one sentence explaining why this node is NOT an agent>"
    }
  ]
}"""

AGENT_ELIGIBLE_FILTER_USER = """\
Analyse the following knowledge graph nodes and classify each as agent-eligible \
or not according to the criteria in the system prompt.

KG NODES:
{nodes_json}

Return valid JSON only."""

# ---------------------------------------------------------------------------
# Stage 2: Agent Profile Generation
# ---------------------------------------------------------------------------

AGENT_GENERATION_SYSTEM = """\
You are an expert in multi-agent simulation and social science modelling.

Your task is to generate rich, realistic agent profiles for a simulation based on \
knowledge graph entities and their relationships.  Each profile will directly drive \
an autonomous agent in the simulation — the persona text becomes the agent's \
"character" that governs how it communicates, reasons, and makes decisions.

KNOWLEDGE FIREWALL — CRITICAL:
You must reason ONLY from the provided seed text and knowledge graph data.
Do NOT use your training knowledge about events, outcomes, or plot developments \
that occur AFTER the time horizon described in the seed text.
If the seed text covers a novel's first three books, do NOT reference or use \
knowledge of subsequent books. If it describes events up to a specific date, \
do NOT use knowledge of what happened after that date. Agent personas, goals, \
and stances must be grounded solely in the provided seed material.

PROFILE REQUIREMENTS
--------------------
1. id
   - URL-safe slug using lowercase letters, digits, and underscores
   - Must be unique across all agents in this batch
   - Examples: "iran_supreme_leader", "us_department_of_defense", "reuters_news"

2. name
   - Human-readable display name; use the language most natural for this entity
   - Include title or position if it adds meaningful context

3. role
   - One concise sentence describing what this agent does in the scenario

4. entity_type
   - One of: Person | Country | Military | Organization | MediaOutlet |
     PoliticalFigure | Company | NGO | Institution | Faction | Family |
     SecretSociety | Creature | Supernatural

5. persona (CRITICAL — 2–4 sentences)
   - Captures the agent's worldview, typical communication style, and \
decision-making heuristics
   - Must be grounded in the agent's real-world characteristics as reflected \
in the KG
   - This text is fed verbatim to the simulation engine as the agent's character card

6. goals (2–5 items)
   - Core objectives the agent pursues during the simulation
   - Should be specific and actionable, not generic
   - Infer from KG node properties and edges

7. capabilities (2–6 items)
   - Concrete resources, tools, or powers available to this agent
   - Should reflect the agent's real-world influence mechanisms

8. stance_axes
   - Infer 3–7 axes that are RELEVANT TO THIS SCENARIO (not generic axes)
   - Each axis is a named dimension with a float value in [0.0, 1.0]
   - Examples for a geopolitical scenario: militarism, diplomacy, nationalism, \
economic_openness, domestic_stability_focus
   - Examples for a corporate scenario: innovation_risk_tolerance, \
market_aggression, regulatory_compliance, stakeholder_focus
   - Use the SAME axis names across ALL agents so stances can be compared
   - Base axis values on the agent's known positions, not random assignment

9. Big Five personality traits (openness, conscientiousness, extraversion,
   agreeableness, neuroticism)
   - Each is a float in [0.0, 1.0] where 0.5 is the neutral midpoint
   - Must be internally consistent with the persona and role
   - Examples: a cautious bureaucrat → high conscientiousness, low openness;
     a charismatic populist → high extraversion, low agreeableness

10. relationships
    - Derive from KG edges provided
    - Each entry: (other_agent_id, description)
    - Description should be a short phrase, e.g. "strategic rival", \
"military ally", "media critic of"

11. activity_level (float 0.0–1.0)
    - How frequently this actor participates in public discourse each round
    - High (0.7–1.0): heads of state, active military commanders, \
media outlets, social media-savvy activists
    - Medium (0.4–0.6): advisory bodies, mid-level officials, smaller companies
    - Low (0.1–0.3): secretive organisations, behind-the-scenes power brokers, \
passive observers

12. influence_weight (float 0.0–3.0)
    - How visible and impactful this actor's communications are when they do act
    - 2.0–3.0: superpower nations, global media outlets, dominant market leaders
    - 1.0–1.5: regional powers, mid-size companies, established NGOs
    - 0.3–0.9: minor actors, local organisations, background characters

ADDITIONAL AGENTS
-----------------
If the scenario context implies important actors that are NOT in the eligible \
node list but are essential for a realistic simulation, you MUST generate \
profiles for them too (up to the target_count limit).  Mark these with \
entity_type "Inferred" so the caller knows they were not directly in the KG.

OUTPUT FORMAT
-------------
Return ONLY valid JSON with no markdown, no code fences, no extra text.
{
  "agents": [
    {
      "id": "...",
      "name": "...",
      "role": "...",
      "entity_type": "...",
      "persona": "...",
      "goals": ["...", "..."],
      "capabilities": ["...", "..."],
      "stance_axes": {"axis_name": 0.0, ...},
      "relationships": {"other_agent_id": "description", ...},
      "openness": 0.5,
      "conscientiousness": 0.5,
      "extraversion": 0.5,
      "agreeableness": 0.5,
      "neuroticism": 0.5,
      "kg_node_id": "...",
      "activity_level": 0.5,
      "influence_weight": 1.0
    }
  ]
}"""

AGENT_GENERATION_USER = """\
Generate simulation agent profiles for the following scenario.

SCENARIO SEED TEXT:
{seed_text}

ELIGIBLE KG NODES (generate one agent per node, plus inferred agents if needed):
{eligible_nodes_json}

KG EDGES (use to populate relationships and infer stances):
{edges_json}

TARGET AGENT COUNT: {target_count}
If there are fewer eligible nodes than target_count, generate additional \
plausible agents implied by the scenario to reach the target.

Requirements:
- Use the SAME stance axis names across ALL agents
- All stance values must be in [0.0, 1.0]
- All Big Five values must be in [0.0, 1.0]
- The persona field (2–4 sentences) must be rich enough to drive autonomous \
  behaviour in the simulation
- Infer relationships from the KG edges provided

Return valid JSON only."""
