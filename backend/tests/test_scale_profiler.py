"""Tests for ScaleProfiler service (Phase 4A).

~10 tests covering:
- start_hook / end_hook timing
- get_summary aggregation
- bottleneck_hook detection
- persist round-trip
- clear resets state
"""

from __future__ import annotations

import time

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
# Timing tests
# ---------------------------------------------------------------------------


def test_start_hook_returns_float():
    from backend.app.services.scale_profiler import ScaleProfiler

    p = ScaleProfiler()
    t = p.start_hook("group_1", 1)
    assert isinstance(t, float)
    assert t > 0.0


def test_end_hook_returns_hook_timing():
    from backend.app.services.scale_profiler import ScaleProfiler
    from backend.app.models.scale import HookTiming

    p = ScaleProfiler()
    t0 = p.start_hook("group_1", 1)
    timing = p.end_hook("group_1", 1, t0, agent_count=100)

    assert isinstance(timing, HookTiming)
    assert timing.hook_name == "group_1"
    assert timing.round_number == 1
    assert timing.duration_ms >= 0.0
    assert timing.agent_count == 100


def test_end_hook_duration_positive():
    from backend.app.services.scale_profiler import ScaleProfiler

    p = ScaleProfiler()
    t0 = p.start_hook("group_2", 3)
    time.sleep(0.005)  # 5 ms sleep
    timing = p.end_hook("group_2", 3, t0)

    assert timing.duration_ms >= 1.0  # at least 1 ms


def test_timing_count_increments():
    from backend.app.services.scale_profiler import ScaleProfiler

    p = ScaleProfiler()
    assert p.timing_count == 0
    t0 = p.start_hook("feed_ranking", 1)
    p.end_hook("feed_ranking", 1, t0)
    assert p.timing_count == 1
    t1 = p.start_hook("group_1", 1)
    p.end_hook("group_1", 1, t1)
    assert p.timing_count == 2


# ---------------------------------------------------------------------------
# Aggregation tests
# ---------------------------------------------------------------------------


def test_get_summary_empty_returns_zero_rounds():
    from backend.app.services.scale_profiler import ScaleProfiler
    from backend.app.models.scale import BenchmarkResult

    p = ScaleProfiler()
    result = p.get_summary("standard", 300, 60.0, 512.0)

    assert isinstance(result, BenchmarkResult)
    assert result.rounds_completed == 0
    assert result.avg_round_duration_s == 0.0


def test_get_summary_aggregates_hooks():
    from backend.app.services.scale_profiler import ScaleProfiler

    p = ScaleProfiler()
    for rnd in range(3):
        t0 = p.start_hook("group_1", rnd)
        p.end_hook("group_1", rnd, t0, agent_count=100)
        t1 = p.start_hook("group_2", rnd)
        p.end_hook("group_2", rnd, t1, agent_count=100)

    result = p.get_summary("standard", 300, 90.0, 1024.0)

    assert result.rounds_completed == 3
    assert "group_1" in result.hook_durations
    assert "group_2" in result.hook_durations
    assert result.total_duration_s == 90.0
    assert result.agent_count == 300


def test_get_summary_bottleneck_hook():
    from backend.app.services.scale_profiler import ScaleProfiler

    p = ScaleProfiler()
    # Manually inject timings with known durations
    from backend.app.models.scale import HookTiming
    p._timings = [
        HookTiming("fast_hook", 1, 5.0),
        HookTiming("slow_hook", 1, 100.0),
        HookTiming("fast_hook", 2, 6.0),
        HookTiming("slow_hook", 2, 110.0),
    ]

    result = p.get_summary("standard", 100, 10.0, 256.0)
    assert result.bottleneck_hook == "slow_hook"


def test_get_summary_throughput():
    from backend.app.services.scale_profiler import ScaleProfiler
    from backend.app.models.scale import HookTiming

    p = ScaleProfiler()
    p._timings = [HookTiming("g1", 1, 10.0), HookTiming("g1", 2, 10.0)]

    result = p.get_summary("standard", 1000, 100.0, 512.0)
    # 1000 agents × 2 rounds / 100 s = 20 agents/s
    assert abs(result.throughput_agents_per_sec - 20.0) < 0.1


# ---------------------------------------------------------------------------
# Persist tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_writes_row(bench_db):
    from backend.app.services.scale_profiler import ScaleProfiler
    from backend.app.models.scale import HookTiming

    p = ScaleProfiler()
    p._timings = [HookTiming("group_1", 1, 50.0, agent_count=200)]
    result = p.get_summary("fast", 200, 30.0, 1024.0)

    await p.persist(result, bench_db)

    cursor = await bench_db.execute("SELECT COUNT(*) FROM scale_benchmarks")
    row = await cursor.fetchone()
    assert row[0] == 1


@pytest.mark.asyncio
async def test_persist_stores_correct_values(bench_db):
    from backend.app.services.scale_profiler import ScaleProfiler
    from backend.app.models.scale import HookTiming

    p = ScaleProfiler()
    p._timings = [HookTiming("group_1", 1, 75.0, agent_count=500)]
    result = p.get_summary("deep", 500, 120.0, 2048.0)

    await p.persist(result, bench_db)

    cursor = await bench_db.execute(
        "SELECT target_name, agent_count, total_duration_s FROM scale_benchmarks LIMIT 1"
    )
    row = await cursor.fetchone()
    assert row["target_name"] == "deep"
    assert row["agent_count"] == 500
    assert abs(row["total_duration_s"] - 120.0) < 0.01


# ---------------------------------------------------------------------------
# Clear tests
# ---------------------------------------------------------------------------


def test_clear_resets_timings():
    from backend.app.services.scale_profiler import ScaleProfiler

    p = ScaleProfiler()
    t0 = p.start_hook("group_1", 1)
    p.end_hook("group_1", 1, t0)
    assert p.timing_count == 1

    p.clear()
    assert p.timing_count == 0
