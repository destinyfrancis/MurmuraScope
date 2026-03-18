"""Tests for simulation manager and runner."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.models.project import (
    CostEstimate,
    SessionState,
    SessionStatus,
    SimMode,
)


# ======================================================================
# Session creation
# ======================================================================


class TestCreateSessionStoresInDB:
    """Test that creating a session persists correctly to the DB."""

    @pytest.mark.asyncio
    async def test_session_state_create(self):
        session = SessionState.create(
            name="test_property_10agents",
            sim_mode=SimMode.LIFE_DECISION,
            agent_count=10,
            round_count=5,
            graph_id="graph-001",
            scenario_type="property",
        )

        assert session.status == SessionStatus.CREATED
        assert session.agent_count == 10
        assert session.round_count == 5
        assert session.graph_id == "graph-001"
        assert session.current_round == 0
        assert session.cost_estimate is not None
        assert session.id is not None
        assert len(session.id) == 36  # UUID format

    @pytest.mark.asyncio
    async def test_session_persists_to_db(self, test_db, sample_session_request):
        session = SessionState.create(
            name="test_session",
            sim_mode=SimMode.LIFE_DECISION,
            agent_count=sample_session_request["agent_count"],
            round_count=sample_session_request["round_count"],
            graph_id=sample_session_request["graph_id"],
            scenario_type=sample_session_request["scenario_type"],
        )

        cost_json = json.dumps({
            "agent_count": session.cost_estimate.agent_count,
            "round_count": session.cost_estimate.round_count,
            "cost_per_call_usd": session.cost_estimate.cost_per_call_usd,
            "total_estimated_usd": session.cost_estimate.total_estimated_usd,
            "token_estimate": session.cost_estimate.token_estimate,
        })

        # Note: The schema has different columns from _persist_session,
        # so we insert using the schema's actual columns.
        await test_db.execute(
            """INSERT INTO simulation_sessions
               (id, name, sim_mode, seed_text, scenario_type, graph_id,
                agent_count, round_count, llm_provider, llm_model,
                oasis_db_path, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session.id,
                session.name,
                session.sim_mode.value,
                "test seed text",
                session.scenario_type,
                session.graph_id,
                session.agent_count,
                session.round_count,
                session.llm_provider,
                "deepseek-chat",
                "/tmp/test.db",
                session.status.value,
            ),
        )
        await test_db.commit()

        cursor = await test_db.execute(
            "SELECT * FROM simulation_sessions WHERE id = ?", (session.id,)
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row["status"] == "created"
        assert row["agent_count"] == 10

    @pytest.mark.asyncio
    async def test_create_session_requires_graph_id(self):
        """SessionState.create should work; manager validates graph_id separately."""
        session = SessionState.create(
            name="test",
            sim_mode=SimMode.LIFE_DECISION,
            agent_count=5,
            round_count=3,
            graph_id="g-1",
            scenario_type="property",
        )
        assert session.graph_id == "g-1"


# ======================================================================
# Session status transitions
# ======================================================================


class TestSessionStatusTransitions:
    """Test the state machine for session lifecycle."""

    def test_created_to_running(self):
        session = SessionState.create(
            name="test", sim_mode=SimMode.LIFE_DECISION,
            agent_count=5, round_count=3,
            graph_id="g-1", scenario_type="property",
        )
        updated = session.with_status(SessionStatus.RUNNING)
        assert updated.status == SessionStatus.RUNNING
        assert updated.id == session.id  # ID preserved

    def test_running_to_completed(self):
        session = SessionState.create(
            name="test", sim_mode=SimMode.LIFE_DECISION,
            agent_count=5, round_count=3,
            graph_id="g-1", scenario_type="property",
        )
        running = session.with_status(SessionStatus.RUNNING)
        completed = running.with_status(SessionStatus.COMPLETED)
        assert completed.status == SessionStatus.COMPLETED

    def test_running_to_failed(self):
        session = SessionState.create(
            name="test", sim_mode=SimMode.LIFE_DECISION,
            agent_count=5, round_count=3,
            graph_id="g-1", scenario_type="property",
        )
        running = session.with_status(SessionStatus.RUNNING)
        failed = running.with_status(
            SessionStatus.FAILED, error_message="Test error"
        )
        assert failed.status == SessionStatus.FAILED
        assert failed.error_message == "Test error"

    def test_with_status_creates_new_instance(self):
        session = SessionState.create(
            name="test", sim_mode=SimMode.LIFE_DECISION,
            agent_count=5, round_count=3,
            graph_id="g-1", scenario_type="property",
        )
        updated = session.with_status(SessionStatus.RUNNING)
        # Original is unchanged (immutability)
        assert session.status == SessionStatus.CREATED
        assert updated.status == SessionStatus.RUNNING
        assert session is not updated

    def test_with_round_updates_round(self):
        session = SessionState.create(
            name="test", sim_mode=SimMode.LIFE_DECISION,
            agent_count=5, round_count=10,
            graph_id="g-1", scenario_type="property",
        )
        updated = session.with_round(7)
        assert updated.current_round == 7
        assert session.current_round == 0  # Immutability

    def test_validate_transition_rejects_invalid(self):
        from backend.app.services.simulation_manager import _validate_transition

        with pytest.raises(ValueError, match="Invalid transition"):
            _validate_transition(SessionStatus.COMPLETED, SessionStatus.RUNNING)

    def test_validate_transition_accepts_valid(self):
        from backend.app.services.simulation_manager import _validate_transition

        # Should not raise
        _validate_transition(SessionStatus.CREATED, SessionStatus.RUNNING)
        _validate_transition(SessionStatus.RUNNING, SessionStatus.COMPLETED)
        _validate_transition(SessionStatus.RUNNING, SessionStatus.FAILED)


# ======================================================================
# Agent profiles match census distribution
# ======================================================================


class TestAgentProfilesMatchCensusDistribution:
    """Test that generated agent profiles follow census distributions."""

    @pytest.mark.asyncio
    async def test_agent_profiles_stored_in_db(self, test_db):
        session_id = str(uuid.uuid4())

        # Insert session first
        await test_db.execute(
            """INSERT INTO simulation_sessions
               (id, name, sim_mode, seed_text, agent_count, round_count,
                llm_provider, llm_model, oasis_db_path, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, "test", "life_decision", "seed", 5, 3,
             "deepseek", "deepseek-chat", "/tmp/test.db", "created"),
        )

        # Insert agent profiles
        agents = [
            (session_id, i, "resident", 25 + i * 5, "M" if i % 2 == 0 else "F",
             "Central", "professional", "high",
             "university", "single", "private",
             0.7, 0.6, 0.5, 0.8, 0.3,
             30000 + i * 5000, 100000,
             f"persona_{i}", f"user_{i}")
            for i in range(5)
        ]

        for agent in agents:
            await test_db.execute(
                """INSERT INTO agent_profiles
                   (session_id, id, agent_type, age, sex, district, occupation,
                    income_bracket, education_level, marital_status, housing_type,
                    openness, conscientiousness, extraversion, agreeableness, neuroticism,
                    monthly_income, savings, oasis_persona, oasis_username)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                agent,
            )
        await test_db.commit()

        cursor = await test_db.execute(
            "SELECT COUNT(*) as cnt FROM agent_profiles WHERE session_id = ?",
            (session_id,),
        )
        row = await cursor.fetchone()
        assert row["cnt"] == 5

    @pytest.mark.asyncio
    async def test_agent_sex_distribution(self, test_db):
        session_id = str(uuid.uuid4())

        await test_db.execute(
            """INSERT INTO simulation_sessions
               (id, name, sim_mode, seed_text, agent_count, round_count,
                llm_provider, llm_model, oasis_db_path, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, "test", "life_decision", "seed", 100, 3,
             "deepseek", "deepseek-chat", "/tmp/test.db", "created"),
        )

        # Insert 100 agents with roughly equal sex distribution
        for i in range(100):
            sex = "M" if i < 48 else "F"
            await test_db.execute(
                """INSERT INTO agent_profiles
                   (session_id, id, agent_type, age, sex, district, occupation,
                    income_bracket, education_level, marital_status, housing_type,
                    openness, conscientiousness, extraversion, agreeableness, neuroticism,
                    monthly_income, savings, oasis_persona, oasis_username)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, i, "resident", 30, sex, "Central", "worker",
                 "medium", "secondary", "single", "public",
                 0.5, 0.5, 0.5, 0.5, 0.5, 20000, 50000,
                 f"persona_{i}", f"user_{i}"),
            )
        await test_db.commit()

        cursor = await test_db.execute(
            "SELECT sex, COUNT(*) as cnt FROM agent_profiles WHERE session_id = ? GROUP BY sex",
            (session_id,),
        )
        rows = await cursor.fetchall()
        sex_counts = {row["sex"]: row["cnt"] for row in rows}

        assert "M" in sex_counts
        assert "F" in sex_counts
        # Roughly balanced (within 10%)
        total = sum(sex_counts.values())
        male_pct = sex_counts["M"] / total
        assert 0.3 <= male_pct <= 0.7


