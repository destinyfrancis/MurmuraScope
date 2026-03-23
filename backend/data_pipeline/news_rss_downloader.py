"""HK news RSS feed downloader for sentiment analysis.

Downloads headlines from RTHK and SCMP RSS feeds, categorises them
by topic, and stores results into ``hk_data_snapshots`` and
``news_headlines`` tables for downstream sentiment processing.

Dependency: feedparser>=6.0
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import httpx

from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("data_pipeline.news_rss")

# ---------------------------------------------------------------------------
# Constants — RSS feed URLs
# ---------------------------------------------------------------------------

_RTHK_LOCAL_EN = "https://rthk.hk/rthk/news/rss/e_expressnews_elocal.xml"
_RTHK_LOCAL_ZH = "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml"
_RTHK_FINANCE = "https://rthk.hk/rthk/news/rss/e_expressnews_efinance.xml"
_SCMP_RSS = "https://www.scmp.com/rss/91/feed"

_RTHK_FEEDS: tuple[tuple[str, str], ...] = (
    (_RTHK_LOCAL_EN, "rthk_en"),
    (_RTHK_LOCAL_ZH, "rthk_zh"),
    (_RTHK_FINANCE, "rthk_finance"),
)

_DEFAULT_TIMEOUT = 15

# ---------------------------------------------------------------------------
# Keyword sets for headline categorisation
# ---------------------------------------------------------------------------

_PROPERTY_KEYWORDS: frozenset[str] = frozenset(
    {
        "property",
        "housing",
        "flat",
        "rent",
        "mortgage",
        "ccl",
        "樓",
        "樓市",
        "樓價",
        "按揭",
        "地產",
        "租金",
        "公屋",
        "居屋",
    }
)

_EMPLOYMENT_KEYWORDS: frozenset[str] = frozenset(
    {
        "employment",
        "unemployment",
        "job",
        "wage",
        "salary",
        "labour",
        "layoff",
        "hiring",
        "redundancy",
        "就業",
        "失業",
        "裁員",
        "招聘",
        "人工",
        "勞工",
    }
)

_POLITICAL_KEYWORDS: frozenset[str] = frozenset(
    {
        "legco",
        "policy",
        "election",
        "government",
        "chief executive",
        "national security",
        "protest",
        "legislature",
        "political",
        "立法會",
        "施政",
        "選舉",
        "政府",
        "特首",
        "國安",
        "政治",
    }
)

_FINANCIAL_KEYWORDS: frozenset[str] = frozenset(
    {
        "stock",
        "hsi",
        "hang seng",
        "market",
        "finance",
        "bank",
        "interest rate",
        "hibor",
        "bond",
        "ipo",
        "exchange",
        "股市",
        "恒指",
        "金融",
        "銀行",
        "利率",
        "債券",
        "匯率",
    }
)

# ---------------------------------------------------------------------------
# DB DDL — news_headlines table (created if missing)
# ---------------------------------------------------------------------------

_CREATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS news_headlines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    published TEXT,
    source TEXT NOT NULL,
    url TEXT,
    category TEXT DEFAULT 'general',
    sentiment TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
"""

_CREATE_INDEX_SQL = """\
CREATE INDEX IF NOT EXISTS idx_news_source
    ON news_headlines(source);
"""

# ---------------------------------------------------------------------------
# Frozen dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NewsHeadline:
    """Immutable representation of a single news headline."""

    title: str
    published: str  # ISO-8601 datetime string
    source: str
    url: str
    category: str  # property / employment / political / financial / general


@dataclass(frozen=True)
class NewsDownloadResult:
    """Immutable result of a news download run."""

    headlines: tuple[NewsHeadline, ...]
    headline_count: int
    sources_fetched: int
    error: str | None


# ---------------------------------------------------------------------------
# Categorisation
# ---------------------------------------------------------------------------


