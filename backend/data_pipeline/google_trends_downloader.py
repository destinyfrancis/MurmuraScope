"""Google Trends downloader for HK-related search keywords.

Fetches interest-over-time data from Google Trends for keywords relevant to the
HK simulation (emigration, property prices, unemployment). Weekly data is
aggregated to quarterly means and stored in hk_data_snapshots as supplementary
sentiment signals (20% weight in sentiment composite).

Dependency: pytrends>=4.9.0 (optional — gracefully degrades if not installed).

Rate-limit handling: Google Trends enforces strict 429 limits. This module uses
a 24-hour in-memory cache and returns empty results on TooManyRequestsError
rather than retrying or falling back to hardcoded values.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass

from backend.app.utils.logger import get_logger

# ---------------------------------------------------------------------------
# Optional dependency — pytrends
# ---------------------------------------------------------------------------

try:
    from pytrends.request import TrendReq
    from pytrends.exceptions import TooManyRequestsError  # type: ignore[import-untyped]
    HAS_PYTRENDS = True
except ImportError:
    TrendReq = None  # type: ignore[assignment, misc]
    TooManyRequestsError = Exception  # type: ignore[assignment, misc]
    HAS_PYTRENDS = False

logger = get_logger("data_pipeline.google_trends")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KEYWORDS: tuple[str, ...] = (
    "移民 香港",
    "樓價",
    "失業",
    "emigration Hong Kong",
    "property price Hong Kong",
)

_SENTIMENT_WEIGHT: float = 0.20  # supplementary weight in sentiment composite

_CACHE_TTL_SECONDS: float = 86_400.0  # 24 hours

# Module-level cache
_cached_records: list[TrendsRecord] = []
_last_fetch_time: float = 0.0

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrendsRecord:
    """Immutable Google Trends observation (quarterly aggregated)."""

    period: str  # YYYY-QN format
    keyword: str
    interest_value: float  # 0-100 scale
    source: str = "google_trends"


@dataclass(frozen=True)
class DownloadResult:
    """Immutable result from Google Trends download."""

    category: str
    row_count: int
    records: tuple[TrendsRecord, ...]
    error: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_KEYWORD_SANITIZE_RE = re.compile(r"[^a-zA-Z0-9\u4e00-\u9fff_]")


def _sanitize_keyword(keyword: str) -> str:
    """Sanitize keyword for use as a DB metric name.

    Replaces spaces and special chars with underscores, lowercases ASCII.
    """
    sanitized = _KEYWORD_SANITIZE_RE.sub("_", keyword)
    return sanitized.strip("_").lower()


def _week_to_quarter(date_str: str) -> str:
    """Convert a date string (YYYY-MM-DD) to YYYY-QN format."""
    parts = date_str.split("-")
    if len(parts) < 2:
        return "unknown"
    month = int(parts[1])
    quarter = (month - 1) // 3 + 1
    return f"{parts[0]}-Q{quarter}"


def _aggregate_to_quarterly(
    weekly_data: dict[str, list[tuple[str, float]]],
) -> list[TrendsRecord]:
    """Aggregate weekly interest data to quarterly means.

    Args:
        weekly_data: Mapping of keyword -> list of (date_str, interest_value).

    Returns:
        List of TrendsRecord with quarterly aggregation.
    """
    records: list[TrendsRecord] = []

    for keyword, entries in weekly_data.items():
        quarterly_sums: dict[str, list[float]] = {}
        for date_str, value in entries:
            quarter = _week_to_quarter(date_str)
            quarterly_sums.setdefault(quarter, []).append(value)

        for quarter, values in sorted(quarterly_sums.items()):
            mean_value = round(sum(values) / len(values), 2)
            records.append(TrendsRecord(
                period=quarter,
                keyword=keyword,
                interest_value=mean_value,
            ))

    return records


# ---------------------------------------------------------------------------
# Fetch (sync, wrapped for async)
# ---------------------------------------------------------------------------


def _fetch_trends_sync(
    keywords: tuple[str, ...],
    timeframe: str = "today 5-y",
    geo: str = "HK",
) -> list[TrendsRecord]:
    """Fetch Google Trends data synchronously.

    pytrends is a synchronous library; this function is designed to be called
    via asyncio.to_thread().

    Raises:
        TooManyRequestsError: When Google returns HTTP 429.
        ImportError: When pytrends is not installed.
    """
    if not HAS_PYTRENDS:
        raise ImportError("pytrends is not installed (pip install pytrends>=4.9.0)")

    pytrends = TrendReq(hl="zh-TW", tz=480)  # HK timezone UTC+8

    # pytrends supports max 5 keywords per request
    keyword_list = list(keywords[:5])
    pytrends.build_payload(keyword_list, timeframe=timeframe, geo=geo)

    df = pytrends.interest_over_time()
    if df.empty:
        logger.warning("Google Trends returned empty dataframe for %s", keyword_list)
        return []

    # Build weekly data dict
    weekly_data: dict[str, list[tuple[str, float]]] = {}
    for kw in keyword_list:
        if kw not in df.columns:
            continue
        entries: list[tuple[str, float]] = []
        for date_idx, value in df[kw].items():
            date_str = str(date_idx.date())  # type: ignore[union-attr]
            entries.append((date_str, float(value)))
        weekly_data[kw] = entries

    return _aggregate_to_quarterly(weekly_data)


async def _fetch_trends(
    keywords: tuple[str, ...],
    timeframe: str = "today 5-y",
    geo: str = "HK",
) -> list[TrendsRecord]:
    """Async wrapper around pytrends (sync library).

    Delegates to asyncio.to_thread() to avoid blocking the event loop.
    """
    return await asyncio.to_thread(
        _fetch_trends_sync, keywords, timeframe, geo,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def download_all_trends(client: object = None) -> list[DownloadResult]:  # noqa: ARG001
    """Download Google Trends data for all HK-related keywords.

    Uses a 24-hour in-memory cache to avoid excessive API calls. On 429 or
    timeout errors, returns empty results with an error message (no fallback).

    Returns:
        List with a single DownloadResult (list for pipeline compatibility).
    """
    global _cached_records, _last_fetch_time  # noqa: PLW0603

    if not HAS_PYTRENDS:
        logger.warning("pytrends not installed — skipping Google Trends download")
        return [DownloadResult(
            category="search_trends",
            row_count=0,
            records=(),
            error="pytrends not installed (pip install pytrends>=4.9.0)",
        )]

    # Check 24h cache
    now = time.monotonic()
    if _cached_records and (now - _last_fetch_time) < _CACHE_TTL_SECONDS:
        logger.debug(
            "Google Trends cache hit (%d records, %.0fs remaining)",
            len(_cached_records),
            _CACHE_TTL_SECONDS - (now - _last_fetch_time),
        )
        return [DownloadResult(
            category="search_trends",
            row_count=len(_cached_records),
            records=tuple(_cached_records),
        )]

    try:
        records = await _fetch_trends(KEYWORDS)
        _cached_records = records
        _last_fetch_time = time.monotonic()
        logger.info("Google Trends: %d quarterly records fetched", len(records))
        return [DownloadResult(
            category="search_trends",
            row_count=len(records),
            records=tuple(records),
        )]
    except TooManyRequestsError:
        logger.warning("Google Trends 429 rate limit — returning empty results")
        return [DownloadResult(
            category="search_trends",
            row_count=0,
            records=(),
            error="Google Trends rate limit (429) — retry after 24h",
        )]
    except (TimeoutError, OSError) as exc:
        logger.warning("Google Trends network error: %s", exc)
        return [DownloadResult(
            category="search_trends",
            row_count=0,
            records=(),
            error=f"Network error: {exc}",
        )]
    except ImportError as exc:
        logger.warning("Google Trends import error: %s", exc)
        return [DownloadResult(
            category="search_trends",
            row_count=0,
            records=(),
            error=str(exc),
        )]


def get_trend_index(
    records: tuple[TrendsRecord, ...] | list[TrendsRecord],
    keyword: str,
) -> list[TrendsRecord]:
    """Extract trend records for a single keyword.

    Args:
        records: Collection of TrendsRecord from download_all_trends().
        keyword: Exact keyword string to filter by.

    Returns:
        List of TrendsRecord for the specified keyword, sorted by period.
    """
    filtered = [r for r in records if r.keyword == keyword]
    return sorted(filtered, key=lambda r: r.period)
