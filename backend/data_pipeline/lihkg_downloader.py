"""LIHKG social data downloader for HK social sentiment analysis.

Collects thread data from LIHKG public API for sentiment baseline.
Target categories: 吹水台(1), 政事台(3), 財經台(5), 上班台(25)

Features:
- Single-page download (current threads)
- Historical paginated download (multiple pages per category)
- Enhanced Cantonese NLP sentiment scoring

Note: LIHKG may block programmatic access. This module includes graceful
fallback behaviour — if the API is unreachable or blocked, it returns empty
results with a warning rather than raising an exception.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

from backend.app.utils.logger import get_logger

logger = get_logger("data_pipeline.lihkg")

_LIHKG_API_BASE = "https://lihkg.com/api_v2/thread/category"
_RAW_DIR = Path("data/raw/social/lihkg")
_RATE_LIMIT_SECONDS = 2.0
_DEFAULT_PAGES = 3  # pages to fetch per category in historical mode

# LIHKG category map: (cat_id, name)
_LIHKG_CATEGORIES: tuple[tuple[int, str], ...] = (
    (1, "吹水台"),
    (3, "政事台"),
    (5, "財經台"),
    (25, "上班台"),
)

_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "zh-HK,zh;q=0.9,en;q=0.8",
    "Referer": "https://lihkg.com/",
}

# ---------------------------------------------------------------------------
# Enhanced Cantonese NLP sentiment lexicon
# ---------------------------------------------------------------------------

# Positive sentiment terms (Cantonese + Traditional Chinese)
_POSITIVE_TERMS: frozenset[str] = frozenset(
    {
        # Standard positive
        "好",
        "靚",
        "正",
        "勁",
        "棒",
        "讚",
        "優秀",
        "出色",
        "卓越",
        "滿意",
        "開心",
        "快樂",
        "高興",
        "喜悅",
        "欣喜",
        "愉快",
        "幸福",
        "美好",
        "支持",
        "認同",
        "贊成",
        "同意",
        "推薦",
        "鼓勵",
        "感謝",
        "多謝",
        "進步",
        "改善",
        "提升",
        "增長",
        "發展",
        "成功",
        "勝利",
        "達成",
        # Cantonese slang / internet speak
        "正㗎",
        "好正",
        "勁正",
        "核突",
        "型",
        "巴閉",
        "威",
        "掂",
        "叻",
        "頂癮",
        "好爽",
        "爽歪歪",
        "無得頂",
        "一流",
        "超正",
        "係掂",
        "贏",
        "有hope",
        "搏到",
        "升",
        "加薪",
        "有著數",
        "著數",
        "好彩",
        "幸運",
        "中獎",
        "派息",
        "升值",
        # Finance positive
        "升市",
        "牛市",
        "回升",
        "反彈",
        "創新高",
        "跑贏",
        "跑嬴",
        # Housing positive
        "減價",
        "減租",
        "平盤",
        "筍盤",
    }
)

# Negative sentiment terms
_NEGATIVE_TERMS: frozenset[str] = frozenset(
    {
        # Standard negative
        "差",
        "衰",
        "爛",
        "廢",
        "劣",
        "壞",
        "失望",
        "難過",
        "傷心",
        "痛苦",
        "憤怒",
        "憎恨",
        "討厭",
        "反感",
        "批評",
        "譴責",
        "抗議",
        "不滿",
        "下跌",
        "衰退",
        "萎縮",
        "虧損",
        "失業",
        "裁員",
        "破產",
        "倒閉",
        "通脹",
        "加息",
        "加租",
        "加價",
        "貴",
        "負擔",
        "困難",
        "艱難",
        # Cantonese slang negative
        "衰格",
        "廢柴",
        "蠢",
        "蠢豬",
        "撚樣",
        "仆街",
        "撚",
        "撚你",
        "X你",
        "冇用",
        "冇料",
        "玩嘢",
        "串",
        "串到爆",
        "戇居",
        "戇鳩",
        "GG",
        "涼了",
        "凉",
        "攬炒",
        "完蛋",
        "出事",
        "大鑊",
        "死梗",
        "執笠",
        "炒魷",
        "炒",
        "炒散",
        "被炒",
        "被裁",
        "失業",
        # Finance negative
        "熊市",
        "跌市",
        "插水",
        "瀉",
        "急跌",
        "大跌",
        "崩盤",
        "爆煲",
        "跌",
        "蝕",
        "蝕錢",
        "蝕本",
        "虧",
        "輸錢",
        "輸",
        "慘",
        "慘烈",
        "損失",
        # Housing negative
        "加租",
        "加價",
        "貴租",
        "樓價高",
        "供唔起",
        "負資產",
        # Social/political negative
        "移民",
        "走佬",
        "離港",
        "走",
        "逃",
        "潤",
        "run",
        "打壓",
        "控制",
        "限制",
        "禁",
        "拘捕",
        "坐牢",
    }
)

# Intensifiers (amplify adjacent sentiment)
_INTENSIFIERS: frozenset[str] = frozenset(
    {
        "非常",
        "極",
        "好",
        "超",
        "勁",
        "特別",
        "相當",
        "十分",
        "真係",
        "真的",
        "完全",
        "絕對",
        "太",
        "咁",
        "咁樣",
        "好似",
        "最",
        "更",
        "更加",
    }
)

# Negation words
_NEGATIONS: frozenset[str] = frozenset(
    {
        "唔",
        "不",
        "沒有",
        "冇",
        "無",
        "並非",
        "並不",
        "非",
        "否",
        "未",
    }
)


def score_sentiment(text: str) -> tuple[str, float]:
    """Score Cantonese/Chinese text sentiment using lexicon lookup.

    Applies a sliding window to detect negation and intensification.
    Uses like/dislike ratios when available from thread metadata.

    Args:
        text: Thread title or content to score.

    Returns:
        Tuple of (sentiment_label, score) where label is one of
        "positive", "negative", "neutral" and score is in [-1.0, 1.0].
    """
    if not text:
        return "neutral", 0.0

    # Tokenise: split CJK chars individually, keep ASCII words intact
    tokens: list[str] = []
    for chunk in re.split(r"(\s+)", text):
        if not chunk.strip():
            continue
        # If chunk has CJK characters, split char by char
        if re.search(r"[\u4e00-\u9fff\u3400-\u4dbf]", chunk):
            tokens.extend(list(chunk))
        else:
            tokens.append(chunk.lower())

    raw_score = 0.0
    window = 4  # look-back window for negation/intensification

    for i, token in enumerate(tokens):
        if token in _POSITIVE_TERMS:
            base = 1.0
        elif token in _NEGATIVE_TERMS:
            base = -1.0
        else:
            continue

        # Check preceding window for negation or intensification
        preceding = tokens[max(0, i - window) : i]
        negated = any(neg in preceding for neg in _NEGATIONS)
        intensified = any(amp in preceding for amp in _INTENSIFIERS)

        score = base * (-1.0 if negated else 1.0) * (1.5 if intensified else 1.0)
        raw_score += score

    # Normalise to [-1, 1]
    if raw_score == 0.0:
        return "neutral", 0.0

    normalised = max(-1.0, min(1.0, raw_score / max(1, len(tokens) / 10)))

    if normalised > 0.1:
        return "positive", round(normalised, 4)
    if normalised < -0.1:
        return "negative", round(normalised, 4)
    return "neutral", round(normalised, 4)


def score_thread_sentiment(
    title: str,
    like_count: int,
    dislike_count: int,
) -> tuple[str, float]:
    """Combined sentiment score from title NLP + like/dislike ratio.

    Weights: 60% text NLP, 40% engagement ratio.
    """
    _, text_score = score_sentiment(title)

    total_votes = like_count + dislike_count
    if total_votes > 0:
        engagement_score = (like_count - dislike_count) / total_votes
    else:
        engagement_score = 0.0

    combined = 0.6 * text_score + 0.4 * engagement_score
    combined = max(-1.0, min(1.0, combined))

    if combined > 0.1:
        label = "positive"
    elif combined < -0.1:
        label = "negative"
    else:
        label = "neutral"

    return label, round(combined, 4)


@dataclass(frozen=True)
class LihkgThread:
    """Immutable representation of a single LIHKG thread."""

    thread_id: str
    title: str
    category: str
    category_id: int
    reply_count: int
    like_count: int
    dislike_count: int
    create_time: str  # ISO-8601 string
    sentiment: str = "neutral"  # "positive" | "negative" | "neutral"
    sentiment_score: float = 0.0


@dataclass(frozen=True)
class DownloadResult:
    """Immutable result from a single LIHKG category download."""

    category: str
    row_count: int
    records: tuple[LihkgThread, ...]
    error: str | None = None


def _parse_thread(item: dict, category_name: str, category_id: int) -> LihkgThread | None:
    """Parse a raw LIHKG API thread item into a frozen dataclass.

    Returns None if required fields are missing. Applies Cantonese NLP
    sentiment scoring to the thread title.
    """
    try:
        thread_id = str(item.get("thread_id", ""))
        title = str(item.get("title", "")).strip()
        if not thread_id or not title:
            return None

        create_ts = item.get("create_time", 0)
        try:
            create_time = datetime.fromtimestamp(int(create_ts), tz=timezone.utc).isoformat()
        except (ValueError, TypeError, OSError):
            create_time = datetime.now(tz=timezone.utc).isoformat()

        like_count = int(item.get("like_count", 0))
        dislike_count = int(item.get("dislike_count", 0))
        sentiment, sentiment_score = score_thread_sentiment(title, like_count, dislike_count)

        return LihkgThread(
            thread_id=thread_id,
            title=title,
            category=category_name,
            category_id=category_id,
            reply_count=int(item.get("no_of_reply", 0)),
            like_count=like_count,
            dislike_count=dislike_count,
            create_time=create_time,
            sentiment=sentiment,
            sentiment_score=sentiment_score,
        )
    except (KeyError, ValueError, TypeError) as exc:
        logger.debug("Skipping malformed thread item: %s", exc)
        return None


def _save_raw(cat_id: int, category_name: str, data: dict) -> None:
    """Persist raw API JSON to data/raw/social/lihkg/."""
    _RAW_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = _RAW_DIR / f"cat{cat_id}_{ts}.json"
    try:
        with open(filename, "w", encoding="utf-8") as fh:
            json.dump(
                {"category_id": cat_id, "category_name": category_name, "fetched_at": ts, "data": data},
                fh,
                ensure_ascii=False,
                indent=2,
            )
        logger.debug("Saved raw LIHKG data: %s", filename)
    except OSError as exc:
        logger.warning("Could not save raw LIHKG data for cat %d: %s", cat_id, exc)


async def _download_category(
    client: httpx.AsyncClient,
    cat_id: int,
    category_name: str,
) -> DownloadResult:
    """Fetch one LIHKG category page and return parsed threads.

    Handles HTTP errors and access-blocked responses gracefully.
    """
    url = f"{_LIHKG_API_BASE}?cat_id={cat_id}&page=1&count=30"
    try:
        resp = await client.get(url, headers=_REQUEST_HEADERS, timeout=20.0)

        if resp.status_code in (403, 429, 503):
            logger.warning(
                "LIHKG blocked access for cat %d (HTTP %d) — skipping",
                cat_id,
                resp.status_code,
            )
            return DownloadResult(
                category=category_name,
                row_count=0,
                records=(),
                error=f"HTTP {resp.status_code} — access blocked",
            )

        if resp.status_code != 200:
            logger.warning(
                "LIHKG API returned HTTP %d for cat %d",
                resp.status_code,
                cat_id,
            )
            return DownloadResult(
                category=category_name,
                row_count=0,
                records=(),
                error=f"HTTP {resp.status_code}",
            )

        data = resp.json()

        # LIHKG returns {"success": 0} when rate-limited or blocked
        if not data.get("success"):
            logger.warning("LIHKG API returned success=0 for cat %d", cat_id)
            return DownloadResult(
                category=category_name,
                row_count=0,
                records=(),
                error="LIHKG API success=0 (possibly rate-limited)",
            )

        _save_raw(cat_id, category_name, data)

        items = data.get("response", {}).get("items", [])
        threads: list[LihkgThread] = []
        for item in items:
            parsed = _parse_thread(item, category_name, cat_id)
            if parsed is not None:
                threads.append(parsed)

        logger.info("LIHKG cat %d (%s): %d threads fetched", cat_id, category_name, len(threads))
        return DownloadResult(
            category=category_name,
            row_count=len(threads),
            records=tuple(threads),
            error=None,
        )

    except httpx.TimeoutException:
        logger.warning("LIHKG request timed out for cat %d", cat_id)
        return DownloadResult(
            category=category_name,
            row_count=0,
            records=(),
            error="Request timed out",
        )
    except httpx.RequestError as exc:
        logger.warning("LIHKG network error for cat %d: %s", cat_id, exc)
        return DownloadResult(
            category=category_name,
            row_count=0,
            records=(),
            error=f"Network error: {exc}",
        )
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning("LIHKG response parse error for cat %d: %s", cat_id, exc)
        return DownloadResult(
            category=category_name,
            row_count=0,
            records=(),
            error=f"Parse error: {exc}",
        )


async def _download_category_historical(
    client: httpx.AsyncClient,
    cat_id: int,
    category_name: str,
    pages: int = _DEFAULT_PAGES,
) -> DownloadResult:
    """Fetch multiple pages of a LIHKG category for historical data.

    Paginates through `pages` pages (30 threads/page) with rate limiting.
    Deduplicates by thread_id. Stops early if blocked.

    Args:
        client: Shared httpx.AsyncClient.
        cat_id: LIHKG category ID.
        category_name: Human-readable category name.
        pages: Number of pages to fetch (default 3 = ~90 threads).

    Returns:
        DownloadResult with all unique threads across pages.
    """
    seen_ids: set[str] = set()
    all_threads: list[LihkgThread] = []

    for page in range(1, pages + 1):
        if page > 1:
            await asyncio.sleep(_RATE_LIMIT_SECONDS)

        url = f"{_LIHKG_API_BASE}?cat_id={cat_id}&page={page}&count=30"
        try:
            resp = await client.get(url, headers=_REQUEST_HEADERS, timeout=20.0)

            if resp.status_code in (403, 429, 503):
                logger.warning(
                    "LIHKG blocked for cat %d page %d (HTTP %d) — stopping pagination",
                    cat_id,
                    page,
                    resp.status_code,
                )
                break

            if resp.status_code != 200:
                logger.warning("LIHKG HTTP %d for cat %d page %d", resp.status_code, cat_id, page)
                break

            data = resp.json()
            if not data.get("success"):
                logger.warning("LIHKG success=0 for cat %d page %d — stopping", cat_id, page)
                break

            _save_raw(cat_id, category_name, data)
            items = data.get("response", {}).get("items", [])

            if not items:
                logger.debug("No items on cat %d page %d — end of data", cat_id, page)
                break

            for item in items:
                parsed = _parse_thread(item, category_name, cat_id)
                if parsed is not None and parsed.thread_id not in seen_ids:
                    seen_ids.add(parsed.thread_id)
                    all_threads.append(parsed)

        except (httpx.TimeoutException, httpx.RequestError, json.JSONDecodeError) as exc:
            logger.warning("LIHKG error on cat %d page %d: %s", cat_id, page, exc)
            break

    logger.info(
        "LIHKG historical cat %d (%s): %d unique threads across %d pages",
        cat_id,
        category_name,
        len(all_threads),
        pages,
    )
    return DownloadResult(
        category=category_name,
        row_count=len(all_threads),
        records=tuple(all_threads),
        error=None if all_threads else f"No threads fetched from cat {cat_id}",
    )


async def download_all_social(
    client: httpx.AsyncClient,
) -> list[DownloadResult]:
    """Download LIHKG threads from all target categories (current page).

    Enforces a 2-second rate limit between requests to avoid triggering
    LIHKG's anti-scraping measures. Returns empty results (not exceptions)
    if LIHKG is unreachable or returns blocked responses.

    Args:
        client: Shared httpx.AsyncClient from the pipeline orchestrator.

    Returns:
        List of DownloadResult, one per category. Row counts may be zero
        if the API was unavailable.
    """
    results: list[DownloadResult] = []

    for idx, (cat_id, category_name) in enumerate(_LIHKG_CATEGORIES):
        if idx > 0:
            await asyncio.sleep(_RATE_LIMIT_SECONDS)

        result = await _download_category(client, cat_id, category_name)
        results.append(result)

    total_threads = sum(r.row_count for r in results)
    blocked = [r for r in results if r.error is not None]
    logger.info(
        "LIHKG download complete: %d threads across %d categories (%d errors)",
        total_threads,
        len(results),
        len(blocked),
    )
    return results


async def download_historical_social(
    client: httpx.AsyncClient,
    pages: int = _DEFAULT_PAGES,
) -> list[DownloadResult]:
    """Download historical LIHKG threads (multiple pages per category).

    Fetches `pages` pages per category with rate limiting between each
    request. Deduplicates by thread_id across pages.

    Args:
        client: Shared httpx.AsyncClient from the pipeline orchestrator.
        pages: Pages to fetch per category (default 3, ~90 threads each).

    Returns:
        List of DownloadResult, one per category.
    """
    results: list[DownloadResult] = []

    for idx, (cat_id, category_name) in enumerate(_LIHKG_CATEGORIES):
        if idx > 0:
            await asyncio.sleep(_RATE_LIMIT_SECONDS)

        result = await _download_category_historical(client, cat_id, category_name, pages=pages)
        results.append(result)

    total_threads = sum(r.row_count for r in results)
    logger.info(
        "LIHKG historical download complete: %d threads, %d pages/category",
        total_threads,
        pages,
    )
    return results
