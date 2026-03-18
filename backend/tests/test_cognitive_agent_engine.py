# backend/tests/test_cognitive_agent_engine.py
"""Tests for CognitiveAgentEngine — Tier 1 full-LLM deliberation."""
from __future__ import annotations
import json
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


# ---------------------------------------------------------------------------
# NEW FIELD TESTS for DeliberationResult (Task 2)
# ---------------------------------------------------------------------------

def test_deliberation_result_new_fields_have_defaults():
    """New fields topic_tags and emotional_reaction default to empty values."""
    r = DeliberationResult(
        agent_id="a1",
        decision="emigrate",
        reasoning="...",
        belief_updates={},
        stance_statement="...",
    )
    assert r.topic_tags == ()
    assert r.emotional_reaction == ""


def test_deliberation_result_is_frozen_with_new_fields():
    """New fields are frozen — mutations raise FrozenInstanceError."""
    import dataclasses
    r = DeliberationResult(
        agent_id="a1",
        decision="stay",
        reasoning="...",
        belief_updates={},
        stance_statement="...",
        topic_tags=("程序正義", "信息透明"),
        emotional_reaction="憤怒，感到不公平",
    )
    assert r.topic_tags == ("程序正義", "信息透明")
    assert r.emotional_reaction == "憤怒，感到不公平"
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.emotional_reaction = "changed"  # type: ignore


def test_deliberation_result_topic_tags_is_tuple():
    """topic_tags must be a tuple (not list) for immutability."""
    r = DeliberationResult(
        agent_id="a1",
        decision="negotiate",
        reasoning="...",
        belief_updates={},
        stance_statement="...",
        topic_tags=("主權", "談判"),
    )
    assert isinstance(r.topic_tags, tuple)
    assert len(r.topic_tags) == 2


def test_deliberation_result_new_fields_backward_compat():
    """Existing callers that omit new fields still get valid objects."""
    r = DeliberationResult(
        agent_id="a2",
        decision="observe",
        reasoning="Watching events unfold.",
        belief_updates={"metric_a": 0.1},
        stance_statement="We wait and see.",
    )
    # new fields must not raise — just return defaults
    assert r.topic_tags == ()
    assert r.emotional_reaction == ""


# ---------------------------------------------------------------------------
# Task 4: LLM response extraction of topic_tags + emotional_reaction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deliberate_extracts_topic_tags_and_emotional_reaction():
    """deliberate() populates topic_tags and emotional_reaction from LLM JSON."""
    engine = CognitiveAgentEngine()
    mock_response = {
        "decision": "emigrate",
        "reasoning": "unstable",
        "belief_updates": {"safety": -0.2},
        "stance_statement": "Will leave",
        "topic_tags": ["移民", "就業"],
        "emotional_reaction": "焦慮",
    }
    with patch.object(engine._llm, "chat_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = mock_response
        result = await engine.deliberate(
            agent_context=_make_agent_context(),
            scenario_description="HK stability scenario",
            active_metrics=("safety", "stability"),
        )
    assert result.topic_tags == ("移民", "就業")
    assert result.emotional_reaction == "焦慮"


@pytest.mark.asyncio
async def test_deliberate_topic_tags_missing_returns_empty_tuple():
    """If LLM omits topic_tags, result defaults to empty tuple."""
    engine = CognitiveAgentEngine()
    mock_response = {
        "decision": "stay",
        "reasoning": "stable enough",
        "belief_updates": {},
        "stance_statement": "Stay put",
        # topic_tags intentionally omitted
    }
    with patch.object(engine._llm, "chat_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = mock_response
        result = await engine.deliberate(
            agent_context=_make_agent_context(),
            scenario_description="HK stability scenario",
            active_metrics=("safety",),
        )
    assert result.topic_tags == ()
    assert result.emotional_reaction == ""


@pytest.mark.asyncio
async def test_deliberate_topic_tags_malformed_skips_non_strings():
    """topic_tags with non-string items are silently filtered out."""
    engine = CognitiveAgentEngine()
    mock_response = {
        "decision": "negotiate",
        "reasoning": "diplomacy first",
        "belief_updates": {},
        "stance_statement": "Negotiate",
        "topic_tags": ["有效標籤", 42, None, "另一個標籤"],
        "emotional_reaction": "冷靜",
    }
    with patch.object(engine._llm, "chat_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = mock_response
        result = await engine.deliberate(
            agent_context=_make_agent_context(),
            scenario_description="test",
            active_metrics=("escalation_index",),
        )
    assert result.topic_tags == ("有效標籤", "另一個標籤")
    assert result.emotional_reaction == "冷靜"


@pytest.mark.asyncio
async def test_deliberate_topic_tags_capped_at_five():
    """topic_tags are capped at 5 entries."""
    engine = CognitiveAgentEngine()
    mock_response = {
        "decision": "observe",
        "reasoning": "many topics",
        "belief_updates": {},
        "stance_statement": "Watch",
        "topic_tags": ["t1", "t2", "t3", "t4", "t5", "t6", "t7"],
        "emotional_reaction": "複雜",
    }
    with patch.object(engine._llm, "chat_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = mock_response
        result = await engine.deliberate(
            agent_context=_make_agent_context(),
            scenario_description="test",
            active_metrics=("escalation_index",),
        )
    assert len(result.topic_tags) == 5


@pytest.mark.asyncio
async def test_deliberate_emotional_reaction_truncated_at_50():
    """emotional_reaction is truncated to 50 characters."""
    engine = CognitiveAgentEngine()
    long_reaction = "非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常複雜的情緒反應"
    mock_response = {
        "decision": "stay",
        "reasoning": "complex",
        "belief_updates": {},
        "stance_statement": "Remain",
        "topic_tags": [],
        "emotional_reaction": long_reaction,
    }
    with patch.object(engine._llm, "chat_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = mock_response
        result = await engine.deliberate(
            agent_context=_make_agent_context(),
            scenario_description="test",
            active_metrics=("escalation_index",),
        )
    assert len(result.emotional_reaction) <= 50


def test_deliberation_prompt_includes_topic_tags_instruction():
    """_DELIBERATION_USER prompt requests topic_tags and emotional_reaction fields."""
    from backend.app.services.cognitive_agent_engine import _DELIBERATION_USER
    assert "topic_tags" in _DELIBERATION_USER
    assert "emotional_reaction" in _DELIBERATION_USER
