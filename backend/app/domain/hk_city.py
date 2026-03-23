"""Hong Kong Society domain pack — copies all HK-specific constants.

This module duplicates (not moves) constants from various service files
so the core engine can eventually become domain-agnostic. The original
constants remain in their original locations for backward compatibility.
"""

from __future__ import annotations

from backend.app.domain.base import (
    DecisionThresholds,
    DomainPack,
    DomainPackRegistry,
    MacroImpactDeltas,
    MetricSpec,
    ShockTypeSpec,
)
from backend.app.domain.locales.zh_hk import HK_DEMOGRAPHICS, ZH_HK_LOCALE, ZH_HK_SENTIMENT

# ---------------------------------------------------------------------------
# Shock type specs (source: macro_state.py L12-54)
# ---------------------------------------------------------------------------

_HK_SHOCK_SPECS: tuple[ShockTypeSpec, ...] = (
    ShockTypeSpec("interest_rate_hike", "加息", "Interest Rate Hike"),
    ShockTypeSpec("property_crash", "樓市崩盤", "Property Crash"),
    ShockTypeSpec("unemployment_spike", "失業率急升", "Unemployment Spike"),
    ShockTypeSpec("policy_change", "政策變動", "Policy Change"),
    ShockTypeSpec("market_rally", "股市大升", "Market Rally"),
    ShockTypeSpec("emigration_wave", "移民潮", "Emigration Wave"),
    ShockTypeSpec("fed_rate_hike", "聯儲局加息", "Fed Rate Hike"),
    ShockTypeSpec("fed_rate_cut", "聯儲局減息", "Fed Rate Cut"),
    ShockTypeSpec("china_slowdown", "中國經濟放緩", "China Slowdown"),
    ShockTypeSpec("china_stimulus", "中國刺激政策", "China Stimulus"),
    ShockTypeSpec("taiwan_strait_tension", "台海緊張", "Taiwan Strait Tension"),
    ShockTypeSpec("taiwan_strait_ease", "台海緩和", "Taiwan Strait Ease"),
    ShockTypeSpec("shenzhen_magnet", "深圳虹吸效應", "Shenzhen Magnet"),
    ShockTypeSpec("greater_bay_boost", "大灣區利好", "Greater Bay Boost"),
    ShockTypeSpec("tariff_increase", "關稅增加", "Tariff Increase"),
    ShockTypeSpec("supply_chain_disruption", "供應鏈中斷", "Supply Chain Disruption"),
    ShockTypeSpec("china_demand_collapse", "中國需求崩塌", "China Demand Collapse"),
    ShockTypeSpec("rcep_benefit", "RCEP利好", "RCEP Benefit"),
)

_HK_VALID_SHOCK_TYPES: frozenset[str] = frozenset(spec.id for spec in _HK_SHOCK_SPECS)

# ---------------------------------------------------------------------------
# Metric specs (source: time_series_forecaster.py L46-58)
# ---------------------------------------------------------------------------

_HK_METRICS: tuple[MetricSpec, ...] = (
    MetricSpec("ccl_index", "property", "ccl_index", 4),
    MetricSpec("unemployment_rate", "employment", "unemployment_rate", 4),
    MetricSpec("hsi_level", "finance", "hsi_level", 12),
    MetricSpec("cpi_yoy", "price_index", "cpi_yoy", 12),
    MetricSpec("gdp_growth", "gdp", "gdp_growth_rate", 4),
    MetricSpec("consumer_confidence", "sentiment", "consumer_confidence", 4),
    MetricSpec("hibor_1m", "interest_rate", "hibor_1m", 4),
    MetricSpec("prime_rate", "interest_rate", "prime_rate", 4),
    MetricSpec("net_migration", "migration", "net_migration", 4),
    MetricSpec("retail_sales_index", "retail", "retail_sales_index", 4),
    MetricSpec("tourist_arrivals", "tourism", "tourist_arrivals", 4),
)

_HK_DEFAULT_FORECAST_METRICS: tuple[str, ...] = tuple(m.name for m in _HK_METRICS)

# ---------------------------------------------------------------------------
# Monte Carlo constants (source: monte_carlo.py L32, L58-66)
# ---------------------------------------------------------------------------

_HK_CORRELATED_VARS: tuple[str, ...] = (
    "gdp_growth",
    "unemployment_rate",
    "consumer_confidence",
    "hsi_level",
)

_HK_MC_DEFAULT_METRICS: tuple[str, ...] = (
    "ccl_index_change",
    "unemployment_change",
    "net_migration_change",
    "hsi_change",
    "consumer_confidence_change",
    "buy_property_rate",
    "emigrate_rate",
)

# ---------------------------------------------------------------------------
# Baseline district prices (source: macro_state.py L60-79)
# ---------------------------------------------------------------------------

_HK_BASELINE_DISTRICT_PRICES: dict[str, int] = {
    "中西區": 18_500,
    "灣仔": 19_200,
    "東區": 14_800,
    "南區": 15_600,
    "油尖旺": 16_200,
    "深水埗": 13_500,
    "九龍城": 15_900,
    "黃大仙": 11_800,
    "觀塘": 12_600,
    "葵青": 10_800,
    "荃灣": 11_500,
    "屯門": 9_200,
    "元朗": 9_600,
    "北區": 9_000,
    "大埔": 10_200,
    "沙田": 12_800,
    "西貢": 11_900,
    "離島": 10_500,
}

