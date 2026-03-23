"""Tests for universal (domain-agnostic) ontology generalisation.

Covers:
- Ontology prompts are free of HK-specific language in system messages.
- OntologyGenerator.generate() dispatches to correct defaults based on
  domain_hint ("auto" → generic, "hk" → HK-specific).
- ZeroConfigService.detect_mode() classifies HK vs geopolitical text.
- ZeroConfigResult includes a ``mode`` field with correct default.
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# 1. Prompt string assertions
# ---------------------------------------------------------------------------


class TestOntologyPromptsAreGeneric:
    """System-message strings must not bias the LLM toward Hong Kong."""

    def test_ontology_generation_system_no_hk(self) -> None:
        from backend.prompts.ontology_prompts import ONTOLOGY_GENERATION_SYSTEM

        assert "hong kong" not in ONTOLOGY_GENERATION_SYSTEM.lower(), (
            "ONTOLOGY_GENERATION_SYSTEM must not reference 'Hong Kong'"
        )

    def test_entity_extraction_system_no_hk(self) -> None:
        from backend.prompts.ontology_prompts import ENTITY_EXTRACTION_SYSTEM

        assert "hong kong" not in ENTITY_EXTRACTION_SYSTEM.lower(), (
            "ENTITY_EXTRACTION_SYSTEM must not reference 'Hong Kong'"
        )

    def test_community_summary_system_no_hk(self) -> None:
        from backend.prompts.ontology_prompts import COMMUNITY_SUMMARY_SYSTEM

        assert "hong kong" not in COMMUNITY_SUMMARY_SYSTEM.lower(), (
            "COMMUNITY_SUMMARY_SYSTEM must not reference 'Hong Kong'"
        )

    def test_default_hk_types_preserved(self) -> None:
        """DEFAULT_HK_* constants must still exist for backward compatibility."""
        from backend.prompts.ontology_prompts import (
            DEFAULT_HK_ENTITY_TYPES,
            DEFAULT_HK_RELATION_TYPES,
        )

        assert len(DEFAULT_HK_ENTITY_TYPES) > 0
        assert len(DEFAULT_HK_RELATION_TYPES) > 0

    def test_generic_entity_types_exist(self) -> None:
        from backend.prompts.ontology_prompts import DEFAULT_GENERIC_ENTITY_TYPES

        assert "Person" in DEFAULT_GENERIC_ENTITY_TYPES
        assert "Organization" in DEFAULT_GENERIC_ENTITY_TYPES
        assert "Country" in DEFAULT_GENERIC_ENTITY_TYPES

    def test_generic_relation_types_exist(self) -> None:
        from backend.prompts.ontology_prompts import DEFAULT_GENERIC_RELATION_TYPES

        assert "SUPPORTS" in DEFAULT_GENERIC_RELATION_TYPES
        assert "OPPOSES" in DEFAULT_GENERIC_RELATION_TYPES
        assert "INFLUENCES" in DEFAULT_GENERIC_RELATION_TYPES

    def test_generic_entity_types_count(self) -> None:
        from backend.prompts.ontology_prompts import DEFAULT_GENERIC_ENTITY_TYPES

        assert len(DEFAULT_GENERIC_ENTITY_TYPES) >= 8

    def test_generic_relation_types_count(self) -> None:
        from backend.prompts.ontology_prompts import DEFAULT_GENERIC_RELATION_TYPES

        assert len(DEFAULT_GENERIC_RELATION_TYPES) >= 8


# ---------------------------------------------------------------------------
# 2. OntologyGenerator domain_hint dispatch
# ---------------------------------------------------------------------------


def _make_mock_llm(
    entity_types: list[str] | None = None,
    relation_types: list[str] | None = None,
) -> MagicMock:
    """Return a mock LLMClient whose chat_json always returns the given types."""
    mock_llm = MagicMock()
    mock_llm.chat_json = AsyncMock(
        return_value={
            "entity_types": entity_types or ["Person", "Organization"],
            "relation_types": relation_types or ["INFLUENCES", "CONTROLS"],
        }
    )
    return mock_llm


class TestOntologyGeneratorDomainHint:
    """OntologyGenerator.generate() must respect domain_hint."""

    @pytest.mark.asyncio
    async def test_auto_hint_uses_generic_defaults_on_llm_failure(self) -> None:
        """When LLM fails and domain_hint is 'auto', fall back to generic types."""
        from backend.app.services.ontology_generator import OntologyGenerator
        from backend.prompts.ontology_prompts import (
            DEFAULT_GENERIC_ENTITY_TYPES,
            DEFAULT_GENERIC_RELATION_TYPES,
        )

        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

        gen = OntologyGenerator(llm_client=mock_llm)
        entities, relations = await gen.generate("geopolitics", "NATO invades", domain_hint="auto")

        assert entities == DEFAULT_GENERIC_ENTITY_TYPES
        assert relations == DEFAULT_GENERIC_RELATION_TYPES

    @pytest.mark.asyncio
    async def test_hk_hint_uses_hk_defaults_on_llm_failure(self) -> None:
        """When LLM fails and domain_hint is 'hk', fall back to HK-specific types."""
        from backend.app.services.ontology_generator import OntologyGenerator
        from backend.prompts.ontology_prompts import (
            DEFAULT_HK_ENTITY_TYPES,
            DEFAULT_HK_RELATION_TYPES,
        )

        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

        gen = OntologyGenerator(llm_client=mock_llm)
        entities, relations = await gen.generate("housing", "香港樓市", domain_hint="hk")

        assert entities == DEFAULT_HK_ENTITY_TYPES
        assert relations == DEFAULT_HK_RELATION_TYPES

    @pytest.mark.asyncio
    async def test_auto_hint_passes_generic_defaults_to_llm_prompt(self) -> None:
        """With domain_hint='auto', the prompt must include generic defaults."""
        from backend.app.services.ontology_generator import OntologyGenerator
        from backend.prompts.ontology_prompts import DEFAULT_GENERIC_ENTITY_TYPES

        mock_llm = _make_mock_llm(
            entity_types=["Warrior", "State"],
            relation_types=["INVADES"],
        )
        gen = OntologyGenerator(llm_client=mock_llm)
        await gen.generate("war", "Military conflict", domain_hint="auto")

        call_args = mock_llm.chat_json.call_args
        messages = call_args[0][0]
        user_content = next(m["content"] for m in messages if m["role"] == "user")

        # The prompt must contain at least one of the generic entity types
        assert any(et in user_content for et in DEFAULT_GENERIC_ENTITY_TYPES), (
            "User prompt must include generic entity types when domain_hint='auto'"
        )

    @pytest.mark.asyncio
    async def test_hk_hint_passes_hk_defaults_to_llm_prompt(self) -> None:
        """With domain_hint='hk', the prompt must include HK-specific defaults."""
        from backend.app.services.ontology_generator import OntologyGenerator
        from backend.prompts.ontology_prompts import DEFAULT_HK_ENTITY_TYPES

        mock_llm = _make_mock_llm()
        gen = OntologyGenerator(llm_client=mock_llm)
        await gen.generate("property", "Hong Kong housing", domain_hint="hk")

        call_args = mock_llm.chat_json.call_args
        messages = call_args[0][0]
        user_content = next(m["content"] for m in messages if m["role"] == "user")

        assert any(et in user_content for et in DEFAULT_HK_ENTITY_TYPES), (
            "User prompt must include HK entity types when domain_hint='hk'"
        )

    @pytest.mark.asyncio
    async def test_default_hint_is_auto(self) -> None:
        """Omitting domain_hint should behave the same as 'auto'."""
        from backend.app.services.ontology_generator import OntologyGenerator
        from backend.prompts.ontology_prompts import DEFAULT_GENERIC_ENTITY_TYPES

        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(side_effect=RuntimeError("forced failure"))

        gen = OntologyGenerator(llm_client=mock_llm)
        # No domain_hint argument — should default to "auto" → generic fallback
        entities, _ = await gen.generate("global", "World trade war")

        assert entities == DEFAULT_GENERIC_ENTITY_TYPES

    @pytest.mark.asyncio
    async def test_llm_result_returned_when_valid(self) -> None:
        """LLM result is returned when it contains valid string lists."""
        from backend.app.services.ontology_generator import OntologyGenerator

        llm_entities = ["State", "MilitaryAlliance", "Leader"]
        llm_relations = ["INVADES", "NEGOTIATES_WITH"]
        mock_llm = _make_mock_llm(
            entity_types=llm_entities,
            relation_types=llm_relations,
        )
        gen = OntologyGenerator(llm_client=mock_llm)
        entities, relations = await gen.generate("conflict", "NATO conflict", domain_hint="auto")

        assert entities == llm_entities
        assert relations == llm_relations

    @pytest.mark.asyncio
    async def test_empty_llm_result_falls_back_to_generic(self) -> None:
        """Empty lists from LLM must trigger fallback to generic defaults."""
        from backend.app.services.ontology_generator import OntologyGenerator
        from backend.prompts.ontology_prompts import DEFAULT_GENERIC_ENTITY_TYPES

        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(return_value={"entity_types": [], "relation_types": []})
        gen = OntologyGenerator(llm_client=mock_llm)
        entities, _ = await gen.generate("unknown", "mystery text", domain_hint="auto")

        assert entities == DEFAULT_GENERIC_ENTITY_TYPES


# ---------------------------------------------------------------------------
# 3. ZeroConfigService.detect_mode()
# ---------------------------------------------------------------------------


class TestDetectMode:
    """ZeroConfigService.detect_mode() classification tests."""

    def setup_method(self) -> None:
        from backend.app.services.zero_config import ZeroConfigService

        self.svc = ZeroConfigService()

    # HK detection ---------------------------------------------------------

    def test_hk_chinese_characters(self) -> None:
        assert self.svc.detect_mode("香港樓市下跌趨勢") == "hk_demographic"

    def test_hk_emigration_keyword(self) -> None:
        assert self.svc.detect_mode("移民潮加劇") == "hk_demographic"

    def test_hk_fertility_keyword(self) -> None:
        assert self.svc.detect_mode("生育率下降") == "hk_demographic"

    def test_hk_english_name(self) -> None:
        assert self.svc.detect_mode("Hong Kong property market") == "hk_demographic"

    def test_hk_abbreviation(self) -> None:
        assert self.svc.detect_mode("HK economy outlook 2025") == "hk_demographic"

    def test_hk_hsi_indicator(self) -> None:
        assert self.svc.detect_mode("HSI drops 500 points today") == "hk_demographic"

    def test_hk_ccl_indicator(self) -> None:
        assert self.svc.detect_mode("CCL index rises in Q3") == "hk_demographic"

    # KG-driven detection --------------------------------------------------

    def test_geopolitical_war(self) -> None:
        assert self.svc.detect_mode("Military troops invade the border region") == "kg_driven"

    def test_geopolitical_nato(self) -> None:
        assert self.svc.detect_mode("NATO alliance responds to conflict") == "kg_driven"

    def test_geopolitical_sanctions(self) -> None:
        assert self.svc.detect_mode("International sanctions imposed on regime") == "kg_driven"

    def test_geopolitical_trade_war(self) -> None:
        assert self.svc.detect_mode("US-China trade war escalates with tariffs") == "kg_driven"

    def test_geopolitical_coup(self) -> None:
        assert self.svc.detect_mode("Military coup overthrows elected government") == "kg_driven"

    # HK wins when both present -------------------------------------------

    def test_hk_wins_over_geopolitical(self) -> None:
        """HK keywords take priority over geopolitical for backward compat."""
        mixed = "香港 military alliance conflict"
        assert self.svc.detect_mode(mixed) == "hk_demographic"

    # Default behaviour ----------------------------------------------------

    def test_unrelated_text_defaults_hk_demographic(self) -> None:
        assert self.svc.detect_mode("random unrelated text xyz123") == "hk_demographic"

    def test_empty_text_defaults_hk_demographic(self) -> None:
        assert self.svc.detect_mode("") == "hk_demographic"

    def test_case_insensitive_hk(self) -> None:
        assert self.svc.detect_mode("HONG KONG market") == "hk_demographic"

    def test_case_insensitive_geopolitical(self) -> None:
        assert self.svc.detect_mode("NATO INVASION NUCLEAR THREAT") == "kg_driven"


# ---------------------------------------------------------------------------
# 4. ZeroConfigResult includes mode field
# ---------------------------------------------------------------------------


class TestZeroConfigResultMode:
    """ZeroConfigResult must expose a ``mode`` field."""

    def test_default_mode_is_hk_demographic(self) -> None:
        from backend.app.services.zero_config import ZeroConfigResult

        r = ZeroConfigResult(
            domain_pack_id="hk_city",
            agent_count=100,
            round_count=10,
            preset_name="fast",
            seed_text="test",
            detected_entities=[],
            estimated_duration_seconds=20,
        )
        assert r.mode == "hk_demographic"

    def test_mode_can_be_set_to_kg_driven(self) -> None:
        from backend.app.services.zero_config import ZeroConfigResult

        r = ZeroConfigResult(
            domain_pack_id="global_macro",
            agent_count=200,
            round_count=15,
            preset_name="standard",
            seed_text="NATO conflict",
            detected_entities=[],
            estimated_duration_seconds=60,
            mode="kg_driven",
        )
        assert r.mode == "kg_driven"

    def test_result_is_still_frozen(self) -> None:
        from backend.app.services.zero_config import ZeroConfigResult

        r = ZeroConfigResult(
            domain_pack_id="hk_city",
            agent_count=100,
            round_count=10,
            preset_name="fast",
            seed_text="test",
            detected_entities=[],
            estimated_duration_seconds=20,
        )
        with pytest.raises(AttributeError):
            r.mode = "kg_driven"  # type: ignore[misc]

    @pytest.mark.asyncio
    async def test_prepare_returns_mode_hk_for_hk_text(self) -> None:
        from backend.app.services.zero_config import ZeroConfigService

        svc = ZeroConfigService()
        with patch.dict(sys.modules, {"backend.app.services.text_processor": None}):
            result = await svc.prepare("香港樓市下跌")

        assert result.mode == "hk_demographic"

    @pytest.mark.asyncio
    async def test_prepare_returns_mode_kg_for_geopolitical_text(self) -> None:
        from backend.app.services.zero_config import ZeroConfigService

        svc = ZeroConfigService()
        with patch.dict(sys.modules, {"backend.app.services.text_processor": None}):
            result = await svc.prepare("NATO military invasion war sanctions")

        assert result.mode == "kg_driven"
