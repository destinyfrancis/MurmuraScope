"""Integration tests for OASIS fork hooks: attention economy, temporal activation,
collective actions, and extended action types.

Tests verify that services are callable and produce correct outputs,
using in-memory SQLite databases to avoid side effects.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import replace as dc_replace
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def event_loop():
    """Create a fresh event loop for each test."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def in_memory_db():
    """Create an in-memory SQLite database with core schema tables."""
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row

    # Create core tables needed by the hooks
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS agent_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            agent_type TEXT DEFAULT 'citizen',
            age INTEGER DEFAULT 35,
            sex TEXT DEFAULT 'M',
            district TEXT DEFAULT '中西區',
            occupation TEXT DEFAULT '專業人員',
            income_bracket TEXT DEFAULT 'middle',
            education_level TEXT DEFAULT 'tertiary',
            marital_status TEXT DEFAULT 'single',
            housing_type TEXT DEFAULT 'private',
            openness REAL DEFAULT 0.5,
            conscientiousness REAL DEFAULT 0.5,
            extraversion REAL DEFAULT 0.5,
            agreeableness REAL DEFAULT 0.5,
            neuroticism REAL DEFAULT 0.5,
            monthly_income INTEGER DEFAULT 25000,
            savings INTEGER DEFAULT 100000,
            political_stance REAL DEFAULT 0.5,
            oasis_username TEXT
        );
        CREATE TABLE IF NOT EXISTS simulation_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            round_number INTEGER NOT NULL,
            agent_id INTEGER,
            oasis_username TEXT,
            action_type TEXT DEFAULT 'post',
            platform TEXT DEFAULT 'facebook',
            content TEXT,
            target_agent_username TEXT,
            sentiment TEXT DEFAULT 'neutral',
            topics TEXT DEFAULT '[]',
            post_id TEXT,
            parent_action_id INTEGER,
            spread_depth INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS agent_relationships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            agent_a_id INTEGER NOT NULL,
            agent_b_id INTEGER NOT NULL,
            relationship_type TEXT DEFAULT 'follows',
            trust_score REAL DEFAULT 0.0,
            UNIQUE(session_id, agent_a_id, agent_b_id)
        );
        CREATE TABLE IF NOT EXISTS echo_chamber_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            round_number INTEGER NOT NULL,
            cluster_id INTEGER,
            agent_ids TEXT,
            modularity REAL DEFAULT 0.0
        );
        CREATE TABLE IF NOT EXISTS agent_attention (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            agent_id INTEGER NOT NULL,
            round_number INTEGER NOT NULL,
            topic TEXT NOT NULL,
            points_spent INTEGER NOT NULL DEFAULT 0,
            sensitivity REAL NOT NULL DEFAULT 1.0,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(session_id, agent_id, round_number, topic)
        );
        CREATE TABLE IF NOT EXISTS agent_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            group_name TEXT NOT NULL,
            agenda TEXT,
            leader_agent_id INTEGER NOT NULL,
            member_count INTEGER NOT NULL DEFAULT 0,
            shared_resources INTEGER NOT NULL DEFAULT 0,
            formed_round INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS agent_group_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            group_id INTEGER NOT NULL,
            agent_id INTEGER NOT NULL,
            joined_round INTEGER NOT NULL,
            UNIQUE(session_id, group_id, agent_id)
        );
        CREATE TABLE IF NOT EXISTS collective_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            group_id INTEGER,
            initiator_agent_id INTEGER NOT NULL,
            action_type TEXT NOT NULL,
            target TEXT,
            participant_count INTEGER NOT NULL DEFAULT 0,
            momentum REAL NOT NULL DEFAULT 0.1,
            consecutive_low_rounds INTEGER NOT NULL DEFAULT 0,
            round_initiated INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'building',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS collective_action_participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            action_id INTEGER NOT NULL,
            agent_id INTEGER NOT NULL,
            joined_round INTEGER NOT NULL,
            UNIQUE(session_id, action_id, agent_id)
        );
    """)
    await db.commit()

    yield db
    await db.close()


# ---------------------------------------------------------------------------
# Test: Attention Economy
# ---------------------------------------------------------------------------


class TestAttentionEconomyIntegration:
    """Tests for attention_economy.py hook integration."""

    def test_post_cost_short(self):
        """Short posts (<=100 chars) cost 1 attention point."""
        from backend.app.services.attention_economy import _post_cost
        assert _post_cost("hello") == 1

    def test_post_cost_medium(self):
        """Medium posts (101-300 chars) cost 2 attention points."""
        from backend.app.services.attention_economy import _post_cost
        assert _post_cost("x" * 150) == 2

    def test_post_cost_long(self):
        """Long posts (>300 chars) cost 3 attention points."""
        from backend.app.services.attention_economy import _post_cost
        assert _post_cost("x" * 350) == 3

    def test_extract_topics_hashtags(self):
        """Hashtags are extracted as topics."""
        from backend.app.services.attention_economy import _extract_topics
        topics = _extract_topics("今日 #樓市 好差 #移民 趨勢")
        assert "樓市" in topics
        assert "移民" in topics

    def test_extract_topics_keyword_heuristics(self):
        """Keyword heuristics detect HK-specific topics."""
        from backend.app.services.attention_economy import _extract_topics
        topics = _extract_topics("恒指大跌三百點")
        assert "金融" in topics

    def test_extract_topics_fallback(self):
        """Content without recognizable topics defaults to 'general'."""
        from backend.app.services.attention_economy import _extract_topics
        topics = _extract_topics("random english text with no keywords")
        assert topics == ["general"]

    def test_compute_sensitivity_fresh_topic(self):
        """Fresh topics (0 points spent) have full novelty bonus."""
        from backend.app.services.attention_economy import _compute_sensitivity
        assert _compute_sensitivity(0) == 1.0

    def test_compute_sensitivity_diminishing(self):
        """Heavy engagement reduces sensitivity."""
        from backend.app.services.attention_economy import _compute_sensitivity
        assert _compute_sensitivity(10) < 0.8
        assert _compute_sensitivity(100) < 0.5

    def test_compute_sensitivity_floor(self):
        """Sensitivity never drops below the diminishing cap."""
        from backend.app.services.attention_economy import _compute_sensitivity, _DIMINISHING_CAP
        assert _compute_sensitivity(10000) >= _DIMINISHING_CAP

    @pytest.mark.asyncio
    async def test_allocate_attention_budget(self):
        """allocate_attention returns a valid AttentionBudget."""
        from backend.app.services.attention_economy import allocate_attention
        posts = [
            {"content": "今日 #樓市 好差"},
            {"content": "恒指大跌三百點，好驚"},
        ]
        budget = await allocate_attention(
            session_id="test-session",
            round_num=1,
            agent_id=1,
            posts_this_round=posts,
        )
        assert budget.session_id == "test-session"
        assert budget.agent_id == 1
        assert budget.total_points == 24
        assert budget.remaining <= 24
        assert len(budget.allocations) > 0

    @pytest.mark.asyncio
    async def test_allocate_attention_fatigue(self):
        """Agents stop engaging when attention budget depleted."""
        from backend.app.services.attention_economy import allocate_attention
        # Generate many long posts to exhaust the 24-point budget
        posts = [{"content": "x" * 400} for _ in range(20)]
        budget = await allocate_attention(
            session_id="test-session",
            round_num=1,
            agent_id=1,
            posts_this_round=posts,
        )
        # Should have stopped before processing all 20 posts
        total_spent = sum(p for _, p in budget.allocations)
        assert total_spent <= 24

    def test_topic_sensitivity_from_budget(self):
        """compute_topic_sensitivity derives correct sensitivity map."""
        from backend.app.services.attention_economy import (
            AttentionBudget,
            compute_topic_sensitivity,
        )
        budget = AttentionBudget(
            session_id="s",
            agent_id=1,
            round_number=1,
            total_points=24,
            allocations=(("金融", 5), ("房地產", 1)),
            remaining=18,
        )
        sensitivities = compute_topic_sensitivity(budget)
        assert "金融" in sensitivities
        assert "房地產" in sensitivities
        # More points spent on 金融 → lower sensitivity
        assert sensitivities["金融"] < sensitivities["房地產"]

    @pytest.mark.asyncio
    async def test_batch_allocate_with_db(self):
        """batch_allocate_attention reads/writes to the DB."""
        from backend.app.services.attention_economy import batch_allocate_attention

        # Patch get_db to use in-memory DB
        async def _fake_get_db():
            db = await aiosqlite.connect(":memory:")
            await db.execute("""
                CREATE TABLE IF NOT EXISTS agent_attention (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    agent_id INTEGER NOT NULL,
                    round_number INTEGER NOT NULL,
                    topic TEXT NOT NULL,
                    points_spent INTEGER NOT NULL DEFAULT 0,
                    sensitivity REAL NOT NULL DEFAULT 1.0,
                    created_at TEXT DEFAULT (datetime('now')),
                    UNIQUE(session_id, agent_id, round_number, topic)
                )
            """)
            await db.commit()
            return db

        class FakeCtx:
            def __init__(self):
                self._db = None

            async def __aenter__(self):
                self._db = await aiosqlite.connect(":memory:")
                await self._db.execute("""
                    CREATE TABLE IF NOT EXISTS agent_attention (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        agent_id INTEGER NOT NULL,
                        round_number INTEGER NOT NULL,
                        topic TEXT NOT NULL,
                        points_spent INTEGER NOT NULL DEFAULT 0,
                        sensitivity REAL NOT NULL DEFAULT 1.0,
                        UNIQUE(session_id, agent_id, round_number, topic)
                    )
                """)
                await self._db.commit()
                return self._db

            async def __aexit__(self, *args):
                if self._db:
                    await self._db.close()

        with patch("backend.app.services.attention_economy.get_db", return_value=FakeCtx()):
            budgets = await batch_allocate_attention(
                session_id="test",
                round_num=1,
                agent_ids=[1, 2],
                posts=[{"content": "樓市升"}],
            )
            assert len(budgets) == 2


# ---------------------------------------------------------------------------
# Test: Temporal Activation
# ---------------------------------------------------------------------------


class TestTemporalActivationIntegration:
    """Tests for temporal_activation.py hook integration."""

    def test_round_to_hour_starts_at_8(self):
        """Round 0 maps to 8 AM HKT."""
        from backend.app.services.temporal_activation import TemporalActivationService
        svc = TemporalActivationService()
        assert svc.round_to_hour(0) == 8

    def test_round_to_hour_wraps(self):
        """Clock wraps every 24 rounds."""
        from backend.app.services.temporal_activation import TemporalActivationService
        svc = TemporalActivationService()
        assert svc.round_to_hour(24) == 8  # wraps back
        assert svc.round_to_hour(16) == 0  # midnight

    def test_generate_profile(self):
        """generate_profile returns a valid ActivityProfile."""
        from backend.app.services.temporal_activation import TemporalActivationService
        from backend.app.models.activity_profile import VALID_CHRONOTYPES
        svc = TemporalActivationService()
        rng = random.Random(42)
        profile = svc.generate_profile(agent_id=1, age=30, occupation="專業人員", rng=rng)
        assert profile.agent_id == 1
        assert profile.chronotype in VALID_CHRONOTYPES
        assert len(profile.activity_vector) == 24
        assert 0.0 < profile.base_activity_rate <= 1.0

    def test_elderly_morning_lark_bias(self):
        """Elderly agents are biased toward morning_lark chronotype."""
        from backend.app.services.temporal_activation import TemporalActivationService
        svc = TemporalActivationService()
        morning_count = 0
        trials = 100
        for i in range(trials):
            rng = random.Random(i)
            profile = svc.generate_profile(agent_id=i, age=70, occupation="退休", rng=rng)
            if profile.chronotype == "morning_lark":
                morning_count += 1
        # At least 40% should be morning_lark (expected 60%)
        assert morning_count >= 40

    def test_young_evening_owl_bias(self):
        """Young agents are biased toward evening_owl chronotype."""
        from backend.app.services.temporal_activation import TemporalActivationService
        svc = TemporalActivationService()
        owl_count = 0
        trials = 100
        for i in range(trials):
            rng = random.Random(i)
            profile = svc.generate_profile(agent_id=i, age=22, occupation="學生", rng=rng)
            if profile.chronotype == "evening_owl":
                owl_count += 1
        assert owl_count >= 40

    def test_should_activate_deterministic(self):
        """should_activate is deterministic with same RNG seed."""
        from backend.app.services.temporal_activation import TemporalActivationService
        from backend.app.models.activity_profile import ActivityProfile
        svc = TemporalActivationService()
        profile = ActivityProfile(
            agent_id=1,
            chronotype="standard",
            activity_vector=(0.5,) * 24,
            base_activity_rate=0.65,
        )
        results = []
        for _ in range(10):
            rng = random.Random(42)
            results.append(svc.should_activate(profile, round_number=5, rng=rng))
        # All should be identical with same seed
        assert all(r == results[0] for r in results)

    def test_should_activate_respects_min_probability(self):
        """Even at off-peak hours, min activation probability prevents total silence."""
        from backend.app.services.temporal_activation import TemporalActivationService
        from backend.app.models.activity_profile import ActivityProfile
        svc = TemporalActivationService()
        # Activity vector with 0.0 at all hours
        profile = ActivityProfile(
            agent_id=1,
            chronotype="standard",
            activity_vector=(0.0,) * 24,
            base_activity_rate=0.65,
        )
        # Over many trials, some activations should occur due to the 0.05 floor
        activations = 0
        for i in range(200):
            rng = random.Random(i)
            if svc.should_activate(profile, round_number=0, rng=rng):
                activations += 1
        # With 5% floor, expect ~10 activations out of 200
        assert activations > 0

    def test_hookconfig_has_temporal_fields(self):
        """HookConfig includes temporal activation config fields."""
        from backend.app.models.simulation_config import HookConfig
        hc = HookConfig()
        assert hc.temporal_activation_enabled is True
        assert hc.attention_economy_interval == 1


# ---------------------------------------------------------------------------
# Test: Collective Actions
# ---------------------------------------------------------------------------


class TestCollectiveActionsIntegration:
    """Tests for collective_actions.py hook integration."""

    def test_agent_group_frozen(self):
        """AgentGroup is immutable."""
        from backend.app.services.collective_actions import AgentGroup
        group = AgentGroup(
            id=1,
            session_id="test",
            group_name="測試聯盟",
            agenda="社區互助支援",
            leader_agent_id=10,
            member_count=5,
            shared_resources=5000,
            formed_round=3,
            status="active",
        )
        with pytest.raises(AttributeError):
            group.member_count = 10  # type: ignore[misc]

    def test_collective_action_frozen(self):
        """CollectiveAction is immutable."""
        from backend.app.services.collective_actions import CollectiveAction
        action = CollectiveAction(
            id=1,
            session_id="test",
            group_id=1,
            initiator_agent_id=10,
            action_type="protest",
            target="政策",
            participant_count=5,
            momentum=0.5,
            round_initiated=3,
            status="building",
        )
        with pytest.raises(AttributeError):
            action.momentum = 0.9  # type: ignore[misc]

    @pytest.mark.asyncio
    async def test_initiate_collective_action(self):
        """initiate_collective_action creates an action with initial momentum."""
        from backend.app.services.collective_actions import initiate_collective_action

        async def _mock_get_db():
            db = await aiosqlite.connect(":memory:")
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS agent_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL, group_name TEXT NOT NULL,
                    agenda TEXT, leader_agent_id INTEGER NOT NULL,
                    member_count INTEGER DEFAULT 0, shared_resources INTEGER DEFAULT 0,
                    formed_round INTEGER NOT NULL, status TEXT DEFAULT 'active',
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS agent_group_members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL, group_id INTEGER NOT NULL,
                    agent_id INTEGER NOT NULL, joined_round INTEGER NOT NULL,
                    UNIQUE(session_id, group_id, agent_id)
                );
                CREATE TABLE IF NOT EXISTS collective_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL, group_id INTEGER,
                    initiator_agent_id INTEGER NOT NULL, action_type TEXT NOT NULL,
                    target TEXT, participant_count INTEGER DEFAULT 0,
                    momentum REAL DEFAULT 0.1, consecutive_low_rounds INTEGER DEFAULT 0,
                    round_initiated INTEGER NOT NULL, status TEXT DEFAULT 'building',
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS collective_action_participants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL, action_id INTEGER NOT NULL,
                    agent_id INTEGER NOT NULL, joined_round INTEGER NOT NULL,
                    UNIQUE(session_id, action_id, agent_id)
                );
            """)
            await db.commit()
            return db

        class FakeCtx:
            def __init__(self):
                self._db = None
            async def __aenter__(self):
                self._db = await _mock_get_db()
                return self._db
            async def __aexit__(self, *args):
                if self._db:
                    await self._db.close()

        with patch("backend.app.services.collective_actions.get_db", return_value=FakeCtx()):
            result = await initiate_collective_action(
                session_id="test-session",
                group_id=None,
                initiator_id=10,
                action_type="protest",
                target="加租",
                round_num=5,
            )
            assert result is not None
            assert result.action_type == "protest"
            assert result.momentum == 0.15
            assert result.participant_count == 1
            assert result.status == "building"

    def test_hookconfig_has_collective_action_interval(self):
        """HookConfig includes collective_action_interval."""
        from backend.app.models.simulation_config import HookConfig
        hc = HookConfig()
        assert hc.collective_action_interval == 5

    def test_group_formation_already_in_hooks(self):
        """SocialHooksMixin has _process_group_formation method."""
        from backend.app.services.simulation_hooks_social import SocialHooksMixin
        assert hasattr(SocialHooksMixin, "_process_group_formation")

    def test_collective_momentum_already_in_hooks(self):
        """SocialHooksMixin has _process_collective_action_momentum method."""
        from backend.app.services.simulation_hooks_social import SocialHooksMixin
        assert hasattr(SocialHooksMixin, "_process_collective_action_momentum")


