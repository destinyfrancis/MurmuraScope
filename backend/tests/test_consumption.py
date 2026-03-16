"""Tests for Phase C: B2C Consumption Tracking.

Covers:
- ConsumptionTracker.ensure_table (schema creation)
- ConsumptionTracker.track_round (profile generation + DB insert)
- ConsumptionTracker.get_consumption_trends (aggregate query)
- ConsumptionTracker.get_agent_consumption (per-agent query)
- RoundConsumptionSummary frozen dataclass (immutability, to_dict)
- GET /{session_id}/consumption API endpoint
- GET /{session_id}/agents/{agent_id}/consumption API endpoint
"""

from __future__ import annotations

import dataclasses
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from backend.app.services.consumption_model import (
    ConsumptionTracker,
    RoundConsumptionSummary,
    _CATEGORIES,
)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture()
def sample_agent_profiles():
    """Return a small list of AgentProfile instances."""
    from backend.app.services.agent_factory import AgentProfile

    return [
        AgentProfile(
            id=i,
            agent_type="citizen",
            age=30 + i * 5,
            sex="F" if i % 2 == 0 else "M",
            district="沙田",
            occupation="專業人士",
            income_bracket="$25,000-$39,999",
            education_level="大學",
            marital_status="已婚",
            housing_type="私人住宅",
            openness=0.6,
            conscientiousness=0.7,
            extraversion=0.5,
            agreeableness=0.6,
            neuroticism=0.4,
            monthly_income=30_000,
            savings=100_000,
        )
        for i in range(5)
    ]


@pytest.fixture()
def sample_macro_state():
    """Return a minimal MacroState."""
    from backend.app.services.macro_state import MacroState

    return MacroState(
        hibor_1m=0.04, prime_rate=0.0575,
        unemployment_rate=0.029, median_monthly_income=20_000,
        ccl_index=152.3, avg_sqft_price={}, mortgage_cap=0.70,
        stamp_duty_rates={}, gdp_growth=0.032, cpi_yoy=0.021,
        hsi_level=16_800.0, consumer_confidence=88.5,
        net_migration=-12_000, birth_rate=5.8, policy_flags={},
    )


# ===========================================================================
# RoundConsumptionSummary tests
# ===========================================================================


class TestRoundConsumptionSummary:
    """Unit tests for the immutable RoundConsumptionSummary dataclass."""

    def _make_summary(self, **kwargs) -> RoundConsumptionSummary:
        defaults = dict(
            round_number=1,
            agent_count=10,
            avg_food=0.22,
            avg_housing=0.28,
            avg_transport=0.10,
            avg_entertainment=0.10,
            avg_education=0.06,
            avg_healthcare=0.06,
            avg_savings_rate=0.18,
            dominant_category="housing",
        )
        defaults.update(kwargs)
        return RoundConsumptionSummary(**defaults)

    def test_frozen(self):
        s = self._make_summary()
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            s.avg_food = 0.99  # type: ignore[misc]

    def test_to_dict_complete(self):
        s = self._make_summary()
        d = s.to_dict()
        assert "round_number" in d
        assert "avg_food" in d
        assert "dominant_category" in d
        assert "avg_savings_rate" in d

    def test_to_dict_values_correct(self):
        s = self._make_summary(avg_food=0.25, round_number=3)
        d = s.to_dict()
        assert d["avg_food"] == 0.25
        assert d["round_number"] == 3


# ===========================================================================
# ConsumptionTracker.ensure_table
# ===========================================================================


class TestEnsureTable:
    """Tests that ensure_table creates the required schema."""

    @pytest.mark.asyncio
    async def test_creates_table(self, test_db):
        tracker = ConsumptionTracker()
        await tracker.ensure_table(test_db)

        cursor = await test_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_consumption'"
        )
        row = await cursor.fetchone()
        assert row is not None, "agent_consumption table should exist"

    @pytest.mark.asyncio
    async def test_idempotent(self, test_db):
        """Calling ensure_table twice should not raise."""
        tracker = ConsumptionTracker()
        await tracker.ensure_table(test_db)
        await tracker.ensure_table(test_db)  # second call — no error


# ===========================================================================
# ConsumptionTracker.track_round
# ===========================================================================


