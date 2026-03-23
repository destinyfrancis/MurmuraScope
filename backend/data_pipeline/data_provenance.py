"""Data provenance tracker for MurmuraScope data pipeline.

Records the origin, freshness, and coverage of every data point ingested
into the system. Enables auditing which metrics come from live APIs,
derived proxies, or are currently unavailable.

Usage::

    async with get_db() as db:
        await ensure_table(db)
        await record_fetch(
            db,
            category="economy",
            metric="gdp_growth_rate",
            source_type="api_live",
            source_url="https://data.gov.hk/...",
            record_count=44,
            coverage_start="2015-Q1",
            coverage_end="2025-Q4",
        )
        report = await get_provenance_report(db)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

import aiosqlite

from backend.app.utils.logger import get_logger

logger = get_logger("data_pipeline.data_provenance")

SourceType = Literal["api_live", "derived_proxy", "unavailable"]

_CREATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS data_provenance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    metric TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_url TEXT,
    fetch_timestamp TEXT NOT NULL,
    record_count INTEGER NOT NULL,
    coverage_start TEXT,
    coverage_end TEXT,
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
"""

_VALID_SOURCE_TYPES = frozenset({"api_live", "derived_proxy", "unavailable"})


# ---------------------------------------------------------------------------
# Frozen dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProvenanceRecord:
    """Single provenance entry for a (category, metric) pair."""

    category: str
    metric: str
    source_type: str
    source_url: str | None
    fetch_timestamp: str
    record_count: int
    coverage_start: str | None
    coverage_end: str | None
    notes: str | None


@dataclass(frozen=True)
class DataGap:
    """A metric that is unavailable or has zero records."""

    category: str
    metric: str
    last_attempt: str
    error: str


@dataclass(frozen=True)
class CoverageReport:
    """Aggregate coverage summary across all tracked metrics."""

    total_metrics: int
    live_count: int
    proxy_count: int
    unavailable_count: int
    gaps: list[DataGap]


# ---------------------------------------------------------------------------
# Public async functions
# ---------------------------------------------------------------------------


async def ensure_table(db: aiosqlite.Connection) -> None:
    """Create the data_provenance table if it does not exist."""
    await db.execute(_CREATE_TABLE_SQL)
    await db.commit()
    logger.debug("data_provenance table ensured")


async def record_fetch(
    db: aiosqlite.Connection,
    *,
    category: str,
    metric: str,
    source_type: SourceType,
    source_url: str | None = None,
    record_count: int,
    coverage_start: str | None = None,
    coverage_end: str | None = None,
    notes: str | None = None,
) -> None:
    """Insert one provenance row for a data fetch operation."""
    if source_type not in _VALID_SOURCE_TYPES:
        raise ValueError(f"Invalid source_type '{source_type}'; must be one of {sorted(_VALID_SOURCE_TYPES)}")
    if record_count < 0:
        raise ValueError(f"record_count must be >= 0, got {record_count}")

    timestamp = datetime.now(timezone.utc).isoformat()
    await db.execute(
        """
        INSERT INTO data_provenance
            (category, metric, source_type, source_url,
             fetch_timestamp, record_count, coverage_start, coverage_end, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            category,
            metric,
            source_type,
            source_url,
            timestamp,
            record_count,
            coverage_start,
            coverage_end,
            notes,
        ),
    )
    await db.commit()
    logger.info(
        "Recorded provenance: %s/%s source=%s count=%d",
        category,
        metric,
        source_type,
        record_count,
    )


async def get_data_gaps(db: aiosqlite.Connection) -> list[DataGap]:
    """Return metrics that are unavailable or have zero records.

    For each (category, metric) pair, inspects the most recent provenance
    row. If source_type is 'unavailable' or record_count is 0, it is
    reported as a gap.
    """
    cursor = await db.execute(
        """
        SELECT p.category, p.metric, p.fetch_timestamp, p.notes
        FROM data_provenance p
        INNER JOIN (
            SELECT category, metric, MAX(fetch_timestamp) AS latest
            FROM data_provenance
            GROUP BY category, metric
        ) latest_row
            ON p.category = latest_row.category
            AND p.metric = latest_row.metric
            AND p.fetch_timestamp = latest_row.latest
        WHERE p.source_type = 'unavailable' OR p.record_count = 0
        ORDER BY p.category, p.metric
        """
    )
    rows = await cursor.fetchall()
    return [
        DataGap(
            category=row["category"],
            metric=row["metric"],
            last_attempt=row["fetch_timestamp"],
            error=row["notes"] or "no data available",
        )
        for row in rows
    ]


async def get_provenance_report(db: aiosqlite.Connection) -> list[ProvenanceRecord]:
    """Return the full provenance matrix (most recent entry per metric)."""
    cursor = await db.execute(
        """
        SELECT p.category, p.metric, p.source_type, p.source_url,
               p.fetch_timestamp, p.record_count,
               p.coverage_start, p.coverage_end, p.notes
        FROM data_provenance p
        INNER JOIN (
            SELECT category, metric, MAX(fetch_timestamp) AS latest
            FROM data_provenance
            GROUP BY category, metric
        ) latest_row
            ON p.category = latest_row.category
            AND p.metric = latest_row.metric
            AND p.fetch_timestamp = latest_row.latest
        ORDER BY p.category, p.metric
        """
    )
    rows = await cursor.fetchall()
    return [
        ProvenanceRecord(
            category=row["category"],
            metric=row["metric"],
            source_type=row["source_type"],
            source_url=row["source_url"],
            fetch_timestamp=row["fetch_timestamp"],
            record_count=row["record_count"],
            coverage_start=row["coverage_start"],
            coverage_end=row["coverage_end"],
            notes=row["notes"],
        )
        for row in rows
    ]


async def get_coverage_summary(db: aiosqlite.Connection) -> CoverageReport:
    """Return aggregate counts by source_type plus a list of gaps."""
    cursor = await db.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN source_type = 'api_live' THEN 1 ELSE 0 END) AS live,
            SUM(CASE WHEN source_type = 'derived_proxy' THEN 1 ELSE 0 END) AS proxy,
            SUM(CASE WHEN source_type = 'unavailable' THEN 1 ELSE 0 END) AS unavail
        FROM (
            SELECT p.category, p.metric, p.source_type
            FROM data_provenance p
            INNER JOIN (
                SELECT category, metric, MAX(fetch_timestamp) AS latest
                FROM data_provenance
                GROUP BY category, metric
            ) latest_row
                ON p.category = latest_row.category
                AND p.metric = latest_row.metric
                AND p.fetch_timestamp = latest_row.latest
        )
        """
    )
    row = await cursor.fetchone()
    gaps = await get_data_gaps(db)

    return CoverageReport(
        total_metrics=row["total"] or 0,
        live_count=row["live"] or 0,
        proxy_count=row["proxy"] or 0,
        unavailable_count=row["unavail"] or 0,
        gaps=gaps,
    )
