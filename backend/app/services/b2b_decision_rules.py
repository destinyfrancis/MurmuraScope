"""Rule-based eligibility filters for B2B enterprise decisions (Phase 5).

All functions are pure (no side effects, no LLM calls).  They examine company
profiles and macro state to determine which companies are eligible for each
decision type, keeping LLM costs low by pre-filtering candidates.
"""

from __future__ import annotations

import random
from typing import Sequence

from backend.app.models.company import CompanyDecisionType, CompanyProfile
from backend.app.services.macro_state import MacroState
from backend.app.utils.logger import get_logger

logger = get_logger("b2b_decision_rules")

# ---------------------------------------------------------------------------
# Sampling constants
# ---------------------------------------------------------------------------

_ELIGIBLE_SAMPLE_RATE: float = 0.20   # 20% of eligible companies per decision
_MAX_PER_TYPE: int = 30               # hard cap per decision type per round


def scale_thresholds(company_count: int) -> float:
    """Return a threshold multiplier based on company count.

    Smaller simulations use relaxed thresholds so that decisions can still
    trigger with fewer companies.

    Args:
        company_count: Total number of companies in the simulation.

    Returns:
        Multiplier in (0, 1]: applied to numeric thresholds.
    """
    if company_count <= 20:
        return 0.5
    if company_count <= 50:
        return 0.7
    if company_count <= 100:
        return 0.85
    return 1.0

# ---------------------------------------------------------------------------
# Expand thresholds
# Source: HK GDP trend growth ~2.5% (2010-2023 average)
# ---------------------------------------------------------------------------

_EXPAND_MIN_GDP_GROWTH: float = 0.02       # expand when GDP growth > 2%
_EXPAND_MIN_CONSUMER_CONFIDENCE: float = 55.0  # above neutral sentiment
_EXPAND_MAX_TARIFF: float = 0.15           # don't expand if tariffs very high

# ---------------------------------------------------------------------------
# Contract thresholds
# Source: HK trade exposure — 60%+ of GDP is re-export/entrepot trade
# ---------------------------------------------------------------------------

_CONTRACT_MIN_TARIFF: float = 0.08         # tariff friction threshold
_CONTRACT_MIN_LOGISTICS_COST: float = 1.20  # index > 1.20 = +20% above baseline
_CONTRACT_MIN_CHINA_EXPOSURE: float = 0.50  # >50% revenue from China trade
_CONTRACT_MIN_DISRUPTION: float = 0.30     # supply chain disruption severity

# ---------------------------------------------------------------------------
# Relocate thresholds
# ---------------------------------------------------------------------------

_RELOCATE_MIN_DISRUPTION: float = 0.50     # severe disruption → consider relocate
_RELOCATE_MIN_CHINA_EXPOSURE: float = 0.70  # highly China-dependent
_RELOCATE_GEOPOLITICAL_RISK: float = 0.60  # taiwan_strait_risk threshold

# ---------------------------------------------------------------------------
# Hire thresholds
# Source: HK structural unemployment ~3% (C&SD 2015-2023 average)
# ---------------------------------------------------------------------------

_HIRE_MAX_UNEMPLOYMENT: float = 0.035      # hire when unemployment < 3.5% (tight labour)
_HIRE_MIN_GDP: float = 0.025              # GDP growth > 2.5% signals expansion
_HIRE_MIN_CONFIDENCE: float = 60.0         # above neutral consumer sentiment

# ---------------------------------------------------------------------------
# Layoff thresholds
# Source: HK recession definition — GDP < 1% typically triggers restructuring
# ---------------------------------------------------------------------------

_LAYOFF_MAX_GDP: float = 0.01             # layoff when GDP growth < 1%
_LAYOFF_MIN_TARIFF: float = 0.10          # tariff pressure threshold
_LAYOFF_MIN_DISRUPTION: float = 0.40      # significant supply chain disruption
_LAYOFF_MIN_COMPANY_EXPOSURE: float = 0.45  # company must be exposed to China trade

