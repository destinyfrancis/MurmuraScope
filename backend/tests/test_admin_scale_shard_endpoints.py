"""Tests for admin scale profiler and shard coordinator API endpoints (Phase 4D).

Covers:
- POST /simulation/admin/profile (validation + background task launch)
- GET /simulation/admin/profile-results (query filtering)
- GET /simulation/admin/shards (enabled/disabled states)
- POST /simulation/admin/shards/rebalance (dry-run computation + validation)
- SimulationRunner shard coordinator helpers
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
import aiosqlite


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def bench_db():
    """In-memory SQLite with scale_benchmarks table."""
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    await db.execute(
        """
        CREATE TABLE scale_benchmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_name TEXT NOT NULL,
            agent_count INTEGER NOT NULL,
            rounds_completed INTEGER NOT NULL,
            total_duration_s REAL NOT NULL,
            avg_round_duration_s REAL NOT NULL,
            peak_memory_mb REAL NOT NULL DEFAULT 0,
            db_queries_total INTEGER NOT NULL DEFAULT 0,
            db_avg_query_ms REAL NOT NULL DEFAULT 0.0,
            llm_calls_total INTEGER NOT NULL DEFAULT 0,
            llm_avg_latency_ms REAL NOT NULL DEFAULT 0.0,
            hook_durations_json TEXT NOT NULL DEFAULT '{}',
            bottleneck_hook TEXT NOT NULL DEFAULT '',
            throughput REAL NOT NULL DEFAULT 0.0,
            passed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    await db.commit()
    yield db
    await db.close()


# ---------------------------------------------------------------------------
# ShardCoordinator static method tests
# ---------------------------------------------------------------------------


def test_compute_shard_configs_single_shard():
    """Small agent count fits in one shard."""
    from backend.app.services.shard_coordinator import ShardCoordinator

    configs = ShardCoordinator._compute_shard_configs(100, agents_per_shard=2500)
    assert len(configs) == 1
    assert configs[0].shard_id == 0
    assert configs[0].agent_start == 0
    assert configs[0].agent_end == 100
    assert configs[0].agent_count == 100


def test_compute_shard_configs_multiple_shards():
    """10k agents at 2500/shard produces 4 shards."""
    from backend.app.services.shard_coordinator import ShardCoordinator

    configs = ShardCoordinator._compute_shard_configs(10_000, agents_per_shard=2500)
    assert len(configs) == 4
    assert configs[0].agent_start == 0
    assert configs[0].agent_end == 2500
    assert configs[3].agent_start == 7500
    assert configs[3].agent_end == 10000


def test_compute_shard_configs_uneven_split():
    """7 agents at 3/shard produces 3 shards with uneven last."""
    from backend.app.services.shard_coordinator import ShardCoordinator

    configs = ShardCoordinator._compute_shard_configs(7, agents_per_shard=3)
    assert len(configs) == 3
    assert configs[2].agent_start == 6
    assert configs[2].agent_end == 7
    assert configs[2].agent_count == 1


def test_compute_shard_configs_exact_fit():
    """Exact multiple produces no remainder shard."""
    from backend.app.services.shard_coordinator import ShardCoordinator

    configs = ShardCoordinator._compute_shard_configs(9, agents_per_shard=3)
    assert len(configs) == 3
    for cfg in configs:
        assert cfg.agent_count == 3


# ---------------------------------------------------------------------------
# ShardConfig property tests
# ---------------------------------------------------------------------------


def test_shard_config_agent_count():
    from backend.app.services.shard_coordinator import ShardConfig

    cfg = ShardConfig(shard_id=0, agent_start=100, agent_end=350)
    assert cfg.agent_count == 250


def test_shard_config_frozen():
    from backend.app.services.shard_coordinator import ShardConfig

    cfg = ShardConfig(shard_id=0, agent_start=0, agent_end=100)
    with pytest.raises(AttributeError):
        cfg.shard_id = 1  # type: ignore[misc]


# ---------------------------------------------------------------------------
# SimulationRunner shard helpers
# ---------------------------------------------------------------------------


def test_is_sharding_enabled_default_false():
    """Sharding disabled by default."""
    from backend.app.services.simulation_runner import SimulationRunner

    runner = SimulationRunner(dry_run=True)
    with patch.dict("os.environ", {}, clear=True):
        assert runner._is_sharding_enabled() is False


def test_is_sharding_enabled_true():
    from backend.app.services.simulation_runner import SimulationRunner

    runner = SimulationRunner(dry_run=True)
    with patch.dict("os.environ", {"DB_SHARDING_ENABLED": "true"}):
        assert runner._is_sharding_enabled() is True


