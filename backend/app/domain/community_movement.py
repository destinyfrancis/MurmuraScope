"""Community/Social Movement DomainPack for MurmuraScope.

Bundles all social-movement-specific constants (shocks, metrics,
demographics, macro fields, scenarios) into a single frozen DomainPack
for simulating grassroots movements, protests, and collective action.
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
# Demographics — movement participant profiles
# ---------------------------------------------------------------------------

CM_DEMOGRAPHICS = DemographicsSpec(
    regions={
        "Urban Core": 0.30,
        "Suburbs": 0.20,
        "University": 0.20,
        "Industrial": 0.15,
        "Rural": 0.15,
    },
    occupations={
        "Student": 0.25,
        "Worker": 0.20,
        "Professional": 0.20,
        "Artist": 0.10,
        "Journalist": 0.10,
        "Retiree": 0.15,
    },
    income_by_occupation={
        "Student": {"median": 1_200, "std": 600, "unemployed_pct": 0.20},
        "Worker": {"median": 3_500, "std": 1_200, "unemployed_pct": 0.08},
        "Professional": {"median": 6_500, "std": 2_500, "unemployed_pct": 0.03},
        "Artist": {"median": 2_800, "std": 1_500, "unemployed_pct": 0.12},
        "Journalist": {"median": 4_000, "std": 1_800, "unemployed_pct": 0.06},
        "Retiree": {"median": 2_500, "std": 1_000, "unemployed_pct": 0.0},
    },
    region_income_modifier={
        "Urban Core": 1.15,
        "Suburbs": 1.00,
        "University": 0.80,
        "Industrial": 0.90,
        "Rural": 0.75,
    },
    education_levels={
        "No Diploma": 0.10,
        "High School": 0.25,
        "Some College": 0.20,
        "Bachelor's": 0.30,
        "Graduate": 0.15,
    },
    housing_types={"Own": 0.45, "Rent": 0.40, "Shared": 0.15},
    age_brackets={
        "18-24": 0.25,
        "25-34": 0.25,
        "35-44": 0.18,
        "45-54": 0.15,
        "55-64": 0.10,
        "65+": 0.07,
    },
    sex_weights={"M": 0.48, "F": 0.52},
    marital_statuses={
        "Single": 0.45,
        "Married": 0.35,
        "Divorced": 0.12,
        "Widowed": 0.05,
        "Separated": 0.03,
    },
    surnames=(
        "Lee", "Wong", "Chan", "Chen", "Kim", "Park", "Singh", "Ahmed",
        "Garcia", "Rodriguez", "Martinez", "Smith", "Johnson", "Brown",
        "Davis", "Wilson", "Taylor", "Thomas", "Moore", "Jackson",
    ),
    username_parts=(
        "resist", "unite", "voice", "stand", "march", "freedom", "justice",
        "rights", "people", "change", "hope", "rise", "power", "truth",
        "solidarity", "action", "community", "movement",
    ),
    currency_symbol="$",
    currency_code="USD",
)

# ---------------------------------------------------------------------------
# Shock type specs
# ---------------------------------------------------------------------------

_CM_SHOCK_SPECS: tuple[ShockTypeSpec, ...] = (
    ShockTypeSpec("government_crackdown", "政府鎮壓", "Government Crackdown"),
    ShockTypeSpec("leader_arrested", "領袖被捕", "Leader Arrested"),
    ShockTypeSpec("international_support", "國際聲援", "International Support"),
    ShockTypeSpec("media_coverage", "媒體報導", "Major Media Coverage"),
    ShockTypeSpec("counter_movement", "反對運動", "Counter-Movement"),
    ShockTypeSpec("economic_pressure", "經濟壓力", "Economic Pressure"),
    ShockTypeSpec("legal_victory", "法律勝利", "Legal Victory"),
    ShockTypeSpec("viral_moment", "病毒式傳播", "Viral Moment"),
)

# ---------------------------------------------------------------------------
# Metric specs
# ---------------------------------------------------------------------------

_CM_METRICS: tuple[MetricSpec, ...] = (
    MetricSpec("movement_size", "movement", "movement_size", 4),
    MetricSpec("solidarity_index", "movement", "solidarity_index", 4),
    MetricSpec("resource_level", "movement", "resource_level", 4),
    MetricSpec("public_sympathy", "sentiment", "public_sympathy", 4),
    MetricSpec("media_attention", "sentiment", "media_attention", 4),
    MetricSpec("organizational_capacity", "movement", "organizational_capacity", 4),
)

# ---------------------------------------------------------------------------
# Macro field specs
# ---------------------------------------------------------------------------

_CM_MACRO_FIELDS: tuple[MacroFieldSpec, ...] = (
    MacroFieldSpec("political_freedom", "Political Freedom Index", 0.5, "index"),
    MacroFieldSpec("economic_inequality", "Economic Inequality (Gini)", 0.40, "index"),
    MacroFieldSpec("media_freedom", "Media Freedom Index", 0.6, "index"),
    MacroFieldSpec("police_intensity", "Police Response Intensity", 0.3, "index"),
    MacroFieldSpec("international_pressure", "International Pressure", 0.2, "index"),
    MacroFieldSpec("social_trust", "Social Trust Level", 0.5, "index"),
)

# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

_CM_SCENARIOS: tuple[dict[str, str], ...] = (
    {
        "key": "grassroots_uprising",
        "title_zh": "草根起義",
        "title_en": "Grassroots Uprising",
        "desc_en": "Spontaneous mass mobilization from economic grievances",
        "icon": "raised_fist",
    },
    {
        "key": "government_response",
        "title_zh": "政府回應",
        "title_en": "Government Response",
        "desc_en": "Simulate government strategies: concession vs. crackdown",
        "icon": "classical_building",
    },
    {
        "key": "international_solidarity",
        "title_zh": "國際聲援",
        "title_en": "International Solidarity",
        "desc_en": "External support amplifies domestic movement momentum",
        "icon": "globe_with_meridians",
    },
    {
        "key": "movement_fragmentation",
        "title_zh": "運動分裂",
        "title_en": "Movement Fragmentation",
        "desc_en": "Internal divisions weaken collective action capacity",
        "icon": "broken_heart",
    },
)

# ---------------------------------------------------------------------------
# Decision thresholds — movement-adapted values
# ---------------------------------------------------------------------------

_CM_DECISION_THRESHOLDS = DecisionThresholds(
    min_months_down_payment=12,
    stress_test_dti=0.50,
    max_borrower_age_plus_tenor=75,
    emigration_savings_default=15_000,
    invest_min_savings=5_000,
    invest_min_openness=0.30,
    child_min_age=22,
    child_max_age=45,
    child_min_income=2_500,
    job_min_age=18,
    job_max_age=65,
    job_min_extraversion=0.40,
    job_change_unemploy_threshold=0.07,
    spending_adjust_cpi_threshold=0.02,
    spending_adjust_confidence_low=40.0,
    employment_quit_neuroticism=0.55,
    employment_quit_savings_alt=20_000,
    employment_quit_unemploy_cap=0.06,
    employment_strike_stance=0.5,
    employment_strike_confidence=35.0,
    employment_lie_flat_max_age=35,
    employment_lie_flat_min_age=18,
    employment_lie_flat_openness=0.35,
    employment_lie_flat_conscien=0.35,
    employment_sample_rate=0.08,
    employment_max_per_round=40,
    relocate_price_income_ratio=8,
    relocate_school_min_age=25,
    relocate_school_max_age=50,
    relocate_gentrify_income_cap=4_000,
    relocate_gentrify_price_floor=1_500,
    relocate_sample_rate=0.10,
    relocate_max_per_round=50,
)

# ---------------------------------------------------------------------------
# Macro impact deltas
# ---------------------------------------------------------------------------

_CM_MACRO_IMPACT_DELTAS = MacroImpactDeltas(
    buy_property_ccl_delta=0.1,
    emigrate_net_mig_delta=-30,
    invest_stocks_hsi_delta=0.0,
    have_child_confidence_delta=0.1,
    adjust_spending_confidence_delta=-0.4,
)

# ---------------------------------------------------------------------------
# Macro baselines — community movement defaults
# ---------------------------------------------------------------------------

_COMMUNITY_MACRO_BASELINES: dict[str, float] = {
    "consumer_confidence": 45.0,
    "unemployment_rate": 0.060,
    "gdp_growth": 0.015,
    "cpi_yoy": 0.035,
}

# ---------------------------------------------------------------------------
# Pack construction + registration
# ---------------------------------------------------------------------------

COMMUNITY_MOVEMENT_PACK = DomainPack(
    id="community_movement",
    name_zh="社會運動",
    name_en="Community Movement",
    locale="en",
    valid_shock_types=frozenset(s.id for s in _CM_SHOCK_SPECS),
    shock_specs=_CM_SHOCK_SPECS,
    metrics=_CM_METRICS,
    default_forecast_metrics=tuple(m.name for m in _CM_METRICS),
    correlated_vars=(
        "movement_size", "solidarity_index", "public_sympathy", "media_attention",
    ),
    mc_default_metrics=(
        "movement_size", "solidarity_index", "public_sympathy",
        "organizational_capacity",
    ),
    macro_baselines=_COMMUNITY_MACRO_BASELINES,
    decision_thresholds=_CM_DECISION_THRESHOLDS,
    macro_impact_deltas=_CM_MACRO_IMPACT_DELTAS,
    demographics=CM_DEMOGRAPHICS,
    macro_fields=_CM_MACRO_FIELDS,
    decision_types=(
        "join_movement", "donate", "protest", "defect", "recruit",
    ),
    scenarios=_CM_SCENARIOS,
    keywords=(
        "社區", "community", "movement", "組織",
        "grassroots", "activism", "protest", "rally",
    ),
)

DomainPackRegistry.register(COMMUNITY_MOVEMENT_PACK)
