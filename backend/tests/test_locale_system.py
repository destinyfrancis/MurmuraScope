"""Tests for the locale and sentiment system, including backward compatibility."""

from __future__ import annotations

import pytest

# Ensure all packs are registered
import backend.app.domain.hk_city  # noqa: F401
import backend.app.domain.us_markets  # noqa: F401
import backend.app.domain.global_macro  # noqa: F401

from backend.app.domain.base import (
    DomainPackRegistry,
    PromptLocale,
    SentimentLexicon,
)
from backend.app.domain.locales.zh_hk import ZH_HK_LOCALE, ZH_HK_SENTIMENT
from backend.app.domain.locales.en_us import EN_US_LOCALE, EN_US_SENTIMENT


# ---------------------------------------------------------------------------
# PromptLocale dataclass
# ---------------------------------------------------------------------------


class TestPromptLocaleCreation:
    def test_zh_hk_locale_created(self) -> None:
        assert ZH_HK_LOCALE is not None
        assert ZH_HK_LOCALE.language_code == "zh-HK"

    def test_en_us_locale_created(self) -> None:
        assert EN_US_LOCALE is not None
        assert EN_US_LOCALE.language_code == "en-US"

    def test_prompt_locale_is_frozen(self) -> None:
        import dataclasses
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, TypeError)):
            EN_US_LOCALE.language_code = "fr-FR"  # type: ignore[misc]

    def test_zh_hk_has_personality_descriptions(self) -> None:
        assert "openness" in ZH_HK_LOCALE.personality_descriptions
        assert "conscientiousness" in ZH_HK_LOCALE.personality_descriptions

    def test_en_us_has_personality_descriptions(self) -> None:
        assert "openness" in EN_US_LOCALE.personality_descriptions
        assert "neuroticism" in EN_US_LOCALE.personality_descriptions

    def test_zh_hk_has_posting_guidelines(self) -> None:
        assert len(ZH_HK_LOCALE.posting_guidelines) > 0

    def test_en_us_has_posting_guidelines(self) -> None:
        assert len(EN_US_LOCALE.posting_guidelines) > 0

    def test_zh_hk_housing_context_has_keys(self) -> None:
        assert "公屋" in ZH_HK_LOCALE.housing_context

    def test_en_us_housing_context_has_keys(self) -> None:
        assert "Own" in EN_US_LOCALE.housing_context
        assert "Rent" in EN_US_LOCALE.housing_context

    def test_custom_prompt_locale_construction(self) -> None:
        locale = PromptLocale(
            language_code="fr-FR",
            language_rule="Écrire en français",
            personality_descriptions={"openness": {"high": "curieux"}},
            housing_context={"rent": "vous louez"},
            concern_templates={"low_income": "difficultés financières"},
            posting_guidelines="Postez en français",
        )
        assert locale.language_code == "fr-FR"
        assert locale.language_rule == "Écrire en français"


# ---------------------------------------------------------------------------
# SentimentLexicon
# ---------------------------------------------------------------------------


class TestSentimentLexicon:
    def test_zh_hk_positive_keywords(self) -> None:
        assert "好消息" in ZH_HK_SENTIMENT.positive_keywords
        assert "增長" in ZH_HK_SENTIMENT.positive_keywords

    def test_zh_hk_negative_keywords(self) -> None:
        assert "跌" in ZH_HK_SENTIMENT.negative_keywords
        assert "危機" in ZH_HK_SENTIMENT.negative_keywords

    def test_en_us_positive_keywords(self) -> None:
        assert "bullish" in EN_US_SENTIMENT.positive_keywords
        assert "growth" in EN_US_SENTIMENT.positive_keywords

    def test_en_us_negative_keywords(self) -> None:
        assert "bearish" in EN_US_SENTIMENT.negative_keywords
        assert "recession" in EN_US_SENTIMENT.negative_keywords

    def test_sentiment_lexicon_is_frozen(self) -> None:
        # frozen dataclass — must not allow attribute mutation
        import dataclasses
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, TypeError)):
            EN_US_SENTIMENT.positive_keywords = frozenset()  # type: ignore[misc]

    def test_zh_hk_intensifiers_nonempty(self) -> None:
        assert len(ZH_HK_SENTIMENT.intensifiers) > 0

    def test_en_us_intensifiers_nonempty(self) -> None:
        assert len(EN_US_SENTIMENT.intensifiers) > 0

    def test_zh_hk_particle_modifiers_nonempty(self) -> None:
        assert len(ZH_HK_SENTIMENT.particle_modifiers) > 0

    def test_custom_sentiment_lexicon_creation(self) -> None:
        lexicon = SentimentLexicon(
            positive_keywords=frozenset({"good", "great"}),
            negative_keywords=frozenset({"bad", "terrible"}),
            intensifiers=frozenset({"very", "extremely"}),
        )
        assert "good" in lexicon.positive_keywords
        assert "bad" in lexicon.negative_keywords


# ---------------------------------------------------------------------------
# HK pack backward compatibility
# ---------------------------------------------------------------------------


