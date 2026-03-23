"""Tests for schema.sql FK constraints — verify cascade delete works on fresh DB."""

from __future__ import annotations

import aiosqlite
import pytest


@pytest.mark.asyncio
async def test_cascade_delete_on_fresh_db(tmp_path) -> None:
    """Create a fresh DB from schema.sql, insert session + child rows, delete session, verify cascade."""
    import pathlib

    schema_path = pathlib.Path(__file__).parent.parent / "database" / "schema.sql"
    schema_sql = schema_path.read_text()

    db_path = tmp_path / "test_fk.db"
    async with aiosqlite.connect(str(db_path)) as db:
        # Enable FK enforcement (SQLite disables by default)
        await db.execute("PRAGMA foreign_keys = ON")

        # Create all tables
        await db.executescript(schema_sql)

        # Insert a session
        await db.execute(
            """INSERT INTO simulation_sessions
                   (id, name, sim_mode, agent_count, round_count, llm_provider, status)
               VALUES ('sess-fk-test', 'FK Test', 'hk_demographic', 10, 5, 'openrouter', 'completed')"""
        )

        # Insert child rows in FK-constrained tables with minimal required cols
        await db.execute(
            """INSERT INTO belief_states (session_id, agent_id, round_number, topic, stance)
               VALUES ('sess-fk-test', 1, 1, 'test-topic', 0.5)"""
        )
        await db.execute(
            """INSERT INTO simulation_actions
                   (session_id, round_number, agent_id, oasis_username, action_type, content)
               VALUES ('sess-fk-test', 1, 1, 'agent_1', 'post', 'test content')"""
        )
        await db.execute(
            """INSERT INTO emotional_states (session_id, agent_id, round_number, valence, arousal)
               VALUES ('sess-fk-test', 1, 1, 0.5, 0.5)"""
        )
        await db.commit()

        # Verify child rows exist
        for table in ("belief_states", "simulation_actions", "emotional_states"):
            row = await (
                await db.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE session_id = 'sess-fk-test'"  # noqa: S608
                )
            ).fetchone()
            assert row[0] == 1, f"Expected 1 row in {table}, got {row[0]}"

        # Delete the session — CASCADE should remove child rows
        await db.execute("DELETE FROM simulation_sessions WHERE id = 'sess-fk-test'")
        await db.commit()

        # Verify cascade: all child rows should be gone
        for table in ("belief_states", "simulation_actions", "emotional_states"):
            row = await (
                await db.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE session_id = 'sess-fk-test'"  # noqa: S608
                )
            ).fetchone()
            assert row[0] == 0, f"CASCADE failed for {table}: {row[0]} rows remain"


@pytest.mark.asyncio
async def test_fk_rejects_orphan_insert(tmp_path) -> None:
    """FK constraint should reject insert with non-existent session_id."""
    import pathlib
    import sqlite3

    schema_path = pathlib.Path(__file__).parent.parent / "database" / "schema.sql"
    schema_sql = schema_path.read_text()

    db_path = tmp_path / "test_fk_reject.db"
    async with aiosqlite.connect(str(db_path)) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.executescript(schema_sql)

        with pytest.raises(sqlite3.IntegrityError):
            await db.execute(
                """INSERT INTO belief_states (session_id, agent_id, round_number, topic, stance)
                   VALUES ('nonexistent-session', 1, 1, 'test', 0.5)"""
            )
