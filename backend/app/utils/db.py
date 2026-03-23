"""Async SQLite connection manager using aiosqlite with WAL mode."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from backend.app.config import get_settings
from backend.app.utils.logger import get_logger

logger = get_logger("db")


@asynccontextmanager
async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    """Yield an async SQLite connection with WAL mode and foreign keys enabled.

    Usage::

        async with get_db() as db:
            await db.execute("SELECT 1")
    """
    settings = get_settings()
    db_path = Path(settings.DATABASE_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    db = await aiosqlite.connect(str(db_path))
    try:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
        # Phase 4A: WAL performance tuning for large-scale simulations.
        # journal_size_limit: cap WAL file at 64 MB (prevents unbounded growth).
        # wal_autocheckpoint: checkpoint every 2000 pages (~8 MB) instead of 1000.
        # cache_size: use 64 MB page cache (-N means kibibytes in SQLite).
        # mmap_size: memory-map up to 256 MB of the database file for faster reads.
        await db.execute("PRAGMA journal_size_limit = 67108864")
        await db.execute("PRAGMA wal_autocheckpoint = 2000")
        await db.execute("PRAGMA cache_size = -65536")
        await db.execute("PRAGMA mmap_size = 268435456")
        # Prevent SQLITE_BUSY under concurrent async writes: wait up to 5s before
        # raising an error when another connection holds a write lock.
        await db.execute("PRAGMA busy_timeout = 5000")
        db.row_factory = aiosqlite.Row
        yield db
    finally:
        await db.close()


async def init_db() -> None:
    """Initialise the database by executing schema.sql.

    Reads the schema file and executes it within a single connection.
    Safe to call multiple times (uses CREATE TABLE IF NOT EXISTS).
    """
    settings = get_settings()
    schema_file = Path(settings.schema_path)

    if not schema_file.exists():
        logger.error("schema.sql not found at %s", schema_file)
        raise FileNotFoundError(f"schema.sql not found at {schema_file}")

    schema_sql = schema_file.read_text(encoding="utf-8")
    logger.info("Initialising database at %s", settings.DATABASE_PATH)

    async with get_db() as db:
        await db.executescript(schema_sql)
        await db.commit()

    logger.info("Database initialised successfully")


async def apply_migrations() -> None:
    """Apply ALTER TABLE migrations for columns added after initial schema.

    Uses try/except to guard against 'duplicate column name' on existing DBs,
    matching the existing pattern used for political_stance and other late columns.
    Safe to call multiple times.
    """
    migrations = [
        "ALTER TABLE agent_profiles ADD COLUMN tier INTEGER DEFAULT 2",
        "ALTER TABLE agent_profiles ADD COLUMN political_stance REAL DEFAULT 0.5",
        "ALTER TABLE kg_edges ADD COLUMN round_number INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE agent_decisions ADD COLUMN topic_tags TEXT",
        "ALTER TABLE agent_decisions ADD COLUMN emotional_reaction TEXT",
        "ALTER TABLE agent_memories ADD COLUMN importance_score REAL DEFAULT 0.5",
        "ALTER TABLE agent_memories ADD COLUMN metadata TEXT DEFAULT NULL",
    ]
    # Idempotent index creation — CREATE INDEX IF NOT EXISTS is always safe
    index_migrations = [
        # Composite index for recursive CTE in get_relational_context()
        "CREATE INDEX IF NOT EXISTS idx_triple_search ON memory_triples(session_id, agent_id, subject, object)",
    ]
    async with get_db() as db:
        for sql in migrations:
            try:
                await db.execute(sql)
                await db.commit()
            except Exception as exc:
                if "duplicate column name" not in str(exc).lower():
                    logger.warning("Migration skipped with unexpected error: %s — sql: %s", exc, sql)
        for sql in index_migrations:
            try:
                await db.execute(sql)
                await db.commit()
            except Exception as e:
                err_msg = str(e).lower()
                if "already exists" in err_msg:
                    pass  # expected on repeated startup
                else:
                    logger.warning("Index migration warning: %s | SQL: %s", e, sql[:100])
    logger.info("DB migrations applied")


@asynccontextmanager
async def get_workspace_db(workspace_id: str | None) -> AsyncIterator[aiosqlite.Connection]:
    """Get a database connection for a workspace-scoped database.

    Each workspace has its own SQLite file at:
        data/workspaces/{workspace_id}/murmuroscope.db

    This gives true write isolation between workspaces — no concurrent write
    contention between tenants.  Falls back to the global database when
    workspace_id is None.

    Usage::

        async with get_workspace_db(workspace_id) as db:
            await db.execute("SELECT 1")
    """
    if workspace_id is None:
        async with get_db() as db:
            yield db
        return

    settings = get_settings()
    # Derive the workspace DB directory from the global DB's parent.
    # Global DB lives at <data_dir>/murmuroscope.db; workspace DBs live at
    # <data_dir>/workspaces/<workspace_id>/murmuroscope.db
    global_db_parent = Path(settings.DATABASE_PATH).parent
    workspace_dir = global_db_parent / "workspaces" / workspace_id
    os.makedirs(workspace_dir, exist_ok=True)

    db_path = workspace_dir / "murmuroscope.db"
    is_new_db = not db_path.exists()

    db = await aiosqlite.connect(str(db_path))
    try:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
        await db.execute("PRAGMA journal_size_limit = 67108864")
        await db.execute("PRAGMA wal_autocheckpoint = 2000")
        await db.execute("PRAGMA cache_size = -65536")
        await db.execute("PRAGMA mmap_size = 268435456")
        await db.execute("PRAGMA busy_timeout = 5000")
        db.row_factory = aiosqlite.Row

        if is_new_db:
            schema_file = Path(settings.schema_path)
            if schema_file.exists():
                schema_sql = schema_file.read_text(encoding="utf-8")
                await db.executescript(schema_sql)
                await db.commit()
                logger.info(
                    "Initialised new workspace DB for workspace %s at %s",
                    workspace_id,
                    db_path,
                )
            else:
                logger.warning(
                    "schema.sql not found at %s — workspace DB %s created without schema",
                    schema_file,
                    db_path,
                )

        yield db
    finally:
        await db.close()


async def get_db_for_session(session_id: str) -> str | None:
    """Look up the workspace_id for a session, if any.

    Returns the workspace_id string when the session belongs to a workspace,
    or None when it belongs to the global (default) database.

    This is the hook point for future callers that want to route DB access to
    the correct per-workspace SQLite file.  The actual query routing is done by
    callers using ``get_workspace_db(await get_db_for_session(session_id))``.

    Usage::

        workspace_id = await get_db_for_session(session_id)
        async with get_workspace_db(workspace_id) as db:
            ...
    """
    async with get_db() as db:
        cursor = await db.execute(
            """SELECT ws.workspace_id
               FROM workspace_sessions ws
               WHERE ws.session_id = ?
               LIMIT 1""",
            (session_id,),
        )
        row = await cursor.fetchone()

    if row is None:
        return None
    return row["workspace_id"]
