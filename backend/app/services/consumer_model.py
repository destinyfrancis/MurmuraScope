"""B2C Consumer Model for MurmuraScope Phase 4.

Models individual household spending behaviour and aggregates to sector-level
retail forecasts based on agent profiles and macro-economic conditions.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from backend.app.services.agent_factory import AgentProfile
from backend.app.services.macro_state import MacroState
from backend.app.utils.logger import get_logger

logger = get_logger("consumer_model")

# ---------------------------------------------------------------------------
# Life-cycle and wealth effect constants
# ---------------------------------------------------------------------------

# Marginal Propensity to Consume by age band
# Young workers spend more; seniors save more (pension/asset drawdown reliance)
_LIFECYCLE_MPC: dict[str, float] = {"young": 0.85, "middle": 0.65, "senior": 0.50}

# Every 10% wealth change → 1.5% consumption change (empirical HK estimate)
_WEALTH_ELASTICITY: float = 0.15

# CCL wealth effect: 1% rise in property price index → this % rise in consumption
WEALTH_ELASTICITY_CCL: float = 0.08

# Discretionary categories are more sensitive to wealth changes
# Price elasticity estimates for discretionary categories (Engel curve extension).
# Applied when CPI inflation exceeds 3% — quantity_change = elasticity * excess_inflation.
_PRICE_ELASTICITY: dict[str, float] = {
    "entertainment": -1.2,
    "transport": -0.5,
    "education": -0.3,
}

_DISCRETIONARY_CATEGORIES: frozenset[str] = frozenset(
    {"entertainment", "education"}
)
_NECESSITY_CATEGORIES: frozenset[str] = frozenset(
    {"food", "housing", "transport", "healthcare"}
)

# ---------------------------------------------------------------------------
# SpendingProfile
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SpendingProfile:
    """Immutable household spending allocation as a fraction of monthly income.

    All fields are 0–1 fractions.  They should sum to approximately 1.0,
    with ``savings_rate`` representing the portion not consumed.
    """

    food: float             # Food & beverages
    housing: float          # Rent / mortgage payment + utilities
    transport: float        # Public transport, car, taxi
    entertainment: float    # Dining out, leisure, travel
    education: float        # Tuition, courses, books
    healthcare: float       # Medical, insurance premiums
    savings_rate: float     # Fraction saved / invested (residual)

    def __post_init__(self) -> None:
        for field_name in (
            "food", "housing", "transport", "entertainment",
            "education", "healthcare", "savings_rate",
        ):
            val = getattr(self, field_name)
            if not (0.0 <= val <= 1.0):
                raise ValueError(
                    f"SpendingProfile.{field_name} must be in [0, 1], got {val}"
                )

    @property
    def total_consumption_rate(self) -> float:
        """Sum of non-savings fractions."""
        return (
            self.food
            + self.housing
            + self.transport
            + self.entertainment
            + self.education
            + self.healthcare
        )

    def monthly_amounts(self, monthly_income: int) -> dict[str, float]:
        """Return absolute monthly spend (HKD) per category."""
        return {
            "food": self.food * monthly_income,
            "housing": self.housing * monthly_income,
            "transport": self.transport * monthly_income,
            "entertainment": self.entertainment * monthly_income,
            "education": self.education * monthly_income,
            "healthcare": self.healthcare * monthly_income,
            "savings": self.savings_rate * monthly_income,
        }


# ---------------------------------------------------------------------------
# Base spending templates by income bracket
# ---------------------------------------------------------------------------

# Source: C&SD Household Expenditure Survey 2019/20 (approximate)
# Format: (food, housing, transport, entertainment, education, healthcare, savings)
# Keyed by income floor (HKD); agent income mapped to closest bracket via _income_bracket()
_HK_EXPENDITURE_BY_INCOME: dict[int, tuple[float, float, float, float, float, float, float]] = {
    0:      (0.35, 0.25, 0.08, 0.05, 0.02, 0.05, 0.20),
    8000:   (0.32, 0.28, 0.10, 0.06, 0.03, 0.04, 0.17),
    15000:  (0.28, 0.30, 0.10, 0.08, 0.04, 0.04, 0.16),
    25000:  (0.24, 0.30, 0.10, 0.10, 0.05, 0.04, 0.17),
    40000:  (0.20, 0.28, 0.10, 0.12, 0.06, 0.04, 0.20),
    60000:  (0.16, 0.25, 0.09, 0.14, 0.07, 0.05, 0.24),
    100000: (0.12, 0.20, 0.08, 0.15, 0.08, 0.06, 0.31),
}

# Sorted income thresholds for binary-search lookup
_INCOME_THRESHOLDS: tuple[int, ...] = tuple(sorted(_HK_EXPENDITURE_BY_INCOME.keys()))

# Legacy bracket-name mapping (for backward compat with AgentProfile.income_bracket)
_BRACKET_NAME_TO_INCOME: dict[str, int] = {
    "無收入":           0,
    "<$8,000":          0,
    "$8,000-$14,999":   8000,
    "$15,000-$24,999":  15000,
    "$25,000-$39,999":  25000,
    "$40,000-$59,999":  40000,
    "$60,000+":         100000,
}

_DEFAULT_BASE = _HK_EXPENDITURE_BY_INCOME[15000]

# Housing adjustments by housing type
_HOUSING_TYPE_ADJ: dict[str, float] = {
    "公屋": -0.08,           # subsidised rent → lower housing fraction
    "資助出售房屋": -0.04,
    "私人住宅": 0.0,
    "臨時／其他": -0.06,
}

# Age-based spending adjustments (additive to entertainment / education)
_AGE_ENTERTAINMENT_ADJ: dict[str, float] = {
    "young":  0.03,   # 18–34
    "middle": 0.00,   # 35–54
    "senior": -0.04,  # 55+
}
_AGE_EDUCATION_ADJ: dict[str, float] = {
    "young":  0.02,   # more courses / self-improvement
    "middle": 0.03,   # children's education
    "senior": -0.02,
}


# ---------------------------------------------------------------------------
# ConsumerModel
# ---------------------------------------------------------------------------

class ConsumerModel:
    """Models individual household spending and produces retail forecasts."""

    # -----------------------------------------------------------------------
    # Core methods
    # -----------------------------------------------------------------------

    def generate_spending_profile(
        self, profile: AgentProfile, macro_state: MacroState
    ) -> SpendingProfile:
        """Generate a baseline spending profile for a given agent.

        Uses income bracket as starting point, adjusts for housing type,
        age group, and macro conditions (mortgage rate, CPI).

        Args:
            profile: Agent profile (income, housing, age, etc.).
            macro_state: Current macro-economic state.

        Returns:
            Immutable ``SpendingProfile``.
        """
        base = _resolve_spending_base(profile)
        food, housing, transport, entertainment, education, healthcare, savings = base

        # Housing-type adjustment
        housing_adj = _HOUSING_TYPE_ADJ.get(profile.housing_type, 0.0)
        housing = _clamp(housing + housing_adj)
        savings = _clamp(savings - housing_adj)   # offset savings

        # Age group adjustments
        age_band = _age_band(profile.age)
        entertainment = _clamp(entertainment + _AGE_ENTERTAINMENT_ADJ[age_band])
        education = _clamp(education + _AGE_EDUCATION_ADJ[age_band])
        savings = _clamp(savings - _AGE_ENTERTAINMENT_ADJ[age_band] - _AGE_EDUCATION_ADJ[age_band])

        # High mortgage rate → squeeze savings
        if macro_state.hibor_1m > 0.04:
            extra_mortgage_burden = (macro_state.hibor_1m - 0.04) * 2.0
            housing = _clamp(housing + extra_mortgage_burden)
            savings = _clamp(savings - extra_mortgage_burden)

        # High CPI → food costs more
        if macro_state.cpi_yoy > 0.03:
            extra_food = (macro_state.cpi_yoy - 0.03) * 0.8
            food = _clamp(food + extra_food)
            entertainment = _clamp(entertainment - extra_food * 0.5)
            savings = _clamp(savings - extra_food * 0.5)

        # Normalise to ensure total ≤ 1.0
        total_non_savings = food + housing + transport + entertainment + education + healthcare
        if total_non_savings > 0.95:
            scale = 0.95 / total_non_savings
            food *= scale
            housing *= scale
            transport *= scale
            entertainment *= scale
            education *= scale
            healthcare *= scale
            savings = 1.0 - (food + housing + transport + entertainment + education + healthcare)

        return SpendingProfile(
            food=round(food, 4),
            housing=round(housing, 4),
            transport=round(transport, 4),
            entertainment=round(entertainment, 4),
            education=round(education, 4),
            healthcare=round(healthcare, 4),
            savings_rate=round(max(0.0, savings), 4),
        )

    def adjust_spending(
        self,
        spending: SpendingProfile,
        macro_state: MacroState,
        sentiment: str,
        age_band: str = "middle",
        wealth_change_pct: float = 0.0,
    ) -> SpendingProfile:
        """Return an adjusted SpendingProfile based on macro conditions and sentiment.

        Adjustments are applied immutably (returns new profile).

        Args:
            spending: Baseline spending profile.
            macro_state: Current macro-economic state.
            sentiment: "positive", "negative", or "neutral".
            age_band: Life-cycle stage ("young", "middle", "senior").
                Defaults to "middle" for backward compatibility.
            wealth_change_pct: Percentage change in household wealth (e.g. 0.10 = +10%).
                Driven by CCL and HSI movements.  Defaults to 0.0 (no change).

        Returns:
            New ``SpendingProfile`` with adjustments applied.
        """
        entertainment = spending.entertainment
        savings_rate = spending.savings_rate
        food = spending.food
        healthcare = spending.healthcare
        education = spending.education
        transport = spending.transport

        # ------------------------------------------------------------------
        # Wealth effect (life-cycle adjusted)
        # ------------------------------------------------------------------
        if wealth_change_pct != 0.0:
            mpc = _LIFECYCLE_MPC.get(age_band, _LIFECYCLE_MPC["middle"])
            wealth_adjustment = wealth_change_pct * _WEALTH_ELASTICITY * mpc

            # Discretionary categories absorb 70% of the adjustment,
            # necessities absorb the remaining 30%.
            discretionary_adj = wealth_adjustment * 0.7
            necessity_adj = wealth_adjustment * 0.3

            # Apply to discretionary: entertainment and education
            entertainment = _clamp(entertainment * (1.0 + discretionary_adj))
            education = _clamp(education * (1.0 + discretionary_adj))

            # Apply (smaller) to necessities: food, transport
            food = _clamp(food * (1.0 + necessity_adj))
            transport = _clamp(transport * (1.0 + necessity_adj))

            # Savings absorbs the mirror: positive wealth → save less (spend more)
            total_spending_delta = (
                (entertainment - spending.entertainment)
                + (education - spending.education)
                + (food - spending.food)
                + (transport - spending.transport)
            )
            savings_rate = _clamp(savings_rate - total_spending_delta)

        # ------------------------------------------------------------------
        # Sentiment-driven adjustments
        # ------------------------------------------------------------------
        if sentiment == "negative":
            # Cut discretionary; increase savings buffer
            entertainment = _clamp(entertainment * 0.85)
            savings_rate = _clamp(savings_rate + (spending.entertainment - entertainment))
        elif sentiment == "positive":
            # Slightly more spending on entertainment
            extra = spending.savings_rate * 0.05
            entertainment = _clamp(entertainment + extra)
            savings_rate = _clamp(savings_rate - extra)

        # High inflation → squeeze discretionary
        if macro_state.cpi_yoy > 0.04:
            cut = (macro_state.cpi_yoy - 0.04) * 1.5
            entertainment = _clamp(entertainment * (1.0 - cut))
            savings_rate = _clamp(savings_rate - cut * 0.5)
            food = _clamp(food * (1.0 + cut * 0.3))

        # Price elasticity for discretionary categories (Engel curve extension).
        # When inflation exceeds 3%, apply per-category elasticity adjustments.
        if macro_state.cpi_yoy > 0.03:
            inflation_excess = macro_state.cpi_yoy - 0.03
            for category, elasticity in _PRICE_ELASTICITY.items():
                adjustment = max(0.5, 1.0 + elasticity * inflation_excess)
                if category == "entertainment":
                    entertainment = _clamp(entertainment * adjustment)
                elif category == "transport":
                    transport = _clamp(transport * adjustment)
                elif category == "education":
                    education = _clamp(education * adjustment)

        # Property crash (CCL < 100) → renters save more (lower housing costs)
        if macro_state.ccl_index < 100 and spending.housing < 0.20:
            # Renters benefit from lower property prices (lower rents)
            freed = 0.02
            savings_rate = _clamp(savings_rate + freed)
            entertainment = _clamp(entertainment + freed * 0.5)

        # Low consumer confidence → precautionary savings
        if macro_state.consumer_confidence < 40:
            extra_savings = 0.03
            entertainment = _clamp(entertainment - extra_savings)
            savings_rate = _clamp(savings_rate + extra_savings)

        return replace(
            spending,
            food=round(food, 4),
            transport=round(transport, 4),
            entertainment=round(entertainment, 4),
            education=round(education, 4),
            healthcare=round(healthcare, 4),
            savings_rate=round(max(0.0, savings_rate), 4),
        )

    def aggregate_retail_forecast(
        self,
        spending_profiles: Sequence[SpendingProfile],
        incomes: Sequence[int],
    ) -> dict[str, float]:
        """Aggregate individual spending profiles into sector-level retail forecasts.

        Args:
            spending_profiles: List of SpendingProfile objects.
            incomes: Monthly income (HKD) corresponding to each profile.

        Returns:
            Dict with total and per-sector spending (HKD/month), plus
            sector-level YoY change indicators.
        """
        if not spending_profiles:
            return {}

        totals: dict[str, float] = {
            "food": 0.0,
            "housing": 0.0,
            "transport": 0.0,
            "entertainment": 0.0,
            "education": 0.0,
            "healthcare": 0.0,
            "savings": 0.0,
        }
        count = 0

        for sp, income in zip(spending_profiles, incomes):
            if income <= 0:
                continue
            amounts = sp.monthly_amounts(income)
            for sector, amount in amounts.items():
                totals[sector] = totals.get(sector, 0.0) + amount
            count += 1

        if count == 0:
            return {}

        total_spending = sum(v for k, v in totals.items() if k != "savings")
        avg_savings_rate = (
            totals["savings"] / (totals["savings"] + total_spending)
            if (totals["savings"] + total_spending) > 0
            else 0.0
        )

        return {
            "agent_count": count,
            "total_monthly_spending_hkd": round(total_spending, 2),
            "total_monthly_savings_hkd": round(totals["savings"], 2),
            "avg_savings_rate": round(avg_savings_rate, 4),
            "sector_breakdown": {
                sector: round(totals[sector], 2)
                for sector in ("food", "housing", "transport", "entertainment", "education", "healthcare")
            },
            "dominant_sector": max(
                ("food", "housing", "transport", "entertainment", "education", "healthcare"),
                key=lambda s: totals[s],
            ),
        }

    def generate_batch(
        self,
        profiles: Sequence[AgentProfile],
        macro_state: MacroState,
        sentiment_map: dict[int, str] | None = None,
    ) -> list[SpendingProfile]:
        """Generate spending profiles for a batch of agents.

        Args:
            profiles: Agent profiles to process.
            macro_state: Current macro-economic state.
            sentiment_map: Optional mapping of agent_id → sentiment string.

        Returns:
            List of SpendingProfile objects, one per input profile.
        """
        result: list[SpendingProfile] = []
        for p in profiles:
            base = self.generate_spending_profile(p, macro_state)
            sentiment = (sentiment_map or {}).get(p.id, "neutral")
            adjusted = self.adjust_spending(base, macro_state, sentiment)
            result.append(adjusted)
        return result


# ---------------------------------------------------------------------------
# Public lifecycle / wealth API
# ---------------------------------------------------------------------------


def _lifecycle_mpc(age: int) -> float:
    """Marginal propensity to consume by age (lifecycle hypothesis).

    Younger: higher MPC (less savings). Middle: moderate. Older: higher asset
    dependency / drawdown.

    Args:
        age: Agent age in years.

    Returns:
        MPC scalar (>1 means spending exceeds income, i.e. dissaving).
    """
    if age < 30:
        return 1.05   # young, spend more than earn
    elif age < 45:
        return 0.88
    elif age < 60:
        return 0.78
    else:
        return 0.92   # elderly, higher asset drawdown


def compute_spending(
    spending: SpendingProfile,
    monthly_income: int,
    age: int = 40,
    ccl_change: float = 0.0,
) -> dict[str, float]:
    """Compute absolute monthly spending with lifecycle MPC and CCL wealth effect.

    Applies two academic adjustments on top of the base SpendingProfile:

    1. **Lifecycle MPC** — scales total consumption by the age-dependent marginal
       propensity to consume (Modigliani lifecycle hypothesis).
    2. **Wealth effect (CCL)** — a 1% rise in the CCL property price index
       raises total consumption by ``WEALTH_ELASTICITY_CCL`` percent (default
       0.08%, empirically calibrated for HK owner-occupier households).

    Args:
        spending: Base SpendingProfile (fractions of income).
        monthly_income: Gross monthly income in HKD.
        age: Agent age in years (default 40 → MPC = 0.88).
        ccl_change: Percentage change in CCL index (e.g. +5.0 means +5%).
            Positive → wealth gain → higher spending. Default 0.0 (no effect).

    Returns:
        Dict with keys matching ``SpendingProfile.monthly_amounts`` plus
        ``"total_consumption"`` and ``"lifecycle_mpc"`` diagnostics.
    """
    # Base amounts from profile fractions × income
    base_amounts = spending.monthly_amounts(monthly_income)

    # Lifecycle MPC scalar
    mpc = _lifecycle_mpc(age)

    # CCL wealth effect multiplier: (1 + elasticity * ccl_change / 100)
    wealth_multiplier = 1.0 + WEALTH_ELASTICITY_CCL * ccl_change / 100.0

    # Apply both adjustments to consumption categories (not to savings)
    adjusted: dict[str, float] = {}
    total_consumption = 0.0
    for category in ("food", "housing", "transport", "entertainment", "education", "healthcare"):
        raw = base_amounts[category]
        adjusted_amount = raw * mpc * wealth_multiplier
        adjusted[category] = round(adjusted_amount, 2)
        total_consumption += adjusted_amount

    # Savings is the residual (not scaled by MPC/wealth effect directly)
    adjusted["savings"] = round(base_amounts["savings"], 2)
    adjusted["total_consumption"] = round(total_consumption, 2)
    adjusted["lifecycle_mpc"] = mpc
    adjusted["wealth_multiplier"] = round(wealth_multiplier, 6)

    return adjusted


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamp(val: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, val))


def _age_band(age: int) -> str:
    if age < 35:
        return "young"
    if age < 55:
        return "middle"
    return "senior"


def _income_to_bracket(monthly_income: int) -> int:
    """Map agent monthly income to the closest C&SD expenditure bracket floor."""
    best = _INCOME_THRESHOLDS[0]
    for threshold in _INCOME_THRESHOLDS:
        if monthly_income >= threshold:
            best = threshold
        else:
            break
    return best


def _resolve_spending_base(
    profile: AgentProfile,
) -> tuple[float, float, float, float, float, float, float]:
    """Resolve the base spending tuple for an agent.

    Prefers direct income-based lookup from C&SD data.  Falls back to
    bracket name mapping for backward compatibility.
    """
    # Primary: use actual monthly income
    if profile.monthly_income >= 0:
        bracket = _income_to_bracket(profile.monthly_income)
        result = _HK_EXPENDITURE_BY_INCOME.get(bracket)
        if result is not None:
            return result

    # Fallback: legacy bracket name
    bracket_name = getattr(profile, "income_bracket", "")
    income_floor = _BRACKET_NAME_TO_INCOME.get(bracket_name, 15000)
    return _HK_EXPENDITURE_BY_INCOME.get(income_floor, _DEFAULT_BASE)
