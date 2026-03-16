"""Rule-based eligibility filters for the Agent Decision Engine.

All functions are pure (no side effects, no LLM calls).  They examine agent
profiles and macro state to determine which agents are eligible for each
decision type, keeping LLM costs low by sending only ~10% of agents for
deliberation.
"""

from __future__ import annotations

import random
from typing import Sequence

from backend.app.models.decision import DecisionType
from backend.app.services.agent_factory import AgentProfile
from backend.app.services.macro_state import MacroState
from backend.app.utils.logger import get_logger

logger = get_logger("decision_rules")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Fraction of eligible agents to sample (cap at MAX_PER_TYPE for cost control)
_ELIGIBLE_SAMPLE_RATE: float = 0.10
_MAX_PER_TYPE: int = 50   # hard cap per decision type per round

# Property thresholds — mortgage rate derived from real HKMA BLR (best lending rate)
_MIN_MONTHS_DOWN_PAYMENT: int = 24         # must have ≥ 24 months income saved
_STRESS_TEST_DTI: float = 0.50             # monthly payment ≤ 50% of income
# HKMA rule: loan maturity + borrower age ≤ 75 (conservative)
_MAX_BORROWER_AGE_PLUS_TENOR: int = 75

# Emigration thresholds — tiered by destination (HKD savings required)
# Source: CIC/ImmD settlement fund requirements + cost-of-living estimates
_EMIGRATION_SAVINGS_BY_DESTINATION: dict[str, int] = {
    "uk": 500_000,        # UK BN(O) visa — high cost of living
    "canada": 500_000,    # Canada PR — settlement fund requirement
    "australia": 500_000, # Australia skilled visa — settlement fund
    "taiwan": 200_000,    # Taiwan investment/work — lower cost of living
    "malaysia": 200_000,  # MM2H — lower cost of living
}
_EMIGRATION_SAVINGS_DEFAULT: int = 350_000  # weighted average for unknown destination

# Investment thresholds
_INVEST_MIN_SAVINGS: int = 100_000
_INVEST_MIN_OPENNESS: float = 0.40

# Child-bearing thresholds
_CHILD_MIN_AGE: int = 25
_CHILD_MAX_AGE: int = 45
_CHILD_MIN_INCOME: int = 20_000  # Source: HK median household income ~$20K needed for child-rearing

# Job change thresholds
_JOB_MIN_AGE: int = 22
_JOB_MAX_AGE: int = 60
_JOB_MIN_EXTRAVERSION: float = 0.50
_JOB_CHANGE_UNEMPLOY_THRESHOLD: float = 0.06  # above this → stress triggers

# Spending adjustment thresholds
# Source: HK average CPI ~2% (2010-2023); 2.5% is above-trend and triggers behaviour change
_SPENDING_ADJUST_CPI_THRESHOLD: float = 0.025  # CPI > 2.5% → likely adjust
_SPENDING_ADJUST_CONFIDENCE_LOW: float = 45.0  # confidence < 45 → likely cut

# Employment change thresholds (Phase 18)
_EMPLOYMENT_QUIT_NEUROTICISM: float = 0.6
_EMPLOYMENT_QUIT_SAVINGS_ALT: int = 300_000     # can quit if this savings even with high unemployment
_EMPLOYMENT_QUIT_UNEMPLOY_CAP: float = 0.05     # below this → safe to quit
_EMPLOYMENT_STRIKE_STANCE: float = 0.6          # political stance threshold for strike
_EMPLOYMENT_STRIKE_CONFIDENCE: float = 40.0     # consumer confidence below this → strike
_EMPLOYMENT_LIE_FLAT_MAX_AGE: int = 35
_EMPLOYMENT_LIE_FLAT_MIN_AGE: int = 22
_EMPLOYMENT_LIE_FLAT_OPENNESS: float = 0.4
_EMPLOYMENT_LIE_FLAT_CONSCIEN: float = 0.4
_EMPLOYMENT_SAMPLE_RATE: float = 0.05
_EMPLOYMENT_MAX_PER_ROUND: int = 30