# ---------------------------------------------------------------------------
# Stockpile thresholds
# Source: HK logistics hub — manufacturing/import-export sensitive to disruption
# ---------------------------------------------------------------------------

_STOCKPILE_MIN_DISRUPTION: float = 0.25    # pre-emptive stockpiling threshold
_STOCKPILE_MIN_LOGISTICS_COST: float = 1.10  # +10% logistics cost triggers action
_STOCKPILE_RELEVANT_SECTORS: frozenset[str] = frozenset(
    {"manufacturing", "import_export", "retail", "logistics"}
)

# ---------------------------------------------------------------------------
# Enter/Exit market thresholds
# Source: HK startup ecosystem — 4,000+ startups (InvestHK 2023 survey)
# ---------------------------------------------------------------------------

_ENTER_MARKET_MIN_GDP: float = 0.03       # strong growth needed to enter
_ENTER_MARKET_STARTUP_SIZES: frozenset[str] = frozenset({"startup", "sme"})
_EXIT_MARKET_MAX_GDP: float = 0.005        # near-zero growth → exit trigger
_EXIT_MARKET_MIN_TARIFF: float = 0.12      # high tariffs compress margins


# ---------------------------------------------------------------------------
# Eligibility functions (pure)
# ---------------------------------------------------------------------------


def should_expand(
    company: CompanyProfile,
    macro_state: MacroState,
    company_count: int = 100,
) -> bool:
    """Return True if macro conditions support business expansion.

    Criteria (scaled by company count):
    - GDP growth > 2% * scale
    - Consumer confidence > 55 * scale
    - Tariff rate < 15% / scale (inverted — lower scale = more lenient)
    - No major supply chain disruption (< 30% / scale)
    """
    s = scale_thresholds(company_count)
    if macro_state.gdp_growth < _EXPAND_MIN_GDP_GROWTH * s:
        return False
    if macro_state.consumer_confidence < _EXPAND_MIN_CONSUMER_CONFIDENCE * s:
        return False
    if macro_state.import_tariff_rate > _EXPAND_MAX_TARIFF / s:
        return False
    if macro_state.supply_chain_disruption > _CONTRACT_MIN_DISRUPTION / s:
        return False
    return True


def should_contract(
    company: CompanyProfile,
    macro_state: MacroState,
    company_count: int = 100,
) -> bool:
    """Return True if macro conditions force business contraction.

    Criteria (any two of, thresholds scaled by company count):
    - Import tariff rate > 8% * scale  AND  company is China-exposed (> 50% * scale)
    - Logistics cost index > 1.20 * scale
    - Supply chain disruption > 30% * scale
    - GDP growth negative or flat (< 1% / scale)
    """
    s = scale_thresholds(company_count)
    signals = 0
    if (
        macro_state.import_tariff_rate > _CONTRACT_MIN_TARIFF * s
        and company.china_exposure > _CONTRACT_MIN_CHINA_EXPOSURE * s
    ):
        signals += 1
    if macro_state.export_logistics_cost > _CONTRACT_MIN_LOGISTICS_COST * s:
        signals += 1
    if macro_state.supply_chain_disruption > _CONTRACT_MIN_DISRUPTION * s:
        signals += 1
    if macro_state.gdp_growth < _LAYOFF_MAX_GDP / s:
        signals += 1
    return signals >= 2


