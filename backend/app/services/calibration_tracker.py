"""Track prediction accuracy over time.

Records directional predictions made by simulations and verifies them
against actual outcomes when they become available. Computes hit-rate
statistics to assess the real-world calibration of the engine.

Design:
  - ``_ensure_schema()`` is idempotent: safe to call on every operation.
  - All DB access via the project-standard ``get_db()`` context manager.
  - Table ``prediction_tracking`` is created lazily (no schema migration needed).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from backend.app.utils.db import get_db


class CalibrationTracker:
    """Track and verify directional predictions from simulation sessions."""

    async def _ensure_schema(self) -> None:
        """Create the ``prediction_tracking`` table if it does not exist."""
        async with get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS prediction_tracking (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    predicted_direction TEXT NOT NULL,
                    predicted_magnitude REAL,
                    prediction_date TEXT NOT NULL,
                    target_date TEXT NOT NULL,
                    actual_direction TEXT,
                    actual_value REAL,
                    hit INTEGER,
                    verified_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_pt_pending ON prediction_tracking(hit)")
            await db.commit()

    async def record(
        self,
        session_id: str,
        metric: str,
        predicted_direction: str,
        predicted_magnitude: float,
        target_date: str,
    ) -> None:
        """Record a new directional prediction.

        Args:
            session_id: Simulation session that produced the prediction.
            metric: Name of the metric being predicted (e.g. "hsi", "ccl_index").
            predicted_direction: "up", "down", or "stable".
            predicted_magnitude: Expected percentage change (informational).
            target_date: ISO date string when the prediction should be verified.
        """
        await self._ensure_schema()
        async with get_db() as db:
            await db.execute(
                """INSERT INTO prediction_tracking
                (session_id, metric, predicted_direction, predicted_magnitude,
                 prediction_date, target_date)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    metric,
                    predicted_direction,
                    predicted_magnitude,
                    date.today().isoformat(),
                    target_date,
                ),
            )
            await db.commit()

    async def get_pending(self) -> list[dict]:
        """Return all predictions that have not yet been verified.

        Returns:
            List of dicts with keys ``session_id``, ``metric``,
            ``predicted_direction``, ``target_date``.
        """
        await self._ensure_schema()
        async with get_db() as db:
            cursor = await db.execute(
                """SELECT session_id, metric, predicted_direction, target_date
                   FROM prediction_tracking
                   WHERE hit IS NULL
                   ORDER BY target_date ASC"""
            )
            rows = await cursor.fetchall()
            return [
                {
                    "session_id": r[0],
                    "metric": r[1],
                    "predicted_direction": r[2],
                    "target_date": r[3],
                }
                for r in rows
            ]

    async def verify(
        self,
        session_id: str,
        metric: str,
        actual_direction: str,
        actual_value: float,
    ) -> None:
        """Verify a pending prediction against an observed outcome.

        Sets ``hit=1`` if ``actual_direction`` matches ``predicted_direction``,
        otherwise ``hit=0``. Only the first unverified record for the given
        ``(session_id, metric)`` pair is updated.

        Args:
            session_id: Session whose prediction is being verified.
            metric: Metric name.
            actual_direction: Observed direction ("up", "down", "stable").
            actual_value: Observed numeric value.
        """
        await self._ensure_schema()
        async with get_db() as db:
            cursor = await db.execute(
                """SELECT id, predicted_direction
                   FROM prediction_tracking
                   WHERE session_id = ? AND metric = ? AND hit IS NULL
                   ORDER BY id ASC
                   LIMIT 1""",
                (session_id, metric),
            )
            row = await cursor.fetchone()
            if row:
                hit = 1 if row[1] == actual_direction else 0
                await db.execute(
                    """UPDATE prediction_tracking
                       SET actual_direction = ?,
                           actual_value = ?,
                           hit = ?,
                           verified_at = ?
                       WHERE id = ?""",
                    (
                        actual_direction,
                        actual_value,
                        hit,
                        datetime.now(timezone.utc).isoformat(),
                        row[0],
                    ),
                )
                await db.commit()

    async def get_accuracy(self) -> dict:
        """Return aggregate hit-rate statistics across all verified predictions.

        Returns:
            Dict with keys ``total`` (int), ``hits`` (int), ``hit_rate`` (float).
        """
        await self._ensure_schema()
        async with get_db() as db:
            cursor = await db.execute(
                """SELECT COUNT(*),
                          SUM(CASE WHEN hit = 1 THEN 1 ELSE 0 END)
                   FROM prediction_tracking
                   WHERE hit IS NOT NULL"""
            )
            row = await cursor.fetchone()
            total = row[0] or 0
            hits = row[1] or 0
            return {
                "total": total,
                "hits": hits,
                "hit_rate": round(hits / total, 4) if total > 0 else 0.0,
            }

    async def get_accuracy_by_metric(self) -> dict[str, dict]:
        """Return per-metric hit-rate statistics.

        Returns:
            Dict mapping metric name to ``{total, hits, hit_rate}``.
        """
        await self._ensure_schema()
        async with get_db() as db:
            cursor = await db.execute(
                """SELECT metric,
                          COUNT(*) as total,
                          SUM(CASE WHEN hit = 1 THEN 1 ELSE 0 END) as hits
                   FROM prediction_tracking
                   WHERE hit IS NOT NULL
                   GROUP BY metric
                   ORDER BY metric"""
            )
            rows = await cursor.fetchall()
            result = {}
            for row in rows:
                metric, total, hits = row[0], row[1] or 0, row[2] or 0
                result[metric] = {
                    "total": total,
                    "hits": hits,
                    "hit_rate": round(hits / total, 4) if total > 0 else 0.0,
                }
            return result
