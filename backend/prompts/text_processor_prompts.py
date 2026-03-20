"""Prompt templates for seed text analysis (TextProcessor).

Universal: works for any domain — geopolitics, fiction, economics,
social dynamics, corporate competition, interpersonal scenarios, etc.
"""

from __future__ import annotations

ANALYZE_SEED_SYSTEM = """\
You are an expert analyst capable of processing seed text from ANY domain: \
geopolitics, economics, fiction, social dynamics, corporate competition, \
historical events, fantasy worlds, interpersonal relationships, and more.

Your task is to analyse a piece of text and extract structured data for a \
multi-agent social simulation engine.

KNOWLEDGE FIREWALL — CRITICAL:
You must extract information ONLY from the provided text. Do NOT inject your \
training knowledge about events, outcomes, or plot developments that occur \
AFTER the time horizon described in the text. If the text covers a novel's \
first three books, do NOT reference later books. Extract only what is \
explicitly present or directly implied by the text.

Respond in the SAME language as the seed text. If the text is in Chinese, \
respond in Chinese. If in English, respond in English.
Return ONLY valid JSON — no markdown, no code fences, no extra text."""

ANALYZE_SEED_USER = """\
Analyse the following text and extract key information. Return a JSON object.

TEXT:
{seed_text}

Return the following JSON structure (use the same language as the text):
{{
  "language": "<BCP-47 code: zh-HK | en-US | ja-JP | auto>",
  "entities": [
    {{"name": "<entity name>", "type": "<person|org|location|policy|economic|\
event|faction|creature|artifact|magical|military|media|institution|family|\
technology>", "relevance": 0.0-1.0}}
  ],
  "timeline": [
    {{"date_hint": "<time hint, e.g. 'March 2024' or 'Chapter 3' or \
'early period'>", "event": "<event description>"}}
  ],
  "stakeholders": [
    {{"group": "<stakeholder group>", "impact": "<positive|negative|neutral>", \
"description": "<impact description>"}}
  ],
  "sentiment": "positive|negative|neutral|mixed",
  "key_claims": ["<core claim 1>", "<core claim 2>"],
  "suggested_scenario": "<free-form scenario label that best describes this \
text, e.g. geopolitical_conflict, corporate_competition, fantasy_adventure, \
family_drama, property_market, social_movement, etc.>",
  "suggested_regions": ["<relevant regions, locations, or settings mentioned \
in the text — may be real places, fictional locations, or organisations>"],
  "confidence": 0.0-1.0
}}

Rules:
- entities: up to 40, sorted by relevance descending. Include ALL named \
  characters, organisations, factions, and significant entities.
- timeline: up to 15 events
- stakeholders: up to 20 groups, covering all significantly affected parties
- key_claims: up to 15 core themes or arguments
- suggested_regions: any relevant locations (real or fictional), up to 20
- Be thorough: missing entities will degrade simulation quality"""

SUGGEST_AGENTS_SYSTEM = """\
You are an expert simulation designer. Given a scenario analysis, suggest \
the optimal agent role distribution for a multi-agent simulation.
Respond in the SAME language as the provided summary.
Return ONLY valid JSON."""

SUGGEST_AGENTS_USER = """\
Based on the following scenario analysis, suggest agent role distribution:

Summary: {summary}
Scenario: {scenario}
Key stakeholders: {stakeholders}
Key regions: {districts}

Return JSON with suggested agent types and proportions:
{{
  "agent_suggestions": [
    {{
      "agent_type": "<role description>",
      "proportion": 0.0-1.0,
      "region_focus": ["<relevant regions>"],
      "rationale": "<why this group matters for this scenario>"
    }}
  ],
  "recommended_total": <integer 100-500>,
  "recommended_rounds": <integer 20-60>
}}

Ensure all proportion values sum to approximately 1.0."""
