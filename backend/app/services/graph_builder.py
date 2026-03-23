"""Local SQLite-based GraphRAG service (replaces Zep Cloud).

Builds, stores, queries, and updates knowledge graphs using the
kg_nodes, kg_edges, and kg_communities tables.
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from typing import Any

from backend.app.services.entity_extractor import EntityExtractor
from backend.app.services.ontology_generator import OntologyGenerator
from backend.app.utils.db import get_db
from backend.app.utils.llm_client import LLMClient, get_agent_provider_model
from backend.app.utils.logger import get_logger
from backend.app.utils.prompt_security import sanitize_seed_text
from backend.prompts.ontology_prompts import (
    COMMUNITY_SUMMARY_SYSTEM,
    COMMUNITY_SUMMARY_USER,
)

logger = get_logger("graph_builder")


class GraphBuilderService:
    """Build and manage local knowledge graphs backed by SQLite.

    Orchestrates ontology generation, entity extraction, graph storage,
    community detection, and natural-language graph querying.
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        provider: str | None = None,
    ) -> None:
        self._llm = llm_client or LLMClient()
        self._provider = provider or get_agent_provider_model()[0]
        self._ontology_gen = OntologyGenerator(self._llm, self._provider)
        self._entity_ext = EntityExtractor(self._llm, self._provider)

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    async def build_graph(
        self,
        session_id: str,
        scenario_type: str,
        seed_text: str,
        hk_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Build a knowledge graph from scenario + seed text + HK data.

        Steps:
            1. Generate ontology (entity types + relation types).
            2. Extract entities from seed text + HK data.
            3. Store nodes and edges in the database.
            4. Detect and store communities.

        Returns:
            Summary dict with graph_id, node_count, edge_count,
            entity_types, and relation_types.
        """
        seed_text = sanitize_seed_text(seed_text)
        graph_id = f"graph_{session_id}_{uuid.uuid4().hex[:8]}"
        logger.info("Building graph %s for session %s", graph_id, session_id)

        # Step 1 — Ontology
        entity_types, relation_types = await self._ontology_gen.generate(scenario_type, seed_text)

        # Step 2 — Entity extraction
        nodes, edges = await self._entity_ext.extract(seed_text, hk_data, entity_types, relation_types)

        if not nodes:
            logger.warning("No entities extracted for session %s", session_id)
            return {
                "graph_id": graph_id,
                "node_count": 0,
                "edge_count": 0,
                "entity_types": entity_types,
                "relation_types": relation_types,
            }

        # Step 3 — Store nodes and edges
        await self._store_nodes(session_id, nodes)
        await self._store_edges(session_id, edges)

        # Step 4 — Community detection
        communities = await self._detect_communities(session_id, nodes, edges)
        await self._store_communities(session_id, communities)

        logger.info(
            "Graph %s built: %d nodes, %d edges, %d communities",
            graph_id,
            len(nodes),
            len(edges),
            len(communities),
        )

        return {
            "graph_id": graph_id,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "entity_types": entity_types,
            "relation_types": relation_types,
        }

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_graph(self, graph_id: str) -> dict[str, Any]:
        """Get full graph data (nodes + edges) for visualisation.

        Args:
            graph_id: The graph identifier (contains session_id prefix).

        Returns:
            Dict with ``nodes``, ``edges``, and ``communities`` lists.
        """
        # Extract session_id from graph_id (format: graph_{session_id}_{hex})
        session_id = _session_id_from_graph_id(graph_id)

        async with get_db() as db:
            node_rows = await db.execute_fetchall(
                "SELECT id, entity_type, title, description, properties FROM kg_nodes WHERE session_id = ?",
                (session_id,),
            )
            edge_rows = await db.execute_fetchall(
                "SELECT source_id, target_id, relation_type, description, weight FROM kg_edges WHERE session_id = ?",
                (session_id,),
            )
            community_rows = await db.execute_fetchall(
                "SELECT id, title, summary, member_ids FROM kg_communities WHERE session_id = ?",
                (session_id,),
            )

        nodes = [
            {
                "id": r[0],
                "entity_type": r[1],
                "title": r[2],
                "description": r[3],
                "properties": json.loads(r[4]) if r[4] else {},
            }
            for r in node_rows
        ]
        edges = [
            {
                "source_id": r[0],
                "target_id": r[1],
                "relation_type": r[2],
                "description": r[3],
                "weight": r[4],
            }
            for r in edge_rows
        ]
        communities = [
            {
                "id": r[0],
                "title": r[1],
                "summary": r[2],
                "member_ids": json.loads(r[3]) if r[3] else [],
            }
            for r in community_rows
        ]

        return {"nodes": nodes, "edges": edges, "communities": communities}

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    async def query_graph(
        self,
        graph_id: str,
        query: str,
    ) -> list[dict[str, Any]]:
        """Query graph using natural language (for ReACT tools).

        Performs keyword-based search over node titles and descriptions,
        then returns matching nodes with their immediate edges.
        """
        session_id = _session_id_from_graph_id(graph_id)
        keywords = query.lower().split()

        async with get_db() as db:
            # Fetch candidate nodes via LIKE on title/description
            conditions = " OR ".join(["LOWER(title) LIKE ? OR LOWER(description) LIKE ?"] * len(keywords))
            params: list[str] = []
            for kw in keywords:
                pattern = f"%{kw}%"
                params.extend([pattern, pattern])

            sql = (
                f"SELECT id, entity_type, title, description, properties "
                f"FROM kg_nodes WHERE session_id = ? AND ({conditions})"
            )
            node_rows = await db.execute_fetchall(sql, [session_id, *params])

            if not node_rows:
                return []

            node_ids = [r[0] for r in node_rows]
            placeholders = ", ".join("?" * len(node_ids))

            edge_rows = await db.execute_fetchall(
                f"SELECT source_id, target_id, relation_type, description, weight "
                f"FROM kg_edges WHERE session_id = ? AND "
                f"(source_id IN ({placeholders}) OR target_id IN ({placeholders}))",
                [session_id, *node_ids, *node_ids],
            )

        results: list[dict[str, Any]] = []
        for r in node_rows:
            node_id = r[0]
            connected_edges = [
                {
                    "source_id": e[0],
                    "target_id": e[1],
                    "relation_type": e[2],
                    "description": e[3],
                    "weight": e[4],
                }
                for e in edge_rows
                if e[0] == node_id or e[1] == node_id
            ]
            results.append(
                {
                    "node": {
                        "id": node_id,
                        "entity_type": r[1],
                        "title": r[2],
                        "description": r[3],
                        "properties": json.loads(r[4]) if r[4] else {},
                    },
                    "edges": connected_edges,
                }
            )

        return results

    # ------------------------------------------------------------------
    # Update from simulation round
    # ------------------------------------------------------------------

    async def update_graph_from_round(
        self,
        graph_id: str,
        round_data: dict[str, Any],
    ) -> None:
        """Update graph with new relationships from a simulation round.

        Args:
            graph_id: The graph to update.
            round_data: Dict with ``round_number``, ``events`` (text summary),
                        and optionally ``relation_types``.
        """
        session_id = _session_id_from_graph_id(graph_id)

        # Fetch current nodes
        async with get_db() as db:
            rows = await db.execute_fetchall(
                "SELECT id, entity_type, title, description, properties FROM kg_nodes WHERE session_id = ?",
                (session_id,),
            )
        existing_nodes = [
            {
                "id": r[0],
                "entity_type": r[1],
                "title": r[2],
                "description": r[3],
                "properties": json.loads(r[4]) if r[4] else {},
            }
            for r in rows
        ]

        if not existing_nodes:
            logger.warning("No nodes found for session %s, skipping update", session_id)
            return

        relation_types = round_data.get(
            "relation_types",
            [
                "SUPPORTS",
                "OPPOSES",
                "COMMENTS_ON",
                "AFFILIATED_WITH",
                "REGULATES",
                "COMPETES_WITH",
            ],
        )
        round_context = round_data.get("events", "")

        new_edges, updated_edges = await self._entity_ext.extract_from_round(
            existing_nodes, relation_types, round_context
        )

        if new_edges:
            await self._store_edges(session_id, new_edges)

        if updated_edges:
            await self._update_edge_weights(session_id, updated_edges)

        logger.info(
            "Round update for %s: +%d edges, ~%d weight updates",
            graph_id,
            len(new_edges),
            len(updated_edges),
        )

    # ------------------------------------------------------------------
    # Private: storage
    # ------------------------------------------------------------------

    async def _store_nodes(
        self,
        session_id: str,
        nodes: list[dict[str, Any]],
    ) -> None:
        async with get_db() as db:
            await db.executemany(
                "INSERT OR REPLACE INTO kg_nodes "
                "(id, session_id, entity_type, title, description, properties) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        n["id"],
                        session_id,
                        n["entity_type"],
                        n["title"],
                        n.get("description", ""),
                        json.dumps(n.get("properties", {}), ensure_ascii=False),
                    )
                    for n in nodes
                ],
            )
            await db.commit()

    async def _store_edges(
        self,
        session_id: str,
        edges: list[dict[str, Any]],
    ) -> None:
        async with get_db() as db:
            await db.executemany(
                "INSERT INTO kg_edges "
                "(session_id, source_id, target_id, relation_type, description, weight) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        session_id,
                        e["source_id"],
                        e["target_id"],
                        e["relation_type"],
                        e.get("description", ""),
                        e.get("weight", 1.0),
                    )
                    for e in edges
                ],
            )
            await db.commit()

    async def _update_edge_weights(
        self,
        session_id: str,
        updated_edges: list[dict[str, Any]],
    ) -> None:
        async with get_db() as db:
            for edge in updated_edges:
                await db.execute(
                    "UPDATE kg_edges SET weight = ? "
                    "WHERE session_id = ? AND source_id = ? "
                    "AND target_id = ? AND relation_type = ?",
                    (
                        edge.get("new_weight", 1.0),
                        session_id,
                        edge["source_id"],
                        edge["target_id"],
                        edge["relation_type"],
                    ),
                )
            await db.commit()

    async def _store_communities(
        self,
        session_id: str,
        communities: list[dict[str, Any]],
    ) -> None:
        if not communities:
            return
        async with get_db() as db:
            await db.executemany(
                "INSERT OR REPLACE INTO kg_communities "
                "(id, session_id, title, summary, member_ids) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        c["id"],
                        session_id,
                        c["title"],
                        c.get("summary", ""),
                        json.dumps(c["member_ids"], ensure_ascii=False),
                    )
                    for c in communities
                ],
            )
            await db.commit()

    # ------------------------------------------------------------------
    # Private: community detection (simple connected-component approach)
    # ------------------------------------------------------------------

    async def _detect_communities(
        self,
        session_id: str,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Detect communities via connected components, then summarise with LLM."""
        if not nodes:
            return []

        # Build adjacency list
        adjacency: dict[str, set[str]] = defaultdict(set)
        for edge in edges:
            adjacency[edge["source_id"]].add(edge["target_id"])
            adjacency[edge["target_id"]].add(edge["source_id"])

        # Find connected components using BFS
        visited: set[str] = set()
        components: list[list[str]] = []
        node_ids = [n["id"] for n in nodes]

        for node_id in node_ids:
            if node_id in visited:
                continue
            component: list[str] = []
            queue = [node_id]
            while queue:
                current = queue.pop(0)
                if current in visited:
                    continue
                visited.add(current)
                component.append(current)
                for neighbour in adjacency.get(current, set()):
                    if neighbour not in visited:
                        queue.append(neighbour)
            if len(component) >= 2:
                components.append(component)

        if not components:
            return []

        # Summarise each community with LLM
        node_lookup = {n["id"]: n for n in nodes}
        communities: list[dict[str, Any]] = []

        for component in components:
            community_id = f"comm_{uuid.uuid4().hex[:8]}"
            members = [node_lookup[nid] for nid in component if nid in node_lookup]
            community_edges = [
                e for e in edges if e["source_id"] in set(component) and e["target_id"] in set(component)
            ]

            summary = await self._summarise_community(members, community_edges)

            communities.append(
                {
                    "id": community_id,
                    "title": summary.get("title", f"Community {community_id}"),
                    "summary": summary.get("summary", ""),
                    "member_ids": component,
                }
            )

        return communities

    async def _summarise_community(
        self,
        members: list[dict[str, Any]],
        edges: list[dict[str, Any]],
    ) -> dict[str, str]:
        """Use LLM to generate a title and summary for a community."""
        members_brief = [{"id": m["id"], "title": m["title"], "entity_type": m["entity_type"]} for m in members]
        edges_brief = [
            {
                "source": e["source_id"],
                "target": e["target_id"],
                "relation": e["relation_type"],
            }
            for e in edges
        ]

        messages = [
            {"role": "system", "content": COMMUNITY_SUMMARY_SYSTEM},
            {
                "role": "user",
                "content": COMMUNITY_SUMMARY_USER.format(
                    members_json=json.dumps(members_brief, ensure_ascii=False, indent=2),
                    edges_json=json.dumps(edges_brief, ensure_ascii=False, indent=2),
                ),
            },
        ]

        try:
            return await self._llm.chat_json(
                messages,
                provider=self._provider,
                temperature=0.4,
                max_tokens=512,
            )
        except Exception:
            logger.exception("Community summarisation failed")
            return {"title": "Unnamed Community", "summary": ""}

    async def update_weights_from_actions(
        self,
        session_id: str,
        actions: list[dict],
    ) -> int:
        """Update KG edge weights based on simulation actions.

        LIKE/REPOST actions increase weight += 0.1.
        Edges with no interaction decay by *= 0.98.

        Args:
            session_id: Session UUID (used as graph_id).
            actions: List of action dicts from simulation_actions table.

        Returns:
            Number of edges updated.
        """
        if not actions:
            return 0

        # Normalise action type variants to canonical names before matching.
        # OASIS emits both bare forms ("like") and compound forms ("like_post").
        _CANONICAL_ACTION: dict[str, str] = {
            "like": "like",
            "like_post": "like",
            "repost": "repost",
            "repost_post": "repost",
            "retweet": "repost",
            "retweet_post": "repost",
            "share": "repost",
            "share_post": "repost",
        }

        # Build interaction counts from actions
        interaction_counts: dict[str, int] = {}
        for action in actions:
            raw_type = action.get("action_type", "post")
            canonical = _CANONICAL_ACTION.get(raw_type, raw_type)
            if canonical in ("like", "repost"):
                username = action.get("oasis_username", "")
                if username:
                    interaction_counts[username] = interaction_counts.get(username, 0) + 1

        try:
            async with get_db() as db:
                # Decay all edges for this session
                await db.execute(
                    "UPDATE kg_edges SET weight = weight * 0.98 WHERE session_id = ?",
                    (session_id,),
                )
                # Boost interacted edges (only edges involving the interacting node)
                if interaction_counts:
                    for username, count in interaction_counts.items():
                        boost = 0.1 * count
                        # Look up the node for this username
                        cursor = await db.execute(
                            "SELECT id FROM kg_nodes WHERE session_id = ? AND (title = ? OR id LIKE ?)",
                            (session_id, username, f"%_{username}"),
                        )
                        node_row = await cursor.fetchone()
                        if not node_row:
                            continue
                        node_id = node_row[0]
                        await db.execute(
                            "UPDATE kg_edges SET weight = weight + ? WHERE session_id = ? AND (source_id = ? OR target_id = ?)",
                            (boost, session_id, node_id, node_id),
                        )
                await db.commit()

                # Count updated rows
                cursor = await db.execute(
                    "SELECT COUNT(*) FROM kg_edges WHERE session_id = ?",
                    (session_id,),
                )
                row = await cursor.fetchone()
                return row[0] if row else 0
        except Exception:
            logger.exception("update_weights_from_actions failed session=%s", session_id)
            return 0

    async def take_snapshot(
        self,
        session_id: str,
        round_number: int,
    ) -> bool:
        """Save a snapshot of the current KG state.

        Called every 5 rounds from simulation_runner and on completion.

        Args:
            session_id: Session UUID (used as graph_id).
            round_number: Current simulation round.

        Returns:
            True if snapshot was saved successfully.
        """
        try:
            async with get_db() as db:
                # Fetch current nodes and edges
                node_rows = await (
                    await db.execute(
                        "SELECT id, entity_type, title, description, properties FROM kg_nodes WHERE session_id = ?",
                        (session_id,),
                    )
                ).fetchall()
                edge_rows = await (
                    await db.execute(
                        "SELECT source_id, target_id, relation_type, weight FROM kg_edges WHERE session_id = ?",
                        (session_id,),
                    )
                ).fetchall()

                node_count = len(node_rows)
                edge_count = len(edge_rows)

                snapshot = {
                    "nodes": [
                        {
                            "id": r[0],
                            "type": r[1],
                            "label": r[2],
                            "description": r[3] or "",
                        }
                        for r in node_rows
                    ],
                    "edges": [
                        {
                            "source": r[0],
                            "target": r[1],
                            "label": r[2],
                            "weight": r[3] or 1.0,
                        }
                        for r in edge_rows
                    ],
                }

                # DEPRECATED: periodic full-graph snapshots are superseded by temporal kg_edges
                # validity windows (valid_from / valid_until). This code is kept for backward
                # compatibility with the GraphExplorer snapshot slider but will be removed in v0.3.
                await db.execute(
                    """
                    INSERT INTO kg_snapshots
                        (session_id, round_number, snapshot_json, node_count, edge_count)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        round_number,
                        json.dumps(snapshot, ensure_ascii=False),
                        node_count,
                        edge_count,
                    ),
                )
                await db.commit()

            logger.info(
                "KG snapshot saved: session=%s round=%d nodes=%d edges=%d",
                session_id,
                round_number,
                node_count,
                edge_count,
            )
            return True
        except Exception:
            logger.exception("take_snapshot failed session=%s round=%d", session_id, round_number)
            return False

    async def get_snapshot(
        self,
        session_id: str,
        round_number: int,
    ) -> dict:
        """Retrieve a saved KG snapshot.

        Args:
            session_id: Session UUID.
            round_number: Round to retrieve snapshot for.

        Returns:
            Snapshot dict with 'nodes' and 'edges', or empty dict if not found.
        """
        try:
            async with get_db() as db:
                row = await (
                    await db.execute(
                        "SELECT snapshot_json FROM kg_snapshots"
                        " WHERE session_id = ? AND round_number = ?"
                        " ORDER BY id DESC LIMIT 1",
                        (session_id, round_number),
                    )
                ).fetchone()

            if not row:
                return {}
            return json.loads(row[0] or "{}")
        except Exception:
            logger.exception("get_snapshot failed session=%s round=%d", session_id, round_number)
            return {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _session_id_from_graph_id(graph_id: str) -> str:
    """Extract session_id from graph_id format ``graph_{session_id}_{hex}``.

    Falls back to using graph_id as-is if format doesn't match.
    """
    parts = graph_id.split("_")
    if len(parts) >= 3 and parts[0] == "graph":
        # Rejoin everything between 'graph_' and the final '_hex8'
        return "_".join(parts[1:-1])
    return graph_id
