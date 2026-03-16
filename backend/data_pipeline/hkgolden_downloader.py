"""HKGolden forum scraper.

Scrapes thread listings and content from HKGolden (高登討論區).
Targets: 吹水台 (BW), 時事台 (CA), 財經台 (FN).

Usage (standalone):
    python -m backend.data_pipeline.hkgolden_downloader
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://forum.hkgolden.com"
_MAX_PAGES_PER_CHANNEL = 3
_REQUEST_DELAY_SECONDS = 3.0
_REQUEST_TIMEOUT = 20.0

_CHANNELS: tuple[dict[str, str], ...] = (
    {"id": "BW", "name": "吹水台"},
    {"id": "CA", "name": "時事台"},
    {"id": "FN", "name": "財經台"},
)

_USER_AGENTS: tuple[str, ...] = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GoldenPost:
    """Immutable representation of a single HKGolden thread."""

    title: str
    content: str
    reply_count: int
    rating: int
    published: str
    channel: str
    source_url: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _random_ua() -> str:
    return random.choice(_USER_AGENTS)


def _make_headers() -> dict[str, str]:
    return {
        "User-Agent": _random_ua(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        "Referer": _BASE_URL,
    }


def _parse_int(text: str | None) -> int:
    if not text:
        return 0
    cleaned = text.strip().replace(",", "")
    try:
        return int(cleaned)
    except (ValueError, TypeError):
        return 0


# ---------------------------------------------------------------------------
# Downloader
# ---------------------------------------------------------------------------

class HKGoldenDownloader:
    """Async scraper for HKGolden forum."""

    def __init__(
        self,
        channels: tuple[dict[str, str], ...] | None = None,
    ) -> None:
        self._channels = channels or _CHANNELS

    async def download(self) -> tuple[GoldenPost, ...]:
        """Scrape all configured channels and return collected posts.

        Returns:
            Tuple of GoldenPost. Empty tuple on complete failure.
        """
        if BeautifulSoup is None:
            logger.error("beautifulsoup4 not installed — cannot scrape HKGolden")
            return ()

        all_posts: list[GoldenPost] = []

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(_REQUEST_TIMEOUT, connect=10.0),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        ) as client:
            for channel in self._channels:
                try:
                    posts = await self._scrape_channel(client, channel["id"], channel["name"])
                    all_posts.extend(posts)
                    logger.info("Scraped %d posts from HKGolden/%s", len(posts), channel["name"])
                except Exception:
                    logger.warning(
                        "Failed to scrape HKGolden/%s", channel["name"],
                        exc_info=True,
                    )

        logger.info("Total HKGolden posts scraped: %d", len(all_posts))
        return tuple(all_posts)

    async def _scrape_channel(
        self,
        client: httpx.AsyncClient,
        channel_id: str,
        channel_name: str,
    ) -> tuple[GoldenPost, ...]:
        """Scrape one channel, up to _MAX_PAGES_PER_CHANNEL pages.

        Args:
            client: Shared httpx client.
            channel_id: Channel code (e.g. "BW", "CA", "FN").
            channel_name: Human-readable channel name.

        Returns:
            Tuple of GoldenPost from this channel.
        """
        posts: list[GoldenPost] = []

        for page in range(1, _MAX_PAGES_PER_CHANNEL + 1):
            try:
                topic_metas = await self._parse_topic_list(client, channel_id, page)
                for meta in topic_metas:
                    posts.append(GoldenPost(
                        title=meta["title"],
                        content="",
                        reply_count=meta.get("reply_count", 0),
                        rating=meta.get("rating", 0),
                        published=meta.get("published", ""),
                        channel=channel_name,
                        source_url=meta.get("url", ""),
                    ))
            except Exception:
                logger.warning(
                    "Failed to parse HKGolden/%s page %d", channel_name, page,
                    exc_info=True,
                )
                break

            await asyncio.sleep(_REQUEST_DELAY_SECONDS)

        return tuple(posts)

    async def _parse_topic_list(
        self,
        client: httpx.AsyncClient,
        channel_id: str,
        page: int,
    ) -> list[dict[str, Any]]:
        """Parse one page of the topic listing.

        Args:
            client: Shared httpx client.
            channel_id: Channel code.
            page: Page number (1-indexed).

        Returns:
            List of dicts with keys: title, url, reply_count, rating, published.
        """
        url = f"{_BASE_URL}/channel/{channel_id}/page/{page}"
        resp = await client.get(url, headers=_make_headers())
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")
        topics: list[dict[str, Any]] = []

        # HKGolden topic rows — try multiple selectors for resilience
        rows = soup.select("div.topic-list-item") or soup.select("tr.topic_row") or soup.select("table.forum-list tr")

        for row in rows:
            try:
                # Title + link
                link_tag = row.select_one("a.topic-title") or row.select_one("a[href*='/thread/']")
                if not link_tag:
                    continue

                title = link_tag.get_text(strip=True)
                href = link_tag.get("href", "")
                topic_url = href if href.startswith("http") else f"{_BASE_URL}{href}"

                # Reply count
                reply_tag = row.select_one(".reply-count") or row.select_one("td.replies")
                reply_count = _parse_int(reply_tag.get_text() if reply_tag else None)

                # Rating
                rating_tag = row.select_one(".rating") or row.select_one(".like-count")
                rating = _parse_int(rating_tag.get_text() if rating_tag else None)

                # Date
                date_tag = row.select_one(".topic-date") or row.select_one("td.date") or row.select_one("time")
                published = date_tag.get_text(strip=True) if date_tag else ""

                if not title:
                    continue

                topics.append({
                    "title": title,
                    "url": topic_url,
                    "reply_count": reply_count,
                    "rating": rating,
                    "published": published,
                })
            except Exception:
                logger.debug("Failed to parse topic row in HKGolden/%s page %d", channel_id, page, exc_info=True)
                continue

        return topics

    async def _parse_topic(
        self,
        client: httpx.AsyncClient,
        topic_id: str,
    ) -> GoldenPost | None:
        """Parse an individual topic thread for its content.

        Args:
            client: Shared httpx client.
            topic_id: HKGolden topic ID.

        Returns:
            GoldenPost with content, or None on failure.
        """
        url = f"{_BASE_URL}/thread/{topic_id}"
        try:
            resp = await client.get(url, headers=_make_headers())
            resp.raise_for_status()
        except httpx.HTTPError:
            logger.debug("Failed to fetch topic: %s", url)
            return None

        soup = BeautifulSoup(resp.text, "lxml")

        # Title
        title_tag = soup.select_one("h1.thread-title") or soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else ""

        # First post content
        content_div = soup.select_one(".content-body") or soup.select_one("#post-content-0")
        content = content_div.get_text(strip=True)[:2000] if content_div else ""

        if not title:
            return None

        return GoldenPost(
            title=title,
            content=content,
            reply_count=0,
            rating=0,
            published=datetime.now(tz=timezone.utc).isoformat(),
            channel="",
            source_url=url,
        )


# ---------------------------------------------------------------------------
# Pipeline entry point
# ---------------------------------------------------------------------------

async def download_all_hkgolden(client: httpx.AsyncClient | None = None) -> list:
    """Entry point for the download pipeline.

    The ``client`` parameter is accepted for API compatibility but not used
    (the scraper creates its own client with appropriate rate limiting).

    Returns a list with a single DownloadResult-like object.
    """
    downloader = HKGoldenDownloader()
    posts = await downloader.download()

    @dataclass(frozen=True)
    class _Result:
        row_count: int
        records: tuple[GoldenPost, ...]

    return [_Result(row_count=len(posts), records=posts)]


if __name__ == "__main__":
    import asyncio as _asyncio

    logging.basicConfig(level=logging.INFO)
    results = _asyncio.run(download_all_hkgolden())
    for r in results:
        print(f"Downloaded {r.row_count} posts")
        for p in r.records[:3]:
            print(f"  [{p.channel}] {p.title[:60]}")
