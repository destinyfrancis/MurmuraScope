"""Tests for session_key_store.py — BYOK encrypted key storage."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest

# Ensure a test encryption key is set before importing
os.environ.setdefault("SESSION_ENCRYPTION_KEY", "")


class TestSessionKeyStore:
    """Test SessionKeyStore encrypt/decrypt/delete lifecycle."""

    @pytest.fixture(autouse=True)
    def _setup_encryption_key(self, monkeypatch):
        """Set a valid Fernet key for tests."""
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode()
        monkeypatch.setenv("SESSION_ENCRYPTION_KEY", key)

    @pytest.fixture
    def _mock_db(self, tmp_path):
        """Create a temporary SQLite database with session_api_keys table."""
        db_path = str(tmp_path / "test.db")

        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE session_api_keys ("
            "  session_id TEXT PRIMARY KEY,"
            "  encrypted_key BLOB NOT NULL,"
            "  provider TEXT NOT NULL,"
            "  model TEXT,"
            "  base_url TEXT,"
            "  created_at TEXT DEFAULT (datetime('now'))"
            ")"
        )
        conn.commit()
        conn.close()
        return db_path

    @pytest.mark.asyncio
    async def test_store_and_retrieve_key(self, _mock_db):
        """Store a key and retrieve it — should round-trip correctly."""
        from backend.app.services.session_key_store import SessionKeyStore

        store = SessionKeyStore()

        with patch("backend.app.services.session_key_store.get_db") as mock_get_db:
            db = await aiosqlite.connect(_mock_db)
            db.row_factory = aiosqlite.Row

            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=db)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            await store.store_key("sess-1", "sk-test-key-123", "openrouter", "gpt-4o", "https://api.example.com/v1")
            await db.close()

            # Retrieve
            db2 = await aiosqlite.connect(_mock_db)
            db2.row_factory = aiosqlite.Row
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=db2)

            result = await store.retrieve_key("sess-1")
            await db2.close()

        assert result is not None
        assert result.api_key == "sk-test-key-123"
        assert result.provider == "openrouter"
        assert result.model == "gpt-4o"
        assert result.base_url == "https://api.example.com/v1"

    @pytest.mark.asyncio
    async def test_retrieve_nonexistent_key(self, _mock_db):
        """Retrieving a key for a session that doesn't exist returns None."""
        from backend.app.services.session_key_store import SessionKeyStore

        store = SessionKeyStore()

        with patch("backend.app.services.session_key_store.get_db") as mock_get_db:
            db = await aiosqlite.connect(_mock_db)
            db.row_factory = aiosqlite.Row
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=db)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await store.retrieve_key("nonexistent-session")
            await db.close()

        assert result is None

    @pytest.mark.asyncio
    async def test_delete_key(self, _mock_db):
        """Delete a stored key — retrieve should return None afterwards."""
        from backend.app.services.session_key_store import SessionKeyStore

        store = SessionKeyStore()

        with patch("backend.app.services.session_key_store.get_db") as mock_get_db:
            db = await aiosqlite.connect(_mock_db)
            db.row_factory = aiosqlite.Row
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=db)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            await store.store_key("sess-del", "key-to-delete", "fireworks")
            await store.delete_key("sess-del")
            result = await store.retrieve_key("sess-del")
            await db.close()

        assert result is None

    def test_session_key_info_frozen(self):
        """SessionKeyInfo should be immutable."""
        from backend.app.services.session_key_store import SessionKeyInfo

        info = SessionKeyInfo(api_key="k", provider="p", model="m", base_url="u")
        with pytest.raises(AttributeError):
            info.api_key = "new"  # type: ignore[misc]

    @pytest.mark.asyncio
    async def test_store_key_upserts(self, _mock_db):
        """Storing a key for the same session should update, not fail."""
        from backend.app.services.session_key_store import SessionKeyStore

        store = SessionKeyStore()

        with patch("backend.app.services.session_key_store.get_db") as mock_get_db:
            db = await aiosqlite.connect(_mock_db)
            db.row_factory = aiosqlite.Row
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=db)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            await store.store_key("sess-up", "key-v1", "openrouter")
            await store.store_key("sess-up", "key-v2", "fireworks", "model-2")

            result = await store.retrieve_key("sess-up")
            await db.close()

        assert result is not None
        assert result.api_key == "key-v2"
        assert result.provider == "fireworks"
        assert result.model == "model-2"


