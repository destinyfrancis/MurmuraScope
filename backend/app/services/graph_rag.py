"""GraphRAG service for community-level knowledge graph summarisation.

Implements a Map-Reduce GraphRAG pattern:
- Map: Summarise each Louvain community via LLM
- Reduce: Combine community summaries + TKG conflicts into global narrative
- Query: Semantic subgraph retrieval via LanceDB community embeddings

Reuses existing infrastructure: LanceDB (vector_store), Louvain (social_network),
TKG triples (memory_triples), token budgeting (token_budget).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from backend.app.utils.db import get_db
from backend.app.utils.llm_client import LLMClient
from backend.app.utils.logger import get_logger

logger = get_logger("graph_rag")

# Max concurrent LLM calls for community summarisation
_LLM_SEMAPHORE = asyncio.Semaphore(5)
# Skip clusters with fewer members than this threshold
_MIN_CLUSTER_SIZE = 3


# ---------------------------------------------------------------------------
# Data models (frozen dataclasses)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommunitySummary:
    """Immutable summary of a single Louvain community."""

    id: int | None
    session_id: str
    round_number: int
    cluster_id: int
    core_narrative: str
    shared_anxieties: str
    main_opposition: str
    member_count: int
    avg_trust: float


@dataclass(frozen=True)
class SubgraphInsight:
    """Immutable insight from semantic subgraph query."""

    query: str
    relevant_communities: list[int]
    node_count: int
    edge_count: int
    insight_report: str


@dataclass(frozen=True)
class TripleConflict:
    """Immutable representation of a TKG predicate conflict."""

    entity: str
    predicate_a: str
    object_a: str
    agent_ids_a: list[int]
    predicate_b: str
    object_b: str
    agent_ids_b: list[int]
    conflict_score: float


@dataclass(frozen=True)
class GlobalNarrative:
    """Immutable global narrative analysis across all communities."""

    session_id: str
    round_number: int
    community_count: int
    narrative_text: str
    fault_lines: list[str]


# ---------------------------------------------------------------------------
# Opposing predicate pairs for conflict detection
# ---------------------------------------------------------------------------

_OPPOSING_PAIRS: frozenset[tuple[str, str]] = frozenset({
    ("supports", "opposes"),
    ("opposes", "supports"),
    ("increases", "decreases"),
    ("decreases", "increases"),
    ("worries_about", "supports"),
    ("supports", "worries_about"),
    ("trusts", "distrusts"),
    ("distrusts", "trusts"),
    ("promotes", "blocks"),
    ("blocks", "promotes"),
})


# ---------------------------------------------------------------------------
# GraphRAGService
# ---------------------------------------------------------------------------


class GraphRAGService:
    """Community-level GraphRAG for report generation.

    Requires a VectorStore instance (for LanceDB community summary embeddings)
    and an optional LLMClient (defaults to a new instance if not provided).
    """

    def __init__(
        self,
        vector_store: Any | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        self._vector_store = vector_store
        self._llm = llm_client or LLMClient()

    # ------------------------------------------------------------------
    # Runtime table creation
    # ------------------------------------------------------------------

    @staticmethod
    async def _ensure_table() -> None:
        """Create community_summaries table if it doesn't exist."""
        async with get_db() as db:
            await db.execute(
                """CREATE TABLE IF NOT EXISTS community_summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    round_number INTEGER NOT NULL,
                    cluster_id INTEGER NOT NULL,
                    core_narrative TEXT NOT NULL,
                    shared_anxieties TEXT NOT NULL DEFAULT '',
                    main_opposition TEXT NOT NULL DEFAULT '',
                    member_count INTEGER NOT NULL DEFAULT 0,
                    avg_trust REAL NOT NULL DEFAULT 0.0,
                    created_at TEXT DEFAULT (datetime('now')),
                    UNIQUE(session_id, round_number, cluster_id)
                )"""
            )
            await db.commit()

    # ------------------------------------------------------------------
    # Map phase: generate_community_summaries
    # ------------------------------------------------------------------

    async def generate_community_summaries(
        self,
        session_id: str,
        round_number: int,
        echo_result: Any,
    ) -> list[CommunitySummary]:
        """Generate LLM summaries for each Louvain community (Map phase).

        Args:
            session_id: Simulation session UUID.
            round_number: Current simulation round.
            echo_result: EchoChamberResult from social_network.detect_echo_chambers().

        Returns:
            List of CommunitySummary objects persisted to SQLite + LanceDB.
        """
        await self._ensure_table()

        # Filter out tiny clusters
        valid_chambers = [
            c for c in echo_result.chambers
            if c.member_count >= _MIN_CLUSTER_SIZE
        ]
        if not valid_chambers:
            logger.info(
                "No clusters >= %d members, skipping community summaries session=%s",
                _MIN_CLUSTER_SIZE, session_id,
            )
            return []

        # Summarise each cluster in parallel (bounded by semaphore)
        tasks = [
            self._summarize_cluster(session_id, round_number, chamber)
            for chamber in valid_chambers
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        summaries: list[CommunitySummary] = []
        for r in results:
            if isinstance(r, Exception):
                logger.error("Cluster summarisation failed: %s", r)
            elif r is not None:
                summaries.append(r)

        if summaries:
            await self._persist_summaries(session_id, round_number, summaries)

        logger.info(
            "Generated %d community summaries session=%s round=%d",
            len(summaries), session_id, round_number,
        )
        return summaries

    async def _summarize_cluster(
        self,
        session_id: str,
        round_number: int,
        chamber: Any,
    ) -> CommunitySummary | None:
        """Summarise a single cluster using top-10 memories + triples.

        Args:
            session_id: Simulation session UUID.
            round_number: Current round.
            chamber: EchoChamber dataclass with cluster_id, member_ids, etc.

        Returns:
            CommunitySummary or None if cluster has insufficient data.
        """
        member_ids = list(chamber.member_ids) if hasattr(chamber, "member_ids") else []
        if len(member_ids) < _MIN_CLUSTER_SIZE:
            return None

        cluster_id = chamber.cluster_id

        # Fetch top-10 high-salience memories from cluster members
        placeholders = ",".join("?" * len(member_ids))
        async with get_db() as db:
            cursor = await db.execute(
                f"""SELECT memory_text, salience_score, agent_id
                    FROM agent_memories
                    WHERE session_id = ? AND agent_id IN ({placeholders})
                    ORDER BY salience_score DESC
                    LIMIT 10""",
                (session_id, *member_ids),
            )
            memory_rows = await cursor.fetchall()

            # Fetch triples from cluster members
            cursor = await db.execute(
                f"""SELECT subject, predicate, object, confidence
                    FROM memory_triples
                    WHERE session_id = ? AND agent_id IN ({placeholders})
                    ORDER BY confidence DESC
                    LIMIT 20""",
                (session_id, *member_ids),
            )
            triple_rows = await cursor.fetchall()

            # Compute average trust within cluster
            cursor = await db.execute(
                f"""SELECT AVG(trust_score) as avg_trust
                    FROM agent_relationships
                    WHERE session_id = ?
                    AND agent_a_id IN ({placeholders})
                    AND agent_b_id IN ({placeholders})""",
                (session_id, *member_ids, *member_ids),
            )
            trust_row = await cursor.fetchone()

        avg_trust = float(trust_row["avg_trust"]) if trust_row and trust_row["avg_trust"] else 0.0
        member_count = len(member_ids)

        if not memory_rows and not triple_rows:
            logger.debug("Cluster %d has no memories/triples, skipping", cluster_id)
            return None

        # Format data for prompt
        top_memories = "\n".join(
            f"- [{r['salience_score']:.2f}] {r['memory_text'][:120]}"
            for r in memory_rows
        )
        triples = "\n".join(
            f"- ({r['subject']}, {r['predicate']}, {r['object']}) [conf={r['confidence']:.2f}]"
            for r in triple_rows
        )

        from backend.prompts.report_prompts import (  # noqa: PLC0415
            COMMUNITY_SUMMARY_SYSTEM,
            COMMUNITY_SUMMARY_USER,
        )

        user_prompt = COMMUNITY_SUMMARY_USER.format(
            cluster_id=cluster_id,
            member_count=member_count,
            avg_trust=avg_trust,
            top_memories=top_memories or "(無記憶)",
            triples=triples or "(無三元組)",
        )

        async with _LLM_SEMAPHORE:
            try:
                result = await self._llm.chat_json(
                    [
                        {"role": "system", "content": COMMUNITY_SUMMARY_SYSTEM},
                        {"role": "user", "content": user_prompt},
                    ],
                    provider="openrouter",
                    max_tokens=512,
                )
            except Exception as exc:
                logger.error("LLM summarise cluster %d failed: %s", cluster_id, exc)
                return None

        return CommunitySummary(
            id=None,
            session_id=session_id,
            round_number=round_number,
            cluster_id=cluster_id,
            core_narrative=result.get("core_narrative", ""),
            shared_anxieties=result.get("shared_anxieties", ""),
            main_opposition=result.get("main_opposition", ""),
            member_count=member_count,
            avg_trust=avg_trust,
        )

    async def _persist_summaries(
        self,
        session_id: str,
        round_number: int,
        summaries: list[CommunitySummary],
    ) -> None:
        """Persist community summaries to SQLite + LanceDB embeddings."""
        # SQLite upsert
        async with get_db() as db:
            await db.executemany(
                """INSERT INTO community_summaries
                   (session_id, round_number, cluster_id,
                    core_narrative, shared_anxieties, main_opposition,
                    member_count, avg_trust)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(session_id, round_number, cluster_id)
                   DO UPDATE SET
                       core_narrative = excluded.core_narrative,
                       shared_anxieties = excluded.shared_anxieties,
                       main_opposition = excluded.main_opposition,
                       member_count = excluded.member_count,
                       avg_trust = excluded.avg_trust""",
                [
                    (
                        s.session_id, s.round_number, s.cluster_id,
                        s.core_narrative, s.shared_anxieties, s.main_opposition,
                        s.member_count, s.avg_trust,
                    )
                    for s in summaries
                ],
            )
            await db.commit()

        # LanceDB: embed community narratives for semantic retrieval
        if self._vector_store is not None:
            try:
                from backend.app.services.embedding_provider import EmbeddingProvider  # noqa: PLC0415

                embedder = EmbeddingProvider()
                texts = [
                    f"社群{s.cluster_id}: {s.core_narrative} {s.shared_anxieties}"
                    for s in summaries
                ]

                import asyncio as _asyncio  # noqa: PLC0415

                vectors = await _asyncio.to_thread(embedder.embed, texts)

                records = [
                    {
                        "memory_id": s.cluster_id + round_number * 1000,
                        "session_id": session_id,
                        "agent_id": -1,  # sentinel for community summaries
                        "round_number": s.round_number,
                        "memory_text": f"社群{s.cluster_id}: {s.core_narrative} {s.shared_anxieties}",
                        "memory_type": "community_summary",
                        "salience_score": 0.9,
                        "vector": vec.tolist(),
                    }
                    for s, vec in zip(summaries, vectors)
                ]

                table_name = f"cs_{session_id.replace('-', '')[:12]}"

                def _upsert() -> None:
                    import lancedb  # noqa: PLC0415
                    from pathlib import Path  # noqa: PLC0415

                    db_path = Path("data/vector_store")
                    db_path.mkdir(parents=True, exist_ok=True)
                    db = lancedb.connect(str(db_path))
                    try:
                        tbl = db.open_table(table_name)
                        tbl.add(records)
                    except Exception:
                        db.create_table(table_name, records)

                await asyncio.to_thread(_upsert)
                logger.debug(
                    "Persisted %d community summary embeddings to LanceDB table=%s",
                    len(records), table_name,
                )
            except Exception:
                logger.exception("Failed to persist community summaries to LanceDB")

    # ------------------------------------------------------------------
    # Semantic subgraph query
    # ------------------------------------------------------------------

    async def semantic_subgraph_query(
        self,
        session_id: str,
        query: str,
        max_depth: int = 2,
        max_edges: int = 50,
    ) -> SubgraphInsight:
        """Semantic subgraph retrieval: query → top-3 communities → 2-hop CTE → LLM insight.

        Args:
            session_id: Simulation session UUID.
            query: Natural language query.
            max_depth: Maximum hop depth for recursive CTE (default 2).
            max_edges: Maximum edges to return (default 50).

        Returns:
            SubgraphInsight with structured analysis.
        """
        # Step 1: Find relevant community summaries via LanceDB
        relevant_summaries = await self._search_community_summaries(
            session_id, query, top_k=3
        )

        if not relevant_summaries:
            raise ValueError("No community summaries available for semantic query")

        # Collect seed nodes from relevant communities
        cluster_ids = [s["cluster_id"] for s in relevant_summaries]

        # Get member agent IDs from echo chamber snapshots
        seed_nodes: list[str] = []
        async with get_db() as db:
            cursor = await db.execute(
                """SELECT cluster_data_json FROM echo_chamber_snapshots
                   WHERE session_id = ?
                   ORDER BY round_number DESC LIMIT 1""",
                (session_id,),
            )
            row = await cursor.fetchone()
            if row and row["cluster_data_json"]:
                cluster_data = json.loads(row["cluster_data_json"])
                for cluster in cluster_data:
                    cid = cluster.get("cluster_id", cluster.get("id", -1))
                    if cid in cluster_ids:
                        members = cluster.get("member_ids", [])
                        seed_nodes.extend(str(m) for m in members[:10])

        # Step 2: 2-hop recursive CTE from seed nodes
        if not seed_nodes:
            # Fallback: use query as LIKE search on kg_nodes
            async with get_db() as db:
                cursor = await db.execute(
                    """SELECT id FROM kg_nodes
                       WHERE session_id = ? AND (title LIKE ? OR description LIKE ?)
                       LIMIT 10""",
                    (session_id, f"%{query}%", f"%{query}%"),
                )
                seed_nodes = [r["id"] for r in await cursor.fetchall()]

        subgraph_edges: list[dict[str, Any]] = []
        if seed_nodes:
            placeholders = ",".join("?" * len(seed_nodes))
            async with get_db() as db:
                cursor = await db.execute(
                    f"""WITH RECURSIVE subgraph AS (
                        SELECT source_id, target_id, relation_type, weight, 1 AS depth
                        FROM kg_edges
                        WHERE session_id = ? AND source_id IN ({placeholders})
                        UNION ALL
                        SELECT e.source_id, e.target_id, e.relation_type, e.weight, s.depth + 1
                        FROM kg_edges e
                        JOIN subgraph s ON e.source_id = s.target_id
                        WHERE e.session_id = ? AND s.depth < ?
                    )
                    SELECT DISTINCT source_id, target_id, relation_type, weight
                    FROM subgraph
                    ORDER BY weight DESC
                    LIMIT ?""",
                    (session_id, *seed_nodes, session_id, max_depth, max_edges),
                )
                rows = await cursor.fetchall()
                subgraph_edges = [
                    {
                        "source": r["source_id"],
                        "target": r["target_id"],
                        "relation": r["relation_type"],
                        "weight": r["weight"],
                    }
                    for r in rows
                ]

        # Collect unique nodes
        nodes: set[str] = set()
        for edge in subgraph_edges:
            nodes.add(edge["source"])
            nodes.add(edge["target"])

        # Step 3: Generate insight via LLM
        from backend.prompts.report_prompts import (  # noqa: PLC0415
            SUBGRAPH_INSIGHT_SYSTEM,
            SUBGRAPH_INSIGHT_USER,
        )

        community_text = "\n".join(
            f"- 社群 #{s['cluster_id']}（{s['member_count']} 人）：{s['core_narrative']}"
            for s in relevant_summaries
        )
        edge_text = "\n".join(
            f"- {e['source']} --[{e['relation']}]--> {e['target']} (w={e['weight']:.2f})"
            for e in subgraph_edges[:30]
        )

        user_prompt = SUBGRAPH_INSIGHT_USER.format(
            query=query,
            community_summaries=community_text or "(無社群摘要)",
            node_count=len(nodes),
            edge_count=len(subgraph_edges),
            subgraph_edges=edge_text or "(無子圖邊)",
        )

        async with _LLM_SEMAPHORE:
            response = await self._llm.chat(
                [
                    {"role": "system", "content": SUBGRAPH_INSIGHT_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                provider="openrouter",
                max_tokens=1024,
            )

        return SubgraphInsight(
            query=query,
            relevant_communities=cluster_ids,
            node_count=len(nodes),
            edge_count=len(subgraph_edges),
            insight_report=response.content,
        )

    async def _search_community_summaries(
        self,
        session_id: str,
        query: str,
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        """Search community summaries via LanceDB semantic similarity.

        Falls back to SQL if LanceDB table doesn't exist.
        """
        # Try LanceDB first
        try:
            from backend.app.services.embedding_provider import EmbeddingProvider  # noqa: PLC0415

            embedder = EmbeddingProvider()
            query_vec = await asyncio.to_thread(embedder.embed_single, query)

            table_name = f"cs_{session_id.replace('-', '')[:12]}"

            def _search() -> list[dict[str, Any]]:
                import lancedb  # noqa: PLC0415
                from pathlib import Path  # noqa: PLC0415

                db = lancedb.connect(str(Path("data/vector_store")))
                try:
                    tbl = db.open_table(table_name)
                except Exception:
                    return []

                results_df = tbl.search(query_vec.tolist()).limit(top_k).to_pandas()
                return results_df.to_dict("records")

            lance_results = await asyncio.to_thread(_search)
            if lance_results:
                # Enrich with full summary data from SQLite
                cluster_ids = [int(r.get("memory_id", 0)) % 1000 for r in lance_results]
                return await self._load_summaries_by_clusters(session_id, cluster_ids)
        except Exception:
            logger.debug("LanceDB community search failed, falling back to SQL")

        # Fallback: load latest summaries from SQL
        return await self._load_latest_summaries(session_id, limit=top_k)

    async def _load_summaries_by_clusters(
        self,
        session_id: str,
        cluster_ids: list[int],
    ) -> list[dict[str, Any]]:
        """Load community summaries by cluster IDs (latest round)."""
        if not cluster_ids:
            return []

        placeholders = ",".join("?" * len(cluster_ids))
        async with get_db() as db:
            cursor = await db.execute(
                f"""SELECT * FROM community_summaries
                    WHERE session_id = ? AND cluster_id IN ({placeholders})
                    ORDER BY round_number DESC""",
                (session_id, *cluster_ids),
            )
            rows = await cursor.fetchall()

        seen: set[int] = set()
        results: list[dict[str, Any]] = []
        for r in rows:
            cid = r["cluster_id"]
            if cid not in seen:
                seen.add(cid)
                results.append(dict(r))
        return results

    async def _load_latest_summaries(
        self,
        session_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Load the most recent community summaries for a session."""
        async with get_db() as db:
            cursor = await db.execute(
                """SELECT * FROM community_summaries
                   WHERE session_id = ?
                   AND round_number = (
                       SELECT MAX(round_number) FROM community_summaries
                       WHERE session_id = ?
                   )
                   ORDER BY member_count DESC
                   LIMIT ?""",
                (session_id, session_id, limit),
            )
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # TKG conflict detection (pure SQL + Python, zero LLM cost)
    # ------------------------------------------------------------------

    async def detect_triple_conflicts(
        self,
        session_id: str,
        min_agents_per_side: int = 3,
    ) -> list[TripleConflict]:
        """Detect conflicting TKG triples across agents.

        Scans memory_triples, groups by subject, finds opposing predicate pairs
        where each side has at least `min_agents_per_side` distinct agents.

        Args:
            session_id: Simulation session UUID.
            min_agents_per_side: Minimum agents per side to qualify as conflict.

        Returns:
            List of TripleConflict sorted by conflict_score descending.
        """
        async with get_db() as db:
            cursor = await db.execute(
                """SELECT subject, predicate, object, agent_id
                   FROM memory_triples
                   WHERE session_id = ?
                   ORDER BY subject, predicate""",
                (session_id,),
            )
            rows = await cursor.fetchall()

        if not rows:
            return []

        # Group by (subject, predicate) → {object: set(agent_ids)}
        subject_predicates: dict[str, dict[str, dict[str, set[int]]]] = {}
        for r in rows:
            subj = r["subject"]
            pred = r["predicate"]
            obj = r["object"]
            agent_id = r["agent_id"]

            if subj not in subject_predicates:
                subject_predicates[subj] = {}
            if pred not in subject_predicates[subj]:
                subject_predicates[subj][pred] = {}
            if obj not in subject_predicates[subj][pred]:
                subject_predicates[subj][pred][obj] = set()
            subject_predicates[subj][pred][obj].add(agent_id)

        conflicts: list[TripleConflict] = []

        for entity, pred_map in subject_predicates.items():
            predicates = list(pred_map.keys())
            for i, pred_a in enumerate(predicates):
                for pred_b in predicates[i + 1:]:
                    if (pred_a, pred_b) not in _OPPOSING_PAIRS and (pred_b, pred_a) not in _OPPOSING_PAIRS:
                        continue

                    # Find the most popular object for each predicate
                    objs_a = pred_map[pred_a]
                    objs_b = pred_map[pred_b]

                    best_obj_a = max(objs_a.items(), key=lambda x: len(x[1]))
                    best_obj_b = max(objs_b.items(), key=lambda x: len(x[1]))

                    agents_a = best_obj_a[1]
                    agents_b = best_obj_b[1]

                    if len(agents_a) < min_agents_per_side or len(agents_b) < min_agents_per_side:
                        continue

                    # Conflict score = geometric mean of side sizes / total agents
                    total = len(agents_a) + len(agents_b)
                    score = (len(agents_a) * len(agents_b)) ** 0.5 / max(total, 1)

                    conflicts.append(TripleConflict(
                        entity=entity,
                        predicate_a=pred_a,
                        object_a=best_obj_a[0],
                        agent_ids_a=sorted(agents_a),
                        predicate_b=pred_b,
                        object_b=best_obj_b[0],
                        agent_ids_b=sorted(agents_b),
                        conflict_score=round(score, 4),
                    ))

        conflicts.sort(key=lambda c: c.conflict_score, reverse=True)
        return conflicts

    # ------------------------------------------------------------------
    # Reduce phase: global narrative
    # ------------------------------------------------------------------

    async def get_global_narrative(
        self,
        session_id: str,
        round_number: int | None = None,
    ) -> GlobalNarrative:
        """Generate a global narrative by combining all community summaries + conflicts.

        Args:
            session_id: Simulation session UUID.
            round_number: Specific round (or latest if None).

        Returns:
            GlobalNarrative with analysis text and fault lines.
        """
        await self._ensure_table()

        # Load summaries
        if round_number is not None:
            async with get_db() as db:
                cursor = await db.execute(
                    """SELECT * FROM community_summaries
                       WHERE session_id = ? AND round_number = ?
                       ORDER BY member_count DESC""",
                    (session_id, round_number),
                )
                rows = await cursor.fetchall()
        else:
            rows_list = await self._load_latest_summaries(session_id, limit=20)
            rows = rows_list
            if rows:
                round_number = rows[0].get("round_number", 0)
            else:
                round_number = 0

        summaries_data = [dict(r) for r in rows] if rows else []
        if not summaries_data:
            return GlobalNarrative(
                session_id=session_id,
                round_number=round_number or 0,
                community_count=0,
                narrative_text="暫無社群摘要數據，無法生成全局敘事。",
                fault_lines=[],
            )

        # Detect conflicts
        conflicts = await self.detect_triple_conflicts(session_id)

        # Format for prompt
        from backend.prompts.report_prompts import (  # noqa: PLC0415
            GLOBAL_NARRATIVE_SYSTEM,
            GLOBAL_NARRATIVE_USER,
        )

        all_summaries_text = "\n".join(
            f"### 社群 #{s.get('cluster_id', '?')}（{s.get('member_count', 0)} 人，信任度 {s.get('avg_trust', 0):.2f}）\n"
            f"- 核心敘事：{s.get('core_narrative', '')}\n"
            f"- 共同焦慮：{s.get('shared_anxieties', '')}\n"
            f"- 主要對立：{s.get('main_opposition', '')}"
            for s in summaries_data
        )

        conflict_text = "\n".join(
            f"- **{c.entity}**：{len(c.agent_ids_a)} 人認為 [{c.predicate_a}→{c.object_a}] "
            f"vs {len(c.agent_ids_b)} 人認為 [{c.predicate_b}→{c.object_b}]（衝突分數 {c.conflict_score:.2f}）"
            for c in conflicts[:10]
        ) or "(無明顯觀點衝突)"

        user_prompt = GLOBAL_NARRATIVE_USER.format(
            session_id=session_id,
            round_number=round_number,
            community_count=len(summaries_data),
            all_community_summaries=all_summaries_text,
            conflict_data=conflict_text,
        )

        async with _LLM_SEMAPHORE:
            response = await self._llm.chat(
                [
                    {"role": "system", "content": GLOBAL_NARRATIVE_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                provider="openrouter",
                max_tokens=1536,
            )

        # Extract fault lines (lines starting with numbered patterns or bold markers)
        narrative = response.content
        fault_lines: list[str] = []
        for line in narrative.split("\n"):
            stripped = line.strip()
            if stripped.startswith("**") and "**" in stripped[2:]:
                # Extract bold text as fault line label
                end = stripped.index("**", 2)
                label = stripped[2:end].strip("：: ")
                if label:
                    fault_lines.append(label)

        return GlobalNarrative(
            session_id=session_id,
            round_number=round_number or 0,
            community_count=len(summaries_data),
            narrative_text=narrative,
            fault_lines=fault_lines,
        )
