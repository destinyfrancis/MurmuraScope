"""Agent long-term memory service with optional semantic vector search.

Stores per-round memory summaries (via LLM) for each agent, with
salience-based decay and hybrid retrieval (semantic + salience re-ranking).

When a VectorStore is provided, memories are dual-written to both SQLite and
LanceDB; retrieval uses cosine similarity re-ranked with salience. When no
VectorStore is available, falls back to the original SQL-only path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

import aiosqlite

from backend.app.utils.db import get_db
from backend.app.utils.llm_client import LLMClient, get_agent_provider_model
from backend.app.utils.logger import get_logger
from backend.app.utils.token_budget import TokenBudget
from backend.app.utils.token_counter import TokenCounter
from backend.prompts.memory_prompts import (
    MEMORY_COMPRESSION_SYSTEM,
    MEMORY_COMPRESSION_USER,
    MEMORY_CONTEXT_FORMAT,
    MEMORY_SUMMARIZE_SYSTEM,
    MEMORY_SUMMARIZE_USER,
)

if TYPE_CHECKING:
    from backend.app.services.vector_store import VectorStore

from backend.app.services.triple_extractor import TripleExtractor

logger = get_logger("agent_memory")

_SALIENCE_DECAY = 0.85
_SALIENCE_PRUNE_THRESHOLD = 0.05
_SALIENCE_MIN_FLOOR = 0.07  # memories stabilize here — above prune threshold, never deleted
_MAX_MEMORIES_PER_AGENT_PER_ROUND = 3
_CONTEXT_ROUNDS_LOOKBACK = 5
_MAX_CONTEXT_MEMORIES = 10

# Hybrid re-ranking weights
_WEIGHT_SEMANTIC = 0.4
_WEIGHT_SALIENCE = 0.3
_WEIGHT_IMPORTANCE = 0.3

# Memory summarization constants (Phase 17)
_SUMMARIZE_INTERVAL: int = 10
_SUMMARIZE_MIN_MEMORIES: int = 5
_SUMMARY_SALIENCE: float = 0.8

# Memory compression constants (Phase 6 — ReMe-inspired lazy compression)
_COMPRESSION_THRESHOLD: int = 200      # trigger when agent has >200 non-summary memories
_COMPRESSION_BATCH_SIZE: int = 100     # compress oldest 100 memories per trigger
_COMPRESSION_MIN_ROUND_AGE: int = 5    # only compress memories from ≥5 rounds ago


@dataclass(frozen=True)
class AgentMemory:
    """Immutable memory record for a single agent."""

    id: int | None
    session_id: str
    agent_id: int
    round_number: int
    memory_text: str
    salience_score: float
    memory_type: str


class AgentMemoryService:
    """Manages agent memory: store, retrieve, decay — with optional vector search."""

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        vector_store: "VectorStore | None" = None,
        summarize_interval: int = 20,
        summarize_salience_threshold: float = 0.3,
    ) -> None:
        self._llm = llm_client or LLMClient()
        self._vector_store = vector_store
        self._triple_extractor = TripleExtractor()
        self._summarize_interval = summarize_interval
        self._summarize_salience_threshold = summarize_salience_threshold

    @property
    def has_vector_store(self) -> bool:
        return self._vector_store is not None

    async def store_round_memories(
        self,
        session_id: str,
        round_number: int,
        posts_by_agent: dict[str, list[str]],
        username_to_agent_id: dict[str, int] | None = None,
    ) -> int:
        """Summarise each agent's posts for this round into memories.

        Dual-writes to SQLite + LanceDB (if vector store available).

        Returns:
            Total number of memory records inserted.
        """
        if not posts_by_agent:
            return 0

        total = 0
        for username, posts in posts_by_agent.items():
            if not posts:
                continue

            agent_id = (username_to_agent_id or {}).get(username)
            memories = await self._summarize_posts(username, posts, round_number)

            if memories:
                rows = []
                for m in memories[:_MAX_MEMORIES_PER_AGENT_PER_ROUND]:
                    if agent_id is None:
                        continue
                    importance_raw = float(m.get("importance_score", 5))
                    importance = max(0.0, min(1.0, importance_raw / 10.0))
                    rows.append((
                        session_id,
                        agent_id,
                        round_number,
                        m.get("memory_text", ""),
                        float(m.get("salience_score", 0.5)),
                        m.get("memory_type", "observation"),
                        importance,
                    ))

                if rows:
                    try:
                        inserted_ids: list[int] = []
                        async with get_db() as db:
                            for row in rows:
                                cursor = await db.execute(
                                    """
                                    INSERT INTO agent_memories
                                        (session_id, agent_id, round_number,
                                         memory_text, salience_score, memory_type,
                                         importance_score)
                                    VALUES (?, ?, ?, ?, ?, ?, ?)
                                    """,
                                    row,
                                )
                                inserted_ids.append(cursor.lastrowid)
                            await db.commit()
                        total += len(rows)

                        # Extract and store triples for each inserted memory
                        try:
                            triple_rows: list[tuple] = []
                            for row_data, mem_id in zip(rows, inserted_ids):
                                if mem_id is None:
                                    continue
                                # row_data: (session_id, agent_id, round_number,
                                #            memory_text, salience_score, memory_type,
                                #            importance_score)
                                mem_text = row_data[3]
                                mem_type = row_data[5]
                                triples = self._triple_extractor.extract_triples(
                                    mem_text, mem_type, username,
                                )
                                for t in triples:
                                    triple_rows.append((
                                        mem_id,
                                        session_id,
                                        agent_id,
                                        round_number,
                                        t.subject,
                                        t.predicate,
                                        t.object,
                                        t.confidence,
                                    ))
                            if triple_rows:
                                async with get_db() as db:
                                    await db.executemany(
                                        """
                                        INSERT OR IGNORE INTO memory_triples
                                            (memory_id, session_id, agent_id, round_number,
                                             subject, predicate, object, confidence)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                        """,
                                        triple_rows,
                                    )
                                    await db.commit()
                        except Exception:
                            logger.exception(
                                "triple extraction/insert failed session=%s round=%d",
                                session_id, round_number,
                            )

                        # Dual-write to vector store
                        if self._vector_store is not None:
                            vec_records = []
                            for row_data, mem_id in zip(rows, inserted_ids):
                                vec_records.append({
                                    "memory_id": mem_id,
                                    "agent_id": row_data[1],
                                    "round_number": row_data[2],
                                    "memory_text": row_data[3],
                                    "salience_score": row_data[4],
                                    "memory_type": row_data[5],
                                    "importance_score": row_data[6],
                                })
                            try:
                                await self._vector_store.add_memories(
                                    session_id, vec_records,
                                )
                            except Exception:
                                logger.exception(
                                    "vector_store.add_memories failed session=%s round=%d",
                                    session_id, round_number,
                                )

                    except Exception:
                        logger.exception(
                            "store_round_memories insert failed session=%s round=%d",
                            session_id, round_number,
                        )

        return total

    async def get_agent_context(
        self,
        session_id: str,
        agent_id: int,
        current_round: int,
        context_query: str | None = None,
        trust_context: str = "",
    ) -> str:
        """Build a memory context string for persona enrichment.

        If a vector store is available and *context_query* is provided, uses
        hybrid semantic + salience re-ranking. Otherwise falls back to SQL.
        Appends relational context (TKG triples) and optional trust context.

        Args:
            session_id: Session UUID.
            agent_id: agent_profiles.id.
            current_round: Current simulation round.
            context_query: Optional query text for semantic search
                (e.g. scenario description or recent posts).
            trust_context: Optional pre-formatted trust relationship string.

        Returns:
            Formatted memory context string, or empty string if no memories.
        """
        # Lazy memory compression: compact old memories when threshold exceeded
        await self._compress_if_needed(session_id, agent_id, current_round)

        # Try semantic path first
        memory_context = ""
        if self._vector_store is not None and context_query:
            try:
                results = await self._vector_store.search(
                    session_id=session_id,
                    query_text=context_query,
                    agent_id=agent_id,
                    top_k=_MAX_CONTEXT_MEMORIES * 2,
                )
                if results:
                    # Hybrid re-rank: semantic * 0.4 + salience * 0.3 + importance * 0.3
                    ranked = sorted(
                        results,
                        key=lambda r: (
                            _WEIGHT_SEMANTIC * r.similarity_score
                            + _WEIGHT_SALIENCE * r.salience_score
                            + _WEIGHT_IMPORTANCE * r.importance_score
                        ),
                        reverse=True,
                    )[:_MAX_CONTEXT_MEMORIES]

                    memory_lines = [
                        MEMORY_CONTEXT_FORMAT.format(
                            round_number=r.round_number,
                            memory_type=r.memory_type,
                            salience=r.salience_score,
                            memory_text=r.memory_text,
                        )
                        for r in ranked
                    ]
                    memory_context = "\n".join(["【近期記憶】"] + memory_lines)
            except Exception:
                logger.exception(
                    "Semantic search failed, falling back to SQL session=%s agent=%d",
                    session_id, agent_id,
                )

        # SQL fallback
        if not memory_context:
            memory_context = await self._get_agent_context_sql(
                session_id, agent_id, current_round
            )

        # Append relational context (TKG triples) if memories exist
        parts = [memory_context] if memory_context else []

        relational = await self.get_relational_context(session_id, agent_id)
        if relational:
            parts.append(relational)

        if trust_context:
            parts.append(trust_context)

        return "\n".join(parts)

    async def get_relational_context(
        self,
        session_id: str,
        agent_id: int,
        entity_query: str = "",
        max_hops: int = 2,
    ) -> str:
        """Build a relational context string from memory triples (TKG).

        Uses a recursive CTE to traverse up to *max_hops* from any triple
        involving the agent or the *entity_query* term.

        Args:
            session_id: Session UUID.
            agent_id: agent_profiles.id.
            entity_query: Optional entity to start traversal from.
                          Defaults to querying triples where subject/object
                          contains the agent's own references.
            max_hops: Maximum graph traversal depth (default 2).

        Returns:
            Formatted string like
            「【關係記憶】我 → 擔心 → 樓價; 樓價 → 受影響 → 加息」
            or empty string if no triples.
        """
        try:
            async with get_db() as db:
                if entity_query:
                    like_param = f"%{entity_query}%"
                    cursor = await db.execute(
                        """
                        WITH RECURSIVE hops(subject, predicate, object, depth) AS (
                            SELECT subject, predicate, object, 1
                            FROM memory_triples
                            WHERE session_id = ?
                              AND agent_id = ?
                              AND (subject LIKE ? OR object LIKE ?)
                          UNION ALL
                            SELECT mt.subject, mt.predicate, mt.object, h.depth + 1
                            FROM memory_triples mt
                            JOIN hops h
                              ON (mt.subject = h.object OR mt.object = h.subject)
                            WHERE mt.session_id = ?
                              AND mt.agent_id = ?
                              AND h.depth < ?
                        )
                        SELECT DISTINCT subject, predicate, object,
                               MIN(depth) AS min_depth
                        FROM hops
                        GROUP BY subject, predicate, object
                        ORDER BY min_depth
                        LIMIT 20
                        """,
                        (
                            session_id, agent_id, like_param, like_param,
                            session_id, agent_id, max_hops,
                        ),
                    )
                else:
                    # No entity query: just return the most recent triples for the agent
                    cursor = await db.execute(
                        """
                        SELECT DISTINCT subject, predicate, object, 0 AS min_depth
                        FROM memory_triples
                        WHERE session_id = ? AND agent_id = ?
                        ORDER BY id DESC
                        LIMIT 20
                        """,
                        (session_id, agent_id),
                    )
                rows = await cursor.fetchall()
        except Exception:
            logger.exception(
                "get_relational_context failed session=%s agent=%d",
                session_id, agent_id,
            )
            return ""

        if not rows:
            return ""

        triple_strs = [f"{r[0]} → {r[1]} → {r[2]}" for r in rows]
        return "【關係記憶】" + "; ".join(triple_strs)

    async def decay_memories(
        self,
        session_id: str,
        round_number: int,
    ) -> int:
        """Apply salience decay to all memories for this session.

        Syncs decay to both SQLite and LanceDB (if available).

        Returns:
            Number of pruned memory records.
        """
        try:
            async with get_db() as db:
                await db.execute(
                    """
                    UPDATE agent_memories
                    SET salience_score = MAX(salience_score * ?, ?)
                    WHERE session_id = ?
                    """,
                    (_SALIENCE_DECAY, _SALIENCE_MIN_FLOOR, session_id),
                )
                cursor = await db.execute(
                    """
                    DELETE FROM agent_memories
                    WHERE session_id = ?
                      AND salience_score < ?
                    """,
                    (session_id, _SALIENCE_PRUNE_THRESHOLD),
                )
                pruned = cursor.rowcount
                await db.commit()

            # Sync decay to vector store
            if self._vector_store is not None:
                try:
                    await self._vector_store.update_salience(
                        session_id, decay_factor=_SALIENCE_DECAY,
                    )
                except Exception:
                    logger.exception(
                        "vector_store.update_salience failed session=%s", session_id,
                    )

            logger.debug(
                "decay_memories round=%d pruned=%d session=%s",
                round_number, pruned, session_id,
            )
            return pruned
        except Exception:
            logger.exception(
                "decay_memories failed session=%s round=%d", session_id, round_number
            )
            return 0

    async def get_agent_memories(
        self,
        session_id: str,
        agent_id: int,
        limit: int = 50,
    ) -> list[dict]:
        """Retrieve all memories for an agent (for API/debug).

        Returns:
            List of memory dicts.
        """
        try:
            async with get_db() as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """
                    SELECT id, session_id, agent_id, round_number,
                           memory_text, salience_score, memory_type, created_at
                    FROM agent_memories
                    WHERE session_id = ? AND agent_id = ?
                    ORDER BY round_number DESC, salience_score DESC
                    LIMIT ?
                    """,
                    (session_id, agent_id, limit),
                )
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]
        except Exception:
            logger.exception(
                "get_agent_memories failed session=%s agent=%d", session_id, agent_id
            )
            return []

    async def get_agent_triples(
        self,
        session_id: str,
        agent_id: int,
        limit: int = 100,
    ) -> list[dict]:
        """Retrieve memory triples (TKG) for an agent.

        Returns:
            List of triple dicts with subject, predicate, object, confidence,
            round_number, and memory_id.
        """
        try:
            async with get_db() as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """
                    SELECT mt.id, mt.memory_id, mt.session_id, mt.agent_id,
                           mt.round_number, mt.subject, mt.predicate, mt.object,
                           mt.confidence
                    FROM memory_triples mt
                    WHERE mt.session_id = ? AND mt.agent_id = ?
                    ORDER BY mt.round_number DESC, mt.id DESC
                    LIMIT ?
                    """,
                    (session_id, agent_id, limit),
                )
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]
        except Exception:
            logger.exception(
                "get_agent_triples failed session=%s agent=%d",
                session_id, agent_id,
            )
            return []

    async def search_memories(
        self,
        session_id: str,
        agent_id: int,
        query: str,
        top_k: int = 10,
        with_kg_subgraph: bool = False,
    ) -> list[dict]:
        """Public semantic search across an agent's memories.

        Optionally enriches results with KG sub-graph context (nodes and
        direct edges) for any entity IDs referenced in the returned memories.

        Args:
            session_id: Session UUID.
            agent_id: agent_profiles.id.
            query: Natural-language search query.
            top_k: Max results.
            with_kg_subgraph: When True, fetches KG nodes/edges for entity
                IDs found in the memory results and returns a combined dict.
                Defaults to False (zero change to existing behaviour).

        Returns:
            When *with_kg_subgraph* is False: list of dicts with memory
            fields + similarity_score (original behaviour).
            When *with_kg_subgraph* is True: list containing a single dict
            with keys ``"memories"`` and ``"kg_context"``.

        Raises:
            RuntimeError: If vector store is not available.
        """
        if self._vector_store is None:
            raise RuntimeError("Vector store not available — semantic search disabled")

        results = await self._vector_store.search(
            session_id=session_id,
            query_text=query,
            agent_id=agent_id,
            top_k=top_k,
        )

        memories = [
            {
                "memory_id": r.memory_id,
                "memory_text": r.memory_text,
                "round_number": r.round_number,
                "salience_score": r.salience_score,
                "memory_type": r.memory_type,
                "similarity_score": round(r.similarity_score, 4),
            }
            for r in results
        ]

        if with_kg_subgraph:
            entity_ids = [m.get("entity_id") for m in memories if m.get("entity_id")]
            if entity_ids:
                kg_context = await self._fetch_kg_subgraph(entity_ids)
                return [{"memories": memories, "kg_context": kg_context}]

        return memories

    async def build_context_window(
        self,
        session_id: str,
        agent_id: int,
        current_round: int,
        context_query: str,
        max_tokens: int = 4096,
    ) -> str:
        """Three-tier context assembly with token budgeting.

        Tiers:
          1. Recency: last 5 rounds, max 5 memories (budget: 40%)
          2. Semantic: LanceDB top-5 by hybrid score (budget: 40%)
          3. Social: top-3 trusted KOL latest posts (budget: 20%)

        Args:
            session_id: Session UUID.
            agent_id: agent_profiles.id.
            current_round: Current simulation round.
            context_query: Query text for semantic search.
            max_tokens: Total token budget.

        Returns:
            Assembled context string within budget.
        """
        budget = TokenBudget(total=max_tokens)

        # Priority 1: Recency (40% budget)
        recent = await self._get_recent_memories(
            session_id, agent_id, current_round, limit=5
        )
        recency_block = self._format_memories(recent, "短期記憶")
        recency_tokens = TokenCounter.count(recency_block)

        # Priority 2: Semantic (40% budget)
        semantic_block = ""
        if self._vector_store and context_query:
            try:
                results = await self._vector_store.search(
                    session_id=session_id,
                    query_text=context_query,
                    agent_id=agent_id,
                    top_k=5,
                )
                # Deduplicate against recency
                recent_ids = {m["id"] for m in recent if m.get("id")}
                unique_results = [
                    r for r in results if r.memory_id not in recent_ids
                ]
                if unique_results:
                    semantic_mems = [
                        {
                            "round_number": r.round_number,
                            "memory_type": r.memory_type,
                            "salience_score": r.salience_score,
                            "memory_text": r.memory_text,
                        }
                        for r in unique_results
                    ]
                    semantic_block = self._format_memories(semantic_mems, "相關記憶")
            except Exception:
                logger.exception(
                    "Semantic tier failed session=%s agent=%d", session_id, agent_id
                )
        semantic_tokens = TokenCounter.count(semantic_block)

        # Tier 3: Social influence (20% budget)
        kol_block = await self._get_kol_context(session_id, agent_id, current_round)
        social_tokens = TokenCounter.count(kol_block)

        # Assemble with priority: recency=1.0, semantic=0.9, social=0.8
        blocks = [
            (recency_block, recency_tokens, 1.0),
            (semantic_block, semantic_tokens, 0.9),
            (kol_block, social_tokens, 0.8),
        ]

        return budget.assemble(blocks)

    async def summarize_old_memories(
        self,
        session_id: str,
        agent_id: int,
        current_round: int,
    ) -> bool:
        """Compress memories older than _SUMMARIZE_INTERVAL rounds into a summary.

        Inspired by Zep Cloud's memory summarization, but runs locally
        via DeepSeek to avoid privacy/cost/latency concerns.

        Returns True if summarization was performed.
        """
        cutoff_round = current_round - self._summarize_interval
        if cutoff_round <= 0:
            return False

        try:
            async with get_db() as db:
                cursor = await db.execute(
                    """SELECT id, memory_text, memory_type, salience_score, round_number
                       FROM agent_memories
                       WHERE session_id = ? AND agent_id = ? AND round_number <= ?
                         AND memory_type != 'summary'
                         AND salience_score < ?
                       ORDER BY round_number ASC""",
                    (session_id, agent_id, cutoff_round, self._summarize_salience_threshold),
                )
                old_memories = await cursor.fetchall()

            if len(old_memories) < _SUMMARIZE_MIN_MEMORIES:
                return False

            # Build input for LLM summarization
            memory_texts = [
                f"[第{r[4]}輪, {r[2]}, 重要度{float(r[3]):.2f}] {r[1]}"
                for r in old_memories
            ]
            input_text = "\n".join(memory_texts)

            response = await self._llm.chat(
                [
                    {"role": "system", "content": MEMORY_COMPRESSION_SYSTEM},
                    {"role": "user", "content": MEMORY_COMPRESSION_USER.format(
                        agent_id=agent_id,
                        memory_count=len(old_memories),
                        memories=input_text,
                    )},
                ],
                provider=get_agent_provider_model()[0],
                model=get_agent_provider_model()[1],
                max_tokens=512,
            )
            summary = response.content

            if not summary or not summary.strip():
                return False

            # Store summary as high-salience "summary" memory
            async with get_db() as db:
                await db.execute(
                    """INSERT INTO agent_memories
                        (session_id, agent_id, round_number, memory_text,
                         salience_score, memory_type, importance_score)
                    VALUES (?, ?, ?, ?, ?, 'summary', 0.8)""",
                    (session_id, agent_id, current_round, summary.strip(), _SUMMARY_SALIENCE),
                )

                # Delete originals from SQLite
                old_ids = [r[0] for r in old_memories]
                if not old_ids:
                    return False
                placeholders = ",".join("?" * len(old_ids))
                await db.execute(
                    f"DELETE FROM agent_memories WHERE id IN ({placeholders})",
                    old_ids,
                )
                await db.commit()

            # Delete from vector store too
            if self._vector_store:
                try:
                    old_ids = [r[0] for r in old_memories]
                    await self._vector_store.delete_by_ids(session_id, old_ids)
                except Exception:
                    logger.exception(
                        "vector_store delete failed during summarization session=%s",
                        session_id,
                    )

            logger.info(
                "Summarized %d memories → 1 summary for agent=%d session=%s round=%d",
                len(old_memories), agent_id, session_id, current_round,
            )
            return True

        except Exception:
            logger.exception(
                "summarize_old_memories failed session=%s agent=%d round=%d",
                session_id, agent_id, current_round,
            )
            return False

    async def _compress_if_needed(
        self,
        session_id: str,
        agent_id: int,
        current_round: int,
    ) -> bool:
        """Compress oldest memories into a summary node when count exceeds threshold.

        Best-effort: returns False on any error. Only compresses memories from
        rounds >= _COMPRESSION_MIN_ROUND_AGE ago to avoid destroying recent context.
        """
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    """
                    SELECT COUNT(*) FROM agent_memories
                    WHERE session_id = ? AND agent_id = ?
                      AND memory_type NOT IN ('summary', 'compressed_summary', 'thought')
                    """,
                    (session_id, agent_id),
                )
                row = await cursor.fetchone()
                count = row[0] if row else 0

            if count <= _COMPRESSION_THRESHOLD:
                return False

            cutoff_round = max(0, current_round - _COMPRESSION_MIN_ROUND_AGE)
            async with get_db() as db:
                cursor = await db.execute(
                    """
                    SELECT id, memory_text FROM agent_memories
                    WHERE session_id = ? AND agent_id = ?
                      AND memory_type NOT IN ('summary', 'compressed_summary', 'thought')
                      AND round_number <= ?
                    ORDER BY round_number ASC
                    LIMIT ?
                    """,
                    (session_id, agent_id, cutoff_round, _COMPRESSION_BATCH_SIZE),
                )
                rows = await cursor.fetchall()

            if not rows:
                return False

            ids_to_delete = [r[0] for r in rows]
            memory_texts = [r[1] for r in rows]

            provider, model = get_agent_provider_model()
            messages = [
                {"role": "system", "content": MEMORY_COMPRESSION_SYSTEM},
                {
                    "role": "user",
                    "content": MEMORY_COMPRESSION_USER.format(
                        agent_id=agent_id,
                        memory_count=len(memory_texts),
                        memories="\n".join(f"- {t}" for t in memory_texts),
                    ),
                },
            ]
            response = await self._llm.chat(messages, provider=provider, model=model)
            summary_text = response.content.strip()

            async with get_db() as db:
                await db.execute(
                    """
                    INSERT INTO agent_memories
                      (session_id, agent_id, round_number, memory_text,
                       salience_score, memory_type, importance_score)
                    VALUES (?, ?, ?, ?, ?, 'compressed_summary', 0.8)
                    """,
                    (session_id, agent_id, current_round, summary_text, 0.8),
                )
                placeholders = ",".join("?" * len(ids_to_delete))
                await db.execute(
                    f"DELETE FROM agent_memories WHERE id IN ({placeholders})",
                    ids_to_delete,
                )
                await db.commit()

            logger.debug(
                "Compressed %d memories → 1 summary for agent=%d session=%s",
                len(ids_to_delete), agent_id, session_id,
            )
            return True

        except Exception:
            logger.debug(
                "Memory compression skipped for agent=%d session=%s",
                agent_id, session_id, exc_info=True,
            )
            return False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _fetch_kg_subgraph(self, entity_ids: list[str]) -> dict:
        """Fetch KG nodes and their direct neighbours for the given entity IDs.

        Args:
            entity_ids: List of ``kg_nodes.id`` values to look up.

        Returns:
            Dict with keys ``"nodes"`` (list of node row dicts) and
            ``"edges"`` (list of edge row dicts for all direct connections).
        """
        from backend.app.utils.db import get_db  # noqa: PLC0415
        async with get_db() as db:
            db.row_factory = aiosqlite.Row
            placeholders = ",".join("?" * len(entity_ids))
            cursor = await db.execute(
                f"SELECT * FROM kg_nodes WHERE id IN ({placeholders})",
                entity_ids,
            )
            nodes = [dict(r) for r in await cursor.fetchall()]
            cursor = await db.execute(
                f"SELECT * FROM kg_edges"
                f" WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})",
                entity_ids + entity_ids,
            )
            edges = [dict(r) for r in await cursor.fetchall()]
        return {"nodes": nodes, "edges": edges}

    async def _get_recent_memories(
        self,
        session_id: str,
        agent_id: int,
        current_round: int,
        limit: int = 5,
    ) -> list[dict]:
        """Fetch most recent memories within lookback window."""
        min_round = max(0, current_round - _CONTEXT_ROUNDS_LOOKBACK)
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    """SELECT id, round_number, memory_text, salience_score, memory_type,
                              importance_score
                       FROM agent_memories
                       WHERE session_id = ? AND agent_id = ?
                         AND round_number >= ? AND salience_score >= ?
                       ORDER BY round_number DESC, salience_score DESC
                       LIMIT ?""",
                    (session_id, agent_id, min_round, _SALIENCE_PRUNE_THRESHOLD, limit),
                )
                rows = await cursor.fetchall()
                return [
                    {
                        "id": r[0],
                        "round_number": r[1],
                        "memory_text": r[2],
                        "salience_score": float(r[3]),
                        "memory_type": r[4],
                        "importance_score": float(r[5]),
                    }
                    for r in rows
                ]
        except Exception:
            logger.exception(
                "_get_recent_memories failed session=%s agent=%d", session_id, agent_id
            )
            return []

    def _format_memories(self, memories: list[dict], header: str) -> str:
        """Format memory dicts into a labelled context block."""
        if not memories:
            return ""
        lines = [f"【{header}】"]
        for m in memories:
            lines.append(
                MEMORY_CONTEXT_FORMAT.format(
                    round_number=m.get("round_number", 0),
                    memory_type=m.get("memory_type", "observation"),
                    salience=m.get("salience_score", 0.5),
                    memory_text=m.get("memory_text", ""),
                )
            )
        return "\n".join(lines)

    async def _get_kol_context(
        self,
        session_id: str,
        agent_id: int,
        current_round: int,
        top_k: int = 3,
    ) -> str:
        """Fetch latest posts from agent's most trusted KOLs."""
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    """SELECT ar.agent_b_id AS kol_id, ar.trust_score,
                              sa.content, sa.round_number
                       FROM agent_relationships ar
                       JOIN simulation_actions sa
                            ON sa.agent_id = ar.agent_b_id
                            AND sa.session_id = ar.session_id
                       WHERE ar.session_id = ? AND ar.agent_a_id = ?
                         AND ar.trust_score >= 0.5
                       ORDER BY ar.trust_score DESC, sa.round_number DESC
                       LIMIT ?""",
                    (session_id, agent_id, top_k),
                )
                rows = await cursor.fetchall()

            if not rows:
                return ""

            lines = ["【信任來源動態】"]
            for r in rows:
                lines.append(
                    f"[KOL#{r[0]}, 信任度{float(r[1]):.2f}, 第{r[3]}輪] {r[2][:100]}"
                )
            return "\n".join(lines)
        except Exception:
            logger.exception(
                "_get_kol_context failed session=%s agent=%d", session_id, agent_id
            )
            return ""

    async def _get_agent_context_sql(
        self,
        session_id: str,
        agent_id: int,
        current_round: int,
    ) -> str:
        """Original SQL-only context retrieval (salience + recency)."""
        min_round = max(0, current_round - _CONTEXT_ROUNDS_LOOKBACK)

        try:
            async with get_db() as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """
                    SELECT round_number, memory_text, salience_score, memory_type
                    FROM agent_memories
                    WHERE session_id = ?
                      AND agent_id = ?
                      AND round_number >= ?
                      AND salience_score >= ?
                    ORDER BY salience_score DESC, round_number DESC
                    LIMIT ?
                    """,
                    (session_id, agent_id, min_round,
                     _SALIENCE_PRUNE_THRESHOLD, _MAX_CONTEXT_MEMORIES),
                )
                rows = await cursor.fetchall()
        except Exception:
            logger.exception(
                "_get_agent_context_sql failed session=%s agent=%d",
                session_id, agent_id,
            )
            return ""

        if not rows:
            return ""

        memory_lines = [
            MEMORY_CONTEXT_FORMAT.format(
                round_number=r["round_number"],
                memory_type=r["memory_type"],
                salience=r["salience_score"],
                memory_text=r["memory_text"],
            )
            for r in rows
        ]

        return "\n".join(["【近期記憶】"] + memory_lines)

    async def _summarize_posts(
        self,
        username: str,
        posts: list[str],
        round_number: int,
    ) -> list[dict]:
        """Call LLM to summarize posts into memory records."""
        posts_text = "\n".join(
            f"[帖子 {i+1}] {p}" for i, p in enumerate(posts[:10])
        )

        messages = [
            {"role": "system", "content": MEMORY_SUMMARIZE_SYSTEM},
            {
                "role": "user",
                "content": MEMORY_SUMMARIZE_USER.format(
                    round_number=round_number,
                    username=username,
                    posts_text=posts_text,
                ),
            },
        ]

        try:
            data = await self._llm.chat_json(
                messages,
                provider=get_agent_provider_model()[0],
                temperature=0.4,
                max_tokens=4096,
            )
            return data.get("memories", [])
        except Exception:
            logger.exception(
                "_summarize_posts failed for user=%s round=%d", username, round_number
            )
            return []

    # ------------------------------------------------------------------
    # Batch salience evaluation
    # ------------------------------------------------------------------

    async def batch_evaluate_salience(
        self,
        agent_memories: list[dict],
        batch_size: int = 10,
    ) -> list[float]:
        """Evaluate salience for multiple agents in one LLM call per batch.

        Args:
            agent_memories: List of dicts with keys ``agent_id``, ``memory_text``,
                and optionally ``round``.
            batch_size: Number of memories to send per LLM request.

        Returns:
            List of salience scores (floats 0.0–1.0), aligned with input list.
        """
        all_scores: list[float] = []
        for i in range(0, len(agent_memories), batch_size):
            batch = agent_memories[i : i + batch_size]
            prompt = "\n".join(
                f"Agent {m['agent_id']}: {m['memory_text'][:200]}"
                for m in batch
            )
            try:
                result = await self._llm.chat_json(
                    [
                        {
                            "role": "system",
                            "content": (
                                "Rate the salience (0.0-1.0) of each agent's memory. "
                                'Return JSON: {"salience_scores": [0.8, 0.6, ...]}'
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    provider=get_agent_provider_model()[0],
                    model=get_agent_provider_model()[1],
                )
                scores = result.get("salience_scores", [0.5] * len(batch))
                # Guard: ensure correct count, values clamped to [0, 1]
                scores = [max(0.0, min(1.0, float(s))) for s in scores[: len(batch)]]
                if len(scores) < len(batch):
                    scores.extend([0.5] * (len(batch) - len(scores)))
            except Exception:
                logger.exception(
                    "batch_evaluate_salience LLM call failed for batch starting at %d", i
                )
                scores = [0.5] * len(batch)
            all_scores.extend(scores)
        return all_scores
