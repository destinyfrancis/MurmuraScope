"""LLM-based ontology generation for knowledge graph construction.

Given a scenario type and seed text, generates entity types and relation
types appropriate for the scenario domain. Supports both HK-specific and
generic (domain-agnostic) ontology defaults.
"""

from __future__ import annotations

from backend.app.utils.llm_client import LLMClient
from backend.app.utils.logger import get_logger
from backend.prompts.ontology_prompts import (
    DEFAULT_GENERIC_ENTITY_TYPES,
    DEFAULT_GENERIC_RELATION_TYPES,
    DEFAULT_HK_ENTITY_TYPES,
    DEFAULT_HK_RELATION_TYPES,
    ONTOLOGY_GENERATION_SYSTEM,
    ONTOLOGY_GENERATION_USER,
)

logger = get_logger("ontology_generator")


class OntologyGenerator:
    """Generate entity types and relation types for a given scenario.

    Uses an LLM to produce a tailored ontology based on the scenario domain.
    When ``domain_hint="hk"`` the HK-specific defaults are used (backward
    compatible). For all other values — including ``"auto"`` — the generic
    domain-agnostic defaults are used instead.
    Falls back to the selected defaults on LLM failure.
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
        domain_hint: str = "auto",
    ) -> tuple[list[str], list[str]]:
        """Generate ``(entity_types, relation_types)`` for the scenario.

        Args:
            scenario_type: High-level scenario category (e.g. "housing_crisis").
            seed_text: Narrative description of the scenario.
            domain_hint: Controls which default types are used as the LLM
                starting point.  Pass ``"hk"`` to use the HK-specific
                defaults (backward compatible).  Any other value — including
                the default ``"auto"`` — selects the generic domain-agnostic
                defaults.

        Returns:
            A tuple of (entity_types, relation_types) lists.
        """
        if domain_hint == "hk":
            default_entities: list[str] = DEFAULT_HK_ENTITY_TYPES
            default_relations: list[str] = DEFAULT_HK_RELATION_TYPES
        else:
            default_entities = DEFAULT_GENERIC_ENTITY_TYPES
            default_relations = DEFAULT_GENERIC_RELATION_TYPES

        messages = [
            {"role": "system", "content": ONTOLOGY_GENERATION_SYSTEM},
            {
                "role": "user",
                "content": ONTOLOGY_GENERATION_USER.format(
                    scenario_type=scenario_type,
                    seed_text=seed_text,
                    default_entity_types=", ".join(default_entities),
                    default_relation_types=", ".join(default_relations),
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
                default_entities,
            )
            relation_types = _validate_types(
                result.get("relation_types", []),
                default_relations,
            )
            logger.info(
                "Generated ontology (domain_hint=%s): %d entity types, %d relation types",
                domain_hint,
                len(entity_types),
                len(relation_types),
            )
            return entity_types, relation_types

        except Exception:
            logger.exception(
                "Ontology generation failed, falling back to defaults (domain_hint=%s)",
                domain_hint,
            )
            return list(default_entities), list(default_relations)


def _validate_types(raw: list[str], defaults: list[str]) -> list[str]:
    """Ensure the type list is non-empty and contains only strings."""
    validated = [t for t in raw if isinstance(t, str) and t.strip()]
    if not validated:
        return list(defaults)
    return validated