def _categorize_headline(title: str) -> str:
    """Categorise a headline by keyword matching.

    Checks property, employment, political, and financial keyword sets
    in order of specificity.  Falls back to ``"general"`` when no
    keywords match.

    Args:
        title: The headline text (any language).

    Returns:
        One of ``"property"``, ``"employment"``, ``"political"``,
        ``"financial"``, or ``"general"``.
    """
    lower = title.lower()

    if any(kw in lower for kw in _PROPERTY_KEYWORDS):
        return "property"
    if any(kw in lower for kw in _EMPLOYMENT_KEYWORDS):
        return "employment"
    if any(kw in lower for kw in _POLITICAL_KEYWORDS):
        return "political"
    if any(kw in lower for kw in _FINANCIAL_KEYWORDS):
        return "financial"
    return "general"


# ---------------------------------------------------------------------------
# Feed fetching
# ---------------------------------------------------------------------------


def _parse_published(entry: dict) -> str:
    """Extract and normalise the published date from an RSS entry.

    Args:
        entry: A single feedparser entry dict.

    Returns:
        ISO-8601 datetime string, or current UTC time if parsing fails.
    """
    raw = entry.get("published") or entry.get("updated") or ""
    if not raw:
        return datetime.now(tz=timezone.utc).isoformat()
    try:
        dt = parsedate_to_datetime(raw)
        return dt.isoformat()
    except (TypeError, ValueError):
        return datetime.now(tz=timezone.utc).isoformat()


