"""DuckDB analytical overlay for heavy aggregation queries.

DuckDB reads the SQLite file directly (zero-copy via its SQLite scanner),
providing columnar vectorised execution for queries that would otherwise
bottleneck the aiosqlite WAL writer.

Use cases:
  - Emergence metrics aggregation (belief_states × agents × rounds)
  - Monte Carlo result percentile computation
  - Bulk faction/tipping-point analytics across sessions
  - Cross-session comparison queries

DuckDB operates **read-only** on the SQLite file — all writes still go
through aiosqlite to preserve WAL consistency.

Usage::

    from backend.app.utils.duckdb_analytics import get_analytics, AnalyticsQuery

    analytics = get_analytics()
    result = analytics.query(
        "SELECT topic, AVG(stance) FROM belief_states WHERE session_id = ? GROUP BY topic",
        params=("abc123",),
    )

References:
    DuckDB SQLite Scanner: https://duckdb.org/docs/extensions/sqlite_scanner
"""

from __future__ import annotations

import re
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.config import get_settings
from backend.app.utils.logger import get_logger

logger = get_logger("duckdb_analytics")

# ---------------------------------------------------------------------------
# Table name allowlist — prevents SQL injection via f-string interpolation
# ---------------------------------------------------------------------------

_VALID_TABLES: frozenset[str] = frozenset(
    {
        "agent_profiles",
        "belief_states",
        "simulation_actions",
        "simulation_sessions",
        "emotional_states",
        "agent_memories",
        "kg_nodes",
        "kg_edges",
        "kg_communities",
        "agent_relationships",
        "agent_decisions",
        "hk_data_snapshots",
        "market_data",
        "macro_scenarios",
        "ensemble_results",
        "validation_runs",
        "social_sentiment",
        "echo_chamber_snapshots",
        "news_headlines",
        "network_events",
        "agent_feeds",
        "cognitive_dissonance",
        "polarization_snapshots",
        "emergence_metrics",
        "cognitive_fingerprints",
        "world_events",
        "faction_snapshots_v2",
        "tipping_points",
        "debate_rounds",
        "consensus_scores",
        "multi_run_results",
        "seed_world_context",
        "seed_persona_templates",
        "memory_triples",
        "reports",
        "scenario_branches",
    }
)

# ---------------------------------------------------------------------------
# Optional dependency guard
# ---------------------------------------------------------------------------

try:
    import duckdb

    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False
    logger.info("duckdb not installed — analytical overlay unavailable")

# ---------------------------------------------------------------------------
# Frozen result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AnalyticsResult:
    """Immutable result from a DuckDB analytical query.

    Attributes:
        columns: Column names from the result set.
        rows: Tuple of tuples — each inner tuple is one row.
        row_count: Number of rows returned.
    """

    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    row_count: int

    def to_dicts(self) -> list[dict[str, Any]]:
        """Convert rows to a list of dicts keyed by column name."""
        return [dict(zip(self.columns, row)) for row in self.rows]


_EMPTY_RESULT = AnalyticsResult(columns=(), rows=(), row_count=0)

# ---------------------------------------------------------------------------
# Analytics engine (thread-safe singleton)
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_instance: DuckDBAnalytics | None = None


