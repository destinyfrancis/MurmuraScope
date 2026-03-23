"""GraphRAG Seed Injection service.

Converts ProcessedSeed output (from TextProcessor) into KG-compatible
nodes and edges, then stores them on top of the base property graph.

Entity type mapping:
  person       → Person
  org          → Organization
  location     → District
  policy       → Policy
  economic     → EconomicIndicator
  event        → Event
  stakeholder  → StakeholderGroup (generated from ProcessedSeed.stakeholders)
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

if TYPE_CHECKING:
    from backend.app.services.text_processor import ProcessedSeed

logger = get_logger("seed_graph_injector")

# ---------------------------------------------------------------------------
# Entity type mapping
# ---------------------------------------------------------------------------

_ENTITY_TYPE_MAP: dict[str, str] = {
    "person": "Person",
    "org": "Organization",
    "location": "District",
    "policy": "Policy",
    "economic": "EconomicIndicator",
    "event": "Event",
}

# ---------------------------------------------------------------------------
# Frozen dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeedGraphNode:
    """Immutable KG node derived from seed text."""

    id: str
    entity_type: str
    title: str
    description: str
    properties: dict[str, Any]


@dataclass(frozen=True)
class SeedGraphEdge:
    """Immutable KG edge derived from seed text."""

    source_id: str
    target_id: str
    relation_type: str
    description: str
    weight: float


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class SeedGraphInjector:
    """Converts ProcessedSeed into KG nodes/edges and appends to existing graph."""

    async def inject(
        self,
        graph_id: str,
        processed_seed: ProcessedSeed,
    ) -> dict[str, Any]:
        """Convert ProcessedSeed into KG nodes/edges and store via aiosqlite.

        Merges seed-derived content ON TOP of an existing graph (does not
        delete existing nodes/edges).  Uses INSERT OR IGNORE to skip
        duplicates on node id.

        Args:
            graph_id: The graph identifier (also used as session_id in kg_*).
            processed_seed: Output of TextProcessor.process().

        Returns:
            Dict with ``seed_nodes`` and ``seed_edges`` counts.
        """
        prefix = graph_id.replace("-", "")[:8]

        # ------------------------------------------------------------------
        # Step 1: load existing node titles to deduplicate
        # ------------------------------------------------------------------
        existing_titles = await self._load_existing_titles(graph_id)

        # ------------------------------------------------------------------
        # Step 2: convert entities → nodes
        # ------------------------------------------------------------------
        entity_nodes: list[SeedGraphNode] = []
        entity_id_map: dict[str, str] = {}  # entity_name_normalized → node_id

        for entity in processed_seed.entities:
            norm = _normalize_name(entity.name)
            if norm in existing_titles:
                # Map to existing node id by normalized lookup
                existing_id = existing_titles[norm]
                entity_id_map[norm] = existing_id
                continue

            node_id = f"{prefix}_seed_{_slug(entity.name)}"
            # Avoid duplicate ids when two entities share the same slug
            if node_id in {n.id for n in entity_nodes}:
                node_id = f"{node_id}_{len(entity_nodes)}"

            mapped_type = _ENTITY_TYPE_MAP.get(entity.type, entity.type.capitalize())
            node = SeedGraphNode(
                id=node_id,
                entity_type=mapped_type,
                title=entity.name,
                description=f"從種子文本提取的{mapped_type}實體",
                properties={"relevance": entity.relevance, "source": "seed"},
            )
            entity_nodes.append(node)
            entity_id_map[norm] = node_id

        # ------------------------------------------------------------------
        # Step 3: convert stakeholders → nodes + edges to related entities
        # ------------------------------------------------------------------
        stakeholder_nodes: list[SeedGraphNode] = []
        stakeholder_edges: list[SeedGraphEdge] = []

        for stk in processed_seed.stakeholders:
            norm = _normalize_name(stk.group)
            if norm in existing_titles:
                stk_id = existing_titles[norm]
            else:
                stk_id = f"{prefix}_stk_{_slug(stk.group)}"
                if stk_id not in {n.id for n in stakeholder_nodes}:
                    stakeholder_nodes.append(
                        SeedGraphNode(
                            id=stk_id,
                            entity_type="StakeholderGroup",
                            title=stk.group,
                            description=stk.description or f"影響群體：{stk.group}",
                            properties={"impact": stk.impact, "source": "seed"},
                        )
                    )

            # Connect stakeholder to related entities
            for entity in processed_seed.entities:
                e_norm = _normalize_name(entity.name)
                e_id = entity_id_map.get(e_norm)
                if e_id:
                    stakeholder_edges.append(
                        SeedGraphEdge(
                            source_id=stk_id,
                            target_id=e_id,
                            relation_type="AFFECTED_BY",
                            description=f"{stk.group}受{entity.name}影響",
                            weight=entity.relevance,
                        )
                    )

        # ------------------------------------------------------------------
        # Step 4: timeline events → PRECEDES edges
        # ------------------------------------------------------------------
        timeline_nodes: list[SeedGraphNode] = []
        timeline_edges: list[SeedGraphEdge] = []

        if len(processed_seed.timeline) >= 2:
            event_ids: list[str] = []
            for i, event in enumerate(processed_seed.timeline):
                ev_id = f"{prefix}_evt_{i}_{_slug(event.event[:20])}"
                norm = _normalize_name(event.event)
                if norm in existing_titles:
                    event_ids.append(existing_titles[norm])
                    continue
                timeline_nodes.append(
                    SeedGraphNode(
                        id=ev_id,
                        entity_type="Event",
                        title=event.event[:60],
                        description=f"時間：{event.date_hint}" if event.date_hint else event.event,
                        properties={"date_hint": event.date_hint, "source": "seed"},
                    )
                )
                event_ids.append(ev_id)

            for i in range(len(event_ids) - 1):
                timeline_edges.append(
                    SeedGraphEdge(
                        source_id=event_ids[i],
                        target_id=event_ids[i + 1],
                        relation_type="PRECEDES",
                        description="時間順序",
                        weight=1.0,
                    )
                )

        # ------------------------------------------------------------------
        # Step 5: key_claims → RELATED_TO edges between co-mentioned entities
        # ------------------------------------------------------------------
        claim_edges: list[SeedGraphEdge] = []
        all_entity_ids = list(entity_id_map.values())

        for claim in processed_seed.key_claims:
            # Find entities mentioned in this claim
            mentioned: list[str] = []
            for entity in processed_seed.entities:
                if entity.name in claim or _normalize_name(entity.name) in _normalize_name(claim):
                    e_id = entity_id_map.get(_normalize_name(entity.name))
                    if e_id and e_id not in mentioned:
                        mentioned.append(e_id)

            # Connect pairs of co-mentioned entities
            for i in range(len(mentioned)):
                for j in range(i + 1, len(mentioned)):
                    claim_edges.append(
                        SeedGraphEdge(
                            source_id=mentioned[i],
                            target_id=mentioned[j],
                            relation_type="RELATED_TO",
                            description=claim[:120],
                            weight=0.8,
                        )
                    )

        # ------------------------------------------------------------------
        # Step 6: persist all
        # ------------------------------------------------------------------
        all_nodes = entity_nodes + stakeholder_nodes + timeline_nodes
        all_edges = stakeholder_edges + timeline_edges + claim_edges

        node_count, edge_count = await self._persist(graph_id, all_nodes, all_edges)

        logger.info(
            "SeedGraphInjector: graph=%s injected %d nodes, %d edges",
            graph_id,
            node_count,
            edge_count,
        )
        return {"seed_nodes": node_count, "seed_edges": edge_count}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _load_existing_titles(
        self,
        graph_id: str,
    ) -> dict[str, str]:
        """Return {normalized_title: node_id} for existing nodes in this graph."""
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    "SELECT id, title FROM kg_nodes WHERE session_id = ?",
                    (graph_id,),
                )
                rows = await cursor.fetchall()
            return {_normalize_name(r[1]): r[0] for r in rows}
        except Exception:
            logger.exception("_load_existing_titles failed graph=%s", graph_id)
            return {}

    async def _persist(
        self,
        graph_id: str,
        nodes: list[SeedGraphNode],
        edges: list[SeedGraphEdge],
    ) -> tuple[int, int]:
        """Insert nodes and edges; use INSERT OR IGNORE to skip duplicates."""
        if not nodes and not edges:
            return 0, 0

        node_rows = [
            (
                n.id,
                graph_id,
                n.entity_type,
                n.title,
                n.description,
                json.dumps(n.properties, ensure_ascii=False),
            )
            for n in nodes
        ]
        edge_rows = [
            (
                graph_id,
                e.source_id,
                e.target_id,
                e.relation_type,
                e.description,
                e.weight,
            )
            for e in edges
        ]

        try:
            async with get_db() as db:
                if node_rows:
                    await db.executemany(
                        "INSERT OR IGNORE INTO kg_nodes"
                        " (id, session_id, entity_type, title, description, properties)"
                        " VALUES (?, ?, ?, ?, ?, ?)",
                        node_rows,
                    )
                if edge_rows:
                    await db.executemany(
                        "INSERT INTO kg_edges"
                        " (session_id, source_id, target_id, relation_type, description, weight)"
                        " VALUES (?, ?, ?, ?, ?, ?)",
                        edge_rows,
                    )
                await db.commit()
        except Exception:
            logger.exception("SeedGraphInjector._persist failed graph=%s", graph_id)
            return 0, 0

        return len(node_rows), len(edge_rows)


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def _normalize_name(name: str) -> str:
    """Strip whitespace, normalise Unicode, lowercase English chars.

    Chinese characters are preserved as-is (no lowercasing needed).
    """
    stripped = name.strip()
    # NFKC normalisation handles full-width chars, ligatures, etc.
    normalised = unicodedata.normalize("NFKC", stripped)
    # Lowercase ASCII portion only
    return "".join(c.lower() if c.isascii() else c for c in normalised)


def _slug(text: str) -> str:
    """Convert text to a safe node ID slug.

    Replaces spaces and non-alphanumeric chars with underscores, trims length.
    """
    # Keep Chinese chars, ASCII alphanumeric
    slug = re.sub(r"[^\w\u4e00-\u9fff]", "_", text, flags=re.UNICODE)
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug[:30].lower()
