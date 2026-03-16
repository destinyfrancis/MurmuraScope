"""Tests for US Markets and Global Macro domain packs."""

from __future__ import annotations

import pytest

# Trigger registration
import backend.app.domain.us_markets  # noqa: F401
import backend.app.domain.global_macro  # noqa: F401

from backend.app.domain.base import DomainPackRegistry
from backend.app.domain.us_markets import US_MARKETS_PACK, US_DEMOGRAPHICS
from backend.app.domain.global_macro import GLOBAL_MACRO_PACK
from backend.app.services.generic_macro import GenericMacroState


# ---------------------------------------------------------------------------
# US Markets pack: registration
# ---------------------------------------------------------------------------


class TestUSMarketsPackRegistration:
    def test_us_markets_registered(self) -> None:
        packs = DomainPackRegistry.list_packs()
        assert "us_markets" in packs

    def test_us_markets_retrievable(self) -> None:
        pack = DomainPackRegistry.get("us_markets")
        assert pack.id == "us_markets"

    def test_us_markets_locale(self) -> None:
        pack = DomainPackRegistry.get("us_markets")
        assert pack.locale == "en-US"

    def test_us_markets_names(self) -> None:
        pack = DomainPackRegistry.get("us_markets")
        assert pack.name_en == "US Markets"
        assert pack.name_zh == "美國市場"


# ---------------------------------------------------------------------------
# US Markets pack: shock types
# ---------------------------------------------------------------------------


class TestUSMarketsShocks:
    def test_shock_count(self) -> None:
        pack = DomainPackRegistry.get("us_markets")
        assert len(pack.shock_specs) == 8

    def test_fed_rate_hike_present(self) -> None:
        pack = DomainPackRegistry.get("us_markets")
        ids = {s.id for s in pack.shock_specs}
        assert "fed_rate_hike" in ids
        assert "fed_rate_cut" in ids

    def test_valid_shock_types_match_specs(self) -> None:
        pack = DomainPackRegistry.get("us_markets")
        spec_ids = {s.id for s in pack.shock_specs}
        assert pack.valid_shock_types == spec_ids

    def test_shock_spec_fields(self) -> None:
        pack = DomainPackRegistry.get("us_markets")
        for spec in pack.shock_specs:
            assert spec.id
            assert spec.label_zh
            assert spec.label_en


# ---------------------------------------------------------------------------
# US Markets pack: metrics
# ---------------------------------------------------------------------------


class TestUSMarketsMetrics:
    def test_metric_count(self) -> None:
        pack = DomainPackRegistry.get("us_markets")
        assert len(pack.metrics) == 8

    def test_spx_metric_present(self) -> None:
        pack = DomainPackRegistry.get("us_markets")
        names = {m.name for m in pack.metrics}
        assert "spx_close" in names
        assert "ndx_close" in names
        assert "vix_close" in names

    def test_default_forecast_metrics_nonempty(self) -> None:
        pack = DomainPackRegistry.get("us_markets")
        assert len(pack.default_forecast_metrics) > 0

    def test_correlated_vars_subset_of_metrics(self) -> None:
        pack = DomainPackRegistry.get("us_markets")
        metric_names = {m.name for m in pack.metrics}
        for var in pack.correlated_vars:
            assert var in metric_names, f"{var} not in metrics"


# ---------------------------------------------------------------------------
# US Markets pack: demographics
# ---------------------------------------------------------------------------


class TestUSMarketsDemographics:
    def test_demographics_not_none(self) -> None:
        pack = DomainPackRegistry.get("us_markets")
        assert pack.demographics is not None

    def test_region_weights_sum_to_one(self) -> None:
        d = US_DEMOGRAPHICS
        total = sum(d.regions.values())
        assert abs(total - 1.0) < 1e-9

    def test_occupation_weights_sum_to_one(self) -> None:
        d = US_DEMOGRAPHICS
        total = sum(d.occupations.values())
        assert abs(total - 1.0) < 1e-9

    def test_currency_is_usd(self) -> None:
        d = US_DEMOGRAPHICS
        assert d.currency_code == "USD"
        assert d.currency_symbol == "$"

    def test_housing_types_sum_to_one(self) -> None:
        d = US_DEMOGRAPHICS
        total = sum(d.housing_types.values())
        assert abs(total - 1.0) < 1e-9

    def test_income_by_occupation_keys_match_occupations(self) -> None:
        d = US_DEMOGRAPHICS
        assert set(d.income_by_occupation.keys()) == set(d.occupations.keys())

    def test_surnames_nonempty(self) -> None:
        d = US_DEMOGRAPHICS
        assert len(d.surnames) > 0

    def test_username_parts_nonempty(self) -> None:
        d = US_DEMOGRAPHICS
        assert len(d.username_parts) > 0


# ---------------------------------------------------------------------------
# US Markets pack: macro fields
# ---------------------------------------------------------------------------


class TestUSMarketsMacroFields:
    def test_macro_fields_nonempty(self) -> None:
        pack = DomainPackRegistry.get("us_markets")
        assert len(pack.macro_fields) > 0

    def test_spx_level_field_present(self) -> None:
        pack = DomainPackRegistry.get("us_markets")
        names = {f.name for f in pack.macro_fields}
        assert "spx_level" in names

    def test_macro_field_defaults_are_positive(self) -> None:
        pack = DomainPackRegistry.get("us_markets")
        for f in pack.macro_fields:
            assert f.default_value >= 0, f"{f.name} has negative default"


# ---------------------------------------------------------------------------
# US Markets pack: scenarios
# ---------------------------------------------------------------------------


