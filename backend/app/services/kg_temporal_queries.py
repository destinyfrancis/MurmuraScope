"""Temporal KG query helpers — Graphiti-style validity windows.

kg_edges rows have valid_from (round created) and valid_until (round dissolved,
NULL = still active). These helpers let callers query the graph at any point in
simulation history without relying on periodic full-graph snapshots.
"""

from __future__ import annotations

from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("kg_temporal")


async def get_kg_edges_at_round(session_id: str, round_number: int) -> list[dict]:
    """Return all KG edges that were active at *round_number*.

    An edge is active when:
        valid_from <= round_number AND (valid_until IS NULL OR valid_until > round_number)
    """
    async with get_db() as db:
        db.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
        cursor = await db.execute(
            """
            SELECT e.id, e.source_id, e.target_id, e.relation_type,
                   e.description, e.weight, e.round_number,
                   e.valid_from, e.valid_until
            FROM kg_edges e
            WHERE e.session_id = ?
              AND e.valid_from <= ?
              AND (e.valid_until IS NULL OR e.valid_until > ?)
            ORDER BY e.valid_from
            """,
            (session_id, round_number, round_number),
        )
        return await cursor.fetchall()


async def get_edge_history(session_id: str, source_id: str, target_id: str) -> list[dict]:
    """Return all versions of the edge between two nodes across simulation history."""
    async with get_db() as db:
        db.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
        cursor = await db.execute(
            """
            SELECT id, source_id, target_id, relation_type, description,
                   weight, round_number, valid_from, valid_until
            FROM kg_edges
            WHERE session_id = ? AND source_id = ? AND target_id = ?
            ORDER BY valid_from
            """,
            (session_id, source_id, target_id),
        )
        return await cursor.fetchall()


async def get_kg_diff(session_id: str, round_a: int, round_b: int) -> dict[str, list[dict]]:
    """Return edges added and removed between round_a and round_b.

    Returns {"added": [...], "removed": [...]}
    """
    async with get_db() as db:
        db.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))

        # Edges that started existing between round_a and round_b (exclusive of round_a)
        cur_added = await db.execute(
            """
            SELECT id, source_id, target_id, relation_type, description,
                   weight, valid_from, valid_until
            FROM kg_edges
            WHERE session_id = ?
              AND valid_from > ?
              AND valid_from <= ?
            ORDER BY valid_from
            """,
            (session_id, round_a, round_b),
        )
        added = await cur_added.fetchall()

        # Edges dissolved between round_a and round_b
        cur_removed = await db.execute(
            """
            SELECT id, source_id, target_id, relation_type, description,
                   weight, valid_from, valid_until
            FROM kg_edges
            WHERE session_id = ?
              AND valid_until IS NOT NULL
              AND valid_until > ?
              AND valid_until <= ?
            ORDER BY valid_until
            """,
            (session_id, round_a, round_b),
        )
        removed = await cur_removed.fetchall()

    return {"added": added, "removed": removed}
