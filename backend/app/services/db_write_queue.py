"""
SQLite Write Queue — serializes all write operations through a single asyncio queue
to prevent "database is locked" errors under concurrent load.

Read operations continue using the existing get_db() pattern (SQLite WAL allows
concurrent reads from multiple connections simultaneously).

Usage::

    from backend.app.services.db_write_queue import get_write_queue

    queue = await get_write_queue()
    result = await queue.execute(
        "INSERT INTO agent_profiles (session_id, name) VALUES (?, ?)",
        params=(session_id, name),
        session_id=session_id,
    )
    if not result.success:
        raise RuntimeError(f"DB write failed: {result.error}")
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Immutable data transfer objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WriteRequest:
    """Immutable write request submitted to the queue."""

    sql: str
    params: tuple[Any, ...] = ()
    session_id: str | None = None
    created_at: float = field(default_factory=time.monotonic)


@dataclass(frozen=True)
class WriteResult:
    """Immutable result returned after a write completes."""

    success: bool
    rowcount: int = 0
    lastrowid: int | None = None
    error: str | None = None
    latency_ms: float = 0.0


# ---------------------------------------------------------------------------
# Core queue implementation
# ---------------------------------------------------------------------------


class WriteQueue:
    """Serializes SQLite write operations through a single asyncio queue.

    A single long-lived aiosqlite connection is held by the background worker.
    All callers submit requests via ``execute()`` / ``execute_many()`` and
    await an ``asyncio.Future`` that is resolved when the worker finishes.

    Thread-safety: the queue is an asyncio.Queue so it is coroutine-safe.
    Do not share a WriteQueue across threads without an explicit event-loop bridge.
    """

    def __init__(self, db_path: str, max_queue_size: int = 10_000) -> None:
        self._db_path = db_path
        self._queue: asyncio.Queue[
            tuple[WriteRequest, bool, asyncio.Future[WriteResult]]
        ] = asyncio.Queue(maxsize=max_queue_size)
        self._worker_task: asyncio.Task[None] | None = None
        self._running = False
        self._metrics: dict[str, float] = {
            "total_writes": 0.0,
            "total_errors": 0.0,
            "total_latency_ms": 0.0,
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background write worker."""
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._worker(), name="db-write-queue-worker")
        logger.info("WriteQueue started for %s", self._db_path)

    async def stop(self) -> None:
        """Stop the write worker gracefully, logging final metrics."""
        self._running = False
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
        logger.info(
            "WriteQueue stopped. writes=%d errors=%d avg_latency_ms=%.1f",
            int(self._metrics["total_writes"]),
            int(self._metrics["total_errors"]),
            (
                self._metrics["total_latency_ms"] / self._metrics["total_writes"]
                if self._metrics["total_writes"] > 0
                else 0.0
            ),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(
        self,
        sql: str,
        params: tuple[Any, ...] = (),
        session_id: str | None = None,
    ) -> WriteResult:
        """Submit a single write operation and wait for its result.

        Args:
            sql: Parameterised SQL statement (INSERT / UPDATE / DELETE).
            params: Positional bind parameters for the statement.
            session_id: Optional session tag used in error logs for tracing.

        Returns:
            WriteResult with success flag, affected row count, last insert id,
            and wall-clock latency.
        """
        request = WriteRequest(sql=sql, params=params, session_id=session_id)
        future: asyncio.Future[WriteResult] = asyncio.get_event_loop().create_future()
        await self._queue.put((request, False, future))
        return await future

    async def execute_many(
        self,
        sql: str,
        params_list: list[tuple[Any, ...]],
        session_id: str | None = None,
    ) -> WriteResult:
        """Submit a batch write (executemany) and wait for its result.

        Args:
            sql: Parameterised SQL statement applied to every row in params_list.
            params_list: List of parameter tuples, one per row.
            session_id: Optional session tag for error tracing.

        Returns:
            WriteResult representing the overall batch outcome.
        """
        # Encode params_list as the params field using a sentinel flag (is_many=True)
        request = WriteRequest(
            sql=sql,
            params=tuple(params_list),  # type: ignore[arg-type]
            session_id=session_id,
        )
        future: asyncio.Future[WriteResult] = asyncio.get_event_loop().create_future()
        await self._queue.put((request, True, future))
        return await future

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def queue_depth(self) -> int:
        """Number of pending write requests not yet processed."""
        return self._queue.qsize()

    @property
    def metrics(self) -> dict[str, float]:
        """Snapshot of accumulated performance metrics (immutable copy)."""
        return dict(self._metrics)

    # ------------------------------------------------------------------
    # Background worker
    # ------------------------------------------------------------------

    async def _worker(self) -> None:
        """Process write requests sequentially on a single DB connection."""
        import aiosqlite

        async with aiosqlite.connect(self._db_path) as db:
            # Mirror the WAL tuning from get_db() so writes benefit from
            # the same performance settings.
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute("PRAGMA journal_size_limit = 67108864")
            await db.execute("PRAGMA wal_autocheckpoint = 2000")
            await db.execute("PRAGMA cache_size = -65536")
            await db.execute("PRAGMA mmap_size = 268435456")
            await db.execute("PRAGMA busy_timeout = 5000")

            while self._running:
                try:
                    request, is_many, future = await asyncio.wait_for(
                        self._queue.get(), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    break

                result = await self._execute_one(db, request, is_many)

                if not future.done():
                    future.set_result(result)

    async def _execute_one(
        self,
        db: Any,
        request: WriteRequest,
        is_many: bool,
    ) -> WriteResult:
        """Execute a single request against an open aiosqlite connection."""
        start = time.monotonic()
        try:
            if is_many:
                cursor = await db.executemany(request.sql, request.params)
            else:
                cursor = await db.execute(request.sql, request.params)
            await db.commit()

            latency = (time.monotonic() - start) * 1000.0
            self._metrics["total_writes"] += 1
            self._metrics["total_latency_ms"] += latency

            return WriteResult(
                success=True,
                rowcount=cursor.rowcount,
                lastrowid=cursor.lastrowid,
                latency_ms=latency,
            )

        except Exception as exc:
            latency = (time.monotonic() - start) * 1000.0
            self._metrics["total_errors"] += 1

            logger.error(
                "WriteQueue write error (session=%s): %s | sql=%.120s",
                request.session_id or "n/a",
                exc,
                request.sql,
            )
            return WriteResult(
                success=False,
                error=str(exc),
                latency_ms=latency,
            )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_write_queue: WriteQueue | None = None


async def get_write_queue() -> WriteQueue:
    """Return the global WriteQueue singleton, creating and starting it if needed.

    The singleton is initialised lazily from ``settings.DATABASE_PATH`` so it
    works correctly whether called at startup or from an individual service.
    """
    global _write_queue  # noqa: PLW0603
    if _write_queue is None:
        from backend.app.config import get_settings

        settings = get_settings()
        _write_queue = WriteQueue(db_path=str(settings.DATABASE_PATH))
        await _write_queue.start()
    return _write_queue


async def shutdown_write_queue() -> None:
    """Gracefully stop the global WriteQueue singleton.

    Call this from the FastAPI lifespan shutdown handler.
    """
    global _write_queue  # noqa: PLW0603
    if _write_queue is not None:
        await _write_queue.stop()
        _write_queue = None
