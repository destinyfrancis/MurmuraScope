"""LLM prompt templates for MemoryInitializationService.

Phase 2: world context extraction (group memory)
Phase 3: persona template extraction (individual memory)
"""

# ---------------------------------------------------------------------------
# Phase 2: World Context Extraction
# ---------------------------------------------------------------------------

WORLD_CONTEXT_SYSTEM = """\
You are an expert social analyst. Extract macro-level world context from the
provided text that will serve as background knowledge for a social simulation.
Output ONLY valid JSON — no markdown, no explanation.
"""

WORLD_CONTEXT_USER = """\
Extract 4–8 macro-level world context entries from the text below.
These entries represent the social climate, core conflicts, and key events
that every agent in this simulation should be aware of from Round 0.

For each entry produce:
- "context_type": one of: social_climate | core_conflict | institutional_failure | public_event | reputation_risk | opportunity
- "title": short label (4–10 words, in the text's original language)
- "content": 2–4 sentence description providing rich background
- "severity": float 0.0–1.0 (how destabilising this context is)
- "phase": one of: pre_crisis | crisis | recovery

Output format — JSON array only:
[
  {{"context_type": "social_climate", "title": "...", "content": "...", "severity": 0.8, "phase": "crisis"}},
  ...
]

TEXT:
{seed_text}
"""

# ---------------------------------------------------------------------------
# Phase 3: Persona Template Extraction
# ---------------------------------------------------------------------------

PERSONA_TEMPLATE_SYSTEM = """\
You are an expert sociologist and simulation designer.
Extract distinct stakeholder personas from the provided text.
Output ONLY valid JSON — no markdown, no explanation.
"""

PERSONA_TEMPLATE_USER = """\
Identify 3–6 distinct stakeholder groups from the text below.
For each group, create an agent persona template for a social simulation.

CRITICAL: Each agent_type_key MUST be lowercase snake_case, 2–5 words,
derived from this specific scenario (e.g. student_rights_advocate,
institutional_defender, academic_researcher). Do NOT use generic labels.

For each persona produce:
- "agent_type_key": snake_case key unique to this scenario
- "display_name": human-readable name in the text's original language
- "age_min": minimum age (integer)
- "age_max": maximum age (integer)
- "region_hint": one of: local | outside_region | overseas | any
- "population_ratio": estimated share of public discussion (floats sum to ~1.0)
- "initial_memories": list of 2–4 first-person memory strings this agent type holds at Round 0 (in original language, visceral and specific)
- "personality_hints": object with keys:
    openness, conscientiousness, extraversion, agreeableness, neuroticism (each 0.0–1.0)
    key_concerns (list of 2–4 strings)
    preferred_platforms (list of platform names)
    stance_tendency (string: rights_advocate | institutional_defender | neutral_observer | academic_critic)
    verbal_patterns (list of 2–4 characteristic phrases/memes)
    trigger_topics (list of 2–4 topics that provoke strong reaction)

Output format — JSON array only:
[
  {{
    "agent_type_key": "...",
    "display_name": "...",
    "age_min": 18,
    "age_max": 22,
    "region_hint": "any",
    "population_ratio": 0.35,
    "initial_memories": ["...", "..."],
    "personality_hints": {{
      "openness": 0.8, "conscientiousness": 0.6, "extraversion": 0.5,
      "agreeableness": 0.3, "neuroticism": 0.75,
      "key_concerns": ["..."],
      "preferred_platforms": ["xiaohongshu", "bilibili"],
      "stance_tendency": "rights_advocate",
      "verbal_patterns": ["..."],
      "trigger_topics": ["..."]
    }}
  }},
  ...
]

TEXT:
{seed_text}
"""