class DuckDBAnalytics:
    """Read-only DuckDB analytical engine over the SQLite database.

    Maintains a single DuckDB in-memory connection that attaches the SQLite
    file via the ``sqlite_scanner`` extension.  Re-attaches automatically if
    the database path changes (e.g. workspace routing).

    Thread-safe: all public methods acquire an internal lock.
    """

    def __init__(self, sqlite_path: str | Path) -> None:
        self._sqlite_path = str(sqlite_path)
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._lock = threading.Lock()

    def _validate_table(self, name: str) -> str:
        """Return ``name`` if it is in the allowlist, otherwise raise ValueError."""
        if name not in _VALID_TABLES:
            raise ValueError(f"Invalid table name: {name!r}")
        return name

    def _ensure_connection(self) -> duckdb.DuckDBPyConnection:
        """Lazily create the DuckDB connection and attach SQLite.

        Acquires ``self._lock`` internally so the check-then-create sequence
        is atomic.  Callers must NOT hold ``self._lock`` when calling this
        method — doing so would deadlock because ``threading.Lock`` is
        non-reentrant.  ``query`` and ``query_df`` therefore call this method
        first (outside their own lock scope) and then acquire the lock only
        for the query-execution phase.
        """
        with self._lock:
            if self._conn is not None:
                return self._conn

            if not HAS_DUCKDB:
                raise RuntimeError("duckdb is not installed")

            # Validate path: only allow safe filesystem characters to prevent
            # SQL injection via the ATTACH statement.
            if not re.match(r"^[\w./\-]+$", self._sqlite_path):
                raise ValueError(f"Invalid database path: {self._sqlite_path!r}")

            conn = duckdb.connect(":memory:")
            conn.execute("INSTALL sqlite; LOAD sqlite;")
            # Path is safe to interpolate: validated by regex above to contain
            # only word chars, dots, slashes, and hyphens — no SQL metacharacters.
            conn.execute(f"ATTACH '{self._sqlite_path}' AS sqlite_db (TYPE SQLITE, READ_ONLY)")
            # Set default schema so queries can reference tables directly
            conn.execute("USE sqlite_db")
            self._conn = conn
            logger.info("DuckDB attached to SQLite at %s", self._sqlite_path)
            return conn

    def query(
        self,
        sql: str,
        params: Sequence[Any] = (),
    ) -> AnalyticsResult:
        """Execute a read-only SQL query and return an AnalyticsResult.

        Args:
            sql: SQL query string (may use $1, $2 positional placeholders).
            params: Query parameters (positional).

        Returns:
            Frozen AnalyticsResult. Returns empty result on any failure.
        """
        try:
            # _ensure_connection acquires self._lock internally for init.
            conn = self._ensure_connection()
            with self._lock:
                if params:
                    result = conn.execute(sql, list(params))
                else:
                    result = conn.execute(sql)
                columns = tuple(desc[0] for desc in result.description or [])
                rows = tuple(tuple(row) for row in result.fetchall())
            return AnalyticsResult(
                columns=columns,
                rows=rows,
                row_count=len(rows),
            )
        except Exception as exc:
            logger.warning("DuckDB query failed: %s — sql: %s", exc, sql[:200])
            return _EMPTY_RESULT

    def query_df(self, sql: str, params: Sequence[Any] = ()) -> Any:
        """Execute query and return a pandas DataFrame (or None on failure).

        Requires pandas to be installed. Returns None if pandas is unavailable
        or the query fails.
        """
        try:
            import pandas  # noqa: PLC0415, F811

            # _ensure_connection acquires self._lock internally for init.
            conn = self._ensure_connection()
            with self._lock:
                if params:
                    result = conn.execute(sql, list(params))
                else:
                    result = conn.execute(sql)
                return result.fetchdf()
        except ImportError:
            logger.warning("pandas not available for query_df")
            return None
        except Exception as exc:
            logger.warning("DuckDB query_df failed: %s", exc)
            return None

    def aggregate_beliefs(
        self,
        session_id: str,
        round_number: int | None = None,
    ) -> AnalyticsResult:
        """Vectorised belief aggregation across all agents for a session.

        Returns per-topic statistics: mean, std, min, max, count.
        Optionally filtered to a specific round.
        """
        where = "WHERE session_id = $1"
        params: list[Any] = [session_id]
        if round_number is not None:
            where += " AND round_number = $2"
            params.append(round_number)

        sql = f"""
            SELECT
                topic,
                round_number,
                COUNT(*) AS agent_count,
                AVG(stance) AS mean_stance,
                STDDEV_SAMP(stance) AS std_stance,
                MIN(stance) AS min_stance,
                MAX(stance) AS max_stance,
                PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY stance) AS p25,
                PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY stance) AS median,
                PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY stance) AS p75
            FROM belief_states
            {where}
            GROUP BY topic, round_number
            ORDER BY topic, round_number
        """
        return self.query(sql, params)

    def aggregate_monte_carlo(self, session_id: str) -> AnalyticsResult:
        """Vectorised percentile computation for Monte Carlo ensemble results."""
        sql = """
            SELECT
                metric,
                COUNT(*) AS n_trials,
                AVG(value) AS mean_val,
                STDDEV_SAMP(value) AS std_val,
                PERCENTILE_CONT(0.05) WITHIN GROUP (ORDER BY value) AS p5,
                PERCENTILE_CONT(0.10) WITHIN GROUP (ORDER BY value) AS p10,
                PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY value) AS p25,
                PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY value) AS median,
                PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY value) AS p75,
                PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY value) AS p90,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY value) AS p95
            FROM multi_run_results
            WHERE session_id = $1
            GROUP BY metric
            ORDER BY metric
        """
        return self.query(sql, [session_id])

    def faction_timeline(self, session_id: str) -> AnalyticsResult:
        """Cross-round faction evolution with per-round membership counts."""
        sql = """
            SELECT
                round_number,
                COUNT(DISTINCT faction_id) AS n_factions,
                COUNT(*) AS n_agents,
                MAX(agent_count) AS largest_faction_size
            FROM (
                SELECT
                    round_number,
                    json_extract(snapshot_json, '$.faction_id') AS faction_id,
                    COUNT(*) AS agent_count
                FROM faction_snapshots_v2
                WHERE session_id = $1
                GROUP BY round_number, faction_id
            ) sub
            GROUP BY round_number
            ORDER BY round_number
        """
        return self.query(sql, [session_id])

    def emergence_heatmap(self, session_id: str) -> AnalyticsResult:
        """TDMI scores as a topic × lag heatmap for emergence visualisation."""
        sql = """
            SELECT
                topic,
                lag,
                round_number,
                tdmi_score,
                n_samples
            FROM emergence_metrics
            WHERE session_id = $1
            ORDER BY round_number, topic, lag
        """
        return self.query(sql, [session_id])

    def health_check(self) -> bool:
        """Verify DuckDB can read the SQLite database."""
        result = self.query("SELECT COUNT(*) AS n FROM simulation_sessions")
        return result.row_count > 0

    def close(self) -> None:
        """Close the DuckDB connection (idempotent)."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None


def get_analytics(sqlite_path: str | Path | None = None) -> DuckDBAnalytics:
    """Get or create the singleton DuckDBAnalytics instance.

    Args:
        sqlite_path: Override path to the SQLite database file.
            Defaults to the configured DATABASE_PATH.

    Returns:
        DuckDBAnalytics instance (thread-safe singleton).
    """
    global _instance
    with _lock:
        if _instance is not None:
            return _instance

        if sqlite_path is None:
            settings = get_settings()
            sqlite_path = settings.DATABASE_PATH

        _instance = DuckDBAnalytics(sqlite_path)
        return _instance


def shutdown_analytics() -> None:
    """Shutdown the singleton analytics engine (for app teardown)."""
    global _instance
    with _lock:
        if _instance is not None:
            _instance.close()
            _instance = None
