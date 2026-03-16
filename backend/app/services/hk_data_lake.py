"""HK public data query service.

Provides async query methods against the hk_data_snapshots and
population_distributions tables. Used by simulation agents to
fetch real HK macro/demographic data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("services.hk_data_lake")


@dataclass(frozen=True)
class DataPoint:
    """Immutable data point from hk_data_snapshots."""

    category: str
    metric: str
    value: float
    unit: str
    period: str
    source: str
    source_url: str


@dataclass(frozen=True)
class PopulationBucket:
    """Immutable population distribution bucket."""

    dimension_1: str
    dimension_2: str | None
    dimension_3: str | None
    count: int
    probability: float


@dataclass(frozen=True)
class MacroSnapshot:
    """Immutable macro-economic snapshot with latest indicators."""

    gdp: DataPoint | None
    cpi: DataPoint | None
    unemployment_rate: DataPoint | None
    prime_rate: DataPoint | None
    hibor_3m: DataPoint | None
    property_price_index: DataPoint | None
    population_total: DataPoint | None


def _row_to_datapoint(row: Any) -> DataPoint:
    """Convert a database row to an immutable DataPoint."""
    return DataPoint(
        category=row["category"],
        metric=row["metric"],
        value=row["value"],
        unit=row["unit"] or "",
        period=row["period"],
        source=row["source"],
        source_url=row["source_url"] or "",
    )


async def get_latest(category: str, metric: str) -> DataPoint | None:
    """Get the latest data point for a given category and metric.

    Args:
        category: Data category (e.g. "gdp", "employment", "property").
        metric: Specific metric name (e.g. "gdp_total", "unemployment_rate").

    Returns:
        The most recent DataPoint, or None if not found.
    """
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT category, metric, value, unit, period, source, source_url "
            "FROM hk_data_snapshots "
            "WHERE category = ? AND metric = ? "
            "ORDER BY period DESC, created_at DESC "
            "LIMIT 1",
            (category, metric),
        )
        row = await cursor.fetchone()

    if row is None:
        logger.debug("No data found for %s/%s", category, metric)
        return None

    return _row_to_datapoint(row)


async def get_time_series(
    category: str,
    metric: str,
    periods: int = 12,
) -> list[DataPoint]:
    """Get a time series of data points for a given category and metric.

    Args:
        category: Data category.
        metric: Specific metric name.
        periods: Maximum number of periods to return (most recent first).

    Returns:
        List of DataPoint ordered by period descending.
    """
    if periods < 1:
        raise ValueError("periods must be >= 1")
    if periods > 1000:
        raise ValueError("periods must be <= 1000")

    async with get_db() as db:
        cursor = await db.execute(
            "SELECT category, metric, value, unit, period, source, source_url "
            "FROM hk_data_snapshots "
            "WHERE category = ? AND metric = ? "
            "ORDER BY period DESC, created_at DESC "
            "LIMIT ?",
            (category, metric, periods),
        )
        rows = await cursor.fetchall()

    result = [_row_to_datapoint(row) for row in rows]
    logger.debug("Time series %s/%s: %d points", category, metric, len(result))
    return result


async def get_population_distribution(
    dimension: str,
    source_year: int | None = None,
) -> dict[str, PopulationBucket]:
    """Get population distribution by a given dimension.

    Args:
        dimension: The category/dimension to query (e.g. "age_sex", "district").
        source_year: Optional year filter. If None, uses the latest available year.

    Returns:
        Dict mapping dimension_1 values to PopulationBucket objects.
    """
    async with get_db() as db:
        if source_year is not None:
            cursor = await db.execute(
                "SELECT dimension_1, dimension_2, dimension_3, count, probability "
                "FROM population_distributions "
                "WHERE category = ? AND source_year = ? "
                "ORDER BY count DESC",
                (dimension, source_year),
            )
        else:
            # Get the latest source_year for this dimension
            year_cursor = await db.execute(
                "SELECT MAX(source_year) as max_year "
                "FROM population_distributions "
                "WHERE category = ?",
                (dimension,),
            )
            year_row = await year_cursor.fetchone()
            latest_year = year_row["max_year"] if year_row else None

            if latest_year is None:
                logger.debug("No population data found for dimension: %s", dimension)
                return {}

            cursor = await db.execute(
                "SELECT dimension_1, dimension_2, dimension_3, count, probability "
                "FROM population_distributions "
                "WHERE category = ? AND source_year = ? "
                "ORDER BY count DESC",
                (dimension, latest_year),
            )

        rows = await cursor.fetchall()

    result: dict[str, PopulationBucket] = {}
    for row in rows:
        key = row["dimension_1"]
        if row["dimension_2"]:
            key = f"{key}|{row['dimension_2']}"
        result[key] = PopulationBucket(
            dimension_1=row["dimension_1"],
            dimension_2=row["dimension_2"],
            dimension_3=row["dimension_3"],
            count=row["count"],
            probability=row["probability"],
        )

    logger.debug("Population distribution %s: %d buckets", dimension, len(result))
    return result


async def get_macro_snapshot() -> MacroSnapshot:
    """Get a snapshot of all latest macro-economic indicators.

    Returns:
        MacroSnapshot with the latest values for key indicators.
        Individual fields may be None if no data is available.
    """
    gdp = await get_latest("gdp", "gdp_total")
    if gdp is None:
        # Try alternative metric names
        gdp = await get_latest("gdp", "gdp_gdp_at_current_market_prices")

    cpi = await get_latest("price_index", "cpi_composite")
    if cpi is None:
        cpi = await get_latest("price_index", "cpi_all_items")

    unemployment = await get_latest("employment", "unemployment_rate")
    if unemployment is None:
        unemployment = await get_latest("employment", "unemployment_unemployment_rate")

    prime_rate = await get_latest("interest_rate", "prime_rate")
    hibor = await get_latest("interest_rate", "hibor_3m")
    property_idx = await get_latest("property", "price_index_all_classes")

    population = await get_latest("population", "total_population")

    snapshot = MacroSnapshot(
        gdp=gdp,
        cpi=cpi,
        unemployment_rate=unemployment,
        prime_rate=prime_rate,
        hibor_3m=hibor,
        property_price_index=property_idx,
        population_total=population,
    )
    logger.info("Macro snapshot assembled: %d/%d indicators available", _count_available(snapshot), 7)
    return snapshot


def _count_available(snapshot: MacroSnapshot) -> int:
    """Count how many indicators in a MacroSnapshot are non-None."""
    fields = (
        snapshot.gdp, snapshot.cpi, snapshot.unemployment_rate,
        snapshot.prime_rate, snapshot.hibor_3m,
        snapshot.property_price_index, snapshot.population_total,
    )
    return sum(1 for f in fields if f is not None)


async def get_market_data(
    ticker: str,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Retrieve market data from the market_data table.

    Args:
        ticker: Asset ticker symbol (e.g. "HSI", "USD/HKD").
        start_date: ISO date string (YYYY-MM-DD), inclusive.
        end_date: ISO date string (YYYY-MM-DD), inclusive.
        limit: Maximum rows to return.

    Returns:
        List of market data dicts ordered by date descending.
    """
    from backend.app.utils.db import get_db  # noqa: PLC0415
    import aiosqlite  # noqa: PLC0415
    import logging  # noqa: PLC0415

    _logger = logging.getLogger(__name__)

    conditions = ["ticker = ?"]
    params: list = [ticker]

    if start_date:
        conditions.append("date >= ?")
        params.append(start_date)
    if end_date:
        conditions.append("date <= ?")
        params.append(end_date)

    where = " AND ".join(conditions)
    params.append(limit)

    try:
        async with get_db() as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                f"SELECT * FROM market_data WHERE {where}"
                f" ORDER BY date DESC LIMIT ?",
                params,
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
    except Exception:
        _logger.exception("get_market_data failed ticker=%s", ticker)
        return []


async def search_metrics(
    category: str | None = None,
    query: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Search available metrics in the data lake.

    Args:
        category: Optional category filter.
        query: Optional text search in metric names.
        limit: Maximum results to return.

    Returns:
        List of dicts with category, metric, latest_period, latest_value.
    """
    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500")

    conditions: list[str] = []
    params: list[Any] = []

    if category:
        conditions.append("category = ?")
        params.append(category)
    if query:
        conditions.append("metric LIKE ?")
        params.append(f"%{query}%")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)

    sql = (
        f"SELECT category, metric, MAX(period) as latest_period, "
        f"value as latest_value, unit "
        f"FROM hk_data_snapshots "
        f"{where} "
        f"GROUP BY category, metric "
        f"ORDER BY category, metric "
        f"LIMIT ?"
    )

    async with get_db() as db:
        cursor = await db.execute(sql, params)
        rows = await cursor.fetchall()

    return [
        {
            "category": row["category"],
            "metric": row["metric"],
            "latest_period": row["latest_period"],
            "latest_value": row["latest_value"],
            "unit": row["unit"],
        }
        for row in rows
    ]
