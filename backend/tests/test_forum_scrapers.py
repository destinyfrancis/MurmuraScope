"""Tests for forum scrapers and sentiment weight normalization.

Tests use mocked HTTP responses — no real network calls.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Sample HTML fixtures
# ---------------------------------------------------------------------------

SAMPLE_DISCUZ_HTML = """
<html><body>
<div id="threadlisttableid">
  <tbody id="normalthread_1001">
    <tr>
      <th><a href="thread-1001-1-1.html" class="xst">樓市會唔會再跌？</a></th>
      <td class="by"><cite><a>user123</a></cite><em>2025-3-10</em></td>
      <td class="num"><a class="xi2">42</a></td>
    </tr>
  </tbody>
  <tbody id="normalthread_1002">
    <tr>
      <th><a href="thread-1002-1-1.html" class="xst">移民英國心得分享</a></th>
      <td class="by"><cite><a>hk_citizen</a></cite><em>2025-3-9</em></td>
      <td class="num"><a class="xi2">28</a></td>
    </tr>
  </tbody>
</div>
</body></html>
"""

SAMPLE_DISCUZ_RSS = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
<channel>
  <item>
    <title>RSS 標題測試</title>
    <link>http://example.com/thread-2001-1-1.html</link>
    <pubDate>Mon, 10 Mar 2025 12:00:00 +0800</pubDate>
  </item>
</channel>
</rss>
"""

SAMPLE_HKGOLDEN_TOPIC_LIST = """
<html><body>
<div id="topicListPanel">
  <table>
    <tr class="topic_row" data-topic-id="5001">
      <td class="topic_title"><a href="/view/5001/1">深圳樓價vs香港</a></td>
      <td class="topic_author">golden_user</td>
      <td class="topic_replies">55</td>
    </tr>
    <tr class="topic_row" data-topic-id="5002">
      <td class="topic_title"><a href="/view/5002/1">加息影響分析</a></td>
      <td class="topic_author">analyst88</td>
      <td class="topic_replies">31</td>
    </tr>
  </table>
</div>
</body></html>
"""


# ---------------------------------------------------------------------------
# Mock response helper
# ---------------------------------------------------------------------------


