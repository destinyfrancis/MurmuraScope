"""Tests for ReportAgent — ReACT tool orchestration, report parsing, error handling."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.services.report_agent import (
    ReportAgent,
    _build_initial_prompt,
    _extract_final_report,
    _extract_tool_call,
    _parse_report,
    TOOLS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_ipc():
    """Return a mock SimulationIPC."""
    ipc = MagicMock()
    ipc.interview_agent = AsyncMock(return_value="我覺得樓價太貴")
    return ipc


@pytest.fixture()
def agent(mock_ipc):
    return ReportAgent(ipc=mock_ipc)


# ---------------------------------------------------------------------------
# _extract_final_report
# ---------------------------------------------------------------------------


class TestExtractFinalReport:
    def test_extracts_after_marker(self):
        response = "Some thinking...\n## FINAL_REPORT\n# My Report\nContent here"
        result = _extract_final_report(response)
        assert result.startswith("# My Report")
        assert "Content here" in result

    def test_returns_full_response_when_no_marker(self):
        response = "No marker here, just text"
        result = _extract_final_report(response)
        assert result == response

    def test_strips_whitespace_after_marker(self):
        response = "## FINAL_REPORT\n   \n# Report Title"
        result = _extract_final_report(response)
        assert result.startswith("# Report Title")


# ---------------------------------------------------------------------------
# _extract_tool_call
# ---------------------------------------------------------------------------


class TestExtractToolCall:
    def test_extracts_valid_tool_call(self):
        response = 'I need data. {"tool": "get_macro_context", "params": {}}'
        result = _extract_tool_call(response)
        assert result is not None
        assert result["tool"] == "get_macro_context"

    def test_extracts_tool_call_with_params(self):
        response = '{"tool": "query_graph", "params": {"query": "property"}}'
        result = _extract_tool_call(response)
        assert result is not None
        assert result["tool"] == "query_graph"
        assert result["params"]["query"] == "property"

    def test_returns_none_for_no_json(self):
        response = "Just plain text with no JSON"
        result = _extract_tool_call(response)
        assert result is None

    def test_returns_none_for_json_without_tool_key(self):
        response = '{"name": "something", "value": 42}'
        result = _extract_tool_call(response)
        assert result is None

    def test_returns_none_for_malformed_json(self):
        response = '{"tool": "broken'
        result = _extract_tool_call(response)
        assert result is None


# ---------------------------------------------------------------------------
# _parse_report
# ---------------------------------------------------------------------------


class TestParseReport:
    def test_extracts_title_from_h1(self):
        content = "# Custom Title\n\nSome content"
        result = _parse_report("sess-1", content)
        assert result["title"] == "Custom Title"

    def test_default_title_when_no_h1(self):
        content = "No heading here\nJust content"
        result = _parse_report("sess-1", content)
        assert result["title"] == "Simulation Analysis Report"

    def test_extracts_key_findings(self):
        content = (
            "# Report\n\n"
            "1. Housing prices increased by 5%\n"
            "2. Emigration sentiment rose sharply\n"
            "3. Consumer confidence dropped\n"
        )
        result = _parse_report("sess-1", content)
        assert len(result["key_findings"]) == 3
        assert "Housing prices" in result["key_findings"][0]

    def test_generates_summary(self):
        content = "First line of content.\nSecond line.\n\nNew paragraph."
        result = _parse_report("sess-1", content)
        assert result["summary"]
        assert len(result["summary"]) <= 500

    def test_report_has_required_keys(self):
        content = "# Title\n\nBody"
        result = _parse_report("sess-1", content)
        required = {"report_id", "title", "content_markdown", "summary", "key_findings", "charts_data", "agent_log"}
        assert required.issubset(result.keys())


# ---------------------------------------------------------------------------
# _build_initial_prompt
# ---------------------------------------------------------------------------


class TestBuildInitialPrompt:
    def test_includes_session_id(self):
        prompt = _build_initial_prompt("abc-123", "full", [])
        assert "abc-123" in prompt

    def test_includes_report_type(self):
        prompt = _build_initial_prompt("sess", "sentiment", [])
        assert "sentiment" in prompt

    def test_includes_focus_areas(self):
        prompt = _build_initial_prompt("sess", "full", ["housing", "emigration"])
        assert "housing" in prompt
        assert "emigration" in prompt


# ---------------------------------------------------------------------------
# TOOLS registry
# ---------------------------------------------------------------------------


class TestToolsRegistry:
    def test_has_expected_tools(self):
        expected = {
            "query_graph", "get_sentiment_distribution",
            "get_demographic_breakdown", "interview_agents",
            "get_macro_context", "calculate_cashflow",
            "get_decision_summary", "get_sentiment_timeline",
            "get_ensemble_forecast", "get_macro_history",
        }
        assert expected.issubset(set(TOOLS.keys()))


# ---------------------------------------------------------------------------
# ReportAgent._execute_tool
# ---------------------------------------------------------------------------


class TestExecuteTool:
    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self, agent):
        result = await agent._execute_tool("nonexistent_tool", {}, "sess-1")
        assert "Error" in result
        assert "Unknown tool" in result

    @pytest.mark.asyncio
    async def test_calculate_cashflow_returns_projection(self, agent):
        result = await agent._execute_tool(
            "calculate_cashflow",
            {"property_price": 5_000_000, "monthly_income": 40_000},
            "sess-1",
        )
        parsed = json.loads(result)
        assert "monthly_payment" in parsed
        assert "debt_to_income_ratio" in parsed
        assert isinstance(parsed["affordable"], bool)

    @pytest.mark.asyncio
    async def test_calculate_cashflow_zero_rate(self, agent):
        result = await agent._execute_tool(
            "calculate_cashflow",
            {"property_price": 1_200_000, "monthly_income": 30_000, "mortgage_rate": 0},
            "sess-1",
        )
        parsed = json.loads(result)
        # With 0% rate, total interest should be 0
        assert parsed["total_interest"] == 0


# ---------------------------------------------------------------------------
# ReportAgent.generate_report (with mocked LLM)
# ---------------------------------------------------------------------------


class TestGenerateReport:
    @pytest.mark.asyncio
    async def test_immediate_final_report(self, agent):
        """LLM returns FINAL_REPORT on first call."""
        mock_response = MagicMock()
        mock_response.content = (
            "## FINAL_REPORT\n"
            "# Test Report\n\n"
            "1. Finding one\n"
            "2. Finding two\n"
        )

        with patch("backend.app.services.report_agent._call_llm", new_callable=AsyncMock, return_value=mock_response.content):
            with patch("backend.app.services.report_agent._persist_report", new_callable=AsyncMock):
                report = await agent.generate_report("sess-1", "full")

        assert report["title"] == "Test Report"
        assert len(report["key_findings"]) >= 2
        assert report["agent_log"]

    @pytest.mark.asyncio
    async def test_tool_call_then_report(self, agent):
        """LLM calls a tool on first iteration, then produces report."""
        call_count = 0

        async def mock_llm(messages, system_prompt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return '{"tool": "calculate_cashflow", "params": {"property_price": 5000000}}'
            return (
                "## FINAL_REPORT\n"
                "# Analysis Complete\n\n"
                "1. Cashflow is healthy\n"
            )

        with patch("backend.app.services.report_agent._call_llm", side_effect=mock_llm):
            with patch("backend.app.services.report_agent._persist_report", new_callable=AsyncMock):
                report = await agent.generate_report("sess-1", "full")

        assert report["title"] == "Analysis Complete"
        # Should have logged Action and Observation steps
        step_types = [s["step_type"] for s in report["agent_log"]]
        assert "Action" in step_types
        assert "Observation" in step_types

    @pytest.mark.asyncio
    async def test_max_iterations_forces_report(self, agent):
        """When LLM never produces FINAL_REPORT, max iterations forces it."""
        call_count = 0

        async def mock_llm(messages, system_prompt):
            nonlocal call_count
            call_count += 1
            # Only produce final report when forced (last call after max iterations)
            if call_count > 10:
                return "## FINAL_REPORT\n# Forced Report\n\nForced content."
            return "Still thinking..."

        with patch("backend.app.services.report_agent._call_llm", side_effect=mock_llm):
            with patch("backend.app.services.report_agent._persist_report", new_callable=AsyncMock):
                report = await agent.generate_report("sess-1", "full")

        assert report["content_markdown"]


# ---------------------------------------------------------------------------
# ReportAgent.chat
# ---------------------------------------------------------------------------


class TestReportChat:
    @pytest.mark.asyncio
    async def test_chat_raises_on_empty_message(self, agent):
        with pytest.raises(ValueError, match="empty"):
            await agent.chat("sess-1", "")

    @pytest.mark.asyncio
    async def test_chat_raises_on_whitespace_message(self, agent):
        with pytest.raises(ValueError, match="empty"):
            await agent.chat("sess-1", "   ")

    @pytest.mark.asyncio
    async def test_chat_returns_response(self, agent):
        with patch("backend.app.services.report_agent._call_llm", new_callable=AsyncMock, return_value="回覆內容"):
            with patch("backend.app.services.report_agent._load_report_context", new_callable=AsyncMock, return_value=None):
                result = await agent.chat("sess-1", "What about housing?")

        assert result == "回覆內容"