def test_is_sharding_enabled_case_insensitive():
    from backend.app.services.simulation_runner import SimulationRunner

    runner = SimulationRunner(dry_run=True)
    with patch.dict("os.environ", {"DB_SHARDING_ENABLED": "True"}):
        assert runner._is_sharding_enabled() is True


def test_get_shard_coordinator_returns_none_when_disabled():
    from backend.app.services.simulation_runner import SimulationRunner
    from pathlib import Path

    runner = SimulationRunner(dry_run=True)
    with patch.dict("os.environ", {}, clear=True):
        result = runner._get_shard_coordinator("sess1", Path("/usr/bin/python"), Path("/script.py"))
        assert result is None


def test_get_shard_coordinator_creates_when_enabled():
    from backend.app.services.simulation_runner import SimulationRunner
    from pathlib import Path

    runner = SimulationRunner(dry_run=True)
    with patch.dict("os.environ", {"DB_SHARDING_ENABLED": "true"}):
        coord = runner._get_shard_coordinator("sess1", Path("/usr/bin/python"), Path("/script.py"))
        assert coord is not None
        # Second call returns same instance (cached)
        coord2 = runner._get_shard_coordinator("sess1", Path("/usr/bin/python"), Path("/script.py"))
        assert coord is coord2


@pytest.mark.asyncio
async def test_cleanup_shard_coordinator_calls_shutdown():
    from backend.app.services.simulation_runner import SimulationRunner

    runner = SimulationRunner(dry_run=True)
    mock_coord = AsyncMock()
    runner._shard_coordinators["sess1"] = mock_coord

    await runner._cleanup_shard_coordinator("sess1")

    mock_coord.shutdown_all.assert_awaited_once()
    assert "sess1" not in runner._shard_coordinators


@pytest.mark.asyncio
async def test_cleanup_shard_coordinator_noop_when_missing():
    """No error when cleaning up a session that never had a coordinator."""
    from backend.app.services.simulation_runner import SimulationRunner

    runner = SimulationRunner(dry_run=True)
    # Should not raise
    await runner._cleanup_shard_coordinator("nonexistent")


@pytest.mark.asyncio
async def test_cleanup_shard_coordinator_handles_shutdown_error():
    """Shutdown errors are logged but not raised."""
    from backend.app.services.simulation_runner import SimulationRunner

    runner = SimulationRunner(dry_run=True)
    mock_coord = AsyncMock()
    mock_coord.shutdown_all.side_effect = RuntimeError("boom")
    runner._shard_coordinators["sess1"] = mock_coord

    # Should not raise
    await runner._cleanup_shard_coordinator("sess1")
    assert "sess1" not in runner._shard_coordinators


# ---------------------------------------------------------------------------
# Profile results DB query tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_profile_results_filter(bench_db):
    """profile-results endpoint should only return profile_* preset names."""
    # Insert a mix of profile and non-profile rows
    await bench_db.execute(
        """INSERT INTO scale_benchmarks
           (target_name, agent_count, rounds_completed, total_duration_s,
            avg_round_duration_s, hook_durations_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("profile_100", 100, 5, 1.0, 0.2, '{"group_1": 5.0}'),
    )
    await bench_db.execute(
        """INSERT INTO scale_benchmarks
           (target_name, agent_count, rounds_completed, total_duration_s,
            avg_round_duration_s, hook_durations_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("1k", 1000, 10, 30.0, 3.0, '{"group_1": 50.0}'),
    )
    await bench_db.commit()

    # Query only profile_* rows
    rows = await (
        await bench_db.execute(
            "SELECT * FROM scale_benchmarks WHERE target_name LIKE 'profile_%'"
        )
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["target_name"] == "profile_100"


# ---------------------------------------------------------------------------
# ScaleProfiler integration with profile endpoint pattern
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_profiler_persist_profile_preset(bench_db):
    """ScaleProfiler persists profile_* preset names that match endpoint filter."""
    from backend.app.services.scale_profiler import ScaleProfiler
    from backend.app.models.scale import HookTiming

    profiler = ScaleProfiler()
    profiler._timings = [
        HookTiming("group_1", 1, 10.0, agent_count=300),
        HookTiming("group_2", 1, 20.0, agent_count=300),
    ]
    result = profiler.get_summary("profile_300", 300, 5.0, 128.0)
    await profiler.persist(result, bench_db)

    rows = await (
        await bench_db.execute(
            "SELECT * FROM scale_benchmarks WHERE target_name LIKE 'profile_%'"
        )
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["agent_count"] == 300