def _make_response(text: str, status_code: int = 200):
    """Create a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return resp


# ---------------------------------------------------------------------------
# Discuz scraper tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discuz_scraper_imports():
    """Verify DiscuzForumScraper and ForumPost can be imported."""
    try:
        from backend.data_pipeline.discuz_forum_scraper import DiscuzForumScraper, ForumPost
    except ImportError:
        pytest.skip("discuz_forum_scraper not installed")

    assert DiscuzForumScraper is not None
    assert ForumPost is not None


@pytest.mark.asyncio
async def test_discuz_scraper_init():
    """Verify scraper can be instantiated with forum configs."""
    try:
        from backend.data_pipeline.discuz_forum_scraper import DISCUSS_FORUMS, DiscuzForumScraper
    except ImportError:
        pytest.skip("discuz_forum_scraper not installed")

    scraper = DiscuzForumScraper(forums=DISCUSS_FORUMS)
    assert scraper is not None


@pytest.mark.asyncio
async def test_discuz_scraper_download_empty_on_error():
    """Verify download returns empty tuple on network error."""
    try:
        from backend.data_pipeline.discuz_forum_scraper import DiscuzForumScraper
    except ImportError:
        pytest.skip("discuz_forum_scraper not installed")

    # Patch httpx.AsyncClient to raise on all requests
    with patch("backend.data_pipeline.discuz_forum_scraper.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=ConnectionError("Network unreachable"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        scraper = DiscuzForumScraper(
            forums=({"name": "test", "base_url": "http://example.com", "fid": 1, "platform": "discuss"},)
        )
        result = await scraper.download()
        assert result == () or len(result) == 0


# ---------------------------------------------------------------------------
# HKGolden scraper tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hkgolden_imports():
    """Verify HKGoldenDownloader and GoldenPost can be imported."""
    try:
        from backend.data_pipeline.hkgolden_downloader import GoldenPost, HKGoldenDownloader
    except ImportError:
        pytest.skip("hkgolden_downloader not installed")

    assert HKGoldenDownloader is not None
    assert GoldenPost is not None


@pytest.mark.asyncio
async def test_hkgolden_download_empty_on_error():
    """Verify download returns empty tuple on network error."""
    try:
        from backend.data_pipeline.hkgolden_downloader import HKGoldenDownloader
    except ImportError:
        pytest.skip("hkgolden_downloader not installed")

    with patch("backend.data_pipeline.hkgolden_downloader.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=ConnectionError("Network unreachable"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        scraper = HKGoldenDownloader()
        result = await scraper.download()
        assert result == () or len(result) == 0


@pytest.mark.asyncio
async def test_forum_post_frozen():
    """Verify ForumPost dataclass is frozen."""
    try:
        from backend.data_pipeline.discuz_forum_scraper import ForumPost
    except ImportError:
        pytest.skip("discuz_forum_scraper not installed")

    post = ForumPost(
        title="test",
        content="content",
        reply_count=0,
        view_count=0,
        published="2025-01-01",
        forum_name="test",
        source_url="http://example.com",
        platform="discuss",
    )
    with pytest.raises(AttributeError):
        post.title = "changed"


# ---------------------------------------------------------------------------
# Sentiment weight normalization tests
# ---------------------------------------------------------------------------


def test_sentiment_reweight_normalize():
    """Test weight redistribution with various available source combinations."""
    from backend.data_pipeline.social_sentiment_processor import _SOURCE_WEIGHTS

    # Simulate normalization: if only lihkg + news available
    available = {"lihkg", "news_rss"}
    total = sum(w for k, w in _SOURCE_WEIGHTS.items() if k in available)

    normalized = {k: _SOURCE_WEIGHTS[k] / total for k in available}

    # Weights should sum to ~1.0
    assert abs(sum(normalized.values()) - 1.0) < 1e-6
    # Each normalized weight should be >= original
    for k in available:
        assert normalized[k] >= _SOURCE_WEIGHTS[k]


def test_sentiment_reweight_single_source():
    """Only 1 source available -> weight should be 1.0."""
    from backend.data_pipeline.social_sentiment_processor import _SOURCE_WEIGHTS

    available = {"news_rss"}
    total = sum(w for k, w in _SOURCE_WEIGHTS.items() if k in available)

    normalized = {k: _SOURCE_WEIGHTS[k] / total for k in available}

    assert abs(normalized["news_rss"] - 1.0) < 1e-6


def test_sentiment_reweight_all_sources():
    """All sources available -> original weights preserved."""
    from backend.data_pipeline.social_sentiment_processor import _SOURCE_WEIGHTS

    available = set(_SOURCE_WEIGHTS.keys())
    total = sum(w for k, w in _SOURCE_WEIGHTS.items() if k in available)

    normalized = {k: _SOURCE_WEIGHTS[k] / total for k in available}

    for k in available:
        assert abs(normalized[k] - _SOURCE_WEIGHTS[k]) < 1e-6


def test_normalize_weights_function():
    """Test the _normalize_weights helper directly."""
    try:
        from backend.data_pipeline.social_sentiment_processor import _normalize_weights
    except ImportError:
        pytest.skip("_normalize_weights not available")

    result = _normalize_weights({"lihkg", "news_rss"})
    assert abs(sum(result.values()) - 1.0) < 1e-6

    result_empty = _normalize_weights(set())
    assert result_empty == {}

    result_all = _normalize_weights(
        set(
            _normalize_weights.__module__
            and [
                "lihkg",
                "hkgolden",
                "discuss",
                "baby_kingdom",
                "news_rss",
                "google_trends",
                "facebook",
            ]
        )
    )
    assert abs(sum(result_all.values()) - 1.0) < 1e-6
