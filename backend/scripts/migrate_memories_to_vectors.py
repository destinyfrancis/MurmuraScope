#!/usr/bin/env python3
"""Migrate existing agent_memories from SQLite to LanceDB vector store.

Usage:
    python -m backend.scripts.migrate_memories_to_vectors [--batch-size 100]

Reads all rows from agent_memories, embeds them, and writes to LanceDB.
Safe to run multiple times (additive — existing vectors are preserved).
"""

from __future__ import annotations

import argparse
import asyncio
import sqlite3
from pathlib import Path

DB_PATH = Path("data/hksimengine.db")
VECTOR_STORE_PATH = "data/vector_store"
BATCH_SIZE = 100


async def migrate(batch_size: int = BATCH_SIZE) -> None:
    from backend.app.services.vector_store import VectorStore

    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        """
        SELECT id, session_id, agent_id, round_number,
               memory_text, salience_score, memory_type
        FROM agent_memories
        ORDER BY session_id, id
        """
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print("No memories to migrate.")
        return

    print(f"Found {len(rows)} memories to migrate.")

    vs = VectorStore(db_path=VECTOR_STORE_PATH)

    # Group by session_id for batch processing
    by_session: dict[str, list[dict]] = {}
    for row in rows:
        sid = row["session_id"]
        if sid not in by_session:
            by_session[sid] = []
        by_session[sid].append({
            "memory_id": row["id"],
            "agent_id": row["agent_id"],
            "round_number": row["round_number"],
            "memory_text": row["memory_text"],
            "salience_score": row["salience_score"],
            "memory_type": row["memory_type"],
        })

    total = 0
    for session_id, memories in by_session.items():
        print(f"  Session {session_id[:8]}… — {len(memories)} memories")

        # Process in batches
        for i in range(0, len(memories), batch_size):
            batch = memories[i : i + batch_size]
            count = await vs.add_memories(session_id, batch)
            total += count
            print(f"    Batch {i // batch_size + 1}: embedded {count} records")

    print(f"\nMigration complete. Total: {total} memories vectorised.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate agent_memories to LanceDB")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    args = parser.parse_args()
    asyncio.run(migrate(batch_size=args.batch_size))


if __name__ == "__main__":
    main()
