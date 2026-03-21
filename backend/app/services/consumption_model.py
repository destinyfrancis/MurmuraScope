"""B2C Consumption Tracking for MurmuraScope Phase C.

Wraps the existing ``ConsumerModel`` and adds per-round DB persistence so
that consumption trends can be queried for analytics and reporting.

The ``ConsumptionTracker`` is the primary entry point:
- ``track_round()``: generate + persist spending profiles for all agents.
- ``get_consumption_trends()``: aggregate stored data by round for a session.

All returned data is structured as plain dicts or frozen dataclasses — no
in-place mutation.

Usage::

    tracker = ConsumptionTracker()
    async with get_db() as db:
        await tracker.ensure_table(db)
    await tracker.track_round(
        session_id="abc123",
        round_number=5,
        profiles=agent_profiles,
        macro_state=current_macro,
    )
    trends = await tracker.get_consumption_trends("abc123")
"""

from __future__ import annotations

import dataclasses
from typing import Sequence

import aiosqlite

from backend.app.services.agent_factory import AgentProfile
from backend.app.services.consumer_model import ConsumerModel, SpendingProfile
from backend.app.services.macro_state import MacroState
from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("consumption_model")

# ---------------------------------------------------------------------------
# Schema constant (kept in sync with schema.sql)
# ---------------------------------------------------------------------------

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS agent_consumption (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    agent_id INTEGER NOT NULL,
    round_number INTEGER NOT NULL,
    category TEXT NOT NULL,
    amount_pct REAL NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_consumption_session
    ON agent_consumption(session_id, round_number);
"""

# Spending categories written to DB (excludes savings — tracked separately)
_CATEGORIES = ("food", "housing", "transport", "entertainment", "education", "healthcare")


# ---------------------------------------------------------------------------
# RoundConsumptionSummary — immutable aggregate result
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class RoundConsumptionSummary:
    """Aggregate spending profile for one simulation round.

    Attributes:
        round_number: The simulation round this summary covers.
        agent_count: Number of agents included in the aggregate.
        avg_food: Average food spending fraction across agents.
        avg_housing: Average housing spending fraction.
        avg_transport: Average transport spending fraction.
        avg_entertainment: Average entertainment spending fraction.
        avg_education: Average education spending fraction.
        avg_healthcare: Average healthcare spending fraction.
        avg_savings_rate: Implied average savings rate (1 − total_consumption).
        dominant_category: The category with the highest average spend.
    """

    round_number: int
    agent_count: int
    avg_food: float
    avg_housing: float
    avg_transport: float
    avg_entertainment: float
    avg_education: float
    avg_healthcare: float
    avg_savings_rate: float
    dominant_category: str

    def to_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# ConsumptionTracker
# ---------------------------------------------------------------------------


class ConsumptionTracker:
    """Tracks per-round household consumption and persists to ``agent_consumption``.

    Wraps ``ConsumerModel`` for profile generation and delegates DB I/O to
    aiosqlite via the project's ``get_db()`` context manager.

    All methods are async-safe and stateless — the tracker holds no mutable
    session data between calls.
    """

    def __init__(self) -> None:
        self._consumer_model = ConsumerModel()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def ensure_table(self, db: aiosqlite.Connection) -> None:
        """Create ``agent_consumption`` table if it does not yet exist.

        Safe to call on every startup — uses ``CREATE TABLE IF NOT EXISTS``.

        Args:
            db: Open aiosqlite connection.
        """
        await db.executescript(_CREATE_TABLE_SQL)
        await db.commit()

    async def track_round(
        self,
        session_id: str,
        round_number: int,
        profiles: Sequence[AgentProfile],
        macro_state: MacroState,
        sentiment_map: dict[int, str] | None = None,
    ) -> int:
        """Generate spending profiles for all agents and persist to DB.

        Generates a ``SpendingProfile`` per agent via ``ConsumerModel``,
        optionally adjusting for the agent's last-known sentiment.  Batch-
        inserts all category-amount rows into ``agent_consumption``.

        Args:
            session_id: Simulation session UUID.
            round_number: The simulation round that just completed.
            profiles: Agent profiles for the session.
            macro_state: Current macro-economic state used for adjustments.
            sentiment_map: Optional mapping of agent_id → sentiment string
                (``"positive"``, ``"negative"``, ``"neutral"``).

        Returns:
            Number of DB rows inserted (agents × categories).
        """
        if not profiles:
            return 0

        # Generate spending profiles (immutable, no side effects)
        spending_profiles = self._consumer_model.generate_batch(
            profiles=list(profiles),
            macro_state=macro_state,
            sentiment_map=sentiment_map,
        )

        # Build batch insert rows
        rows: list[tuple[str, int, int, str, float]] = []
        for agent_profile, spending in zip(profiles, spending_profiles):
            for category in _CATEGORIES:
                amount_pct = float(getattr(spending, category, 0.0))
                rows.append((
                    session_id,
                    agent_profile.id,
                    round_number,
                    category,
                    amount_pct,
                ))

        if not rows:
            return 0

        try:
            async with get_db() as db:
                await self.ensure_table(db)
                await db.executemany(
                    """
                    INSERT INTO agent_consumption
                        (session_id, agent_id, round_number, category, amount_pct)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    rows,
                )
                await db.commit()
        except Exception:
            logger.exception(
                "track_round: DB write failed session=%s round=%d",
                session_id, round_number,
            )
            return 0

        logger.debug(
            "track_round: inserted %d rows session=%s round=%d agents=%d",
            len(rows), session_id, round_number, len(profiles),
        )
        return len(rows)

    async def get_consumption_trends(
        self,
        session_id: str,
        limit_rounds: int = 50,
    ) -> list[RoundConsumptionSummary]:
        """Return aggregated spending trends grouped by round.

        Reads from ``agent_consumption`` and computes per-round averages for
        each spending category.  Results are sorted chronologically.

        Args:
            session_id: Simulation session UUID.
            limit_rounds: Maximum number of rounds to return.  Default 50.

        Returns:
            List of ``RoundConsumptionSummary`` objects, one per round.
            Empty list if no data recorded.
        """
        try:
            async with get_db() as db:
                await self.ensure_table(db)
                cursor = await db.execute(
                    """
                    SELECT
                        round_number,
                        COUNT(DISTINCT agent_id)  AS agent_count,
                        AVG(CASE WHEN category = 'food'          THEN amount_pct ELSE NULL END) AS avg_food,
                        AVG(CASE WHEN category = 'housing'       THEN amount_pct ELSE NULL END) AS avg_housing,
                        AVG(CASE WHEN category = 'transport'     THEN amount_pct ELSE NULL END) AS avg_transport,
                        AVG(CASE WHEN category = 'entertainment' THEN amount_pct ELSE NULL END) AS avg_entertainment,
                        AVG(CASE WHEN category = 'education'     THEN amount_pct ELSE NULL END) AS avg_education,
                        AVG(CASE WHEN category = 'healthcare'    THEN amount_pct ELSE NULL END) AS avg_healthcare
                    FROM agent_consumption
                    WHERE session_id = ?
                    GROUP BY round_number
                    ORDER BY round_number ASC
                    LIMIT ?
                    """,
                    (session_id, limit_rounds),
                )
                rows = await cursor.fetchall()
        except Exception:
            logger.exception(
                "get_consumption_trends: DB read failed session=%s", session_id
            )
            return []

        summaries: list[RoundConsumptionSummary] = []
        for row in rows:
            avg_food = float(row[2] or 0.0)
            avg_housing = float(row[3] or 0.0)
            avg_transport = float(row[4] or 0.0)
            avg_entertainment = float(row[5] or 0.0)
            avg_education = float(row[6] or 0.0)
            avg_healthcare = float(row[7] or 0.0)

            total_consumption = (
                avg_food + avg_housing + avg_transport
                + avg_entertainment + avg_education + avg_healthcare
            )
            avg_savings_rate = max(0.0, round(1.0 - total_consumption, 4))

            category_avgs = {
                "food": avg_food,
                "housing": avg_housing,
                "transport": avg_transport,
                "entertainment": avg_entertainment,
                "education": avg_education,
                "healthcare": avg_healthcare,
            }
            dominant = max(category_avgs, key=lambda k: category_avgs[k])

            summaries.append(RoundConsumptionSummary(
                round_number=int(row[0]),
                agent_count=int(row[1] or 0),
                avg_food=round(avg_food, 4),
                avg_housing=round(avg_housing, 4),
                avg_transport=round(avg_transport, 4),
                avg_entertainment=round(avg_entertainment, 4),
                avg_education=round(avg_education, 4),
                avg_healthcare=round(avg_healthcare, 4),
                avg_savings_rate=avg_savings_rate,
                dominant_category=dominant,
            ))

        return summaries

    async def get_agent_consumption(
        self,
        session_id: str,
        agent_id: int,
        limit_rounds: int = 30,
    ) -> list[dict[str, object]]:
        """Return raw consumption rows for a single agent across rounds.

        Useful for agent detail panels and individual spending timelines.

        Args:
            session_id: Simulation session UUID.
            agent_id: Agent primary key.
            limit_rounds: Maximum number of distinct rounds to return.

        Returns:
            List of dicts with keys: round_number, category, amount_pct.
        """
        try:
            async with get_db() as db:
                await self.ensure_table(db)
                cursor = await db.execute(
                    """
                    SELECT round_number, category, amount_pct
                    FROM agent_consumption
                    WHERE session_id = ? AND agent_id = ?
                    ORDER BY round_number ASC, category ASC
                    LIMIT ?
                    """,
                    (session_id, agent_id, limit_rounds * len(_CATEGORIES)),
                )
                rows = await cursor.fetchall()
        except Exception:
            logger.exception(
                "get_agent_consumption: DB read failed session=%s agent=%d",
                session_id, agent_id,
            )
            return []

        return [
            {
                "round_number": row[0],
                "category": row[1],
                "amount_pct": row[2],
            }
            for row in rows
        ]
