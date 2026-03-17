"""Tests for ZeroConfigService and quick-start endpoint."""
from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.services.zero_config import (
    ZeroConfigResult,
    ZeroConfigService,
    _DOMAIN_KEYWORDS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_text_processor_module(
    entities: list[str] | None = None,
    *,
    raise_on_import: bool = False,
) -> MagicMock | None:
    """Build a fake ``backend.app.services.text_processor`` module.

    When *raise_on_import* is True, returns ``None`` so that
    ``patch.dict("sys.modules", ...)`` makes the import raise ImportError.
    """
    if raise_on_import:
        return None  # type: ignore[return-value]
    mock_tp_instance = MagicMock()
    mock_tp_instance.analyze_seed = AsyncMock(
        return_value={"entities": entities or []},
    )
    mod = MagicMock()
    mod.TextProcessor = MagicMock(return_value=mock_tp_instance)
    return mod


# ---------------------------------------------------------------------------
# ZeroConfigResult dataclass tests
# ---------------------------------------------------------------------------


class TestZeroConfigResult:
    """Frozen dataclass creation and immutability."""

    def test_create_result(self) -> None:
        r = ZeroConfigResult(
            domain_pack_id="hk_city",
            agent_count=100,
            round_count=10,
            preset_name="fast",
            seed_text="test",
            detected_entities=["entity_a"],
            estimated_duration_seconds=20,
        )
        assert r.domain_pack_id == "hk_city"
        assert r.agent_count == 100
        assert r.detected_entities == ["entity_a"]

    def test_result_is_frozen(self) -> None:
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
            r.agent_count = 999  # type: ignore[misc]


# ---------------------------------------------------------------------------
# infer_domain tests
# ---------------------------------------------------------------------------


class TestInferDomain:
    """Domain inference from seed text keywords."""

    def setup_method(self) -> None:
        self.svc = ZeroConfigService()

    def test_hk_property_text(self) -> None:
        assert self.svc.infer_domain("香港樓市下跌") == "hk_city"

    def test_us_market_text(self) -> None:
        assert self.svc.infer_domain("Nasdaq crashes after Fed rate hike") == "us_markets"

    def test_empty_text_defaults_hk_city(self) -> None:
        assert self.svc.infer_domain("") == "hk_city"

    def test_mixed_keywords_highest_wins(self) -> None:
        result = self.svc.infer_domain("香港樓市 fed")
        assert result == "hk_city"

    def test_chinese_narrative_text(self) -> None:
        assert self.svc.infer_domain("輿論走向與民意變化") == "public_narrative"

    def test_english_real_estate(self) -> None:
        assert self.svc.infer_domain(
            "Real estate mortgage rates rising in the housing market",
        ) == "real_estate"

    def test_community_movement(self) -> None:
        assert self.svc.infer_domain(
            "grassroots community activism movement",
        ) == "community_movement"

    def test_company_competitor(self) -> None:
        assert self.svc.infer_domain(
            "company competitor market share analysis",
        ) == "company_competitor"

    def test_global_macro(self) -> None:
        assert self.svc.infer_domain(
            "global recession trade war commodity prices",
        ) == "global_macro"

    def test_no_keywords_defaults(self) -> None:
        assert self.svc.infer_domain("completely unrelated text xyz123") == "hk_city"

    def test_case_insensitive(self) -> None:
        assert self.svc.infer_domain("NASDAQ FED INFLATION") == "us_markets"


# ---------------------------------------------------------------------------
# prepare() tests
# ---------------------------------------------------------------------------


class TestPrepare:
    """Async prepare method tests."""

    def setup_method(self) -> None:
        self.svc = ZeroConfigService()

    @pytest.mark.asyncio
    async def test_prepare_with_mock_text_processor(self) -> None:
        mod = _mock_text_processor_module(entities=["HSI", "CCL"])
        with patch.dict(sys.modules, {"backend.app.services.text_processor": mod}):
            result = await self.svc.prepare("香港樓市分析")

        assert result.domain_pack_id == "hk_city"
        assert result.agent_count == 100
        assert result.round_count == 10
        assert result.preset_name == "fast"
        assert result.seed_text == "香港樓市分析"
        assert result.detected_entities == ["HSI", "CCL"]
        assert result.estimated_duration_seconds == 20

    @pytest.mark.asyncio
    async def test_prepare_without_text_processor(self) -> None:
        with patch.dict(sys.modules, {"backend.app.services.text_processor": None}):
            result = await self.svc.prepare("some text here")

        assert result.detected_entities == []
        assert result.domain_pack_id == "hk_city"

    @pytest.mark.asyncio
    async def test_prepare_empty_text_raises(self) -> None:
        with pytest.raises(ValueError, match="seed_text must not be empty"):
            await self.svc.prepare("")

    @pytest.mark.asyncio
    async def test_prepare_whitespace_only_raises(self) -> None:
        with pytest.raises(ValueError, match="seed_text must not be empty"):
            await self.svc.prepare("   \n\t  ")


# ---------------------------------------------------------------------------
# prepare() domain inference integration
# ---------------------------------------------------------------------------


class TestPrepareDomainIntegration:
    """Verify prepare() delegates domain inference correctly."""

    def setup_method(self) -> None:
        self.svc = ZeroConfigService()

    @pytest.mark.asyncio
    async def test_prepare_us_markets_domain(self) -> None:
        with patch.dict(sys.modules, {"backend.app.services.text_processor": None}):
            result = await self.svc.prepare("Nasdaq and S&P 500 after Fed decision")
        assert result.domain_pack_id == "us_markets"

    @pytest.mark.asyncio
    async def test_prepare_real_estate_domain(self) -> None:
        with patch.dict(sys.modules, {"backend.app.services.text_processor": None}):
            result = await self.svc.prepare("Mortgage rates and housing market CCL index")
        assert result.domain_pack_id == "real_estate"

    @pytest.mark.asyncio
    async def test_prepare_default_domain_for_ambiguous(self) -> None:
        with patch.dict(sys.modules, {"backend.app.services.text_processor": None}):
            result = await self.svc.prepare("random unmatched words 12345")
        assert result.domain_pack_id == "hk_city"


# ---------------------------------------------------------------------------
# Quick-start endpoint tests (mocked)
# ---------------------------------------------------------------------------


class TestQuickStartEndpoint:
    """Test the POST /simulation/quick-start endpoint handler."""

    @pytest.mark.asyncio
    async def test_quick_start_success(self) -> None:
        from backend.app.api.simulation import quick_start

        mock_zc_result = ZeroConfigResult(
            domain_pack_id="hk_city",
            agent_count=100,
            round_count=10,
            preset_name="fast",
            seed_text="香港樓市",
            detected_entities=["HSI"],
            estimated_duration_seconds=20,
        )

        mock_zc = MagicMock()
        mock_zc.prepare = AsyncMock(return_value=mock_zc_result)

        mock_graph_builder = MagicMock()
        mock_graph_builder.build_graph = AsyncMock(return_value={"graph_id": "g_123"})

        mock_manager = MagicMock()
        mock_manager.create_session = AsyncMock(return_value={"session_id": "sess_1"})
        mock_manager.start_session = AsyncMock()

        mock_factory = MagicMock()
        mock_factory.generate_population = MagicMock(return_value=[])

        mock_macro = MagicMock()
        mock_macro.get_baseline_for_scenario = AsyncMock(return_value=MagicMock())

        mock_profile_gen = MagicMock()
        mock_profile_gen.to_oasis_csv = MagicMock(return_value="header\n")

        with (
            patch("backend.app.api.simulation.ZeroConfigService", return_value=mock_zc, create=True),
            patch("backend.app.api.simulation.GraphBuilderService", return_value=mock_graph_builder, create=True),
            patch("backend.app.api.simulation.SimulationManager", return_value=mock_manager),
            patch("backend.app.api.simulation.AgentFactory", return_value=mock_factory),
            patch("backend.app.api.simulation.MacroController", return_value=mock_macro),
            patch("backend.app.api.simulation.ProfileGenerator", return_value=mock_profile_gen),
            patch("backend.app.api.simulation.store_agent_profiles", new_callable=AsyncMock),
            patch("backend.app.api.simulation.store_activity_profiles", new_callable=AsyncMock),
            patch("asyncio.to_thread", new_callable=AsyncMock),
            patch("asyncio.create_task"),
        ):
            resp = await quick_start({"seed_text": "香港樓市"})

        assert resp.success is True
        assert resp.data["session_id"] == "sess_1"
        assert resp.data["domain_pack_id"] == "hk_city"

    @pytest.mark.asyncio
    async def test_quick_start_empty_seed_raises_400(self) -> None:
        from fastapi import HTTPException

        from backend.app.api.simulation import quick_start

        with pytest.raises(HTTPException) as exc_info:
            await quick_start({"seed_text": ""})
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_quick_start_missing_seed_raises_400(self) -> None:
        from fastapi import HTTPException

        from backend.app.api.simulation import quick_start

        with pytest.raises(HTTPException) as exc_info:
            await quick_start({})
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases for zero-config service."""

    def setup_method(self) -> None:
        self.svc = ZeroConfigService()

    @pytest.mark.asyncio
    async def test_very_long_text(self) -> None:
        long_text = "香港樓市 " * 5000
        with patch.dict(sys.modules, {"backend.app.services.text_processor": None}):
            result = await self.svc.prepare(long_text)
        assert result.domain_pack_id == "hk_city"
        assert result.agent_count == 100

    @pytest.mark.asyncio
    async def test_special_characters(self) -> None:
        text = "香港!@#$%^&*() property <script>alert('xss')</script>"
        with patch.dict(sys.modules, {"backend.app.services.text_processor": None}):
            result = await self.svc.prepare(text)
        assert result.domain_pack_id == "hk_city"

    @pytest.mark.asyncio
    async def test_unicode_emoji_text(self) -> None:
        text = "Nasdaq Fed inflation"
        with patch.dict(sys.modules, {"backend.app.services.text_processor": None}):
            result = await self.svc.prepare(text)
        assert result.domain_pack_id == "us_markets"

    def test_infer_domain_preserves_service_state(self) -> None:
        """Calling infer_domain should not mutate service internals."""
        result1 = self.svc.infer_domain("Nasdaq fed")
        result2 = self.svc.infer_domain("香港樓市")
        assert result1 == "us_markets"
        assert result2 == "hk_city"

    @pytest.mark.asyncio
    async def test_entities_capped_at_10(self) -> None:
        many_entities = [f"entity_{i}" for i in range(20)]
        mod = _mock_text_processor_module(entities=many_entities)
        with patch.dict(sys.modules, {"backend.app.services.text_processor": mod}):
            result = await self.svc.prepare("香港 test text")
        assert len(result.detected_entities) == 10

    @pytest.mark.asyncio
    async def test_text_processor_returns_non_dict(self) -> None:
        """TextProcessor returning unexpected type should not crash."""
        mock_tp_instance = MagicMock()
        mock_tp_instance.analyze_seed = AsyncMock(return_value="unexpected string")
        mod = MagicMock()
        mod.TextProcessor = MagicMock(return_value=mock_tp_instance)
        with patch.dict(sys.modules, {"backend.app.services.text_processor": mod}):
            result = await self.svc.prepare("some text")
        assert result.detected_entities == []


# ---------------------------------------------------------------------------
# detect_mode_async() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_mode_harry_potter_returns_kg_driven():
    """Harry Potter seed → kg_driven even with no geopolitical keywords."""
    svc = ZeroConfigService()
    with patch.object(svc, "_llm_detect_mode", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = "kg_driven"
        result = await svc.detect_mode_async("Dumbledore faces Voldemort at Hogwarts.")
    assert result == "kg_driven"


@pytest.mark.asyncio
async def test_detect_mode_hk_fast_path_skips_llm():
    """HK keywords → hk_demographic without LLM call."""
    svc = ZeroConfigService()
    with patch.object(svc, "_llm_detect_mode", new_callable=AsyncMock) as mock_llm:
        result = await svc.detect_mode_async("香港樓市最新數據顯示CCL指數下跌。")
    mock_llm.assert_not_called()
    assert result == "hk_demographic"
