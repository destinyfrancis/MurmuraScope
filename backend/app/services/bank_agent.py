"""Bank & credit cycle agent for MurmuraScope.

Models the Hong Kong banking system's credit cycle, including loan-to-deposit
ratios, NPL dynamics, credit impulse, and HKMA prudential constraints (LTV
caps, countercyclical buffers).

Also models retail credit decisions (mortgage assessment) and credit crunch
signalling, enabling household agent buy_property decisions to be gated by
dynamic bank lending policy.

All state transitions produce new frozen dataclass instances via
``dataclasses.replace()`` -- no mutation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers (defined first; used throughout module)
# ---------------------------------------------------------------------------


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# HKMA prudential bounds
_LTV_CAP_MIN: float = 0.40  # HKMA has historically tightened to 40%
_LTV_CAP_MAX: float = 0.70  # post-relaxation (2024) max
_LTD_MIN: float = 0.50  # structural floor
_LTD_MAX: float = 0.95  # HKMA soft ceiling

# Credit cycle sensitivity parameters
_HIBOR_SPREAD_SENSITIVITY: float = 0.8  # spread moves ~80% of HIBOR delta
_NPL_UNEMPLOYMENT_COEFF: float = 0.4  # 1pp unemployment → 0.4pp NPL
_NPL_PROPERTY_COEFF: float = 0.3  # 10% CCL drop → 0.3pp NPL increase
_CREDIT_IMPULSE_GDP_POS: float = 0.001  # +1% credit impulse → +0.1% GDP
_CREDIT_IMPULSE_GDP_NEG: float = 0.0015  # -1% credit impulse → -0.15% GDP (asymmetric)
_NPL_HSI_DRAG_THRESHOLD: float = 0.03  # NPL > 3% → HSI drag
_NPL_HSI_DRAG_PER_PCT: float = 100.0  # -100 HSI per 1% NPL above threshold
_SPREAD_UNEMPLOYMENT_COEFF: float = 0.002  # high spread → business cost → unemployment

# Retail mortgage constants
_HKMA_MAX_LTV: float = 0.70  # 70% for properties < HK$10M (2024 relaxation)
_HKMA_MIN_RESERVE_RATIO: float = 0.08  # Basel III Tier-1 minimum
_CRISIS_LTV_FLOOR: float = 0.40  # matches _LTV_CAP_MIN above


# ---------------------------------------------------------------------------
# BankState frozen dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BankState:
    """Immutable snapshot of the HK banking system state.

    All monetary values in HKD billions unless stated otherwise.
    """

    # System-level balance sheet
    total_loans_bn: float = 11_000.0  # HK total loans ~HKD 11 trillion
    total_deposits_bn: float = 15_000.0  # HK total deposits ~HKD 15 trillion
    loan_to_deposit_ratio: float = 0.733  # LTD ratio
    mortgage_book_bn: float = 1_800.0  # mortgage book ~HKD 1.8 trillion
    reserve_ratio: float = 0.08  # 8%
    npl_ratio: float = 0.015  # ~1.5%
    credit_impulse: float = 0.0  # d(credit_growth)/dt
    credit_growth_yoy: float = 0.02  # 2% YoY
    interbank_spread: float = 0.005  # 50bps
    ltv_cap: float = 0.60  # HKMA LTV cap

    # Retail / agent-facing fields
    bank_id: str = "representative_hk_bank"
    systemic_risk_score: float = 0.0  # 0.0 = safe, 1.0 = crisis

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict for JSON / DB storage."""
        return {
            "bank_id": self.bank_id,
            "total_loans_bn": self.total_loans_bn,
            "total_deposits_bn": self.total_deposits_bn,
            "loan_to_deposit_ratio": self.loan_to_deposit_ratio,
            "mortgage_book_bn": self.mortgage_book_bn,
            "reserve_ratio": self.reserve_ratio,
            "npl_ratio": self.npl_ratio,
            "credit_impulse": self.credit_impulse,
            "credit_growth_yoy": self.credit_growth_yoy,
            "interbank_spread": self.interbank_spread,
            "ltv_cap": self.ltv_cap,
            "systemic_risk_score": self.systemic_risk_score,
        }


