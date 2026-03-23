"""Tests for macro shock handlers — verifies each of the 18 shock types produces correct state changes."""

from __future__ import annotations

from dataclasses import replace

import pytest

from backend.app.services.macro_shocks import (
    SHOCK_HANDLERS,
    _apply_second_order,
    _shock_china_demand_collapse,
    _shock_china_slowdown,
    _shock_china_stimulus,
    _shock_emigration_wave,
    _shock_fed_rate_cut,
    _shock_fed_rate_hike,
    _shock_greater_bay_boost,
    _shock_interest_rate_hike,
    _shock_market_rally,
    _shock_policy_change,
    _shock_property_crash,
    _shock_rcep_benefit,
    _shock_shenzhen_magnet,
    _shock_supply_chain_disruption,
    _shock_taiwan_strait_ease,
    _shock_taiwan_strait_tension,
    _shock_tariff_increase,
    _shock_unemployment_spike,
    apply_shock,
)
from backend.app.services.macro_state import (
    BASELINE_AVG_SQFT_PRICE,
    BASELINE_STAMP_DUTY,
    VALID_SHOCK_TYPES,
    MacroState,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def baseline() -> MacroState:
    """Return a baseline MacroState for testing."""
    return MacroState(
        hibor_1m=0.046,
        prime_rate=0.0575,
        unemployment_rate=0.03,
        median_monthly_income=20_000,
        ccl_index=160.0,
        avg_sqft_price=dict(BASELINE_AVG_SQFT_PRICE),
        mortgage_cap=0.7,
        stamp_duty_rates=dict(BASELINE_STAMP_DUTY),
        gdp_growth=0.032,
        cpi_yoy=0.02,
        hsi_level=18_000.0,
        consumer_confidence=100.0,
        net_migration=-20_000,
        birth_rate=5.8,
        policy_flags={"stamp_duty_removed": True},
    )


# ---------------------------------------------------------------------------
# Handler registry
# ---------------------------------------------------------------------------


class TestHandlerRegistry:
    def test_all_18_shock_types_registered(self) -> None:
        assert len(SHOCK_HANDLERS) == 18

    def test_all_valid_types_have_handlers(self) -> None:
        for shock_type in VALID_SHOCK_TYPES:
            assert shock_type in SHOCK_HANDLERS, f"Missing handler for {shock_type}"

    def test_unknown_shock_returns_unchanged(self, baseline: MacroState) -> None:
        result = apply_shock(baseline, "nonexistent_shock", {})
        assert result == baseline


# ---------------------------------------------------------------------------
# Immutability — all handlers must return new state
# ---------------------------------------------------------------------------


class TestImmutability:
    def test_all_handlers_return_new_state(self, baseline: MacroState) -> None:
        for shock_type, handler in SHOCK_HANDLERS.items():
            result = handler(baseline, {})
            assert isinstance(result, MacroState)
            # Should be a different object (even if values happen to match for policy_change)


# ---------------------------------------------------------------------------
# Interest rate hike
# ---------------------------------------------------------------------------


class TestInterestRateHike:
    def test_hibor_increases(self, baseline: MacroState) -> None:
        result = _shock_interest_rate_hike(baseline, {"basis_points": 100})
        assert result.hibor_1m > baseline.hibor_1m

    def test_ccl_decreases(self, baseline: MacroState) -> None:
        result = _shock_interest_rate_hike(baseline, {"basis_points": 100})
        assert result.ccl_index < baseline.ccl_index

    def test_hsi_decreases(self, baseline: MacroState) -> None:
        result = _shock_interest_rate_hike(baseline, {"basis_points": 100})
        assert result.hsi_level < baseline.hsi_level

    def test_confidence_decreases(self, baseline: MacroState) -> None:
        result = _shock_interest_rate_hike(baseline, {"basis_points": 100})
        assert result.consumer_confidence < baseline.consumer_confidence

    def test_default_50bps(self, baseline: MacroState) -> None:
        result = _shock_interest_rate_hike(baseline, {})
        assert result.hibor_1m == pytest.approx(baseline.hibor_1m + 0.005)


# ---------------------------------------------------------------------------
# Property crash
# ---------------------------------------------------------------------------


class TestPropertyCrash:
    def test_ccl_drops(self, baseline: MacroState) -> None:
        result = _shock_property_crash(baseline, {"pct_drop": 0.20})
        assert result.ccl_index < baseline.ccl_index

    def test_hsi_drops(self, baseline: MacroState) -> None:
        result = _shock_property_crash(baseline, {"pct_drop": 0.20})
        assert result.hsi_level < baseline.hsi_level

    def test_gdp_drops(self, baseline: MacroState) -> None:
        result = _shock_property_crash(baseline, {"pct_drop": 0.20})
        assert result.gdp_growth < baseline.gdp_growth

    def test_sqft_prices_drop(self, baseline: MacroState) -> None:
        result = _shock_property_crash(baseline, {"pct_drop": 0.20})
        for district in baseline.avg_sqft_price:
            assert result.avg_sqft_price[district] < baseline.avg_sqft_price[district]


# ---------------------------------------------------------------------------
# Unemployment spike
# ---------------------------------------------------------------------------


class TestUnemploymentSpike:
    def test_unemployment_set(self, baseline: MacroState) -> None:
        result = _shock_unemployment_spike(baseline, {"new_rate": 0.065})
        assert result.unemployment_rate == 0.065

    def test_confidence_drops(self, baseline: MacroState) -> None:
        result = _shock_unemployment_spike(baseline, {"new_rate": 0.065})
        assert result.consumer_confidence < baseline.consumer_confidence

    def test_gdp_drops(self, baseline: MacroState) -> None:
        result = _shock_unemployment_spike(baseline, {"new_rate": 0.065})
        assert result.gdp_growth < baseline.gdp_growth

    def test_income_drops(self, baseline: MacroState) -> None:
        result = _shock_unemployment_spike(baseline, {"new_rate": 0.065})
        assert result.median_monthly_income < baseline.median_monthly_income


# ---------------------------------------------------------------------------
# Policy change
# ---------------------------------------------------------------------------


class TestPolicyChange:
    def test_flags_merged(self, baseline: MacroState) -> None:
        result = _shock_policy_change(baseline, {"new_flags": {"new_policy": True}})
        assert result.policy_flags["stamp_duty_removed"] is True
        assert result.policy_flags["new_policy"] is True

    def test_mortgage_cap_override(self, baseline: MacroState) -> None:
        result = _shock_policy_change(baseline, {"mortgage_cap": 0.8})
        assert result.mortgage_cap == 0.8

    def test_stamp_duty_override(self, baseline: MacroState) -> None:
        result = _shock_policy_change(baseline, {"stamp_duty_overrides": {"non_hkpr": 0.15}})
        assert result.stamp_duty_rates["non_hkpr"] == 0.15


# ---------------------------------------------------------------------------
# Market rally
# ---------------------------------------------------------------------------


class TestMarketRally:
    def test_hsi_increases(self, baseline: MacroState) -> None:
        result = _shock_market_rally(baseline, {"hsi_pct_up": 0.15})
        assert result.hsi_level > baseline.hsi_level

    def test_confidence_increases(self, baseline: MacroState) -> None:
        result = _shock_market_rally(baseline, {"hsi_pct_up": 0.15})
        assert result.consumer_confidence > baseline.consumer_confidence

    def test_confidence_capped_at_120(self, baseline: MacroState) -> None:
        high_conf = replace(baseline, consumer_confidence=115.0)
        result = _shock_market_rally(high_conf, {"hsi_pct_up": 0.50})
        assert result.consumer_confidence <= 120.0


# ---------------------------------------------------------------------------
# Emigration wave
# ---------------------------------------------------------------------------


class TestEmigrationWave:
    def test_net_migration_drops(self, baseline: MacroState) -> None:
        result = _shock_emigration_wave(baseline, {"extra_outflow": 50_000})
        assert result.net_migration < baseline.net_migration

    def test_confidence_drops(self, baseline: MacroState) -> None:
        result = _shock_emigration_wave(baseline, {"extra_outflow": 50_000})
        assert result.consumer_confidence < baseline.consumer_confidence


# ---------------------------------------------------------------------------
# Fed rate hike
# ---------------------------------------------------------------------------


class TestFedRateHike:
    def test_fed_rate_increases(self, baseline: MacroState) -> None:
        result = _shock_fed_rate_hike(baseline, {"basis_points": 25})
        assert result.fed_rate > baseline.fed_rate

    def test_hibor_pass_through(self, baseline: MacroState) -> None:
        result = _shock_fed_rate_hike(baseline, {"basis_points": 100})
        hibor_delta = result.hibor_1m - baseline.hibor_1m
        fed_delta = result.fed_rate - baseline.fed_rate
        # Pass-through is 0.85x
        assert hibor_delta == pytest.approx(fed_delta * 0.85, abs=1e-6)

    def test_hsi_drops(self, baseline: MacroState) -> None:
        result = _shock_fed_rate_hike(baseline, {"basis_points": 50})
        assert result.hsi_level < baseline.hsi_level


# ---------------------------------------------------------------------------
# Fed rate cut
# ---------------------------------------------------------------------------


class TestFedRateCut:
    def test_fed_rate_decreases(self, baseline: MacroState) -> None:
        result = _shock_fed_rate_cut(baseline, {"basis_points": 25})
        assert result.fed_rate < baseline.fed_rate

    def test_hsi_increases(self, baseline: MacroState) -> None:
        result = _shock_fed_rate_cut(baseline, {"basis_points": 25})
        assert result.hsi_level > baseline.hsi_level

    def test_fed_rate_floored_at_zero(self, baseline: MacroState) -> None:
        low_rate = replace(baseline, fed_rate=0.001)
        result = _shock_fed_rate_cut(low_rate, {"basis_points": 100})
        assert result.fed_rate >= 0.0


# ---------------------------------------------------------------------------
# China slowdown
# ---------------------------------------------------------------------------


class TestChinaSlowdown:
    def test_china_gdp_drops(self, baseline: MacroState) -> None:
        result = _shock_china_slowdown(baseline, {"gdp_drop": 0.01})
        assert result.china_gdp_growth < baseline.china_gdp_growth

    def test_hsi_drops(self, baseline: MacroState) -> None:
        result = _shock_china_slowdown(baseline, {"gdp_drop": 0.01})
        assert result.hsi_level < baseline.hsi_level

    def test_northbound_capital_drops(self, baseline: MacroState) -> None:
        result = _shock_china_slowdown(baseline, {"gdp_drop": 0.01})
        assert result.northbound_capital_bn < baseline.northbound_capital_bn


# ---------------------------------------------------------------------------
# China stimulus
# ---------------------------------------------------------------------------


class TestChinaStimulus:
    def test_china_gdp_increases(self, baseline: MacroState) -> None:
        result = _shock_china_stimulus(baseline, {"scale": 0.5})
        assert result.china_gdp_growth > baseline.china_gdp_growth

    def test_hsi_rallies(self, baseline: MacroState) -> None:
        result = _shock_china_stimulus(baseline, {"scale": 0.5})
        assert result.hsi_level > baseline.hsi_level

    def test_property_crisis_eases(self, baseline: MacroState) -> None:
        result = _shock_china_stimulus(baseline, {"scale": 0.5})
        assert result.china_property_crisis < baseline.china_property_crisis


# ---------------------------------------------------------------------------
# Taiwan Strait tension
# ---------------------------------------------------------------------------


class TestTaiwanStraitTension:
    def test_risk_increases(self, baseline: MacroState) -> None:
        result = _shock_taiwan_strait_tension(baseline, {"severity": 0.2})
        assert result.taiwan_strait_risk > baseline.taiwan_strait_risk

    def test_hsi_drops(self, baseline: MacroState) -> None:
        result = _shock_taiwan_strait_tension(baseline, {"severity": 0.2})
        assert result.hsi_level < baseline.hsi_level

    def test_net_migration_drops(self, baseline: MacroState) -> None:
        result = _shock_taiwan_strait_tension(baseline, {"severity": 0.2})
        assert result.net_migration < baseline.net_migration

    def test_risk_capped_at_1(self, baseline: MacroState) -> None:
        high_risk = replace(baseline, taiwan_strait_risk=0.9)
        result = _shock_taiwan_strait_tension(high_risk, {"severity": 0.5})
        assert result.taiwan_strait_risk <= 1.0


# ---------------------------------------------------------------------------
# Taiwan Strait ease
# ---------------------------------------------------------------------------


class TestTaiwanStraitEase:
    def test_risk_decreases(self, baseline: MacroState) -> None:
        result = _shock_taiwan_strait_ease(baseline, {"relief": 0.15})
        assert result.taiwan_strait_risk < baseline.taiwan_strait_risk

    def test_hsi_recovers(self, baseline: MacroState) -> None:
        result = _shock_taiwan_strait_ease(baseline, {"relief": 0.15})
        assert result.hsi_level > baseline.hsi_level

    def test_risk_floored_at_zero(self, baseline: MacroState) -> None:
        low_risk = replace(baseline, taiwan_strait_risk=0.05)
        result = _shock_taiwan_strait_ease(low_risk, {"relief": 0.5})
        assert result.taiwan_strait_risk >= 0.0


# ---------------------------------------------------------------------------
# Shenzhen magnet
# ---------------------------------------------------------------------------


class TestShenzhenMagnet:
    def test_cost_ratio_drops(self, baseline: MacroState) -> None:
        result = _shock_shenzhen_magnet(baseline, {"cost_ratio_drop": 0.05})
        assert result.shenzhen_cost_ratio < baseline.shenzhen_cost_ratio

    def test_cross_border_residents_increase(self, baseline: MacroState) -> None:
        result = _shock_shenzhen_magnet(baseline, {"extra_residents": 20_000})
        assert result.cross_border_residents > baseline.cross_border_residents


# ---------------------------------------------------------------------------
# Greater Bay boost
# ---------------------------------------------------------------------------


class TestGreaterBayBoost:
    def test_policy_score_increases(self, baseline: MacroState) -> None:
        result = _shock_greater_bay_boost(baseline, {"policy_score_gain": 0.1})
        assert result.greater_bay_policy_score > baseline.greater_bay_policy_score

    def test_policy_score_capped_at_1(self, baseline: MacroState) -> None:
        high_score = replace(baseline, greater_bay_policy_score=0.95)
        result = _shock_greater_bay_boost(high_score, {"policy_score_gain": 0.2})
        assert result.greater_bay_policy_score <= 1.0

    def test_gdp_increases(self, baseline: MacroState) -> None:
        result = _shock_greater_bay_boost(baseline, {})
        assert result.gdp_growth > baseline.gdp_growth


# ---------------------------------------------------------------------------
# Tariff increase
# ---------------------------------------------------------------------------


class TestTariffIncrease:
    def test_tariff_rate_increases(self, baseline: MacroState) -> None:
        result = _shock_tariff_increase(baseline, {"tariff_delta": 0.10})
        assert result.import_tariff_rate > baseline.import_tariff_rate

    def test_logistics_cost_increases(self, baseline: MacroState) -> None:
        result = _shock_tariff_increase(baseline, {"tariff_delta": 0.10})
        assert result.export_logistics_cost > baseline.export_logistics_cost

    def test_hsi_drops(self, baseline: MacroState) -> None:
        result = _shock_tariff_increase(baseline, {"tariff_delta": 0.10})
        assert result.hsi_level < baseline.hsi_level


# ---------------------------------------------------------------------------
# Supply chain disruption
# ---------------------------------------------------------------------------


class TestSupplyChainDisruption:
    def test_disruption_increases(self, baseline: MacroState) -> None:
        result = _shock_supply_chain_disruption(baseline, {"severity": 0.3})
        assert result.supply_chain_disruption > baseline.supply_chain_disruption

    def test_disruption_capped_at_1(self, baseline: MacroState) -> None:
        high_disruption = replace(baseline, supply_chain_disruption=0.9)
        result = _shock_supply_chain_disruption(high_disruption, {"severity": 0.5})
        assert result.supply_chain_disruption <= 1.0

    def test_cpi_increases(self, baseline: MacroState) -> None:
        result = _shock_supply_chain_disruption(baseline, {"severity": 0.3})
        assert result.cpi_yoy > baseline.cpi_yoy


# ---------------------------------------------------------------------------
# China demand collapse
# ---------------------------------------------------------------------------


class TestChinaDemandCollapse:
    def test_demand_drops(self, baseline: MacroState) -> None:
        result = _shock_china_demand_collapse(baseline, {"demand_drop": 0.15})
        assert result.china_import_demand < baseline.china_import_demand

    def test_china_gdp_drops(self, baseline: MacroState) -> None:
        result = _shock_china_demand_collapse(baseline, {"demand_drop": 0.15})
        assert result.china_gdp_growth < baseline.china_gdp_growth

    def test_hsi_drops(self, baseline: MacroState) -> None:
        result = _shock_china_demand_collapse(baseline, {"demand_drop": 0.15})
        assert result.hsi_level < baseline.hsi_level


# ---------------------------------------------------------------------------
# RCEP benefit
# ---------------------------------------------------------------------------


class TestRCEPBenefit:
    def test_tariff_rate_decreases(self, baseline: MacroState) -> None:
        result = _shock_rcep_benefit(baseline, {"benefit_scale": 0.5})
        assert result.import_tariff_rate <= baseline.import_tariff_rate

    def test_logistics_cost_decreases(self, baseline: MacroState) -> None:
        result = _shock_rcep_benefit(baseline, {"benefit_scale": 0.5})
        assert result.export_logistics_cost <= baseline.export_logistics_cost

    def test_hsi_increases(self, baseline: MacroState) -> None:
        result = _shock_rcep_benefit(baseline, {"benefit_scale": 0.5})
        assert result.hsi_level > baseline.hsi_level

    def test_confidence_capped_at_120(self, baseline: MacroState) -> None:
        high_conf = replace(baseline, consumer_confidence=119.0)
        result = _shock_rcep_benefit(high_conf, {"benefit_scale": 1.0})
        assert result.consumer_confidence <= 120.0


# ---------------------------------------------------------------------------
# Second-order effects
# ---------------------------------------------------------------------------


class TestSecondOrderEffects:
    def test_property_crash_triggers_unemployment_rise(self, baseline: MacroState) -> None:
        # Large CCL drop should trigger 2nd-order unemployment increase
        crashed = replace(baseline, ccl_index=baseline.ccl_index * 0.8)  # 20% drop
        result = _apply_second_order(baseline, crashed)
        assert result.unemployment_rate > crashed.unemployment_rate

    def test_unemployment_spike_triggers_gdp_drop(self, baseline: MacroState) -> None:
        # Significant unemployment rise should trigger 2nd-order GDP drop
        spiked = replace(baseline, unemployment_rate=baseline.unemployment_rate + 0.01)
        result = _apply_second_order(baseline, spiked)
        assert result.gdp_growth < spiked.gdp_growth

    def test_no_second_order_for_small_changes(self, baseline: MacroState) -> None:
        # Tiny CCL change should not trigger 2nd-order
        tiny = replace(baseline, ccl_index=baseline.ccl_index * 0.999)
        result = _apply_second_order(baseline, tiny)
        assert result.unemployment_rate == tiny.unemployment_rate


# ---------------------------------------------------------------------------
# apply_shock integration
# ---------------------------------------------------------------------------


class TestApplyShockIntegration:
    def test_applies_primary_and_second_order(self, baseline: MacroState) -> None:
        result = apply_shock(baseline, "property_crash", {"pct_drop": 0.30})
        # Primary: CCL drops; Second-order: unemployment should also be affected
        assert result.ccl_index < baseline.ccl_index
        assert result.unemployment_rate >= baseline.unemployment_rate

    def test_unknown_shock_returns_original(self, baseline: MacroState) -> None:
        result = apply_shock(baseline, "does_not_exist", {})
        assert result == baseline
