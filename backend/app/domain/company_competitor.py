"""Company/Competitor Analysis DomainPack for HKSimEngine.

Bundles all company-competition-specific constants (shocks, metrics,
demographics, macro fields, scenarios) into a single frozen DomainPack
for simulating competitive dynamics across industries.
"""

from __future__ import annotations

from backend.app.domain.base import (
    DecisionThresholds,
    DemographicsSpec,
    DomainPack,
    DomainPackRegistry,
    MacroFieldSpec,
    MacroImpactDeltas,
    MetricSpec,
    ShockTypeSpec,
)

# ---------------------------------------------------------------------------
# Demographics — corporate agent profiles
# ---------------------------------------------------------------------------

CC_DEMOGRAPHICS = DemographicsSpec(
    regions={
        "North America": 0.30,
        "Europe": 0.25,
        "APAC": 0.25,
        "LATAM": 0.20,
    },
    occupations={
        "CEO": 0.10,
        "CMO": 0.15,
        "CFO": 0.15,
        "CTO": 0.15,
        "VP_Sales": 0.20,
        "Analyst": 0.25,
    },
    income_by_occupation={
        "CEO": {"median": 25_000, "std": 10_000, "unemployed_pct": 0.01},
        "CMO": {"median": 18_000, "std": 6_000, "unemployed_pct": 0.02},
        "CFO": {"median": 20_000, "std": 7_000, "unemployed_pct": 0.02},
        "CTO": {"median": 22_000, "std": 8_000, "unemployed_pct": 0.02},
        "VP_Sales": {"median": 16_000, "std": 5_000, "unemployed_pct": 0.03},
        "Analyst": {"median": 7_000, "std": 2_500, "unemployed_pct": 0.05},
    },
    region_income_modifier={
        "North America": 1.20,
        "Europe": 1.10,
        "APAC": 0.85,
        "LATAM": 0.70,
    },
    education_levels={
        "Bachelor's": 0.30,
        "Master's": 0.40,
        "MBA": 0.20,
        "PhD": 0.10,
    },
    housing_types={"Own": 0.70, "Rent": 0.30},
    age_brackets={
        "25-34": 0.20,
        "35-44": 0.30,
        "45-54": 0.30,
        "55-64": 0.15,
        "65+": 0.05,
    },
    sex_weights={"M": 0.58, "F": 0.42},
    marital_statuses={
        "Single": 0.20,
        "Married": 0.60,
        "Divorced": 0.15,
        "Widowed": 0.05,
    },
    surnames=(
        "Chen", "Wang", "Kim", "Singh", "Nakamura", "Mueller", "Garcia",
        "Smith", "Johnson", "Williams", "Brown", "Lee", "Patel", "Taylor",
        "Anderson", "Martinez", "Thompson", "White", "Lopez", "Clark",
    ),
    username_parts=(
        "strategy", "compete", "market", "growth", "profit", "revenue",
        "disrupt", "innovate", "scale", "pivot", "moat", "edge",
        "margin", "share", "lead", "venture", "exec", "corp",
    ),
    currency_symbol="$",
    currency_code="USD",
)

# ---------------------------------------------------------------------------
# Shock type specs
# ---------------------------------------------------------------------------

_CC_SHOCK_SPECS: tuple[ShockTypeSpec, ...] = (
    ShockTypeSpec("competitor_price_drop", "競爭對手降價", "Competitor Price Drop"),
    ShockTypeSpec("regulatory_change", "監管變化", "Regulatory Change"),
    ShockTypeSpec("market_recession", "市場衰退", "Market Recession"),
    ShockTypeSpec("new_technology", "新技術出現", "New Technology Emergence"),
    ShockTypeSpec("supply_shortage", "供應短缺", "Supply Shortage"),
    ShockTypeSpec("consumer_shift", "消費者偏好轉變", "Consumer Preference Shift"),
    ShockTypeSpec("patent_expiry", "專利到期", "Patent Expiry"),
    ShockTypeSpec("talent_war", "人才爭奪戰", "Talent War"),
)

# ---------------------------------------------------------------------------
# Metric specs
# ---------------------------------------------------------------------------

_CC_METRICS: tuple[MetricSpec, ...] = (
    MetricSpec("market_share", "competition", "market_share", 4),
    MetricSpec("revenue_growth", "finance", "revenue_growth", 4),
    MetricSpec("customer_churn", "competition", "customer_churn", 4),
    MetricSpec("brand_sentiment", "sentiment", "brand_sentiment", 4),
    MetricSpec("cost_efficiency", "finance", "cost_efficiency", 4),
    MetricSpec("innovation_index", "competition", "innovation_index", 4),
)

# ---------------------------------------------------------------------------
# Macro field specs
# ---------------------------------------------------------------------------

