"""Prompt templates for ontology generation and entity extraction.

All templates use Python string formatting with named placeholders.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Default generic types (domain-agnostic fallback)
# ---------------------------------------------------------------------------

DEFAULT_GENERIC_ENTITY_TYPES: list[str] = [
    "Person",
    "Organization",
    "Country",
    "Event",
    "Location",
    "Policy",
    "Resource",
    "MediaOutlet",
    "MilitaryForce",
    "Institution",
]

DEFAULT_GENERIC_RELATION_TYPES: list[str] = [
    "SUPPORTS",
    "OPPOSES",
    "ALLIED_WITH",
    "CONFLICTS_WITH",
    "INFLUENCES",
    "CONTROLS",
    "REGULATES",
    "COMMENTS_ON",
    "BELONGS_TO",
    "DEPENDS_ON",
]


# ---------------------------------------------------------------------------
# Default HK-specific types
# ---------------------------------------------------------------------------

DEFAULT_HK_ENTITY_TYPES: list[str] = [
    "Person",
    "District",
    "Industry",
    "University",
    "GovernmentAgency",
    "MediaOutlet",
    "Bank",
    "PropertyDeveloper",
    "PoliticalFigure",
]

DEFAULT_HK_RELATION_TYPES: list[str] = [
    "LIVES_IN",
    "WORKS_IN",
    "SUPPORTS",
    "OPPOSES",
    "COMMENTS_ON",
    "AFFILIATED_WITH",
    "REGULATES",
    "COMPETES_WITH",
]


# ---------------------------------------------------------------------------
# Ontology generation: derive entity/relation types from a scenario
# ---------------------------------------------------------------------------

ONTOLOGY_GENERATION_SYSTEM = (
    "You are a knowledge graph ontology designer. Analyse the seed text to "
    "determine the domain and design an appropriate ontology. Given a scenario "
    "description, you produce a set of entity types and relation types that "
    "best capture the domain."
)

ONTOLOGY_GENERATION_USER = """\
Scenario type: {scenario_type}

Scenario description:
{seed_text}

Default entity types (you may keep, extend, or replace based on the scenario domain):
{default_entity_types}

Default relation types (you may keep, extend, or replace based on the scenario domain):
{default_relation_types}

Generate an ontology suitable for building a knowledge graph about this \
scenario. Return ONLY valid JSON with the following structure:

{{
  "entity_types": ["Type1", "Type2", ...],
  "relation_types": ["REL_1", "REL_2", ...]
}}

Guidelines:
- Include types from the defaults that are relevant to the scenario.
- Add new types specific to this scenario domain.
- Use PascalCase for entity types and UPPER_SNAKE_CASE for relation types.
- Keep the total between 8-20 entity types and 8-16 relation types.
"""


# ---------------------------------------------------------------------------
# Entity extraction: pull concrete entities from text + HK data
# ---------------------------------------------------------------------------

ENTITY_EXTRACTION_SYSTEM = (
    "You are a named entity recognition (NER) expert. "
    "Extract entities and relationships from the provided text and data."
)

ENTITY_EXTRACTION_USER = """\
Entity types to extract: {entity_types}
Relation types to detect: {relation_types}

Source text:
{seed_text}

Supplementary HK data:
{hk_data_json}

Extract all entities and relationships. Return ONLY valid JSON:

{{
  "nodes": [
    {{
      "id": "unique_snake_case_id",
      "entity_type": "TypeFromList",
      "title": "Display Name",
      "description": "Brief description of the entity",
      "properties": {{}}
    }}
  ],
  "edges": [
    {{
      "source_id": "node_id_1",
      "target_id": "node_id_2",
      "relation_type": "REL_FROM_LIST",
      "description": "How they are related",
      "weight": 1.0
    }}
  ]
}}

Guidelines:
- Use the supplied entity and relation types only.
- Generate a stable, unique ``id`` for each node (lowercase_with_underscores).
- Weight edges from 0.1 (weak) to 1.0 (strong).
- Include real-world entities where the data supports them.
"""


# ---------------------------------------------------------------------------
# Relationship detection between existing entities
# ---------------------------------------------------------------------------

RELATIONSHIP_DETECTION_SYSTEM = (
    "You are a relationship extraction expert. Given a set of entities and "
    "context, identify relationships between them."
)

RELATIONSHIP_DETECTION_USER = """\
Existing entities:
{entities_json}

Available relation types: {relation_types}

New context from simulation round:
{round_context}

Identify NEW relationships between the entities based on the round context. \
Return ONLY valid JSON:

{{
  "new_edges": [
    {{
      "source_id": "existing_node_id",
      "target_id": "existing_node_id",
      "relation_type": "REL_FROM_LIST",
      "description": "Relationship description",
      "weight": 1.0
    }}
  ],
  "updated_edges": [
    {{
      "source_id": "existing_node_id",
      "target_id": "existing_node_id",
      "relation_type": "REL_FROM_LIST",
      "new_weight": 0.8,
      "reason": "Why weight changed"
    }}
  ]
}}
"""


# ---------------------------------------------------------------------------
# Community detection summarisation
# ---------------------------------------------------------------------------

COMMUNITY_SUMMARY_SYSTEM = (
    "You are a community analyst for networks and communities. "
    "Summarise clusters of related entities."
)

COMMUNITY_SUMMARY_USER = """\
Community members:
{members_json}

Relationships among members:
{edges_json}

Provide a concise summary of this community. Return ONLY valid JSON:

{{
  "title": "Short descriptive title for this community",
  "summary": "2-4 sentence summary of what unites these entities and their significance in the scenario context"
}}
"""