class TestTrackRound:
    """Tests for the core track_round persistence method."""

    @pytest.mark.asyncio
    async def test_inserts_correct_row_count(
        self, test_db, test_db_path, sample_agent_profiles, sample_macro_state
    ):
        """track_round should insert (agents × categories) rows."""
        tracker = ConsumptionTracker()

        with patch("backend.app.services.consumption_model.get_db") as mock_get_db:
            mock_get_db.return_value = _AsyncDbContextManager(test_db)
            inserted = await tracker.track_round(
                session_id="sess-001",
                round_number=1,
                profiles=sample_agent_profiles,
                macro_state=sample_macro_state,
            )

        expected = len(sample_agent_profiles) * len(_CATEGORIES)
        assert inserted == expected

    @pytest.mark.asyncio
    async def test_data_persisted_to_db(
        self, test_db, sample_agent_profiles, sample_macro_state
    ):
        """Rows written by track_round should be retrievable from the DB."""
        tracker = ConsumptionTracker()

        with patch("backend.app.services.consumption_model.get_db") as mock_get_db:
            mock_get_db.return_value = _AsyncDbContextManager(test_db)
            await tracker.track_round(
                session_id="sess-002",
                round_number=2,
                profiles=sample_agent_profiles,
                macro_state=sample_macro_state,
            )

        cursor = await test_db.execute(
            "SELECT COUNT(*) FROM agent_consumption WHERE session_id = 'sess-002'"
        )
        row = await cursor.fetchone()
        assert row[0] == len(sample_agent_profiles) * len(_CATEGORIES)

    @pytest.mark.asyncio
    async def test_empty_profiles_returns_zero(self, sample_macro_state):
        """Empty profiles list should return 0 without touching the DB."""
        tracker = ConsumptionTracker()
        inserted = await tracker.track_round(
            session_id="sess-empty",
            round_number=1,
            profiles=[],
            macro_state=sample_macro_state,
        )
        assert inserted == 0

    @pytest.mark.asyncio
    async def test_sentiment_map_applied(
        self, test_db, sample_agent_profiles, sample_macro_state
    ):
        """Negative sentiment should reduce entertainment spending."""
        tracker = ConsumptionTracker()
        sentiment_map = {p.id: "negative" for p in sample_agent_profiles}

        # Track without sentiment (neutral baseline)
        with patch("backend.app.services.consumption_model.get_db") as mock_get_db:
            mock_get_db.return_value = _AsyncDbContextManager(test_db)
            await tracker.track_round(
                session_id="sess-neutral",
                round_number=1,
                profiles=sample_agent_profiles,
                macro_state=sample_macro_state,
                sentiment_map=None,
            )

        # Track with negative sentiment
        with patch("backend.app.services.consumption_model.get_db") as mock_get_db:
            mock_get_db.return_value = _AsyncDbContextManager(test_db)
            await tracker.track_round(
                session_id="sess-negative",
                round_number=1,
                profiles=sample_agent_profiles,
                macro_state=sample_macro_state,
                sentiment_map=sentiment_map,
            )

        cursor_neutral = await test_db.execute(
            "SELECT AVG(amount_pct) FROM agent_consumption "
            "WHERE session_id = 'sess-neutral' AND category = 'entertainment'"
        )
        cursor_negative = await test_db.execute(
            "SELECT AVG(amount_pct) FROM agent_consumption "
            "WHERE session_id = 'sess-negative' AND category = 'entertainment'"
        )
        avg_neutral = (await cursor_neutral.fetchone())[0] or 0.0
        avg_negative = (await cursor_negative.fetchone())[0] or 0.0

        # Negative sentiment should suppress entertainment spending
        assert avg_negative <= avg_neutral

    @pytest.mark.asyncio
    async def test_amount_pct_in_unit_range(
        self, test_db, sample_agent_profiles, sample_macro_state
    ):
        """All amount_pct values should be in [0, 1]."""
        tracker = ConsumptionTracker()

        with patch("backend.app.services.consumption_model.get_db") as mock_get_db:
            mock_get_db.return_value = _AsyncDbContextManager(test_db)
            await tracker.track_round(
                session_id="sess-range",
                round_number=1,
                profiles=sample_agent_profiles,
                macro_state=sample_macro_state,
            )

        cursor = await test_db.execute(
            "SELECT MIN(amount_pct), MAX(amount_pct) FROM agent_consumption "
            "WHERE session_id = 'sess-range'"
        )
        row = await cursor.fetchone()
        assert row[0] >= 0.0
        assert row[1] <= 1.0


# ===========================================================================
# ConsumptionTracker.get_consumption_trends
# ===========================================================================


