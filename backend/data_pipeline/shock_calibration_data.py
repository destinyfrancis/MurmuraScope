"""Historical shock calibration data for HK macro shocks.

Sources: HKMA, C&SD, RVD, various public records.
All values are approximate observed impacts.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ShockEpisode:
    """An observed HK crisis episode with measured macro impacts."""

    name: str
    period: str  # e.g. "1997-Q3"
    ccl_impact_pct: float  # % change in CCL index
    hsi_impact_pct: float  # % change in HSI
    unemployment_delta_pp: float  # percentage point change
    gdp_impact_pct: float  # % change in GDP growth
    confidence_impact_pct: float  # % change in consumer confidence
    tourist_impact_pct: float  # % change in tourist arrivals
    net_migration_delta: float  # change in thousands
    duration_quarters: int
    notes: str = ""


# ---------------------------------------------------------------------------
# Historical episodes
# ---------------------------------------------------------------------------

ASIAN_FINANCIAL_CRISIS = ShockEpisode(
    name="Asian Financial Crisis",
    period="1997-Q3",
    ccl_impact_pct=-65.0,
    hsi_impact_pct=-60.0,
    unemployment_delta_pp=5.0,
    gdp_impact_pct=-5.0,
    confidence_impact_pct=-40.0,
    tourist_impact_pct=-15.0,
    net_migration_delta=-10.0,
    duration_quarters=8,
    notes="Property crash + currency peg defense",
)

SARS = ShockEpisode(
    name="SARS Outbreak",
    period="2003-Q1",
    ccl_impact_pct=-10.0,
    hsi_impact_pct=-15.0,
    unemployment_delta_pp=2.0,
    gdp_impact_pct=-2.5,
    confidence_impact_pct=-30.0,
    tourist_impact_pct=-70.0,
    net_migration_delta=-5.0,
    duration_quarters=3,
    notes="Short but severe tourism/retail hit",
)

GFC = ShockEpisode(
    name="Global Financial Crisis",
    period="2008-Q4",
    ccl_impact_pct=-20.0,
    hsi_impact_pct=-50.0,
    unemployment_delta_pp=2.5,
    gdp_impact_pct=-2.5,
    confidence_impact_pct=-35.0,
    tourist_impact_pct=-5.0,
    net_migration_delta=-3.0,
    duration_quarters=4,
    notes="Global contagion; HK property recovered faster than equities",
)

OCCUPY_CENTRAL = ShockEpisode(
    name="Occupy Central",
    period="2014-Q3",
    ccl_impact_pct=-2.0,
    hsi_impact_pct=-5.0,
    unemployment_delta_pp=0.2,
    gdp_impact_pct=-0.3,
    confidence_impact_pct=-10.0,
    tourist_impact_pct=-10.0,
    net_migration_delta=-2.0,
    duration_quarters=2,
    notes="Limited economic impact; mainly sentiment",
)

SOCIAL_MOVEMENT_2019 = ShockEpisode(
    name="2019 Social Movement",
    period="2019-Q3",
    ccl_impact_pct=-5.0,
    hsi_impact_pct=-15.0,
    unemployment_delta_pp=1.0,
    gdp_impact_pct=-1.2,
    confidence_impact_pct=-25.0,
    tourist_impact_pct=-80.0,
    net_migration_delta=-15.0,
    duration_quarters=4,
    notes="Tourism collapse; emigration wave started",
)

COVID_2020 = ShockEpisode(
    name="COVID-19 Pandemic",
    period="2020-Q1",
    ccl_impact_pct=-5.0,
    hsi_impact_pct=-20.0,
    unemployment_delta_pp=3.0,
    gdp_impact_pct=-6.0,
    confidence_impact_pct=-35.0,
    tourist_impact_pct=-99.0,
    net_migration_delta=-20.0,
    duration_quarters=8,
    notes="Extended by HK zero-COVID policy until 2023",
)

FED_RATE_HIKE_2022 = ShockEpisode(
    name="Fed Rate Hike Cycle",
    period="2022-Q1",
    ccl_impact_pct=-15.0,
    hsi_impact_pct=-25.0,
    unemployment_delta_pp=0.5,
    gdp_impact_pct=-1.0,
    confidence_impact_pct=-15.0,
    tourist_impact_pct=0.0,
    net_migration_delta=-10.0,
    duration_quarters=6,
    notes="HIBOR +4%; CCL -15%; transaction volume -40%",
)

REOPENING_2023 = ShockEpisode(
    name="Post-COVID Reopening",
    period="2023-Q1",
    ccl_impact_pct=5.0,
    hsi_impact_pct=5.0,
    unemployment_delta_pp=-1.0,
    gdp_impact_pct=3.0,
    confidence_impact_pct=20.0,
    tourist_impact_pct=200.0,
    net_migration_delta=5.0,
    duration_quarters=4,
    notes="Tourist +200%; retail +15%; gradual recovery",
)

ALL_EPISODES: tuple[ShockEpisode, ...] = (
    ASIAN_FINANCIAL_CRISIS,
    SARS,
    GFC,
    OCCUPY_CENTRAL,
    SOCIAL_MOVEMENT_2019,
    COVID_2020,
    FED_RATE_HIKE_2022,
    REOPENING_2023,
)


# ---------------------------------------------------------------------------
# Calibrated shock multipliers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ShockMultiplier:
    """Calibrated multiplier for a specific shock type, derived from historical episodes."""

    shock_type: str
    source_episode: str
    ccl_per_unit: float  # CCL % change per unit of shock
    hsi_per_unit: float
    unemployment_per_unit: float  # pp change per unit
    confidence_per_unit: float  # % change per unit
    gdp_per_unit: float
    notes: str = ""


# Derived multipliers for the 18 shock types.
# "per unit" = per 100bp for rate shocks, per event for discrete shocks.
SHOCK_MULTIPLIERS: dict[str, ShockMultiplier] = {
    "interest_rate_hike": ShockMultiplier(
        shock_type="interest_rate_hike",
        source_episode="Fed Rate Hike 2022-23",
        ccl_per_unit=-3.75,  # per 100bp; 400bp -> -15%
        hsi_per_unit=-6.25,  # per 100bp
        unemployment_per_unit=0.125,
        confidence_per_unit=-3.75,
        gdp_per_unit=-0.25,
        notes="Derived from 2022-23 cycle: 400bp hike -> CCL -15%, HSI -25%",
    ),
    "property_crash": ShockMultiplier(
        shock_type="property_crash",
        source_episode="Asian Financial Crisis 1997",
        ccl_per_unit=-65.0,
        hsi_per_unit=-40.0,
        unemployment_per_unit=4.0,
        confidence_per_unit=-40.0,
        gdp_per_unit=-4.0,
        notes="Extreme scenario; 1997 AFC observed",
    ),
    "pandemic": ShockMultiplier(
        shock_type="pandemic",
        source_episode="COVID-19 2020",
        ccl_per_unit=-5.0,
        hsi_per_unit=-20.0,
        unemployment_per_unit=3.0,
        confidence_per_unit=-35.0,
        gdp_per_unit=-6.0,
        notes="Based on COVID-19 first-year impact",
    ),
    "social_unrest": ShockMultiplier(
        shock_type="social_unrest",
        source_episode="2019 Social Movement",
        ccl_per_unit=-5.0,
        hsi_per_unit=-15.0,
        unemployment_per_unit=1.0,
        confidence_per_unit=-25.0,
        gdp_per_unit=-1.2,
        notes="Based on 2019 movement; tourism severely hit",
    ),
    "fed_rate_hike": ShockMultiplier(
        shock_type="fed_rate_hike",
        source_episode="Fed Rate Hike 2022-23",
        ccl_per_unit=-3.75,
        hsi_per_unit=-6.25,
        unemployment_per_unit=0.125,
        confidence_per_unit=-3.75,
        gdp_per_unit=-0.25,
        notes="HIBOR pass-through ~0.85x of Fed rate change",
    ),
    "tourism_boom": ShockMultiplier(
        shock_type="tourism_boom",
        source_episode="Post-COVID Reopening 2023",
        ccl_per_unit=1.25,
        hsi_per_unit=1.25,
        unemployment_per_unit=-0.25,
        confidence_per_unit=5.0,
        gdp_per_unit=0.75,
        notes="Moderate positive; tourism contributes ~4% of GDP",
    ),
    "tourism_collapse": ShockMultiplier(
        shock_type="tourism_collapse",
        source_episode="SARS 2003 + COVID 2020",
        ccl_per_unit=-2.5,
        hsi_per_unit=-7.5,
        unemployment_per_unit=1.5,
        confidence_per_unit=-15.0,
        gdp_per_unit=-2.0,
        notes="Blend of SARS and COVID tourism impact",
    ),
    "china_slowdown": ShockMultiplier(
        shock_type="china_slowdown",
        source_episode="Estimated from HK-China linkage",
        ccl_per_unit=-3.0,
        hsi_per_unit=-10.0,
        unemployment_per_unit=0.5,
        confidence_per_unit=-10.0,
        gdp_per_unit=-1.5,
        notes="HK GDP ~60% linked to China trade/services",
    ),
    "geopolitical_crisis": ShockMultiplier(
        shock_type="geopolitical_crisis",
        source_episode="2019 Social Movement + estimates",
        ccl_per_unit=-8.0,
        hsi_per_unit=-20.0,
        unemployment_per_unit=1.0,
        confidence_per_unit=-30.0,
        gdp_per_unit=-2.0,
        notes="Severe scenario; capital flight risk",
    ),
    "emigration_wave": ShockMultiplier(
        shock_type="emigration_wave",
        source_episode="2020-2022 observed",
        ccl_per_unit=-3.0,
        hsi_per_unit=-2.0,
        unemployment_per_unit=-0.3,
        confidence_per_unit=-10.0,
        gdp_per_unit=-0.5,
        notes="Net outflow ~100K/yr 2020-22; mixed employment effect",
    ),
    "stock_market_crash": ShockMultiplier(
        shock_type="stock_market_crash",
        source_episode="GFC 2008",
        ccl_per_unit=-10.0,
        hsi_per_unit=-50.0,
        unemployment_per_unit=1.5,
        confidence_per_unit=-30.0,
        gdp_per_unit=-2.0,
        notes="2008 GFC: HSI -50%, spillover to property modest",
    ),
    "positive_policy": ShockMultiplier(
        shock_type="positive_policy",
        source_episode="Various stimulus measures",
        ccl_per_unit=3.0,
        hsi_per_unit=5.0,
        unemployment_per_unit=-0.3,
        confidence_per_unit=10.0,
        gdp_per_unit=0.5,
        notes="Stamp duty cuts, consumption vouchers, etc.",
    ),
    "tariff_war": ShockMultiplier(
        shock_type="tariff_war",
        source_episode="US-China trade war 2018-19",
        ccl_per_unit=-2.0,
        hsi_per_unit=-10.0,
        unemployment_per_unit=0.5,
        confidence_per_unit=-15.0,
        gdp_per_unit=-1.0,
        notes="HK as trade hub particularly exposed",
    ),
    "supply_chain_disruption": ShockMultiplier(
        shock_type="supply_chain_disruption",
        source_episode="COVID supply chain 2021-22",
        ccl_per_unit=0.0,
        hsi_per_unit=-5.0,
        unemployment_per_unit=0.3,
        confidence_per_unit=-5.0,
        gdp_per_unit=-0.8,
        notes="Moderate; HK is services-dominated",
    ),
    "china_demand_surge": ShockMultiplier(
        shock_type="china_demand_surge",
        source_episode="Pre-2019 mainland spending boom",
        ccl_per_unit=5.0,
        hsi_per_unit=8.0,
        unemployment_per_unit=-0.3,
        confidence_per_unit=10.0,
        gdp_per_unit=1.0,
        notes="Mainland tourist/investor demand boost",
    ),
    "rcep_boost": ShockMultiplier(
        shock_type="rcep_boost",
        source_episode="RCEP implementation estimates",
        ccl_per_unit=1.0,
        hsi_per_unit=3.0,
        unemployment_per_unit=-0.1,
        confidence_per_unit=5.0,
        gdp_per_unit=0.3,
        notes="Modest trade facilitation benefit",
    ),
    "inflation_surge": ShockMultiplier(
        shock_type="inflation_surge",
        source_episode="Various",
        ccl_per_unit=2.0,
        hsi_per_unit=-5.0,
        unemployment_per_unit=0.2,
        confidence_per_unit=-10.0,
        gdp_per_unit=-0.3,
        notes="HK CPI typically moderate; linked to USD peg",
    ),
    "deflation": ShockMultiplier(
        shock_type="deflation",
        source_episode="1999-2004 deflation period",
        ccl_per_unit=-5.0,
        hsi_per_unit=-3.0,
        unemployment_per_unit=0.5,
        confidence_per_unit=-15.0,
        gdp_per_unit=-1.0,
        notes="Extended deflation 1999-2004 post-AFC",
    ),
}
