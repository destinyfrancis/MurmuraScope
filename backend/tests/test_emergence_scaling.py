"""Unit tests for emergence scaling fixes.

These are unit tests (no real DB): they verify cache mechanics and contagion logic
using in-memory data structures and mocks.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_round_profiles_dict_initialised_empty():
    """SimulationRunner must have _round_profiles dict from __init__."""
    from backend.app.services.simulation_runner import SimulationRunner
    runner = SimulationRunner()
    assert hasattr(runner, "_round_profiles")
    assert isinstance(runner._round_profiles, dict)
    assert len(runner._round_profiles) == 0


@pytest.mark.asyncio
async def test_fetch_and_cache_profiles_populates_cache():
    """_fetch_and_cache_profiles stores rows keyed by session_id."""
    from backend.app.services.simulation_runner import SimulationRunner

    runner = SimulationRunner()
    fake_rows = [{"id": 1, "agent_type": "worker"}, {"id": 2, "agent_type": "student"}]

    mock_cursor = AsyncMock()
    mock_cursor.fetchall = AsyncMock(return_value=fake_rows)
    mock_db = MagicMock()
    mock_db.execute = AsyncMock(return_value=mock_cursor)
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.app.utils.db.get_db", return_value=mock_db):
        result = await runner._fetch_and_cache_profiles("sess-abc")

    assert runner._round_profiles["sess-abc"] == fake_rows
    assert result == fake_rows


def test_cache_pop_removes_session():
    """Cache cleanup must remove the session key without raising on missing key."""
    from backend.app.services.simulation_runner import SimulationRunner

    runner = SimulationRunner()
    runner._round_profiles["sess-xyz"] = [{"id": 1}]
    runner._round_profiles.pop("sess-xyz", None)
    assert "sess-xyz" not in runner._round_profiles

    # Must not raise on absent key
    runner._round_profiles.pop("sess-missing", None)


@pytest.mark.asyncio
async def test_process_round_decisions_no_db_call_when_cache_empty():
    """With empty cache, _process_round_decisions returns early without touching DB."""
    from backend.app.services.simulation_runner import SimulationRunner
    runner = SimulationRunner()
    runner._round_profiles["sess-1"] = []

    # Empty cache → `if not rows: return` fires before any DB call
    with patch("backend.app.services.simulation_hooks_agent.get_db") as mock_gdb:
        await runner._process_round_decisions("sess-1", 0)
        mock_gdb.assert_not_called()


@pytest.mark.asyncio
async def test_process_belief_update_no_db_call_when_cache_empty():
    """With empty cache, _process_belief_update returns early without touching DB."""
    from backend.app.services.simulation_runner import SimulationRunner
    runner = SimulationRunner()
    runner._round_profiles["sess-3"] = []

    # The standalone agent_profiles block is deleted; empty cache → early return
    # before any remaining DB calls (belief loading, etc.)
    with patch("backend.app.services.simulation_hooks_agent.get_db") as mock_gdb:
        await runner._process_belief_update("sess-3", 0)
        mock_gdb.assert_not_called()


@pytest.mark.asyncio
async def test_process_round_consumption_no_db_call_when_cache_empty():
    """With empty cache, _process_round_consumption returns early without touching DB."""
    from backend.app.services.simulation_runner import SimulationRunner
    runner = SimulationRunner()
    runner._round_profiles["sess-4"] = []

    with patch("backend.app.services.simulation_hooks_agent.get_db") as mock_gdb:
        await runner._process_round_consumption("sess-4", 0)
        mock_gdb.assert_not_called()


@pytest.mark.asyncio
async def test_process_emotional_state_does_not_query_agent_profiles():
    """_process_emotional_state must not execute SELECT on agent_profiles after cache fix.

    Note: this function still opens get_db for engine.load_states() — so we cannot
    use assert_not_called(). Instead, track executed SQL and verify none touch agent_profiles.
    """
    from backend.app.services.simulation_runner import SimulationRunner
    runner = SimulationRunner()
    runner._round_profiles["sess-2"] = []  # empty → early return after load_states

    executed_sqls: list[str] = []

    mock_cursor = AsyncMock()
    mock_cursor.fetchall = AsyncMock(return_value=[])

    mock_db = MagicMock()
    mock_db.row_factory = None

    async def tracking_execute(sql: str, *args, **kwargs):
        executed_sqls.append(sql.strip())
        return mock_cursor

    mock_db.execute = tracking_execute
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.app.services.simulation_hooks_agent.get_db", return_value=mock_db):
        with patch("backend.app.services.simulation_hooks_agent.EmotionalEngine") as mock_ee_cls:
            mock_engine = MagicMock()
            mock_engine.load_states = AsyncMock(return_value={})
            mock_ee_cls.return_value = mock_engine
            await runner._process_emotional_state("sess-2", 1)

    # None of the SQL calls should touch agent_profiles
    for sql in executed_sqls:
        assert "agent_profiles" not in sql.lower(), (
            f"Unexpected agent_profiles query executed: {sql!r}"
        )
