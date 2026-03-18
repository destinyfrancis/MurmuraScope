"""Structural integration tests for report quality upgrade features.

These tests verify the plumbing works end-to-end without live LLM calls.
"""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch


def test_report_generate_request_scenario_question_optional():
    """Existing clients without scenario_question still work."""
    from backend.app.models.request import ReportGenerateRequest
    req = ReportGenerateRequest(session_id="s1", report_type="full")
    assert req.scenario_question is None


def test_report_generate_request_accepts_scenario_question():
    """New clients can pass scenario_question."""
    from backend.app.models.request import ReportGenerateRequest
    req = ReportGenerateRequest(
        session_id="s1",
        report_type="full",
        scenario_question="如果X發生，輿情會怎樣？",
    )
    assert req.scenario_question == "如果X發生，輿情會怎樣？"


def test_section_generator_enforces_min_3_tool_calls():
    """Section generator rejects Final Answer if fewer than 3 tool calls made."""
    tool_calls_made = []

    async def mock_tool(name, params):
        tool_calls_made.append(name)
        return f"Result from {name}"

    call_count = 0

    async def mock_llm(messages):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return f'<tool_call>{{"name": "insight_forge", "parameters": {{"query": "test"}}}}</tool_call>'
        if call_count == 3:
            # Try to end with only 2 tool calls — should be rejected
            return "Final Answer: premature end"
        if call_count == 4:
            # Make 3rd tool call after rejection
            return f'<tool_call>{{"name": "get_sentiment_timeline", "parameters": {{}}}}</tool_call>'
        # Final answer with 3 tool calls
        return "Final Answer: This is the real final content."

    from backend.app.services.report_section_generator import generate_section
    result = asyncio.run(generate_section(
        system_prompt="test",
        section_outline={"title": "Test", "thesis": "Test", "suggested_tools": []},
        previous_sections=[],
        tool_handler=mock_tool,
        llm_caller=mock_llm,
        unused_tools=["insight_forge"],
    ))
    assert "real final content" in result
    assert len(tool_calls_made) >= 3


def test_platform_breakdown_handles_no_actions():
    """get_platform_breakdown returns empty dict if no actions."""
    async def run():
        with patch("backend.app.services.report_agent_xai.get_db") as mock_db_ctx:
            mock_conn = AsyncMock()
            mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_conn.__aexit__ = AsyncMock(return_value=None)
            mock_cursor = AsyncMock()
            mock_cursor.fetchall = AsyncMock(return_value=[])
            mock_conn.execute = AsyncMock(return_value=mock_cursor)
            mock_db_ctx.return_value = mock_conn
            from backend.app.services.report_agent_xai import get_platform_breakdown
            result = await get_platform_breakdown("sess_no_actions")
        return result

    result = asyncio.run(run())
    assert result == {}


def test_get_agent_story_arcs_returns_empty_for_hk_mode():
    """get_agent_story_arcs returns [] for hk_demographic mode — guards kg_driven only feature."""
    from backend.app.services.report_agent_xai import get_agent_story_arcs
    result = asyncio.run(get_agent_story_arcs("any_session", sim_mode="hk_demographic"))
    assert result == []


def test_insight_forge_result_is_frozen():
    """InsightForgeResult can be created and is immutable."""
    import dataclasses
    from backend.app.models.report_models import InsightForgeResult
    r = InsightForgeResult(
        query="test", sub_queries=("a",),
        facts=("fact",), quotable_excerpts=("q",), source_agents=("a1",)
    )
    assert r.query == "test"
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.query = "changed"  # type: ignore


def test_topic_evolution_result_is_frozen():
    """TopicEvolutionResult can be created and is immutable."""
    import dataclasses
    from backend.app.models.report_models import TopicEvolutionResult, TopicWindow
    w = TopicWindow(rounds="1-5", dominant_topics=("A",), emerging=(), fading=())
    r = TopicEvolutionResult(windows=(w,), migration_path="A → B", inflection_round=None)
    assert r.migration_path == "A → B"
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.migration_path = "changed"  # type: ignore


def test_report_orchestrator_parse_outline_all_paths():
    """_parse_outline handles valid JSON, malformed JSON, and missing chapters key."""
    from backend.app.services.report_orchestrator import ReportOrchestrator
    orch = ReportOrchestrator.__new__(ReportOrchestrator)

    # Valid JSON with chapters
    valid = '{"chapters": [{"title": "T", "thesis": "Th", "suggested_tools": []}]}'
    result = orch._parse_outline(valid)
    assert len(result) == 1 and result[0]["title"] == "T"

    # Missing chapters key
    result = orch._parse_outline('{"other": "value"}')
    assert result == []

    # Malformed JSON
    result = orch._parse_outline("not json")
    assert result == []

    # JSON with trailing prose
    result = orch._parse_outline('{"chapters": [{"title": "T2", "thesis": "T", "suggested_tools": []}]} extra text')
    assert len(result) == 1


def test_deliberation_result_backward_compat():
    """DeliberationResult without new fields still works."""
    from backend.app.services.cognitive_agent_engine import DeliberationResult
    r = DeliberationResult(
        agent_id="a1", decision="stay",
        reasoning="test", belief_updates={}, stance_statement="neutral",
    )
    assert r.topic_tags == ()
    assert r.emotional_reaction == ""


def test_universal_agent_profile_backward_compat():
    """UniversalAgentProfile without new voice fields still works."""
    from backend.app.models.universal_agent_profile import UniversalAgentProfile
    p = UniversalAgentProfile(
        id="t1", name="Test", role="Tester", entity_type="Person",
        persona="A test.", goals=(), capabilities=(), stance_axes=(), relationships=(),
        kg_node_id="node_t1",
    )
    assert p.communication_style == ""
    assert p.vocabulary_hints == ()
    assert p.platform_persona == ""
