"""Tests for report_agent_xai insight_forge tool."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from backend.app.models.report_models import InsightForgeResult


class TestInsightForgeResult:
    def test_insight_forge_result_is_frozen(self):
        """InsightForgeResult is a frozen dataclass."""
        result = InsightForgeResult(
            query="test",
            sub_queries=("a", "b"),
            facts=("fact1",),
            quotable_excerpts=("quote1",),
            source_agents=("agent1",),
        )
        with pytest.raises((AttributeError, TypeError)):
            result.query = "mutated"  # type: ignore[misc]

    def test_insight_forge_result_fields(self):
        """InsightForgeResult stores all five fields correctly."""
        result = InsightForgeResult(
            query="q",
            sub_queries=("s1", "s2"),
            facts=("f1", "f2"),
            quotable_excerpts=("e1",),
            source_agents=("a1",),
        )
        assert result.query == "q"
        assert result.sub_queries == ("s1", "s2")
        assert result.facts == ("f1", "f2")
        assert result.quotable_excerpts == ("e1",)
        assert result.source_agents == ("a1",)


class TestInsightForge:
    def test_insight_forge_returns_insight_forge_result(self):
        """insight_forge returns InsightForgeResult dataclass."""
        with patch(
            "backend.app.services.report_agent_xai._generate_sub_queries",
            new=AsyncMock(return_value=("sub1", "sub2")),
        ), patch(
            "backend.app.services.report_agent_xai._search_agent_memories",
            new=AsyncMock(
                return_value=[
                    {
                        "content": "Agent A said: 程序正義很重要",
                        "agent_id": "a1",
                        "agent_name": "陳同學",
                    }
                ]
            ),
        ), patch(
            "backend.app.services.report_agent_xai._search_kg_nodes_edges",
            new=AsyncMock(return_value=[]),
        ), patch(
            "backend.app.services.report_agent_xai._search_simulation_actions",
            new=AsyncMock(return_value=[]),
        ):
            from backend.app.services.report_agent_xai import insight_forge

            result = asyncio.run(insight_forge("sess1", "什麼議題最重要？"))

        assert isinstance(result, InsightForgeResult)
        assert len(result.sub_queries) == 2
        assert len(result.facts) >= 1

    def test_insight_forge_labels_quotable_excerpts(self):
        """Quotable excerpts contain agent-attributed content."""
        agent_memory = {
            "content": "制度改革是必要的",
            "agent_id": "a1",
            "agent_name": "陳博士",
        }

        with patch(
            "backend.app.services.report_agent_xai._generate_sub_queries",
            new=AsyncMock(return_value=("制度改革",)),
        ), patch(
            "backend.app.services.report_agent_xai._search_agent_memories",
            new=AsyncMock(return_value=[agent_memory]),
        ), patch(
            "backend.app.services.report_agent_xai._search_kg_nodes_edges",
            new=AsyncMock(return_value=[]),
        ), patch(
            "backend.app.services.report_agent_xai._search_simulation_actions",
            new=AsyncMock(return_value=[]),
        ):
            from backend.app.services.report_agent_xai import insight_forge

            result = asyncio.run(insight_forge("sess1", "制度改革問題"))

        assert len(result.quotable_excerpts) >= 1
        # Excerpts should contain agent identifier
        assert any("a1" in exc or "陳博士" in exc for exc in result.quotable_excerpts)

    def test_insight_forge_handles_empty_results(self):
        """insight_forge returns valid result when all searches return nothing."""
        with patch(
            "backend.app.services.report_agent_xai._generate_sub_queries",
            new=AsyncMock(return_value=("query1",)),
        ), patch(
            "backend.app.services.report_agent_xai._search_agent_memories",
            new=AsyncMock(return_value=[]),
        ), patch(
            "backend.app.services.report_agent_xai._search_kg_nodes_edges",
            new=AsyncMock(return_value=[]),
        ), patch(
            "backend.app.services.report_agent_xai._search_simulation_actions",
            new=AsyncMock(return_value=[]),
        ):
            from backend.app.services.report_agent_xai import insight_forge

            result = asyncio.run(insight_forge("sess1", "empty query"))

        assert isinstance(result, InsightForgeResult)
        assert result.facts == ()
        assert result.quotable_excerpts == ()
        assert result.source_agents == ()

    def test_insight_forge_handles_gather_exceptions(self):
        """insight_forge skips sources that raise exceptions (return_exceptions=True)."""
        with patch(
            "backend.app.services.report_agent_xai._generate_sub_queries",
            new=AsyncMock(return_value=("sub1",)),
        ), patch(
            "backend.app.services.report_agent_xai._search_agent_memories",
            new=AsyncMock(side_effect=RuntimeError("DB error")),
        ), patch(
            "backend.app.services.report_agent_xai._search_kg_nodes_edges",
            new=AsyncMock(return_value=[]),
        ), patch(
            "backend.app.services.report_agent_xai._search_simulation_actions",
            new=AsyncMock(return_value=[]),
        ):
            from backend.app.services.report_agent_xai import insight_forge

            # Should not raise even when one source fails
            result = asyncio.run(insight_forge("sess1", "test query"))

        assert isinstance(result, InsightForgeResult)

    def test_insight_forge_deduplicates_facts(self):
        """Duplicate fact content is deduplicated in result."""
        duplicate_memory = {"content": "同一個事實", "agent_id": "a1", "agent_name": "張三"}

        with patch(
            "backend.app.services.report_agent_xai._generate_sub_queries",
            new=AsyncMock(return_value=("query1", "query2")),
        ), patch(
            "backend.app.services.report_agent_xai._search_agent_memories",
            new=AsyncMock(return_value=[duplicate_memory, duplicate_memory]),
        ), patch(
            "backend.app.services.report_agent_xai._search_kg_nodes_edges",
            new=AsyncMock(return_value=[]),
        ), patch(
            "backend.app.services.report_agent_xai._search_simulation_actions",
            new=AsyncMock(return_value=[]),
        ):
            from backend.app.services.report_agent_xai import insight_forge

            result = asyncio.run(insight_forge("sess1", "test"))

        # Deduplicated — same fact should appear only once
        assert result.facts.count("同一個事實") == 1

    def test_insight_forge_kg_nodes_contribute_facts(self):
        """KG node/edge data contributes to facts via description field."""
        kg_item = {
            "label": "民主黨",
            "relation_type": "advocates",
            "description": "民主黨主張普選",
        }

        with patch(
            "backend.app.services.report_agent_xai._generate_sub_queries",
            new=AsyncMock(return_value=("民主",)),
        ), patch(
            "backend.app.services.report_agent_xai._search_agent_memories",
            new=AsyncMock(return_value=[]),
        ), patch(
            "backend.app.services.report_agent_xai._search_kg_nodes_edges",
            new=AsyncMock(return_value=[kg_item]),
        ), patch(
            "backend.app.services.report_agent_xai._search_simulation_actions",
            new=AsyncMock(return_value=[]),
        ):
            from backend.app.services.report_agent_xai import insight_forge

            result = asyncio.run(insight_forge("sess1", "民主黨立場"))

        assert any("民主黨主張普選" in f for f in result.facts)

    def test_insight_forge_sub_queries_stored(self):
        """sub_queries field stores the decomposed queries from _generate_sub_queries."""
        expected = ("香港政治", "社會運動", "政府回應")

        with patch(
            "backend.app.services.report_agent_xai._generate_sub_queries",
            new=AsyncMock(return_value=expected),
        ), patch(
            "backend.app.services.report_agent_xai._search_agent_memories",
            new=AsyncMock(return_value=[]),
        ), patch(
            "backend.app.services.report_agent_xai._search_kg_nodes_edges",
            new=AsyncMock(return_value=[]),
        ), patch(
            "backend.app.services.report_agent_xai._search_simulation_actions",
            new=AsyncMock(return_value=[]),
        ):
            from backend.app.services.report_agent_xai import insight_forge

            result = asyncio.run(insight_forge("sess1", "政治局勢"))

        assert result.sub_queries == expected


class TestGenerateSubQueries:
    def test_generate_sub_queries_returns_tuple(self):
        """_generate_sub_queries returns a tuple of strings."""
        from backend.app.utils.llm_client import LLMResponse

        mock_llm_response = LLMResponse(
            content='["子查詢1", "子查詢2", "子查詢3"]',
            model="claude-haiku-4-5-20251001",
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            cost_usd=0.0,
        )

        with patch(
            "backend.app.services.report_agent_xai.LLMClient"
        ) as MockLLMClient:
            instance = MockLLMClient.return_value
            instance.chat = AsyncMock(return_value=mock_llm_response)

            from backend.app.services.report_agent_xai import _generate_sub_queries

            result = asyncio.run(_generate_sub_queries("什麼議題最重要？"))

        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_generate_sub_queries_fallback_on_invalid_json(self):
        """_generate_sub_queries falls back to original query on bad LLM output."""
        from backend.app.utils.llm_client import LLMResponse

        mock_llm_response = LLMResponse(
            content="not valid JSON output",
            model="claude-haiku-4-5-20251001",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            cost_usd=0.0,
        )

        with patch(
            "backend.app.services.report_agent_xai.LLMClient"
        ) as MockLLMClient:
            instance = MockLLMClient.return_value
            instance.chat = AsyncMock(return_value=mock_llm_response)

            from backend.app.services.report_agent_xai import _generate_sub_queries

            result = asyncio.run(_generate_sub_queries("test query"))

        assert result == ("test query",)

    def test_generate_sub_queries_fallback_on_no_array(self):
        """_generate_sub_queries falls back when no JSON array found."""
        from backend.app.utils.llm_client import LLMResponse

        mock_llm_response = LLMResponse(
            content="Here are some queries: A, B, C",
            model="claude-haiku-4-5-20251001",
            usage={"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            cost_usd=0.0,
        )

        with patch(
            "backend.app.services.report_agent_xai.LLMClient"
        ) as MockLLMClient:
            instance = MockLLMClient.return_value
            instance.chat = AsyncMock(return_value=mock_llm_response)

            from backend.app.services.report_agent_xai import _generate_sub_queries

            result = asyncio.run(_generate_sub_queries("test query"))

        assert result == ("test query",)


class TestInsightForgeRegistration:
    def test_insight_forge_in_tools_dict(self):
        """insight_forge tool is registered in TOOLS dict."""
        from backend.app.services.report_agent import TOOLS

        assert "insight_forge" in TOOLS

    def test_insight_forge_handler_registered(self):
        """insight_forge handler is in _TOOL_HANDLERS."""
        from backend.app.services.report_agent import _TOOL_HANDLERS

        assert "insight_forge" in _TOOL_HANDLERS

    def test_insight_forge_tool_description_not_empty(self):
        """insight_forge tool description is non-empty."""
        from backend.app.services.report_agent import TOOLS

        assert len(TOOLS.get("insight_forge", "")) > 10

    @pytest.mark.asyncio
    async def test_insight_forge_dispatches_via_execute_tool(self):
        """ReportAgent._execute_tool dispatches insight_forge correctly."""
        from backend.app.services.report_agent import ReportAgent

        agent = ReportAgent()
        mock_result = InsightForgeResult(
            query="q",
            sub_queries=("s1",),
            facts=("f1",),
            quotable_excerpts=("e1",),
            source_agents=("a1",),
        )

        # Patch the alias imported into report_agent module namespace
        with patch(
            "backend.app.services.report_agent._insight_forge",
            new=AsyncMock(return_value=mock_result),
        ):
            result = await agent._execute_tool(
                "insight_forge", {"query": "q"}, "sess1"
            )

        assert "f1" in result or "e1" in result
