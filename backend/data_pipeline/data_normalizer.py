"""Normalize downloaded data into hk_data_snapshots and population_distributions tables.

Takes parsed records from all downloaders and inserts them into the database.
Uses batch inserts for efficiency. All operations are idempotent — duplicate
records (same category+metric+period) are skipped via INSERT OR IGNORE.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("data_pipeline.normalizer")

BATCH_SIZE = 500


class HasSnapshotFields(Protocol):
    """Protocol for records that can be normalised into hk_data_snapshots.

    Only ``metric``, ``value``, and ``source`` are strictly required.
    ``category``, ``period`` (or ``date``), and ``source_url`` are handled
    gracefully via getattr() in ``to_snapshot_rows()``.
    """

    metric: str
    value: float
    source: str


@dataclass(frozen=True)
class SnapshotRow:
    """Immutable row ready for insertion into hk_data_snapshots."""

    category: str
    metric: str
    value: float
    unit: str
    period: str
    source: str
    source_url: str


@dataclass(frozen=True)
class PopulationRow:
    """Immutable row ready for insertion into population_distributions."""

    category: str
    dimension_1: str
    dimension_2: str | None
    dimension_3: str | None
    count: int
    probability: float
    source_year: int
    source_dataset: str


@dataclass(frozen=True)
class NormalizeResult:
    """Immutable result of a normalisation operation."""

    snapshots_inserted: int
    snapshots_skipped: int
    populations_inserted: int
    populations_skipped: int


def _extract_unit(record: Any) -> str:
    """Extract unit from a record, with fallback."""
    return getattr(record, "unit", "") or ""


def to_snapshot_rows(records: Sequence[Any]) -> list[SnapshotRow]:
    """Convert downloader records to SnapshotRow list.

    Accepts any record with category, metric, value, source fields.
    Optional fields are handled gracefully:
      - ``period``: falls back to ``date`` attribute, then empty string
      - ``source_url``: falls back to empty string
      - ``category``: falls back to empty string
    """
    rows: list[SnapshotRow] = []
    for rec in records:
        # period: some records use 'date' instead of 'period'
        period = getattr(rec, "period", None) or getattr(rec, "date", "") or ""
        # source_url: not present on all record types
        source_url = getattr(rec, "source_url", "") or ""
        # category: not present on FredRecord (uses series_id as metric)
        category = getattr(rec, "category", "") or ""
        rows.append(
            SnapshotRow(
                category=category,
                metric=rec.metric,
                value=float(rec.value),
                unit=_extract_unit(rec),
                period=str(period),
                source=rec.source,
                source_url=source_url,
            )
        )
    return rows


def to_population_rows(
    records: Sequence[Any],
    source_year: int,
    source_dataset: str,
    total_population: float | None = None,
) -> list[PopulationRow]:
    """Convert census records to PopulationRow list.

    Computes probability as count/total_population.
    If total_population is not provided, it is computed as the sum of all values.
    """
    if not records:
        return []

    values = [float(rec.value) for rec in records]
    computed_total = total_population or sum(values)

    if computed_total <= 0:
        logger.warning("Total population is zero or negative, skipping probability calculation")
        computed_total = 1.0  # Avoid division by zero

    rows: list[PopulationRow] = []
    for rec in records:
        count = int(rec.value)
        probability = float(rec.value) / computed_total

        rows.append(
            PopulationRow(
                category=getattr(rec, "category", "population"),
                dimension_1=getattr(rec, "dimension_1", ""),
                dimension_2=getattr(rec, "dimension_2", None),
                dimension_3=getattr(rec, "dimension_3", None),
                count=count,
                probability=round(probability, 8),
                source_year=source_year,
                source_dataset=source_dataset,
            )
        )

    return rows


async def insert_snapshots(rows: Sequence[SnapshotRow]) -> tuple[int, int]:
    """Insert snapshot rows into hk_data_snapshots table.

    Returns (inserted_count, skipped_count).
    Uses INSERT OR IGNORE to skip duplicates.
    """
    if not rows:
        return 0, 0

    inserted = 0
    skipped = 0

    async with get_db() as db:
        # Create unique index if not exists (for deduplication)
        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_snapshot_unique ON hk_data_snapshots(category, metric, period)"
        )

        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i : i + BATCH_SIZE]
            for row in batch:
                try:
                    cursor = await db.execute(
                        "INSERT OR IGNORE INTO hk_data_snapshots "
                        "(category, metric, value, unit, period, source, source_url) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (row.category, row.metric, row.value, row.unit, row.period, row.source, row.source_url),
                    )
                    if cursor.rowcount > 0:
                        inserted += 1
                    else:
                        skipped += 1
                except Exception:
                    logger.exception(
                        "Failed to insert snapshot: %s/%s/%s",
                        row.category,
                        row.metric,
                        row.period,
                    )
                    skipped += 1

            await db.commit()

    logger.info("Snapshots: inserted=%d, skipped=%d", inserted, skipped)
    return inserted, skipped


async def insert_populations(rows: Sequence[PopulationRow]) -> tuple[int, int]:
    """Insert population rows into population_distributions table.

    Returns (inserted_count, skipped_count).
    """
    if not rows:
        return 0, 0

    inserted = 0
    skipped = 0

    async with get_db() as db:
        # Create unique index for deduplication
        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_pop_unique "
            "ON population_distributions(category, dimension_1, "
            "COALESCE(dimension_2, ''), source_year)"
        )

        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i : i + BATCH_SIZE]
            for row in batch:
                try:
                    cursor = await db.execute(
                        "INSERT OR IGNORE INTO population_distributions "
                        "(category, dimension_1, dimension_2, dimension_3, "
                        "count, probability, source_year, source_dataset) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            row.category,
                            row.dimension_1,
                            row.dimension_2,
                            row.dimension_3,
                            row.count,
                            row.probability,
                            row.source_year,
                            row.source_dataset,
                        ),
                    )
                    if cursor.rowcount > 0:
                        inserted += 1
                    else:
                        skipped += 1
                except Exception:
                    logger.exception(
                        "Failed to insert population: %s/%s/%s",
                        row.category,
                        row.dimension_1,
                        row.dimension_2,
                    )
                    skipped += 1

            await db.commit()

    logger.info("Populations: inserted=%d, skipped=%d", inserted, skipped)
    return inserted, skipped


async def normalize_all(
    snapshot_records: Sequence[Any],
    population_records: Sequence[Any] | None = None,
    source_year: int = 2024,
    source_dataset: str = "census",
    total_population: float | None = None,
) -> NormalizeResult:
    """Normalize and insert all records into the database.

    Args:
        snapshot_records: Records with category/metric/value/period/source/source_url.
        population_records: Census records with dimension fields for population table.
        source_year: Year of the source data.
        source_dataset: Name of the source dataset.
        total_population: Total population for probability calculation.

    Returns:
        NormalizeResult with counts of inserted/skipped rows.
    """
    # Convert and insert snapshots
    snapshot_rows = to_snapshot_rows(snapshot_records)
    snap_inserted, snap_skipped = await insert_snapshots(snapshot_rows)

    # Convert and insert populations (if provided)
    pop_inserted, pop_skipped = 0, 0
    if population_records:
        pop_rows = to_population_rows(
            population_records,
            source_year=source_year,
            source_dataset=source_dataset,
            total_population=total_population,
        )
        pop_inserted, pop_skipped = await insert_populations(pop_rows)

    result = NormalizeResult(
        snapshots_inserted=snap_inserted,
        snapshots_skipped=snap_skipped,
        populations_inserted=pop_inserted,
        populations_skipped=pop_skipped,
    )
    logger.info(
        "Normalization complete: snapshots=%d/%d, populations=%d/%d (inserted/skipped)",
        snap_inserted,
        snap_skipped,
        pop_inserted,
        pop_skipped,
    )
    return result