# Relocate thresholds (Phase 18)
_RELOCATE_PRICE_INCOME_RATIO: int = 15          # avg sqft price > income × this ratio
_RELOCATE_SCHOOL_MIN_AGE: int = 30
_RELOCATE_SCHOOL_MAX_AGE: int = 50
_RELOCATE_GENTRIFY_INCOME_CAP: int = 25_000
_RELOCATE_GENTRIFY_PRICE_FLOOR: int = 15_000   # sqft price threshold for gentrification
_RELOCATE_SAMPLE_RATE: float = 0.08
_RELOCATE_MAX_PER_ROUND: int = 40


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_mortgage_rate(macro_state: MacroState) -> float:
    """Derive mortgage rate from HKMA BLR (best lending rate).

    Uses prime_rate from macro_state (real HKMA data) minus typical bank
    discount (P-1.5%).  If prime_rate is unavailable, uses 6.25% BLR
    (2024-Q4 actual) as the safety default.
    """
    prime = getattr(macro_state, "prime_rate", 0.0625)
    if prime <= 0.01:
        # No real data — use 2024-Q4 HKMA BLR as fallback
        prime = 0.0625
    return prime - 0.015  # P-1.5% typical HK mortgage discount


def _loan_tenor_years(agent_age: int) -> int:
    """Calculate maximum loan tenor per HKMA rule: age + tenor ≤ 75.

    Args:
        agent_age: Borrower's current age.

    Returns:
        Loan tenor in years, capped at 25 (standard HK maximum).
    """
    return min(25, _MAX_BORROWER_AGE_PLUS_TENOR - agent_age)


def _monthly_mortgage_payment(
    property_price: float,
    mortgage_cap: float,
    mortgage_rate: float | None = None,
    agent_age: int = 35,
) -> float:
    """Estimate monthly mortgage payment for a property at *property_price*.

    Uses a simplified annuity formula:
        PMT = P * r / (1 - (1+r)^(-n))
    where P = principal (price × loan_ratio), r = monthly rate, n = payments.
    Loan tenor follows HKMA rule: age + tenor ≤ 75.
    """
    principal = property_price * mortgage_cap
    rate = mortgage_rate if mortgage_rate is not None else 0.0475  # P-1.5% on 6.25% BLR
    monthly_rate = rate / 12
    tenor_years = _loan_tenor_years(agent_age)
    n_payments = tenor_years * 12
    if monthly_rate <= 0 or n_payments <= 0:
        return 0.0
    factor = (1 + monthly_rate) ** n_payments
    return principal * monthly_rate * factor / (factor - 1)


def _district_avg_price(district: str, macro_state: MacroState) -> int:
    """Return average price per sqft for the agent's district."""
    return macro_state.avg_sqft_price.get(district, 13_000)


def _entry_level_flat_size_sqft(income: int) -> float:
    """Rough estimate of entry-level flat size an agent can afford (sqft)."""
    # Typical HK starter flat: 350–500 sqft
    if income >= 40_000:
        return 450.0
    if income >= 25_000:
        return 380.0
    return 320.0


# ---------------------------------------------------------------------------
# Eligibility functions (pure)
# ---------------------------------------------------------------------------

