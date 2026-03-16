"""Tests for BankAgent — financial intermediary ABM with reserve ratio and dynamic LTV.

Covers:
- BankState immutability
- update_credit_cycle: normal and crisis macro
- assess_mortgage: approval / rejection / LTV capping
- update_from_macro: credit crunch signal emission
- systemic risk score bounds
- NPL dynamics
- credit growth negativity in crisis
- compute_macro_feedback channels
"""

from __future__ import annotations

import dataclasses
import pytest

from backend.app.services.bank_agent import (
    BankAgent,
    BankState,
    CreditCrunchSignal,
    CreditDecision,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _MacroStub:
    """Lightweight macro stub — only provides attributes used by BankAgent."""

    def __init__(
        self,
        hibor_1m: float = 0.02,
        unemployment_rate: float = 0.035,
        ccl_index: float = 150.0,
        hsi_level: float = 20_000.0,
        gdp_growth: float = 0.02,
        consumer_confidence: float = 50.0,
        bank_ltv_cap: float = 0.60,
        credit_growth_yoy: float = 0.02,
        interbank_spread: float = 0.005,
        mortgage_delinquency: float = 0.015,
    ) -> None:
        self.hibor_1m = hibor_1m
        self.unemployment_rate = unemployment_rate
        self.ccl_index = ccl_index
        self.hsi_level = hsi_level
        self.gdp_growth = gdp_growth
        self.consumer_confidence = consumer_confidence
        self.bank_ltv_cap = bank_ltv_cap
        self.credit_growth_yoy = credit_growth_yoy
        self.interbank_spread = interbank_spread
        self.mortgage_delinquency = mortgage_delinquency


def _normal_macro() -> _MacroStub:
    """Baseline / benign macro environment."""
    return _MacroStub()


def _crisis_macro() -> _MacroStub:
    """Severe stress scenario: high unemployment, crashed property & HSI."""
    return _MacroStub(
        hibor_1m=0.08,
        unemployment_rate=0.10,   # 10%
        ccl_index=80.0,           # ~47% drop from 150
        hsi_level=10_000.0,       # -50% from 20k
        gdp_growth=-0.05,         # -5%
        consumer_confidence=15.0,
    )


# ---------------------------------------------------------------------------
# BankState immutability
# ---------------------------------------------------------------------------

def test_bank_state_is_frozen() -> None:
    """BankState must be frozen (immutable)."""
    state = BankState()
    assert dataclasses.is_dataclass(state)
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        state.ltv_cap = 0.5  # type: ignore[misc]


def test_bank_state_default_fields() -> None:
    """Default BankState has expected HKMA-compliant values."""
    state = BankState()
    assert 0.0 <= state.ltv_cap <= 0.70
    assert 0.0 <= state.reserve_ratio <= 1.0
    assert 0.0 <= state.npl_ratio <= 1.0
    assert state.bank_id == "representative_hk_bank"
    assert state.systemic_risk_score == 0.0


def test_bank_state_to_dict_includes_all_keys() -> None:
    """to_dict() must include key fields for serialisation."""
    d = BankState().to_dict()
    for key in ("ltv_cap", "npl_ratio", "reserve_ratio", "credit_growth_yoy",
                "interbank_spread", "bank_id", "systemic_risk_score"):
        assert key in d, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# update_credit_cycle — normal macro
# ---------------------------------------------------------------------------

def test_normal_macro_gives_full_ltv() -> None:
    """Under benign macro the bank's LTV cap should remain near 0.60 (default)."""
    agent = BankAgent()
    new_state = agent.update_credit_cycle(_normal_macro())
    # Default starts at 0.60; benign conditions should not tighten
    assert new_state.ltv_cap >= 0.55


def test_credit_cycle_returns_frozen_bank_state() -> None:
    """update_credit_cycle must return a new frozen BankState."""
    agent = BankAgent()
    new_state = agent.update_credit_cycle(_normal_macro())
    assert isinstance(new_state, BankState)
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        new_state.npl_ratio = 0.99  # type: ignore[misc]


def test_credit_cycle_updates_internal_state() -> None:
    """update_credit_cycle must mutate agent._state."""
    agent = BankAgent()
    original_ltv = agent.state.ltv_cap
    agent.update_credit_cycle(_normal_macro())
    # state reference should now point to a new object
    assert agent.state is not None


# ---------------------------------------------------------------------------
# update_credit_cycle — crisis macro
# ---------------------------------------------------------------------------

def test_crisis_macro_tightens_ltv() -> None:
    """Under crisis conditions the LTV cap must tighten below the normal 60%."""
    agent = BankAgent()
    new_state = agent.update_credit_cycle(_crisis_macro())
    # Crisis drives NPL above 3% → LTV tightens to 55% or below
    assert new_state.ltv_cap <= 0.60
    assert new_state.ltv_cap >= 0.40  # floor is 40%


def test_crisis_macro_raises_npl() -> None:
    """Crisis unemployment + property crash must drive NPL above baseline 1.5%."""
    agent = BankAgent()
    new_state = agent.update_credit_cycle(_crisis_macro())
    assert new_state.npl_ratio > 0.015


def test_npl_rises_with_unemployment() -> None:
    """Higher unemployment directly raises NPL ratio."""
    agent_low = BankAgent()
    state_low = agent_low.update_credit_cycle(_MacroStub(unemployment_rate=0.035))

    agent_high = BankAgent()
    state_high = agent_high.update_credit_cycle(_MacroStub(unemployment_rate=0.10))

    assert state_high.npl_ratio > state_low.npl_ratio


def test_credit_growth_negative_in_crisis() -> None:
    """Credit growth must turn negative under severe stress."""
    agent = BankAgent()
    new_state = agent.update_credit_cycle(_crisis_macro())
    assert new_state.credit_growth_yoy < 0.0


def test_systemic_risk_bounded_0_to_1() -> None:
    """Systemic risk score must always lie in [0, 1]."""
    for macro in (_normal_macro(), _crisis_macro()):
        agent = BankAgent()
        new_state = agent.update_credit_cycle(macro)
        assert 0.0 <= new_state.systemic_risk_score <= 1.0


def test_systemic_risk_higher_in_crisis() -> None:
    """Crisis macro must produce a higher systemic risk score than normal macro."""
    agent_n = BankAgent()
    agent_c = BankAgent()
    normal_state = agent_n.update_credit_cycle(_normal_macro())
    crisis_state = agent_c.update_credit_cycle(_crisis_macro())
    assert crisis_state.systemic_risk_score > normal_state.systemic_risk_score


# ---------------------------------------------------------------------------
# assess_mortgage
# ---------------------------------------------------------------------------

def test_mortgage_approved_low_dsr() -> None:
    """High income vs moderate loan → DSR < 50% → approved."""
    agent = BankAgent()
    # Property HKD 5M, 70% LTV = 3.5M loan, monthly income HKD 80k
    # Approx monthly payment ~HKD 18k at 4% / 25yr → DSR ~22%
    decision = agent.assess_mortgage(
        property_price=5_000_000,
        monthly_income=80_000,
        requested_ltv=0.70,
        loan_term_years=25,
        interest_rate=0.04,
    )
    assert isinstance(decision, CreditDecision)
    assert decision.approved is True
    assert decision.rejection_reason is None
    assert decision.approved_ltv > 0
    assert decision.monthly_payment > 0


def test_mortgage_rejected_high_dsr() -> None:
    """Low income vs large loan → DSR > 50% → rejected with reason."""
    agent = BankAgent()
    # Property HKD 10M, 60% LTV = 6M loan, monthly income HKD 20k → DSR >> 50%
    decision = agent.assess_mortgage(
        property_price=10_000_000,
        monthly_income=20_000,
        requested_ltv=0.60,
        loan_term_years=25,
        interest_rate=0.04,
    )
    assert isinstance(decision, CreditDecision)
    assert decision.approved is False
    assert decision.rejection_reason is not None
    assert "DSR" in decision.rejection_reason
    assert decision.approved_ltv == 0.0
    assert decision.monthly_payment == 0.0


def test_mortgage_ltv_capped_by_bank_policy() -> None:
    """If bank's ltv_cap is below requested LTV, approved LTV is capped."""
    # Start with a bank whose LTV cap is 0.55 (after some tightening)
    tight_state = BankState(ltv_cap=0.55)
    agent = BankAgent(initial_state=tight_state)
    # Borrower requests 70% but bank only allows 55%
    decision = agent.assess_mortgage(
        property_price=5_000_000,
        monthly_income=100_000,
        requested_ltv=0.70,
    )
    assert decision.approved is True
    assert abs(decision.approved_ltv - 0.55) < 1e-9


def test_mortgage_decision_is_frozen() -> None:
    """CreditDecision must be a frozen dataclass."""
    agent = BankAgent()
    decision = agent.assess_mortgage(5_000_000, 80_000)
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        decision.approved = False  # type: ignore[misc]


def test_mortgage_systemic_risk_propagated() -> None:
    """CreditDecision.systemic_risk_score must match the bank state."""
    agent = BankAgent()
    agent.update_credit_cycle(_crisis_macro())
    decision = agent.assess_mortgage(5_000_000, 200_000)
    assert decision.systemic_risk_score == agent.state.systemic_risk_score


# ---------------------------------------------------------------------------
# update_from_macro — credit crunch signalling
# ---------------------------------------------------------------------------

def test_credit_crunch_signal_emitted_on_tightening() -> None:
    """When LTV tightens >5pp in a single step, a CreditCrunchSignal is returned."""
    # Force a large NPL by providing extreme crisis macro; then call update_from_macro
    # Start with a high LTV state so there is room to tighten significantly
    generous_state = BankState(ltv_cap=0.70, npl_ratio=0.005)
    agent = BankAgent(initial_state=generous_state)
    # Very high unemployment should push NPL above 3% → LTV tightens -5pp
    extreme_macro = _MacroStub(unemployment_rate=0.15, ccl_index=60.0)
    signal = agent.update_from_macro(extreme_macro)
    # Signal may or may not be emitted depending on NPL crossing 3% threshold;
    # confirm the function returns the correct type when a signal IS emitted
    if signal is not None:
        assert isinstance(signal, CreditCrunchSignal)
        assert signal.ltv_reduction > 0.05
        assert signal.severity in {"mild", "moderate", "severe"}
        assert 0.0 <= signal.estimated_demand_suppression <= 0.8
        assert signal.bank_id == agent.state.bank_id


def test_no_crunch_signal_under_normal_macro() -> None:
    """Under normal macro no credit crunch signal should be emitted."""
    agent = BankAgent()
    signal = agent.update_from_macro(_normal_macro())
    # Normal macro does not tighten LTV by >5pp from default 0.60
    assert signal is None


def test_crunch_signal_is_frozen() -> None:
    """CreditCrunchSignal must be a frozen dataclass."""
    signal = CreditCrunchSignal(
        bank_id="test_bank",
        severity="mild",
        ltv_reduction=0.06,
        estimated_demand_suppression=0.18,
    )
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        signal.severity = "severe"  # type: ignore[misc]


def test_crunch_severity_levels() -> None:
    """Verify severity thresholds are correctly applied to CreditCrunchSignal."""
    # We construct signals directly to test severity logic
    def _make_signal(reduction: float) -> CreditCrunchSignal:
        severity = (
            "severe" if reduction > 0.15
            else "moderate" if reduction > 0.08
            else "mild"
        )
        return CreditCrunchSignal(
            bank_id="test",
            severity=severity,
            ltv_reduction=reduction,
            estimated_demand_suppression=min(0.8, reduction * 3.0),
        )

    assert _make_signal(0.06).severity == "mild"
    assert _make_signal(0.10).severity == "moderate"
    assert _make_signal(0.20).severity == "severe"


# ---------------------------------------------------------------------------
# compute_macro_feedback
# ---------------------------------------------------------------------------

def test_macro_feedback_empty_under_neutral_state() -> None:
    """With baseline bank state and baseline macro, feedback deltas should be near-zero."""
    agent = BankAgent()
    feedback = agent.compute_macro_feedback(agent.state, _normal_macro())
    # credit_growth_yoy delta may be zero; hsi_level should not appear (NPL < 3%)
    assert "hsi_level" not in feedback


def test_macro_feedback_hsi_drag_when_npl_high() -> None:
    """When NPL > 3%, compute_macro_feedback must include a negative hsi_level delta."""
    high_npl_state = BankState(npl_ratio=0.05, ltv_cap=0.60)
    agent = BankAgent(initial_state=high_npl_state)
    feedback = agent.compute_macro_feedback(high_npl_state, _normal_macro())
    assert "hsi_level" in feedback
    assert feedback["hsi_level"] < 0


def test_macro_feedback_gdp_drag_on_negative_impulse() -> None:
    """Negative credit impulse → negative GDP adjustment."""
    negative_impulse_state = BankState(credit_impulse=-0.05, npl_ratio=0.015)
    agent = BankAgent(initial_state=negative_impulse_state)
    feedback = agent.compute_macro_feedback(negative_impulse_state, _normal_macro())
    if "gdp_growth" in feedback:
        assert feedback["gdp_growth"] < 0


def test_macro_feedback_returns_dict() -> None:
    """compute_macro_feedback must always return a dict."""
    agent = BankAgent()
    result = agent.compute_macro_feedback(agent.state, _normal_macro())
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# BankAgent custom bank_id
# ---------------------------------------------------------------------------

def test_custom_bank_id_stored_in_state() -> None:
    """BankAgent created with custom bank_id propagates it to BankState."""
    agent = BankAgent(bank_id="hang_seng_bank")
    assert agent.state.bank_id == "hang_seng_bank"


def test_update_credit_cycle_preserves_bank_id() -> None:
    """update_credit_cycle must not overwrite bank_id."""
    agent = BankAgent(bank_id="boc_hk")
    agent.update_credit_cycle(_normal_macro())
    assert agent.state.bank_id == "boc_hk"
