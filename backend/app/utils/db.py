"""Async SQLite connection manager using aiosqlite with WAL mode."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

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
        "ALTER TABLE kg_edges ADD COLUMN round_number INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE agent_decisions ADD COLUMN topic_tags TEXT",
        "ALTER TABLE agent_decisions ADD COLUMN emotional_reaction TEXT",
    ]
    # Idempotent index creation — CREATE INDEX IF NOT EXISTS is always safe
    index_migrations = [
        # Composite index for recursive CTE in get_relational_context()
        "CREATE INDEX IF NOT EXISTS idx_triple_search "
        "ON memory_triples(session_id, agent_id, subject, object)",
    ]
    async with get_db() as db:
        for sql in migrations:
            try:
                await db.execute(sql)
                await db.commit()
            except Exception:
                # Column already exists — safe to ignore
                pass
        for sql in index_migrations:
            await db.execute(sql)
            await db.commit()
    logger.info("DB migrations applied")
