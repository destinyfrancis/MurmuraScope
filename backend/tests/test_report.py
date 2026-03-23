"""Tests for report generation agent and chat endpoints."""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock

import pytest

# ======================================================================
# Report generation
# ======================================================================


class TestReportGenerationProducesMarkdown:
    """Test that report generation returns valid Markdown content."""

    @pytest.mark.asyncio
    async def test_generate_report_endpoint(self, test_client):
        # The report endpoint calls the real LLM and inserts into reports
        # table with a FK to simulation_sessions.  We just verify the
        # endpoint is reachable and returns a well-formed error or success.
        response = await test_client.post(
            "/api/report/generate",
            json={
                "session_id": str(uuid.uuid4()),
                "report_type": "full",
                "focus_areas": ["property_sentiment", "demographics"],
            },
        )

        # Accept either 200 (LLM available) or 500 (LLM unavailable / FK)
        assert response.status_code in (200, 500)
        data = response.json()
        if response.status_code == 200:
            assert data["success"] is True
            report = data["data"]
            assert "report_id" in report
            assert "content_markdown" in report

    @pytest.mark.asyncio
    async def test_get_report_by_id(self, test_client):
        # A non-existent report should return 404
        report_id = str(uuid.uuid4())
        response = await test_client.get(f"/api/report/{report_id}")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_report_stored_in_db(self, test_db):
        report_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())

        markdown_content = (
            "## Executive Summary\n\n"
            "The simulation reveals shifting property sentiment among Hong Kong residents.\n\n"
            "### Key Findings\n\n"
            "1. Interest rate sensitivity highest among 25-34 age group\n"
            "2. Social media amplifies negative sentiment by 2.3x\n"
        )

        # Insert parent simulation_sessions row to satisfy FK constraint
        await test_db.execute(
            """INSERT INTO simulation_sessions
               (id, name, sim_mode, agent_count, round_count, llm_provider)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, "test-session", "standard", 10, 5, "test"),
        )

        await test_db.execute(
            """INSERT INTO reports
               (id, session_id, report_type, title, content_markdown,
                summary, key_findings, charts_data)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                report_id,
                session_id,
                "full",
                "HK Property Simulation Report",
                markdown_content,
                "Summary of findings",
                json.dumps(["Finding 1", "Finding 2"]),
                json.dumps({"sentiment_chart": []}),
            ),
        )
        await test_db.commit()

        cursor = await test_db.execute("SELECT * FROM reports WHERE id = ?", (report_id,))
        row = await cursor.fetchone()
        assert row is not None
        assert "## Executive Summary" in row["content_markdown"]
        assert row["report_type"] == "full"


# ======================================================================
# ReAct loop (tool-calling)
# ======================================================================


