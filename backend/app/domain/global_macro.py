"""Global Macro DomainPack for HKSimEngine.

Covers multi-national macro indicators, commodity shocks, and central bank
divergence scenarios. Designed for global investor and analyst personas.
"""

from __future__ import annotations

from backend.app.domain.base import (
    DataSourceSpec,
    DecisionThresholds,
    DemographicsSpec,
    DomainPack,
    DomainPackRegistry,
    MacroFieldSpec,
    MacroImpactDeltas,
    MetricSpec,
    ShockTypeSpec,
)
from backend.app.domain.locales.en_us import EN_US_LOCALE, EN_US_SENTIMENT

# ---------------------------------------------------------------------------
# Demographics — generic global investor profile
# ---------------------------------------------------------------------------

GLOBAL_DEMOGRAPHICS = DemographicsSpec(
    regions={
        "North America": 0.25,
        "Europe": 0.22,
        "Asia Pacific": 0.30,
        "Latin America": 0.10,
        "Middle East & Africa": 0.08,
        "Other": 0.05,
    },
    occupations={
        "Finance/Investment": 0.20,
        "Technology": 0.15,
        "Management": 0.15,
        "Research/Academia": 0.10,
        "Government/Policy": 0.08,
        "Trade/Commerce": 0.12,
        "Energy/Commodities": 0.08,
        "Retired/Independent": 0.12,
    },
    income_by_occupation={
        "Finance/Investment": {"median": 12_000, "std": 8_000, "unemployed_pct": 0.01},
        "Technology": {"median": 9_000, "std": 5_000, "unemployed_pct": 0.02},
        "Management": {"median": 10_000, "std": 6_000, "unemployed_pct": 0.02},
        "Research/Academia": {"median": 5_500, "std": 2_000, "unemployed_pct": 0.03},
        "Government/Policy": {"median": 6_000, "std": 2_500, "unemployed_pct": 0.01},
        "Trade/Commerce": {"median": 7_000, "std": 4_000, "unemployed_pct": 0.04},
        "Energy/Commodities": {"median": 8_000, "std": 4_500, "unemployed_pct": 0.03},
        "Retired/Independent": {"median": 5_000, "std": 3_000, "unemployed_pct": 0.0},
    },
    region_income_modifier={
        "North America": 1.30,
        "Europe": 1.10,
        "Asia Pacific": 0.90,
        "Latin America": 0.65,
        "Middle East & Africa": 0.70,
        "Other": 0.75,
    },
    education_levels={
        "High School": 0.10,
        "Some College": 0.15,
        "Bachelor's": 0.38,
        "Master's": 0.27,
        "PhD/Professional": 0.10,
    },
    housing_types={"Own": 0.60, "Rent": 0.40},
    age_brackets={
        "18-24": 0.05,
        "25-34": 0.18,
        "35-44": 0.22,
        "45-54": 0.22,
        "55-64": 0.18,
        "65+": 0.15,
    },
    sex_weights={"M": 0.55, "F": 0.45},
    marital_statuses={
        "Single": 0.28,
        "Married": 0.55,
        "Divorced": 0.12,
        "Widowed": 0.05,
    },
    surnames=(
        "Smith", "Müller", "Chen", "Kim", "Patel", "Rossi", "García",
        "Tanaka", "Dupont", "Ivanov", "Svensson", "Park", "Singh",
        "Nguyen", "Ali", "Cohen", "Santos", "Johansson", "Brown",
        "Wang", "Schmidt", "Fernandez", "Johnson", "Kovacs", "Petrov",
    ),
    username_parts=(
        "macro", "global", "analyst", "trader", "investor", "quant",
        "economist", "strateg", "markets", "alpha", "yield", "risk",
        "outlook", "thesis", "signal", "hedge", "arbitrage", "diverge",
    ),
    currency_symbol="$",
    currency_code="USD",
)

# ---------------------------------------------------------------------------
# Shock type specs
# ---------------------------------------------------------------------------

