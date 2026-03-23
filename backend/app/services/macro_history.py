"""Macro-economic state history storage for MurmuraScope.

Persists per-round MacroState snapshots in a lightweight SQLite table so
the frontend can render indicator timelines across simulation rounds.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass

from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("macro_history")

# ---------------------------------------------------------------------------
# Domain model
# ---------------------------------------------------------------------------

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS macro_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL,
    round_number INTEGER NOT NULL,
    macro_json  TEXT    NOT NULL,
    created_at  TEXT    DEFAULT (datetime('now')),
    UNIQUE(session_id, round_number)
)
"""

# Key indicators extracted for the summary list view (avoids parsing full JSON)
_KEY_METRICS: tuple[str, ...] = (
    "consumer_confidence",
    "hsi_level",
    "unemployment_rate",
    "ccl_index",
    "gdp_growth",
    "net_migration",
)


@dataclass(frozen=True)
class MacroSnapshot:
    """Immutable record of a MacroState at a specific simulation round."""

    session_id: str
    round_number: int
    macro_json: str  # JSON-serialised MacroState as a flat dict


# ---------------------------------------------------------------------------
# MacroHistoryService
# ---------------------------------------------------------------------------


class MacroHistoryService:
    """Stores and retrieves MacroState snapshots per simulation round."""

    async def save_snapshot(
        self,
        session_id: str,
        round_number: int,
        state: object,  # MacroState — typed as object to avoid circular import
    ) -> None:
        """Persist a MacroState snapshot for the given round.

        Uses INSERT OR REPLACE so re-running a round is idempotent.

        Args:
            session_id: Simulation session UUID.
            round_number: The simulation round this snapshot belongs to.
            state: A MacroState frozen dataclass instance.
        """
        try:
            macro_dict = _serialize_macro_state(state)
            macro_json = json.dumps(macro_dict, ensure_ascii=False)

            async with get_db() as db:
                await db.execute(_CREATE_TABLE_SQL)
                await db.execute(
                    """
                    INSERT INTO macro_snapshots (session_id, round_number, macro_json)
                    VALUES (?, ?, ?)
                    ON CONFLICT(session_id, round_number) DO UPDATE SET
                        macro_json = excluded.macro_json,
                        created_at = datetime('now')
                    """,
                    (session_id, round_number, macro_json),
                )
                await db.commit()

            logger.debug("Saved macro snapshot session=%s round=%d", session_id, round_number)
        except Exception:
            logger.exception("save_snapshot failed session=%s round=%d", session_id, round_number)

    async def get_history(
        self,
        session_id: str,
    ) -> list[dict]:
        """Return macro history for a session — one entry per round.

        Each entry contains: round_number + key indicator values
        (consumer_confidence, hsi_level, unemployment_rate, ccl_index,
        gdp_growth, net_migration).

        Args:
            session_id: Simulation session UUID.

        Returns:
            List of dicts sorted by round_number ascending.
        """
        try:
            async with get_db() as db:
                await db.execute(_CREATE_TABLE_SQL)
                cursor = await db.execute(
                    """
                    SELECT round_number, macro_json
                    FROM macro_snapshots
                    WHERE session_id = ?
                    ORDER BY round_number ASC
                    """,
                    (session_id,),
                )
                rows = await cursor.fetchall()
        except Exception:
            logger.exception("get_history failed session=%s", session_id)
            return []

        result: list[dict] = []
        for row in rows:
            round_number = row[0]
            raw_json = row[1]
            try:
                full = json.loads(raw_json)
            except (json.JSONDecodeError, TypeError):
                full = {}

            entry: dict = {"round_number": round_number}
            for metric in _KEY_METRICS:
                entry[metric] = full.get(metric)
            result.append(entry)

        return result

    async def get_snapshot(
        self,
        session_id: str,
        round_number: int,
    ) -> dict | None:
        """Return the full MacroState dict for a specific round.

        Args:
            session_id: Simulation session UUID.
            round_number: Round to retrieve.

        Returns:
            Full macro dict, or None if not found.
        """
        try:
            async with get_db() as db:
                await db.execute(_CREATE_TABLE_SQL)
                cursor = await db.execute(
                    """
                    SELECT macro_json
                    FROM macro_snapshots
                    WHERE session_id = ? AND round_number = ?
                    LIMIT 1
                    """,
                    (session_id, round_number),
                )
                row = await cursor.fetchone()
        except Exception:
            logger.exception("get_snapshot failed session=%s round=%d", session_id, round_number)
            return None

        if row is None:
            return None

        try:
            return json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            logger.warning("get_snapshot: invalid JSON for session=%s round=%d", session_id, round_number)
            return None


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _serialize_macro_state(state: object) -> dict:
    """Convert a MacroState dataclass to a JSON-serialisable flat dict.

    Handles nested dicts (avg_sqft_price, stamp_duty_rates, policy_flags)
    by keeping them as-is (they are already JSON-safe).

    Args:
        state: MacroState frozen dataclass instance.

    Returns:
        Plain dict suitable for json.dumps().
    """
    try:
        raw: dict = dataclasses.asdict(state)
    except Exception:
        # Fallback: try __dict__ for non-dataclass objects
        raw = getattr(state, "__dict__", {})

    # Ensure all values are JSON-serialisable (int/float/str/bool/None/dict/list)
    safe: dict = {}
    for key, value in raw.items():
        if isinstance(value, dict):
            safe[key] = {str(k): v for k, v in value.items()}
        elif isinstance(value, (int, float, str, bool, type(None), list)):
            safe[key] = value
        else:
            safe[key] = str(value)
    return safe