def is_eligible_buy_property(
    profile: AgentProfile, macro_state: MacroState
) -> bool:
    """Return True if the agent meets basic property purchase criteria.

    Criteria:
    - Has employment income (monthly_income > 0)
    - Savings ≥ price × (1 − mortgage_cap) + stamp_duty  (down payment buffer)
    - Stress test: monthly mortgage payment ≤ 50% of gross income
    - Not already owning and underwater (housing_type == '臨時／其他' excluded)
    """
    if profile.monthly_income <= 0:
        return False

    if profile.housing_type == "臨時／其他":
        return False

    # 公屋住戶受租售限制，唔可以同時持有公屋 + 私樓按揭
    if profile.housing_type == "公屋":
        return False

    district_price = _district_avg_price(profile.district, macro_state)
    flat_sqft = _entry_level_flat_size_sqft(profile.monthly_income)
    property_price = district_price * flat_sqft

    # Down payment required = purchase price × (1 - mortgage_cap) + stamp duty
    stamp_duty_rate = macro_state.stamp_duty_rates.get("ad_valorem_scale_2", 0.0375)
    down_payment_needed = property_price * (1.0 - macro_state.mortgage_cap) + property_price * stamp_duty_rate
    if profile.savings < down_payment_needed:
        return False

    # Stress test: monthly payment must not exceed 50% of income
    # Loan tenor follows HKMA rule: borrower age + tenor ≤ 75
    rate = _get_mortgage_rate(macro_state)
    monthly_payment = _monthly_mortgage_payment(
        property_price, macro_state.mortgage_cap, rate, agent_age=profile.age,
    )
    if monthly_payment > profile.monthly_income * _STRESS_TEST_DTI:
        return False

    return True


def is_eligible_emigrate(
    profile: AgentProfile, macro_state: MacroState
) -> bool:
    """Return True if the agent has material motivation and means to emigrate.

    Criteria:
    - Savings ≥ destination-tiered threshold (default $350K weighted average)
    - Age-based probability decay: full eligibility <45, linear decay 45-65, zero >65
    - Geopolitical stress path also requires adequate savings (at least $200K)
    """
    # Age-based probability decay (replaces hard cap at 55)
    # Below 45: full eligibility; 45-65: linear decay; above 65: zero
    if profile.age > 65:
        return False
    p_eligible = 1.0
    if profile.age > 45:
        p_eligible = max(0.0, 1.0 - (profile.age - 45) / 20.0)

    # Financial means: use tiered savings threshold
    savings_threshold = _EMIGRATION_SAVINGS_DEFAULT
    has_means = profile.savings >= savings_threshold

    # Geopolitical stress paths — ALSO require minimum savings ($200K floor)
    min_geopolitical_savings = 200_000
    geopolitical_stress = (
        profile.neuroticism > 0.65
        and macro_state.taiwan_strait_risk > 0.5
        and profile.savings >= min_geopolitical_savings
    )
    trade_stress = (
        profile.neuroticism > 0.70
        and macro_state.us_china_trade_tension > 0.65
        and profile.savings >= min_geopolitical_savings
    )

    if not (has_means or geopolitical_stress or trade_stress):
        return False

    # Apply age-based probability decay via deterministic threshold
    # Use agent hash for reproducible per-agent eligibility
    if p_eligible < 1.0:
        agent_hash = hash((profile.id, profile.district, "emigrate")) % 1000
        if (agent_hash / 1000.0) >= p_eligible:
            return False

    return True


def is_eligible_change_job(
    profile: AgentProfile, macro_state: MacroState
) -> bool:
    """Return True if the agent is in working age and has job-change motivation.

    Criteria:
    - Age 22–60
    - Not retired / student
    - Extraversion > 0.5 (proactive personality) OR unemployment_rate rising (> 6%)
    """
    if not (_JOB_MIN_AGE <= profile.age <= _JOB_MAX_AGE):
        return False
    if profile.occupation in ("退休", "學生"):
        return False
    if profile.monthly_income <= 0:
        return False  # unemployed — not changing jobs, might be seeking

    proactive = profile.extraversion > _JOB_MIN_EXTRAVERSION
    market_stress = macro_state.unemployment_rate > _JOB_CHANGE_UNEMPLOY_THRESHOLD

    return proactive or market_stress


