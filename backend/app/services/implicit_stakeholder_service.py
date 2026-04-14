# backend/app/services/implicit_stakeholder_service.py
"""Implicit stakeholder discovery service.

Option A of the implicit stakeholder feature: discovers actors critically
affected by a scenario but not explicitly mentioned in the seed text.
Runs at Step 1 (graph build time) so KGAgentFactory picks them up naturally.

Pipeline:
  1. Load existing KG node titles for deduplication.
  2. Call LLM: "given seed text + existing nodes, who is missing?"
  3. Deduplicate against existing node titles (case-insensitive).
  4. Inject new nodes into kg_nodes with source="implicit_discovery".
  5. Return DiscoveryResult.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from backend.app.utils.db import get_db
from backend.app.utils.llm_client import LLMClient, get_step_provider_model
from backend.app.utils.logger import get_logger
from backend.app.utils.prompt_security import sanitize_seed_text
from backend.prompts.implicit_stakeholder_prompts import (
    IMPLICIT_STAKEHOLDER_SYSTEM,
    IMPLICIT_STAKEHOLDER_USER,
)

logger = get_logger("implicit_stakeholder_service")

_SLUG_RE = re.compile(r"^[a-z0-9_]+$")
_MAX_IMPLICIT = 50


# ---------------------------------------------------------------------------
# Frozen result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ImplicitStakeholder:
    """An actor discovered by LLM as critically relevant but not in seed text."""

    id: str
    name: str
    entity_type: str
    role: str
    relevance_reason: str


@dataclass(frozen=True)
class DiscoveryResult:
    """Result of an implicit stakeholder discovery run."""

    stakeholders: tuple[ImplicitStakeholder, ...]
    nodes_added: int


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ImplicitStakeholderService:
    """Discovers and injects implied actors missing from the knowledge graph.

    Args:
        llm_client: Optional pre-configured LLMClient. Default created if None.
    """

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm = llm_client or LLMClient()

    async def discover(
        self,
        graph_id: str,
        seed_text: str,
        existing_nodes: list[dict[str, Any]],
    ) -> DiscoveryResult:
        """Discover implicit stakeholders via LLM analysis of seed text.

        Args:
            graph_id: The graph/session identifier for DB operations.
            seed_text: Original seed text used to build the KG.
            existing_nodes: Current KG nodes (for deduplication context).

        Returns:
            DiscoveryResult with discovered stakeholders and nodes_added count.
        """
        if not seed_text or not seed_text.strip():
            return DiscoveryResult(stakeholders=(), nodes_added=0)

        try:
            raw_actors = await self._call_llm(seed_text, existing_nodes)
        except Exception:
            logger.exception("ImplicitStakeholderService: LLM call failed for graph %s", graph_id)
            return DiscoveryResult(stakeholders=(), nodes_added=0)

        return await self._process_and_persist(graph_id, raw_actors, existing_nodes)

    async def discover_from_topology(
        self,
        graph_id: str,
    ) -> DiscoveryResult:
        """Discover implicit stakeholders based on graph topological anomalies (structural holes).

        Args:
            graph_id: The session identifier.

        Returns:
            DiscoveryResult.
        """
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT source_id as source, target_id as target, weight FROM kg_edges WHERE session_id = ?",
                (graph_id,),
            )
            edges = [dict(r) for r in await cursor.fetchall()]
            
            cursor = await db.execute(
                "SELECT id, title, description FROM kg_nodes WHERE session_id = ?",
                (graph_id,),
            )
            nodes = [dict(r) for r in await cursor.fetchall()]

        if not edges:
            return DiscoveryResult(stakeholders=(), nodes_added=0)

        from backend.app.utils.graph_metrics import calculate_topological_metrics # noqa: PLC0415
        
        metrics = calculate_topological_metrics(edges)
        if "error" in metrics:
            return DiscoveryResult(stakeholders=(), nodes_added=0)

        # Identify 'Structural Holes' - nodes acting as critical bridges
        betweenness = metrics.get("betweenness", {})
        top_bridges = sorted(betweenness.items(), key=lambda x: x[1], reverse=True)[:5]
        bridge_ids = [node_id for node_id, score in top_bridges if score > 0.1]

        if not bridge_ids:
            return DiscoveryResult(stakeholders=(), nodes_added=0)

        # Call LLM to see if these bridges imply a 'hidden' actor
        # e.g. if A and B are connected only via a bridge, maybe there's a third party mediating.
        bridge_nodes = [n for n in nodes if n["id"] in bridge_ids]
        
        try:
            user_content = (
                f"Graph Topology Analysis for session: {graph_id}\n\n"
                f"The following nodes have high Betweenness Centrality (critical bridges):\n"
                f"{json.dumps(bridge_nodes, ensure_ascii=False, indent=2)}\n\n"
                "Based on the fact that these actors are bridging disparate communities, "
                "identify any 'Latent Actors' (e.g. regulators, competitors, or covert influencers) "
                "that are likely operating in the background but are not yet in the graph."
            )
            
            messages = [
                {"role": "system", "content": IMPLICIT_STAKEHOLDER_SYSTEM + " (Focus on Topological Structural Holes)"},
                {"role": "user", "content": user_content},
            ]
            
            _s1_provider, _s1_model = get_step_provider_model(1)
            raw = await self._llm.chat_json(messages, max_tokens=2048, temperature=0.3,
                                            provider=_s1_provider, model=_s1_model)
            raw_actors = raw.get("implied_actors", [])
            
            return await self._process_and_persist(graph_id, raw_actors, nodes)
        except Exception:
            logger.exception("Topo-Auditor discovery failed for graph %s", graph_id)
            return DiscoveryResult(stakeholders=(), nodes_added=0)

    async def _process_and_persist(
        self,
        graph_id: str,
        raw_actors: list[dict[str, Any]],
        existing_nodes: list[dict[str, Any]],
    ) -> DiscoveryResult:
        """Helper to deduplicate and save discovered stakeholders."""
        # Load all current node titles for dedup
        current_titles = await self._load_kg_nodes(graph_id)
        existing_titles_norm = {
            _normalize(n.get("label") or n.get("title") or "") for n in current_titles + existing_nodes
        }

        # Filter and build new nodes
        new_stakeholders: list[ImplicitStakeholder] = []
        for actor in raw_actors[:_MAX_IMPLICIT]:
            name = (actor.get("name") or "").strip()
            if not name:
                continue
            if _normalize(name) in existing_titles_norm:
                logger.debug("ImplicitStakeholderService: skipping '%s' (already in KG)", name)
                continue

            actor_id = _to_slug(actor.get("id") or name)
            new_stakeholders.append(
                ImplicitStakeholder(
                    id=actor_id,
                    name=name,
                    entity_type=actor.get("entity_type", "Organization"),
                    role=(actor.get("role") or "").strip(),
                    relevance_reason=(actor.get("relevance_reason") or "").strip(),
                )
            )
            existing_titles_norm.add(_normalize(name))  # prevent self-dups

        if not new_stakeholders:
            return DiscoveryResult(stakeholders=tuple(new_stakeholders), nodes_added=0)

        nodes_added = await self._persist_nodes(graph_id, new_stakeholders)
        logger.info(
            "ImplicitStakeholderService: graph=%s discovered %d actors, injected %d nodes",
            graph_id,
            len(new_stakeholders),
            nodes_added,
        )
        return DiscoveryResult(
            stakeholders=tuple(new_stakeholders),
            nodes_added=nodes_added,
        )


    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _call_llm(
        self,
        seed_text: str,
        existing_nodes: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Call LLM and return raw list of implied actor dicts."""
        safe_seed = sanitize_seed_text(seed_text)
        node_summaries = [
            {
                "id": n.get("id"),
                "label": n.get("label") or n.get("title"),
                "type": n.get("entity_type") or n.get("type"),
            }
            for n in existing_nodes
        ]
        user_content = IMPLICIT_STAKEHOLDER_USER.format(
            seed_text=safe_seed,
            node_count=len(node_summaries),
            existing_nodes_json=json.dumps(node_summaries, ensure_ascii=False, indent=2),
        )
        messages = [
            {"role": "system", "content": IMPLICIT_STAKEHOLDER_SYSTEM},
            {"role": "user", "content": user_content},
        ]
        _s1_provider, _s1_model = get_step_provider_model(1)
        raw = await self._llm.chat_json(messages, max_tokens=4096, temperature=0.3,
                                        provider=_s1_provider, model=_s1_model)
        return raw.get("implied_actors", [])

    async def _load_kg_nodes(self, graph_id: str) -> list[dict[str, Any]]:
        """Return lightweight node dicts from DB for deduplication."""
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    "SELECT id, entity_type, title FROM kg_nodes WHERE session_id = ?",
                    (graph_id,),
                )
                rows = await cursor.fetchall()
            return [{"id": r[0], "entity_type": r[1], "title": r[2]} for r in rows]
        except Exception:
            logger.exception("_load_kg_nodes failed for graph %s", graph_id)
            return []

    async def _persist_nodes(
        self,
        graph_id: str,
        stakeholders: list[ImplicitStakeholder],
    ) -> int:
        """Insert implicit actor nodes into kg_nodes. Returns count inserted."""
        prefix = graph_id.replace("-", "")[:8]
        node_rows = [
            (
                f"{prefix}_imp_{s.id}",
                graph_id,
                s.entity_type,
                s.name,
                s.role,
                json.dumps(
                    {"relevance_reason": s.relevance_reason, "source": "implicit_discovery"},
                    ensure_ascii=False,
                ),
            )
            for s in stakeholders
        ]
        try:
            async with get_db() as db:
                await db.executemany(
                    """INSERT OR IGNORE INTO kg_nodes
                       (id, session_id, entity_type, title, description, properties)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    node_rows,
                )
                await db.commit()
            return len(node_rows)
        except Exception:
            logger.exception("_persist_nodes failed for graph %s", graph_id)
            return 0


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    """Lowercase + strip accents for fuzzy deduplication."""
    nfkd = unicodedata.normalize("NFKD", text.lower().strip())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _to_slug(raw: str) -> str:
    """Convert arbitrary string to URL-safe slug."""
    nfkd = unicodedata.normalize("NFKD", raw.lower())
    ascii_str = "".join(c for c in nfkd if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_str).strip("_")
    if not _SLUG_RE.match(slug or "x"):
        slug = "actor_" + re.sub(r"\W+", "_", raw.lower()).strip("_")
    return slug or "unknown_actor"