class TestUSMarketsScenarios:
    def test_scenarios_nonempty(self) -> None:
        pack = DomainPackRegistry.get("us_markets")
        assert len(pack.scenarios) >= 4

    def test_scenario_has_required_keys(self) -> None:
        pack = DomainPackRegistry.get("us_markets")
        for scenario in pack.scenarios:
            assert "key" in scenario
            assert "title_en" in scenario


# ---------------------------------------------------------------------------
# US Markets pack: prompt locale + sentiment
# ---------------------------------------------------------------------------


class TestUSMarketsLocale:
    def test_prompt_locale_not_none(self) -> None:
        pack = DomainPackRegistry.get("us_markets")
        assert pack.prompt_locale is not None

    def test_prompt_locale_is_en_us(self) -> None:
        pack = DomainPackRegistry.get("us_markets")
        assert pack.prompt_locale.language_code == "en-US"  # type: ignore[union-attr]

    def test_sentiment_lexicon_not_none(self) -> None:
        pack = DomainPackRegistry.get("us_markets")
        assert pack.sentiment_lexicon is not None

    def test_sentiment_positive_keywords(self) -> None:
        pack = DomainPackRegistry.get("us_markets")
        lexicon = pack.sentiment_lexicon
        assert "bullish" in lexicon.positive_keywords  # type: ignore[operator]

    def test_sentiment_negative_keywords(self) -> None:
        pack = DomainPackRegistry.get("us_markets")
        lexicon = pack.sentiment_lexicon
        assert "bearish" in lexicon.negative_keywords  # type: ignore[operator]


# ---------------------------------------------------------------------------
# Global Macro pack: basic tests
# ---------------------------------------------------------------------------


class TestGlobalMacroPackRegistration:
    def test_global_macro_registered(self) -> None:
        packs = DomainPackRegistry.list_packs()
        assert "global_macro" in packs

    def test_global_macro_locale(self) -> None:
        pack = DomainPackRegistry.get("global_macro")
        assert pack.locale == "en-US"

    def test_global_macro_shocks(self) -> None:
        pack = DomainPackRegistry.get("global_macro")
        ids = {s.id for s in pack.shock_specs}
        assert "oil_shock" in ids
        assert "trade_war_escalation" in ids
        assert "central_bank_pivot" in ids

    def test_global_macro_metrics(self) -> None:
        pack = DomainPackRegistry.get("global_macro")
        names = {m.name for m in pack.metrics}
        assert "oil_price" in names
        assert "gold_price" in names
        assert "usd_index" in names

    def test_global_macro_scenarios_count(self) -> None:
        pack = DomainPackRegistry.get("global_macro")
        assert len(pack.scenarios) >= 4

    def test_global_macro_demographics_not_none(self) -> None:
        pack = DomainPackRegistry.get("global_macro")
        assert pack.demographics is not None


# ---------------------------------------------------------------------------
# GenericMacroState
# ---------------------------------------------------------------------------


class TestGenericMacroState:
    def test_from_macro_fields_us(self) -> None:
        pack = DomainPackRegistry.get("us_markets")
        state = GenericMacroState.from_macro_fields(pack.macro_fields, round_number=0)
        assert state.round_number == 0
        assert len(state.fields) == len(pack.macro_fields)

    def test_default_values_match_specs(self) -> None:
        pack = DomainPackRegistry.get("us_markets")
        state = GenericMacroState.from_macro_fields(pack.macro_fields)
        for spec in pack.macro_fields:
            assert state.get(spec.name) == spec.default_value

    def test_get_missing_key_returns_default(self) -> None:
        state = GenericMacroState(fields={"spx_level": 5200.0})
        assert state.get("nonexistent", 99.0) == 99.0

    def test_with_update_immutable(self) -> None:
        original = GenericMacroState(fields={"spx_level": 5200.0}, round_number=1)
        updated = original.with_update(spx_level=5300.0)
        # Original unchanged
        assert original.get("spx_level") == 5200.0
        assert updated.get("spx_level") == 5300.0

    def test_with_round_immutable(self) -> None:
        original = GenericMacroState(fields={}, round_number=3)
        advanced = original.with_round(7)
        assert original.round_number == 3
        assert advanced.round_number == 7

    def test_to_dict_includes_round(self) -> None:
        state = GenericMacroState(fields={"gold_price": 2050.0}, round_number=5)
        d = state.to_dict()
        assert d["round_number"] == 5
        assert d["gold_price"] == 2050.0

    def test_from_dict_roundtrip(self) -> None:
        original = GenericMacroState(
            fields={"oil_price": 80.0, "gold_price": 2050.0},
            round_number=3,
        )
        as_dict = original.to_dict()
        restored = GenericMacroState.from_dict(as_dict)
        assert restored.round_number == 3
        assert restored.get("oil_price") == 80.0
        assert restored.get("gold_price") == 2050.0

    def test_to_prompt_context_contains_round(self) -> None:
        state = GenericMacroState(fields={"vix_level": 18.0}, round_number=4)
        ctx = state.to_prompt_context()
        assert "Round 4" in ctx
        assert "vix_level" in ctx

    def test_to_brief_context_alias(self) -> None:
        state = GenericMacroState(fields={"fed_funds_rate": 5.25}, round_number=2)
        assert state.to_brief_context() == state.to_prompt_context()

    def test_from_macro_fields_global(self) -> None:
        pack = DomainPackRegistry.get("global_macro")
        state = GenericMacroState.from_macro_fields(pack.macro_fields, round_number=10)
        assert state.round_number == 10
        # Check a known field
        assert state.get("oil_price") > 0