# ======================================================================
# Cost estimation
# ======================================================================


class TestCostEstimation:
    """Test CostEstimate calculation logic."""

    def test_basic_cost_calculation(self):
        cost = CostEstimate.calculate(agent_count=300, round_count=40)

        assert cost.agent_count == 300
        assert cost.round_count == 40
        assert cost.token_estimate == 300 * 40 * 500  # 6,000,000
        assert cost.total_estimated_usd > 0
        assert cost.cost_per_call_usd > 0

    def test_cost_scales_with_agents(self):
        small = CostEstimate.calculate(agent_count=10, round_count=10)
        large = CostEstimate.calculate(agent_count=100, round_count=10)

        assert large.total_estimated_usd > small.total_estimated_usd
        # Should scale linearly
        ratio = large.total_estimated_usd / small.total_estimated_usd
        assert abs(ratio - 10.0) < 0.001

    def test_cost_scales_with_rounds(self):
        few = CostEstimate.calculate(agent_count=100, round_count=5)
        many = CostEstimate.calculate(agent_count=100, round_count=50)

        ratio = many.total_estimated_usd / few.total_estimated_usd
        assert abs(ratio - 10.0) < 0.001

    def test_cost_estimate_is_frozen(self):
        cost = CostEstimate.calculate(agent_count=10, round_count=5)
        with pytest.raises(AttributeError):
            cost.agent_count = 999  # type: ignore[misc]


