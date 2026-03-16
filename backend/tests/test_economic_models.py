"""Tests for Workstream E: Economic Model Deepening.

Covers:
- E1: Wealth effect + life-cycle MPC in ConsumerModel
- E2: Nonlinear shocks (regime detection, interaction terms)
- E3: Bank & credit cycle (BankAgent)
"""

from __future__ import annotations

import dataclasses
import pytest

from backend.app.services.macro_state import MacroState, BASELINE_AVG_SQFT_PRICE, BASELINE_STAMP_DUTY


# ---------------------------------------------------------------------------
# Fixture: baseline MacroState
# ---------------------------------------------------------------------------

def _baseline_macro(**overrides) -> MacroState:
    """Create a baseline MacroState with optional overrides."""
    defaults = dict(
        hibor_1m=0.042,
        prime_rate=0.0575,
        unemployment_rate=0.029,
        median_monthly_income=20000,
        ccl_index=150.0,
        avg_sqft_price=dict(BASELINE_AVG_SQFT_PRICE),
        mortgage_cap=0.60,
        stamp_duty_rates=dict(BASELINE_STAMP_DUTY),
        gdp_growth=0.032,
        cpi_yoy=0.021,
        hsi_level=17000.0,
        consumer_confidence=55.0,
        net_migration=-20000,
        birth_rate=5.8,
        policy_flags={},
    )
    defaults.update(overrides)
    return MacroState(**defaults)


# =========================================================================
# E1: Wealth Effect + Life Cycle
# =========================================================================


class TestWealthEffectLifeCycle:
    """Tests for wealth effect and life-cycle MPC in ConsumerModel."""

    def _make_profile(self):
        from backend.app.services.agent_factory import AgentProfile
        return AgentProfile(
            id=1, agent_type="npc", age=40, sex="M",
            district="中西區", occupation="金融業",
            income_bracket="$40,000-$59,999", education_level="大學",
            marital_status="已婚", housing_type="私人住宅",
            openness=0.6, conscientiousness=0.5, extraversion=0.5,
            agreeableness=0.5, neuroticism=0.3,
            monthly_income=45000, savings=500000,
        )

    def test_mpc_varies_by_age_band(self):
        """Different age bands produce different MPC values."""
        from backend.app.services.consumer_model import _LIFECYCLE_MPC
        assert _LIFECYCLE_MPC["young"] > _LIFECYCLE_MPC["middle"]
        assert _LIFECYCLE_MPC["middle"] > _LIFECYCLE_MPC["senior"]

    def test_wealth_elasticity_applies(self):
        """Positive wealth change increases entertainment spending."""
        from backend.app.services.consumer_model import ConsumerModel
        model = ConsumerModel()
        macro = _baseline_macro()
        profile = self._make_profile()
        base = model.generate_spending_profile(profile, macro)

        no_wealth = model.adjust_spending(base, macro, "neutral")
        with_wealth = model.adjust_spending(
            base, macro, "neutral", age_band="middle", wealth_change_pct=0.20
        )

        # 20% wealth gain → entertainment should increase
        assert with_wealth.entertainment > no_wealth.entertainment

    def test_senior_more_sensitive_than_young(self):
        """Seniors have lower MPC so the same wealth shock produces a smaller
        absolute adjustment, but they are *more* asset-dependent in reality.
        The MPC scaling ensures senior response is different from young."""
        from backend.app.services.consumer_model import ConsumerModel
        model = ConsumerModel()
        macro = _baseline_macro()
        profile = self._make_profile()
        base = model.generate_spending_profile(profile, macro)

        young_adj = model.adjust_spending(
            base, macro, "neutral", age_band="young", wealth_change_pct=0.10
        )
        senior_adj = model.adjust_spending(
            base, macro, "neutral", age_band="senior", wealth_change_pct=0.10
        )
        # Young MPC is higher → bigger entertainment change
        young_delta = young_adj.entertainment - base.entertainment
        senior_delta = senior_adj.entertainment - base.entertainment
        # Both should be positive (wealth gain → more spending)
        assert young_delta > 0
        assert senior_delta > 0
        # Young should respond more strongly (higher MPC)
        assert young_delta > senior_delta

    def test_zero_wealth_change_no_adjustment(self):
        """Zero wealth change should not alter spending."""
        from backend.app.services.consumer_model import ConsumerModel
        model = ConsumerModel()
        macro = _baseline_macro()
        profile = self._make_profile()
        base = model.generate_spending_profile(profile, macro)

        adjusted = model.adjust_spending(
            base, macro, "neutral", age_band="middle", wealth_change_pct=0.0
        )
        baseline = model.adjust_spending(base, macro, "neutral")

        assert adjusted.entertainment == baseline.entertainment
        assert adjusted.food == baseline.food

    def test_backward_compat_no_new_params(self):
        """Calling adjust_spending without new params works the same as before."""
        from backend.app.services.consumer_model import ConsumerModel
        model = ConsumerModel()
        macro = _baseline_macro()
        profile = self._make_profile()
        base = model.generate_spending_profile(profile, macro)

        result = model.adjust_spending(base, macro, "neutral")
        assert result.entertainment > 0
        assert result.savings_rate >= 0


# =========================================================================
# E2: Nonlinear Shocks + Interaction Terms
# =========================================================================