def should_relocate(
    company: CompanyProfile,
    macro_state: MacroState,
    company_count: int = 100,
) -> bool:
    """Return True if conditions motivate supply chain relocation.

    Criteria (scaled):
    - Supply chain disruption severity > 50% * scale
    - Company china_exposure > 70% * scale
    - OR Taiwan strait risk > 60% * scale  AND  company china_exposure > 50% * scale
    """
    s = scale_thresholds(company_count)
    severe_disruption = (
        macro_state.supply_chain_disruption > _RELOCATE_MIN_DISRUPTION * s
        and company.china_exposure > _RELOCATE_MIN_CHINA_EXPOSURE * s
    )
    geopolitical = (
        macro_state.taiwan_strait_risk > _RELOCATE_GEOPOLITICAL_RISK * s
        and company.china_exposure > _CONTRACT_MIN_CHINA_EXPOSURE * s
    )
    return severe_disruption or geopolitical


def should_hire(
    company: CompanyProfile,
    macro_state: MacroState,
    company_count: int = 100,
) -> bool:
    """Return True if conditions support headcount expansion.

    Criteria (scaled):
    - Unemployment rate < 4.5% / scale (more lenient for small sims)
    - GDP growth > 2.5% * scale
    - Consumer confidence > 60 * scale
    - Company is in growth sector (tech, finance, retail)
    """
    s = scale_thresholds(company_count)
    if macro_state.unemployment_rate >= _HIRE_MAX_UNEMPLOYMENT / s:
        return False
    if macro_state.gdp_growth < _HIRE_MIN_GDP * s:
        return False
    if macro_state.consumer_confidence < _HIRE_MIN_CONFIDENCE * s:
        return False
    # Growth sectors or MNCs more likely to hire
    if company.industry_sector in ("tech", "finance", "retail") or company.company_size == "mnc":
        return True
    # Other sectors hire only in strong conditions
    return macro_state.gdp_growth > 0.04 * s


def should_layoff(
    company: CompanyProfile,
    macro_state: MacroState,
    company_count: int = 100,
) -> bool:
    """Return True if conditions force workforce reduction.

    Criteria (scaled):
    - GDP growth < 1% / scale  OR  tariff rate > 10% * scale for exposed companies
    - Company has significant China/export exposure
    - Supply chain disruption > 40% * scale
    """
    s = scale_thresholds(company_count)
    weak_economy = macro_state.gdp_growth < _LAYOFF_MAX_GDP / s
    tariff_pressure = (
        macro_state.import_tariff_rate > _LAYOFF_MIN_TARIFF * s
        and company.china_exposure > _LAYOFF_MIN_COMPANY_EXPOSURE * s
    )
    disruption_pressure = (
        macro_state.supply_chain_disruption > _LAYOFF_MIN_DISRUPTION * s
        and company.export_ratio > 0.3 * s
    )
    return (weak_economy or tariff_pressure) and (disruption_pressure or tariff_pressure)


def should_stockpile(
    company: CompanyProfile,
    macro_state: MacroState,
    company_count: int = 100,
) -> bool:
    """Return True if conditions motivate inventory stockpiling.

    Criteria (scaled):
    - Company is in a goods-handling sector
    - Supply chain disruption > 25% * scale OR logistics cost > 1.10 * scale
    - China import demand signal suggests shortages ahead
    """
    if company.industry_sector not in _STOCKPILE_RELEVANT_SECTORS:
        return False
    s = scale_thresholds(company_count)
    cost_pressure = macro_state.export_logistics_cost > _STOCKPILE_MIN_LOGISTICS_COST * s
    disruption_risk = macro_state.supply_chain_disruption > _STOCKPILE_MIN_DISRUPTION * s
    demand_signal = macro_state.china_import_demand < -0.05  # falling demand → oversupply risk
    return (cost_pressure or disruption_risk) and not demand_signal


def should_enter_market(
    company: CompanyProfile,
    macro_state: MacroState,
    company_count: int = 100,
) -> bool:
    """Return True if conditions support entering a new market.

    Criteria (scaled):
    - GDP growth > 3% * scale
    - Company is startup or SME (growth-oriented)
    - Low supply chain disruption (< 20% / scale)
    - Trade tension not extreme (< 80% / scale)
    """
    s = scale_thresholds(company_count)
    if macro_state.gdp_growth < _ENTER_MARKET_MIN_GDP * s:
        return False
    if company.company_size not in _ENTER_MARKET_STARTUP_SIZES:
        return False
    if macro_state.supply_chain_disruption > 0.20 / s:
        return False
    if macro_state.us_china_trade_tension > 0.80 / s:
        return False
    return True


