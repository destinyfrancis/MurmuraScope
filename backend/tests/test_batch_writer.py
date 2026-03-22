"""Tests for BatchWriter service (Phase 4A).

~15 tests covering:
- register_table
- queue + flush writes correct rows
- auto-flush threshold
- flush_all with multiple tables
- clear empties buffers
- empty flush returns 0
- unregistered table raises KeyError
"""

from __future__ import annotations

import pytest
import pytest_asyncio
import aiosqlite


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def mem_db():
    """In-memory SQLite connection with two test tables."""
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    await db.execute(
        "CREATE TABLE memories (session_id TEXT, agent_id INTEGER, content TEXT)"
    )
    await db.execute(
        "CREATE TABLE actions (session_id TEXT, round_num INTEGER, msg TEXT)"
    )
    await db.commit()
    yield db
    await db.close()


# ---------------------------------------------------------------------------
# Basic registration & queue tests
# ---------------------------------------------------------------------------


def test_register_table_creates_schema():
    from backend.app.services.batch_writer import BatchWriter

    w = BatchWriter()
    w.register_table("memories", ["session_id", "agent_id", "content"])
    # Schema is stored internally
    assert "memories" in w._schemas
    assert "INSERT" in w._schemas["memories"]


def test_register_table_idempotent():
    from backend.app.services.batch_writer import BatchWriter

    w = BatchWriter()
    w.register_table("memories", ["session_id", "agent_id", "content"])
    first_sql = w._schemas["memories"]
    # Second call with same table should not overwrite
    w.register_table("memories", ["different", "columns"])
    assert w._schemas["memories"] == first_sql


def test_queue_adds_row():
    from backend.app.services.batch_writer import BatchWriter

    w = BatchWriter()
    w.register_table("memories", ["session_id", "agent_id", "content"])
    w.queue("memories", ("sess-1", 42, "hello"))
    assert w.queue_count("memories") == 1


def test_queue_multiple_rows():
    from backend.app.services.batch_writer import BatchWriter

    w = BatchWriter()
    w.register_table("memories", ["session_id", "agent_id", "content"])
    for i in range(5):
        w.queue("memories", ("sess-1", i, f"content-{i}"))
    assert w.queue_count("memories") == 5


def test_queue_unregistered_raises():
    from backend.app.services.batch_writer import BatchWriter

    w = BatchWriter()
    with pytest.raises(KeyError, match="not registered"):
        w.queue("nonexistent_table", ("a", "b"))


def test_queue_count_all_tables():
    from backend.app.services.batch_writer import BatchWriter

    w = BatchWriter()
    w.register_table("memories", ["session_id", "agent_id", "content"])
    w.register_table("actions", ["session_id", "round_num", "msg"])
    w.queue("memories", ("sess-1", 1, "hello"))
    w.queue("actions", ("sess-1", 1, "post"))
    w.queue("actions", ("sess-1", 2, "like"))
    assert w.queue_count() == 3


# ---------------------------------------------------------------------------
# Flush tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flush_writes_rows(mem_db):
    from backend.app.services.batch_writer import BatchWriter

    w = BatchWriter()
    w.register_table("memories", ["session_id", "agent_id", "content"])
    w.queue("memories", ("sess-1", 42, "hello"))
    w.queue("memories", ("sess-1", 43, "world"))

    written = await w.flush("memories", mem_db)
    assert written == 2

    cursor = await mem_db.execute("SELECT COUNT(*) FROM memories")
    row = await cursor.fetchone()
    assert row[0] == 2


@pytest.mark.asyncio
async def test_flush_clears_buffer(mem_db):
    from backend.app.services.batch_writer import BatchWriter

    w = BatchWriter()
    w.register_table("memories", ["session_id", "agent_id", "content"])
    w.queue("memories", ("sess-1", 1, "a"))

    await w.flush("memories", mem_db)
    assert w.queue_count("memories") == 0


