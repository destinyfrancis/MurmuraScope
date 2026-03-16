"""Entity extraction from seed text and HK data.

Extracts concrete entities (nodes) and relationships (edges) using an LLM,
guided by the ontology's entity types and relation types.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from backend.app.utils.llm_client import LLMClient
from backend.app.utils.logger import get_logger
from backend.prompts.ontology_prompts import (
    ENTITY_EXTRACTION_SYSTEM,
    ENTITY_EXTRACTION_USER,
    RELATIONSHIP_DETECTION_SYSTEM,
    RELATIONSHIP_DETECTION_USER,
)

logger = get_logger("entity_extractor")


class EntityExtractor:
    """Extract entities and relationships from text and structured HK data.

    Uses an LLM to perform named entity recognition and relation extraction
    within the ontology defined by the provided type lists.
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        provider: str = "fireworks",
    ) -> None:
        self._llm = llm_client or LLMClient()
        self._provider = provider

    async def extract(
        self,
        seed_text: str,
        hk_data: dict[str, Any],
        entity_types: list[str],
        relation_types: list[str],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Extract nodes and edges from seed text and HK data.

        Args:
            seed_text: Scenario narrative text.
            hk_data: Supplementary structured HK data.
            entity_types: Allowed entity types from the ontology.
            relation_types: Allowed relation types from the ontology.

        Returns:
            A tuple of (nodes, edges) where each node is a dict with keys
            ``{id, entity_type, title, description, properties}`` and each
            edge is ``{source_id, target_id, relation_type, description, weight}``.
        """
        messages = [
            {"role": "system", "content": ENTITY_EXTRACTION_SYSTEM},
            {
                "role": "user",
                "content": ENTITY_EXTRACTION_USER.format(
                    entity_types=", ".join(entity_types),
                    relation_types=", ".join(relation_types),
                    seed_text=seed_text,
                    hk_data_json=json.dumps(hk_data, ensure_ascii=False, indent=2),
                ),
            },
        ]

        try:
            result = await self._llm.chat_json(
                messages,
                provider=self._provider,
                temperature=0.3,
                max_tokens=4096,
            )
            raw_nodes = result.get("nodes", [])
            raw_edges = result.get("edges", [])

            nodes = _validate_nodes(raw_nodes, entity_types)
            edges = _validate_edges(raw_edges, nodes, relation_types)

            logger.info(
                "Extracted %d nodes and %d edges", len(nodes), len(edges)
            )
            return nodes, edges

        except Exception:
            logger.exception("Entity extraction failed")
            return [], []

    async def extract_from_round(
        self,
        existing_nodes: list[dict[str, Any]],
        relation_types: list[str],
        round_context: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Extract new/updated edges from a simulation round.

        Args:
            existing_nodes: Current graph nodes.
            relation_types: Allowed relation types.
            round_context: Text describing what happened in this round.

        Returns:
            A tuple of (new_edges, updated_edges).
        """
        entities_summary = [
            {"id": n["id"], "title": n["title"], "entity_type": n["entity_type"]}
            for n in existing_nodes
        ]

        messages = [
            {"role": "system", "content": RELATIONSHIP_DETECTION_SYSTEM},
            {
                "role": "user",
                "content": RELATIONSHIP_DETECTION_USER.format(
                    entities_json=json.dumps(
                        entities_summary, ensure_ascii=False, indent=2
                    ),
                    relation_types=", ".join(relation_types),
                    round_context=round_context,
                ),
            },
        ]

        try:
            result = await self._llm.chat_json(
                messages,
                provider=self._provider,
                temperature=0.3,
                max_tokens=2048,
            )
            new_edges = result.get("new_edges", [])
            updated_edges = result.get("updated_edges", [])

            node_ids = {n["id"] for n in existing_nodes}
            new_edges = [
                e for e in new_edges
                if e.get("source_id") in node_ids and e.get("target_id") in node_ids
            ]

            logger.info(
                "Round extraction: %d new edges, %d updated edges",
                len(new_edges),
                len(updated_edges),
            )
            return new_edges, updated_edges

        except Exception:
            logger.exception("Round entity extraction failed")
            return [], []


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_nodes(
    raw_nodes: list[dict[str, Any]],
    entity_types: list[str],
) -> list[dict[str, Any]]:
    """Validate and normalise extracted nodes."""
    valid_types = set(entity_types)
    validated: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for node in raw_nodes:
        node_id = node.get("id", "")
        if not node_id or not node.get("title"):
            continue
        if node.get("entity_type") not in valid_types:
            continue
        if node_id in seen_ids:
            node_id = f"{node_id}_{uuid.uuid4().hex[:6]}"

        seen_ids.add(node_id)
        validated.append({
            "id": node_id,
            "entity_type": node["entity_type"],
            "title": node["title"],
            "description": node.get("description", ""),
            "properties": node.get("properties", {}),
        })

    return validated


def _validate_edges(
    raw_edges: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
    relation_types: list[str],
) -> list[dict[str, Any]]:
    """Validate edges: ensure source/target exist and relation type is valid."""
    node_ids = {n["id"] for n in nodes}
    valid_rels = set(relation_types)
    validated: list[dict[str, Any]] = []

    for edge in raw_edges:
        src = edge.get("source_id", "")
        tgt = edge.get("target_id", "")
        rel = edge.get("relation_type", "")

        if src not in node_ids or tgt not in node_ids:
            continue
        if rel not in valid_rels:
            continue

        weight = edge.get("weight", 1.0)
        if not isinstance(weight, (int, float)):
            weight = 1.0
        weight = max(0.1, min(1.0, float(weight)))

        validated.append({
            "source_id": src,
            "target_id": tgt,
            "relation_type": rel,
            "description": edge.get("description", ""),
            "weight": weight,
        })

    return validated
