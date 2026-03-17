# backend/tests/test_cognitive_agent_engine.py
"""Tests for CognitiveAgentEngine — Tier 1 full-LLM deliberation."""
from __future__ import annotations
from unittest.mock import AsyncMock, patch
import pytest
from backend.app.services.cognitive_agent_engine import CognitiveAgentEngine, DeliberationResult


def _make_agent_context() -> dict:
    return {
        "agent_id": "iran_supreme_leader",
        "name": "Iran Supreme Leader",
        "role": "Supreme Leader of Iran",
        "current_beliefs": {"escalation_index": 0.7, "diplomatic_pressure": 0.3},
        "recent_events": ["Iran announces suspension of nuclear talks."],
        "faction": "hardliner_faction",
    }


@pytest.mark.asyncio
async def test_deliberate_returns_result():
    engine = CognitiveAgentEngine()
    mock_response = {
        "decision": "escalate_military",
        "reasoning": "The reasoning is clear: given the suspension of talks, escalation is necessary.",
        "belief_updates": {"escalation_index": 0.05, "diplomatic_pressure": -0.10},
        "stance_statement": "We will not back down from our nuclear rights.",
    }
    with patch.object(engine._llm, "chat_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = mock_response
        result = await engine.deliberate(
            agent_context=_make_agent_context(),
            scenario_description="US-Iran conflict 2026",
            active_metrics=("escalation_index", "diplomatic_pressure"),
        )
    assert isinstance(result, DeliberationResult)
    assert result.agent_id == "iran_supreme_leader"
    assert result.decision == "escalate_military"
    assert "reasoning" in result.reasoning


@pytest.mark.asyncio
async def test_deliberate_returns_default_on_llm_failure():
    """LLM failure must return a safe default DeliberationResult, never raise."""
    engine = CognitiveAgentEngine()
    with patch.object(engine._llm, "chat_json", side_effect=RuntimeError("LLM down")):
        result = await engine.deliberate(
            agent_context=_make_agent_context(),
            scenario_description="test",
            active_metrics=("escalation_index",),
        )
    assert isinstance(result, DeliberationResult)
    assert result.decision == "observe"  # safe default


@pytest.mark.asyncio
async def test_deliberate_filters_unknown_metrics():
    """belief_updates keys not in active_metrics are silently dropped."""
    engine = CognitiveAgentEngine()
    mock_response = {
        "decision": "negotiate",
        "reasoning": "Diplomacy is preferable.",
        "belief_updates": {"escalation_index": -0.05, "unknown_metric": 0.99},
        "stance_statement": "We seek dialogue.",
    }
    with patch.object(engine._llm, "chat_json", new_callable=AsyncMock) as m:
        m.return_value = mock_response
        result = await engine.deliberate(
            agent_context=_make_agent_context(),
            scenario_description="test",
            active_metrics=("escalation_index",),
        )
    assert "unknown_metric" not in result.belief_updates
