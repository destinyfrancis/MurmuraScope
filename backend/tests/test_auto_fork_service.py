"""Unit tests for AutoForkService."""

from __future__ import annotations

import dataclasses
from contextlib import asynccontextmanager
from unittest.mock import patch

import aiosqlite
import pytest
import pytest_asyncio

from backend.app.services.auto_fork_service import (
    _JSD_BASE_THRESHOLD,
    _JSD_STRONG_SIGNAL_MULTIPLIER,
    _MAX_AUTO_FORKS,
    _MIN_AUTO_FORKS,
    AutoForkResult,
    _apply_counterfactual_nudge,
    _nudge_description,
    compute_fork_budget,
    fork_at_tipping_point,
)
from backend.app.services.emergence_tracker import TippingPoint

# ---------------------------------------------------------------------------
# Minimal DB schema for fork integration tests
# ---------------------------------------------------------------------------

_FORK_DB_DDL = """
CREATE TABLE simulation_sessions (
    id TEXT PRIMARY KEY, name TEXT, sim_mode TEXT, scenario_type TEXT,
    status TEXT, config_json TEXT, agent_count INTEGER, round_count INTEGER,
    llm_provider TEXT, llm_model TEXT, oasis_db_path TEXT, created_at TEXT
);
CREATE TABLE agent_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, agent_type TEXT,
    age INTEGER, sex TEXT, district TEXT, occupation TEXT, income_bracket TEXT,
    education_level TEXT, marital_status TEXT, housing_type TEXT,
    openness REAL, conscientiousness REAL, extraversion REAL, agreeableness REAL,
    neuroticism REAL, monthly_income REAL, savings REAL, oasis_persona TEXT,
    oasis_username TEXT, created_at TEXT
);
CREATE TABLE agent_memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, agent_id INTEGER,
    round_number INTEGER, memory_text TEXT, salience_score REAL,
    memory_type TEXT, created_at TEXT
);
CREATE TABLE simulation_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, agent_id INTEGER,
    round_number INTEGER, action_type TEXT, content TEXT, platform TEXT,
    created_at TEXT
);
CREATE TABLE kg_nodes (
    id TEXT, session_id TEXT, entity_type TEXT, title TEXT, description TEXT,
    properties TEXT, created_at TEXT, PRIMARY KEY (id, session_id)
);
CREATE TABLE relationship_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT, agent_a_id INTEGER, agent_b_id INTEGER,
    round_number INTEGER, intimacy REAL, passion REAL, commitment REAL,
    satisfaction REAL, alternatives REAL, investment REAL, trust REAL,
    interaction_count INTEGER, rounds_since_change INTEGER, updated_at TEXT,
    UNIQUE (session_id, agent_a_id, agent_b_id, round_number)
);
CREATE TABLE scenario_branches (
    id TEXT PRIMARY KEY, parent_session_id TEXT, branch_session_id TEXT,
    scenario_variant TEXT, label TEXT, fork_round INTEGER, created_at TEXT,
    UNIQUE (parent_session_id, branch_session_id)
);
"""

_PARENT_ID = "parent-session-001"


@pytest_asyncio.fixture()
async def fork_db():
    """In-memory SQLite DB with fork schema and a seeded parent session."""
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    await db.executescript(_FORK_DB_DDL)
    # Seed parent session row
    await db.execute(
        """INSERT INTO simulation_sessions
           (id, name, sim_mode, scenario_type, status, config_json,
            agent_count, round_count, llm_provider, llm_model, oasis_db_path, created_at)
           VALUES (?, 'test', 'parallel', 'kg_driven', 'running', '{}',
                   100, 20, 'openrouter', 'gemini/flash', '', datetime('now'))""",
        (_PARENT_ID,),
    )
    # Seed one kg_nodes row for parent
    await db.execute(
        """INSERT INTO kg_nodes (id, session_id, entity_type, title, description, properties, created_at)
           VALUES ('node_001', ?, 'person', 'Test Node', 'A test entity', '{}', datetime('now'))""",
        (_PARENT_ID,),
    )
    # Seed one relationship_states row for parent (round 1)
    await db.execute(
        """INSERT INTO relationship_states
           (session_id, agent_a_id, agent_b_id, round_number,
            intimacy, passion, commitment, satisfaction,
            alternatives, investment, trust, interaction_count, rounds_since_change, updated_at)
           VALUES (?, 1, 2, 1, 0.5, 0.4, 0.6, 0.7, 0.3, 0.5, 0.8, 3, 1, datetime('now'))""",
        (_PARENT_ID,),
    )
    await db.commit()
    yield db
    await db.close()