def is_eligible_invest(
    profile: AgentProfile, macro_state: MacroState
) -> bool:
    """Return True if the agent has surplus savings and openness to invest.

    Criteria:
    - Savings > 100,000 HKD
    - Openness > 0.40
    - Has some income (not purely unemployed)
    """
    if profile.savings < _INVEST_MIN_SAVINGS:
        return False
    if profile.openness < _INVEST_MIN_OPENNESS:
        return False
    # Require some baseline financial engagement
    if profile.monthly_income <= 0 and profile.savings < 300_000:
        return False
    return True


def is_eligible_have_child(
    profile: AgentProfile, macro_state: MacroState
) -> bool:
    """Return True if the agent is in child-bearing age with financial means.

    Criteria:
    - Age 25–45
    - Married (已婚)
    - Monthly income ≥ 20,000 HKD (HK median household income threshold)
    """
    if not (_CHILD_MIN_AGE <= profile.age <= _CHILD_MAX_AGE):
        return False
    if profile.marital_status != "已婚":
        return False
    if profile.monthly_income < _CHILD_MIN_INCOME:
        return False
    return True


def is_eligible_adjust_spending(
    profile: AgentProfile, macro_state: MacroState
) -> bool:
    """Return True if macro conditions suggest spending adjustment is relevant.

    Most agents can adjust spending; we filter to those most likely to act:
    - High inflation (CPI > 2.5%, above HK trend average) → cut / save
    - Low consumer confidence (< 45) → cut
    - High confidence (> 75) → spend more
    - Any employed agent with income > 0
    """
    if profile.monthly_income <= 0:
        return False

    high_inflation = macro_state.cpi_yoy > _SPENDING_ADJUST_CPI_THRESHOLD
    low_confidence = macro_state.consumer_confidence < _SPENDING_ADJUST_CONFIDENCE_LOW
    high_confidence = macro_state.consumer_confidence > 75.0

    return high_inflation or low_confidence or high_confidence


def is_eligible_employment_change(
    profile: AgentProfile, macro_state: MacroState
) -> bool:
    """Return True if the agent is eligible for an employment change decision.

    Covers quit, strike, lie-flat, seek employment, and maintain actions.

    Criteria:
    - Must be employed (income > 0) or unemployed seeking work (seek_employment path)
    - Not retired or student
    - Age 22–60
    - Sample rate 5%, cap 30

    Specific paths:
    - quit:             neuroticism > 0.6 AND (unemployment < 5% OR savings > 300K)
    - strike:           political_stance > 0.6 AND consumer_confidence < 40
    - lie_flat:         age 22-35 AND openness < 0.4 AND conscientiousness < 0.4
    - seek_employment:  income == 0 AND age 22-60
    """
    if profile.occupation in ("退休", "學生"):
        return False
    if not (22 <= profile.age <= 60):
        return False

    # quit path
    if (
        profile.monthly_income > 0
        and profile.neuroticism > _EMPLOYMENT_QUIT_NEUROTICISM
        and (
            macro_state.unemployment_rate < _EMPLOYMENT_QUIT_UNEMPLOY_CAP
            or profile.savings > _EMPLOYMENT_QUIT_SAVINGS_ALT
        )
    ):
        return True

    # strike path
    if (
        profile.monthly_income > 0
        and profile.political_stance > _EMPLOYMENT_STRIKE_STANCE
        and macro_state.consumer_confidence < _EMPLOYMENT_STRIKE_CONFIDENCE
    ):
        return True

    # lie_flat path (躺平 — disengage from work)
    if (
        _EMPLOYMENT_LIE_FLAT_MIN_AGE <= profile.age <= _EMPLOYMENT_LIE_FLAT_MAX_AGE
        and profile.openness < _EMPLOYMENT_LIE_FLAT_OPENNESS
        and profile.conscientiousness < _EMPLOYMENT_LIE_FLAT_CONSCIEN
    ):
        return True

    # seek_employment path (currently unemployed, working age)
    if profile.monthly_income == 0 and 22 <= profile.age <= 60:
        return True

    return False


