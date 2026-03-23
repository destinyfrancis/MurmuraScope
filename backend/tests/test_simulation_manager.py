"""Tests for SimulationManager — session lifecycle, state machine, config building.

Covers:
- _infer_sim_mode mapping
- _validate_transition state machine
- _session_to_dict serialization
- create_session with valid inputs
- create_session rejects invalid inputs (missing graph_id, agent_count < 1)
- State machine transitions (valid + invalid)
- Idempotent start (already running returns early)
- Task tracking (self._session_tasks populated after start)
- Config building (_build_runner_config API key selection)
- get_session returns proper dict
- store_agent_profiles batch insert
- stop_session lifecycle
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest
import pytest_asyncio

from backend.app.models.project import SessionState, SessionStatus, SimMode
from backend.app.services.simulation_manager import (
    SimulationManager,
    _build_runner_config,
    _infer_sim_mode,
    _load_session,
    _session_to_dict,
    _validate_transition,
    store_agent_profiles,
)

# ---------------------------------------------------------------------------
# Singleton tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_simulation_manager_returns_singleton():
    """Two calls to get_simulation_manager() must return the same object."""
    import backend.app.services.simulation_manager as mgr_module

    # Reset singleton for test isolation
    original = mgr_module._MANAGER_SINGLETON
    mgr_module._MANAGER_SINGLETON = None

    from backend.app.services.simulation_manager import get_simulation_manager

    m1 = get_simulation_manager()
    m2 = get_simulation_manager()
    assert m1 is m2, "get_simulation_manager() must return the same singleton instance"

    # Cleanup
    mgr_module._MANAGER_SINGLETON = original


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "database", "schema.sql")


@pytest_asyncio.fixture()
async def sim_db(tmp_path):
    """Create a test DB with schema + domain_pack_id column, patch get_db."""
    db_path = str(tmp_path / "sim_mgr.db")

    init_conn = await aiosqlite.connect(db_path)
    init_conn.row_factory = aiosqlite.Row
    with open(_SCHEMA_PATH, encoding="utf-8") as f:
        await init_conn.executescript(f.read())
    # Add domain_pack_id column that the code expects but schema.sql lacks.
    try:
        await init_conn.execute("ALTER TABLE simulation_sessions ADD COLUMN domain_pack_id TEXT DEFAULT 'hk_city'")
    except Exception:
        pass  # already exists
    await init_conn.commit()
    await init_conn.close()

    @asynccontextmanager
    async def _fake_get_db():
        conn = await aiosqlite.connect(db_path)
        conn.row_factory = aiosqlite.Row
        try:
            yield conn
        finally:
            await conn.close()

    with patch("backend.app.services.simulation_manager.get_db", _fake_get_db):
        # Also open a long-lived conn for assertions inside tests.
        db = await aiosqlite.connect(db_path)
        db.row_factory = aiosqlite.Row
        yield db
        await db.close()


@pytest.fixture()
def mock_runner():
    runner = MagicMock()
    runner.run = AsyncMock()
    runner.stop = AsyncMock()
    return runner


@pytest.fixture()
def valid_request():
    return {
        "graph_id": "g-001",
        "scenario_type": "property",
        "agent_count": 10,
        "round_count": 5,
        "platforms": {"facebook": True, "instagram": True},
        "llm_provider": "openrouter",
    }


# ---------------------------------------------------------------------------
# Helper tests: _infer_sim_mode
# ---------------------------------------------------------------------------


class TestInferSimMode:
    def test_property_maps_to_life_decision(self):
        assert _infer_sim_mode("property") == SimMode.LIFE_DECISION

    def test_emigration_maps_to_life_decision(self):
        assert _infer_sim_mode("emigration") == SimMode.LIFE_DECISION

    def test_b2b_maps_to_b2b_campaign(self):
        assert _infer_sim_mode("b2b") == SimMode.B2B_CAMPAIGN

    def test_macro_maps_to_macro_opinion(self):
        assert _infer_sim_mode("macro") == SimMode.MACRO_OPINION

    def test_unknown_defaults_to_life_decision(self):
        assert _infer_sim_mode("xyz_unknown") == SimMode.LIFE_DECISION


# ---------------------------------------------------------------------------
# Helper tests: _validate_transition
# ---------------------------------------------------------------------------


class TestValidateTransition:
    def test_created_to_running_valid(self):
        _validate_transition(SessionStatus.CREATED, SessionStatus.RUNNING)

    def test_created_to_failed_valid(self):
        _validate_transition(SessionStatus.CREATED, SessionStatus.FAILED)

    def test_running_to_completed_valid(self):
        _validate_transition(SessionStatus.RUNNING, SessionStatus.COMPLETED)

    def test_running_to_failed_valid(self):
        _validate_transition(SessionStatus.RUNNING, SessionStatus.FAILED)

    def test_completed_to_running_invalid(self):
        with pytest.raises(ValueError, match="Invalid transition"):
            _validate_transition(SessionStatus.COMPLETED, SessionStatus.RUNNING)

    def test_failed_to_running_invalid(self):
        with pytest.raises(ValueError, match="Invalid transition"):
            _validate_transition(SessionStatus.FAILED, SessionStatus.RUNNING)

    def test_created_to_completed_invalid(self):
        with pytest.raises(ValueError, match="Invalid transition"):
            _validate_transition(SessionStatus.CREATED, SessionStatus.COMPLETED)


# ---------------------------------------------------------------------------
# Helper tests: _session_to_dict
# ---------------------------------------------------------------------------


class TestSessionToDict:
    def test_converts_all_fields(self):
        session = SessionState.create(
            name="test",
            sim_mode=SimMode.LIFE_DECISION,
            agent_count=100,
            round_count=20,
            graph_id="g1",
            scenario_type="property",
        )
        d = _session_to_dict(session)
        assert d["name"] == "test"
        assert d["sim_mode"] == "life_decision"
        assert d["status"] == "created"
        assert d["agent_count"] == 100
        assert d["round_count"] == 20
        assert d["graph_id"] == "g1"
        assert isinstance(d["estimated_cost_usd"], float)
        assert d["estimated_cost_usd"] > 0

    def test_none_cost_estimate_defaults_to_zero(self):
        session = SessionState(
            id="t1",
            name="t",
            sim_mode=SimMode.LIFE_DECISION,
            status=SessionStatus.CREATED,
            agent_count=10,
            round_count=5,
            current_round=0,
            graph_id="g1",
            scenario_type="property",
            platforms={},
            llm_provider="openrouter",
            cost_estimate=None,
            created_at="2026-01-01",
            updated_at="2026-01-01",
        )
        d = _session_to_dict(session)
        assert d["estimated_cost_usd"] == 0.0


# ---------------------------------------------------------------------------
# create_session
# ---------------------------------------------------------------------------


class TestCreateSession:
    @pytest.mark.asyncio
    async def test_returns_expected_keys(self, sim_db, mock_runner, valid_request, tmp_path):
        mgr = SimulationManager(runner=mock_runner)
        with patch("backend.app.services.simulation_manager._PROJECT_ROOT", tmp_path):
            result = await mgr.create_session(valid_request)

        assert "session_id" in result
        assert result["agent_count"] == 10
        assert result["round_count"] == 5
        assert result["status"] == "created"
        assert isinstance(result["estimated_cost_usd"], float)
        assert result["csv_path"].endswith("agents.csv")

    @pytest.mark.asyncio
    async def test_persists_to_db(self, sim_db, mock_runner, valid_request, tmp_path):
        mgr = SimulationManager(runner=mock_runner)
        with patch("backend.app.services.simulation_manager._PROJECT_ROOT", tmp_path):
            result = await mgr.create_session(valid_request)

        cursor = await sim_db.execute(
            "SELECT * FROM simulation_sessions WHERE id = ?",
            (result["session_id"],),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row["agent_count"] == 10
        assert row["status"] == "created"

    @pytest.mark.asyncio
    async def test_rejects_missing_graph_id(self, sim_db, mock_runner):
        mgr = SimulationManager(runner=mock_runner)
        with pytest.raises(ValueError, match="graph_id is required"):
            await mgr.create_session({"scenario_type": "property"})

    @pytest.mark.asyncio
    async def test_rejects_zero_agents(self, sim_db, mock_runner):
        mgr = SimulationManager(runner=mock_runner)
        with pytest.raises(ValueError, match="agent_count must be at least 1"):
            await mgr.create_session({"graph_id": "g1", "agent_count": 0})

    @pytest.mark.asyncio
    async def test_rejects_negative_rounds(self, sim_db, mock_runner):
        mgr = SimulationManager(runner=mock_runner)
        with pytest.raises(ValueError, match="round_count must be at least 1"):
            await mgr.create_session({"graph_id": "g1", "round_count": -1})


# ---------------------------------------------------------------------------
# get_session
# ---------------------------------------------------------------------------


class TestGetSession:
    @pytest.mark.asyncio
    async def test_returns_dict_with_correct_fields(self, sim_db, mock_runner, valid_request, tmp_path):
        mgr = SimulationManager(runner=mock_runner)
        with patch("backend.app.services.simulation_manager._PROJECT_ROOT", tmp_path):
            created = await mgr.create_session(valid_request)

        result = await mgr.get_session(created["session_id"])
        assert result["id"] == created["session_id"]
        assert result["status"] == "created"
        assert result["agent_count"] == 10
        assert "sim_mode" in result
        assert "platforms" in result

    @pytest.mark.asyncio
    async def test_not_found_raises(self, sim_db, mock_runner):
        mgr = SimulationManager(runner=mock_runner)
        with pytest.raises(ValueError, match="Session not found"):
            await mgr.get_session("nonexistent-id")


# ---------------------------------------------------------------------------
# start_session — idempotent start + task tracking
# ---------------------------------------------------------------------------


class TestStartSession:
    @pytest.mark.asyncio
    async def test_idempotent_when_already_running(self, sim_db, mock_runner, valid_request, tmp_path):
        """Starting an already-running session returns early, runner not called."""
        mgr = SimulationManager(runner=mock_runner)
        with patch("backend.app.services.simulation_manager._PROJECT_ROOT", tmp_path):
            created = await mgr.create_session(valid_request)
        sid = created["session_id"]

        # Manually set status to running in DB
        await sim_db.execute(
            "UPDATE simulation_sessions SET status = 'running' WHERE id = ?",
            (sid,),
        )
        await sim_db.commit()

        # Should return without error and without calling runner
        await mgr.start_session(sid)
        mock_runner.run.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_task_tracking_populated(self, sim_db, mock_runner, valid_request, tmp_path):
        """After start_session, _session_tasks has an entry for the session."""
        # Make runner.run block so the task stays alive for inspection.
        block_event = asyncio.Event()

        async def _blocking_run(**kw):
            await block_event.wait()

        mock_runner.run = AsyncMock(side_effect=_blocking_run)
        mgr = SimulationManager(runner=mock_runner)
        with patch("backend.app.services.simulation_manager._PROJECT_ROOT", tmp_path):
            created = await mgr.create_session(valid_request)
        sid = created["session_id"]

        await mgr.start_session(sid)
        await asyncio.sleep(0.05)

        assert sid in mgr._session_tasks
        assert not mgr._session_tasks[sid].done()

        # Cleanup
        block_event.set()
        mgr._session_tasks[sid].cancel()
        try:
            await mgr._session_tasks[sid]
        except (asyncio.CancelledError, Exception):
            pass

    @pytest.mark.asyncio
    async def test_start_completed_session_raises(self, sim_db, mock_runner, valid_request, tmp_path):
        mgr = SimulationManager(runner=mock_runner)
        with patch("backend.app.services.simulation_manager._PROJECT_ROOT", tmp_path):
            created = await mgr.create_session(valid_request)
        sid = created["session_id"]

        await sim_db.execute(
            "UPDATE simulation_sessions SET status = 'completed' WHERE id = ?",
            (sid,),
        )
        await sim_db.commit()

        with pytest.raises(ValueError, match="Invalid transition"):
            await mgr.start_session(sid)


# ---------------------------------------------------------------------------
# _build_runner_config — API key selection
# ---------------------------------------------------------------------------


class TestBuildRunnerConfig:
    @pytest.mark.asyncio
    async def test_openrouter_provider(self, sim_db, mock_runner, valid_request, tmp_path):
        mgr = SimulationManager(runner=mock_runner)
        with patch("backend.app.services.simulation_manager._PROJECT_ROOT", tmp_path):
            created = await mgr.create_session(valid_request)

        loaded = await _load_session(created["session_id"])

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "or-key-xyz"}):
            config = await _build_runner_config(loaded)

        assert config["llm_provider"] == "openrouter"
        assert config["llm_api_key"] == "or-key-xyz"
        assert config["llm_base_url"] == "https://openrouter.ai/api/v1"
        assert config["llm_model"] == "deepseek/deepseek-v3.2"

    @pytest.mark.asyncio
    async def test_fireworks_provider(self, sim_db, mock_runner, tmp_path):
        request = {
            "graph_id": "g-002",
            "scenario_type": "property",
            "agent_count": 5,
            "round_count": 3,
            "llm_provider": "fireworks",
        }
        mgr = SimulationManager(runner=mock_runner)
        with patch("backend.app.services.simulation_manager._PROJECT_ROOT", tmp_path):
            created = await mgr.create_session(request)

        loaded = await _load_session(created["session_id"])

        with patch.dict(os.environ, {"FIREWORKS_API_KEY": "fw-key-abc"}):
            config = await _build_runner_config(loaded)

        assert config["llm_provider"] == "fireworks"
        assert config["llm_api_key"] == "fw-key-abc"
        assert config["llm_base_url"] == "https://api.fireworks.ai/inference/v1"

    @pytest.mark.asyncio
    async def test_config_includes_session_fields(self, sim_db, mock_runner, valid_request, tmp_path):
        mgr = SimulationManager(runner=mock_runner)
        with patch("backend.app.services.simulation_manager._PROJECT_ROOT", tmp_path):
            created = await mgr.create_session(valid_request)

        loaded = await _load_session(created["session_id"])
        config = await _build_runner_config(loaded)

        assert config["session_id"] == created["session_id"]
        assert config["graph_id"] == "g-001"
        assert config["agent_count"] == 10
        assert config["round_count"] == 5
        assert config["scenario_type"] == "property"


# ---------------------------------------------------------------------------
# stop_session
# ---------------------------------------------------------------------------


class TestStopSession:
    @pytest.mark.asyncio
    async def test_stop_running_session(self, sim_db, mock_runner, valid_request, tmp_path):
        mgr = SimulationManager(runner=mock_runner)
        with patch("backend.app.services.simulation_manager._PROJECT_ROOT", tmp_path):
            created = await mgr.create_session(valid_request)
        sid = created["session_id"]

        await sim_db.execute(
            "UPDATE simulation_sessions SET status = 'running' WHERE id = ?",
            (sid,),
        )
        await sim_db.commit()

        await mgr.stop_session(sid)
        mock_runner.stop.assert_awaited_once_with(sid)

    @pytest.mark.asyncio
    async def test_stop_non_running_raises(self, sim_db, mock_runner, valid_request, tmp_path):
        mgr = SimulationManager(runner=mock_runner)
        with patch("backend.app.services.simulation_manager._PROJECT_ROOT", tmp_path):
            created = await mgr.create_session(valid_request)

        with pytest.raises(ValueError, match="Cannot stop session"):
            await mgr.stop_session(created["session_id"])


# ---------------------------------------------------------------------------
# store_agent_profiles
# ---------------------------------------------------------------------------


class TestStoreAgentProfiles:
    @pytest.mark.asyncio
    async def test_batch_insert(self, sim_db, mock_runner, valid_request, tmp_path):
        mgr = SimulationManager(runner=mock_runner)
        with patch("backend.app.services.simulation_manager._PROJECT_ROOT", tmp_path):
            created = await mgr.create_session(valid_request)
        sid = created["session_id"]

        profiles = []
        for i in range(3):
            p = MagicMock()
            p.agent_type = "consumer"
            p.age = 25 + i
            p.sex = "F"
            p.district = "Wan Chai"
            p.occupation = "Teacher"
            p.income_bracket = "medium"
            p.education_level = "degree"
            p.marital_status = "single"
            p.housing_type = "public"
            p.openness = 0.6
            p.conscientiousness = 0.7
            p.extraversion = 0.5
            p.agreeableness = 0.8
            p.neuroticism = 0.4
            p.monthly_income = 30000
            p.savings = 100000
            profiles.append(p)

        mock_gen = MagicMock()
        mock_gen._factory.generate_username = MagicMock(side_effect=[f"agent_{i}" for i in range(3)])
        mock_gen.to_persona_string = MagicMock(return_value="Persona text")

        await store_agent_profiles(sid, profiles, mock_gen)

        cursor = await sim_db.execute(
            "SELECT COUNT(*) as cnt FROM agent_profiles WHERE session_id = ?",
            (sid,),
        )
        row = await cursor.fetchone()
        assert row["cnt"] == 3

    @pytest.mark.asyncio
    async def test_batch_insert_fields_correct(self, sim_db, mock_runner, valid_request, tmp_path):
        mgr = SimulationManager(runner=mock_runner)
        with patch("backend.app.services.simulation_manager._PROJECT_ROOT", tmp_path):
            created = await mgr.create_session(valid_request)
        sid = created["session_id"]

        p = MagicMock()
        p.agent_type = "investor"
        p.age = 45
        p.sex = "M"
        p.district = "Central"
        p.occupation = "Banker"
        p.income_bracket = "high"
        p.education_level = "masters"
        p.marital_status = "married"
        p.housing_type = "private"
        p.openness = 0.9
        p.conscientiousness = 0.8
        p.extraversion = 0.7
        p.agreeableness = 0.6
        p.neuroticism = 0.2
        p.monthly_income = 80000
        p.savings = 500000

        mock_gen = MagicMock()
        mock_gen._factory.generate_username = MagicMock(return_value="banker_01")
        mock_gen.to_persona_string = MagicMock(return_value="Rich banker")

        await store_agent_profiles(sid, [p], mock_gen)

        cursor = await sim_db.execute("SELECT * FROM agent_profiles WHERE session_id = ?", (sid,))
        row = await cursor.fetchone()
        assert row["agent_type"] == "investor"
        assert row["age"] == 45
        assert row["district"] == "Central"
        assert row["oasis_username"] == "banker_01"
        assert row["oasis_persona"] == "Rich banker"
