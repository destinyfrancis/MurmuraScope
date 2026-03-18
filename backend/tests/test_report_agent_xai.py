"""Tests for report_agent_xai insight_forge tool."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

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
        mock_instance = MagicMock()
        mock_instance.chat = AsyncMock(return_value=mock_llm_response)

        with patch(
            "backend.app.services.report_agent_xai._get_xai_llm",
            return_value=mock_instance,
        ):
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
        mock_instance = MagicMock()
        mock_instance.chat = AsyncMock(return_value=mock_llm_response)

        with patch(
            "backend.app.services.report_agent_xai._get_xai_llm",
            return_value=mock_instance,
        ):
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


# ---------------------------------------------------------------------------
# Task 10: New XAI tools — get_topic_evolution, get_platform_breakdown,
#           get_agent_story_arcs
# ---------------------------------------------------------------------------

import os
import aiosqlite
import pytest_asyncio


@pytest_asyncio.fixture()
async def tmp_db(tmp_path):
    """Temporary aiosqlite DB with full project schema, patched into get_db."""
    db_path = str(tmp_path / "xai_test.db")
    schema_path = os.path.join(
        os.path.dirname(__file__), "..", "database", "schema.sql"
    )
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        with open(schema_path, encoding="utf-8") as f:
            await db.executescript(f.read())
        await db.commit()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _patched_get_db():
        async with aiosqlite.connect(db_path) as conn:
            conn.row_factory = aiosqlite.Row
            yield conn

    with patch("backend.app.services.report_agent_xai.get_db", _patched_get_db):
        yield db_path


class TestGetTopicEvolution:
    @pytest.mark.asyncio
    async def test_returns_topic_evolution_result(self, tmp_db):
        """get_topic_evolution returns a TopicEvolutionResult."""
        from backend.app.models.report_models import TopicEvolutionResult
        from backend.app.utils.llm_client import LLMResponse

        async with aiosqlite.connect(tmp_db) as db:
            db.row_factory = aiosqlite.Row
            await db.execute(
                "INSERT OR IGNORE INTO kg_nodes(id,session_id,entity_type,title) VALUES(?,?,?,?)",
                ("n1", "sess1", "Person", "A"),
            )
            await db.execute(
                "INSERT OR IGNORE INTO kg_nodes(id,session_id,entity_type,title) VALUES(?,?,?,?)",
                ("n2", "sess1", "Organization", "B"),
            )
            for rn in range(1, 11):
                await db.execute(
                    "INSERT INTO kg_edges(session_id,source_id,target_id,relation_type,description,round_number) "
                    "VALUES(?,?,?,?,?,?)",
                    ("sess1", "n1", "n2", "RELATES_TO", f"round {rn} discussion topic", rn),
                )
            await db.commit()


        mock_response = LLMResponse(
            content='["議題A", "議題B"]',
            model="claude-haiku-4-5-20251001",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            cost_usd=0.0,
        )
        with patch("backend.app.services.report_agent_xai.LLMClient") as MockLLM:
            instance = MockLLM.return_value
            instance.chat = AsyncMock(return_value=mock_response)
            from backend.app.services.report_agent_xai import get_topic_evolution
            result = await get_topic_evolution("sess1", window_size=5)

        assert isinstance(result, TopicEvolutionResult)
        assert len(result.windows) >= 1

    @pytest.mark.asyncio
    async def test_empty_session_returns_empty_windows(self, tmp_db):
        """get_topic_evolution with no kg_edges returns empty windows."""
        from backend.app.models.report_models import TopicEvolutionResult
        from backend.app.services.report_agent_xai import get_topic_evolution

        result = await get_topic_evolution("nonexistent_session")
        assert isinstance(result, TopicEvolutionResult)
        assert result.windows == ()

    @pytest.mark.asyncio
    async def test_migration_path_built_from_topics(self, tmp_db):
        """migration_path joins dominant topics across windows."""
        from backend.app.utils.llm_client import LLMResponse

        async with aiosqlite.connect(tmp_db) as db:
            db.row_factory = aiosqlite.Row
            await db.execute(
                "INSERT OR IGNORE INTO kg_nodes(id,session_id,entity_type,title) VALUES(?,?,?,?)",
                ("n1", "sess2", "Person", "X"),
            )
            await db.execute(
                "INSERT OR IGNORE INTO kg_nodes(id,session_id,entity_type,title) VALUES(?,?,?,?)",
                ("n2", "sess2", "Organization", "Y"),
            )
            for rn in range(1, 6):
                await db.execute(
                    "INSERT INTO kg_edges(session_id,source_id,target_id,relation_type,description,round_number) "
                    "VALUES(?,?,?,?,?,?)",
                    ("sess2", "n1", "n2", "RELATES_TO", f"content {rn}", rn),
                )
            await db.commit()

        mock_response = LLMResponse(
            content='["程序正義"]',
            model="claude-haiku-4-5-20251001",
            usage={"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            cost_usd=0.0,
        )
        mock_llm_instance = MagicMock()
        mock_llm_instance.chat = AsyncMock(return_value=mock_response)
        with patch(
            "backend.app.services.report_agent_xai._get_xai_llm",
            return_value=mock_llm_instance,
        ):
            from backend.app.services.report_agent_xai import get_topic_evolution
            result = await get_topic_evolution("sess2", window_size=5)

        assert "程序正義" in result.migration_path


class TestGetPlatformBreakdown:
    @pytest.mark.asyncio
    async def test_returns_dict_with_platforms(self, tmp_db):
        """get_platform_breakdown returns dict keyed by platform."""
        async with aiosqlite.connect(tmp_db) as db:
            db.row_factory = aiosqlite.Row
            for p in ["facebook", "instagram"]:
                await db.execute(
                    "INSERT INTO simulation_actions(session_id,agent_id,round_number,action_type,content,sentiment,oasis_username,platform) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    ("sess3", 1, 1, "post", f"{p} content", "positive", "user1", p),
                )
            await db.commit()

        from backend.app.services.report_agent_xai import get_platform_breakdown
        result = await get_platform_breakdown("sess3")
        assert isinstance(result, dict)
        assert "facebook" in result or "instagram" in result

    @pytest.mark.asyncio
    async def test_empty_session_returns_empty_dict(self, tmp_db):
        """get_platform_breakdown with no actions returns {}."""
        from backend.app.services.report_agent_xai import get_platform_breakdown
        result = await get_platform_breakdown("no_such_session")
        assert result == {}

    @pytest.mark.asyncio
    async def test_breakdown_contains_expected_keys(self, tmp_db):
        """Each platform entry has total_actions, sentiment, top_action_types."""
        async with aiosqlite.connect(tmp_db) as db:
            db.row_factory = aiosqlite.Row
            for i in range(3):
                await db.execute(
                    "INSERT INTO simulation_actions(session_id,agent_id,round_number,action_type,content,sentiment,oasis_username,platform) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    ("sess4", i, 1, "post", "hello", "neutral", f"u{i}", "twitter"),
                )
            await db.commit()

        from backend.app.services.report_agent_xai import get_platform_breakdown
        result = await get_platform_breakdown("sess4")
        assert "twitter" in result
        entry = result["twitter"]
        assert "total_actions" in entry
        assert "sentiment" in entry
        assert "top_action_types" in entry


class TestGetAgentStoryArcs:
    def test_hk_demographic_returns_empty_list(self):
        """get_agent_story_arcs returns [] for hk_demographic mode."""
        import asyncio
        from backend.app.services.report_agent_xai import get_agent_story_arcs
        result = asyncio.run(get_agent_story_arcs("any_session", sim_mode="hk_demographic"))
        assert result == []

    def test_returns_list(self):
        """get_agent_story_arcs returns a list (may be empty if no fingerprints)."""
        import asyncio
        from backend.app.services.report_agent_xai import get_agent_story_arcs

        with patch("backend.app.services.report_agent_xai.get_db") as mock_get_db:
            from contextlib import asynccontextmanager
            mock_conn = AsyncMock()
            mock_conn.row_factory = None
            mock_cursor = AsyncMock()
            mock_cursor.fetchall = AsyncMock(return_value=[])

            @asynccontextmanager
            async def _fake_db():
                mock_conn.execute = AsyncMock(return_value=mock_cursor)
                yield mock_conn

            mock_get_db.side_effect = _fake_db
            result = asyncio.run(get_agent_story_arcs("sess5", sim_mode="kg_driven"))

        assert isinstance(result, list)


class TestNewToolsRegistration:
    def test_get_topic_evolution_in_tools(self):
        """get_topic_evolution is registered in TOOLS dict."""
        from backend.app.services.report_agent import TOOLS
        assert "get_topic_evolution" in TOOLS

    def test_get_platform_breakdown_in_tools(self):
        """get_platform_breakdown is registered in TOOLS dict."""
        from backend.app.services.report_agent import TOOLS
        assert "get_platform_breakdown" in TOOLS

    def test_get_agent_story_arcs_in_tools(self):
        """get_agent_story_arcs is registered in TOOLS dict."""
        from backend.app.services.report_agent import TOOLS
        assert "get_agent_story_arcs" in TOOLS

    def test_get_topic_evolution_handler_registered(self):
        """get_topic_evolution has a handler in _TOOL_HANDLERS."""
        from backend.app.services.report_agent import _TOOL_HANDLERS
        assert "get_topic_evolution" in _TOOL_HANDLERS

    def test_get_platform_breakdown_handler_registered(self):
        """get_platform_breakdown has a handler in _TOOL_HANDLERS."""
        from backend.app.services.report_agent import _TOOL_HANDLERS
        assert "get_platform_breakdown" in _TOOL_HANDLERS

    def test_get_agent_story_arcs_handler_registered(self):
        """get_agent_story_arcs has a handler in _TOOL_HANDLERS."""
        from backend.app.services.report_agent import _TOOL_HANDLERS
        assert "get_agent_story_arcs" in _TOOL_HANDLERS


class TestInterviewAgentsDeliberationUpgrade:
    @pytest.mark.asyncio
    async def test_interview_agents_queries_agent_decisions(self, tmp_db):
        """_handle_interview_agents fetches deliberation context from agent_decisions."""
        async with aiosqlite.connect(tmp_db) as db:
            db.row_factory = aiosqlite.Row
            # Only insert agent_decisions — no FK enforcement on session_id/agent_id
            await db.execute(
                "INSERT INTO agent_decisions(session_id,agent_id,round_number,decision_type,action,reasoning,confidence,topic_tags,emotional_reaction) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                ("sess_iv", 1, 1, "emigrate", "stay", "I decided to stay because...", 0.8, '["程序正義"]', "感到不安"),
            )
            await db.commit()

        from unittest.mock import MagicMock
        from backend.app.services.simulation_ipc import SimulationIPC

        mock_ipc = MagicMock(spec=SimulationIPC)
        mock_ipc.interview_agent = AsyncMock(return_value="I am concerned about the future.")

        with patch("backend.app.services.report_agent.get_db") as mock_get_db:
            from contextlib import asynccontextmanager
            import aiosqlite as _aiosqlite

            @asynccontextmanager
            async def _patched():
                async with _aiosqlite.connect(tmp_db) as conn:
                    conn.row_factory = _aiosqlite.Row
                    yield conn

            mock_get_db.side_effect = _patched

            from backend.app.services.report_agent import _handle_interview_agents
            result = await _handle_interview_agents(
                "sess_iv", {"agent_ids": [1], "question": "What do you think?"}, mock_ipc
            )

        import json as _json
        parsed = _json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["agent_id"] == 1
