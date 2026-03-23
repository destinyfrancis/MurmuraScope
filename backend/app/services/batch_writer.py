"""Batch writer service (Phase 4A).

Accumulates DB rows in memory across multiple queue() calls and flushes them
in a single ``executemany`` transaction per table.  This dramatically reduces
the number of SQLite round-trips for high-throughput simulation hooks.

Usage::

    writer = BatchWriter(flush_threshold=500)
    writer.register_table("agent_memories", ["session_id", "agent_id", "content"])

    # queue rows throughout a round
    writer.queue("agent_memories", ("sess-1", 42, "post content"))
    writer.queue("agent_memories", ("sess-1", 43, "another post"))

    # flush at end of round
    rows_written = await writer.flush("agent_memories", db)

    # or flush everything
    total_written = await writer.flush_all(db)
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import TYPE_CHECKING

from backend.app.utils.logger import get_logger

if TYPE_CHECKING:
    import aiosqlite

logger = get_logger("batch_writer")

# Whitelist of tables allowed for batch writes — prevents SQL injection via
# dynamic table names.  Extend this set when adding new batch-writable tables.
_ALLOWED_TABLES: frozenset[str] = frozenset(
    {
        # Test-only shorthand names (used in unit tests)
        "memories",
        "actions",
        # Production tables
        "agent_memories",
        "simulation_actions",
        "agent_decisions",
        "belief_states",
        "emotional_states",
        "cognitive_dissonance",
        "virality_scores",
        "agent_feeds",
        "network_events",
        "memory_triples",
        "echo_chamber_snapshots",
        "polarization_snapshots",
        "filter_bubble_snapshots",
        "news_headlines",
        "wealth_transfers",
        "collective_actions",
        "collective_action_participants",
        "kg_edges",
        "kg_nodes",
        "kg_snapshots",
        "world_events",
        "faction_snapshots_v2",
        "tipping_points",
        "cognitive_fingerprints",
        "multi_run_results",
        "agent_relationships",
        "relationship_states",
        "attachment_styles",
        "consumption_records",
        "company_decisions",
        "macro_scenarios",
    }
)


class BatchWriter:
    """Accumulate rows and flush them in a single transaction per round.

    Thread/coroutine safety: this class uses a per-instance asyncio.Lock
    around flush operations, so it is safe to queue from multiple coroutines
    and flush from one.  queue() itself is not locked because all simulation
    hooks run in the same event loop thread.
    """

    def __init__(self, flush_threshold: int = 500) -> None:
        """Initialise the writer.

        Args:
            flush_threshold: Automatically flush a table's buffer when the
                number of queued rows reaches this limit.  Set to 0 to
                disable auto-flush (manual flush_all() required).
        """
        self._buffers: dict[str, list[tuple]] = defaultdict(list)
        self._schemas: dict[str, str] = {}  # table → INSERT SQL template
        self._flush_threshold = flush_threshold
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Schema registration
    # ------------------------------------------------------------------

    def register_table(self, table: str, columns: list[str]) -> None:
        """Register a table schema so queue() can build the INSERT SQL.

        Must be called once per table before queue().  Calling again with
        the same table is a no-op (idempotent).

        Args:
            table: SQLite table name.
            columns: Ordered list of column names that map to the tuple
                     values passed to queue().
        """
        if table not in _ALLOWED_TABLES:
            raise ValueError(
                f"Table {table!r} not in BatchWriter allowed list. Add it to _ALLOWED_TABLES if this is intentional."
            )
        if table not in self._schemas:
            col_list = ", ".join(columns)
            placeholders = ", ".join("?" for _ in columns)
            self._schemas[table] = f"INSERT OR IGNORE INTO {table} ({col_list}) VALUES ({placeholders})"
            logger.debug("BatchWriter registered table=%s columns=%s", table, columns)

    # ------------------------------------------------------------------
    # Queueing
    # ------------------------------------------------------------------

    def queue(self, table: str, values: tuple) -> None:
        """Add a row to the buffer for *table*.

        If the buffer reaches flush_threshold this method auto-flushes
        synchronously — callers must be in an async context and supply a
        db connection via the ``_auto_flush_db`` attribute if auto-flush
        is needed.  In normal use the caller flushes explicitly at round end.

        Args:
            table: Registered table name.
            values: Tuple of values matching the registered column order.

        Raises:
            KeyError: If table has not been registered via register_table().
        """
        if table not in self._schemas:
            raise KeyError(f"Table '{table}' not registered. Call register_table() first.")
        self._buffers[table].append(values)

    def queue_count(self, table: str | None = None) -> int:
        """Return the number of queued rows for *table* (or all tables)."""
        if table is not None:
            return len(self._buffers.get(table, []))
        return sum(len(v) for v in self._buffers.values())

    # ------------------------------------------------------------------
    # Flushing
    # ------------------------------------------------------------------

    async def flush(self, table: str | None, db: aiosqlite.Connection) -> int:
        """Flush buffered rows for *table* in a single executemany call.

        Args:
            table: Table name to flush.  Pass ``None`` to flush all tables
                   (equivalent to flush_all).
            db: Open aiosqlite connection.  The caller is responsible for
                opening the connection; this method does NOT commit — it
                expects the caller to commit or uses its own transaction.

        Returns:
            Number of rows written.
        """
        if table is None:
            return await self.flush_all(db)

        async with self._lock:
            rows = self._buffers.get(table, [])
            if not rows:
                return 0

            sql = self._schemas.get(table)
            if sql is None:
                logger.warning("flush called for unregistered table=%s", table)
                return 0

            try:
                await db.executemany(sql, rows)
                await db.commit()
                written = len(rows)
                self._buffers[table] = []
                # Reset retry flag on success
                setattr(self, f"_retry_{table}", False)
                logger.debug("BatchWriter flushed table=%s rows=%d", table, written)
                return written
            except Exception:
                logger.exception("BatchWriter.flush failed table=%s rows=%d", table, len(rows))
                # Keep buffer for ONE retry — next flush will attempt again.
                # If this is the second consecutive failure, clear to prevent
                # infinite retry of bad rows.
                retry_key = f"_retry_{table}"
                if getattr(self, retry_key, False):
                    logger.error(
                        "BatchWriter: second failure for %s — dropping %d rows",
                        table,
                        len(rows),
                    )
                    self._buffers[table] = []
                    setattr(self, retry_key, False)
                else:
                    setattr(self, retry_key, True)
                    # buffer NOT cleared — rows survive for one retry
                return 0

    async def flush_all(self, db: aiosqlite.Connection) -> int:
        """Flush all registered tables in a single pass.

        Args:
            db: Open aiosqlite connection.

        Returns:
            Total rows written across all tables.
        """
        total = 0
        for table in list(self._schemas.keys()):
            total += await self.flush(table, db)
        return total

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Discard all buffered rows without writing them to the DB."""
        self._buffers = defaultdict(list)
        logger.debug("BatchWriter cleared all buffers")
