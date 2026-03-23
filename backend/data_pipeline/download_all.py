"""CLI script to run all HK data pipeline downloaders.

Usage:
    python -m backend.data_pipeline.download_all [--categories CATEGORY ...]

Examples:
    python -m backend.data_pipeline.download_all
    python -m backend.data_pipeline.download_all --categories census economy
    python -m backend.data_pipeline.download_all --categories property --normalize
"""

from __future__ import annotations

import argparse
import asyncio
import time
from dataclasses import dataclass
from typing import Any

import httpx

from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger, setup_logging
from backend.data_pipeline.calibration import CalibrationPipeline
from backend.data_pipeline.census_downloader import download_all_census
from backend.data_pipeline.china_macro_downloader import download_all_china_macro
from backend.data_pipeline.data_normalizer import normalize_all
from backend.data_pipeline.economy_downloader import download_all_economy
from backend.data_pipeline.education_downloader import download_all_education
from backend.data_pipeline.employment_downloader import download_all_employment
from backend.data_pipeline.fred_downloader import download_all_fred
from backend.data_pipeline.hk_retail_tourism_downloader import download_all_retail_tourism
from backend.data_pipeline.lihkg_downloader import download_all_social
from backend.data_pipeline.market_downloader import MarketRecord, download_all_market
from backend.data_pipeline.migration_parser import download_all_migration
from backend.data_pipeline.property_downloader import download_all_property
from backend.data_pipeline.rvd_downloader import download_all_rvd
from backend.data_pipeline.social_sentiment_processor import process_social_sentiment
from backend.data_pipeline.trade_downloader import download_all_trade
from backend.data_pipeline.transport_downloader import download_all_transport
from backend.data_pipeline.weather_downloader import download_all_weather

# New real-data downloaders
try:
    from backend.data_pipeline.yfinance_downloader import download_all_yfinance
except ImportError:
    download_all_yfinance = None  # type: ignore[assignment]

try:
    from backend.data_pipeline.censtatd_downloader import download_all_censtatd
except ImportError:
    download_all_censtatd = None  # type: ignore[assignment]

try:
    from backend.data_pipeline.news_rss_downloader import download_all_news
except ImportError:
    download_all_news = None  # type: ignore[assignment]

try:
    from backend.data_pipeline.google_trends_downloader import download_all_trends
except ImportError:
    download_all_trends = None  # type: ignore[assignment]

try:
    from backend.data_pipeline.discuz_forum_scraper import download_all_discuz
except ImportError:
    download_all_discuz = None  # type: ignore[assignment]

try:
    from backend.data_pipeline.hkgolden_downloader import download_all_hkgolden
except ImportError:
    download_all_hkgolden = None  # type: ignore[assignment]

try:
    from backend.data_pipeline.stock_downloader import download_all_stocks
except ImportError:
    download_all_stocks = None  # type: ignore[assignment]

setup_logging()
logger = get_logger("data_pipeline.cli")

ALL_CATEGORIES = (
    "census",
    "economy",
    "property",
    "rvd",
    "employment",
    "education",
    "migration",
    "weather",
    "transport",
    "market",
    "yfinance",
    "censtatd",
    "social",
    "china_macro",
    "fred",
    "retail_tourism",
    "trade",
    "news_rss",
    "google_trends",
    "discuss",
    "hkgolden",
    "stocks_weekly",
)

# Categories whose records use 'date' instead of 'period' and may lack
# 'category' or 'source_url'.  These need adaptation before normalize_all().
_ADAPT_CATEGORIES = frozenset(
    {
        "weather",
        "transport",
        "china_macro",
        "fred",
        "retail_tourism",
        "trade",
        "rvd",
        "yfinance",
        "censtatd",
        "news_rss",
        "google_trends",
        "stocks_weekly",
    }
)

# Forum scrapers return unstructured post objects (no numeric 'value' field).
# These are raw social text data — not inserted into hk_data_snapshots.
_FORUM_CATEGORIES = frozenset({"discuss", "hkgolden"})


@dataclass(frozen=True)
class DownloadSummary:
    """Immutable summary of the download pipeline run."""

    category: str
    datasets_attempted: int
    datasets_succeeded: int
    total_records: int
    elapsed_seconds: float
    error: str | None


