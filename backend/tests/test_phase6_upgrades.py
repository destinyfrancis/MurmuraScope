"""Integration tests for Phase 6 upgrades.

Covers:
- POST /api/simulation/{session_id}/agents/{agent_id}/interview
- GET  /api/report/{session_id}/narrative
- InterviewEngine: round_number SQL fix, agent_id type tolerance
- NarrativeAnalyst: _harvest_round_data single-connection + engagement sort
- simulate_viral_engagement: deterministic with rng param
"""

from __future__ import annotations

import random

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app import create_app


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_interview_endpoint():
    """POST /api/simulation/{session_id}/agents/{agent_id}/interview returns 200."""
    session_id = "12345678"
    fake_agent = {
        "id": 1,
        "session_id": session_id,
        "oasis_persona": "Persona",
        "oasis_username": "User1",
        "age": 35,
        "sex": "M",
        "occupation": "Engineer",
        "backstory": "Test",
        "personality": "{}",
    }

    with patch("backend.app.services.interview_engine.get_db") as mock_db:
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        # fetchone calls: agent profile, then round_number query
        mock_cursor.fetchone.side_effect = [fake_agent, {"round_number": 5}, None]
        mock_conn.execute.return_value = mock_cursor
        mock_db.return_value.__aenter__.return_value = mock_conn

        with patch("backend.app.services.interview_engine.AgentMemoryService", autospec=True) as mock_mem_cls:
            mock_mem = mock_mem_cls.return_value
            mock_mem.get_agent_context = AsyncMock(return_value="Context text")
            with patch("backend.app.utils.llm_client.LLMClient.chat", new_callable=AsyncMock) as mock_chat:
                mock_msg = MagicMock()
                mock_msg.content = "Hello, I am the agent."
                mock_chat.return_value = mock_msg

                app = create_app()
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                    r = await client.post(
                        f"/api/simulation/{session_id}/agents/1/interview",
                        json={"query": "Who are you?"},
                    )

    assert r.status_code == 200, f"Unexpected status {r.status_code}: {r.json()}"
    assert r.json()["success"] is True
    assert "Hello, I am the agent." in r.json()["data"]["response"]


@pytest.mark.asyncio
async def test_narrative_endpoint():
    """GET /api/report/{session_id}/narrative returns dossier dict."""
    session_id = "12345678"

    with patch(
        "backend.app.services.narrative_analyst.NarrativeAnalyst.generate_dossier",
        new_callable=AsyncMock,
    ) as mock_gen:
        mock_gen.return_value = {"dossier": "Long Narrative Report"}

        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(f"/api/report/{session_id}/narrative")

    assert r.status_code == 200
    assert r.json()["data"]["dossier"] == "Long Narrative Report"


# ---------------------------------------------------------------------------
# InterviewEngine unit tests
# ---------------------------------------------------------------------------

