"""Unified scraper for Discuss.com.hk and Baby Kingdom (Discuz! forums).

Scrapes thread listings and content from configured Discuz!-based forums.
Tries RSS feed first, falls back to HTML scraping.

Usage (standalone):
    python -m backend.data_pipeline.discuz_forum_scraper
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

_MAX_PAGES_PER_FORUM = 5
_REQUEST_DELAY_SECONDS = 3.0
_REQUEST_TIMEOUT = 20.0

_USER_AGENTS: tuple[str, ...] = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
)

DISCUSS_FORUMS: tuple[dict[str, Any], ...] = (
    {"name": "時事新聞", "base_url": "https://www.discuss.com.hk", "fid": 12, "platform": "discuss"},
    {"name": "香港經濟", "base_url": "https://www.discuss.com.hk", "fid": 51, "platform": "discuss"},
    {"name": "地產", "base_url": "https://www.discuss.com.hk", "fid": 48, "platform": "discuss"},
)

BK_FORUMS: tuple[dict[str, Any], ...] = (
    {"name": "自由講場", "base_url": "https://www.baby-kingdom.com", "fid": 162, "platform": "baby_kingdom"},
    {"name": "親子理財", "base_url": "https://www.baby-kingdom.com", "fid": 226, "platform": "baby_kingdom"},
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ForumPost:
    """Immutable representation of a single forum thread."""

    title: str
    content: str
    reply_count: int
    view_count: int
    published: str
    forum_name: str
    source_url: str
    platform: str  # "discuss" | "baby_kingdom"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _random_ua() -> str:
    """Return a random user-agent string."""
    return random.choice(_USER_AGENTS)


def _make_headers() -> dict[str, str]:
    return {
        "User-Agent": _random_ua(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    }


def _parse_int(text: str | None) -> int:
    """Safely parse an integer from text, returning 0 on failure."""
    if not text:
        return 0
    cleaned = text.strip().replace(",", "")
    try:
        return int(cleaned)
    except (ValueError, TypeError):
        return 0


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------


class DiscuzForumScraper:
    """Async scraper for Discuz!-based forums (Discuss.com.hk, Baby Kingdom)."""

    def __init__(
        self,
        forums: tuple[dict[str, Any], ...] | None = None,
    ) -> None:
        self._forums: tuple[dict[str, Any], ...] = forums or (*DISCUSS_FORUMS, *BK_FORUMS)

    async def download(self) -> tuple[ForumPost, ...]:
        """Scrape all configured forums and return collected posts.

        Returns:
            Tuple of ForumPost. Empty tuple on complete failure.
        """
        if BeautifulSoup is None:
            logger.error("beautifulsoup4 not installed — cannot scrape Discuz forums")
            return ()

        all_posts: list[ForumPost] = []

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(_REQUEST_TIMEOUT, connect=10.0),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        ) as client:
            for forum in self._forums:
                try:
                    posts = await self._scrape_forum(client, forum)
                    all_posts.extend(posts)
                    logger.info(
                        "Scraped %d posts from %s/%s",
                        len(posts),
                        forum["platform"],
                        forum["name"],
                    )
                except Exception:
                    logger.warning(
                        "Failed to scrape %s/%s",
                        forum["platform"],
                        forum["name"],
                        exc_info=True,
                    )

        logger.info("Total Discuz posts scraped: %d", len(all_posts))
        return tuple(all_posts)

    async def _scrape_forum(
        self,
        client: httpx.AsyncClient,
        forum: dict[str, Any],
    ) -> tuple[ForumPost, ...]:
        """Scrape one forum: try RSS first, fall back to HTML.

        Args:
            client: Shared httpx client.
            forum: Forum config dict with keys: name, base_url, fid, platform.

        Returns:
            Tuple of ForumPost from this forum.
        """
        base_url = forum["base_url"]
        fid = forum["fid"]
        platform = forum["platform"]
        forum_name = forum["name"]

        # Try RSS first
        rss_url = f"{base_url}/forum.php?mod=rss&fid={fid}"
        try:
            rss_posts = await self._parse_rss(client, rss_url, forum_name, platform)
            if rss_posts:
                logger.info("RSS succeeded for %s/%s: %d posts", platform, forum_name, len(rss_posts))
                return tuple(rss_posts)
        except Exception:
            logger.debug("RSS unavailable for %s/%s, falling back to HTML", platform, forum_name)

        # Fall back to HTML scraping
        posts: list[ForumPost] = []
        for page in range(1, _MAX_PAGES_PER_FORUM + 1):
            try:
                page_posts = await self._scrape_page(client, base_url, fid, page, forum_name, platform)
                posts.extend(page_posts)
            except Exception:
                logger.warning("Failed to scrape page %d of %s/%s", page, platform, forum_name, exc_info=True)
                break

            await asyncio.sleep(_REQUEST_DELAY_SECONDS)

        return tuple(posts)

    async def _parse_rss(
        self,
        client: httpx.AsyncClient,
        rss_url: str,
        forum_name: str,
        platform: str,
    ) -> list[ForumPost]:
        """Parse RSS feed for a forum.

        Returns list of ForumPost, or empty list if RSS is not available.
        """
        resp = await client.get(rss_url, headers=_make_headers())
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml-xml")
        items = soup.find_all("item")
        if not items:
            return []

        posts: list[ForumPost] = []
        for item in items:
            title_tag = item.find("title")
            desc_tag = item.find("description")
            link_tag = item.find("link")
            pub_tag = item.find("pubDate")

            title = title_tag.get_text(strip=True) if title_tag else ""
            content = desc_tag.get_text(strip=True) if desc_tag else ""
            link = link_tag.get_text(strip=True) if link_tag else ""
            published = pub_tag.get_text(strip=True) if pub_tag else ""

            if not title:
                continue

            posts.append(
                ForumPost(
                    title=title,
                    content=content[:2000],
                    reply_count=0,
                    view_count=0,
                    published=published,
                    forum_name=forum_name,
                    source_url=link,
                    platform=platform,
                )
            )

        return posts

    async def _scrape_page(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        fid: int,
        page: int,
        forum_name: str,
        platform: str,
    ) -> list[ForumPost]:
        """Parse one page of thread listings from a Discuz forum.

        Args:
            client: Shared httpx client.
            base_url: Forum base URL.
            fid: Forum ID.
            page: Page number (1-indexed).
            forum_name: Human-readable forum name.
            platform: Platform identifier.

        Returns:
            List of ForumPost from this page.
        """
        url = f"{base_url}/forum.php?mod=forumdisplay&fid={fid}&page={page}"
        resp = await client.get(url, headers=_make_headers())
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")
        posts: list[ForumPost] = []

        # Discuz thread list: <tbody id="normalthread_XXX"> or <th class="new/common">
        thread_rows = soup.select("tbody[id^='normalthread_']")
        if not thread_rows:
            # Alternative selector for some Discuz skins
            thread_rows = soup.select("#threadlisttableid tbody[id^='normalthread']")

        for row in thread_rows:
            try:
                # Title + link
                title_tag = row.select_one("a.xst") or row.select_one("th a.s")
                if not title_tag:
                    continue

                title = title_tag.get_text(strip=True)
                href = title_tag.get("href", "")
                thread_url = href if href.startswith("http") else f"{base_url}/{href}"

                # Reply and view counts
                reply_td = row.select_one("td.num a")
                view_em = row.select_one("td.num em")
                reply_count = _parse_int(reply_td.get_text() if reply_td else None)
                view_count = _parse_int(view_em.get_text() if view_em else None)

                # Date
                date_tag = row.select_one("td.by em span") or row.select_one("td.by em")
                published = date_tag.get_text(strip=True) if date_tag else ""

                posts.append(
                    ForumPost(
                        title=title,
                        content="",  # Content requires opening each thread
                        reply_count=reply_count,
                        view_count=view_count,
                        published=published,
                        forum_name=forum_name,
                        source_url=thread_url,
                        platform=platform,
                    )
                )
            except Exception:
                logger.debug("Failed to parse thread row in %s/%s page %d", platform, forum_name, page, exc_info=True)
                continue

        return posts

    async def _parse_thread(
        self,
        client: httpx.AsyncClient,
        url: str,
        forum_name: str,
        platform: str,
    ) -> ForumPost | None:
        """Parse an individual thread page for its content.

        Args:
            client: Shared httpx client.
            url: Full thread URL.
            forum_name: Forum name for the record.
            platform: Platform identifier.

        Returns:
            ForumPost with content filled, or None on failure.
        """
        try:
            resp = await client.get(url, headers=_make_headers())
            resp.raise_for_status()
        except httpx.HTTPError:
            logger.debug("Failed to fetch thread: %s", url)
            return None

        soup = BeautifulSoup(resp.text, "lxml")

        # Title
        title_tag = soup.select_one("#thread_subject") or soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else ""

        # First post content
        post_div = soup.select_one(".t_f") or soup.select_one(".pct .pcb")
        content = post_div.get_text(strip=True)[:2000] if post_div else ""

        # Reply count from page info
        reply_span = soup.select_one("#postlist .pi strong")
        reply_count = _parse_int(reply_span.get_text() if reply_span else None)

        if not title:
            return None

        return ForumPost(
            title=title,
            content=content,
            reply_count=reply_count,
            view_count=0,
            published=datetime.now(tz=timezone.utc).isoformat(),
            forum_name=forum_name,
            source_url=url,
            platform=platform,
        )


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------


async def download_all_discuz(client: httpx.AsyncClient | None = None) -> list:
    """Entry point for the download pipeline.

    Returns a list with a single DownloadResult-like object for compatibility.
    The ``client`` parameter is accepted for API compatibility but not used
    (the scraper creates its own client with appropriate rate limiting).
    """
    scraper = DiscuzForumScraper()
    posts = await scraper.download()

    @dataclass(frozen=True)
    class _Result:
        row_count: int
        records: tuple[ForumPost, ...]

    return [_Result(row_count=len(posts), records=posts)]


if __name__ == "__main__":
    import asyncio as _asyncio

    logging.basicConfig(level=logging.INFO)
    results = _asyncio.run(download_all_discuz())
    for r in results:
        print(f"Downloaded {r.row_count} posts")
        for p in r.records[:3]:
            print(f"  [{p.platform}] {p.title[:60]}")