# ---------------------------------------------------------------------------
# Stamp duty rates (source: macro_state.py L81-87)
# ---------------------------------------------------------------------------

_HK_BASELINE_STAMP_DUTY: dict[str, float] = {
    "ad_valorem_scale_1": 0.015,
    "ad_valorem_scale_2": 0.0375,
    "ad_valorem_scale_3": 0.075,
    "non_first_time": 0.075,
    "non_hkpr": 0.075,
}

# ---------------------------------------------------------------------------
# Decision thresholds (source: decision_rules.py L29-86)
# ---------------------------------------------------------------------------

_HK_DECISION_THRESHOLDS = DecisionThresholds(
    min_months_down_payment=24,
    stress_test_dti=0.50,
    max_borrower_age_plus_tenor=75,
    emigration_savings_by_destination=(
        ("uk", 500_000),
        ("canada", 500_000),
        ("australia", 500_000),
        ("taiwan", 200_000),
        ("malaysia", 200_000),
    ),
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
# Macro impact deltas (source: decision_engine.py L54-68)
# ---------------------------------------------------------------------------

_HK_MACRO_IMPACT_DELTAS = MacroImpactDeltas(
    buy_property_ccl_delta=0.3,
    emigrate_net_mig_delta=-50,
    invest_stocks_hsi_delta=0.0,
    have_child_confidence_delta=0.2,
    adjust_spending_confidence_delta=-0.3,
)

# ---------------------------------------------------------------------------
# Housing context (source: persona_templates.py L149-162)
# ---------------------------------------------------------------------------

_HK_HOUSING_CONTEXT: dict[str, str] = {
    "公屋": (
        "住喺公共屋邨，每月租金約 HK$2,000-4,000，向房署交租（唔係供樓）。"
        "依規定唔可以同時擁有私人物業，亦唔需要承擔按揭壓力。"
        "（注意：呢位代理人係已入住公屋嘅住客，唔係係等緊上公屋嘅申請人，"
        "唔好寫佢喺輪候公屋。）"
    ),
    "資助出售房屋": "住喺居屋或其他資助出售房屋，以折扣價購入，有轉售限制",
    "私人住宅": "住喺私人物業，可能正在供樓或租住，居住成本較高",
    "臨時／其他": (
        "居住環境較為不穩定，可能住喺劏房或臨時住所。部分居民可能係係輪候公屋嘅申請人，暫時租住私樓或板間房。"
    ),
}

# ---------------------------------------------------------------------------
# Macro baselines (source: macro_state.py MacroState defaults L117-146)
# ---------------------------------------------------------------------------

_HK_MACRO_BASELINES: dict[str, float] = {
    "fed_rate": 0.053,
    "usd_hkd": 7.82,
    "china_gdp_growth": 0.052,
    "rmb_hkd": 1.076,
    "china_property_crisis": 0.6,
    "northbound_capital_bn": 120.0,
    "taiwan_strait_risk": 0.3,
    "us_china_trade_tension": 0.6,
    "shenzhen_cost_ratio": 0.38,
    "cross_border_residents": 50_000,
    "greater_bay_policy_score": 0.55,
    "import_tariff_rate": 0.0,
    "export_logistics_cost": 1.0,
    "supply_chain_disruption": 0.0,
    "china_import_demand": 0.0,
    "bank_ltv_cap": 0.60,
    "credit_growth_yoy": 0.02,
    "interbank_spread": 0.005,
    "mortgage_delinquency": 0.015,
    "bank_reserve_ratio": 0.08,
}

# ---------------------------------------------------------------------------
# Pack construction + registration
# ---------------------------------------------------------------------------

HK_CITY_PACK = DomainPack(
    id="hk_city",
    name_zh="香港社會",
    name_en="Hong Kong Society",
    locale="zh-HK",
    valid_shock_types=_HK_VALID_SHOCK_TYPES,
    shock_specs=_HK_SHOCK_SPECS,
    metrics=_HK_METRICS,
    default_forecast_metrics=_HK_DEFAULT_FORECAST_METRICS,
    correlated_vars=_HK_CORRELATED_VARS,
    mc_default_metrics=_HK_MC_DEFAULT_METRICS,
    macro_baselines=_HK_MACRO_BASELINES,
    baseline_district_prices=_HK_BASELINE_DISTRICT_PRICES,
    baseline_stamp_duty=_HK_BASELINE_STAMP_DUTY,
    decision_thresholds=_HK_DECISION_THRESHOLDS,
    macro_impact_deltas=_HK_MACRO_IMPACT_DELTAS,
    housing_context_map=_HK_HOUSING_CONTEXT,
    demographics=HK_DEMOGRAPHICS,
    prompt_locale=ZH_HK_LOCALE,
    sentiment_lexicon=ZH_HK_SENTIMENT,
    keywords=(
        "香港",
        "樓市",
        "property",
        "移民",
        "emigration",
        "生育",
        "fertility",
        "hk",
        "hong kong",
        "ccl",
        "hsi",
        "恒指",
        "公屋",
    ),
    topic_groups=(
        (
            "hong kong",
            "hkd",
            "property",
            "ccl",
            "emigration",
            "national security",
            "article 23",
            "linked exchange",
            "mpf",
            "樓市",
            "移民",
            "香港",
        ),
    ),
)

DomainPackRegistry.register(HK_CITY_PACK)
