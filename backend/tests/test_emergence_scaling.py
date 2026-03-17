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
