"""LLM-based ontology generation for knowledge graph construction.

Given a scenario type and seed text, generates entity types and relation
types tailored to the Hong Kong socioeconomic domain.
"""

from __future__ import annotations

from backend.app.utils.llm_client import LLMClient
from backend.app.utils.logger import get_logger
from backend.prompts.ontology_prompts import (
    DEFAULT_HK_ENTITY_TYPES,
    DEFAULT_HK_RELATION_TYPES,
    ONTOLOGY_GENERATION_SYSTEM,
    ONTOLOGY_GENERATION_USER,
)

logger = get_logger("ontology_generator")


class OntologyGenerator:
    """Generate entity types and relation types for a given scenario.

    Uses an LLM to extend the default HK ontology with scenario-specific
    types. Falls back to defaults on LLM failure.
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        provider: str = "fireworks",
    ) -> None:
        self._llm = llm_client or LLMClient()
        self._provider = provider

    async def generate(
        self,
        scenario_type: str,
        seed_text: str,
    ) -> tuple[list[str], list[str]]:
        """Generate ``(entity_types, relation_types)`` for the scenario.

        Args:
            scenario_type: High-level scenario category (e.g. "housing_crisis").
            seed_text: Narrative description of the scenario.

        Returns:
            A tuple of (entity_types, relation_types) lists.
        """
        messages = [
            {"role": "system", "content": ONTOLOGY_GENERATION_SYSTEM},
            {
                "role": "user",
                "content": ONTOLOGY_GENERATION_USER.format(
                    scenario_type=scenario_type,
                    seed_text=seed_text,
                    default_entity_types=", ".join(DEFAULT_HK_ENTITY_TYPES),
                    default_relation_types=", ".join(DEFAULT_HK_RELATION_TYPES),
                ),
            },
        ]

        try:
            result = await self._llm.chat_json(
                messages,
                provider=self._provider,
                temperature=0.4,
                max_tokens=2048,
            )
            entity_types = _validate_types(
                result.get("entity_types", []),
                DEFAULT_HK_ENTITY_TYPES,
            )
            relation_types = _validate_types(
                result.get("relation_types", []),
                DEFAULT_HK_RELATION_TYPES,
            )
            logger.info(
                "Generated ontology: %d entity types, %d relation types",
                len(entity_types),
                len(relation_types),
            )
            return entity_types, relation_types

        except Exception:
            logger.exception(
                "Ontology generation failed, falling back to defaults"
            )
            return list(DEFAULT_HK_ENTITY_TYPES), list(DEFAULT_HK_RELATION_TYPES)


def _validate_types(raw: list[str], defaults: list[str]) -> list[str]:
    """Ensure the type list is non-empty and contains only strings."""
    validated = [t for t in raw if isinstance(t, str) and t.strip()]
    if not validated:
        return list(defaults)
    return validated