_GLOBAL_SHOCK_SPECS: tuple[ShockTypeSpec, ...] = (
    ShockTypeSpec("oil_shock", "油價衝擊", "Oil Price Shock"),
    ShockTypeSpec("trade_war_escalation", "貿易戰升級", "Trade War Escalation"),
    ShockTypeSpec("central_bank_pivot", "央行政策轉向", "Central Bank Pivot"),
    ShockTypeSpec("pandemic_wave", "疫情新浪潮", "Pandemic Wave"),
    ShockTypeSpec("climate_event", "氣候事件衝擊", "Major Climate Event"),
    ShockTypeSpec("sovereign_debt_crisis", "主權債務危機", "Sovereign Debt Crisis"),
)

# ---------------------------------------------------------------------------
# Metric specs
# ---------------------------------------------------------------------------

_GLOBAL_METRICS: tuple[MetricSpec, ...] = (
    MetricSpec("global_pmi", "sentiment", "global_pmi", 12),
    MetricSpec("oil_price", "commodity", "oil_price", 12),
    MetricSpec("gold_price", "commodity", "gold_price", 12),
    MetricSpec("usd_index", "currency", "usd_index", 12),
    MetricSpec("g7_avg_gdp", "gdp", "g7_avg_gdp", 4),
    MetricSpec("global_inflation", "price_index", "global_inflation", 4),
    MetricSpec("spx_close", "finance", "spx_close", 12),
    MetricSpec("ftse_close", "finance", "ftse_close", 12),
    MetricSpec("nikkei_close", "finance", "nikkei_close", 12),
)

# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------

_GLOBAL_DATA_SOURCES: tuple[DataSourceSpec, ...] = (
    DataSourceSpec(
        id="yfinance_global_indices",
        downloader="backend.data_pipeline.yfinance_downloader",
        function="download_tickers",
        params={"tickers": ["CL=F", "GC=F", "DX-Y.NYB", "^GSPC", "^FTSE", "^N225"]},
        category="finance",
    ),
    DataSourceSpec(
        id="fred_global_macro",
        downloader="backend.data_pipeline.fred_downloader",
        function="download_series",
        params={
            "series_ids": [
                ("DCOILWTICO", "oil_price_wti", "$/bbl"),
                ("GOLDAMGBD228NLBM", "gold_price", "$/oz"),
                ("DTWEXBGS", "usd_index", "index"),
            ]
        },
        category="commodity",
    ),
)

# ---------------------------------------------------------------------------
# Macro field specs
# ---------------------------------------------------------------------------

_GLOBAL_MACRO_FIELDS: tuple[MacroFieldSpec, ...] = (
    MacroFieldSpec("oil_price", "WTI Crude Oil", 80.0, "$/bbl"),
    MacroFieldSpec("gold_price", "Gold Spot", 2_050.0, "$/oz"),
    MacroFieldSpec("usd_index", "US Dollar Index", 104.0, "index"),
    MacroFieldSpec("global_pmi", "Global Composite PMI", 51.5, "index"),
    MacroFieldSpec("g7_avg_gdp", "G7 Average GDP Growth", 2.1, "%"),
    MacroFieldSpec("global_inflation", "Global Avg Inflation", 3.5, "%"),
    MacroFieldSpec("em_spread", "EM Credit Spread", 350.0, "bps"),
    MacroFieldSpec("vix_level", "VIX", 18.0, "index"),
)

# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

_GLOBAL_SCENARIOS: tuple[dict[str, str], ...] = (
    {
        "key": "global_recession",
        "title_zh": "全球衰退風險",
        "title_en": "Global Recession Risk",
        "desc_en": "Model probability and contagion paths of a synchronised global recession",
        "icon": "🌍",
    },
    {
        "key": "commodity_supercycle",
        "title_zh": "大宗商品超級周期",
        "title_en": "Commodity Supercycle",
        "desc_en": "Simulate oil/gold/metals boom and its macro ripple effects",
        "icon": "🛢️",
    },
    {
        "key": "cb_divergence",
        "title_zh": "央行政策分化",
        "title_en": "Central Bank Divergence",
        "desc_en": "Fed hikes while ECB/BoJ hold — currency and capital flow impacts",
        "icon": "🏦",
    },
    {
        "key": "trade_war",
        "title_zh": "貿易戰升級",
        "title_en": "Trade War Escalation",
        "desc_en": "Multi-lateral tariff escalation and supply chain fragmentation",
        "icon": "⚔️",
    },
)