def should_exit_market(
    company: CompanyProfile,
    macro_state: MacroState,
    company_count: int = 100,
) -> bool:
    """Return True if conditions force market exit.

    Criteria (scaled):
    - GDP growth near zero (< 0.5% / scale)
    - Tariff rate > 12% * scale
    - Company has high China exposure AND disruption is severe (scaled)
    """
    s = scale_thresholds(company_count)
    stagnant = macro_state.gdp_growth < _EXIT_MARKET_MAX_GDP / s
    tariff_high = macro_state.import_tariff_rate > _EXIT_MARKET_MIN_TARIFF * s
    exposed_and_disrupted = (
        company.china_exposure > 0.65 * s
        and macro_state.supply_chain_disruption > 0.50 * s
    )
    return (stagnant and tariff_high) or exposed_and_disrupted


# ---------------------------------------------------------------------------
# Dispatcher map
# ---------------------------------------------------------------------------

_ELIGIBILITY_CHECKS: dict[str, object] = {
    CompanyDecisionType.EXPAND: should_expand,
    CompanyDecisionType.CONTRACT: should_contract,
    CompanyDecisionType.RELOCATE: should_relocate,
    CompanyDecisionType.HIRE: should_hire,
    CompanyDecisionType.LAYOFF: should_layoff,
    CompanyDecisionType.STOCKPILE: should_stockpile,
    CompanyDecisionType.ENTER_MARKET: should_enter_market,
    CompanyDecisionType.EXIT_MARKET: should_exit_market,
}


# ---------------------------------------------------------------------------
# Filter dispatcher
# ---------------------------------------------------------------------------


def filter_eligible_companies(
    companies: Sequence[CompanyProfile],
    macro_state: MacroState,
    decision_type: str,
    sample_rate: float = _ELIGIBLE_SAMPLE_RATE,
    max_companies: int = _MAX_PER_TYPE,
    rng_seed: int | None = None,
) -> list[CompanyProfile]:
    """Return a sampled list of eligible companies for *decision_type*.

    Steps:
    1. Apply the rule-based eligibility check (zero LLM cost).
    2. Randomly sample `sample_rate` fraction of eligible companies.
    3. Cap at `max_companies` to control LLM cost.

    Args:
        companies: Full list of company profiles for the session.
        macro_state: Current macro-economic state.
        decision_type: One of ``CompanyDecisionType`` values.
        sample_rate: Fraction of eligible companies to include (default 20%).
        max_companies: Hard cap per decision type (default 30).
        rng_seed: Optional seed for reproducible sampling.

    Returns:
        List of sampled eligible company profiles.
    """
    check_fn = _ELIGIBILITY_CHECKS.get(decision_type)
    if check_fn is None:
        logger.warning("No eligibility check for decision_type=%s", decision_type)
        return []

    total = len(companies)
    eligible: list[CompanyProfile] = [
        c for c in companies
        if check_fn(c, macro_state, company_count=total)  # type: ignore[operator]
    ]

    if not eligible:
        logger.debug(
            "No eligible companies for decision_type=%s (total=%d)",
            decision_type,
            len(companies),
        )
        return []

    rng = random.Random(rng_seed)
    k = max(1, int(len(eligible) * sample_rate))
    k = min(k, max_companies, len(eligible))
    sampled = rng.sample(eligible, k)

    logger.debug(
        "B2B decision_type=%s eligible=%d sampled=%d (rate=%.0f%%)",
        decision_type,
        len(eligible),
        len(sampled),
        sample_rate * 100,
    )
    return sampled