# ---------------------------------------------------------------------------
# Record adapters
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _AdaptedRecord:
    """Minimal adapter that fills missing fields so normalize_all() works."""

    category: str
    metric: str
    value: float
    unit: str
    period: str
    source: str
    source_url: str


def _adapt_record(rec: Any, fallback_category: str) -> _AdaptedRecord:
    """Convert a record from a newer downloader into a normalizer-compatible form.

    Handles records that:
    - Use ``date`` instead of ``period``
    - Are missing ``category``  (e.g. FredRecord uses ``series_id`` as metric)
    - Are missing ``source_url``

    FredRecord maps ``series_id`` → ``metric`` and uses the ``fred`` fallback
    category so the result lands in hk_data_snapshots as category=fred.
    """
    # period: prefer explicit period attr, fall back to date
    period = str(getattr(rec, "period", None) or getattr(rec, "date", "") or "")
    # category
    category = getattr(rec, "category", None) or fallback_category
    # metric: FredRecord has series_id; TrendsRecord has keyword; others have metric
    metric = (
        getattr(rec, "metric", None) or getattr(rec, "series_id", None) or getattr(rec, "keyword", None) or "unknown"
    )
    # unit
    unit = getattr(rec, "unit", "") or ""
    # source_url
    source_url = getattr(rec, "source_url", "") or ""
    # value: standard 'value' attr; TrendsRecord uses 'interest_value'
    raw_value = getattr(rec, "value", None)
    if raw_value is None:
        raw_value = getattr(rec, "interest_value", 0.0)

    return _AdaptedRecord(
        category=category,
        metric=metric,
        value=float(raw_value),
        unit=unit,
        period=period,
        source=getattr(rec, "source", fallback_category),
        source_url=source_url,
    )


# ---------------------------------------------------------------------------
# Market-data direct INSERT
# ---------------------------------------------------------------------------


async def _insert_market_records(records: list[MarketRecord]) -> int:
    """Insert MarketRecord rows directly into the market_data table.

    Returns the number of rows inserted (skips duplicates via INSERT OR IGNORE).
    """
    if not records:
        return 0

    inserted = 0
    async with get_db() as db:
        # Ensure unique index to allow idempotent re-runs
        await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_market_unique ON market_data(date, asset_type, ticker)")
        for rec in records:
            try:
                cursor = await db.execute(
                    "INSERT OR IGNORE INTO market_data "
                    "(date, asset_type, ticker, open, close, high, low, volume, source) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        rec.date,
                        rec.asset_type,
                        rec.ticker,
                        rec.open,
                        rec.close,
                        rec.high,
                        rec.low,
                        rec.volume,
                        rec.source,
                    ),
                )
                if cursor.rowcount > 0:
                    inserted += 1
            except Exception:
                logger.exception(
                    "Failed to insert market_data: %s/%s/%s",
                    rec.date,
                    rec.asset_type,
                    rec.ticker,
                )
        await db.commit()

    logger.info("market_data: inserted=%d records", inserted)
    return inserted


# ---------------------------------------------------------------------------
# Category runner
# ---------------------------------------------------------------------------


