"""Comprehensive tests for MacroController, MacroState, and shock handlers.

Tests cover:
- MacroState creation and immutability
- apply_overrides
- Shock handlers (interest rate, property crash, unemployment, policy, etc.)
- Second-order effects
- MacroController.apply_shock validation
- Sentiment feedback loop
- Clamping bounds
"""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.services.calibration_config import CalibrationParams, DEFAULT_CALIBRATION
from backend.app.services.macro_controller import MacroController
from backend.app.services.macro_shocks import (
    SHOCK_HANDLERS,
    _apply_second_order,
    _shock_china_slowdown,
    _shock_emigration_wave,
    _shock_fed_rate_cut,
    _shock_fed_rate_hike,
    _shock_interest_rate_hike,
    _shock_market_rally,
    _shock_policy_change,
    _shock_property_crash,
    _shock_tariff_increase,
    _shock_unemployment_spike,
)
from backend.app.services.macro_state import (
    BASELINE_AVG_SQFT_PRICE,
    BASELINE_STAMP_DUTY,
    VALID_SHOCK_TYPES,
    MacroState,
    apply_overrides,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def baseline() -> MacroState:
    """Return a baseline MacroState for testing."""
    return MacroState(
        hibor_1m=0.040,
        prime_rate=0.055,
        unemployment_rate=0.032,
        median_monthly_income=20_800,
        ccl_index=150.0,
        avg_sqft_price=dict(BASELINE_AVG_SQFT_PRICE),
        mortgage_cap=0.70,
        stamp_duty_rates=dict(BASELINE_STAMP_DUTY),
        gdp_growth=0.025,
        cpi_yoy=0.019,
        hsi_level=20_060.0,
        consumer_confidence=45.0,
        net_migration=2_000,
        birth_rate=5.3,
        policy_flags={"辣招撤銷": True},
    )


# ---------------------------------------------------------------------------
# MacroState tests
# ---------------------------------------------------------------------------


class TestMacroState:
    """Tests for MacroState dataclass."""

    def test_frozen_immutable(self, baseline: MacroState) -> None:
        with pytest.raises(AttributeError):
            baseline.hibor_1m = 0.05  # type: ignore[misc]

    def test_to_prompt_context_returns_string(self, baseline: MacroState) -> None:
        ctx = baseline.to_prompt_context()
        assert isinstance(ctx, str)
        assert "HIBOR" in ctx
        assert "恒生指數" in ctx

    def test_to_brief_context_returns_string(self, baseline: MacroState) -> None:
        ctx = baseline.to_brief_context()
        assert isinstance(ctx, str)
        assert "失業率" in ctx

    def test_apply_overrides_returns_new_state(self, baseline: MacroState) -> None:
        new_state = apply_overrides(baseline, {"gdp_growth": 0.03})
        assert new_state.gdp_growth == 0.03
        assert baseline.gdp_growth == 0.025  # original unchanged

    def test_apply_overrides_deep_copies_dicts(self, baseline: MacroState) -> None:
        new_flags = {"test_flag": True}
        new_state = apply_overrides(baseline, {"policy_flags": new_flags})
        # Mutating the input dict should not affect the new state
        new_flags["test_flag"] = False
        assert new_state.policy_flags["test_flag"] is True

    def test_valid_shock_types_is_frozenset(self) -> None:
        assert isinstance(VALID_SHOCK_TYPES, frozenset)
        assert "interest_rate_hike" in VALID_SHOCK_TYPES
        assert len(VALID_SHOCK_TYPES) == 18


# ---------------------------------------------------------------------------
# Shock handler tests
# ---------------------------------------------------------------------------


class TestShockHandlers:
    """Tests for individual shock handler functions."""

    def test_interest_rate_hike_raises_hibor(self, baseline: MacroState) -> None:
        result = _shock_interest_rate_hike(baseline, {"basis_points": 100})
        assert result.hibor_1m > baseline.hibor_1m
        assert result.prime_rate > baseline.prime_rate
        # CCL and HSI should decrease with rate hike
        assert result.ccl_index < baseline.ccl_index
        assert result.hsi_level < baseline.hsi_level

    def test_interest_rate_hike_default_50bps(self, baseline: MacroState) -> None:
        result = _shock_interest_rate_hike(baseline, {})
        expected_delta = 50 / 10_000  # 0.005
        assert abs(result.hibor_1m - (baseline.hibor_1m + expected_delta)) < 0.0001

    def test_property_crash_reduces_ccl(self, baseline: MacroState) -> None:
        result = _shock_property_crash(baseline, {"pct_drop": 0.20})
        assert result.ccl_index < baseline.ccl_index
        assert result.consumer_confidence < baseline.consumer_confidence
        assert result.hsi_level < baseline.hsi_level

    def test_property_crash_reduces_sqft_prices(self, baseline: MacroState) -> None:
        result = _shock_property_crash(baseline, {"pct_drop": 0.30})
        for district in baseline.avg_sqft_price:
            assert result.avg_sqft_price[district] <= baseline.avg_sqft_price[district]

    def test_unemployment_spike(self, baseline: MacroState) -> None:
        result = _shock_unemployment_spike(baseline, {"new_rate": 0.08})
        assert result.unemployment_rate == 0.08
        assert result.consumer_confidence < baseline.consumer_confidence
        assert result.median_monthly_income < baseline.median_monthly_income

    def test_policy_change_updates_flags(self, baseline: MacroState) -> None:
        result = _shock_policy_change(
            baseline, {"new_flags": {"新政策": True}, "mortgage_cap": 0.80}
        )
        assert result.policy_flags["新政策"] is True
        assert result.mortgage_cap == 0.80

    def test_market_rally_boosts_hsi(self, baseline: MacroState) -> None:
        result = _shock_market_rally(baseline, {"hsi_pct_up": 0.15})
        assert result.hsi_level > baseline.hsi_level
        assert result.consumer_confidence > baseline.consumer_confidence
        assert result.ccl_index > baseline.ccl_index

    def test_market_rally_confidence_capped_at_120(self, baseline: MacroState) -> None:
        high_conf = replace(baseline, consumer_confidence=110.0)
        result = _shock_market_rally(high_conf, {"hsi_pct_up": 0.50})
        assert result.consumer_confidence <= 120.0

    def test_emigration_wave_reduces_migration(self, baseline: MacroState) -> None:
        result = _shock_emigration_wave(baseline, {"extra_outflow": 50_000})
        assert result.net_migration < baseline.net_migration
        assert result.net_migration == baseline.net_migration - 50_000

    def test_fed_rate_hike_pass_through(self, baseline: MacroState) -> None:
        result = _shock_fed_rate_hike(baseline, {"basis_points": 25})
        assert result.fed_rate > baseline.fed_rate
        # HIBOR should follow at ~0.85x pass-through
        assert result.hibor_1m > baseline.hibor_1m
        assert result.hsi_level < baseline.hsi_level

    def test_fed_rate_cut_positive_effects(self, baseline: MacroState) -> None:
        result = _shock_fed_rate_cut(baseline, {"basis_points": 25})
        assert result.fed_rate < baseline.fed_rate
        assert result.hsi_level > baseline.hsi_level
        assert result.ccl_index > baseline.ccl_index

    def test_china_slowdown_hits_hsi_and_gdp(self, baseline: MacroState) -> None:
        result = _shock_china_slowdown(baseline, {"gdp_drop": 0.01})
        assert result.china_gdp_growth < baseline.china_gdp_growth
        assert result.hsi_level < baseline.hsi_level
        assert result.northbound_capital_bn < baseline.northbound_capital_bn

    def test_tariff_increase_affects_trade(self, baseline: MacroState) -> None:
        result = _shock_tariff_increase(baseline, {"tariff_delta": 0.10})
        assert result.import_tariff_rate > baseline.import_tariff_rate
        assert result.export_logistics_cost > baseline.export_logistics_cost

    def test_all_shock_types_have_handlers(self) -> None:
        for shock_type in VALID_SHOCK_TYPES:
            assert shock_type in SHOCK_HANDLERS, (
                f"Shock type '{shock_type}' missing from SHOCK_HANDLERS"
            )

    def test_all_handlers_return_new_state(self, baseline: MacroState) -> None:
        for shock_type, handler in SHOCK_HANDLERS.items():
            result = handler(baseline, {})
            assert isinstance(result, MacroState)
            assert result is not baseline


# ---------------------------------------------------------------------------
# Second-order effects
# ---------------------------------------------------------------------------


class TestSecondOrderEffects:
    """Tests for _apply_second_order cascading effects."""

    def test_property_crash_triggers_unemployment_rise(
        self, baseline: MacroState
    ) -> None:
        crashed = replace(
            baseline,
            ccl_index=baseline.ccl_index * 0.80,  # 20% drop
        )
        result = _apply_second_order(baseline, crashed)
        assert result.unemployment_rate > crashed.unemployment_rate

    def test_no_effect_if_no_ccl_drop(self, baseline: MacroState) -> None:
        # No change
        result = _apply_second_order(baseline, baseline)
        assert result.unemployment_rate == baseline.unemployment_rate

    def test_unemployment_triggers_gdp_hit(self, baseline: MacroState) -> None:
        high_unemp = replace(
            baseline,
            unemployment_rate=baseline.unemployment_rate + 0.01,  # +1pp
        )
        result = _apply_second_order(baseline, high_unemp)
        assert result.gdp_growth < high_unemp.gdp_growth


# ---------------------------------------------------------------------------
# MacroController tests
# ---------------------------------------------------------------------------


class TestMacroController:
    """Tests for MacroController class."""

    @pytest.mark.asyncio
    async def test_get_baseline_uses_data_lake(self) -> None:
        with patch(
            "backend.app.services.macro_controller._load_from_data_lake",
            new_callable=AsyncMock,
            return_value={},
        ):
            ctrl = MacroController()
            state = await ctrl.get_baseline()
            assert isinstance(state, MacroState)
            assert state.hibor_1m == 0.040  # default fallback

    @pytest.mark.asyncio
    async def test_get_baseline_applies_db_values(self) -> None:
        with patch(
            "backend.app.services.macro_controller._load_from_data_lake",
            new_callable=AsyncMock,
            return_value={"hibor_1m": 0.050, "unemployment_rate": 0.04},
        ):
            ctrl = MacroController()
            state = await ctrl.get_baseline()
            assert state.hibor_1m == 0.050
            assert state.unemployment_rate == 0.04

    @pytest.mark.asyncio
    async def test_create_scenario_stores_and_retrieves(self) -> None:
        with patch(
            "backend.app.services.macro_controller._load_from_data_lake",
            new_callable=AsyncMock,
            return_value={},
        ):
            ctrl = MacroController()
            scenario = await ctrl.create_scenario("test", {"gdp_growth": 0.05})
            assert scenario.gdp_growth == 0.05
            retrieved = ctrl.get_scenario("test")
            assert retrieved is not None
            assert retrieved.gdp_growth == 0.05

    def test_get_scenario_returns_none_for_unknown(self) -> None:
        ctrl = MacroController()
        assert ctrl.get_scenario("nonexistent") is None

    def test_apply_shock_validates_type(self, baseline: MacroState) -> None:
        ctrl = MacroController()
        with pytest.raises(ValueError, match="Unknown shock type"):
            with patch(
                "backend.app.domain.base.DomainPackRegistry.get",
                side_effect=KeyError("not found"),
            ):
                ctrl.apply_shock(baseline, "invalid_shock", {})

    def test_apply_shock_returns_new_state(self, baseline: MacroState) -> None:
        ctrl = MacroController()
        with patch(
            "backend.app.domain.base.DomainPackRegistry.get",
        ) as mock_get:
            mock_pack = MagicMock()
            mock_pack.valid_shock_types = VALID_SHOCK_TYPES
            mock_get.return_value = mock_pack
            result = ctrl.apply_shock(baseline, "interest_rate_hike", {"basis_points": 50})
        assert isinstance(result, MacroState)
        assert result.hibor_1m > baseline.hibor_1m

    def test_generate_shock_post_validates_type(self, baseline: MacroState) -> None:
        ctrl = MacroController()
        with pytest.raises(ValueError, match="Unknown shock type"):
            ctrl.generate_shock_post("fake_shock", baseline)


# ---------------------------------------------------------------------------
# Sentiment feedback loop tests
# ---------------------------------------------------------------------------


class TestSentimentFeedback:
    """Tests for update_from_actions sentiment-driven macro adjustments."""

    @pytest.mark.asyncio
    async def test_no_actions_returns_unchanged(self, baseline: MacroState) -> None:
        ctrl = MacroController()

        mock_ctx = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])
        mock_ctx.execute = AsyncMock(return_value=mock_cursor)

        with patch(
            "backend.app.utils.db.get_db",
        ) as mock_db:
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch(
                "backend.app.services.macro_controller._load_from_data_lake",
                new_callable=AsyncMock,
                return_value={},
            ):
                result = await ctrl.update_from_actions(baseline, "s1", 5)

        assert result.consumer_confidence == baseline.consumer_confidence

    @pytest.mark.asyncio
    async def test_negative_sentiment_decreases_confidence(
        self, baseline: MacroState
    ) -> None:
        ctrl = MacroController()

        neg_rows = [
            {"sentiment": "negative", "topics": "[]"} for _ in range(8)
        ] + [
            {"sentiment": "positive", "topics": "[]"} for _ in range(2)
        ]

        mock_ctx = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=neg_rows)
        mock_ctx.execute = AsyncMock(return_value=mock_cursor)

        with patch(
            "backend.app.utils.db.get_db",
        ) as mock_db:
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch(
                "backend.app.services.macro_controller._load_from_data_lake",
                new_callable=AsyncMock,
                return_value={},
            ):
                result = await ctrl.update_from_actions(baseline, "s1", 5)

        assert result.consumer_confidence < baseline.consumer_confidence

    @pytest.mark.asyncio
    async def test_emigration_topic_decreases_migration(
        self, baseline: MacroState
    ) -> None:
        ctrl = MacroController()

        rows = [
            {"sentiment": "negative", "topics": '["emigration"]'} for _ in range(5)
        ] + [
            {"sentiment": "neutral", "topics": "[]"} for _ in range(5)
        ]

        mock_ctx = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=rows)
        mock_ctx.execute = AsyncMock(return_value=mock_cursor)

        with patch(
            "backend.app.utils.db.get_db",
        ) as mock_db:
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch(
                "backend.app.services.macro_controller._load_from_data_lake",
                new_callable=AsyncMock,
                return_value={},
            ):
                result = await ctrl.update_from_actions(baseline, "s1", 5)

        assert result.net_migration < baseline.net_migration


# ---------------------------------------------------------------------------
# Clamp bounds tests
# ---------------------------------------------------------------------------


class TestClampBounds:
    """Tests that clamping prevents runaway indicator drift."""

    def test_calibration_params_frozen(self) -> None:
        with pytest.raises(AttributeError):
            DEFAULT_CALIBRATION.neg_threshold = 0.9  # type: ignore[misc]

    def test_calibration_to_dict(self) -> None:
        d = DEFAULT_CALIBRATION.to_dict()
        assert isinstance(d, dict)
        assert "neg_threshold" in d
        assert d["neg_threshold"] == 0.60