class TestGetConsumptionTrends:
    """Tests for aggregated consumption trend queries."""

    @pytest.mark.asyncio
    async def test_returns_summaries_per_round(
        self, test_db, sample_agent_profiles, sample_macro_state
    ):
        """get_consumption_trends should return one summary per tracked round."""
        tracker = ConsumptionTracker()

        for round_num in range(1, 4):
            with patch("backend.app.services.consumption_model.get_db") as mock_get_db:
                mock_get_db.return_value = _AsyncDbContextManager(test_db)
                await tracker.track_round(
                    session_id="sess-trend",
                    round_number=round_num,
                    profiles=sample_agent_profiles,
                    macro_state=sample_macro_state,
                )

        with patch("backend.app.services.consumption_model.get_db") as mock_get_db:
            mock_get_db.return_value = _AsyncDbContextManager(test_db)
            summaries = await tracker.get_consumption_trends("sess-trend")

        assert len(summaries) == 3
        rounds = [s.round_number for s in summaries]
        assert rounds == sorted(rounds)  # chronological order

    @pytest.mark.asyncio
    async def test_summaries_are_frozen_dataclasses(
        self, test_db, sample_agent_profiles, sample_macro_state
    ):
        """All returned summaries must be RoundConsumptionSummary instances."""
        tracker = ConsumptionTracker()

        with patch("backend.app.services.consumption_model.get_db") as mock_get_db:
            mock_get_db.return_value = _AsyncDbContextManager(test_db)
            await tracker.track_round(
                session_id="sess-type",
                round_number=1,
                profiles=sample_agent_profiles,
                macro_state=sample_macro_state,
            )

        with patch("backend.app.services.consumption_model.get_db") as mock_get_db:
            mock_get_db.return_value = _AsyncDbContextManager(test_db)
            summaries = await tracker.get_consumption_trends("sess-type")

        assert len(summaries) == 1
        s = summaries[0]
        assert isinstance(s, RoundConsumptionSummary)
        assert s.agent_count == len(sample_agent_profiles)

    @pytest.mark.asyncio
    async def test_dominant_category_is_valid(
        self, test_db, sample_agent_profiles, sample_macro_state
    ):
        """dominant_category should be one of the known spending categories."""
        tracker = ConsumptionTracker()

        with patch("backend.app.services.consumption_model.get_db") as mock_get_db:
            mock_get_db.return_value = _AsyncDbContextManager(test_db)
            await tracker.track_round(
                session_id="sess-dom",
                round_number=1,
                profiles=sample_agent_profiles,
                macro_state=sample_macro_state,
            )

        with patch("backend.app.services.consumption_model.get_db") as mock_get_db:
            mock_get_db.return_value = _AsyncDbContextManager(test_db)
            summaries = await tracker.get_consumption_trends("sess-dom")

        assert summaries[0].dominant_category in _CATEGORIES

    @pytest.mark.asyncio
    async def test_returns_empty_for_unknown_session(self, test_db):
        """No data for a session should return an empty list."""
        tracker = ConsumptionTracker()

        with patch("backend.app.services.consumption_model.get_db") as mock_get_db:
            mock_get_db.return_value = _AsyncDbContextManager(test_db)
            summaries = await tracker.get_consumption_trends("nonexistent-session")

        assert summaries == []


# ===========================================================================
# ConsumptionTracker.get_agent_consumption
# ===========================================================================


class TestGetAgentConsumption:
    """Tests for per-agent consumption queries."""

    @pytest.mark.asyncio
    async def test_returns_rows_for_tracked_agent(
        self, test_db, sample_agent_profiles, sample_macro_state
    ):
        tracker = ConsumptionTracker()
        agent = sample_agent_profiles[0]

        with patch("backend.app.services.consumption_model.get_db") as mock_get_db:
            mock_get_db.return_value = _AsyncDbContextManager(test_db)
            await tracker.track_round(
                session_id="sess-agent",
                round_number=1,
                profiles=sample_agent_profiles,
                macro_state=sample_macro_state,
            )

        with patch("backend.app.services.consumption_model.get_db") as mock_get_db:
            mock_get_db.return_value = _AsyncDbContextManager(test_db)
            rows = await tracker.get_agent_consumption(
                session_id="sess-agent",
                agent_id=agent.id,
            )

        assert len(rows) == len(_CATEGORIES)
        categories = {r["category"] for r in rows}
        assert categories == set(_CATEGORIES)

    @pytest.mark.asyncio
    async def test_returns_empty_for_unknown_agent(self, test_db):
        tracker = ConsumptionTracker()

        with patch("backend.app.services.consumption_model.get_db") as mock_get_db:
            mock_get_db.return_value = _AsyncDbContextManager(test_db)
            rows = await tracker.get_agent_consumption(
                session_id="sess-unknown",
                agent_id=99999,
            )

        assert rows == []