_CC_MACRO_FIELDS: tuple[MacroFieldSpec, ...] = (
    MacroFieldSpec("market_size", "Total Addressable Market", 10_000.0, "M USD"),
    MacroFieldSpec("growth_rate", "Market Growth Rate", 5.0, "%"),
    MacroFieldSpec("competitive_intensity", "Competitive Intensity", 0.6, "index"),
    MacroFieldSpec("regulatory_pressure", "Regulatory Pressure", 0.3, "index"),
    MacroFieldSpec("technology_disruption", "Technology Disruption", 0.4, "index"),
    MacroFieldSpec("consumer_confidence", "Consumer Confidence", 100.0, "index"),
)

# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

_CC_SCENARIOS: tuple[dict[str, str], ...] = (
    {
        "key": "market_share_battle",
        "title_zh": "市場份額爭奪",
        "title_en": "Market Share Battle",
        "desc_en": "Simulate aggressive market share competition among incumbents",
        "icon": "crossed_swords",
    },
    {
        "key": "price_war",
        "title_zh": "價格戰",
        "title_en": "Price War",
        "desc_en": "Model price competition dynamics and margin erosion",
        "icon": "chart_with_downwards_trend",
    },
    {
        "key": "disruptive_innovation",
        "title_zh": "顛覆性創新",
        "title_en": "Disruptive Innovation",
        "desc_en": "New entrant with disruptive technology reshapes the market",
        "icon": "bulb",
    },
    {
        "key": "regulatory_shift",
        "title_zh": "監管變革",
        "title_en": "Regulatory Shift",
        "desc_en": "Major regulatory change alters competitive landscape",
        "icon": "scroll",
    },
)

# ---------------------------------------------------------------------------
# Decision thresholds — corporate-adapted values
# ---------------------------------------------------------------------------

_CC_DECISION_THRESHOLDS = DecisionThresholds(
    min_months_down_payment=12,
    stress_test_dti=0.40,
    max_borrower_age_plus_tenor=70,
    emigration_savings_default=50_000,
    invest_min_savings=50_000,
    invest_min_openness=0.35,
    child_min_age=25,
    child_max_age=50,
    child_min_income=8_000,
    job_min_age=22,
    job_max_age=65,
    job_min_extraversion=0.45,
    job_change_unemploy_threshold=0.04,
    spending_adjust_cpi_threshold=0.03,
    spending_adjust_confidence_low=50.0,
    employment_quit_neuroticism=0.5,
    employment_quit_savings_alt=100_000,
    employment_quit_unemploy_cap=0.04,
    employment_strike_stance=0.5,
    employment_strike_confidence=50.0,
    employment_lie_flat_max_age=40,
    employment_lie_flat_min_age=25,
    employment_lie_flat_openness=0.35,
    employment_lie_flat_conscien=0.35,
    employment_sample_rate=0.06,
    employment_max_per_round=25,
    relocate_price_income_ratio=4,
    relocate_school_min_age=28,
    relocate_school_max_age=50,
    relocate_gentrify_income_cap=8_000,
    relocate_gentrify_price_floor=3_000,
    relocate_sample_rate=0.07,
    relocate_max_per_round=30,
)

# ---------------------------------------------------------------------------
# Macro impact deltas
# ---------------------------------------------------------------------------

_CC_MACRO_IMPACT_DELTAS = MacroImpactDeltas(
    buy_property_ccl_delta=0.1,
    emigrate_net_mig_delta=-20,
    invest_stocks_hsi_delta=0.0,
    have_child_confidence_delta=0.1,
    adjust_spending_confidence_delta=-0.2,
)

# ---------------------------------------------------------------------------
# Pack construction + registration
# ---------------------------------------------------------------------------

COMPANY_COMPETITOR_PACK = DomainPack(
    id="company_competitor",
    name_zh="企業競爭",
    name_en="Company Competitor",
    locale="en",
    valid_shock_types=frozenset(s.id for s in _CC_SHOCK_SPECS),
    shock_specs=_CC_SHOCK_SPECS,
    metrics=_CC_METRICS,
    default_forecast_metrics=tuple(m.name for m in _CC_METRICS),
    correlated_vars=(
        "market_share", "revenue_growth", "customer_churn", "brand_sentiment",
    ),
    mc_default_metrics=(
        "market_share", "revenue_growth", "customer_churn", "cost_efficiency",
    ),
    decision_thresholds=_CC_DECISION_THRESHOLDS,
    macro_impact_deltas=_CC_MACRO_IMPACT_DELTAS,
    demographics=CC_DEMOGRAPHICS,
    macro_fields=_CC_MACRO_FIELDS,
    decision_types=("pricing", "market_entry", "partnership", "cost_cutting"),
    scenarios=_CC_SCENARIOS,
    keywords=(
        "公司", "company", "competitor", "market share", "營銷",
        "enterprise", "corporate", "industry",
    ),
)

DomainPackRegistry.register(COMPANY_COMPETITOR_PACK)
