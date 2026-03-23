# backend/tests/test_surrogate_model.py
"""Tests for SurrogateModel — Phase A belief→decision surrogate."""

from __future__ import annotations

import pytest

from backend.app.services.multi_run_orchestrator import CanonicalResult, MultiRunOrchestrator
from backend.app.services.surrogate_model import SurrogateModel, SurrogateModelResult


def _make_training_rows():
    """Simulate Phase A belief + decision rows."""
    rows = []
    for i in range(60):
        rows.append(
            {
                "agent_id": f"a_{i}",
                "round_number": i % 10,
                "decision_type": "escalate" if i % 3 != 0 else "ceasefire",
                "belief_snapshot": '{"escalation_index": 0.7, "diplomatic_pressure": 0.3}'
                if i % 3 != 0
                else '{"escalation_index": 0.3, "diplomatic_pressure": 0.7}',
            }
        )
    return rows


def test_surrogate_train_returns_result():
    """train_from_rows() should return a fitted SurrogateModelResult."""
    surrogate = SurrogateModel()
    rows = _make_training_rows()
    result = surrogate.train_from_rows(
        rows,
        outcome_col="decision_type",
        metrics=["escalation_index", "diplomatic_pressure"],
    )
    assert isinstance(result, SurrogateModelResult)
    assert result.is_fitted
    assert result.n_classes >= 2
    assert result.train_accuracy > 0.0


def test_surrogate_predict_returns_known_outcome():
    """predict() should return one of the training outcome labels."""
    surrogate = SurrogateModel()
    rows = _make_training_rows()
    result = surrogate.train_from_rows(
        rows,
        outcome_col="decision_type",
        metrics=["escalation_index", "diplomatic_pressure"],
    )
    belief_vec = {"escalation_index": 0.8, "diplomatic_pressure": 0.2}
    pred = result.predict(belief_vec)
    assert pred in ("escalate", "ceasefire")


def test_surrogate_predict_distribution():
    """predict_distribution() should sum to ~1.0."""
    surrogate = SurrogateModel()
    rows = _make_training_rows()
    result = surrogate.train_from_rows(
        rows,
        outcome_col="decision_type",
        metrics=["escalation_index", "diplomatic_pressure"],
    )
    dist = result.predict_distribution({"escalation_index": 0.5, "diplomatic_pressure": 0.5})
    total = sum(dist.values())
    assert abs(total - 1.0) < 0.01


def test_empty_rows_returns_unfitted():
    """Empty training data should return an unfitted result."""
    surrogate = SurrogateModel()
    result = surrogate.train_from_rows([], outcome_col="decision_type", metrics=["x"])
    assert not result.is_fitted


@pytest.mark.asyncio
async def test_multi_run_uses_surrogate():
    """MultiRunOrchestrator with surrogate should still produce valid distribution."""
    surrogate = SurrogateModel()
    rows = _make_training_rows()
    model = surrogate.train_from_rows(
        rows,
        outcome_col="decision_type",
        metrics=["escalation_index", "diplomatic_pressure"],
    )
    assert model.is_fitted

    orchestrator = MultiRunOrchestrator()
    canonical = CanonicalResult(
        simulation_id="test",
        scenario_metrics=("escalation_index", "diplomatic_pressure"),
        agent_belief_distributions={
            "a": {"escalation_index": (0.7, 0.1), "diplomatic_pressure": (0.3, 0.1)},
        },
        scenario_outcomes=["escalate", "ceasefire"],
        round_count=5,
    )
    result = await orchestrator.run(canonical, trial_count=20, surrogate_model=model)
    assert abs(sum(result.outcome_distribution.values()) - 1.0) < 0.01
