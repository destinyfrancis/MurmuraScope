"""Process LIHKG raw data into sentiment indicators.

Reads raw JSON files from data/raw/social/lihkg/, applies an extended
Cantonese sentiment lexicon (superset of action_logger.py keywords), and
writes aggregated SocialSentimentRecord rows into the social_sentiment table
via hk_data_snapshots for backward compatibility.

情感偵測現委託至 cantonese_lexicon 模組，支援廣東話句末助詞、否定詞及強化詞。

Usage (standalone):
    python -m backend.data_pipeline.social_sentiment_processor
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.utils.cantonese_lexicon import detect_sentiment as _detect_sentiment
from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("data_pipeline.social_sentiment")

_RAW_DIR = Path("data/raw/social/lihkg")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SocialSentimentRecord:
    """Immutable aggregated sentiment record for one LIHKG category period."""

    period: str  # e.g. "2024-01"
    category: str  # e.g. "吹水台"
    positive_ratio: float
    negative_ratio: float
    neutral_ratio: float
    thread_count: int
    total_engagement: int
    source: str = "lihkg"


# ---------------------------------------------------------------------------
# Raw file loading
# ---------------------------------------------------------------------------


def _load_raw_files() -> list[dict]:
    """Load all raw LIHKG JSON files from the raw data directory.

    Returns:
        List of raw data dicts. Empty list if directory does not exist.
    """
    if not _RAW_DIR.exists():
        logger.warning("Raw LIHKG directory not found: %s", _RAW_DIR)
        return []

    raw_files = sorted(_RAW_DIR.glob("*.json"))
    if not raw_files:
        logger.info("No raw LIHKG files found in %s", _RAW_DIR)
        return []

    loaded: list[dict] = []
    for path in raw_files:
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            loaded.append(data)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not load raw file %s: %s", path, exc)

    logger.info("Loaded %d raw LIHKG files", len(loaded))
    return loaded


def _extract_threads(raw_data: dict) -> list[dict]:
    """Extract thread items from a raw file dict."""
    return raw_data.get("data", {}).get("response", {}).get("items", [])


# ---------------------------------------------------------------------------
# Sentiment aggregation
# ---------------------------------------------------------------------------


def _aggregate_sentiment(
    threads: Sequence[dict],
    category_name: str,
    period: str,
) -> SocialSentimentRecord:
    """Aggregate thread-level sentiments into category-level ratios."""
    if not threads:
        return SocialSentimentRecord(
            period=period,
            category=category_name,
            positive_ratio=0.0,
            negative_ratio=0.0,
            neutral_ratio=1.0,
            thread_count=0,
            total_engagement=0,
        )

    counts = {"positive": 0, "negative": 0, "neutral": 0}
    total_engagement = 0

    for thread in threads:
        title = str(thread.get("title", ""))
        sentiment = _detect_sentiment(title)
        counts[sentiment] += 1

        reply_count = int(thread.get("no_of_reply", 0))
        like_count = int(thread.get("like_count", 0))
        dislike_count = int(thread.get("dislike_count", 0))
        total_engagement += reply_count + like_count + dislike_count

    n = len(threads)
    return SocialSentimentRecord(
        period=period,
        category=category_name,
        positive_ratio=round(counts["positive"] / n, 4),
        negative_ratio=round(counts["negative"] / n, 4),
        neutral_ratio=round(counts["neutral"] / n, 4),
        thread_count=n,
        total_engagement=total_engagement,
    )


# ---------------------------------------------------------------------------
# DB persistence
# ---------------------------------------------------------------------------


async def _persist_to_db(records: list[SocialSentimentRecord]) -> None:
    """Write sentiment records into the social_sentiment and hk_data_snapshots tables."""
    if not records:
        return

    async with get_db() as db:
        # social_sentiment table (primary storage)
        await db.executemany(
            """
            INSERT INTO social_sentiment
                (period, category, positive_ratio, negative_ratio, neutral_ratio,
                 thread_count, total_engagement, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    r.period,
                    r.category,
                    r.positive_ratio,
                    r.negative_ratio,
                    r.neutral_ratio,
                    r.thread_count,
                    r.total_engagement,
                    r.source,
                )
                for r in records
            ],
        )

        # hk_data_snapshots for backward-compatible data lake queries
        snapshot_rows: list[tuple] = []
        for r in records:
            snapshot_rows.extend(
                [
                    (
                        "social_sentiment",
                        f"lihkg_{r.category}_positive_ratio",
                        r.positive_ratio,
                        "ratio",
                        r.period,
                        r.source,
                        None,
                    ),
                    (
                        "social_sentiment",
                        f"lihkg_{r.category}_negative_ratio",
                        r.negative_ratio,
                        "ratio",
                        r.period,
                        r.source,
                        None,
                    ),
                    (
                        "social_sentiment",
                        f"lihkg_{r.category}_thread_count",
                        float(r.thread_count),
                        "count",
                        r.period,
                        r.source,
                        None,
                    ),
                    (
                        "social_sentiment",
                        f"lihkg_{r.category}_engagement",
                        float(r.total_engagement),
                        "count",
                        r.period,
                        r.source,
                        None,
                    ),
                ]
            )

        await db.executemany(
            """
            INSERT OR REPLACE INTO hk_data_snapshots
                (category, metric, value, unit, period, source, source_url)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            snapshot_rows,
        )

        await db.commit()

    logger.info("Persisted %d social sentiment records to DB", len(records))


# ---------------------------------------------------------------------------
# Public export
# ---------------------------------------------------------------------------


async def _load_news_sentiment() -> SocialSentimentRecord | None:
    """Aggregate sentiment from news_headlines table (populated by news_rss_downloader).

    Returns a single composite record with source='news_rss', or None if no data.
    """
    try:
        async with get_db() as db:
            cursor = await db.execute("SELECT title, sentiment FROM news_headlines ORDER BY created_at DESC LIMIT 200")
            rows = await cursor.fetchall()
    except Exception:
        logger.debug("news_headlines table not available")
        return None

    if not rows:
        return None

    counts = {"positive": 0, "negative": 0, "neutral": 0}
    for row in rows:
        sent = row["sentiment"] if row["sentiment"] in counts else _detect_sentiment(row["title"])
        counts[sent] += 1

    n = len(rows)
    period = datetime.now(tz=timezone.utc).strftime("%Y-%m")
    return SocialSentimentRecord(
        period=period,
        category="news_composite",
        positive_ratio=round(counts["positive"] / n, 4),
        negative_ratio=round(counts["negative"] / n, 4),
        neutral_ratio=round(counts["neutral"] / n, 4),
        thread_count=n,
        total_engagement=0,
        source="news_rss",
    )


async def _load_trends_sentiment() -> SocialSentimentRecord | None:
    """Derive sentiment signal from Google Trends data in hk_data_snapshots.

    Converts search interest into a rough positive/negative signal:
    - Rising trend for '移民' / 'emigration' → negative sentiment proxy
    - Rising trend for '投資' / 'investment' → positive sentiment proxy

    Returns a single composite record with source='google_trends', or None if no data.
    """
    try:
        async with get_db() as db:
            cursor = await db.execute(
                """SELECT metric, value FROM hk_data_snapshots
                WHERE category = 'search_trends'
                ORDER BY created_at DESC LIMIT 20"""
            )
            rows = await cursor.fetchall()
    except Exception:
        logger.debug("No search_trends data available")
        return None

    if not rows:
        return None

    neg_signals = sum(r["value"] for r in rows if "移民" in r["metric"] or "emigration" in r["metric"])
    pos_signals = sum(r["value"] for r in rows if "投資" in r["metric"] or "property" in r["metric"])
    total = neg_signals + pos_signals + 1.0  # avoid division by zero

    period = datetime.now(tz=timezone.utc).strftime("%Y-%m")
    return SocialSentimentRecord(
        period=period,
        category="trends_composite",
        positive_ratio=round(pos_signals / total, 4),
        negative_ratio=round(neg_signals / total, 4),
        neutral_ratio=round(max(0.0, 1.0 - pos_signals / total - neg_signals / total), 4),
        thread_count=len(rows),
        total_engagement=0,
        source="google_trends",
    )


# Source weights for multi-source aggregation
_SOURCE_WEIGHTS: dict[str, float] = {
    "lihkg": 0.25,
    "hkgolden": 0.15,
    "discuss": 0.15,
    "baby_kingdom": 0.10,
    "news_rss": 0.15,
    "google_trends": 0.10,
    "facebook": 0.10,
}


def _normalize_weights(available_sources: set[str]) -> dict[str, float]:
    """Re-normalize weights to sum to 1.0 based on available sources."""
    available = {k: v for k, v in _SOURCE_WEIGHTS.items() if k in available_sources}
    if not available:
        return {}
    total = sum(available.values())
    return {k: round(v / total, 4) for k, v in available.items()}


async def _load_forum_sentiment(
    source_key: str,
    posts: Sequence[Any],
    period: str,
) -> SocialSentimentRecord | None:
    """Build a composite sentiment record from forum posts (Discuz/HKGolden).

    Each post must have a ``title`` attribute.
    """
    if not posts:
        return None

    counts = {"positive": 0, "negative": 0, "neutral": 0}
    for post in posts:
        title = getattr(post, "title", "") or ""
        sentiment = _detect_sentiment(title)
        counts[sentiment] += 1

    n = len(posts)
    return SocialSentimentRecord(
        period=period,
        category=f"{source_key}_composite",
        positive_ratio=round(counts["positive"] / n, 4),
        negative_ratio=round(counts["negative"] / n, 4),
        neutral_ratio=round(counts["neutral"] / n, 4),
        thread_count=n,
        total_engagement=0,
        source=source_key,
    )


async def process_social_sentiment() -> list[SocialSentimentRecord]:
    """Multi-source sentiment aggregation.

    Sources: LIHKG, HKGolden, Discuss/BabyKingdom, News RSS, Google Trends.
    Weights are dynamically re-normalized based on which sources return data.

    Returns:
        List of SocialSentimentRecord (individual sources + composite).
    """
    records: list[SocialSentimentRecord] = []
    period = datetime.now(tz=timezone.utc).strftime("%Y-%m")
    source_records: dict[str, SocialSentimentRecord | None] = {}

    # 1. LIHKG (may be blocked — 403/429)
    raw_files = _load_raw_files()
    lihkg_composite: SocialSentimentRecord | None = None
    if raw_files:
        from collections import defaultdict

        category_threads: dict[str, list[dict]] = defaultdict(list)

        for raw in raw_files:
            cat_name = raw.get("category_name", "unknown")
            threads = _extract_threads(raw)
            category_threads[cat_name].extend(threads)

        for cat_name, threads in category_threads.items():
            record = _aggregate_sentiment(threads, cat_name, period)
            records.append(record)

        if records:
            avg_pos = sum(r.positive_ratio for r in records) / len(records)
            avg_neg = sum(r.negative_ratio for r in records) / len(records)
            lihkg_composite = SocialSentimentRecord(
                period=period,
                category="lihkg_composite",
                positive_ratio=avg_pos,
                negative_ratio=avg_neg,
                neutral_ratio=round(max(0.0, 1.0 - avg_pos - avg_neg), 4),
                thread_count=sum(r.thread_count for r in records),
                total_engagement=sum(r.total_engagement for r in records),
                source="lihkg",
            )
    source_records["lihkg"] = lihkg_composite

    # 2. HKGolden
    try:
        from backend.data_pipeline.hkgolden_downloader import HKGoldenDownloader

        golden_posts = await HKGoldenDownloader().download()
        golden_rec = await _load_forum_sentiment("hkgolden", golden_posts, period)
        if golden_rec:
            records.append(golden_rec)
        source_records["hkgolden"] = golden_rec
    except Exception:
        logger.warning("HKGolden scraper failed", exc_info=True)
        source_records["hkgolden"] = None

    # 3. Discuss.com.hk + Baby Kingdom
    try:
        from backend.data_pipeline.discuz_forum_scraper import DiscuzForumScraper

        all_discuz_posts = await DiscuzForumScraper().download()
        discuss_posts = tuple(p for p in all_discuz_posts if p.platform == "discuss")
        bk_posts = tuple(p for p in all_discuz_posts if p.platform == "baby_kingdom")

        discuss_rec = await _load_forum_sentiment("discuss", discuss_posts, period)
        if discuss_rec:
            records.append(discuss_rec)
        source_records["discuss"] = discuss_rec

        bk_rec = await _load_forum_sentiment("baby_kingdom", bk_posts, period)
        if bk_rec:
            records.append(bk_rec)
        source_records["baby_kingdom"] = bk_rec
    except Exception:
        logger.warning("Discuz scraper failed", exc_info=True)
        source_records["discuss"] = None
        source_records["baby_kingdom"] = None

    # 4. News RSS
    news_record = await _load_news_sentiment()
    if news_record:
        records.append(news_record)
    source_records["news_rss"] = news_record

    # 5. Google Trends
    trends_record = await _load_trends_sentiment()
    if trends_record:
        records.append(trends_record)
    source_records["google_trends"] = trends_record

    # 6. Weighted composite across all available sources
    available = {k: v for k, v in source_records.items() if v is not None}

    if available:
        weights = _normalize_weights(set(available.keys()))
        w_pos = 0.0
        w_neg = 0.0
        for src, rec in available.items():
            w = weights.get(src, 0.0)
            w_pos += rec.positive_ratio * w
            w_neg += rec.negative_ratio * w

        composite = SocialSentimentRecord(
            period=period,
            category="multi_source_composite",
            positive_ratio=round(w_pos, 4),
            negative_ratio=round(w_neg, 4),
            neutral_ratio=round(max(0.0, 1.0 - w_pos - w_neg), 4),
            thread_count=sum(r.thread_count for r in available.values()),
            total_engagement=sum(r.total_engagement for r in available.values()),
            source="multi_source_composite",
        )
        records.append(composite)

        logger.info(
            "Multi-source composite: +%.1f%% -%.1f%% sources=%s",
            composite.positive_ratio * 100,
            composite.negative_ratio * 100,
            list(available.keys()),
        )
    else:
        logger.warning("No sentiment sources available — returning empty results")

    try:
        await _persist_to_db(records)
    except Exception as exc:
        logger.error("Failed to persist social sentiment to DB: %s", exc)

    return records