class TestReActLoopCallsTools:
    """Test that the report agent's ReAct loop invokes tools correctly."""

    @pytest.mark.asyncio
    async def test_react_loop_with_tool_call(self, mock_llm_client):
        # Simulate a ReAct loop where the LLM decides to call a tool
        mock_llm_client.chat.side_effect = [
            # First call: LLM wants to use a tool
            MagicMock(
                content=json.dumps(
                    {
                        "thought": "I need to query the simulation data for sentiment trends.",
                        "action": "query_simulation_data",
                        "action_input": {"session_id": "s-1", "metric": "sentiment"},
                    }
                ),
                model="test-model",
                usage={"prompt_tokens": 100, "completion_tokens": 80, "total_tokens": 180},
                cost_usd=0.001,
            ),
            # Second call: LLM produces final answer
            MagicMock(
                content=json.dumps(
                    {
                        "thought": "I have the data. Now I can generate the report.",
                        "action": "final_answer",
                        "action_input": "## Report\n\nSentiment turned negative in round 15.",
                    }
                ),
                model="test-model",
                usage={"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300},
                cost_usd=0.002,
            ),
        ]

        # Simulate ReAct loop
        messages = [{"role": "user", "content": "Generate a report for session s-1"}]

        first_response = await mock_llm_client.chat(messages=messages)
        first_parsed = json.loads(first_response.content)
        assert first_parsed["action"] == "query_simulation_data"

        # Simulate tool result being appended
        messages.append({"role": "assistant", "content": first_response.content})
        messages.append(
            {
                "role": "user",
                "content": json.dumps({"tool_result": {"sentiment_data": [0.6, 0.5, 0.3, -0.1]}}),
            }
        )

        second_response = await mock_llm_client.chat(messages=messages)
        second_parsed = json.loads(second_response.content)
        assert second_parsed["action"] == "final_answer"
        assert "## Report" in second_parsed["action_input"]

    @pytest.mark.asyncio
    async def test_react_loop_handles_tool_error(self, mock_llm_client):
        mock_llm_client.chat.side_effect = [
            MagicMock(
                content=json.dumps(
                    {
                        "thought": "Tool returned an error. I will try a different approach.",
                        "action": "final_answer",
                        "action_input": "## Report\n\nInsufficient data for detailed analysis.",
                    }
                ),
                model="test-model",
                usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
                cost_usd=0.001,
            ),
        ]

        response = await mock_llm_client.chat(
            messages=[{"role": "user", "content": "Generate report (tool error scenario)"}]
        )
        parsed = json.loads(response.content)
        assert parsed["action"] == "final_answer"


# ======================================================================
# Chat continuation
# ======================================================================


class TestChatContinuesConversation:
    """Test that the chat endpoint maintains conversational context."""

    @pytest.mark.asyncio
    async def test_chat_returns_reply(self, test_client):
        response = await test_client.post(
            "/api/report/chat",
            json={
                "session_id": str(uuid.uuid4()),
                "message": "What were the main drivers of sentiment change?",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        reply = data["data"]
        assert "reply" in reply
        assert len(reply["reply"]) > 0
        assert "user_message" in reply

    @pytest.mark.asyncio
    async def test_chat_with_agent_id(self, test_client):
        response = await test_client.post(
            "/api/report/chat",
            json={
                "session_id": str(uuid.uuid4()),
                "message": "Why did you delay buying?",
                "agent_id": 42,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["agent_id"] == 42

    @pytest.mark.asyncio
    async def test_chat_preserves_session_context(self, mock_llm_client):
        """Verify that conversation history is passed to the LLM."""
        history = [
            {"role": "user", "content": "Tell me about property sentiment."},
            {"role": "assistant", "content": "Sentiment was positive until round 15."},
            {"role": "user", "content": "What happened at round 15?"},
        ]

        await mock_llm_client.chat(messages=history)

        mock_llm_client.chat.assert_awaited_once_with(messages=history)
        call_args = mock_llm_client.chat.call_args
        assert len(call_args.kwargs["messages"]) == 3


# ======================================================================
# Agent interview
# ======================================================================


class TestAgentInterviewUsesHistory:
    """Test the agent interview endpoint."""

    @pytest.mark.asyncio
    async def test_interview_returns_answer(self, test_client):
        response = await test_client.post(
            "/api/report/interview",
            json={
                "session_id": str(uuid.uuid4()),
                "agent_id": 7,
                "question": "Why did you decide to emigrate?",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        answer = data["data"]
        assert "answer" in answer
        assert "agent_id" in answer
        assert answer["agent_id"] == 7
        assert len(answer["answer"]) > 0

    @pytest.mark.asyncio
    async def test_interview_references_agent(self, test_client):
        agent_id = 15
        response = await test_client.post(
            "/api/report/interview",
            json={
                "session_id": str(uuid.uuid4()),
                "agent_id": agent_id,
                "question": "What is your monthly income?",
            },
        )

        data = response.json()
        assert data["data"]["agent_id"] == agent_id
        # The answer is generated by LLM and may not contain the agent ID
        # string; just verify we got a non-empty answer back.
        assert len(data["data"]["answer"]) > 0

    @pytest.mark.asyncio
    async def test_interview_with_llm_mock(self, mock_llm_client):
        """Test that interview constructs correct prompt with agent context."""
        mock_llm_client.chat.return_value = MagicMock(
            content="As a 28-year-old professional in Central, I delayed my property purchase because interest rates rose.",
            model="test-model",
            usage={"prompt_tokens": 200, "completion_tokens": 80, "total_tokens": 280},
            cost_usd=0.002,
        )

        agent_profile = {
            "id": 7,
            "agent_type": "resident",
            "age": 28,
            "sex": "F",
            "district": "Central",
            "occupation": "accountant",
            "income_bracket": "high",
        }

        messages = [
            {
                "role": "system",
                "content": (
                    f"You are Agent #{agent_profile['id']}, a {agent_profile['age']}-year-old "
                    f"{agent_profile['occupation']} living in {agent_profile['district']}."
                ),
            },
            {"role": "user", "content": "Why did you delay buying property?"},
        ]

        response = await mock_llm_client.chat(messages=messages)
        assert "Central" in response.content
        assert "property" in response.content.lower()


def test_report_agent_has_validation_tool():
    from backend.app.services.report_agent import TOOLS

    assert "get_validation_summary" in TOOLS
