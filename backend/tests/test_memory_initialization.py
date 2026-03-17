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
    SeedInitResult,
    WorldContextEntry,
    _resolve_key,
    _agent_id_from_str,
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
        raw = json.dumps([
            {"context_type": "social_climate", "title": "985 Prestige Collapse",
             "content": "Public trust shattered.", "severity": 0.9, "phase": "crisis"},
        ])
        result = svc._parse_world_context_response(raw)
        assert len(result) == 1
        assert result[0]["context_type"] == "social_climate"
        assert result[0]["severity"] == 0.9

    def test_unknown_context_type_kept(self):
        svc = self._svc()
        raw = json.dumps([
            {"context_type": "unknown_type", "title": "X", "content": "Y",
             "severity": 0.5, "phase": "crisis"},
        ])
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
            "age_min": 18, "age_max": 22,
            "region_hint": "any",
            "population_ratio": 0.35,
            "initial_memories": ["甲醛事件讓我恐懼", "學校欺騙了我們"],
            "personality_hints": {
                "openness": 0.8, "conscientiousness": 0.6,
                "extraversion": 0.5, "agreeableness": 0.3, "neuroticism": 0.75,
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
            new_callable=AsyncMock, return_value=[],
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
