"""Tests for DuckDB analytical overlay.

Tests use an in-memory SQLite database seeded with minimal schema and data,
then verify that the DuckDB scanner can read it correctly.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.app.utils.duckdb_analytics import (
    _EMPTY_RESULT,
    HAS_DUCKDB,
    AnalyticsResult,
    DuckDBAnalytics,
)

pytestmark = pytest.mark.skipif(not HAS_DUCKDB, reason="duckdb not installed")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_sqlite(tmp_path: Path) -> Path:
    """Create a temporary SQLite database with test schema and data."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")

    # Minimal schema matching production tables
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS simulation_sessions (
            id TEXT PRIMARY KEY,
            name TEXT,
            status TEXT DEFAULT 'pending'
        );
        CREATE TABLE IF NOT EXISTS belief_states (
            session_id TEXT,
            agent_id TEXT,
            topic TEXT,
            stance REAL,
            round_number INTEGER,
            confidence REAL DEFAULT 0.5
        );
        CREATE TABLE IF NOT EXISTS emergence_metrics (
            session_id TEXT,
            round_number INTEGER,
            topic TEXT,
            lag INTEGER,
            tdmi_score REAL,
            n_samples INTEGER
        );
        CREATE TABLE IF NOT EXISTS multi_run_results (
            session_id TEXT,
            metric TEXT,
            value REAL,
            trial_id INTEGER
        );
    """)

    # Seed data
    conn.execute(
        "INSERT INTO simulation_sessions (id, name, status) VALUES (?, ?, ?)",
        ("sess1", "Test Session", "completed"),
    )

    # Belief states: 3 agents × 2 topics × 3 rounds
    belief_rows = []
    for agent_id in range(3):
        for topic in ("economy", "housing"):
            for rnd in range(3):
                stance = 0.3 + 0.1 * agent_id + 0.05 * rnd
                belief_rows.append(("sess1", str(agent_id), topic, stance, rnd))
    conn.executemany(
        "INSERT INTO belief_states (session_id, agent_id, topic, stance, round_number) VALUES (?, ?, ?, ?, ?)",
        belief_rows,
    )

    # Emergence metrics
    for topic in ("economy", "housing"):
        for lag in (1, 3, 5):
            conn.execute(
                "INSERT INTO emergence_metrics VALUES (?, ?, ?, ?, ?, ?)",
                ("sess1", 5, topic, lag, 0.03 + 0.01 * lag, 50),
            )

    # Monte Carlo results
    import random

    rng = random.Random(42)
    for trial in range(100):
        for metric in ("hsi_level", "unemployment"):
            val = rng.gauss(100 if metric == "hsi_level" else 5, 10)
            conn.execute(
                "INSERT INTO multi_run_results VALUES (?, ?, ?, ?)",
                ("sess1", metric, val, trial),
            )

    conn.commit()
    conn.close()
    return db_path


@pytest.fixture()
def analytics(tmp_sqlite: Path) -> DuckDBAnalytics:
    """Create a DuckDBAnalytics instance for the temp database."""
    eng = DuckDBAnalytics(tmp_sqlite)
    yield eng
    eng.close()


# ---------------------------------------------------------------------------
# Tests: AnalyticsResult dataclass
# ---------------------------------------------------------------------------


class TestAnalyticsResult:
    def test_frozen(self) -> None:
        r = AnalyticsResult(columns=("a",), rows=((1,),), row_count=1)
        with pytest.raises(AttributeError):
            r.row_count = 99  # type: ignore[misc]

    def test_to_dicts(self) -> None:
        r = AnalyticsResult(
            columns=("name", "value"),
            rows=(("foo", 1), ("bar", 2)),
            row_count=2,
        )
        dicts = r.to_dicts()
        assert len(dicts) == 2
        assert dicts[0] == {"name": "foo", "value": 1}
        assert dicts[1] == {"name": "bar", "value": 2}

    def test_empty_result(self) -> None:
        assert _EMPTY_RESULT.row_count == 0
        assert _EMPTY_RESULT.columns == ()
        assert _EMPTY_RESULT.rows == ()


# ---------------------------------------------------------------------------
# Tests: Basic query
# ---------------------------------------------------------------------------


class TestBasicQuery:
    def test_health_check(self, analytics: DuckDBAnalytics) -> None:
        assert analytics.health_check() is True

    def test_simple_count(self, analytics: DuckDBAnalytics) -> None:
        result = analytics.query("SELECT COUNT(*) AS n FROM simulation_sessions")
        assert result.row_count == 1
        assert result.rows[0][0] == 1  # one session

    def test_query_with_params(self, analytics: DuckDBAnalytics) -> None:
        result = analytics.query(
            "SELECT name FROM simulation_sessions WHERE id = $1",
            params=["sess1"],
        )
        assert result.row_count == 1
        assert result.rows[0][0] == "Test Session"

    def test_bad_query_returns_empty(self, analytics: DuckDBAnalytics) -> None:
        result = analytics.query("SELECT * FROM nonexistent_table_xyz")
        assert result.row_count == 0

    def test_close_idempotent(self, analytics: DuckDBAnalytics) -> None:
        analytics.close()
        analytics.close()  # should not raise


# ---------------------------------------------------------------------------
# Tests: Analytical queries
# ---------------------------------------------------------------------------


class TestAggregateBeliefs:
    def test_all_rounds(self, analytics: DuckDBAnalytics) -> None:
        result = analytics.aggregate_beliefs("sess1")
        assert result.row_count > 0
        cols = result.columns
        assert "topic" in cols
        assert "mean_stance" in cols
        assert "std_stance" in cols

    def test_specific_round(self, analytics: DuckDBAnalytics) -> None:
        result = analytics.aggregate_beliefs("sess1", round_number=1)
        assert result.row_count > 0
        # All rows should be for round 1
        round_col_idx = result.columns.index("round_number")
        for row in result.rows:
            assert row[round_col_idx] == 1

    def test_nonexistent_session(self, analytics: DuckDBAnalytics) -> None:
        result = analytics.aggregate_beliefs("nonexistent")
        assert result.row_count == 0


class TestAggregateMonteCarlo:
    def test_percentiles(self, analytics: DuckDBAnalytics) -> None:
        result = analytics.aggregate_monte_carlo("sess1")
        assert result.row_count == 2  # hsi_level + unemployment
        dicts = result.to_dicts()
        metrics = {d["metric"] for d in dicts}
        assert metrics == {"hsi_level", "unemployment"}
        # Verify percentile ordering: p5 <= p25 <= median <= p75 <= p95
        for d in dicts:
            assert d["p5"] <= d["p25"] <= d["median"] <= d["p75"] <= d["p95"]


class TestEmergenceHeatmap:
    def test_heatmap_data(self, analytics: DuckDBAnalytics) -> None:
        result = analytics.emergence_heatmap("sess1")
        assert result.row_count == 6  # 2 topics × 3 lags
        cols = result.columns
        assert "topic" in cols
        assert "lag" in cols
        assert "tdmi_score" in cols
