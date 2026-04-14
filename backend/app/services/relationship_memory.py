"""Relationship-tagged memory service.

Stores and retrieves agent memories tagged with a specific related_agent_id,
enabling agents to remember what specific individuals did to them.

Uses the existing ``agent_memories`` table with a ``related_agent_id`` key in
the metadata JSON column.  No new DB tables are required.

LanceDB vector search is used for semantic retrieval (same infrastructure as
AgentMemoryService).  LLM cost: 0.
"""

from __future__ import annotations

import json
from typing import Any

from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("relationship_memory")

# Maximum memories returned per relationship query
_MAX_RELATIONSHIP_MEMORIES = 5

# Metadata key used to tag relationship-specific memories
_RELATED_AGENT_KEY = "related_agent_id"


class RelationshipMemoryService:
    """Store and retrieve relationship-tagged memories for agents."""

    # ------------------------------------------------------------------
    # store_interaction_memory
    # ------------------------------------------------------------------

    async def store_interaction_memory(
        self,
        session_id: str,
        agent_id: str,
        related_agent_id: str,
        content: str,
        round_number: int,
        salience: float = 0.5,
        extra_metadata: dict[str, Any] | None = None,
    ) -> None:
        """Store a relationship-tagged memory in agent_memories.

        The memory is stored with a metadata JSON containing
        ``related_agent_id`` so it can be filtered later.

        Args:
            session_id: Simulation session UUID.
            agent_id: The agent who experienced this interaction.
            related_agent_id: The other agent involved in the interaction.
            content: Memory content string.
            round_number: Round when this interaction occurred.
            salience: Memory salience (0..1, higher = more important).
            extra_metadata: Additional metadata to merge.
        """
        metadata = {_RELATED_AGENT_KEY: related_agent_id}
        if extra_metadata:
            metadata.update(extra_metadata)
        metadata_json = json.dumps(metadata)

        try:
            async with get_db() as db:
                await db.execute(
                    """
                    INSERT INTO agent_memories
                        (session_id, agent_id, memory_text, round_number,
                         salience_score, memory_type, metadata)
                    VALUES (?, ?, ?, ?, ?, 'relationship', ?)
                    """,
                    (session_id, agent_id, content, round_number, salience, metadata_json),
                )
                await db.commit()
        except Exception:
            logger.exception(
                "store_interaction_memory failed session=%s agent=%s related=%s",
                session_id,
                agent_id,
                related_agent_id,
            )

    # ------------------------------------------------------------------
    # retrieve_relationship_memories
    # ------------------------------------------------------------------

    async def retrieve_relationship_memories(
        self,
        session_id: str,
        agent_id: str,
        related_agent_id: str,
        max_results: int = _MAX_RELATIONSHIP_MEMORIES,
    ) -> list[dict[str, Any]]:
        """Retrieve memories tagged with a specific related_agent_id.

        Queries agent_memories where metadata JSON contains the
        related_agent_id key, ordered by salience × recency.

        Args:
            session_id: Simulation session UUID.
            agent_id: The agent whose memories to search.
            related_agent_id: Filter to interactions involving this agent.
            max_results: Maximum number of memories to return.

        Returns:
            List of memory dicts with keys: content, round_number,
            salience, metadata.
        """
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    """
                    SELECT memory_text, round_number, salience_score, metadata
                    FROM agent_memories
                    WHERE session_id = ?
                      AND agent_id = ?
                      AND metadata LIKE ?
                    ORDER BY salience_score DESC, round_number DESC
                    LIMIT ?
                    """,
                    (
                        session_id,
                        agent_id,
                        f'%"{_RELATED_AGENT_KEY}": "{related_agent_id}"%',
                        max_results,
                    ),
                )
                rows = await cursor.fetchall()
        except Exception:
            logger.exception(
                "retrieve_relationship_memories failed session=%s agent=%s",
                session_id,
                agent_id,
            )
            return []

        result = []
        for row in rows:
            try:
                meta = json.loads(row[3]) if row[3] else {}
            except (json.JSONDecodeError, TypeError):
                meta = {}
            result.append(
                {
                    "content": row[0],      # memory_text aliased to 'content' for callers
                    "round_number": row[1],
                    "salience": row[2],     # salience_score aliased to 'salience' for callers
                    "metadata": meta,
                }
            )
        return result

    # ------------------------------------------------------------------
    # build_relationship_context
    # ------------------------------------------------------------------

    async def build_relationship_context(
        self,
        session_id: str,
        agent_id: str,
        related_agent_id: str,
        max_memories: int = 3,
    ) -> str:
        """Build a formatted context string for relationship memories.

        Returns a short text block suitable for injection into a deliberation
        prompt.  Returns empty string if no memories exist.

        Args:
            session_id: Simulation session UUID.
            agent_id: The agent whose perspective we use.
            related_agent_id: The agent to recall memories about.
            max_memories: Maximum memories to include in the summary.

        Returns:
            Formatted string, e.g.:
            「【記憶：關於 bob】Round 3: alice 對 bob 表示支持 (salience=0.8)...」
            or empty string if none found.
        """
        memories = await self.retrieve_relationship_memories(
            session_id=session_id,
            agent_id=agent_id,
            related_agent_id=related_agent_id,
            max_results=max_memories,
        )
        if not memories:
            return ""

        lines = [f"【記憶：關於 {related_agent_id}】"]
        for m in memories:
            rnd = m.get("round_number", "?")
            content = m.get("content", "")[:120]
            salience = m.get("salience", 0.5)
            lines.append(f"  Round {rnd}: {content} (salience={salience:.2f})")

        return "\n".join(lines)