async def _run_category(
    category: str,
    client: httpx.AsyncClient,
    normalize: bool,
) -> DownloadSummary:
    """Run a single category downloader and optionally normalise."""
    start = time.monotonic()
    logger.info("Starting download: %s", category)

    downloaders: dict[str, Any] = {
        "census": download_all_census,
        "economy": download_all_economy,
        "property": download_all_property,
        "employment": download_all_employment,
        "education": download_all_education,
        "migration": download_all_migration,
        "weather": download_all_weather,
        "transport": download_all_transport,
        "market": download_all_market,
        "rvd": download_all_rvd,
        "social": download_all_social,
        "china_macro": download_all_china_macro,
        "fred": download_all_fred,
        "retail_tourism": download_all_retail_tourism,
        "trade": download_all_trade,
    }
    # Register new downloaders if available
    if download_all_yfinance is not None:
        downloaders["yfinance"] = download_all_yfinance
    if download_all_censtatd is not None:
        downloaders["censtatd"] = download_all_censtatd
    # news_rss is handled as a special case below (manages its own DB writes)
    if download_all_trends is not None:
        downloaders["google_trends"] = download_all_trends
    if download_all_discuz is not None:
        downloaders["discuss"] = download_all_discuz
    if download_all_hkgolden is not None:
        downloaders["hkgolden"] = download_all_hkgolden

    # news_rss: special handler — manages its own DB writes, no positional client
    if category == "news_rss":
        start = time.monotonic()
        if download_all_news is None:
            return DownloadSummary(
                category=category,
                datasets_attempted=0,
                datasets_succeeded=0,
                total_records=0,
                elapsed_seconds=0.0,
                error="news_rss_downloader not available (feedparser not installed)",
            )
        try:
            result = await download_all_news()
            elapsed = time.monotonic() - start
            return DownloadSummary(
                category=category,
                datasets_attempted=result.sources_fetched,
                datasets_succeeded=result.sources_fetched if result.headline_count > 0 else 0,
                total_records=result.headline_count,
                elapsed_seconds=round(elapsed, 2),
                error=result.error,
            )
        except Exception as exc:
            elapsed = time.monotonic() - start
            logger.exception("Failed to download news_rss")
            return DownloadSummary(
                category=category,
                datasets_attempted=0,
                datasets_succeeded=0,
                total_records=0,
                elapsed_seconds=round(elapsed, 2),
                error=str(exc),
            )

    # stocks_weekly: special handler — no httpx client, calls download_all_stocks directly
    if category == "stocks_weekly":
        start = time.monotonic()
        if download_all_stocks is None:
            return DownloadSummary(
                category=category,
                datasets_attempted=0,
                datasets_succeeded=0,
                total_records=0,
                elapsed_seconds=0.0,
                error="stock_downloader not available (import failed)",
            )
        try:
            results_map = await download_all_stocks()
            total_rows = sum(results_map.values())
            succeeded = sum(1 for v in results_map.values() if v > 0)
            elapsed = time.monotonic() - start
            return DownloadSummary(
                category=category,
                datasets_attempted=len(results_map),
                datasets_succeeded=succeeded,
                total_records=total_rows,
                elapsed_seconds=round(elapsed, 2),
                error=None,
            )
        except Exception as exc:
            elapsed = time.monotonic() - start
            logger.exception("Failed to download stocks_weekly")
            return DownloadSummary(
                category=category,
                datasets_attempted=0,
                datasets_succeeded=0,
                total_records=0,
                elapsed_seconds=round(elapsed, 2),
                error=str(exc),
            )

    downloader = downloaders.get(category)
    if downloader is None:
        return DownloadSummary(
            category=category,
            datasets_attempted=0,
            datasets_succeeded=0,
            total_records=0,
            elapsed_seconds=0.0,
            error=f"Unknown category: {category}",
        )

    try:
        results = await downloader(client)
        total_records = sum(r.row_count for r in results)

        if normalize and total_records > 0:
            # ----------------------------------------------------------------
            # market: incompatible schema — write directly to market_data table
            # ----------------------------------------------------------------
            if category == "market":
                market_records: list[MarketRecord] = []
                for result in results:
                    for rec in result.records:
                        if isinstance(rec, MarketRecord):
                            market_records.append(rec)
                await _insert_market_records(market_records)
                logger.info("Inserted %d market records into market_data", len(market_records))

            # ----------------------------------------------------------------
            # social: run dedicated sentiment processor (writes social_sentiment
            # AND hk_data_snapshots internally)
            # ----------------------------------------------------------------
            elif category == "social":
                sentiment_records = await process_social_sentiment()
                logger.info(
                    "Social sentiment: %d aggregated records processed",
                    len(sentiment_records),
                )

            # ----------------------------------------------------------------
            # Forum scrapers: raw social text — skip hk_data_snapshots insert
            # ----------------------------------------------------------------
            elif category in _FORUM_CATEGORIES:
                logger.info(
                    "Forum category %s: %d posts scraped (not normalised into snapshots)",
                    category,
                    total_records,
                )

            # ----------------------------------------------------------------
            # Newer categories that use 'date' instead of 'period': adapt
            # records before passing to normalize_all()
            # ----------------------------------------------------------------
            elif category in _ADAPT_CATEGORIES:
                all_records: list[_AdaptedRecord] = []
                for result in results:
                    for rec in result.records:
                        all_records.append(_adapt_record(rec, category))

                await normalize_all(
                    snapshot_records=all_records,
                    population_records=None,
                    source_year=2024,
                    source_dataset=category,
                )
                logger.info("Normalised %d adapted records for %s", len(all_records), category)

            # ----------------------------------------------------------------
            # Standard categories (census, economy, property, employment,
            # education, migration): records already have period/source_url
            # ----------------------------------------------------------------
            else:
                all_records_std: list[Any] = []
                census_records: list[Any] = []

                for result in results:
                    for rec in result.records:
                        all_records_std.append(rec)
                        if category == "census" and hasattr(rec, "dimension_1"):
                            census_records.append(rec)

                await normalize_all(
                    snapshot_records=all_records_std,
                    population_records=census_records if census_records else None,
                    source_year=2024,
                    source_dataset=category,
                )
                logger.info("Normalised %d records for %s", len(all_records_std), category)

        elapsed = time.monotonic() - start
        return DownloadSummary(
            category=category,
            datasets_attempted=len(results),
            datasets_succeeded=len([r for r in results if r.row_count > 0]),
            total_records=total_records,
            elapsed_seconds=round(elapsed, 2),
            error=None,
        )
    except Exception as exc:
        elapsed = time.monotonic() - start
        logger.exception("Failed to download %s", category)
        return DownloadSummary(
            category=category,
            datasets_attempted=0,
            datasets_succeeded=0,
            total_records=0,
            elapsed_seconds=round(elapsed, 2),
            error=str(exc),
        )