class TestCostEstimator:
    """Test cost estimation logic."""

    def test_estimate_cost_openrouter(self):
        from backend.app.services.cost_estimator import estimate_cost

        result = estimate_cost("openrouter", None, 300, 20)
        assert result.provider == "openrouter"
        assert result.agent_count == 300
        assert result.round_count == 20
        assert result.estimated_cost_usd > 0
        assert result.estimated_input_tokens == 300 * 20 * 800
        assert result.estimated_output_tokens == 300 * 20 * 200

    def test_estimate_cost_fireworks(self):
        from backend.app.services.cost_estimator import estimate_cost

        result = estimate_cost("fireworks", "deepseek-v3", 100, 10)
        assert result.provider == "fireworks"
        assert result.model == "deepseek-v3"
        assert result.estimated_cost_usd >= 0

    def test_estimate_cost_vllm_free(self):
        from backend.app.services.cost_estimator import estimate_cost

        result = estimate_cost("vllm", None, 500, 30)
        assert result.estimated_cost_usd == 0.0

    def test_estimate_cost_unknown_provider_fallback(self):
        from backend.app.services.cost_estimator import estimate_cost

        result = estimate_cost("unknown_provider", None, 100, 10)
        # Should fallback to openrouter pricing
        assert result.estimated_cost_usd > 0

    def test_cost_breakdown_frozen(self):
        from backend.app.services.cost_estimator import CostBreakdown

        breakdown = CostBreakdown(
            provider="test",
            model="m",
            agent_count=10,
            round_count=5,
            estimated_input_tokens=100,
            estimated_output_tokens=50,
            estimated_cost_usd=0.01,
        )
        with pytest.raises(AttributeError):
            breakdown.provider = "new"  # type: ignore[misc]

    def test_estimate_cost_large_scale(self):
        from backend.app.services.cost_estimator import estimate_cost

        result = estimate_cost("openrouter", None, 10000, 30)
        # Should handle large agent counts without error
        assert result.estimated_input_tokens == 10000 * 30 * 800
        assert result.estimated_cost_usd > 0


class TestSimulationConfig:
    """Test HookConfig.scaled() and SimPreset.custom()."""

    def test_hook_config_scaled_small(self):
        from backend.app.models.simulation_config import HookConfig

        config = HookConfig.scaled(100)
        assert config.decision_cap == 25  # max(25, 100//20=5) = 25
        assert config.llm_concurrency == 20  # min(100, max(10, 100//5=20))
        assert config.emergence_enabled is True

    def test_hook_config_scaled_large(self):
        from backend.app.models.simulation_config import HookConfig

        config = HookConfig.scaled(3000)
        assert config.decision_cap == 150  # max(25, 3000//20)
        assert config.llm_concurrency == 100  # min(100, 3000//5=600)
        assert config.emergence_enabled is True

    def test_hook_config_scaled_massive(self):
        from backend.app.models.simulation_config import HookConfig

        config = HookConfig.scaled(10000)
        assert config.emergence_enabled is True  # Fixed: emergence now enabled at all scales
        assert config.echo_chamber_interval == 10

    def test_sim_preset_custom(self):
        from backend.app.models.simulation_config import SimPreset

        preset = SimPreset.custom(2000, 25, 150)
        assert preset.name == "custom"
        assert preset.agents == 2000
        assert preset.rounds == 25
        assert preset.mc_trials == 150
        assert preset.hook_config.decision_cap == 100

    def test_resolve_preset_standard(self):
        from backend.app.models.simulation_config import resolve_preset

        preset = resolve_preset("standard")
        assert preset.agents == 300
        assert preset.rounds == 20

    def test_resolve_preset_large(self):
        from backend.app.models.simulation_config import resolve_preset

        preset = resolve_preset("large")
        assert preset.agents == 1000
        assert preset.rounds == 25

    def test_resolve_preset_massive(self):
        from backend.app.models.simulation_config import resolve_preset

        preset = resolve_preset("massive")
        assert preset.agents == 3000

    def test_resolve_preset_custom(self):
        from backend.app.models.simulation_config import resolve_preset

        preset = resolve_preset("custom", agent_count=5000, round_count=15)
        assert preset.agents == 5000
        assert preset.rounds == 15
        assert preset.hook_config.emergence_enabled is True

    def test_resolve_preset_custom_too_large(self):
        from backend.app.models.simulation_config import resolve_preset

        with pytest.raises(ValueError, match="50,000"):
            resolve_preset("custom", agent_count=100_000, round_count=10)

    def test_resolve_preset_custom_missing_params(self):
        from backend.app.models.simulation_config import resolve_preset

        with pytest.raises(ValueError, match="requires"):
            resolve_preset("custom")

    def test_resolve_preset_unknown(self):
        from backend.app.models.simulation_config import resolve_preset

        with pytest.raises(ValueError, match="Unknown preset"):
            resolve_preset("nonexistent")

    def test_resolve_preset_none_returns_standard(self):
        from backend.app.models.simulation_config import resolve_preset

        preset = resolve_preset(None)
        assert preset.name == "standard"

    def test_all_presets_in_registry(self):
        from backend.app.models.simulation_config import PRESETS

        assert "fast" in PRESETS
        assert "standard" in PRESETS
        assert "deep" in PRESETS
        assert "large" in PRESETS
        assert "massive" in PRESETS