def _make_tipping(round_num: int = 5, jsd: float = 0.25) -> TippingPoint:
    """Strong-signal tipping point (JSD ≥ 0.225)."""
    return TippingPoint(
        simulation_id=_PARENT_ID,
        round_number=round_num,
        trigger_event_id=None,
        kl_divergence=jsd,
        change_direction="polarize",
        affected_faction_ids=(),
    )


# ---------------------------------------------------------------------------
# Task 2.1 (C3) — fork copies kg_nodes and relationship_states
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fork_copies_kg_nodes_and_relationship_states(fork_db):
    """Auto-fork must copy kg_nodes and relationship_states to both branches.

    Before fix: only 7 tables copied — kg_nodes and relationship_states are missing.
    After fix: 9 tables copied including both new tables.
    """

    @asynccontextmanager
    async def _mock_get_db():
        yield fork_db

    tipping = _make_tipping(round_num=5, jsd=0.25)
    with patch("backend.app.services.auto_fork_service.get_db", _mock_get_db):
        result = await fork_at_tipping_point(
            session_id=_PARENT_ID,
            tipping=tipping,
            current_beliefs={"1": {"escalation_index": 0.7}},
            auto_fork_count=0,
            round_count=20,
        )

    assert result is not None, "fork_at_tipping_point returned None unexpectedly"

    for branch_id in (result.natural_branch_id, result.nudged_branch_id):
        # kg_nodes must be copied
        cur = await fork_db.execute("SELECT COUNT(*) FROM kg_nodes WHERE session_id = ?", (branch_id,))
        row = await cur.fetchone()
        assert row[0] == 1, f"kg_nodes not copied to branch {branch_id[:8]}: got {row[0]} rows"

        # relationship_states must be copied (round 1 ≤ fork_round 5)
        cur = await fork_db.execute("SELECT COUNT(*) FROM relationship_states WHERE session_id = ?", (branch_id,))
        row = await cur.fetchone()
        assert row[0] == 1, f"relationship_states not copied to branch {branch_id[:8]}: got {row[0]} rows"


# ---------------------------------------------------------------------------
# Task 2.2 (C4) — fork failure leaves no orphaned sessions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fork_failure_does_not_leave_orphaned_sessions(fork_db):
    """If mid-fork copy fails, no partial session rows should persist.

    We simulate failure by patching agent_profiles INSERT to raise an error.
    The mock get_db calls rollback on exception (mimicking connection close),
    so simulation_sessions must contain only the parent row after the failure.
    """
    original_execute = fork_db.execute

    async def patched_execute(sql, params=()):
        # Trigger on the INSERT INTO agent_profiles ... SELECT ... statement
        if "INSERT INTO agent_profiles" in sql:
            raise Exception("Simulated DB failure during agent_profiles copy")
        return await original_execute(sql, params)

    @asynccontextmanager
    async def _mock_get_db():
        fork_db.execute = patched_execute
        try:
            yield fork_db
        except Exception:
            # Simulate connection close → implicit SQLite rollback
            await fork_db.rollback()
            raise
        finally:
            fork_db.execute = original_execute

    tipping = _make_tipping(round_num=5, jsd=0.25)
    with patch("backend.app.services.auto_fork_service.get_db", _mock_get_db):
        result = await fork_at_tipping_point(
            session_id=_PARENT_ID,
            tipping=tipping,
            current_beliefs={"1": {"escalation_index": 0.7}},
            auto_fork_count=0,
            round_count=20,
        )

    # After failure, function returns None
    assert result is None, "fork_at_tipping_point should return None on failure"

    # DB should have no branch sessions (only parent survives after rollback)
    cur = await fork_db.execute("SELECT COUNT(*) FROM simulation_sessions WHERE id != ?", (_PARENT_ID,))
    row = await cur.fetchone()
    assert row[0] == 0, f"Orphaned session rows found: {row[0]}"


# ---------------------------------------------------------------------------
# _apply_counterfactual_nudge
# ---------------------------------------------------------------------------


