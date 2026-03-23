# backend/tests/test_multi_run_orchestrator.py
"""Tests for MultiRunOrchestrator Phase B stochastic ensemble."""

from __future__ import annotations

import pytest

from backend.app.services.multi_run_orchestrator import (
    CanonicalResult,
    MultiRunOrchestrator,
    MultiRunResult,
    ReplicateResult,
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


def test_hard_cap_at_50000():
    from backend.app.services.multi_run_orchestrator import _clamp_trial_count

    assert _clamp_trial_count(999999) == 50000
    assert _clamp_trial_count(500) == 500


@pytest.mark.asyncio
async def test_importance_sampling_rare_event():
    """With rare_event_threshold, distribution should still sum to 1."""
    orchestrator = MultiRunOrchestrator()
    canonical = _make_canonical({})
    result = await orchestrator.run(
        canonical,
        trial_count=100,
        rare_event_threshold=0.1,
    )
    assert abs(sum(result.outcome_distribution.values()) - 1.0) < 0.02


@pytest.mark.asyncio
async def test_importance_sampling_returns_importance_weights():
    """run() with rare_event_threshold should populate importance_weights_used field."""
    orchestrator = MultiRunOrchestrator()
    canonical = _make_canonical({})
    result = await orchestrator.run(
        canonical,
        trial_count=50,
        rare_event_threshold=0.05,
    )
    assert hasattr(result, "importance_weights_used")
    assert result.importance_weights_used is True


@pytest.mark.asyncio
async def test_no_importance_sampling_flag_without_threshold():
    """Without rare_event_threshold, importance_weights_used should be False."""
    orchestrator = MultiRunOrchestrator()
    canonical = _make_canonical({})
    result = await orchestrator.run(canonical, trial_count=30)
    assert result.importance_weights_used is False


@pytest.mark.asyncio
async def test_run_replicates_returns_result():
    """run_replicates() should return a ReplicateResult."""
    orchestrator = MultiRunOrchestrator()
    canonical = _make_canonical({})
    result = await orchestrator.run_replicates(
        [canonical, canonical, canonical],
        trial_count_per_replicate=30,
    )
    assert isinstance(result, ReplicateResult)
    assert result.n_replicates == 3


@pytest.mark.asyncio
async def test_run_replicates_outcome_means_sum_to_one():
    """Outcome mean probabilities should sum to ~1.0."""
    orchestrator = MultiRunOrchestrator()
    canonical = _make_canonical({})
    result = await orchestrator.run_replicates(
        [canonical, canonical],
        trial_count_per_replicate=40,
    )
    assert abs(sum(result.outcome_means.values()) - 1.0) < 0.02


@pytest.mark.asyncio
async def test_run_replicates_variance_non_negative():
    """Inter-run variance should be ≥ 0 for all outcomes."""
    orchestrator = MultiRunOrchestrator()
    canonical = _make_canonical({})
    result = await orchestrator.run_replicates(
        [canonical, canonical, canonical],
        trial_count_per_replicate=30,
    )
    for v in result.outcome_variances.values():
        assert v >= 0.0
