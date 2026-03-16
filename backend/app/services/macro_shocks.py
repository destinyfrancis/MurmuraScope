"""Shock handler functions for MacroState — each returns a new MacroState.

Multipliers are sourced from backend.data_pipeline.shock_calibration_data,
which derives values from historical HK crisis episodes (HKMA, C&SD, RVD).
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from backend.data_pipeline.shock_calibration_data import SHOCK_MULTIPLIERS
from backend.app.services.macro_state import (
    MacroState,
    SHOCK_INTEREST_RATE_HIKE,
    SHOCK_PROPERTY_CRASH,
    SHOCK_UNEMPLOYMENT_SPIKE,
    SHOCK_POLICY_CHANGE,
    SHOCK_MARKET_RALLY,
    SHOCK_EMIGRATION_WAVE,
    SHOCK_FED_RATE_HIKE,
    SHOCK_FED_RATE_CUT,
    SHOCK_CHINA_SLOWDOWN,
    SHOCK_CHINA_STIMULUS,
    SHOCK_TAIWAN_STRAIT_TENSION,
    SHOCK_TAIWAN_STRAIT_EASE,
    SHOCK_SHENZHEN_MAGNET,
    SHOCK_GREATER_BAY_BOOST,
    SHOCK_TARIFF_INCREASE,
    SHOCK_SUPPLY_CHAIN_DISRUPTION,
    SHOCK_CHINA_DEMAND_COLLAPSE,
    SHOCK_RCEP_BENEFIT,
)


def _shock_interest_rate_hike(
    state: MacroState, params: dict[str, Any]
) -> MacroState:
    """Simulate HIBOR / prime-rate increase and cascading effects.

    Calibrated from 2022-23 Fed hike cycle (400bp -> CCL -15%, HSI -25%).
    """
    bps = params.get("basis_points", 50)
    delta = bps / 10_000
    units = bps / 100  # number of 100bp units

    mul = SHOCK_MULTIPLIERS["interest_rate_hike"]

    ccl_pct = mul.ccl_per_unit * units / 100  # convert % to fraction
    hsi_pct = mul.hsi_per_unit * units / 100
    conf_pct = mul.confidence_per_unit * units / 100

    new_sqft = {
        district: int(price * (1 + ccl_pct))
        for district, price in state.avg_sqft_price.items()
    }

    return replace(
        state,
        hibor_1m=state.hibor_1m + delta,
        prime_rate=state.prime_rate + delta,
        ccl_index=round(state.ccl_index * (1 + ccl_pct), 1),
        avg_sqft_price=new_sqft,
        consumer_confidence=round(
            state.consumer_confidence * (1 + conf_pct), 1
        ),
        hsi_level=round(state.hsi_level * (1 + hsi_pct), 0),
    )


def _shock_property_crash(
    state: MacroState, params: dict[str, Any]
) -> MacroState:
    """Simulate a property market crash.

    Calibrated from 1997 AFC: 100% severity -> CCL -65%, HSI -40%, GDP -4%.
    pct_drop acts as severity scaler (0.20 = 20% of AFC magnitude).
    """
    pct_drop = params.get("pct_drop", 0.20)

    mul = SHOCK_MULTIPLIERS["property_crash"]
    severity = pct_drop  # 0.20 means 20% of AFC-scale crash

    new_sqft = {
        district: int(price * (1 + mul.ccl_per_unit * severity / 100))
        for district, price in state.avg_sqft_price.items()
    }

    return replace(
        state,
        ccl_index=round(
            state.ccl_index * (1 + mul.ccl_per_unit * severity / 100), 1
        ),
        avg_sqft_price=new_sqft,
        consumer_confidence=round(
            state.consumer_confidence
            * (1 + mul.confidence_per_unit * severity / 100),
            1,
        ),
        hsi_level=round(
            state.hsi_level * (1 + mul.hsi_per_unit * severity / 100), 0
        ),
        gdp_growth=round(
            state.gdp_growth + mul.gdp_per_unit * severity / 100, 3
        ),
    )


def _shock_unemployment_spike(
    state: MacroState, params: dict[str, Any]
) -> MacroState:
    """Simulate a surge in unemployment."""
    new_rate = params.get("new_rate", 0.065)

    return replace(
        state,
        unemployment_rate=new_rate,
        consumer_confidence=round(state.consumer_confidence * 0.80, 1),
        gdp_growth=round(state.gdp_growth - (new_rate - state.unemployment_rate) * 1.2, 3),
        median_monthly_income=int(state.median_monthly_income * 0.95),
    )


def _shock_policy_change(
    state: MacroState, params: dict[str, Any]
) -> MacroState:
    """Simulate a government policy change."""
    new_flags = {**state.policy_flags, **params.get("new_flags", {})}
    new_mortgage_cap = params.get("mortgage_cap", state.mortgage_cap)
    new_stamp_duty = (
        {**state.stamp_duty_rates, **params["stamp_duty_overrides"]}
        if "stamp_duty_overrides" in params
        else dict(state.stamp_duty_rates)
    )

    return replace(
        state,
        policy_flags=new_flags,
        mortgage_cap=new_mortgage_cap,
        stamp_duty_rates=new_stamp_duty,
    )


def _shock_market_rally(
    state: MacroState, params: dict[str, Any]
) -> MacroState:
    """Simulate a broad market rally."""
    hsi_pct_up = params.get("hsi_pct_up", 0.15)

    return replace(
        state,
        hsi_level=round(state.hsi_level * (1 + hsi_pct_up), 0),
        consumer_confidence=round(
            min(state.consumer_confidence * (1 + hsi_pct_up * 0.3), 120.0), 1
        ),
        ccl_index=round(state.ccl_index * (1 + hsi_pct_up * 0.2), 1),
        gdp_growth=round(state.gdp_growth + hsi_pct_up * 0.08, 3),
    )


def _shock_emigration_wave(
    state: MacroState, params: dict[str, Any]
) -> MacroState:
    """Simulate an emigration wave affecting demographics and economy.

    Calibrated from 2020-22 observed: ~100K/yr net outflow.
    extra_outflow=50000 treated as 0.5 unit (vs 100K reference).
    """
    extra_outflow = params.get("extra_outflow", 50_000)

    mul = SHOCK_MULTIPLIERS["emigration_wave"]
    scale = extra_outflow / 100_000  # 100K outflow = 1 unit

    return replace(
        state,
        net_migration=state.net_migration - extra_outflow,
        unemployment_rate=round(
            max(state.unemployment_rate + mul.unemployment_per_unit * scale / 100, 0.01), 3
        ),
        consumer_confidence=round(
            state.consumer_confidence * (1 + mul.confidence_per_unit * scale / 100), 1
        ),
        ccl_index=round(state.ccl_index * (1 + mul.ccl_per_unit * scale / 100), 1),
        gdp_growth=round(state.gdp_growth + mul.gdp_per_unit * scale / 100, 3),
    )


def _shock_fed_rate_hike(state: MacroState, params: dict[str, Any]) -> MacroState:
    """Fed raises rates -> HIBOR follows (HKD peg), property/HSI under pressure.

    Calibrated from 2022-23 cycle. HIBOR pass-through ~0.85x of Fed change.
    """
    bps = params.get("basis_points", 25)
    delta = bps / 10_000
    units = bps / 100  # number of 100bp units

    mul = SHOCK_MULTIPLIERS["fed_rate_hike"]

    ccl_pct = mul.ccl_per_unit * units / 100
    hsi_pct = mul.hsi_per_unit * units / 100
    conf_pct = mul.confidence_per_unit * units / 100

    new_sqft = {d: int(p * (1 + ccl_pct)) for d, p in state.avg_sqft_price.items()}
    return replace(
        state,
        fed_rate=state.fed_rate + delta,
        hibor_1m=state.hibor_1m + delta * 0.85,  # pass-through ratio
        prime_rate=state.prime_rate + delta * 0.8,
        ccl_index=round(state.ccl_index * (1 + ccl_pct), 1),
        avg_sqft_price=new_sqft,
        hsi_level=round(state.hsi_level * (1 + hsi_pct), 0),
        consumer_confidence=round(state.consumer_confidence * (1 + conf_pct), 1),
    )


def _shock_fed_rate_cut(state: MacroState, params: dict[str, Any]) -> MacroState:
    """Fed cuts rates → HIBOR drops, mortgage burden eases, property and HSI rally."""
    bps = params.get("basis_points", 25)
    delta = bps / 10_000
    new_sqft = {d: int(p * (1 + delta * 4)) for d, p in state.avg_sqft_price.items()}
    return replace(
        state,
        fed_rate=max(state.fed_rate - delta, 0.0),
        hibor_1m=max(state.hibor_1m - delta, 0.001),
        prime_rate=max(state.prime_rate - delta * 0.8, 0.01),
        ccl_index=round(state.ccl_index * (1 + delta * 4), 1),
        avg_sqft_price=new_sqft,
        hsi_level=round(state.hsi_level * (1 + delta * 3), 0),
        consumer_confidence=round(min(state.consumer_confidence + bps * 0.04, 120.0), 1),
    )


def _shock_china_slowdown(state: MacroState, params: dict[str, Any]) -> MacroState:
    """China GDP slowdown -> HSI drops, northbound capital retreats, HK GDP hit.

    Calibrated: HK GDP ~60% linked to China trade/services.
    gdp_drop is in fractional form (0.01 = 1pp China GDP decline).
    """
    gdp_drop = params.get("gdp_drop", 0.01)

    mul = SHOCK_MULTIPLIERS["china_slowdown"]
    # Scale multipliers by gdp_drop as fraction of 1pp reference
    scale = gdp_drop / 0.01  # 1pp = 1 unit

    return replace(
        state,
        china_gdp_growth=round(state.china_gdp_growth - gdp_drop, 3),
        china_property_crisis=round(min(state.china_property_crisis + 0.1 * scale, 1.0), 2),
        hsi_level=round(state.hsi_level * (1 + mul.hsi_per_unit * scale / 100), 0),
        northbound_capital_bn=round(state.northbound_capital_bn * (1 - gdp_drop * 3), 1),
        gdp_growth=round(state.gdp_growth + mul.gdp_per_unit * scale / 100, 3),
        consumer_confidence=round(
            state.consumer_confidence * (1 + mul.confidence_per_unit * scale / 100), 1
        ),
    )


def _shock_china_stimulus(state: MacroState, params: dict[str, Any]) -> MacroState:
    """China stimulus → mainland buyers re-enter HK market, HSI rallies."""
    scale = params.get("scale", 0.5)  # 0-1
    new_sqft = {d: int(p * (1 + scale * 0.06)) for d, p in state.avg_sqft_price.items()}
    return replace(
        state,
        china_gdp_growth=round(state.china_gdp_growth + scale * 0.01, 3),
        china_property_crisis=round(max(state.china_property_crisis - scale * 0.15, 0.0), 2),
        hsi_level=round(state.hsi_level * (1 + scale * 0.12), 0),
        northbound_capital_bn=round(state.northbound_capital_bn * (1 + scale * 0.3), 1),
        avg_sqft_price=new_sqft,
        ccl_index=round(state.ccl_index * (1 + scale * 0.04), 1),
        consumer_confidence=round(min(state.consumer_confidence + scale * 5, 120.0), 1),
    )


def _shock_taiwan_strait_tension(
    state: MacroState, params: dict[str, Any]
) -> MacroState:
    """Taiwan Strait tension spikes → risk-off, capital flight, emigration surge."""
    severity = params.get("severity", 0.2)
    extra_outflow = int(30_000 * severity)
    new_sqft = {d: int(p * (1 - severity * 0.08)) for d, p in state.avg_sqft_price.items()}
    return replace(
        state,
        taiwan_strait_risk=round(min(state.taiwan_strait_risk + severity, 1.0), 2),
        hsi_level=round(state.hsi_level * (1 - severity * 0.12), 0),
        avg_sqft_price=new_sqft,
        ccl_index=round(state.ccl_index * (1 - severity * 0.06), 1),
        consumer_confidence=round(state.consumer_confidence * (1 - severity * 0.15), 1),
        net_migration=state.net_migration - extra_outflow,
    )


def _shock_taiwan_strait_ease(
    state: MacroState, params: dict[str, Any]
) -> MacroState:
    """Taiwan Strait tensions ease → risk appetite returns, market recovers."""
    relief = params.get("relief", 0.15)
    return replace(
        state,
        taiwan_strait_risk=round(max(state.taiwan_strait_risk - relief, 0.0), 2),
        hsi_level=round(state.hsi_level * (1 + relief * 0.08), 0),
        ccl_index=round(state.ccl_index * (1 + relief * 0.03), 1),
        consumer_confidence=round(min(state.consumer_confidence * (1 + relief * 0.08), 120.0), 1),
    )


def _shock_shenzhen_magnet(state: MacroState, params: dict[str, Any]) -> MacroState:
    """Shenzhen becomes even more attractive → HKers move north."""
    extra_crossborder = params.get("extra_residents", 20_000)
    cost_drop = params.get("cost_ratio_drop", 0.03)
    new_sqft = {d: int(p * (1 - 0.02)) for d, p in state.avg_sqft_price.items()}
    return replace(
        state,
        shenzhen_cost_ratio=round(max(state.shenzhen_cost_ratio - cost_drop, 0.1), 3),
        cross_border_residents=state.cross_border_residents + extra_crossborder,
        net_migration=state.net_migration - extra_crossborder // 2,
        avg_sqft_price=new_sqft,
        ccl_index=round(state.ccl_index * 0.98, 1),
    )


def _shock_greater_bay_boost(state: MacroState, params: dict[str, Any]) -> MacroState:
    """GBA policy integration accelerates → Northern Metropolis values rise."""
    boost = params.get("policy_score_gain", 0.1)
    yl_premium = params.get("yl_premium", 0.05)
    new_sqft = {
        d: int(p * (1 + yl_premium if d in ("元朗", "北區", "大埔") else p))
        for d, p in state.avg_sqft_price.items()
    }
    return replace(
        state,
        greater_bay_policy_score=round(min(state.greater_bay_policy_score + boost, 1.0), 2),
        cross_border_residents=int(state.cross_border_residents * 1.1),
        avg_sqft_price=new_sqft,
        gdp_growth=round(state.gdp_growth + 0.003, 3),
    )


# ---------------------------------------------------------------------------
# B2B shock handlers (Phase 5)
# ---------------------------------------------------------------------------


def _shock_tariff_increase(state: MacroState, params: dict[str, Any]) -> MacroState:
    """Tariff increase -> export-heavy companies hurt, logistics cost up.

    Calibrated from US-China trade war 2018-19.
    tariff_delta=0.10 (10pp) treated as 1 unit.
    """
    tariff_delta = params.get("tariff_delta", 0.10)

    mul = SHOCK_MULTIPLIERS["tariff_war"]
    scale = tariff_delta / 0.10  # 10pp tariff = 1 unit

    return replace(
        state,
        import_tariff_rate=round(state.import_tariff_rate + tariff_delta, 3),
        export_logistics_cost=round(state.export_logistics_cost * (1 + tariff_delta * 0.3), 3),
        gdp_growth=round(state.gdp_growth + mul.gdp_per_unit * scale / 100, 4),
        hsi_level=round(state.hsi_level * (1 + mul.hsi_per_unit * scale / 100), 0),
        consumer_confidence=round(
            state.consumer_confidence * (1 + mul.confidence_per_unit * scale / 100), 1
        ),
    )


def _shock_supply_chain_disruption(state: MacroState, params: dict[str, Any]) -> MacroState:
    """Supply chain disruption -> logistics cost up, china_exposure companies hurt.

    Calibrated from COVID supply chain 2021-22. severity=1.0 = full unit.
    """
    severity = params.get("severity", 0.3)

    mul = SHOCK_MULTIPLIERS["supply_chain_disruption"]

    return replace(
        state,
        supply_chain_disruption=round(min(state.supply_chain_disruption + severity, 1.0), 2),
        export_logistics_cost=round(state.export_logistics_cost * (1 + severity * 0.5), 3),
        cpi_yoy=round(state.cpi_yoy + severity * 0.01, 4),
        gdp_growth=round(state.gdp_growth + mul.gdp_per_unit * severity / 100, 4),
        hsi_level=round(state.hsi_level * (1 + mul.hsi_per_unit * severity / 100), 0),
        consumer_confidence=round(
            state.consumer_confidence * (1 + mul.confidence_per_unit * severity / 100), 1
        ),
    )


def _shock_china_demand_collapse(state: MacroState, params: dict[str, Any]) -> MacroState:
    """China import demand collapse → export companies revenue drops."""
    demand_drop = params.get("demand_drop", 0.15)
    return replace(
        state,
        china_import_demand=round(state.china_import_demand - demand_drop, 3),
        china_gdp_growth=round(state.china_gdp_growth - demand_drop * 0.3, 3),
        hsi_level=round(state.hsi_level * (1 - demand_drop * 0.1), 0),
        gdp_growth=round(state.gdp_growth - demand_drop * 0.05, 4),
    )


def _shock_rcep_benefit(state: MacroState, params: dict[str, Any]) -> MacroState:
    """RCEP takes effect -> tariffs down, ASEAN trade up.

    Calibrated from RCEP implementation estimates. benefit_scale=1.0 = full unit.
    """
    benefit_scale = params.get("benefit_scale", 0.5)

    mul = SHOCK_MULTIPLIERS["rcep_boost"]

    return replace(
        state,
        import_tariff_rate=round(max(state.import_tariff_rate - benefit_scale * 0.05, 0.0), 3),
        export_logistics_cost=round(
            max(state.export_logistics_cost * (1 - benefit_scale * 0.1), 0.5), 3
        ),
        gdp_growth=round(state.gdp_growth + mul.gdp_per_unit * benefit_scale / 100, 4),
        hsi_level=round(state.hsi_level * (1 + mul.hsi_per_unit * benefit_scale / 100), 0),
        consumer_confidence=round(
            min(
                state.consumer_confidence * (1 + mul.confidence_per_unit * benefit_scale / 100),
                120.0,
            ),
            1,
        ),
    )


# ---------------------------------------------------------------------------
# Second-order effects (1 additional propagation round, no recursion)
# ---------------------------------------------------------------------------

_logger = logging.getLogger(__name__)


def _apply_second_order(
    before: MacroState, after: MacroState
) -> MacroState:
    """Compute second-order cascading effects from primary shock deltas.

    Chain is limited to a single additional pass (no recursion):
      - Property crash -> unemployment rise (+0.5pp per 10% CCL drop) -> confidence drop
      - Unemployment spike -> spending cut -> GDP drop
    Returns a new MacroState with second-order adjustments applied.
    """
    state = after

    # --- Property -> unemployment -> confidence ---
    ccl_before = before.ccl_index
    ccl_after = after.ccl_index
    if ccl_before > 0:
        ccl_drop_pct = (ccl_before - ccl_after) / ccl_before * 100  # positive = drop
        if ccl_drop_pct > 1.0:  # only trigger above 1% drop
            unemp_delta = 0.5 * (ccl_drop_pct / 10.0)  # +0.5pp per 10% crash
            new_unemp = round(min(state.unemployment_rate + unemp_delta / 100, 0.25), 4)
            # Confidence drops 2% per 1pp unemployment rise
            conf_hit = 1.0 - (unemp_delta * 0.02)
            new_conf = round(max(state.consumer_confidence * conf_hit, 10.0), 1)
            state = replace(
                state,
                unemployment_rate=new_unemp,
                consumer_confidence=new_conf,
            )
            _logger.debug(
                "2nd-order property->unemployment: CCL -%.1f%% -> unemp +%.3fpp",
                ccl_drop_pct,
                unemp_delta,
            )

    # --- Unemployment -> spending -> GDP ---
    unemp_delta_pp = (state.unemployment_rate - before.unemployment_rate) * 100
    if unemp_delta_pp > 0.2:  # only trigger above 0.2pp rise
        # Okun's law simplified: 1pp unemployment -> -0.5pp GDP
        gdp_hit = unemp_delta_pp * 0.005
        state = replace(
            state,
            gdp_growth=round(state.gdp_growth - gdp_hit, 4),
        )
        _logger.debug(
            "2nd-order unemployment->GDP: unemp +%.2fpp -> GDP -%.4f",
            unemp_delta_pp,
            gdp_hit,
        )

    return state


def apply_shock(
    state: MacroState,
    shock_type: str,
    params: dict[str, Any],
    active_shocks: tuple[str, ...] = (),
) -> MacroState:
    """Apply a named shock with calibrated multipliers + second-order effects.

    This is the primary entry point for shock application.

    Args:
        state: Current MacroState (immutable).
        shock_type: Identifier of the shock to apply.
        params: Shock-specific parameters dict.
        active_shocks: Other shocks active in the current step, used for
            interaction-term computation.  Defaults to empty tuple for
            backward compatibility.

    Returns:
        New MacroState with primary, nonlinear, and second-order effects applied.
    """
    handler = SHOCK_HANDLERS.get(shock_type)
    if handler is None:
        _logger.warning("Unknown shock type: %s", shock_type)
        return state

    after_primary = handler(state, params)

    # Compute deltas from primary shock for nonlinear modifiers
    from backend.app.services.nonlinear_shocks import apply_nonlinear_shock  # noqa: PLC0415

    base_deltas: dict[str, float] = {}
    for field_name in (
        "hsi_level", "consumer_confidence", "gdp_growth",
        "ccl_index", "unemployment_rate", "net_migration",
    ):
        before_val = getattr(state, field_name, None)
        after_val = getattr(after_primary, field_name, None)
        if before_val is not None and after_val is not None:
            delta = after_val - before_val
            if abs(delta) > 1e-9:
                base_deltas[field_name] = delta

    if base_deltas and active_shocks:
        nonlinear_extras = apply_nonlinear_shock(
            state, shock_type, base_deltas, active_shocks
        )
        # The nonlinear function returns the *full* adjusted deltas;
        # compute the additional increment beyond what primary already applied.
        extra_updates: dict[str, Any] = {}
        for field, adjusted_delta in nonlinear_extras.items():
            original_delta = base_deltas.get(field, 0.0)
            increment = adjusted_delta - original_delta
            if abs(increment) > 1e-9:
                current_val = getattr(after_primary, field, None)
                if current_val is not None and isinstance(current_val, (int, float)):
                    extra_updates[field] = type(current_val)(current_val + increment)
        if extra_updates:
            after_primary = replace(after_primary, **extra_updates)

    return _apply_second_order(state, after_primary)


# ---------------------------------------------------------------------------
# Handler registry
# ---------------------------------------------------------------------------

SHOCK_HANDLERS: dict[str, Any] = {
    SHOCK_INTEREST_RATE_HIKE: _shock_interest_rate_hike,
    SHOCK_PROPERTY_CRASH: _shock_property_crash,
    SHOCK_UNEMPLOYMENT_SPIKE: _shock_unemployment_spike,
    SHOCK_POLICY_CHANGE: _shock_policy_change,
    SHOCK_MARKET_RALLY: _shock_market_rally,
    SHOCK_EMIGRATION_WAVE: _shock_emigration_wave,
    SHOCK_FED_RATE_HIKE: _shock_fed_rate_hike,
    SHOCK_FED_RATE_CUT: _shock_fed_rate_cut,
    SHOCK_CHINA_SLOWDOWN: _shock_china_slowdown,
    SHOCK_CHINA_STIMULUS: _shock_china_stimulus,
    SHOCK_TAIWAN_STRAIT_TENSION: _shock_taiwan_strait_tension,
    SHOCK_TAIWAN_STRAIT_EASE: _shock_taiwan_strait_ease,
    SHOCK_SHENZHEN_MAGNET: _shock_shenzhen_magnet,
    SHOCK_GREATER_BAY_BOOST: _shock_greater_bay_boost,
    SHOCK_TARIFF_INCREASE: _shock_tariff_increase,
    SHOCK_SUPPLY_CHAIN_DISRUPTION: _shock_supply_chain_disruption,
    SHOCK_CHINA_DEMAND_COLLAPSE: _shock_china_demand_collapse,
    SHOCK_RCEP_BENEFIT: _shock_rcep_benefit,
}
