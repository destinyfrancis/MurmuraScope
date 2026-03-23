"""Tests for Phase 2: Feed Ranking Engine and Filter Bubble metrics.

Covers FeedAlgorithm enum, ALGORITHM_WEIGHTS, FeedRankingEngine ranking,
bubble computation, report aggregation, and persistence helpers.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.app.models.recommendation import (
    ALGORITHM_WEIGHTS,
    FeedAlgorithm,
    FilterBubbleIndex,
    FilterBubbleReport,
)
from backend.app.services.feed_ranker import (
    FeedRankingEngine,
    _gini_coefficient,
    _stance_to_bucket,
)

# ---------------------------------------------------------------------------
# FeedAlgorithm enum tests
# ---------------------------------------------------------------------------


class TestFeedAlgorithmEnum:
    def test_values_exist(self):
        assert FeedAlgorithm.CHRONOLOGICAL.value == "chronological"
        assert FeedAlgorithm.ENGAGEMENT_FIRST.value == "engagement_first"
        assert FeedAlgorithm.ECHO_CHAMBER.value == "echo_chamber"

    def test_from_string(self):
        assert FeedAlgorithm("engagement_first") == FeedAlgorithm.ENGAGEMENT_FIRST

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            FeedAlgorithm("invalid_algo")


class TestAlgorithmWeights:
    def test_all_three_presets_exist(self):
        assert FeedAlgorithm.CHRONOLOGICAL in ALGORITHM_WEIGHTS
        assert FeedAlgorithm.ENGAGEMENT_FIRST in ALGORITHM_WEIGHTS
        assert FeedAlgorithm.ECHO_CHAMBER in ALGORITHM_WEIGHTS

    def test_weights_sum_to_one(self):
        for algo, weights in ALGORITHM_WEIGHTS.items():
            total = sum(weights.values())
            assert abs(total - 1.0) < 1e-9, f"{algo}: weights sum to {total}"

    def test_chronological_is_pure_recency(self):
        w = ALGORITHM_WEIGHTS[FeedAlgorithm.CHRONOLOGICAL]
        assert w["recency"] == 1.0
        assert w["engagement"] == 0.0
        assert w["social_affinity"] == 0.0

    def test_echo_chamber_high_social_affinity(self):
        w = ALGORITHM_WEIGHTS[FeedAlgorithm.ECHO_CHAMBER]
        assert w["social_affinity"] >= 0.4

    def test_engagement_first_high_engagement(self):
        w = ALGORITHM_WEIGHTS[FeedAlgorithm.ENGAGEMENT_FIRST]
        assert w["engagement"] >= 0.3

    def test_required_keys_present(self):
        required = {"relevance", "recency", "engagement", "social_affinity", "controversy"}
        for algo, weights in ALGORITHM_WEIGHTS.items():
            assert set(weights.keys()) == required, f"{algo} missing keys"


# ---------------------------------------------------------------------------
# FeedRankingEngine._score_post
# ---------------------------------------------------------------------------


class TestScorePost:
    def test_chronological_pure_recency(self):
        """Chronological score = recency only, so same-round posts rank equal."""
        engine = FeedRankingEngine()
        weights = ALGORITHM_WEIGHTS[FeedAlgorithm.CHRONOLOGICAL]
        post_same_round = {
            "id": "1",
            "agent_id": 1,
            "round_number": 5,
            "content": "test",
            "sentiment": "neutral",
            "trust_score": 0.5,
        }
        post_older = {
            "id": "2",
            "agent_id": 2,
            "round_number": 1,
            "content": "test",
            "sentiment": "neutral",
            "trust_score": 0.5,
        }
        score_same = engine._score_post(post_same_round, 0.5, 5, weights)
        score_old = engine._score_post(post_older, 0.5, 5, weights)
        assert score_same > score_old

    def test_engagement_first_longer_content_higher(self):
        """Engagement proxy based on content length (within same-round, same recency)."""
        engine = FeedRankingEngine()
        weights = ALGORITHM_WEIGHTS[FeedAlgorithm.ENGAGEMENT_FIRST]
        post_long = {
            "id": "1",
            "agent_id": 1,
            "round_number": 3,
            "content": "a" * 200,
            "sentiment": "neutral",
            "trust_score": 0.5,
        }
        post_short = {
            "id": "2",
            "agent_id": 2,
            "round_number": 3,
            "content": "hi",
            "sentiment": "neutral",
            "trust_score": 0.5,
        }
        score_long = engine._score_post(post_long, 0.5, 3, weights)
        score_short = engine._score_post(post_short, 0.5, 3, weights)
        assert score_long >= score_short

    def test_echo_chamber_high_trust_ranks_higher(self):
        """Echo chamber boosts high-trust authors."""
        engine = FeedRankingEngine()
        weights = ALGORITHM_WEIGHTS[FeedAlgorithm.ECHO_CHAMBER]
        post_high_trust = {
            "id": "1",
            "agent_id": 1,
            "round_number": 3,
            "content": "test",
            "sentiment": "positive",
            "trust_score": 0.9,
        }
        post_low_trust = {
            "id": "2",
            "agent_id": 2,
            "round_number": 3,
            "content": "test",
            "sentiment": "positive",
            "trust_score": 0.1,
        }
        score_high = engine._score_post(post_high_trust, 0.5, 3, weights)
        score_low = engine._score_post(post_low_trust, 0.5, 3, weights)
        assert score_high > score_low

    def test_score_in_valid_range(self):
        """Score must be in [0, 1]."""
        engine = FeedRankingEngine()
        for algo, weights in ALGORITHM_WEIGHTS.items():
            post = {
                "id": "1",
                "agent_id": 1,
                "round_number": 5,
                "content": "test post",
                "sentiment": "positive",
                "trust_score": 0.5,
            }
            score = engine._score_post(post, 0.5, 5, weights)
            assert 0.0 <= score <= 1.0 + 1e-9, f"{algo}: score={score}"


# ---------------------------------------------------------------------------
# FeedRankingEngine.rank_feed
# ---------------------------------------------------------------------------


class TestRankFeed:
    def _make_rows(self, n: int) -> list:
        """Generate n mock DB rows."""
        return [(i, i, 5, f"Post content {i}", "neutral", "economy", 0.5) for i in range(1, n + 1)]

    @pytest.mark.asyncio
    async def test_returns_empty_with_no_posts(self):
        engine = FeedRankingEngine()
        mock_db = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])
        mock_db.execute = AsyncMock(return_value=mock_cursor)

        result = await engine.rank_feed("s", 1, 0.5, 5, FeedAlgorithm.ENGAGEMENT_FIRST, mock_db)
        assert result == []

    @pytest.mark.asyncio
    async def test_capped_at_feed_size(self):
        engine = FeedRankingEngine()
        # 50 posts > FEED_SIZE=20
        mock_db = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=self._make_rows(50))
        mock_db.execute = AsyncMock(return_value=mock_cursor)

        result = await engine.rank_feed("s", 1, 0.5, 5, FeedAlgorithm.ENGAGEMENT_FIRST, mock_db)
        assert len(result) <= engine.FEED_SIZE

    @pytest.mark.asyncio
    async def test_chronological_returns_most_recent_first(self):
        """Chronological algo: posts from later rounds should rank higher."""
        engine = FeedRankingEngine()
        rows = [
            (1, 1, 2, "old post", "neutral", "", 0.5),  # older
            (2, 2, 8, "new post", "neutral", "", 0.5),  # newer
        ]
        mock_db = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=rows)
        mock_db.execute = AsyncMock(return_value=mock_cursor)

        result = await engine.rank_feed("s", 1, 0.5, 10, FeedAlgorithm.CHRONOLOGICAL, mock_db)
        assert len(result) == 2
        assert result[0]["id"] == 2  # newer post first

    @pytest.mark.asyncio
    async def test_score_field_in_result(self):
        """Each post dict in result has a 'score' field."""
        engine = FeedRankingEngine()
        mock_db = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=self._make_rows(3))
        mock_db.execute = AsyncMock(return_value=mock_cursor)

        result = await engine.rank_feed("s", 1, 0.5, 5, FeedAlgorithm.ENGAGEMENT_FIRST, mock_db)
        for post in result:
            assert "score" in post
            assert isinstance(post["score"], float)


# ---------------------------------------------------------------------------
# compute_bubble_index tests
# ---------------------------------------------------------------------------


class TestComputeBubbleIndex:
    @pytest.mark.asyncio
    async def test_empty_feed_returns_bubble_score_one(self):
        engine = FeedRankingEngine()
        idx = await engine.compute_bubble_index(1, 0.5, [], 3)
        assert idx.bubble_score == 1.0
        assert idx.exposure_diversity == 0.0

    @pytest.mark.asyncio
    async def test_diverse_feed_low_bubble_score(self):
        """Feed with posts of all stance types should have low bubble score."""
        engine = FeedRankingEngine()
        feed = [
            {"agent_id": i, "sentiment": s, "round_number": 3}
            for i, s in enumerate(["positive", "negative", "neutral", "positive", "negative"])
        ]
        idx = await engine.compute_bubble_index(1, 0.5, feed, 3)
        assert idx.exposure_diversity > 0.0
        assert idx.bubble_score < 1.0

    @pytest.mark.asyncio
    async def test_single_author_max_source_concentration(self):
        """Feed with all posts from same author → max Herfindahl (1.0)."""
        engine = FeedRankingEngine()
        feed = [{"agent_id": 42, "sentiment": "positive", "round_number": 3} for _ in range(10)]
        idx = await engine.compute_bubble_index(1, 0.5, feed, 3)
        assert abs(idx.source_concentration - 1.0) < 1e-9

    @pytest.mark.asyncio
    async def test_multiple_authors_lower_concentration(self):
        """Multiple distinct authors → Herfindahl < 1.0."""
        engine = FeedRankingEngine()
        feed = [{"agent_id": i, "sentiment": "neutral", "round_number": 3} for i in range(10)]
        idx = await engine.compute_bubble_index(1, 0.5, feed, 3)
        assert idx.source_concentration < 1.0

    @pytest.mark.asyncio
    async def test_bubble_score_between_zero_and_one(self):
        """Bubble score must always be in [0, 1]."""
        engine = FeedRankingEngine()
        feed = [
            {"agent_id": 1, "sentiment": "positive", "round_number": 3},
            {"agent_id": 2, "sentiment": "negative", "round_number": 3},
        ]
        idx = await engine.compute_bubble_index(99, 0.0, feed, 3)
        assert 0.0 <= idx.bubble_score <= 1.0

    @pytest.mark.asyncio
    async def test_stance_divergence_computed(self):
        """Stance divergence is computed from feed sentiment vs agent stance."""
        engine = FeedRankingEngine()
        feed = [
            {"agent_id": 1, "sentiment": "negative", "round_number": 3},
        ]
        # Agent stance = +0.5, feed is negative → divergence > 0
        idx = await engine.compute_bubble_index(1, 0.5, feed, 3)
        assert idx.stance_divergence > 0.0


# ---------------------------------------------------------------------------
# compute_bubble_report tests
# ---------------------------------------------------------------------------


class TestComputeBubbleReport:
    @pytest.mark.asyncio
    async def test_empty_indices_zero_report(self):
        engine = FeedRankingEngine()
        report = await engine.compute_bubble_report("s", 5, FeedAlgorithm.ENGAGEMENT_FIRST, [])
        assert report.avg_bubble_score == 0.0
        assert report.gini_coefficient == 0.0

    @pytest.mark.asyncio
    async def test_pct_in_bubble_correct(self):
        """Percentage agents with bubble > 0.7 computed correctly."""
        engine = FeedRankingEngine()
        indices = [
            FilterBubbleIndex(1, 3, 0.3, 0.2, 0.5, 0.9),
            FilterBubbleIndex(2, 3, 0.5, 0.3, 0.4, 0.5),
            FilterBubbleIndex(3, 3, 0.8, 0.4, 0.3, 0.2),
            FilterBubbleIndex(4, 3, 0.2, 0.1, 0.6, 0.8),
        ]
        report = await engine.compute_bubble_report("s", 3, FeedAlgorithm.ENGAGEMENT_FIRST, indices)
        # 2 out of 4 agents have bubble > 0.7 → 0.5
        assert abs(report.pct_in_bubble - 0.5) < 1e-9

    @pytest.mark.asyncio
    async def test_algorithm_name_preserved(self):
        engine = FeedRankingEngine()
        report = await engine.compute_bubble_report(
            "s", 3, FeedAlgorithm.ECHO_CHAMBER, [FilterBubbleIndex(1, 3, 0.5, 0.3, 0.4, 0.6)]
        )
        assert report.algorithm_name == "echo_chamber"

    @pytest.mark.asyncio
    async def test_gini_coefficient_computed(self):
        engine = FeedRankingEngine()
        indices = [
            FilterBubbleIndex(1, 3, 0.5, 0.2, 0.4, 0.0),  # low
            FilterBubbleIndex(2, 3, 0.2, 0.1, 0.5, 1.0),  # high
        ]
        report = await engine.compute_bubble_report("s", 3, FeedAlgorithm.ENGAGEMENT_FIRST, indices)
        # Gini > 0 for unequal distribution
        assert report.gini_coefficient > 0.0


# ---------------------------------------------------------------------------
# Herfindahl and Gini helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_stance_to_bucket_ranges(self):
        assert _stance_to_bucket(-1.0) == 0
        assert _stance_to_bucket(-0.7) == 0
        assert _stance_to_bucket(-0.3) == 1
        assert _stance_to_bucket(0.0) == 2
        assert _stance_to_bucket(0.3) == 3
        assert _stance_to_bucket(0.8) == 4

    def test_gini_equal_distribution(self):
        """All equal → Gini = 0."""
        values = [0.5, 0.5, 0.5, 0.5]
        assert _gini_coefficient(values) == 0.0

    def test_gini_max_inequality(self):
        """One agent has all, rest have zero → Gini approaches 1."""
        values = [0.0, 0.0, 0.0, 1.0]
        g = _gini_coefficient(values)
        assert g > 0.5  # high inequality

    def test_gini_empty_list(self):
        assert _gini_coefficient([]) == 0.0

    def test_gini_single_value(self):
        assert _gini_coefficient([0.7]) == 0.0


# ---------------------------------------------------------------------------
# Persistence tests
# ---------------------------------------------------------------------------


class TestPersistFeeds:
    @pytest.mark.asyncio
    async def test_persist_feeds_calls_executemany(self):
        engine = FeedRankingEngine()
        mock_db = AsyncMock()
        feeds = {
            1: [{"id": "100", "agent_id": 2, "round_number": 3, "score": 0.8}],
            2: [{"id": "101", "agent_id": 1, "round_number": 3, "score": 0.6}],
        }
        await engine.persist_feeds("s", feeds, mock_db)
        mock_db.executemany.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_persist_feeds_empty_no_call(self):
        engine = FeedRankingEngine()
        mock_db = AsyncMock()
        await engine.persist_feeds("s", {}, mock_db)
        mock_db.executemany.assert_not_called()

    @pytest.mark.asyncio
    async def test_persist_bubble_report_uses_upsert(self):
        engine = FeedRankingEngine()
        mock_db = AsyncMock()
        report = FilterBubbleReport(
            session_id="s",
            round_number=5,
            avg_bubble_score=0.45,
            median_bubble_score=0.42,
            pct_in_bubble=0.2,
            algorithm_name="engagement_first",
            gini_coefficient=0.3,
        )
        await engine.persist_bubble_report(report, mock_db)
        call_sql = mock_db.execute.call_args[0][0]
        assert "ON CONFLICT" in call_sql
        mock_db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# FilterBubbleIndex model
# ---------------------------------------------------------------------------


class TestFilterBubbleIndexModel:
    def test_frozen(self):
        idx = FilterBubbleIndex(
            agent_id=1,
            round_number=3,
            exposure_diversity=0.5,
            stance_divergence=0.3,
            source_concentration=0.4,
            bubble_score=0.6,
        )
        with pytest.raises(Exception):
            idx.bubble_score = 0.9  # type: ignore[misc]

    def test_fields(self):
        idx = FilterBubbleIndex(
            agent_id=99,
            round_number=7,
            exposure_diversity=0.8,
            stance_divergence=0.2,
            source_concentration=0.1,
            bubble_score=0.15,
        )
        assert idx.agent_id == 99
        assert idx.bubble_score == 0.15


# ---------------------------------------------------------------------------
# FilterBubbleReport model
# ---------------------------------------------------------------------------


class TestFilterBubbleReportModel:
    def test_frozen(self):
        r = FilterBubbleReport(
            session_id="s",
            round_number=3,
            avg_bubble_score=0.4,
            median_bubble_score=0.38,
            pct_in_bubble=0.1,
            algorithm_name="chronological",
            gini_coefficient=0.2,
        )
        with pytest.raises(Exception):
            r.avg_bubble_score = 0.9  # type: ignore[misc]
