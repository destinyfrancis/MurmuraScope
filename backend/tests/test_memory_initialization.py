"""Unit tests for MemoryInitializationService.

Markers: unit (default — no DB, no HTTP, no LLM)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# These imports will fail until Task 4 creates the module — that's expected.
from backend.app.services.memory_initialization import (
    HydrationResult,
    MemoryInitializationService,
    _agent_id_from_str,
    _resolve_key,
)

# ---------------------------------------------------------------------------
# _resolve_key — fuzzy matching
# ---------------------------------------------------------------------------


class TestResolveKey:
    def test_exact_match(self):
        keys = {"z_gen_undergrad", "grad_researcher", "local_parent_alumni"}
        assert _resolve_key("z_gen_undergrad", keys) == "z_gen_undergrad"

    def test_substring_agent_in_key(self):
        keys = {"student_rights_advocate", "institutional_defender"}
        # "student" is substring of "student_rights_advocate"
        assert _resolve_key("student", keys) == "student_rights_advocate"

    def test_substring_key_in_agent(self):
        keys = {"grad_researcher"}
        assert _resolve_key("grad_researcher_female", keys) == "grad_researcher"

    def test_no_match_returns_none(self):
        keys = {"z_gen_undergrad", "grad_researcher"}
        assert _resolve_key("PoliticalFigure", keys) is None

    def test_empty_keys_returns_none(self):
        assert _resolve_key("anything", set()) is None


# ---------------------------------------------------------------------------
# _agent_id_from_str — deterministic hash
# ---------------------------------------------------------------------------


class TestAgentIdFromStr:
    def test_returns_positive_int(self):
        result = _agent_id_from_str("whu_student_001")
        assert isinstance(result, int)
        assert result > 0

    def test_deterministic(self):
        assert _agent_id_from_str("foo_bar") == _agent_id_from_str("foo_bar")

    def test_different_inputs_different_outputs(self):
        assert _agent_id_from_str("a") != _agent_id_from_str("b")

    def test_fits_in_32bit(self):
        assert _agent_id_from_str("any_string") < 2**31


# ---------------------------------------------------------------------------
# Phase 2 JSON parse — _parse_world_context_response
# ---------------------------------------------------------------------------


class TestParseWorldContextResponse:
    def _svc(self) -> MemoryInitializationService:
        return MemoryInitializationService(llm_client=MagicMock(), lancedb_path="/tmp/test_lance")

    def test_valid_json_array(self):
        svc = self._svc()
        raw = json.dumps(
            [
                {
                    "context_type": "social_climate",
                    "title": "985 Prestige Collapse",
                    "content": "Public trust shattered.",
                    "severity": 0.9,
                    "phase": "crisis",
                },
            ]
        )
        result = svc._parse_world_context_response(raw)
        assert len(result) == 1
        assert result[0]["context_type"] == "social_climate"
        assert result[0]["severity"] == 0.9

    def test_unknown_context_type_kept(self):
        svc = self._svc()
        raw = json.dumps(
            [
                {"context_type": "unknown_type", "title": "X", "content": "Y", "severity": 0.5, "phase": "crisis"},
            ]
        )
        result = svc._parse_world_context_response(raw)
        assert result[0]["context_type"] == "unknown_type"

    def test_invalid_json_returns_empty(self):
        svc = self._svc()
        result = svc._parse_world_context_response("not json at all")
        assert result == []

    def test_missing_required_fields_skipped(self):
        svc = self._svc()
        raw = json.dumps([{"context_type": "social_climate"}])  # missing title/content
        result = svc._parse_world_context_response(raw)
        assert result == []


# ---------------------------------------------------------------------------
# Phase 3 JSON parse — _parse_persona_response
# ---------------------------------------------------------------------------


class TestParsePersonaResponse:
    def _svc(self) -> MemoryInitializationService:
        return MemoryInitializationService(llm_client=MagicMock(), lancedb_path="/tmp/test_lance")

    def _valid_persona(self, key: str = "student_rights_advocate") -> dict:
        return {
            "agent_type_key": key,
            "display_name": "18-22歲本科生",
            "age_min": 18,
            "age_max": 22,
            "region_hint": "any",
            "population_ratio": 0.35,
            "initial_memories": ["甲醛事件讓我恐懼", "學校欺騙了我們"],
            "personality_hints": {
                "openness": 0.8,
                "conscientiousness": 0.6,
                "extraversion": 0.5,
                "agreeableness": 0.3,
                "neuroticism": 0.75,
                "key_concerns": ["程序正義"],
                "preferred_platforms": ["xiaohongshu"],
                "stance_tendency": "rights_advocate",
                "verbal_patterns": ["護校蛆"],
                "trigger_topics": ["甲醛宿舍"],
            },
        }

    def test_valid_persona(self):
        svc = self._svc()
        raw = json.dumps([self._valid_persona()])
        result = svc._parse_persona_response(raw)
        assert len(result) == 1
        assert result[0]["agent_type_key"] == "student_rights_advocate"
        assert result[0]["initial_memories"] == ["甲醛事件讓我恐懼", "學校欺騙了我們"]

    def test_invalid_json_returns_empty(self):
        svc = self._svc()
        assert svc._parse_persona_response("{bad") == []

    def test_missing_agent_type_key_skipped(self):
        svc = self._svc()
        bad = self._valid_persona()
        del bad["agent_type_key"]
        result = svc._parse_persona_response(json.dumps([bad]))
        assert result == []


# ---------------------------------------------------------------------------
# hydrate_session_bulk — guard: no templates found
# ---------------------------------------------------------------------------


class TestHydrateSessionBulkGuard:
    @pytest.mark.asyncio
    async def test_no_templates_returns_zero_hydration(self):
        svc = MemoryInitializationService(llm_client=MagicMock(), lancedb_path="/tmp")

        async def _empty_templates(*args, **kwargs):
            return []

        with patch.object(svc, "_load_persona_templates", _empty_templates):
            result = await svc.hydrate_session_bulk(
                session_id="sess_001",
                graph_id="graph_001",
                agents=[("agent_a", "Person"), ("agent_b", "Organization")],
            )

        assert result == HydrationResult(total_injected=0, agents_skipped=2, templates_found=0)


# ---------------------------------------------------------------------------
# KGAgentFactory.create() — async factory (appended to existing test file)
# ---------------------------------------------------------------------------


class TestKGAgentFactoryCreate:
    @pytest.mark.asyncio
    async def test_create_with_no_templates_returns_empty_keys(self):
        from backend.app.services.kg_agent_factory import KGAgentFactory

        with patch(
            "backend.app.services.kg_agent_factory._load_persona_keys",
            new_callable=AsyncMock,
            return_value=[],
        ):
            factory = await KGAgentFactory.create(graph_id="no_templates_graph")
        assert factory._persona_keys == frozenset()

    @pytest.mark.asyncio
    async def test_create_loads_persona_keys(self):
        from backend.app.services.kg_agent_factory import KGAgentFactory

        with patch(
            "backend.app.services.kg_agent_factory._load_persona_keys",
            new_callable=AsyncMock,
            return_value=["student_rights_advocate", "institutional_defender"],
        ):
            factory = await KGAgentFactory.create(graph_id="graph_001")
        assert "student_rights_advocate" in factory._persona_keys

    def test_direct_init_still_works(self):
        """Existing KGAgentFactory() constructor must remain backward-compatible."""
        from backend.app.services.kg_agent_factory import KGAgentFactory

        factory = KGAgentFactory()
        assert factory._persona_keys == frozenset()


# ---------------------------------------------------------------------------
# Integration tests (use real aiosqlite, no LLM)
# Marked as integration by conftest.py auto-classifier
# ---------------------------------------------------------------------------

from contextlib import asynccontextmanager
from unittest.mock import patch as _patch

import aiosqlite


@pytest.mark.asyncio
async def test_integration_build_and_hydrate(tmp_path):
    """Full pipeline: build_from_graph writes tables, hydrate reads and injects."""

    # Point DB to a temp file
    db_path = str(tmp_path / "test.db")

    # Apply schema
    schema_path = "backend/database/schema.sql"
    with open(schema_path) as f:
        schema_sql = f.read()
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(schema_sql)
        await db.commit()

    @asynccontextmanager
    async def patched_get_db():
        async with aiosqlite.connect(db_path) as conn:
            conn.row_factory = aiosqlite.Row
            yield conn

    with _patch("backend.app.services.memory_initialization.get_db", patched_get_db):
        # Mock LLM — chat_json returns a parsed dict/list (already deserialized)
        mock_llm = AsyncMock()
        mock_llm.chat_json = AsyncMock(
            side_effect=[
                # Phase 2: world context — chat_json returns the parsed list
                [
                    {
                        "context_type": "social_climate",
                        "title": "985濾鏡破碎",
                        "content": "公眾信任崩潰",
                        "severity": 0.9,
                        "phase": "crisis",
                    }
                ],
                # Phase 3: persona templates
                [
                    {
                        "agent_type_key": "student_activist",
                        "display_name": "本科維權生",
                        "age_min": 18,
                        "age_max": 22,
                        "region_hint": "any",
                        "population_ratio": 0.35,
                        "initial_memories": ["學校欺騙了我"],
                        "personality_hints": {
                            "openness": 0.8,
                            "conscientiousness": 0.6,
                            "extraversion": 0.5,
                            "agreeableness": 0.3,
                            "neuroticism": 0.75,
                            "key_concerns": ["透明度"],
                            "preferred_platforms": ["weibo"],
                            "stance_tendency": "rights_advocate",
                            "verbal_patterns": ["護校蛆"],
                            "trigger_topics": ["甲醛"],
                        },
                    }
                ],
            ]
        )

        svc = MemoryInitializationService(llm_client=mock_llm, lancedb_path=str(tmp_path / "lance"))
        result = await svc.build_from_graph("test_graph_001", "武漢大學甲醛宿舍事件")

        assert result.world_context_count == 1
        assert result.persona_template_count == 1

        # Verify DB rows
        async with aiosqlite.connect(db_path) as db:
            rows = await (
                await db.execute(
                    "SELECT context_type, title FROM seed_world_context WHERE graph_id = ?", ("test_graph_001",)
                )
            ).fetchall()
            assert len(rows) == 1
            assert rows[0][1] == "985濾鏡破碎"

            t_rows = await (
                await db.execute(
                    "SELECT agent_type_key FROM seed_persona_templates WHERE graph_id = ?", ("test_graph_001",)
                )
            ).fetchall()
            assert len(t_rows) == 1
            assert t_rows[0][0] == "student_activist"

        # Now hydrate
        result2 = await svc.hydrate_session_bulk(
            session_id="sess_test_001",
            graph_id="test_graph_001",
            agents=[("agent_slug_001", "student_activist")],
        )

        assert result2.total_injected == 1
        assert result2.templates_found == 1
        assert result2.agents_skipped == 0

        # Verify agent_memories row
        async with aiosqlite.connect(db_path) as db:
            mem_rows = await (
                await db.execute(
                    "SELECT round_number, memory_type, salience_score FROM agent_memories WHERE session_id = ?",
                    ("sess_test_001",),
                )
            ).fetchall()
            assert len(mem_rows) == 1
            assert mem_rows[0][0] == 0  # round_number=0
            assert mem_rows[0][1] == "seed"  # memory_type
            assert mem_rows[0][2] == pytest.approx(0.9)  # salience