class TestHKPackBackwardCompat:
    def test_hk_city_still_registered(self) -> None:
        packs = DomainPackRegistry.list_packs()
        assert "hk_city" in packs

    def test_hk_city_has_demographics(self) -> None:
        pack = DomainPackRegistry.get("hk_city")
        assert pack.demographics is not None

    def test_hk_city_has_prompt_locale(self) -> None:
        pack = DomainPackRegistry.get("hk_city")
        assert pack.prompt_locale is not None
        assert pack.prompt_locale.language_code == "zh-HK"

    def test_hk_city_has_sentiment_lexicon(self) -> None:
        pack = DomainPackRegistry.get("hk_city")
        assert pack.sentiment_lexicon is not None

    def test_hk_city_shock_types_preserved(self) -> None:
        pack = DomainPackRegistry.get("hk_city")
        assert "interest_rate_hike" in pack.valid_shock_types
        assert "property_crash" in pack.valid_shock_types

    def test_hk_city_metrics_preserved(self) -> None:
        pack = DomainPackRegistry.get("hk_city")
        names = {m.name for m in pack.metrics}
        assert "ccl_index" in names
        assert "hsi_level" in names

    def test_hk_city_decision_thresholds_accessible(self) -> None:
        pack = DomainPackRegistry.get("hk_city")
        dt = pack.decision_thresholds
        assert dt.min_months_down_payment == 24
        assert dt.stress_test_dti == 0.50

    def test_hk_city_macro_impact_deltas_accessible(self) -> None:
        pack = DomainPackRegistry.get("hk_city")
        d = pack.macro_impact_deltas
        assert d.buy_property_ccl_delta == 0.3

    def test_hk_city_baseline_district_prices_nonempty(self) -> None:
        pack = DomainPackRegistry.get("hk_city")
        assert len(pack.baseline_district_prices) > 0


# ---------------------------------------------------------------------------
# Pack without demographics uses None (no crash)
# ---------------------------------------------------------------------------


class TestPackWithoutDemographics:
    def test_pack_missing_demographics_returns_none(self) -> None:
        """Packs that predate Phase 6 demographics field should have demographics=None."""
        # market_sector and other older packs may not have demographics
        from backend.app.domain.base import DomainPack, DomainPackRegistry, ShockTypeSpec, MetricSpec
        minimal = DomainPack(
            id="_test_minimal",
            name_zh="測試",
            name_en="Test",
            locale="zh-HK",
            valid_shock_types=frozenset({"test_shock"}),
            shock_specs=(ShockTypeSpec("test_shock", "測試", "Test Shock"),),
            metrics=(MetricSpec("test_metric", "test", "test_metric", 4),),
            default_forecast_metrics=("test_metric",),
            correlated_vars=("test_metric",),
            mc_default_metrics=("test_metric",),
            # demographics deliberately omitted → defaults to None
        )
        assert minimal.demographics is None
        assert minimal.prompt_locale is None
        assert minimal.sentiment_lexicon is None
        assert minimal.macro_fields == ()
        assert minimal.scenarios == ()

    def test_pack_without_scenarios_has_empty_tuple(self) -> None:
        pack = DomainPackRegistry.get("hk_city")
        # HK city pack may or may not have scenarios — just verify it doesn't crash
        assert isinstance(pack.scenarios, tuple)


# ---------------------------------------------------------------------------
# Report prompt locale selectors
# ---------------------------------------------------------------------------


class TestReportPromptLocaleSelectors:
    def test_get_react_system_prompt_zh(self) -> None:
        from backend.prompts.report_prompts import get_react_system_prompt, REACT_SYSTEM_PROMPT
        result = get_react_system_prompt("zh-HK")
        assert result == REACT_SYSTEM_PROMPT

    def test_get_react_system_prompt_en(self) -> None:
        from backend.prompts.report_prompts import get_react_system_prompt, REACT_SYSTEM_PROMPT_EN
        result = get_react_system_prompt("en-US")
        assert result == REACT_SYSTEM_PROMPT_EN

    def test_get_react_system_prompt_default_is_zh(self) -> None:
        from backend.prompts.report_prompts import get_react_system_prompt, REACT_SYSTEM_PROMPT
        result = get_react_system_prompt()
        assert result == REACT_SYSTEM_PROMPT

    def test_get_report_generation_prompts_zh(self) -> None:
        from backend.prompts.report_prompts import (
            get_report_generation_prompts,
            REPORT_GENERATION_SYSTEM,
            REPORT_GENERATION_USER,
        )
        system, user = get_report_generation_prompts("zh-HK")
        assert system == REPORT_GENERATION_SYSTEM
        assert user == REPORT_GENERATION_USER

    def test_get_report_generation_prompts_en(self) -> None:
        from backend.prompts.report_prompts import (
            get_report_generation_prompts,
            REPORT_GENERATION_SYSTEM_EN,
            REPORT_GENERATION_USER_EN,
        )
        system, user = get_report_generation_prompts("en-US")
        assert system == REPORT_GENERATION_SYSTEM_EN
        assert user == REPORT_GENERATION_USER_EN


# ---------------------------------------------------------------------------
# Decision prompt locale selectors
# ---------------------------------------------------------------------------


class TestDecisionPromptLocaleSelectors:
    def test_get_deliberation_prompt_function_exists(self) -> None:
        from backend.prompts.decision_prompts import get_deliberation_prompt
        assert callable(get_deliberation_prompt)

    def test_build_deliberation_prompt_en_function_exists(self) -> None:
        from backend.prompts.decision_prompts import build_deliberation_prompt_en
        assert callable(build_deliberation_prompt_en)

    def test_system_prompt_en_exists(self) -> None:
        from backend.prompts.decision_prompts import SYSTEM_PROMPT_EN
        assert len(SYSTEM_PROMPT_EN) > 0

    def test_en_decision_instructions_all_types(self) -> None:
        from backend.prompts.decision_prompts import _DECISION_INSTRUCTIONS_EN
        from backend.app.models.decision import DecisionType
        for dt in DecisionType:
            assert dt in _DECISION_INSTRUCTIONS_EN, f"Missing EN instruction for {dt}"