# ---------------------------------------------------------------------------
# Test: Extended Action Types
# ---------------------------------------------------------------------------


class TestExtendedActionTypes:
    """Tests for action_types.py extended action type taxonomy."""

    def test_action_category_enum(self):
        """ActionCategory has all expected categories."""
        from backend.app.models.action_types import ActionCategory
        assert ActionCategory.CONTENT_CREATION == "content_creation"
        assert ActionCategory.ENGAGEMENT == "engagement"
        assert ActionCategory.SOCIAL_MANAGEMENT == "social_management"
        assert ActionCategory.PASSIVE == "passive"
        assert ActionCategory.SEARCH == "search"

    def test_extended_action_types(self):
        """ExtendedActionType includes follow/unfollow/repost/lurk."""
        from backend.app.models.action_types import ExtendedActionType
        assert ExtendedActionType.FOLLOW.value == "follow"
        assert ExtendedActionType.UNFOLLOW.value == "unfollow"
        assert ExtendedActionType.REPOST.value == "repost"
        assert ExtendedActionType.DO_NOTHING.value == "do_nothing"
        assert ExtendedActionType.MUTE.value == "mute"
        assert ExtendedActionType.UNMUTE.value == "unmute"
        assert ExtendedActionType.REFRESH.value == "refresh"

    def test_get_category_known_types(self):
        """get_category returns correct category for known action types."""
        from backend.app.models.action_types import ActionCategory, get_category
        assert get_category("follow") == ActionCategory.SOCIAL_MANAGEMENT
        assert get_category("unfollow") == ActionCategory.SOCIAL_MANAGEMENT
        assert get_category("create_post") == ActionCategory.CONTENT_CREATION
        assert get_category("repost") == ActionCategory.CONTENT_CREATION
        assert get_category("like_post") == ActionCategory.ENGAGEMENT
        assert get_category("do_nothing") == ActionCategory.PASSIVE

    def test_get_category_unknown_fallback(self):
        """Unknown action types fall back to PASSIVE."""
        from backend.app.models.action_types import ActionCategory, get_category
        assert get_category("unknown_action") == ActionCategory.PASSIVE

    def test_content_actions_frozenset(self):
        """CONTENT_ACTIONS contains expected action types."""
        from backend.app.models.action_types import CONTENT_ACTIONS
        assert "create_post" in CONTENT_ACTIONS
        assert "repost" in CONTENT_ACTIONS
        assert "quote_post" in CONTENT_ACTIONS
        assert "follow" not in CONTENT_ACTIONS

    def test_graph_actions_frozenset(self):
        """GRAPH_ACTIONS contains social management actions."""
        from backend.app.models.action_types import GRAPH_ACTIONS
        assert "follow" in GRAPH_ACTIONS
        assert "unfollow" in GRAPH_ACTIONS
        assert "mute" in GRAPH_ACTIONS
        assert "create_post" not in GRAPH_ACTIONS

    def test_tracked_actions_complete(self):
        """TRACKED_ACTIONS includes all action types except legacy POST."""
        from backend.app.models.action_types import TRACKED_ACTIONS, ExtendedActionType
        for at in ExtendedActionType:
            if at == ExtendedActionType.POST:
                continue
            assert at.value in TRACKED_ACTIONS

    @pytest.mark.asyncio
    async def test_action_logger_log_action_extended_types(self):
        """ActionLogger.log_action handles extended action types (follow, like, lurk)."""
        from backend.scripts.action_logger import ActionLogger

        logger = ActionLogger()

        async def _mock_get_db():
            db = await aiosqlite.connect(":memory:")
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS simulation_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    round_number INTEGER NOT NULL,
                    agent_id INTEGER,
                    oasis_username TEXT,
                    action_type TEXT DEFAULT 'post',
                    platform TEXT DEFAULT 'facebook',
                    content TEXT,
                    target_agent_username TEXT,
                    sentiment TEXT DEFAULT 'neutral',
                    topics TEXT DEFAULT '[]',
                    post_id TEXT,
                    parent_action_id INTEGER,
                    spread_depth INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now'))
                );
            """)
            await db.commit()
            return db

        class FakeCtx:
            def __init__(self):
                self._db = None
            async def __aenter__(self):
                self._db = await _mock_get_db()
                return self._db
            async def __aexit__(self, *args):
                if self._db:
                    await self._db.close()

        with patch("backend.scripts.action_logger.get_db", return_value=FakeCtx()):
            logger._columns_ensured = True  # skip the ALTER TABLE check

            for action_type in ["follow", "unfollow", "like_post", "do_nothing", "repost"]:
                result = await logger.log_action(
                    session_id="test-session",
                    round_number=1,
                    oasis_username="test_user",
                    action_type=action_type,
                    platform="facebook",
                    target_agent_username="target_user",
                    info={"test": True},
                )
                assert result.session_id == "test-session"
                assert result.oasis_username == "test_user"


# ---------------------------------------------------------------------------
# Test: SimulationRunner Hook Wiring
# ---------------------------------------------------------------------------


class TestSimulationRunnerHookWiring:
    """Verify that all OASIS fork services are wired into SimulationRunner."""

    def test_runner_has_attention_allocation_hook(self):
        """SimulationRunner has _process_attention_allocation in Group 1."""
        from backend.app.services.simulation_hooks_agent import AgentHooksMixin
        assert hasattr(AgentHooksMixin, "_process_attention_allocation")

    def test_runner_has_temporal_activation_methods(self):
        """SimulationRunner has temporal activation gating methods."""
        from backend.app.services.simulation_runner import SimulationRunner
        assert hasattr(SimulationRunner, "_is_agent_active")
        assert hasattr(SimulationRunner, "_load_activity_profiles")

    def test_runner_has_group_formation_hook(self):
        """SimulationRunner has _process_group_formation."""
        from backend.app.services.simulation_hooks_social import SocialHooksMixin
        assert hasattr(SocialHooksMixin, "_process_group_formation")

    def test_runner_has_collective_momentum_hook(self):
        """SimulationRunner has _process_collective_action_momentum."""
        from backend.app.services.simulation_hooks_social import SocialHooksMixin
        assert hasattr(SocialHooksMixin, "_process_collective_action_momentum")

    def test_runner_has_handle_action_update(self):
        """SimulationRunner has _handle_action_update for extended action types."""
        from backend.app.services.simulation_runner import SimulationRunner
        assert hasattr(SimulationRunner, "_handle_action_update")

    def test_runner_preset_default(self):
        """SimulationRunner defaults to PRESET_STANDARD."""
        from backend.app.services.simulation_runner import SimulationRunner
        runner = SimulationRunner(dry_run=True)
        assert runner._preset.name == "standard"
        assert runner._preset.agents == 300
        assert runner._preset.rounds == 20

    def test_runner_accepts_custom_preset(self):
        """SimulationRunner accepts a custom SimPreset."""
        from backend.app.services.simulation_runner import SimulationRunner
        from backend.app.models.simulation_config import SimPreset, HookConfig, PRESET_FAST
        runner = SimulationRunner(dry_run=True, preset=PRESET_FAST)
        assert runner._preset.name == "fast"
        assert runner._preset.agents == 100

    def test_execute_round_hooks_is_async(self):
        """_execute_round_hooks is an async method."""
        from backend.app.services.simulation_runner import SimulationRunner
        import inspect
        assert inspect.iscoroutinefunction(SimulationRunner._execute_round_hooks)

    def test_hookconfig_all_oasis_fields(self):
        """HookConfig contains all OASIS fork integration fields."""
        from backend.app.models.simulation_config import HookConfig
        hc = HookConfig()
        # Attention economy
        assert hasattr(hc, "attention_economy_interval")
        # Temporal activation
        assert hasattr(hc, "temporal_activation_enabled")
        # Collective actions
        assert hasattr(hc, "collective_action_interval")
        # Network evolution
        assert hasattr(hc, "network_evolution_interval")
        # Feed ranking
        assert hasattr(hc, "feed_algorithm")
        assert hasattr(hc, "virality_interval")


# ---------------------------------------------------------------------------
# Test: Activity Profile Model
# ---------------------------------------------------------------------------


class TestActivityProfile:
    """Tests for the ActivityProfile frozen dataclass."""

    def test_activity_profile_frozen(self):
        """ActivityProfile is immutable."""
        from backend.app.models.activity_profile import ActivityProfile
        profile = ActivityProfile(
            agent_id=1,
            chronotype="standard",
            activity_vector=(0.5,) * 24,
            base_activity_rate=0.65,
        )
        with pytest.raises(AttributeError):
            profile.agent_id = 2  # type: ignore[misc]

    def test_activity_profile_invalid_vector_length(self):
        """ActivityProfile rejects vectors with wrong length."""
        from backend.app.models.activity_profile import ActivityProfile
        with pytest.raises(ValueError, match="exactly 24"):
            ActivityProfile(
                agent_id=1,
                chronotype="standard",
                activity_vector=(0.5,) * 12,
                base_activity_rate=0.65,
            )

    def test_activity_profile_invalid_chronotype(self):
        """ActivityProfile rejects unknown chronotypes."""
        from backend.app.models.activity_profile import ActivityProfile
        with pytest.raises(ValueError, match="Unknown chronotype"):
            ActivityProfile(
                agent_id=1,
                chronotype="invalid",  # type: ignore[arg-type]
                activity_vector=(0.5,) * 24,
                base_activity_rate=0.65,
            )

    def test_probability_at_hour(self):
        """probability_at_hour returns vector[hour] * base_rate."""
        from backend.app.models.activity_profile import ActivityProfile
        profile = ActivityProfile(
            agent_id=1,
            chronotype="standard",
            activity_vector=tuple(float(i) / 23.0 for i in range(24)),
            base_activity_rate=0.5,
        )
        # At hour 23: vector = 1.0, base_rate = 0.5, expected = 0.5
        assert abs(profile.probability_at_hour(23) - 0.5) < 0.01

    def test_probability_at_hour_out_of_range(self):
        """Out-of-range hours return 0.0."""
        from backend.app.models.activity_profile import ActivityProfile
        profile = ActivityProfile(
            agent_id=1,
            chronotype="standard",
            activity_vector=(0.5,) * 24,
            base_activity_rate=0.65,
        )
        assert profile.probability_at_hour(-1) == 0.0
        assert profile.probability_at_hour(25) == 0.0
