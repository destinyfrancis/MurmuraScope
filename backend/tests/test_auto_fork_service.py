"""Unit tests for AutoForkService."""
from __future__ import annotations

import dataclasses
import pytest

from backend.app.services.auto_fork_service import (
    AutoForkResult,
    _apply_counterfactual_nudge,
    _nudge_description,
    _MIN_AUTO_FORKS,
    _MAX_AUTO_FORKS,
    _JSD_STRONG_SIGNAL_MULTIPLIER,
    _JSD_BASE_THRESHOLD,
    compute_fork_budget,
)


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