async def _fetch_feed(
    url: str,
    source_name: str,
    *,
    timeout: int = _DEFAULT_TIMEOUT,
) -> list[NewsHeadline]:
    """Fetch and parse a single RSS feed.

    Uses ``httpx`` for the HTTP request and delegates XML parsing to
    ``feedparser.parse`` via ``asyncio.to_thread`` so the event loop
    is not blocked.

    Args:
        url: RSS feed URL.
        source_name: Human-readable source label (e.g. ``"rthk_en"``).
        timeout: HTTP timeout in seconds.

    Returns:
        List of :class:`NewsHeadline` instances.  Empty on any error.
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=float(timeout), follow_redirects=True)

        if resp.status_code != 200:
            logger.warning(
                "Feed %s returned HTTP %d — skipping",
                source_name,
                resp.status_code,
            )
            return []

        feed = await asyncio.to_thread(feedparser.parse, resp.text)

        if feed.bozo and not feed.entries:
            logger.warning(
                "Feed %s is malformed and has no entries: %s",
                source_name,
                feed.bozo_exception,
            )
            return []

        headlines: list[NewsHeadline] = []
        for entry in feed.entries:
            title = (entry.get("title") or "").strip()
            if not title:
                continue

            headlines.append(
                NewsHeadline(
                    title=title,
                    published=_parse_published(entry),
                    source=source_name,
                    url=entry.get("link", ""),
                    category=_categorize_headline(title),
                )
            )

        logger.info("Feed %s: %d headlines fetched", source_name, len(headlines))
        return headlines

    except httpx.TimeoutException:
        logger.warning("Feed %s timed out after %ds", source_name, timeout)
        return []
    except Exception:
        logger.exception("Unexpected error fetching feed %s", source_name)
        return []


# ---------------------------------------------------------------------------
# Public download functions
# ---------------------------------------------------------------------------


async def download_rthk_headlines(
    *,
    timeout: int = _DEFAULT_TIMEOUT,
) -> list[NewsHeadline]:
    """Fetch headlines from all three RTHK RSS feeds concurrently.

    Args:
        timeout: Per-feed HTTP timeout in seconds.

    Returns:
        Combined list of :class:`NewsHeadline` from all RTHK feeds.
    """
    tasks = [_fetch_feed(url, name, timeout=timeout) for url, name in _RTHK_FEEDS]
    results = await asyncio.gather(*tasks)

    combined: list[NewsHeadline] = []
    for batch in results:
        combined.extend(batch)

    logger.info("RTHK total: %d headlines from %d feeds", len(combined), len(_RTHK_FEEDS))
    return combined


async def download_scmp_headlines(
    *,
    timeout: int = _DEFAULT_TIMEOUT,
) -> list[NewsHeadline]:
    """Fetch headlines from the SCMP RSS feed.

    Gracefully returns an empty list if the feed is blocked (HTTP 403)
    or times out — SCMP frequently restricts automated access.

    Args:
        timeout: HTTP timeout in seconds.

    Returns:
        List of :class:`NewsHeadline`.  Empty if blocked or on error.
    """
    headlines = await _fetch_feed(_SCMP_RSS, "scmp", timeout=timeout)
    if not headlines:
        logger.info("SCMP feed returned no headlines (may be blocked)")
    return headlines


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


async def _ensure_table() -> None:
    """Create the ``news_headlines`` table if it does not exist."""
    async with get_db() as db:
        await db.executescript(f"{_CREATE_TABLE_SQL}\n{_CREATE_INDEX_SQL}")
        await db.commit()


async def _store_headlines(headlines: Sequence[NewsHeadline]) -> int:
    """Persist headlines into the ``news_headlines`` table.

    Args:
        headlines: Sequence of headlines to store.

    Returns:
        Number of rows inserted.
    """
    if not headlines:
        return 0

    await _ensure_table()

    rows = [(h.title, h.published, h.source, h.url, h.category) for h in headlines]

    async with get_db() as db:
        await db.executemany(
            "INSERT INTO news_headlines (title, published, source, url, category) VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        await db.commit()

    logger.info("Stored %d headlines in news_headlines table", len(rows))
    return len(rows)


async def _store_snapshot_counts(headlines: Sequence[NewsHeadline]) -> None:
    """Record per-source headline counts in ``hk_data_snapshots``.

    Each source gets one row with ``category='news'``,
    ``metric=<source_name>``, ``value=<headline_count>``,
    and ``period=<today's date>``.

    Args:
        headlines: Sequence of fetched headlines.
    """
    if not headlines:
        return

    counts: dict[str, int] = {}
    for h in headlines:
        counts[h.source] = counts.get(h.source, 0) + 1

    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    async with get_db() as db:
        for source_name, count in counts.items():
            await db.execute(
                "INSERT OR REPLACE INTO hk_data_snapshots "
                "(category, metric, value, unit, period, source, source_url) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("news", source_name, float(count), "count", today, "rss", ""),
            )
        await db.commit()

    logger.info(
        "Snapshot counts stored for %d sources: %s",
        len(counts),
        counts,
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def download_all_news(
    *,
    timeout: int = _DEFAULT_TIMEOUT,
    include_scmp: bool = True,
) -> NewsDownloadResult:
    """Download headlines from all configured RSS feeds.

    Fetches RTHK feeds (always) and SCMP (optionally).  Persists
    results to ``news_headlines`` and ``hk_data_snapshots`` tables.

    Args:
        timeout: Per-feed HTTP timeout in seconds.
        include_scmp: Whether to attempt the SCMP feed (may be blocked).

    Returns:
        :class:`NewsDownloadResult` summarising the download run.
    """
    all_headlines: list[NewsHeadline] = []
    sources_fetched = 0
    error: str | None = None

    try:
        rthk = await download_rthk_headlines(timeout=timeout)
        all_headlines.extend(rthk)
        if rthk:
            sources_fetched += len(_RTHK_FEEDS)

        if include_scmp:
            scmp = await download_scmp_headlines(timeout=timeout)
            all_headlines.extend(scmp)
            if scmp:
                sources_fetched += 1

    except Exception as exc:
        error = f"News download failed: {exc}"
        logger.exception("Fatal error during news download")

    # Persist regardless of partial failures
    try:
        await _store_headlines(all_headlines)
        await _store_snapshot_counts(all_headlines)
    except Exception as exc:
        persist_err = f"Persistence error: {exc}"
        error = f"{error}; {persist_err}" if error else persist_err
        logger.exception("Failed to persist news headlines")

    result = NewsDownloadResult(
        headlines=tuple(all_headlines),
        headline_count=len(all_headlines),
        sources_fetched=sources_fetched,
        error=error,
    )

    logger.info(
        "News download complete: %d headlines from %d sources (error=%s)",
        result.headline_count,
        result.sources_fetched,
        result.error,
    )
    return result
