"""Real Estate Market DomainPack for HKSimEngine."""
from __future__ import annotations

from backend.app.domain.base import (
    DomainPack,
    DomainPackRegistry,
    DecisionThresholds,
    MacroImpactDeltas,
    MetricSpec,
    ShockTypeSpec,
)

# ---------------------------------------------------------------------------
# Shock type specs
# ---------------------------------------------------------------------------

_RE_SHOCK_SPECS: tuple[ShockTypeSpec, ...] = (
    ShockTypeSpec("rate_hike", "加息", "Rate Hike"),
    ShockTypeSpec("land_supply_increase", "增加土地供應", "Land Supply Increase"),
    ShockTypeSpec("mortgage_tightening", "收緊按揭", "Mortgage Tightening"),
    ShockTypeSpec("cooling_measure", "樓市辣招", "Cooling Measure"),
    ShockTypeSpec("emigration_wave", "移民潮", "Emigration Wave"),
    ShockTypeSpec("foreign_capital_inflow", "外資湧入", "Foreign Capital Inflow"),
)

_RE_VALID_SHOCK_TYPES: frozenset[str] = frozenset(
    spec.id for spec in _RE_SHOCK_SPECS
)

# ---------------------------------------------------------------------------
# Metric specs
# ---------------------------------------------------------------------------

_RE_METRICS: tuple[MetricSpec, ...] = (
    MetricSpec("property_price_index", "property", "ccl_index", 4),
    MetricSpec("vacancy_rate", "property", "vacancy_rate", 4),
    MetricSpec("transaction_volume", "property", "transaction_volume", 4),
)

_RE_DEFAULT_FORECAST_METRICS: tuple[str, ...] = tuple(
    m.name for m in _RE_METRICS
)

# ---------------------------------------------------------------------------
# Monte Carlo constants
# ---------------------------------------------------------------------------

_RE_CORRELATED_VARS: tuple[str, ...] = (
    "property_price_index",
    "vacancy_rate",
    "transaction_volume",
)

_RE_MC_DEFAULT_METRICS: tuple[str, ...] = (
    "property_price_index",
    "vacancy_rate",
    "transaction_volume",
)

# ---------------------------------------------------------------------------
# Decision thresholds (property-focused overrides)
# ---------------------------------------------------------------------------

_RE_DECISION_THRESHOLDS = DecisionThresholds(
    min_months_down_payment=24,
    stress_test_dti=0.50,
    max_borrower_age_plus_tenor=75,
    emigration_savings_default=350_000,
    invest_min_savings=100_000,
    invest_min_openness=0.40,
    child_min_age=25,
    child_max_age=45,
    child_min_income=20_000,
    job_min_age=22,
    job_max_age=60,
    job_min_extraversion=0.50,
    job_change_unemploy_threshold=0.06,
    spending_adjust_cpi_threshold=0.025,
    spending_adjust_confidence_low=45.0,
    employment_quit_neuroticism=0.6,
    employment_quit_savings_alt=300_000,
    employment_quit_unemploy_cap=0.05,
    employment_strike_stance=0.6,
    employment_strike_confidence=40.0,
    employment_lie_flat_max_age=35,
    employment_lie_flat_min_age=22,
    employment_lie_flat_openness=0.4,
    employment_lie_flat_conscien=0.4,
    employment_sample_rate=0.05,
    employment_max_per_round=30,
    relocate_price_income_ratio=15,
    relocate_school_min_age=30,
    relocate_school_max_age=50,
    relocate_gentrify_income_cap=25_000,
    relocate_gentrify_price_floor=15_000,
    relocate_sample_rate=0.08,
    relocate_max_per_round=40,
)

# ---------------------------------------------------------------------------
# Macro impact deltas
# ---------------------------------------------------------------------------

_RE_MACRO_IMPACT_DELTAS = MacroImpactDeltas(
    buy_property_ccl_delta=0.5,   # Property domain: stronger price feedback
    emigrate_net_mig_delta=-50,
    invest_stocks_hsi_delta=0.0,
    have_child_confidence_delta=0.2,
    adjust_spending_confidence_delta=-0.3,
)

# ---------------------------------------------------------------------------
# Pack construction + registration
# ---------------------------------------------------------------------------

REAL_ESTATE_PACK = DomainPack(
    id="real_estate_market",
    name_zh="房地產市場",
    name_en="Real Estate Market",
    locale="zh-HK",
    valid_shock_types=_RE_VALID_SHOCK_TYPES,
    shock_specs=_RE_SHOCK_SPECS,
    metrics=_RE_METRICS,
    default_forecast_metrics=_RE_DEFAULT_FORECAST_METRICS,
    correlated_vars=_RE_CORRELATED_VARS,
    mc_default_metrics=_RE_MC_DEFAULT_METRICS,
    decision_thresholds=_RE_DECISION_THRESHOLDS,
    macro_impact_deltas=_RE_MACRO_IMPACT_DELTAS,
    keywords=(
        "地產", "real estate", "mortgage", "樓價", "ccl",
        "rent", "housing", "property price",
    ),
)

DomainPackRegistry.register(REAL_ESTATE_PACK)