class TestGeneralizedEngine:
    """Test generalized engine behavior."""

    def test_agent_factory_with_demographics(self):
        """AgentFactory should use demographics when provided."""
        from backend.app.domain.base import DemographicsSpec
        from backend.app.services.agent_factory import AgentFactory

        demographics = DemographicsSpec(
            regions={"Manhattan": 0.5, "Brooklyn": 0.5},
            occupations={"Software Engineer": 0.4, "Teacher": 0.3, "Nurse": 0.3},
            income_by_occupation={
                "Software Engineer": {"median": 120000, "std": 30000, "unemployed_pct": 0.03},
                "Teacher": {"median": 60000, "std": 15000, "unemployed_pct": 0.04},
                "Nurse": {"median": 75000, "std": 20000, "unemployed_pct": 0.02},
            },
            region_income_modifier={"Manhattan": 1.3, "Brooklyn": 1.0},
            education_levels={"High School": 0.3, "Bachelor": 0.5, "Masters": 0.2},
            housing_types={"Apartment": 0.6, "House": 0.4},
            age_brackets={"20-30": 0.3, "30-40": 0.35, "40-50": 0.2, "50-65": 0.15},
            sex_weights={"M": 0.49, "F": 0.51},
            marital_statuses={"Single": 0.45, "Married": 0.45, "Divorced": 0.1},
            surnames=("Smith", "Johnson", "Williams", "Brown"),
            username_parts=("nyc", "bigapple", "metro", "urban"),
            currency_symbol="$",
            currency_code="USD",
        )

        factory = AgentFactory(seed=42, demographics=demographics)
        profiles = factory.generate_population(10)

        assert len(profiles) == 10
        # All agents should use provided regions
        for p in profiles:
            assert p.district in ("Manhattan", "Brooklyn")

    def test_agent_factory_without_demographics_uses_hk(self):
        """AgentFactory without demographics should use HK constants."""
        from backend.app.services.agent_factory import DISTRICT_WEIGHTS, AgentFactory

        factory = AgentFactory(seed=42)
        profiles = factory.generate_population(5)

        assert len(profiles) == 5
        for p in profiles:
            assert p.district in DISTRICT_WEIGHTS

    def test_zero_config_hk_inference(self):
        """ZeroConfigService should infer hk_city for HK text."""
        from backend.app.services.zero_config import ZeroConfigService

        zc = ZeroConfigService()
        assert zc.infer_domain("香港樓市走勢分析") == "hk_city"

    def test_zero_config_us_inference(self):
        """ZeroConfigService should infer us_markets for US text."""
        from backend.app.services.zero_config import ZeroConfigService

        zc = ZeroConfigService()
        assert zc.infer_domain("NASDAQ rally and Fed rate decisions") == "us_markets"

    def test_zero_config_global_inference(self):
        from backend.app.services.zero_config import ZeroConfigService

        zc = ZeroConfigService()
        assert zc.infer_domain("global recession and oil commodity crash") == "global_macro"

    def test_zero_config_fallback_to_hk(self):
        """Unknown text should fall back to hk_city."""
        from backend.app.services.zero_config import ZeroConfigService

        zc = ZeroConfigService()
        assert zc.infer_domain("random unrelated text about cooking") == "hk_city"

    def test_zero_config_community_movement(self):
        from backend.app.services.zero_config import ZeroConfigService

        zc = ZeroConfigService()
        assert zc.infer_domain("社區activism grassroots movement") == "community_movement"

    def test_domain_pack_has_keywords(self):
        """All domain packs should have keywords set."""
        from backend.app.domain.base import DomainPackRegistry

        for pack_id in DomainPackRegistry.list_packs():
            pack = DomainPackRegistry.get(pack_id)
            assert pack.keywords, f"Pack '{pack_id}' has no keywords"

    def test_domain_pack_base_has_new_fields(self):
        """DomainPack should have the new Universal Prediction Engine fields."""
        from backend.app.domain.base import DomainPack

        pack = DomainPack(
            id="test",
            name_zh="測試",
            name_en="Test",
            locale="en",
            valid_shock_types=frozenset(),
            shock_specs=(),
            metrics=(),
            default_forecast_metrics=(),
            correlated_vars=(),
            mc_default_metrics=(),
            keywords=("test", "demo"),
            consensus_weights={"belief": 0.5, "decision": 0.3, "sentiment": 0.2},
        )
        assert pack.keywords == ("test", "demo")
        assert pack.consensus_weights["belief"] == 0.5
        assert pack.retirement_age == 65

    def test_request_model_has_byok_fields(self):
        """SimulationCreateRequest should have BYOK fields."""
        from backend.app.models.request import SimulationCreateRequest

        req = SimulationCreateRequest(
            graph_id="g1",
            scenario_type="property",
            api_key="sk-test",
            llm_model="gpt-4o",
            llm_base_url="https://custom.api.com/v1",
            preset="large",
        )
        assert req.api_key == "sk-test"
        assert req.llm_model == "gpt-4o"
        assert req.llm_base_url == "https://custom.api.com/v1"
        assert req.preset == "large"

    def test_request_model_byok_defaults_none(self):
        """BYOK fields should default to None."""
        from backend.app.models.request import SimulationCreateRequest

        req = SimulationCreateRequest(graph_id="g1", scenario_type="property")
        assert req.api_key is None
        assert req.llm_model is None
        assert req.llm_base_url is None
        assert req.preset is None

    def test_parse_age_bracket_ranges(self):
        """_parse_age_bracket_ranges should parse standard bracket labels."""
        from backend.app.services.agent_factory import _parse_age_bracket_ranges

        brackets = {"20-30": 0.3, "30-40": 0.35, "65+": 0.15}
        ranges = _parse_age_bracket_ranges(brackets)
        assert ranges["20-30"] == (20, 30)
        assert ranges["30-40"] == (30, 40)
        assert ranges["65+"] == (65, 85)

    def test_consensus_estimator_accepts_weights(self):
        """ConsensusEstimator.estimate_probability should accept signal_weights."""
        import inspect

        from backend.app.services.consensus_estimator import ConsensusEstimator

        sig = inspect.signature(ConsensusEstimator.estimate_probability)
        assert "signal_weights" in sig.parameters

    def test_scenario_matcher_accepts_extra_topics(self):
        """ScenarioMatcher should accept extra_topic_groups."""
        from backend.app.services.scenario_matcher import ScenarioMatcher

        matcher = ScenarioMatcher(extra_topic_groups=(("bitcoin", "crypto"),))
        assert matcher._extra_topic_groups == (("bitcoin", "crypto"),)

    def test_llm_client_chat_accepts_api_key(self):
        """LLMClient.chat() should accept api_key and base_url overrides."""
        import inspect

        from backend.app.utils.llm_client import LLMClient

        sig = inspect.signature(LLMClient.chat)
        assert "api_key" in sig.parameters
        assert "base_url" in sig.parameters

    def test_llm_client_chat_batch_accepts_api_key(self):
        """LLMClient.chat_batch() should accept api_key and base_url overrides."""
        import inspect

        from backend.app.utils.llm_client import LLMClient

        sig = inspect.signature(LLMClient.chat_batch)
        assert "api_key" in sig.parameters
        assert "base_url" in sig.parameters