class TestInterviewEngineRoundQuery:
    """Verify the SELECT round_number fix (was wrongly SELECT id)."""

    @pytest.mark.asyncio
    async def test_latest_round_uses_round_number_column(self):
        from backend.app.services.interview_engine import InterviewEngine

        engine = InterviewEngine.__new__(InterviewEngine)

        fake_profile = {
            "id": "1", "age": 30, "sex": "F", "occupation": "Teacher",
            "backstory": "...", "personality": "{}",
        }

        with patch("backend.app.services.interview_engine.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_cursor = AsyncMock()
            # First fetchone → profile; second → round_number row
            mock_cursor.fetchone.side_effect = [fake_profile, {"round_number": 7}]
            mock_conn.execute.return_value = mock_cursor
            mock_db.return_value.__aenter__.return_value = mock_conn

            with patch.object(engine.__class__, "_memory_service", create=True):
                pass  # just verify SQL, not LLM

            # Capture SQL calls
            calls: list[str] = []
            original_execute = mock_conn.execute

            async def capture_execute(sql, *args, **kwargs):
                calls.append(sql)
                return await original_execute(sql, *args, **kwargs)

            mock_conn.execute = capture_execute

            # Minimal engine init
            mock_llm = AsyncMock()
            mock_llm.chat = AsyncMock(return_value=MagicMock(content="response"))
            engine._llm = mock_llm

            mock_mem = AsyncMock()
            mock_mem.get_agent_context = AsyncMock(return_value="ctx")
            engine._memory_service = mock_mem

            with patch("backend.app.services.interview_engine.get_agent_provider_model", return_value=("openrouter", "model")):
                with patch("backend.app.services.interview_engine.get_db") as mock_db2:
                    mock_db2.return_value.__aenter__.return_value = mock_conn
                    await engine.generate_response("sess1", "1", "hello")

        # The second SQL call must SELECT round_number (not id)
        round_query = next((s for s in calls if "agent_memories" in s), "")
        assert "round_number" in round_query, f"Expected 'round_number' in SQL, got: {round_query!r}"
        assert "SELECT id" not in round_query

    @pytest.mark.asyncio
    async def test_agent_id_uuid_does_not_crash(self):
        """kg_driven UUID agent_id should not raise ValueError."""
        from backend.app.services.interview_engine import InterviewEngine

        engine = InterviewEngine.__new__(InterviewEngine)

        uuid_agent_id = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"
        fake_profile = {
            "id": uuid_agent_id, "age": 25, "sex": "M",
            "occupation": "Analyst", "backstory": "", "personality": "{}",
        }

        with patch("backend.app.services.interview_engine.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_cursor = AsyncMock()
            mock_cursor.fetchone.side_effect = [fake_profile, {"round_number": 2}]
            mock_conn.execute.return_value = mock_cursor
            mock_db.return_value.__aenter__.return_value = mock_conn

            mock_llm = AsyncMock()
            mock_llm.chat = AsyncMock(return_value=MagicMock(content="ok"))
            engine._llm = mock_llm

            mock_mem = AsyncMock()
            mock_mem.get_agent_context = AsyncMock(return_value="ctx")
            engine._memory_service = mock_mem

            with patch("backend.app.services.interview_engine.get_agent_provider_model", return_value=("openrouter", "model")):
                # Should not raise ValueError from int(uuid_agent_id)
                result = await engine.generate_response("sess1", uuid_agent_id, "hi")

        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# NarrativeAnalyst unit tests
# ---------------------------------------------------------------------------

class TestHarvestRoundData:
    """Verify single-connection + correct engagement sort SQL."""

    @pytest.mark.asyncio
    async def test_single_db_connection_for_all_rounds(self):
        """_harvest_round_data must open get_db exactly once."""
        from backend.app.services.narrative_analyst import NarrativeAnalyst

        analyst = NarrativeAnalyst.__new__(NarrativeAnalyst)

        with patch("backend.app.services.narrative_analyst.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_cursor = AsyncMock()
            mock_cursor.fetchone.return_value = None
            mock_cursor.fetchall.return_value = []
            mock_conn.execute.return_value = mock_cursor
            mock_db.return_value.__aenter__.return_value = mock_conn

            await analyst._harvest_round_data("sess", 5)

        # get_db context manager should be entered exactly once (single connection)
        assert mock_db.return_value.__aenter__.call_count == 1

    @pytest.mark.asyncio
    async def test_engagement_sort_uses_json_extract(self):
        """SQL for top posts must use json_extract on engagement_metrics, not a subquery."""
        from backend.app.services.narrative_analyst import NarrativeAnalyst

        analyst = NarrativeAnalyst.__new__(NarrativeAnalyst)
        captured_sqls: list[str] = []

        with patch("backend.app.services.narrative_analyst.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_cursor = AsyncMock()
            mock_cursor.fetchone.return_value = None
            mock_cursor.fetchall.return_value = []

            async def capture(sql, *args, **kwargs):
                captured_sqls.append(sql)
                return mock_cursor

            mock_conn.execute = capture
            mock_db.return_value.__aenter__.return_value = mock_conn

            await analyst._harvest_round_data("sess", 2)

        action_sqls = [s for s in captured_sqls if "simulation_actions" in s]
        assert action_sqls, "Expected at least one query on simulation_actions"
        for sql in action_sqls:
            assert "json_extract" in sql, f"Expected json_extract in SQL, got: {sql!r}"
            assert "platform='?'" not in sql, "Old broken subquery still present"

    @pytest.mark.asyncio
    async def test_returns_one_entry_per_round(self):
        from backend.app.services.narrative_analyst import NarrativeAnalyst

        analyst = NarrativeAnalyst.__new__(NarrativeAnalyst)

        with patch("backend.app.services.narrative_analyst.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_cursor = AsyncMock()
            mock_cursor.fetchone.return_value = None
            mock_cursor.fetchall.return_value = []
            mock_conn.execute.return_value = mock_cursor
            mock_db.return_value.__aenter__.return_value = mock_conn

            result = await analyst._harvest_round_data("sess", 4)

        assert len(result) == 4
        assert [r["round"] for r in result] == [1, 2, 3, 4]


# ---------------------------------------------------------------------------
# simulate_viral_engagement determinism tests
# ---------------------------------------------------------------------------

class TestSimulateViralEngagement:
    def _make_state(self, consumer_confidence: float = 50.0):
        from backend.app.services.macro_state import MacroState
        return MacroState(
            hibor_1m=0.04,
            prime_rate=0.055,
            unemployment_rate=0.03,
            median_monthly_income=20000,
            ccl_index=140.0,
            avg_sqft_price={"HK Island": 25000, "Kowloon": 20000, "NT": 15000},
            mortgage_cap=0.60,
            stamp_duty_rates={"AVD": 0.075},
            gdp_growth=0.03,
            cpi_yoy=0.02,
            hsi_level=18000.0,
            consumer_confidence=consumer_confidence,
            net_migration=-30000,
            birth_rate=0.008,
            policy_flags={},
        )

    def test_deterministic_with_rng(self):
        from backend.app.services.macro_posts import simulate_viral_engagement
        from backend.app.services.macro_state import SHOCK_PROPERTY_CRASH

        state = self._make_state()
        rng_a = random.Random(42)
        rng_b = random.Random(42)
        r1 = simulate_viral_engagement(SHOCK_PROPERTY_CRASH, state, rng=rng_a)
        r2 = simulate_viral_engagement(SHOCK_PROPERTY_CRASH, state, rng=rng_b)
        assert r1 == r2

    def test_high_confidence_boosts_likes(self):
        from backend.app.services.macro_posts import simulate_viral_engagement
        from backend.app.services.macro_state import SHOCK_MARKET_RALLY

        low = self._make_state(consumer_confidence=0.0)
        high = self._make_state(consumer_confidence=100.0)
        rng = random.Random(7)

        r_low = simulate_viral_engagement(SHOCK_MARKET_RALLY, low, rng=random.Random(7))
        r_high = simulate_viral_engagement(SHOCK_MARKET_RALLY, high, rng=random.Random(7))
        assert r_high["likes"] >= r_low["likes"]

    def test_returns_required_keys(self):
        from backend.app.services.macro_posts import simulate_viral_engagement
        from backend.app.services.macro_state import SHOCK_UNEMPLOYMENT_SPIKE

        state = self._make_state()
        result = simulate_viral_engagement(SHOCK_UNEMPLOYMENT_SPIKE, state, rng=random.Random(1))
        assert {"likes", "shares", "quotes", "replies"} == set(result.keys())

    def test_no_rng_param_still_works(self):
        """Backward compat: calling without rng should not raise."""
        from backend.app.services.macro_posts import simulate_viral_engagement
        from backend.app.services.macro_state import SHOCK_POLICY_CHANGE

        state = self._make_state()
        result = simulate_viral_engagement(SHOCK_POLICY_CHANGE, state)
        assert result["likes"] > 0