class TestApplyCounterfactualNudge:
    """Tests for belief nudge computation — pure function, no DB."""

    @pytest.fixture()
    def sample_beliefs(self) -> dict[str, dict[str, float]]:
        return {
            "agent_1": {"economy": 0.8, "security": 0.3},
            "agent_2": {"economy": 0.2, "security": 0.9},
        }

    def test_polarize_compresses_toward_center(self, sample_beliefs):
        nudged = _apply_counterfactual_nudge(sample_beliefs, "polarize")
        # economy 0.8 → deviation 0.3 * 0.5 = 0.15 → 0.65
        assert nudged["agent_1"]["economy"] == pytest.approx(0.65, abs=1e-9)
        # economy 0.2 → deviation -0.3 * 0.5 = -0.15 → 0.35
        assert nudged["agent_2"]["economy"] == pytest.approx(0.35, abs=1e-9)

    def test_converge_amplifies_diversity(self, sample_beliefs):
        nudged = _apply_counterfactual_nudge(sample_beliefs, "converge")
        # economy 0.8 → deviation 0.3 * 1.5 = 0.45 → 0.95
        assert nudged["agent_1"]["economy"] == pytest.approx(0.95, abs=1e-9)
        # economy 0.2 → deviation -0.3 * 1.5 = -0.45 → 0.05
        assert nudged["agent_2"]["economy"] == pytest.approx(0.05, abs=1e-9)

    def test_split_reverses_shift(self, sample_beliefs):
        nudged = _apply_counterfactual_nudge(sample_beliefs, "split")
        # economy 0.8 → deviation 0.3, reversed → 0.5 - 0.3 = 0.2
        assert nudged["agent_1"]["economy"] == pytest.approx(0.2, abs=1e-9)
        # economy 0.2 → deviation -0.3, reversed → 0.5 + 0.3 = 0.8
        assert nudged["agent_2"]["economy"] == pytest.approx(0.8, abs=1e-9)

    def test_unknown_direction_mild_compression(self, sample_beliefs):
        nudged = _apply_counterfactual_nudge(sample_beliefs, "unknown_dir")
        # economy 0.8 → deviation 0.3 * 0.7 = 0.21 → 0.71
        assert nudged["agent_1"]["economy"] == pytest.approx(0.71, abs=1e-9)

    def test_clamps_to_zero_one(self):
        beliefs = {"a": {"x": 0.99}}
        nudged = _apply_counterfactual_nudge(beliefs, "converge")
        # 0.99 → deviation 0.49 * 1.5 = 0.735 → 1.235 → clamped to 1.0
        assert nudged["a"]["x"] == 1.0

    def test_does_not_mutate_input(self, sample_beliefs):
        original_val = sample_beliefs["agent_1"]["economy"]
        _apply_counterfactual_nudge(sample_beliefs, "polarize")
        assert sample_beliefs["agent_1"]["economy"] == original_val

    def test_empty_beliefs_returns_empty(self):
        assert _apply_counterfactual_nudge({}, "polarize") == {}


# ---------------------------------------------------------------------------
# _nudge_description
# ---------------------------------------------------------------------------


class TestNudgeDescription:
    def test_polarize_description(self):
        desc = _nudge_description("polarize", 5)
        assert "R5" in desc
        assert "counter-polarization" in desc

    def test_converge_description(self):
        desc = _nudge_description("converge", 10)
        assert "R10" in desc
        assert "counter-convergence" in desc

    def test_split_description(self):
        desc = _nudge_description("split", 3)
        assert "counter-split" in desc

    def test_unknown_direction_fallback(self):
        desc = _nudge_description("mystery", 7)
        assert "R7" in desc
        assert "mild compression" in desc


# ---------------------------------------------------------------------------
# AutoForkResult immutability
# ---------------------------------------------------------------------------


class TestAutoForkResult:
    def test_is_frozen(self):
        result = AutoForkResult(
            parent_session_id="sess1",
            fork_round=5,
            natural_branch_id="nat1",
            nudged_branch_id="nudge1",
            tipping_direction="polarize",
            nudge_description="test",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.fork_round = 10  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Guard constant
# ---------------------------------------------------------------------------


class TestAdaptiveForkBudget:
    def test_short_simulation_gets_min_budget(self):
        """15-round sim → budget = max(2, 15//10) = 2."""
        assert compute_fork_budget(15) == 2

    def test_standard_simulation(self):
        """20-round sim → max(2, 20//10) = 2."""
        assert compute_fork_budget(20) == 2

    def test_deep_simulation(self):
        """30-round sim → max(2, 30//10) = 3."""
        assert compute_fork_budget(30) == 3

    def test_long_simulation_caps_at_max(self):
        """100-round sim → min(5, 100//10) = 5."""
        assert compute_fork_budget(100) == 5

    def test_very_long_caps_at_max(self):
        """200-round sim → min(5, 200//10) = 5."""
        assert compute_fork_budget(200) == 5

    def test_min_is_two(self):
        assert _MIN_AUTO_FORKS == 2

    def test_max_is_five(self):
        assert _MAX_AUTO_FORKS == 5

    def test_jsd_strong_signal_threshold(self):
        """Strong signal = 1.5 × 0.15 = 0.225."""
        expected = _JSD_BASE_THRESHOLD * _JSD_STRONG_SIGNAL_MULTIPLIER
        assert expected == pytest.approx(0.225)