# ---------------------------------------------------------------------------
# Retail credit dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CreditDecision:
    """Result of a bank's credit assessment for a single mortgage application."""

    approved: bool
    approved_ltv: float  # actual LTV offered (may be < requested)
    monthly_payment: float
    rejection_reason: str | None  # None if approved
    systemic_risk_score: float


@dataclass(frozen=True)
class CreditCrunchSignal:
    """Signal emitted when the bank significantly tightens lending policy."""

    bank_id: str
    severity: str  # 'mild' | 'moderate' | 'severe'
    ltv_reduction: float  # absolute reduction in LTV cap
    estimated_demand_suppression: float  # fraction of buyers priced out (0-1)


# ---------------------------------------------------------------------------
# BankAgent
# ---------------------------------------------------------------------------


class BankAgent:
    """Models the HK banking system credit cycle.

    Maintains an internal ``BankState`` that evolves each round based on
    macro indicators (HIBOR, CCL, unemployment).  Produces macro feedback
    adjustments that can be applied to ``MacroState``.

    Also supports retail mortgage assessment (``assess_mortgage``) and
    credit crunch signalling (``update_from_macro``).
    """

    def __init__(
        self,
        initial_state: BankState | None = None,
        bank_id: str = "representative_hk_bank",
    ) -> None:
        self._state = initial_state or BankState(bank_id=bank_id)

    @property
    def state(self) -> BankState:
        """Return the current (frozen) bank state."""
        return self._state

    # ------------------------------------------------------------------
    # Credit cycle update (system-level)
    # ------------------------------------------------------------------

    def update_credit_cycle(
        self,
        macro_state: Any,
        prev_bank_state: BankState | None = None,
    ) -> BankState:
        """Update the bank state based on current macro conditions.

        Rules:
        - HIBOR rise → interbank spread widens → credit growth slows
        - Property crash (CCL drop > 10%) → NPL rises → LTV tightens
        - Credit impulse = change in credit_growth
        - NPL driven by unemployment + property prices
        - Loan-to-deposit ratio clamped [0.50, 0.95]

        Args:
            macro_state: Current ``MacroState`` frozen dataclass.
            prev_bank_state: Previous bank state to compute deltas from.
                Falls back to ``self._state`` if ``None``.

        Returns:
            New frozen ``BankState`` with updated values.
        """
        state = prev_bank_state or self._state

        hibor = getattr(macro_state, "hibor_1m", 0.02)
        unemployment = getattr(macro_state, "unemployment_rate", 0.035)
        ccl = getattr(macro_state, "ccl_index", 150.0)
        ccl_baseline = 150.0  # approximate 2024-Q1 CCL

        # --- Interbank spread follows HIBOR ---
        hibor_excess = max(hibor - 0.02, 0.0)
        new_spread = round(
            _clamp(0.005 + hibor_excess * _HIBOR_SPREAD_SENSITIVITY, 0.001, 0.05),
            4,
        )

        # --- NPL dynamics ---
        unemp_contribution = max(unemployment - 0.035, 0.0) * _NPL_UNEMPLOYMENT_COEFF * 100
        ccl_drop_pct = max((ccl_baseline - ccl) / ccl_baseline, 0.0)
        property_contribution = ccl_drop_pct * _NPL_PROPERTY_COEFF * 100

        new_npl = round(
            _clamp(
                0.015 + (unemp_contribution + property_contribution) / 100,
                0.005,
                0.15,
            ),
            4,
        )

        # --- Credit growth responds to spread and NPL ---
        spread_drag = (new_spread - 0.005) * 5.0
        npl_drag = max(new_npl - 0.015, 0.0) * 3.0
        new_credit_growth = round(
            _clamp(0.02 - spread_drag - npl_drag, -0.10, 0.15),
            4,
        )

        # --- Credit impulse ---
        new_impulse = round(new_credit_growth - state.credit_growth_yoy, 4)

        # --- LTV cap adjustment (HKMA countercyclical) ---
        new_ltv = state.ltv_cap
        if new_npl > 0.03:
            new_ltv = max(state.ltv_cap - 0.05, _LTV_CAP_MIN)
        elif new_npl < 0.01 and new_credit_growth > 0.0:
            new_ltv = min(state.ltv_cap + 0.02, _LTV_CAP_MAX)
        new_ltv = round(new_ltv, 2)

        # --- Loan-to-deposit ratio ---
        new_ltd = round(
            _clamp(
                state.loan_to_deposit_ratio * (1.0 + new_credit_growth * 0.1),
                _LTD_MIN,
                _LTD_MAX,
            ),
            4,
        )

        # --- Mortgage book ---
        mortgage_growth = new_credit_growth * 0.5
        if ccl_drop_pct > 0.10:
            mortgage_growth -= 0.02
        new_mortgage = round(
            max(state.mortgage_book_bn * (1.0 + mortgage_growth * 0.1), 500.0),
            1,
        )

        # Compute systemic risk score from macro for this round
        systemic_risk = self._compute_systemic_risk(macro_state)

        new_state = replace(
            state,
            loan_to_deposit_ratio=new_ltd,
            mortgage_book_bn=new_mortgage,
            npl_ratio=new_npl,
            credit_impulse=new_impulse,
            credit_growth_yoy=new_credit_growth,
            interbank_spread=new_spread,
            ltv_cap=new_ltv,
            systemic_risk_score=systemic_risk,
        )
        self._state = new_state
        return new_state

    # ------------------------------------------------------------------
    # Retail mortgage assessment
    # ------------------------------------------------------------------

    def update_from_macro(self, macro_state: Any) -> CreditCrunchSignal | None:
        """Update bank state and emit credit crunch signal if LTV tightens >5pp.

        Args:
            macro_state: MacroState or any object with relevant attributes.

        Returns:
            ``CreditCrunchSignal`` if significant tightening occurred, else None.
        """
        old_ltv = self._state.ltv_cap
        self.update_credit_cycle(macro_state)
        new_ltv = self._state.ltv_cap

        ltv_reduction = old_ltv - new_ltv
        if ltv_reduction > 0.05:
            severity = "severe" if ltv_reduction > 0.15 else "moderate" if ltv_reduction > 0.08 else "mild"
            suppression = min(0.8, ltv_reduction * 3.0)
            return CreditCrunchSignal(
                bank_id=self._state.bank_id,
                severity=severity,
                ltv_reduction=round(ltv_reduction, 4),
                estimated_demand_suppression=round(suppression, 4),
            )
        return None

    def assess_mortgage(
        self,
        property_price: float,
        monthly_income: float,
        requested_ltv: float = 0.70,
        loan_term_years: int = 25,
        interest_rate: float = 0.04,
    ) -> CreditDecision:
        """Assess a mortgage application under current bank lending policy.

        Applies:
        1. LTV cap from current ``BankState.ltv_cap``
        2. HKMA debt-service ratio (DSR) limit of 50%

        Args:
            property_price: Property value in HKD.
            monthly_income: Borrower gross monthly income in HKD.
            requested_ltv: LTV ratio requested by borrower (default 70%).
            loan_term_years: Amortisation period (default 25 years).
            interest_rate: Annual interest rate (default 4%).

        Returns:
            Frozen ``CreditDecision``.
        """
        effective_ltv = min(requested_ltv, self._state.ltv_cap)
        loan_amount = property_price * effective_ltv

        monthly_rate = interest_rate / 12
        n = loan_term_years * 12
        if monthly_rate > 0 and n > 0:
            monthly_payment = loan_amount * (monthly_rate * (1 + monthly_rate) ** n) / ((1 + monthly_rate) ** n - 1)
        else:
            monthly_payment = loan_amount / n if n > 0 else 0.0

        dsr = monthly_payment / monthly_income if monthly_income > 0 else 1.0

        if dsr > 0.50:
            return CreditDecision(
                approved=False,
                approved_ltv=0.0,
                monthly_payment=0.0,
                rejection_reason=f"DSR {dsr:.1%} exceeds 50% HKMA limit",
                systemic_risk_score=self._state.systemic_risk_score,
            )

        return CreditDecision(
            approved=True,
            approved_ltv=effective_ltv,
            monthly_payment=round(monthly_payment),
            rejection_reason=None,
            systemic_risk_score=self._state.systemic_risk_score,
        )

    # ------------------------------------------------------------------
    # Macro feedback computation
    # ------------------------------------------------------------------

    def compute_macro_feedback(
        self,
        bank_state: BankState,
        macro_state: Any,
    ) -> dict[str, float]:
        """Compute macro adjustments from credit conditions.

        Feedback channels:
        - credit_impulse > 0 → GDP boost (+0.001 per 1% impulse)
        - credit_impulse < 0 → GDP drag (-0.0015 per 1% impulse) [asymmetric]
        - NPL > 3% → HSI drag (-100 per 1% above 3%)
        - LTV tightening → CCL drag (property cools)
        - High interbank_spread → business costs up → unemployment up

        Args:
            bank_state: Current ``BankState`` snapshot.
            macro_state: Current ``MacroState`` for reference values.

        Returns:
            Dict of field-name -> delta to apply via ``dataclasses.replace()``.
        """
        adjustments: dict[str, float] = {}

        # --- Credit impulse → GDP ---
        if bank_state.credit_impulse > 0:
            gdp_boost = bank_state.credit_impulse * _CREDIT_IMPULSE_GDP_POS * 100
            adjustments["gdp_growth"] = round(gdp_boost, 5)
        elif bank_state.credit_impulse < 0:
            gdp_drag = bank_state.credit_impulse * _CREDIT_IMPULSE_GDP_NEG * 100
            adjustments["gdp_growth"] = round(gdp_drag, 5)

        # --- NPL → HSI drag ---
        npl_excess = bank_state.npl_ratio - _NPL_HSI_DRAG_THRESHOLD
        if npl_excess > 0:
            hsi_drag = -npl_excess * 100 * _NPL_HSI_DRAG_PER_PCT
            adjustments["hsi_level"] = round(hsi_drag, 1)

        # --- LTV tightening → CCL cooling ---
        macro_ltv = getattr(macro_state, "bank_ltv_cap", 0.60)
        ltv_delta = bank_state.ltv_cap - macro_ltv
        if ltv_delta < -0.01:
            ccl_drag = ltv_delta * 5.0
            adjustments["ccl_index"] = round(ccl_drag, 2)

        # --- High spread → unemployment ---
        spread_excess = bank_state.interbank_spread - 0.01  # above 100bps
        if spread_excess > 0:
            unemp_push = spread_excess * _SPREAD_UNEMPLOYMENT_COEFF * 100
            adjustments["unemployment_rate"] = round(unemp_push, 5)

        # --- Sync banking fields to MacroState ---
        adjustments["credit_growth_yoy"] = round(
            bank_state.credit_growth_yoy - getattr(macro_state, "credit_growth_yoy", 0.02),
            4,
        )
        adjustments["interbank_spread"] = round(
            bank_state.interbank_spread - getattr(macro_state, "interbank_spread", 0.005),
            4,
        )
        adjustments["mortgage_delinquency"] = round(
            bank_state.npl_ratio - getattr(macro_state, "mortgage_delinquency", 0.015),
            4,
        )
        if bank_state.ltv_cap != macro_ltv:
            adjustments["bank_ltv_cap"] = round(bank_state.ltv_cap - macro_ltv, 2)

        # Remove zero-delta entries
        return {k: v for k, v in adjustments.items() if abs(v) > 1e-9}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_systemic_risk(self, macro_state: Any) -> float:
        """Compute 0–1 systemic risk score from macro indicators."""
        score = 0.0

        unemp = getattr(macro_state, "unemployment_rate", 0.035)
        score += min(0.25, max(0.0, (unemp - 0.035) / 0.10))

        hsi = getattr(macro_state, "hsi_level", 20_000.0)
        score += min(0.25, max(0.0, (20_000.0 - hsi) / 40_000.0))

        ccl = getattr(macro_state, "ccl_index", 150.0)
        score += min(0.20, max(0.0, (150.0 - ccl) / 250.0))

        gdp = getattr(macro_state, "gdp_growth", 0.02)
        score += min(0.20, max(0.0, (0.0 - gdp) / 0.10))

        conf = getattr(macro_state, "consumer_confidence", 50.0)
        score += min(0.10, max(0.0, (50.0 - conf) / 100.0))

        return min(1.0, score)