# ===========================================================================
# API endpoint tests
# ===========================================================================


class TestConsumptionApiEndpoints:
    """HTTP-level tests for the /consumption endpoints."""

    @pytest.mark.asyncio
    async def test_get_consumption_trends_success(self, test_client):
        """GET /{id}/consumption should return 200 with data list."""
        from backend.app.services import consumption_model
        original_class = consumption_model.ConsumptionTracker

        class _MockTracker:
            def __init__(self):
                pass
            async def get_consumption_trends(self, **kwargs):
                return []
            async def ensure_table(self, db):
                pass

        consumption_model.ConsumptionTracker = _MockTracker  # type: ignore
        try:
            response = await test_client.get("/api/simulation/fake-session/consumption")
        finally:
            consumption_model.ConsumptionTracker = original_class  # type: ignore

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)

    @pytest.mark.asyncio
    async def test_get_consumption_trends_returns_summaries(self, test_client):
        """GET /{id}/consumption should serialise RoundConsumptionSummary correctly."""
        summary = RoundConsumptionSummary(
            round_number=3,
            agent_count=100,
            avg_food=0.22,
            avg_housing=0.28,
            avg_transport=0.10,
            avg_entertainment=0.10,
            avg_education=0.06,
            avg_healthcare=0.06,
            avg_savings_rate=0.18,
            dominant_category="housing",
        )
        mock_tracker_instance = MagicMock()
        mock_tracker_instance.get_consumption_trends = AsyncMock(return_value=[summary])

        with patch(
            "backend.app.services.consumption_model.ConsumptionTracker",
            return_value=mock_tracker_instance,
        ):
            # Create tracker, call get_consumption_trends — patch the tracker class
            from backend.app.services import consumption_model
            original_class = consumption_model.ConsumptionTracker

            class _MockTracker:
                def __init__(self):
                    pass
                async def get_consumption_trends(self, **kwargs):
                    return [summary]
                async def ensure_table(self, db):
                    pass

            consumption_model.ConsumptionTracker = _MockTracker  # type: ignore
            try:
                response = await test_client.get("/api/simulation/sess-001/consumption")
            finally:
                consumption_model.ConsumptionTracker = original_class  # type: ignore

        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) == 1
        assert data[0]["round_number"] == 3
        assert data[0]["dominant_category"] == "housing"

    @pytest.mark.asyncio
    async def test_get_agent_consumption_success(self, test_client):
        """GET /{id}/agents/{agent_id}/consumption should return 200."""
        from backend.app.services import consumption_model
        original_class = consumption_model.ConsumptionTracker

        class _MockTracker:
            def __init__(self):
                pass
            async def get_agent_consumption(self, **kwargs):
                return [{"round_number": 1, "category": "food", "amount_pct": 0.22}]
            async def ensure_table(self, db):
                pass

        consumption_model.ConsumptionTracker = _MockTracker  # type: ignore
        try:
            response = await test_client.get("/api/simulation/sess-001/agents/42/consumption")
        finally:
            consumption_model.ConsumptionTracker = original_class  # type: ignore

        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) == 1
        assert data[0]["category"] == "food"

    @pytest.mark.asyncio
    async def test_empty_session_returns_empty_list(self, test_client):
        """An unknown session should still return 200 with empty data."""
        from backend.app.services import consumption_model
        original_class = consumption_model.ConsumptionTracker

        class _MockTracker:
            def __init__(self):
                pass
            async def get_consumption_trends(self, **kwargs):
                return []
            async def ensure_table(self, db):
                pass

        consumption_model.ConsumptionTracker = _MockTracker  # type: ignore
        try:
            response = await test_client.get("/api/simulation/nonexistent/consumption")
        finally:
            consumption_model.ConsumptionTracker = original_class  # type: ignore

        assert response.status_code == 200
        assert response.json()["data"] == []


# ===========================================================================
# Helpers
# ===========================================================================


class _AsyncDbContextManager:
    """Wraps an aiosqlite.Connection as an async context manager for patching."""

    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *args):
        pass
