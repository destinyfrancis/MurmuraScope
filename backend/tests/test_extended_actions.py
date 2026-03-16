"""Tests for Phase 1A: Extended Action Space.

Covers:
  - action_types model (enum, categories, mapping)
  - action_logger.log_action() for non-content actions
  - action diversity scoring (Shannon entropy)
  - backward compatibility (existing 'post' action type)
"""

from __future__ import annotations

import json
import math
import os
from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest
import pytest_asyncio

from backend.app.models.action_types import (
    ACTION_CATEGORY_MAP,
    CONTENT_ACTIONS,
    GRAPH_ACTIONS,
    TRACKED_ACTIONS,
    ActionCategory,
    ExtendedActionType,
    get_category,
)


# ---------------------------------------------------------------------------
# ActionType model tests
# ---------------------------------------------------------------------------


class TestExtendedActionType:
    """Tests for the ExtendedActionType enum and category mapping."""

    def test_enum_values_match_oasis(self):
        """Action type values must match OASIS ActionType.value strings."""
        assert ExtendedActionType.CREATE_POST.value == "create_post"
        assert ExtendedActionType.FOLLOW.value == "follow"
        assert ExtendedActionType.DO_NOTHING.value == "do_nothing"
        assert ExtendedActionType.REPOST.value == "repost"
        assert ExtendedActionType.MUTE.value == "mute"

    def test_all_types_have_category(self):
        """Every ExtendedActionType must map to an ActionCategory."""
        for at in ExtendedActionType:
            assert at in ACTION_CATEGORY_MAP, f"{at} missing from ACTION_CATEGORY_MAP"

    def test_content_creation_actions(self):
        """Content creation category should include post/repost/comment/quote."""
        content_types = {
            at for at, cat in ACTION_CATEGORY_MAP.items()
            if cat == ActionCategory.CONTENT_CREATION
        }
        assert ExtendedActionType.CREATE_POST in content_types
        assert ExtendedActionType.REPOST in content_types
        assert ExtendedActionType.QUOTE_POST in content_types
        assert ExtendedActionType.CREATE_COMMENT in content_types
        assert ExtendedActionType.POST in content_types  # legacy alias

    def test_social_management_actions(self):
        """Social management category should include follow/unfollow/mute."""
        social = {
            at for at, cat in ACTION_CATEGORY_MAP.items()
            if cat == ActionCategory.SOCIAL_MANAGEMENT
        }
        assert ExtendedActionType.FOLLOW in social
        assert ExtendedActionType.UNFOLLOW in social
        assert ExtendedActionType.MUTE in social
        assert ExtendedActionType.UNMUTE in social

    def test_passive_actions(self):
        """Passive category should include do_nothing and refresh."""
        passive = {
            at for at, cat in ACTION_CATEGORY_MAP.items()
            if cat == ActionCategory.PASSIVE
        }
        assert ExtendedActionType.DO_NOTHING in passive
        assert ExtendedActionType.REFRESH in passive

    def test_get_category_known(self):
        assert get_category("follow") == ActionCategory.SOCIAL_MANAGEMENT
        assert get_category("create_post") == ActionCategory.CONTENT_CREATION
        assert get_category("do_nothing") == ActionCategory.PASSIVE

    def test_get_category_unknown_falls_back_to_passive(self):
        assert get_category("unknown_action") == ActionCategory.PASSIVE
        assert get_category("") == ActionCategory.PASSIVE

    def test_content_actions_frozenset(self):
        assert "create_post" in CONTENT_ACTIONS
        assert "repost" in CONTENT_ACTIONS
        assert "follow" not in CONTENT_ACTIONS

    def test_graph_actions_frozenset(self):
        assert "follow" in GRAPH_ACTIONS
        assert "unfollow" in GRAPH_ACTIONS
        assert "mute" in GRAPH_ACTIONS
        assert "create_post" not in GRAPH_ACTIONS

    def test_tracked_actions_covers_all_non_post(self):
        for at in ExtendedActionType:
            if at == ExtendedActionType.POST:
                continue
            assert at.value in TRACKED_ACTIONS, f"{at.value} missing from TRACKED_ACTIONS"

    def test_backward_compat_post_alias(self):
        """The legacy 'post' action type should map to content_creation."""
        assert ExtendedActionType.POST.value == "post"
        assert ACTION_CATEGORY_MAP[ExtendedActionType.POST] == ActionCategory.CONTENT_CREATION


# ---------------------------------------------------------------------------
# ActionLogger.log_action() tests
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture()
async def action_db(tmp_path):
    """Create a temporary DB with simulation_actions table."""
    db_path = str(tmp_path / "test_actions.db")
    schema_path = os.path.join(
        os.path.dirname(__file__), "..", "database", "schema.sql"
    )
    async with aiosqlite.connect(db_path) as db:
        with open(schema_path, encoding="utf-8") as f:
            await db.executescript(f.read())
        await db.commit()
    return db_path


