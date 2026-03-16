"""LanceDB-backed vector store for agent semantic memory.

Each simulation session gets its own LanceDB table (`mem_{session_id[:12]}`).
Provides add / search / delete / salience-sync operations.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from backend.app.services.embedding_provider import EmbeddingProvider
from backend.app.utils.logger import get_logger

logger = get_logger("vector_store")

_DEFAULT_DB_PATH = "data/vector_store"


@dataclass(frozen=True)
class VectorSearchResult:
    """Immutable search result from a vector similarity query."""

    memory_id: int
    similarity_score: float
    memory_text: str
    round_number: int
    salience_score: float
    memory_type: str


class VectorStore:
    """LanceDB wrapper for per-session agent memory vectors."""

    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        self._db_path = Path(db_path)
        self._db_path.mkdir(parents=True, exist_ok=True)
        self._embedder = EmbeddingProvider()
        self._db: Any | None = None

    def _get_db(self) -> Any:
        """Lazily open the LanceDB database connection."""
        if self._db is not None:
            return self._db

        import lancedb  # noqa: PLC0415

        self._db = lancedb.connect(str(self._db_path))
        return self._db

    def _table_name(self, session_id: str) -> str:
        """Deterministic table name for a session."""
        safe = session_id.replace("-", "")[:12]
        return f"mem_{safe}"

    async def close(self) -> None:
        """Release the LanceDB connection to free resources."""
        self._db = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def add_memories(
        self,
        session_id: str,
        memories: list[dict[str, Any]],
    ) -> int:
        """Embed and upsert memory records into the session table.

        Each dict in *memories* must contain:
            memory_id, agent_id, round_number, memory_text, memory_type, salience_score

        Returns:
            Number of records upserted.
        """
        if not memories:
            return 0

        texts = [m["memory_text"] for m in memories]
        vectors = await asyncio.to_thread(self._embedder.embed, texts)

        records = []
        for mem, vec in zip(memories, vectors):
            records.append({
                "memory_id": int(mem["memory_id"]),
                "session_id": session_id,
                "agent_id": int(mem["agent_id"]),
                "round_number": int(mem["round_number"]),
                "memory_text": mem["memory_text"],
                "memory_type": mem.get("memory_type", "observation"),
                "salience_score": float(mem.get("salience_score", 0.5)),
                "vector": vec.tolist(),
            })

        def _upsert() -> int:
            db = self._get_db()
            table_name = self._table_name(session_id)
            try:
                tbl = db.open_table(table_name)
                tbl.add(records)
            except Exception:
                # Table doesn't exist yet — create it
                db.create_table(table_name, records)
            return len(records)

        count = await asyncio.to_thread(_upsert)
        logger.debug(
            "add_memories session=%s count=%d", session_id, count,
        )
        return count

    async def search(
        self,
        session_id: str,
        query_text: str,
        agent_id: int | None = None,
        top_k: int = 10,
    ) -> list[VectorSearchResult]:
        """Semantic similarity search over a session's memory vectors.

        Args:
            session_id: Session UUID.
            query_text: Natural-language query to embed.
            agent_id: Optional filter to restrict to one agent.
            top_k: Max results.

        Returns:
            List of VectorSearchResult ordered by descending similarity.
        """
        query_vec = await asyncio.to_thread(
            self._embedder.embed_single, query_text,
        )

        def _search() -> list[VectorSearchResult]:
            db = self._get_db()
            table_name = self._table_name(session_id)
            try:
                tbl = db.open_table(table_name)
            except Exception:
                logger.warning("search: table %s not found", table_name)
                return []

            q = tbl.search(query_vec.tolist()).limit(top_k * 3 if agent_id else top_k)

            try:
                results_df = q.to_pandas()
            except Exception:
                logger.exception("search to_pandas failed table=%s", table_name)
                return []

            if results_df.empty:
                return []

            # Filter by agent_id if requested
            if agent_id is not None:
                results_df = results_df[results_df["agent_id"] == agent_id]

            # LanceDB returns _distance (L2) by default; convert to similarity
            if "_distance" in results_df.columns:
                # For normalized vectors, cosine similarity ≈ 1 - (L2² / 2)
                results_df = results_df.assign(
                    similarity=1.0 - results_df["_distance"] / 2.0,
                )
            else:
                results_df = results_df.assign(similarity=0.5)

            results_df = results_df.head(top_k)

            out: list[VectorSearchResult] = []
            for _, row in results_df.iterrows():
                out.append(VectorSearchResult(
                    memory_id=int(row["memory_id"]),
                    similarity_score=float(row["similarity"]),
                    memory_text=str(row["memory_text"]),
                    round_number=int(row["round_number"]),
                    salience_score=float(row["salience_score"]),
                    memory_type=str(row["memory_type"]),
                ))
            return out

        return await asyncio.to_thread(_search)

    async def delete_session(self, session_id: str) -> bool:
        """Drop the entire LanceDB table for a session.

        Returns:
            True if the table was deleted, False if it didn't exist.
        """

        def _drop() -> bool:
            db = self._get_db()
            table_name = self._table_name(session_id)
            try:
                db.drop_table(table_name)
                return True
            except Exception:
                return False

        deleted = await asyncio.to_thread(_drop)
        if deleted:
            logger.info("delete_session: dropped table for %s", session_id)
        return deleted

    async def update_salience(
        self,
        session_id: str,
        decay_factor: float = 0.85,
    ) -> int:
        """Sync salience decay: multiply all salience_score by *decay_factor*.

        Returns:
            Number of records updated.
        """

        def _decay() -> int:
            db = self._get_db()
            table_name = self._table_name(session_id)
            try:
                tbl = db.open_table(table_name)
            except Exception:
                return 0

            try:
                df = tbl.to_pandas()
            except Exception:
                return 0

            if df.empty:
                return 0

            df = df.assign(salience_score=df["salience_score"] * decay_factor)
            # Overwrite table with updated data
            db.drop_table(table_name)
            db.create_table(table_name, df.to_dict("records"))
            return len(df)

        count = await asyncio.to_thread(_decay)
        logger.debug(
            "update_salience session=%s factor=%.2f updated=%d",
            session_id, decay_factor, count,
        )
        return count
