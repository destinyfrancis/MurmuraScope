# backend/tests/test_multi_run_orchestrator.py
"""Tests for MultiRunOrchestrator Phase B stochastic ensemble."""
from __future__ import annotations
import pytest
from backend.app.services.multi_run_orchestrator import (
    MultiRunOrchestrator, CanonicalResult, MultiRunResult
)


def _make_canonical(outcomes: dict[str, int]) -> CanonicalResult:
    """Build a minimal CanonicalResult for testing."""
    return CanonicalResult(
        simulation_id="sim_001",
        scenario_metrics=("escalation_index", "diplomatic_pressure"),
        agent_belief_distributions={
            "agent_0": {"escalation_index": (0.7, 0.1), "diplomatic_pressure": (0.3, 0.1)},
            "agent_1": {"escalation_index": (0.3, 0.1), "diplomatic_pressure": (0.7, 0.1)},
        },
        scenario_outcomes=["escalate", "ceasefire", "stalemate"],
        round_count=10,
    )


@pytest.mark.asyncio
async def test_run_produces_outcome_distribution():
    orchestrator = MultiRunOrchestrator()
    canonical = _make_canonical({})
    result = await orchestrator.run(canonical, trial_count=50, concurrency=10)
    assert isinstance(result, MultiRunResult)
    assert abs(sum(result.outcome_distribution.values()) - 1.0) < 0.01


@pytest.mark.asyncio
async def test_run_produces_confidence_intervals():
    orchestrator = MultiRunOrchestrator()
    canonical = _make_canonical({})
    result = await orchestrator.run(canonical, trial_count=100, concurrency=10)
    # Only check outcomes that exist in both dicts (robust to future _simulate_trial changes)
    for outcome in result.confidence_intervals:
        if outcome in result.outcome_distribution:
            lo, hi = result.confidence_intervals[outcome]
            assert lo <= result.outcome_distribution[outcome] <= hi


@pytest.mark.asyncio
async def test_run_trial_count_matches():
    orchestrator = MultiRunOrchestrator()
    canonical = _make_canonical({})
    result = await orchestrator.run(canonical, trial_count=30, concurrency=5)
    assert result.trial_count == 30


def test_hard_cap_at_10000():
    from backend.app.services.multi_run_orchestrator import _clamp_trial_count
    assert _clamp_trial_count(999999) == 10000
    assert _clamp_trial_count(500) == 500
