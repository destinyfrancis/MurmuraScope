"""Data quality monitor for HKSimEngine data pipeline.

Reads from the hk_data_snapshots table and generates a structured
quality report covering completeness, duplicates, outliers, and freshness.

Usage::

    monitor = DataQualityMonitor()
    report = await monitor.generate_report()
    print(f"Quality score: {report.score:.1f}/100")
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("data_pipeline.data_quality")

# Expected periods per metric per year (approximate)
_EXPECTED_FREQUENCY: dict[str, int] = {
    "monthly": 12,
    "quarterly": 4,
    "annual": 1,
}

# Categories with expected monthly frequency
_MONTHLY_CATEGORIES: frozenset[str] = frozenset({
    "interest_rate", "price_index", "market", "social_sentiment",
    "retail_tourism", "weather", "transport", "fred",
})

# Categories with quarterly/annual frequency
_QUARTERLY_CATEGORIES: frozenset[str] = frozenset({"gdp", "employment"})
_ANNUAL_CATEGORIES: frozenset[str] = frozenset({"census", "education", "migration"})


@dataclass(frozen=True)
class OutlierRecord:
    """Immutable description of a detected outlier data point."""

    category: str
    metric: str
    period: str
    value: float
    mean: float
    std_dev: float
    z_score: float


@dataclass(frozen=True)
class QualityReport:
    """Immutable data quality report for hk_data_snapshots.

    Attributes:
        total_records: Total rows in hk_data_snapshots.
        missing_values: Count of NULL or empty value fields.
        duplicates: Count of duplicate (category, metric, period) combos.
        outliers: List of detected outlier records (|z-score| > 3).
        freshness: Dict mapping "{category}/{metric}" -> latest period string.
        stale_metrics: Metrics with no data in the last 3 months.
        score: Overall quality score 0-100.
        generated_at: ISO-8601 timestamp of report generation.
    """

    total_records: int
    missing_values: int
    duplicates: int
    outliers: tuple[OutlierRecord, ...]
    freshness: dict[str, str]
    stale_metrics: tuple[str, ...]
    score: float
    generated_at: str


class DataQualityMonitor:
    """Generates quality reports for hk_data_snapshots table.

    All methods are async and read from the DB via aiosqlite.
    Immutable pattern: each check returns a new datastructure, no in-place
    mutation.
    """

    _OUTLIER_Z_THRESHOLD = 3.0
    _STALE_THRESHOLD_MONTHS = 3

    async def check_completeness(self) -> tuple[int, int]:
        """Check for missing (NULL/empty) values in hk_data_snapshots.

        Returns:
            Tuple of (total_records, missing_count).
        """
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM hk_data_snapshots"
            )
            row = await cursor.fetchone()
            total = int(row[0]) if row else 0

            cursor = await db.execute(
                """
                SELECT COUNT(*) FROM hk_data_snapshots
                WHERE value IS NULL
                   OR metric IS NULL OR metric = ''
                   OR period IS NULL OR period = ''
                """
            )
            row = await cursor.fetchone()
            missing = int(row[0]) if row else 0

        logger.debug("Completeness: total=%d, missing=%d", total, missing)
        return total, missing

    async def check_duplicates(self) -> int:
        """Find duplicate (category, metric, period) combinations.

        Returns:
            Count of duplicate rows (rows beyond the first occurrence).
        """
        async with get_db() as db:
            cursor = await db.execute(
                """
                SELECT SUM(cnt - 1) FROM (
                    SELECT COUNT(*) AS cnt
                    FROM hk_data_snapshots
                    GROUP BY category, metric, period
                    HAVING COUNT(*) > 1
                )
                """
            )
            row = await cursor.fetchone()
            duplicates = int(row[0]) if row and row[0] is not None else 0

        logger.debug("Duplicates: %d excess rows", duplicates)
        return duplicates

    async def check_outliers(self) -> tuple[OutlierRecord, ...]:
        """Detect statistical outliers using z-score method (|z| > 3).

        Groups by (category, metric) and computes mean/std per group.
        Only groups with >=5 data points are checked (insufficient data
        for meaningful statistics otherwise).

        Returns:
            Tuple of OutlierRecord for each detected outlier.
        """
        async with get_db() as db:
            # Fetch all (category, metric, period, value) with non-null values
            cursor = await db.execute(
                """
                SELECT category, metric, period, CAST(value AS REAL) AS v
                FROM hk_data_snapshots
                WHERE value IS NOT NULL
                ORDER BY category, metric, period
                """
            )
            rows = await cursor.fetchall()

        # Group by (category, metric)
        groups: dict[tuple[str, str], list[tuple[str, float]]] = {}
        for category, metric, period, v in rows:
            key = (str(category), str(metric))
            if key not in groups:
                groups[key] = []
            groups[key].append((str(period), float(v)))

        outliers: list[OutlierRecord] = []

        for (category, metric), points in groups.items():
            if len(points) < 5:
                continue  # insufficient data for z-score

            values = [p[1] for p in points]
            mean = sum(values) / len(values)
            variance = sum((v - mean) ** 2 for v in values) / len(values)
            std_dev = math.sqrt(variance) if variance > 0 else 0.0

            if std_dev == 0.0:
                continue

            for period, value in points:
                z = abs((value - mean) / std_dev)
                if z > self._OUTLIER_Z_THRESHOLD:
                    outliers.append(OutlierRecord(
                        category=category,
                        metric=metric,
                        period=period,
                        value=value,
                        mean=round(mean, 4),
                        std_dev=round(std_dev, 4),
                        z_score=round(z, 2),
                    ))

        logger.debug("Outliers detected: %d", len(outliers))
        return tuple(outliers)

    async def check_freshness(self) -> dict[str, str]:
        """Determine the most recent period for each (category, metric) pair.

        Returns:
            Dict mapping "{category}/{metric}" -> latest period string.
        """
        async with get_db() as db:
            cursor = await db.execute(
                """
                SELECT category, metric, MAX(period) AS latest_period
                FROM hk_data_snapshots
                WHERE period IS NOT NULL AND period != ''
                GROUP BY category, metric
                """
            )
            rows = await cursor.fetchall()

        freshness: dict[str, str] = {
            f"{row[0]}/{row[1]}": str(row[2])
            for row in rows
        }
        logger.debug("Freshness check: %d distinct metric series", len(freshness))
        return freshness

    def _is_stale(self, latest_period: str) -> bool:
        """Return True if latest_period is more than 3 months ago.

        Handles YYYY-MM, YYYY-QN, and YYYY format strings.
        """
        now = datetime.now(tz=timezone.utc)

        # Try YYYY-MM
        try:
            dt = datetime.strptime(latest_period[:7], "%Y-%m").replace(tzinfo=timezone.utc)
            months_ago = (now.year - dt.year) * 12 + (now.month - dt.month)
            return months_ago > self._STALE_THRESHOLD_MONTHS
        except ValueError:
            pass

        # Try YYYY-QN (quarterly)
        if "-Q" in latest_period:
            try:
                year, quarter = latest_period.split("-Q")
                month = (int(quarter) - 1) * 3 + 1
                dt = datetime(int(year), month, 1, tzinfo=timezone.utc)
                months_ago = (now.year - dt.year) * 12 + (now.month - dt.month)
                return months_ago > self._STALE_THRESHOLD_MONTHS * 2  # quarterly: 6-month threshold
            except (ValueError, IndexError):
                pass

        # Try YYYY (annual)
        try:
            year = int(latest_period[:4])
            return (now.year - year) > 1
        except ValueError:
            pass

        return False  # Unknown format: assume not stale

    async def generate_report(self) -> QualityReport:
        """Run all quality checks and return a consolidated QualityReport.

        Computes an overall score (0-100):
        - 40 pts: completeness (no missing values)
        - 20 pts: no duplicates
        - 20 pts: no outliers (capped at 10 outliers = 0 pts)
        - 20 pts: freshness (no stale metrics)

        Returns:
            QualityReport with all checks and composite score.
        """
        logger.info("Running data quality checks...")

        total, missing = await self.check_completeness()
        duplicates = await self.check_duplicates()
        outliers = await self.check_outliers()
        freshness = await self.check_freshness()

        # Identify stale metrics
        stale_metrics = tuple(
            key for key, period in freshness.items()
            if self._is_stale(period)
        )

        # Score calculation
        completeness_score = 40.0 * (1.0 - (missing / max(total, 1)))
        duplicate_score = 20.0 if duplicates == 0 else max(0.0, 20.0 - (duplicates * 2.0))
        outlier_score = max(0.0, 20.0 - (len(outliers) * 2.0))
        freshness_total = max(len(freshness), 1)
        freshness_score = 20.0 * (1.0 - (len(stale_metrics) / freshness_total))

        score = round(completeness_score + duplicate_score + outlier_score + freshness_score, 1)
        score = max(0.0, min(100.0, score))

        generated_at = datetime.now(tz=timezone.utc).isoformat()

        report = QualityReport(
            total_records=total,
            missing_values=missing,
            duplicates=duplicates,
            outliers=outliers,
            freshness=freshness,
            stale_metrics=stale_metrics,
            score=score,
            generated_at=generated_at,
        )

        logger.info(
            "Data quality report: score=%.1f, records=%d, missing=%d, "
            "duplicates=%d, outliers=%d, stale=%d",
            score, total, missing, duplicates, len(outliers), len(stale_metrics),
        )
        return report

    async def check_category_coverage(self) -> dict[str, int]:
        """Return count of records per category.

        Useful for a quick overview of which categories are populated.

        Returns:
            Dict mapping category -> record count.
        """
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT category, COUNT(*) FROM hk_data_snapshots GROUP BY category ORDER BY category"
            )
            rows = await cursor.fetchall()
        return {str(row[0]): int(row[1]) for row in rows}
