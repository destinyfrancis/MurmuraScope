"""US Markets DomainPack for MurmuraScope.

Bundles all US-specific constants (shocks, metrics, demographics, data sources,
macro field specs, and prompt locale) into a single frozen DomainPack.
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
# Demographics
# ---------------------------------------------------------------------------

US_DEMOGRAPHICS = DemographicsSpec(
    regions={
        "Northeast": 0.17,
        "Southeast": 0.21,
        "Midwest": 0.21,
        "Southwest": 0.12,
        "West": 0.17,
        "Pacific": 0.12,
    },
    occupations={
        "Management": 0.11,
        "Professional": 0.24,
        "Service": 0.17,
        "Sales/Office": 0.21,
        "Construction": 0.06,
        "Production": 0.06,
        "Student": 0.08,
        "Retired": 0.07,
    },
    income_by_occupation={
        "Management": {"median": 8_500, "std": 3_500, "unemployed_pct": 0.02},
        "Professional": {"median": 7_000, "std": 2_800, "unemployed_pct": 0.02},
        "Service": {"median": 3_200, "std": 1_200, "unemployed_pct": 0.06},
        "Sales/Office": {"median": 4_000, "std": 1_500, "unemployed_pct": 0.04},
        "Construction": {"median": 4_500, "std": 1_800, "unemployed_pct": 0.05},
        "Production": {"median": 3_800, "std": 1_400, "unemployed_pct": 0.05},
        "Student": {"median": 1_500, "std": 800, "unemployed_pct": 0.15},
        "Retired": {"median": 3_500, "std": 2_000, "unemployed_pct": 0.0},
    },
    region_income_modifier={
        "Northeast": 1.15,
        "Pacific": 1.20,
        "West": 1.05,
        "Midwest": 0.90,
        "Southeast": 0.92,
        "Southwest": 0.95,
    },
    education_levels={
        "No Diploma": 0.07,
        "High School": 0.27,
        "Some College": 0.20,
        "Bachelor's": 0.33,
        "Graduate": 0.13,
    },
    housing_types={"Own": 0.65, "Rent": 0.35},
    age_brackets={
        "18-24": 0.12,
        "25-34": 0.18,
        "35-44": 0.16,
        "45-54": 0.16,
        "55-64": 0.17,
        "65+": 0.21,
    },
    sex_weights={"M": 0.49, "F": 0.51},
    marital_statuses={
        "Single": 0.33,
        "Married": 0.48,
        "Divorced": 0.11,
        "Widowed": 0.06,
        "Separated": 0.02,
    },
    surnames=(
        "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
        "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
        "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
        "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
        "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
    ),
    username_parts=(
        "investor", "trader", "bull", "bear", "hodl", "wsb", "tendies",
        "stocks", "market", "alpha", "theta", "gamma", "profit", "gains",
        "diamond", "hands", "moon", "rocket", "dip", "buy", "yolo",
    ),
    currency_symbol="$",
    currency_code="USD",
)

# ---------------------------------------------------------------------------
# Shock type specs
# ---------------------------------------------------------------------------

_US_SHOCK_SPECS: tuple[ShockTypeSpec, ...] = (
    ShockTypeSpec("fed_rate_hike", "聯儲加息", "Fed Rate Hike"),
    ShockTypeSpec("fed_rate_cut", "聯儲減息", "Fed Rate Cut"),
    ShockTypeSpec("earnings_miss", "企業盈利不及預期", "Major Earnings Miss"),
    ShockTypeSpec("inflation_spike", "通脹飆升", "Inflation Spike"),
    ShockTypeSpec("recession_signal", "衰退信號", "Recession Signal"),
    ShockTypeSpec("tech_selloff", "科技股拋售", "Tech Selloff"),
    ShockTypeSpec("geopolitical_crisis", "地緣政治危機", "Geopolitical Crisis"),
    ShockTypeSpec("debt_ceiling", "債務上限危機", "Debt Ceiling Crisis"),
)

# ---------------------------------------------------------------------------
# Metric specs
# ---------------------------------------------------------------------------

_US_METRICS: tuple[MetricSpec, ...] = (
    MetricSpec("spx_close", "finance", "spx_close", 12),
    MetricSpec("ndx_close", "finance", "ndx_close", 12),
    MetricSpec("vix_close", "finance", "vix_close", 12),
    MetricSpec("fed_funds_rate", "interest_rate", "fed_funds_rate", 4),
    MetricSpec("us_unemployment", "employment", "us_unemployment", 4),
    MetricSpec("us_cpi_yoy", "price_index", "us_cpi_yoy", 12),
    MetricSpec("us_10y_yield", "interest_rate", "us_10y_yield", 12),
    MetricSpec("us_consumer_confidence", "sentiment", "us_consumer_confidence", 4),
)

# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------

_US_DATA_SOURCES: tuple[DataSourceSpec, ...] = (
    DataSourceSpec(
        id="yfinance_us_indices",
        downloader="backend.data_pipeline.yfinance_downloader",
        function="download_tickers",
        params={"tickers": ["^GSPC", "^IXIC", "^VIX", "^TNX"]},
        category="finance",
    ),
    DataSourceSpec(
        id="fred_us_macro",
        downloader="backend.data_pipeline.fred_downloader",
        function="download_series",
        params={
            "series_ids": [
                ("FEDFUNDS", "fed_funds_rate", "%"),
                ("UNRATE", "us_unemployment", "%"),
                ("CPIAUCSL", "us_cpi", "index"),
                ("UMCSENT", "us_consumer_sentiment", "index"),
            ]
        },
        category="macro",
    ),
)

# ---------------------------------------------------------------------------
# Macro field specs
# ---------------------------------------------------------------------------

_US_MACRO_FIELDS: tuple[MacroFieldSpec, ...] = (
    MacroFieldSpec("spx_level", "S&P 500", 5_200.0, "index"),
    MacroFieldSpec("ndx_level", "NASDAQ Composite", 16_500.0, "index"),
    MacroFieldSpec("vix_level", "VIX", 18.0, "index"),
    MacroFieldSpec("fed_funds_rate", "Fed Funds Rate", 5.25, "%"),
    MacroFieldSpec("us_10y_yield", "10Y Treasury Yield", 4.25, "%"),
    MacroFieldSpec("us_unemployment", "US Unemployment", 3.7, "%"),
    MacroFieldSpec("us_cpi_yoy", "US CPI YoY", 3.1, "%"),
    MacroFieldSpec("us_consumer_confidence", "Consumer Confidence", 102.0, "index"),
)

# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

_US_SCENARIOS: tuple[dict[str, str], ...] = (
    {
        "key": "spx_forecast",
        "title_zh": "S&P 500 預測",
        "title_en": "S&P 500 Forecast",
        "desc_en": "Predict S&P 500 movements under different macro scenarios",
        "icon": "📈",
    },
    {
        "key": "fed_policy",
        "title_zh": "聯儲政策影響",
        "title_en": "Fed Policy Impact",
        "desc_en": "Simulate Fed rate decisions and their market impact",
        "icon": "🏦",
    },
    {
        "key": "tech_sector",
        "title_zh": "科技板塊展望",
        "title_en": "Tech Sector Outlook",
        "desc_en": "NASDAQ and tech sector prediction under various conditions",
        "icon": "💻",
    },
    {
        "key": "recession_risk",
        "title_zh": "衰退概率",
        "title_en": "Recession Probability",
        "desc_en": "Monte Carlo recession scenario analysis",
        "icon": "📉",
    },
)

# ---------------------------------------------------------------------------
# Decision thresholds — US-adapted values
# ---------------------------------------------------------------------------

_US_DECISION_THRESHOLDS = DecisionThresholds(
    min_months_down_payment=24,
    stress_test_dti=0.43,           # US conventional mortgage max DTI
    max_borrower_age_plus_tenor=80,  # US mortgages can run to 30yr + older borrowers
    emigration_savings_by_destination=(
        ("canada", 30_000),
        ("uk", 40_000),
        ("australia", 35_000),
        ("germany", 25_000),
        ("japan", 20_000),
    ),
    emigration_savings_default=25_000,
    invest_min_savings=10_000,       # $10K USD threshold for retail investment
    invest_min_openness=0.40,
    child_min_age=20,
    child_max_age=45,
    child_min_income=3_500,         # Monthly USD
    job_min_age=18,
    job_max_age=65,
    job_min_extraversion=0.50,
    job_change_unemploy_threshold=0.05,
    spending_adjust_cpi_threshold=0.030,
    spending_adjust_confidence_low=50.0,
    employment_quit_neuroticism=0.6,
    employment_quit_savings_alt=30_000,
    employment_quit_unemploy_cap=0.04,
    employment_strike_stance=0.6,
    employment_strike_confidence=45.0,
    employment_lie_flat_max_age=35,
    employment_lie_flat_min_age=20,
    employment_lie_flat_openness=0.4,
    employment_lie_flat_conscien=0.4,
    employment_sample_rate=0.05,
    employment_max_per_round=30,
    relocate_price_income_ratio=5,  # US median home price / income ratio ~5x
    relocate_school_min_age=28,
    relocate_school_max_age=50,
    relocate_gentrify_income_cap=5_000,
    relocate_gentrify_price_floor=2_000,
    relocate_sample_rate=0.08,
    relocate_max_per_round=40,
)

# ---------------------------------------------------------------------------
# Macro impact deltas — US-adapted
# ---------------------------------------------------------------------------

_US_MACRO_IMPACT_DELTAS = MacroImpactDeltas(
    buy_property_ccl_delta=0.3,
    emigrate_net_mig_delta=-50,
    invest_stocks_hsi_delta=0.0,
    have_child_confidence_delta=0.2,
    adjust_spending_confidence_delta=-0.3,
)

# ---------------------------------------------------------------------------
# Macro baselines — US-adapted defaults
# ---------------------------------------------------------------------------

_US_MACRO_BASELINES: dict[str, float] = {
    "consumer_confidence": 55.0,      # Conference Board CCI (neutral ~50-60)
    "unemployment_rate": 0.040,        # ~4% US unemployment
    "gdp_growth": 0.025,               # ~2.5% US GDP growth
    "cpi_yoy": 0.030,                  # ~3% CPI
    "supply_chain_disruption": 0.20,  # Low baseline disruption
    "import_tariff_rate": 0.025,      # ~2.5% average US tariff
    "credit_growth_yoy": 0.06,        # ~6% credit growth
    "interbank_spread": 0.005,        # Low spread baseline
    "mortgage_delinquency": 0.02,     # ~2% delinquency
}

# ---------------------------------------------------------------------------
# Pack construction + registration
# ---------------------------------------------------------------------------

US_MARKETS_PACK = DomainPack(
    id="us_markets",
    name_zh="美國市場",
    name_en="US Markets",
    locale="en-US",
    valid_shock_types=frozenset(s.id for s in _US_SHOCK_SPECS),
    shock_specs=_US_SHOCK_SPECS,
    metrics=_US_METRICS,
    default_forecast_metrics=tuple(m.name for m in _US_METRICS),
    correlated_vars=("spx_close", "us_10y_yield", "fed_funds_rate", "vix_close"),
    mc_default_metrics=("spx_close", "ndx_close", "vix_close", "us_unemployment"),
    macro_baselines=_US_MACRO_BASELINES,
    decision_thresholds=_US_DECISION_THRESHOLDS,
    macro_impact_deltas=_US_MACRO_IMPACT_DELTAS,
    demographics=US_DEMOGRAPHICS,
    data_sources=_US_DATA_SOURCES,
    prompt_locale=EN_US_LOCALE,
    sentiment_lexicon=EN_US_SENTIMENT,
    macro_fields=_US_MACRO_FIELDS,
    scenarios=_US_SCENARIOS,
    keywords=(
        "美股", "wall street", "nasdaq", "s&p", "fed", "inflation",
        "dow jones", "treasury", "us market", "sp500",
    ),
    topic_groups=(
        ("trump", "biden", "election", "congress", "senate", "republican",
         "democrat", "tariff"),
        ("fed", "federal reserve", "rate cut", "rate hike", "fomc", "powell",
         "interest rate"),
    ),
)

DomainPackRegistry.register(US_MARKETS_PACK)