@pytest.mark.asyncio
async def test_flush_empty_returns_zero(mem_db):
    from backend.app.services.batch_writer import BatchWriter

    w = BatchWriter()
    w.register_table("memories", ["session_id", "agent_id", "content"])
    written = await w.flush("memories", mem_db)
    assert written == 0


@pytest.mark.asyncio
async def test_flush_none_flushes_all(mem_db):
    from backend.app.services.batch_writer import BatchWriter

    w = BatchWriter()
    w.register_table("memories", ["session_id", "agent_id", "content"])
    w.register_table("actions", ["session_id", "round_num", "msg"])
    w.queue("memories", ("sess-1", 1, "mem"))
    w.queue("actions", ("sess-1", 1, "act"))

    total = await w.flush(None, mem_db)
    assert total == 2
    assert w.queue_count() == 0


@pytest.mark.asyncio
async def test_flush_all_multiple_tables(mem_db):
    from backend.app.services.batch_writer import BatchWriter

    w = BatchWriter()
    w.register_table("memories", ["session_id", "agent_id", "content"])
    w.register_table("actions", ["session_id", "round_num", "msg"])

    for i in range(3):
        w.queue("memories", ("sess", i, "m"))
    for i in range(2):
        w.queue("actions", ("sess", i, "a"))

    total = await w.flush_all(mem_db)
    assert total == 5

    c1 = await mem_db.execute("SELECT COUNT(*) FROM memories")
    c2 = await mem_db.execute("SELECT COUNT(*) FROM actions")
    assert (await c1.fetchone())[0] == 3
    assert (await c2.fetchone())[0] == 2


@pytest.mark.asyncio
async def test_flush_failure_preserves_buffer_for_one_retry(mem_db):
    """If flush fails, buffer should survive for one retry before clearing.

    Bug: current code clears buffer on ANY failure, losing all rows permanently.
    Fix: keep buffer on FIRST failure (retry_key unset), clear on SECOND failure.
    """
    from unittest.mock import AsyncMock, patch
    from backend.app.services.batch_writer import BatchWriter

    writer = BatchWriter()
    writer.register_table("memories", ["session_id", "agent_id", "content"])
    writer.queue("memories", ("s1", 1, "text"))

    mock_db = AsyncMock()
    mock_db.executemany = AsyncMock(side_effect=Exception("SQLITE_BUSY"))
    mock_db.commit = AsyncMock()

    # First flush fails — buffer must survive for retry
    result = await writer.flush("memories", mock_db)
    assert result == 0
    assert writer.queue_count("memories") == 1, (
        "Buffer cleared on first failure — rows lost permanently (bug)"
    )

    # Second flush succeeds (simulate recovery)
    mock_db.executemany = AsyncMock(return_value=None)
    mock_db.executemany.side_effect = None
    result = await writer.flush("memories", mock_db)
    assert result == 1
    assert writer.queue_count("memories") == 0


# ---------------------------------------------------------------------------
# Clear tests
# ---------------------------------------------------------------------------


def test_clear_empties_buffers():
    from backend.app.services.batch_writer import BatchWriter

    w = BatchWriter()
    w.register_table("memories", ["session_id", "agent_id", "content"])
    w.queue("memories", ("sess-1", 1, "x"))
    assert w.queue_count("memories") == 1

    w.clear()
    assert w.queue_count("memories") == 0
    assert w.queue_count() == 0


def test_clear_does_not_remove_schemas():
    from backend.app.services.batch_writer import BatchWriter

    w = BatchWriter()
    w.register_table("memories", ["session_id", "agent_id", "content"])
    w.clear()
    # Schema should still be registered after clear
    assert "memories" in w._schemas


@pytest.mark.asyncio
async def test_flush_after_clear_returns_zero(mem_db):
    from backend.app.services.batch_writer import BatchWriter

    w = BatchWriter()
    w.register_table("memories", ["session_id", "agent_id", "content"])
    w.queue("memories", ("sess-1", 1, "x"))
    w.clear()

    written = await w.flush("memories", mem_db)
    assert written == 0