class TestActionLoggerLogAction:
    """Tests for ActionLogger.log_action() method."""

    @pytest.mark.asyncio
    async def test_log_follow_action(self, action_db):
        with patch("backend.scripts.action_logger.get_db") as mock_get_db:
            db = await aiosqlite.connect(action_db)
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=db)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            from backend.scripts.action_logger import ActionLogger

            logger = ActionLogger()
            logger._columns_ensured = True  # skip migration check

            result = await logger.log_action(
                session_id="test-session",
                round_number=5,
                oasis_username="agent_001",
                action_type="follow",
                platform="twitter",
                target_agent_username="agent_002",
            )

            assert result.oasis_username == "agent_001"
            assert result.sentiment == "neutral"
            assert result.topics == []
            await db.close()

    @pytest.mark.asyncio
    async def test_log_content_action_with_sentiment(self, action_db):
        with patch("backend.scripts.action_logger.get_db") as mock_get_db:
            db = await aiosqlite.connect(action_db)
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=db)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            from backend.scripts.action_logger import ActionLogger

            logger = ActionLogger()
            logger._columns_ensured = True

            result = await logger.log_action(
                session_id="test-session",
                round_number=3,
                oasis_username="agent_005",
                action_type="create_post",
                content="今日天氣好好啊！開心",
            )

            # Content actions should have sentiment analysis
            assert result.sentiment in ("positive", "negative", "neutral")
            await db.close()

    @pytest.mark.asyncio
    async def test_log_do_nothing_action(self, action_db):
        with patch("backend.scripts.action_logger.get_db") as mock_get_db:
            db = await aiosqlite.connect(action_db)
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=db)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            from backend.scripts.action_logger import ActionLogger

            logger = ActionLogger()
            logger._columns_ensured = True

            result = await logger.log_action(
                session_id="test-session",
                round_number=1,
                oasis_username="lurker_001",
                action_type="do_nothing",
            )

            assert result.sentiment == "neutral"
            assert result.topics == []
            await db.close()

    @pytest.mark.asyncio
    async def test_log_action_stores_info_as_content(self, action_db):
        with patch("backend.scripts.action_logger.get_db") as mock_get_db:
            db = await aiosqlite.connect(action_db)
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=db)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            from backend.scripts.action_logger import ActionLogger

            logger = ActionLogger()
            logger._columns_ensured = True

            result = await logger.log_action(
                session_id="test-session",
                round_number=2,
                oasis_username="agent_010",
                action_type="like_post",
                info={"post_id": 42, "user_name": "target_user"},
            )

            # Non-content action with info should store info JSON as content
            assert "post_id" in result.content
            await db.close()


# ---------------------------------------------------------------------------
# Action diversity scoring tests
# ---------------------------------------------------------------------------


class TestActionDiversity:
    """Tests for Shannon entropy computation on action type distributions."""

    def test_single_action_type_entropy_zero(self):
        """If all actions are the same type, entropy = 0."""
        counts = {"post": 100}
        entropy = _compute_entropy(counts)
        assert entropy == 0.0

    def test_two_equal_types_entropy_one(self):
        """Two equally distributed types yield entropy = 1.0."""
        counts = {"post": 50, "like_post": 50}
        entropy = _compute_entropy(counts)
        assert abs(entropy - 1.0) < 0.01

    def test_uniform_distribution_max_entropy(self):
        """12 equally distributed types yield entropy = log2(12) ~ 3.585."""
        types = [
            "create_post", "like_post", "dislike_post", "follow",
            "unfollow", "repost", "quote_post", "create_comment",
            "do_nothing", "mute", "search_posts", "trend",
        ]
        counts = {t: 100 for t in types}
        entropy = _compute_entropy(counts)
        expected = math.log2(12)
        assert abs(entropy - expected) < 0.01

    def test_skewed_distribution(self):
        """Skewed distribution should have lower entropy than uniform."""
        counts = {
            "create_post": 800,
            "like_post": 100,
            "do_nothing": 50,
            "follow": 30,
            "repost": 20,
        }
        entropy = _compute_entropy(counts)
        assert 0.0 < entropy < math.log2(5)

    def test_empty_distribution_zero(self):
        counts: dict[str, int] = {}
        assert _compute_entropy(counts) == 0.0

    def test_do_nothing_ratio(self):
        """DO_NOTHING should ideally be 15-30% of actions for realism."""
        counts = {
            "create_post": 400,
            "like_post": 200,
            "do_nothing": 150,  # 20% — within target range
            "follow": 50,
            "repost": 100,
            "search_posts": 50,
            "trend": 50,
        }
        total = sum(counts.values())
        lurk_ratio = counts["do_nothing"] / total
        assert 0.15 <= lurk_ratio <= 0.30


# ---------------------------------------------------------------------------
# Backward compatibility tests
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Ensure existing 'post' action type still works."""

    def test_post_is_content_action(self):
        assert "post" in CONTENT_ACTIONS

    def test_post_category_is_content_creation(self):
        assert get_category("post") == ActionCategory.CONTENT_CREATION


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_entropy(counts: dict[str, int]) -> float:
    """Shannon entropy of action type distribution (matches scorecard logic)."""
    total = sum(counts.values())
    if total == 0:
        return 0.0
    entropy = 0.0
    for cnt in counts.values():
        if cnt > 0:
            p = cnt / total
            entropy -= p * math.log2(p)
    return round(entropy, 4)
