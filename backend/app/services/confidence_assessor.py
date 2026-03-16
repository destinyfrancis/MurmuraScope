"""Confidence assessment service — aggregates data coverage, model fit, and agent consensus."""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.utils.db import get_db


@dataclass(frozen=True)
class MetricConfidence:
    """Confidence scores for a single decision metric."""

    metric: str
    data_coverage: float  # 0-1, % of records with source_type != 'unavailable'
    model_fit: float  # 0-1, inverse normalized MAPE from backtesting
    agent_consensus: float  # 0-1, 1 - normalized decision variance
    overall: float  # weighted average


@dataclass(frozen=True)
class ConfidenceReport:
    """Aggregated confidence report for a simulation session."""

    session_id: str
    metrics: tuple[MetricConfidence, ...]
    overall_score: float  # 0-1
    data_freshness_hours: float  # hours since last data update
    total_data_records: int
    unavailable_sources: int


class ConfidenceAssessor:
    """Assesses prediction confidence based on data coverage, model fit, and agent consensus."""

    async def assess(self, session_id: str) -> ConfidenceReport:
        """Compute confidence report for a simulation session."""
        data_coverage, freshness_hours, unavailable, total_sources = await self._assess_data_coverage()
        total_records = await self._count_data_records()
        metric_confidences = await self._assess_agent_consensus(session_id, data_coverage)

        # Overall score
        if metric_confidences:
            overall = sum(m.overall for m in metric_confidences) / len(metric_confidences)
        else:
            overall = data_coverage * 0.6 + 0.4 * 0.5  # baseline when no decisions exist

        return ConfidenceReport(
            session_id=session_id,
            metrics=tuple(metric_confidences),
            overall_score=round(overall, 3),
            data_freshness_hours=round(freshness_hours, 1),
            total_data_records=total_records,
            unavailable_sources=unavailable,
        )

    async def _assess_data_coverage(self) -> tuple[float, float, int, int]:
        """Check data_provenance table for coverage and freshness.

        Returns:
            (data_coverage, freshness_hours, unavailable_count, total_sources)
        """
        async with get_db() as db:
            prov_rows = await (
                await db.execute(
                    "SELECT source_name, source_type, updated_at "
                    "FROM data_provenance ORDER BY updated_at DESC"
                )
            ).fetchall()

        total_sources = len(prov_rows) if prov_rows else 0
        unavailable = sum(1 for r in (prov_rows or []) if r["source_type"] == "unavailable")
        available = total_sources - unavailable
        data_coverage = available / max(total_sources, 1)

        freshness_hours = 999.0
        if prov_rows:
            freshness_hours = self._compute_freshness(prov_rows)

        return data_coverage, freshness_hours, unavailable, total_sources

    @staticmethod
    def _compute_freshness(prov_rows: list) -> float:
        """Compute hours since the most recent data update."""
        from datetime import datetime, timezone  # noqa: PLC0415

        try:
            updated_values = [r["updated_at"] for r in prov_rows if r["updated_at"]]
            if not updated_values:
                return 999.0

            latest = max(updated_values)
            if isinstance(latest, str):
                latest_dt = datetime.fromisoformat(latest.replace("Z", "+00:00"))
            else:
                latest_dt = latest

            now = datetime.now(timezone.utc)
            if latest_dt.tzinfo is None:
                latest_dt = latest_dt.replace(tzinfo=timezone.utc)

            return (now - latest_dt).total_seconds() / 3600
        except (ValueError, TypeError):
            return 999.0

    async def _count_data_records(self) -> int:
        """Count total records in hk_data_snapshots."""
        async with get_db() as db:
            count_row = await (
                await db.execute("SELECT COUNT(*) as cnt FROM hk_data_snapshots")
            ).fetchone()
        return count_row["cnt"] if count_row else 0

    async def _assess_agent_consensus(
        self, session_id: str, data_coverage: float
    ) -> list[MetricConfidence]:
        """Compute per-decision-type consensus from agent decisions."""
        async with get_db() as db:
            decision_rows = await (
                await db.execute(
                    """SELECT decision_type, COUNT(*) as cnt,
                              AVG(CASE WHEN outcome = 'approved' THEN 1.0 ELSE 0.0 END) as approval_rate
                       FROM agent_decisions
                       WHERE session_id = ?
                       GROUP BY decision_type""",
                    (session_id,),
                )
            ).fetchall()

        if not decision_rows:
            return []

        result: list[MetricConfidence] = []
        for row in decision_rows:
            approval = row["approval_rate"] if row["approval_rate"] is not None else 0.5
            # Consensus = how much agents agree (high when approval_rate near 0 or 1)
            consensus = 1.0 - 4 * approval * (1 - approval)  # quadratic, peaks at 0/1
            consensus = max(0.0, min(1.0, consensus))

            mc = MetricConfidence(
                metric=row["decision_type"],
                data_coverage=data_coverage,
                model_fit=0.7,  # Default until backtesting is run
                agent_consensus=consensus,
                overall=round(0.3 * data_coverage + 0.3 * 0.7 + 0.4 * consensus, 3),
            )
            result = [*result, mc]

        return result