# ---------------------------------------------------------------------------
# Decision thresholds — global defaults
# ---------------------------------------------------------------------------

_GLOBAL_DECISION_THRESHOLDS = DecisionThresholds(
    min_months_down_payment=24,
    stress_test_dti=0.45,
    max_borrower_age_plus_tenor=75,
    emigration_savings_by_destination=(),
    emigration_savings_default=20_000,
    invest_min_savings=5_000,
    invest_min_openness=0.35,
    child_min_age=22,
    child_max_age=45,
    child_min_income=3_000,
    job_min_age=18,
    job_max_age=67,
    job_min_extraversion=0.45,
    job_change_unemploy_threshold=0.06,
    spending_adjust_cpi_threshold=0.030,
    spending_adjust_confidence_low=45.0,
    employment_quit_neuroticism=0.6,
    employment_quit_savings_alt=20_000,
    employment_quit_unemploy_cap=0.05,
    employment_strike_stance=0.6,
    employment_strike_confidence=42.0,
    employment_lie_flat_max_age=38,
    employment_lie_flat_min_age=22,
    employment_lie_flat_openness=0.4,
    employment_lie_flat_conscien=0.4,
    employment_sample_rate=0.05,
    employment_max_per_round=30,
    relocate_price_income_ratio=10,
    relocate_school_min_age=28,
    relocate_school_max_age=50,
    relocate_gentrify_income_cap=4_000,
    relocate_gentrify_price_floor=1_500,
    relocate_sample_rate=0.08,
    relocate_max_per_round=40,
)

_GLOBAL_MACRO_IMPACT_DELTAS = MacroImpactDeltas(
    buy_property_ccl_delta=0.3,
    emigrate_net_mig_delta=-50,
    invest_stocks_hsi_delta=0.0,
    have_child_confidence_delta=0.2,
    adjust_spending_confidence_delta=-0.3,
)

# ---------------------------------------------------------------------------
# Pack construction + registration
# ---------------------------------------------------------------------------

GLOBAL_MACRO_PACK = DomainPack(
    id="global_macro",
    name_zh="全球宏觀",
    name_en="Global Macro",
    locale="en-US",
    valid_shock_types=frozenset(s.id for s in _GLOBAL_SHOCK_SPECS),
    shock_specs=_GLOBAL_SHOCK_SPECS,
    metrics=_GLOBAL_METRICS,
    default_forecast_metrics=("oil_price", "gold_price", "usd_index", "global_pmi"),
    correlated_vars=("oil_price", "gold_price", "usd_index", "global_pmi"),
    mc_default_metrics=("oil_price", "gold_price", "usd_index", "g7_avg_gdp"),
    decision_thresholds=_GLOBAL_DECISION_THRESHOLDS,
    macro_impact_deltas=_GLOBAL_MACRO_IMPACT_DELTAS,
    demographics=GLOBAL_DEMOGRAPHICS,
    data_sources=_GLOBAL_DATA_SOURCES,
    prompt_locale=EN_US_LOCALE,
    sentiment_lexicon=EN_US_SENTIMENT,
    macro_fields=_GLOBAL_MACRO_FIELDS,
    scenarios=_GLOBAL_SCENARIOS,
    keywords=(
        "global", "recession", "trade war", "油價", "commodity",
        "world economy", "geopolitical", "imf", "world bank",
    ),
)

DomainPackRegistry.register(GLOBAL_MACRO_PACK)