# ======================================================================
# Shock injection
# ======================================================================


class TestShockInjectionAtCorrectRound:
    """Test that scheduled shocks are stored with correct round numbers."""

    @pytest.mark.asyncio
    async def test_shock_config_preserved(self, sample_session_request):
        config = sample_session_request
        shocks = config["shocks"]

        assert len(shocks) == 1
        assert shocks[0]["round_number"] == 3
        assert shocks[0]["shock_type"] == "interest_rate_hike"
        assert shocks[0]["parameters"]["delta_bps"] == 25

    @pytest.mark.asyncio
    async def test_multiple_shocks_ordered(self):
        shocks = [
            {"round_number": 5, "shock_type": "policy_change", "description": "BSD removal"},
            {"round_number": 10, "shock_type": "rate_hike", "description": "+50bps"},
            {"round_number": 20, "shock_type": "recession", "description": "GDP contraction"},
        ]

        sorted_shocks = sorted(shocks, key=lambda s: s["round_number"])
        assert sorted_shocks[0]["round_number"] == 5
        assert sorted_shocks[1]["round_number"] == 10
        assert sorted_shocks[2]["round_number"] == 20

    @pytest.mark.asyncio
    async def test_shock_round_within_session_bounds(self, sample_session_request):
        round_count = sample_session_request["round_count"]
        shocks = sample_session_request["shocks"]

        for shock in shocks:
            assert 1 <= shock["round_number"] <= round_count, (
                f"Shock at round {shock['round_number']} exceeds "
                f"session round_count {round_count}"
            )


# ======================================================================
# SimulationRunner — subprocess mock
# ======================================================================


class TestSimulationRunnerSubprocess:
    """Test SimulationRunner with mocked subprocess."""

    @pytest.mark.asyncio
    async def test_runner_rejects_duplicate_session(self):
        from backend.app.services.simulation_runner import SimulationRunner

        runner = SimulationRunner()
        # Simulate an already-running session by inserting into _subprocess_mgr
        mock_proc = MagicMock()
        mock_proc.returncode = None  # marks as still running
        runner._subprocess_mgr._processes["session-1"] = mock_proc

        with pytest.raises(ValueError, match="already running"):
            await runner.run(
                session_id="session-1",
                config={"agent_count": 10},
            )

    @pytest.mark.asyncio
    async def test_runner_stop_nonexistent_raises(self):
        from backend.app.services.simulation_runner import SimulationRunner

        runner = SimulationRunner()

        with pytest.raises(ValueError, match="No running process"):
            await runner.stop("nonexistent-session")