def is_eligible_relocate(
    profile: AgentProfile, macro_state: MacroState
) -> bool:
    """Return True if the agent is eligible for an intra-HK relocation decision.

    Criteria (any one triggers eligibility):
    - Rent pressure: district avg_sqft_price > income × 15
    - School need: married, age 30-50, has child-bearing motivation
    - Gentrification pressure: income < 25K AND district price > 15K/sqft

    Hard exclusion:
    - 公屋 residents (regulated housing — cannot freely relocate)

    Sample rate 8%, cap 40.
    """
    if profile.housing_type == "公屋":
        return False

    district_price = macro_state.avg_sqft_price.get(profile.district, 13_000)

    # Rent pressure path
    if profile.monthly_income > 0:
        if district_price > profile.monthly_income * _RELOCATE_PRICE_INCOME_RATIO:
            return True

    # School need path
    if (
        profile.marital_status == "已婚"
        and _RELOCATE_SCHOOL_MIN_AGE <= profile.age <= _RELOCATE_SCHOOL_MAX_AGE
    ):
        return True

    # Gentrification displacement path
    if (
        profile.monthly_income < _RELOCATE_GENTRIFY_INCOME_CAP
        and district_price > _RELOCATE_GENTRIFY_PRICE_FLOOR
    ):
        return True

    return False


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_ELIGIBILITY_CHECKS: dict[str, object] = {
    DecisionType.BUY_PROPERTY: is_eligible_buy_property,
    DecisionType.EMIGRATE: is_eligible_emigrate,
    DecisionType.CHANGE_JOB: is_eligible_change_job,
    DecisionType.INVEST: is_eligible_invest,
    DecisionType.HAVE_CHILD: is_eligible_have_child,
    DecisionType.ADJUST_SPENDING: is_eligible_adjust_spending,
    DecisionType.EMPLOYMENT_CHANGE: is_eligible_employment_change,
    DecisionType.RELOCATE: is_eligible_relocate,
}


def filter_eligible_agents(
    profiles: Sequence[AgentProfile],
    macro_state: MacroState,
    decision_type: str,
    sample_rate: float = _ELIGIBLE_SAMPLE_RATE,
    max_agents: int = _MAX_PER_TYPE,
    rng_seed: int | None = None,
    thresholds: object | None = None,
) -> list[AgentProfile]:
    """Return a sampled list of eligible agents for *decision_type*.

    Steps:
    1. Apply the appropriate eligibility check (zero LLM cost).
    2. Randomly sample `sample_rate` fraction of eligible agents.
    3. Cap at `max_agents` to control LLM cost.

    Args:
        profiles: Full list of agent profiles in the session.
        macro_state: Current macro-economic state.
        decision_type: One of ``DecisionType`` values.
        sample_rate: Fraction of eligible agents to include (default 10%).
        max_agents: Hard cap (default 50).
        rng_seed: Optional seed for reproducible sampling.

    Returns:
        List of sampled eligible agent profiles.
    """
    check_fn = _ELIGIBILITY_CHECKS.get(decision_type)
    if check_fn is None:
        logger.warning("No eligibility check for decision_type=%s", decision_type)
        return []

    eligible: list[AgentProfile] = [
        p for p in profiles
        if check_fn(p, macro_state)  # type: ignore[operator]
    ]

    if not eligible:
        logger.debug(
            "No eligible agents for decision_type=%s (total=%d)",
            decision_type,
            len(profiles),
        )
        return []

    # Sample
    rng = random.Random(rng_seed)
    k = max(1, int(len(eligible) * sample_rate))
    k = min(k, max_agents, len(eligible))
    sampled = rng.sample(eligible, k)

    logger.debug(
        "decision_type=%s eligible=%d sampled=%d (rate=%.0f%%)",
        decision_type,
        len(eligible),
        len(sampled),
        sample_rate * 100,
    )
    return sampled
