# backend/tests/test_agent_behavior_validator.py
"""Tests for AgentBehaviorValidator service."""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, patch

import pytest

from backend.app.services.agent_behavior_validator import AgentBehaviorValidator, BehaviorValidationResult


def _mock_db_rows():
    """Simulate rows from simulation_actions with reasoning fields."""
    rows = []
    decisions = [
        "protest",
        "protest",
        "protest",
        "comply",
        "protest",
        "protest",
        "comply",
        "protest",
        "protest",
        "comply",
    ]
    for i, d in enumerate(decisions):
        row = {
            "agent_id": f"agent_{i}",
            "decision_type": d,
            "reasoning": f"Agent {i} chose {d} because of local conditions.",
            "round_number": i % 5,
            "persona": f"Persona {i}",
        }
        rows.append(row)
    return rows


def test_action_diversity_uniform():
    """Equal distribution over N outcomes → entropy = log2(N)."""
    validator = AgentBehaviorValidator()
    decisions = ["a", "b", "c", "d"] * 25  # 100 decisions, 4 types equally
    entropy = validator.compute_action_diversity(decisions)
    assert abs(entropy - math.log2(4)) < 0.05


def test_action_diversity_mode_collapse():
    """Single decision type → entropy ≈ 0."""
    validator = AgentBehaviorValidator()
    decisions = ["protest"] * 100
    entropy = validator.compute_action_diversity(decisions)
    assert entropy < 0.05


def test_mode_collapse_flag():
    """Entropy below threshold should raise mode_collapse_warning."""
    validator = AgentBehaviorValidator()
    decisions = ["protest"] * 100
    result = validator._check_mode_collapse(decisions)
    assert result is True


def test_no_mode_collapse_flag():
    """Diverse decisions should not flag mode collapse."""
    validator = AgentBehaviorValidator()
    decisions = ["a", "b", "c"] * 30
    result = validator._check_mode_collapse(decisions)
    assert result is False


@pytest.mark.asyncio
async def test_validate_returns_result():
    """validate() should return a BehaviorValidationResult."""
    validator = AgentBehaviorValidator()
    rows = _mock_db_rows()

    def fake_get_db():
        db = AsyncMock()
        db.__aenter__ = AsyncMock(return_value=db)
        db.__aexit__ = AsyncMock(return_value=False)
        cursor = AsyncMock()
        cursor.fetchall = AsyncMock(return_value=rows)
        db.execute = AsyncMock(return_value=cursor)
        return db

    with patch("backend.app.services.agent_behavior_validator.get_db", fake_get_db):
        # skip_llm=True to avoid LLM calls in unit tests
        result = await validator.validate("session_123", sample_size=5, skip_llm=True)

    assert isinstance(result, BehaviorValidationResult)
    assert result.action_diversity_entropy >= 0.0
    assert result.mode_collapse_warning in (True, False)
    assert result.avg_consistency_score == 0.0  # skip_llm=True → no scores