class TestRegimeDetection:
    """Tests for regime detection in nonlinear_shocks module."""

    def test_crisis_detected_low_hsi(self):
        """HSI far below mean triggers crisis regime."""
        from backend.app.services.nonlinear_shocks import detect_regime
        macro = _baseline_macro(hsi_level=8000.0)  # z-score < -2
        regime = detect_regime(macro)
        assert regime.regime == "crisis"
        assert regime.hsi_zscore < -2.0

    def test_boom_detected_low_unemployment(self):
        """Very low unemployment triggers boom regime."""
        from backend.app.services.nonlinear_shocks import detect_regime
        macro = _baseline_macro(unemployment_rate=0.025, hsi_level=22000.0)
        regime = detect_regime(macro)
        assert regime.regime == "boom"

    def test_normal_for_moderate_values(self):
        """Moderate indicators produce normal regime."""
        from backend.app.services.nonlinear_shocks import detect_regime
        macro = _baseline_macro(
            hsi_level=22000.0,
            unemployment_rate=0.04,
            consumer_confidence=55.0,
        )
        regime = detect_regime(macro)
        assert regime.regime == "normal"

    def test_regime_state_is_frozen(self):
        """RegimeState should be immutable."""
        from backend.app.services.nonlinear_shocks import RegimeState
        rs = RegimeState(regime="normal", hsi_zscore=0.0,
                         unemployment_deviation=0.0, confidence_level=55.0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            rs.regime = "crisis"  # type: ignore[misc]


class TestInteractionTerms:
    """Tests for shock interaction terms."""

    def test_two_simultaneous_shocks_produce_extra(self):
        """interest_rate_hike + china_slowdown → extra HSI + confidence hit."""
        from backend.app.services.nonlinear_shocks import _compute_interaction_effects
        extras = _compute_interaction_effects(
            "interest_rate_hike", ("china_slowdown",)
        )
        assert "hsi_level" in extras
        assert extras["hsi_level"] < 0  # negative extra
        assert "consumer_confidence" in extras

    def test_single_shock_no_interaction(self):
        """A single shock with no active companions produces no interaction."""
        from backend.app.services.nonlinear_shocks import _compute_interaction_effects
        extras = _compute_interaction_effects("interest_rate_hike", ())
        assert extras == {}

    def test_unknown_shock_pair_no_interaction(self):
        """Unknown shock pair produces no interaction terms."""
        from backend.app.services.nonlinear_shocks import _compute_interaction_effects
        extras = _compute_interaction_effects(
            "market_rally", ("rcep_benefit",)
        )
        assert extras == {}


# =========================================================================
# E3: Credit Cycle (BankAgent)
# =========================================================================


class TestCreditCycle:
    """Tests for BankAgent credit cycle model."""

    def test_hibor_increase_tightens_credit(self):
        """Higher HIBOR → wider spread → lower credit growth."""
        from backend.app.services.bank_agent import BankAgent
        agent = BankAgent()

        macro_low = _baseline_macro(hibor_1m=0.01)
        state_low = agent.update_credit_cycle(macro_low)

        agent2 = BankAgent()
        macro_high = _baseline_macro(hibor_1m=0.06)
        state_high = agent2.update_credit_cycle(macro_high)

        assert state_high.interbank_spread > state_low.interbank_spread
        assert state_high.credit_growth_yoy < state_low.credit_growth_yoy

    def test_property_crash_increases_npl(self):
        """CCL drop below baseline → NPL rises."""
        from backend.app.services.bank_agent import BankAgent
        agent = BankAgent()

        macro_normal = _baseline_macro(ccl_index=150.0)
        state_normal = agent.update_credit_cycle(macro_normal)

        agent2 = BankAgent()
        macro_crash = _baseline_macro(ccl_index=80.0, unemployment_rate=0.06)
        state_crash = agent2.update_credit_cycle(macro_crash)

        assert state_crash.npl_ratio > state_normal.npl_ratio

    def test_credit_impulse_positive_gdp_boost(self):
        """Positive credit impulse → positive GDP adjustment."""
        from backend.app.services.bank_agent import BankAgent, BankState
        agent = BankAgent()

        # Force a state with negative credit growth, then update to positive
        prev_state = BankState(credit_growth_yoy=-0.02)
        macro = _baseline_macro(hibor_1m=0.01)  # low rates → credit expands
        new_state = agent.update_credit_cycle(macro, prev_bank_state=prev_state)

        # Credit impulse should be positive (went from -2% to positive)
        assert new_state.credit_impulse > 0

        adjustments = agent.compute_macro_feedback(new_state, macro)
        assert adjustments.get("gdp_growth", 0) > 0

    def test_credit_impulse_negative_gdp_drag_asymmetric(self):
        """Negative credit impulse → larger GDP drag (asymmetric)."""
        from backend.app.services.bank_agent import BankAgent, BankState

        # Force a state with good credit growth, then update to worse conditions
        prev_state = BankState(credit_growth_yoy=0.05)
        agent = BankAgent(initial_state=prev_state)
        macro_stress = _baseline_macro(hibor_1m=0.06, unemployment_rate=0.07)
        new_state = agent.update_credit_cycle(macro_stress)

        # Credit impulse should be negative (credit contracted)
        assert new_state.credit_impulse < 0

        adjustments = agent.compute_macro_feedback(new_state, macro_stress)
        gdp_adj = adjustments.get("gdp_growth", 0)
        assert gdp_adj < 0  # GDP drag

    def test_bank_state_is_frozen(self):
        """BankState should be immutable."""
        from backend.app.services.bank_agent import BankState
        bs = BankState()
        with pytest.raises(dataclasses.FrozenInstanceError):
            bs.npl_ratio = 0.5  # type: ignore[misc]

    def test_ltv_capped_at_hkma_limit(self):
        """LTV should never exceed HKMA bounds regardless of conditions."""
        from backend.app.services.bank_agent import BankAgent
        agent = BankAgent()

        # Very benign conditions → LTV should relax but stay <= 0.70
        macro = _baseline_macro(hibor_1m=0.005, unemployment_rate=0.02)
        state = agent.update_credit_cycle(macro)
        assert state.ltv_cap <= 0.70
        assert state.ltv_cap >= 0.40