async def run_pipeline(
    categories: tuple[str, ...] | None = None,
    normalize: bool = False,
) -> list[DownloadSummary]:
    """Run the full download pipeline for specified categories.

    Args:
        categories: Tuple of category names to download. None means all.
        normalize: Whether to normalise downloaded data into the database.

    Returns:
        List of DownloadSummary for each category.
    """
    target_categories = categories or ALL_CATEGORIES
    logger.info("Pipeline starting: categories=%s, normalize=%s", target_categories, normalize)

    summaries: list[DownloadSummary] = []

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(60.0, connect=15.0),
        follow_redirects=True,
        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
    ) as client:
        for category in target_categories:
            summary = await _run_category(category, client, normalize)
            summaries.append(summary)
            _print_summary(summary)

    # ----------------------------------------------------------------
    # Post-download calibration: fit coefficients from freshly loaded data
    # ----------------------------------------------------------------
    if normalize:
        try:
            pipeline = CalibrationPipeline()
            await pipeline.run_calibration()
            logger.info("Post-download calibration complete")
        except Exception:
            logger.exception("Post-download calibration failed (non-fatal)")

    return summaries


def _print_summary(summary: DownloadSummary) -> None:
    """Print a human-readable summary of a category download."""
    status = "OK" if summary.error is None else f"FAILED: {summary.error}"
    logger.info(
        "[%s] %s — datasets: %d/%d, records: %d, time: %.1fs",
        summary.category.upper(),
        status,
        summary.datasets_succeeded,
        summary.datasets_attempted,
        summary.total_records,
        summary.elapsed_seconds,
    )


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Download HK public data for MurmuraScope",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--categories",
        nargs="+",
        choices=list(ALL_CATEGORIES),
        default=None,
        help="Categories to download (default: all)",
    )
    parser.add_argument(
        "--normalize",
        action="store_true",
        default=False,
        help="Normalise downloaded data into the database",
    )

    args = parser.parse_args()
    categories = tuple(args.categories) if args.categories else None

    start = time.monotonic()
    summaries = asyncio.run(run_pipeline(categories=categories, normalize=args.normalize))
    total_elapsed = time.monotonic() - start

    # Final summary
    total_records = sum(s.total_records for s in summaries)
    failed = [s for s in summaries if s.error is not None]

    logger.info("=" * 60)
    logger.info("Pipeline complete in %.1fs", total_elapsed)
    logger.info("Total records: %d", total_records)
    if failed:
        logger.warning("Failed categories: %s", [s.category for s in failed])
    else:
        logger.info("All categories succeeded")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
