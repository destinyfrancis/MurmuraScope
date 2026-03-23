"""Tests for ConsumerModel — spending profiles, price elasticity, and retail forecasts."""

from __future__ import annotations

from dataclasses import replace

import pytest

from backend.app.services.consumer_model import (
    _PRICE_ELASTICITY,
    ConsumerModel,
    SpendingProfile,
)
from backend.app.services.macro_state import MacroState

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def model() -> ConsumerModel:
    return ConsumerModel()


@pytest.fixture()
def base_macro() -> MacroState:
    """Low-inflation baseline macro state."""
    return MacroState(
        hibor_1m=0.02,
        prime_rate=5.0,
        unemployment_rate=3.0,
        median_monthly_income=20000,
        ccl_index=160.0,
        avg_sqft_price={"HK_Island": 20000, "Kowloon": 15000, "NT": 10000},
        mortgage_cap=0.6,
        stamp_duty_rates={"residential": 0.15},
        gdp_growth=2.5,
        cpi_yoy=0.02,
        hsi_level=20000.0,
        consumer_confidence=55.0,
        net_migration=-10000,
        birth_rate=0.007,
        policy_flags={},
    )


@pytest.fixture()
def high_inflation_macro(base_macro: MacroState) -> MacroState:
    """High-inflation macro state (cpi_yoy=0.08)."""
    return replace(base_macro, cpi_yoy=0.08)


@pytest.fixture()
def base_spending() -> SpendingProfile:
    return SpendingProfile(
        food=0.25,
        housing=0.30,
        transport=0.10,
        entertainment=0.12,
        education=0.05,
        healthcare=0.05,
        savings_rate=0.13,
    )


# ---------------------------------------------------------------------------
# SpendingProfile
# ---------------------------------------------------------------------------


class TestSpendingProfile:
    def test_frozen(self, base_spending: SpendingProfile) -> None:
        with pytest.raises(AttributeError):
            base_spending.food = 0.5  # type: ignore[misc]

    def test_total_consumption_rate(self, base_spending: SpendingProfile) -> None:
        total = base_spending.total_consumption_rate
        assert total == pytest.approx(0.87, abs=0.01)

    def test_monthly_amounts(self, base_spending: SpendingProfile) -> None:
        amounts = base_spending.monthly_amounts(20000)
        assert amounts["food"] == pytest.approx(5000.0)
        assert amounts["savings"] == pytest.approx(2600.0)

    def test_validation_rejects_negative(self) -> None:
        with pytest.raises(ValueError):
            SpendingProfile(
                food=-0.1,
                housing=0.3,
                transport=0.1,
                entertainment=0.1,
                education=0.05,
                healthcare=0.05,
                savings_rate=0.5,
            )


# ---------------------------------------------------------------------------
# Price elasticity (H12)
# ---------------------------------------------------------------------------


class TestPriceElasticity:
    """H12: High inflation should reduce discretionary spending via price elasticity."""

    def test_price_elasticity_constants_exist(self) -> None:
        assert "entertainment" in _PRICE_ELASTICITY
        assert "transport" in _PRICE_ELASTICITY
        assert "education" in _PRICE_ELASTICITY

    def test_entertainment_most_elastic(self) -> None:
        assert abs(_PRICE_ELASTICITY["entertainment"]) > abs(_PRICE_ELASTICITY["transport"])

    def test_high_inflation_reduces_entertainment_more_than_transport(
        self,
        model: ConsumerModel,
        base_spending: SpendingProfile,
        high_inflation_macro: MacroState,
    ) -> None:
        adjusted = model.adjust_spending(
            base_spending,
            high_inflation_macro,
            "neutral",
        )
        ent_cut = base_spending.entertainment - adjusted.entertainment
        trans_cut = base_spending.transport - adjusted.transport
        # Entertainment (elasticity -1.2) should be cut more than transport (-0.5)
        assert ent_cut > trans_cut, f"Entertainment cut {ent_cut:.4f} should exceed transport cut {trans_cut:.4f}"

    def test_low_inflation_no_elasticity_effect(
        self,
        model: ConsumerModel,
        base_spending: SpendingProfile,
        base_macro: MacroState,
    ) -> None:
        """When CPI <= 3%, price elasticity should not kick in."""
        adjusted = model.adjust_spending(
            base_spending,
            base_macro,
            "neutral",
        )
        # No inflation excess, so entertainment should not be cut by elasticity
        # (other adjustments like sentiment may still apply, but no elasticity)
        # Just verify entertainment is not dramatically reduced
        assert adjusted.entertainment >= base_spending.entertainment * 0.95

    def test_education_less_elastic_than_entertainment(
        self,
        model: ConsumerModel,
        base_spending: SpendingProfile,
        high_inflation_macro: MacroState,
    ) -> None:
        adjusted = model.adjust_spending(
            base_spending,
            high_inflation_macro,
            "neutral",
        )
        ent_pct_cut = (base_spending.entertainment - adjusted.entertainment) / base_spending.entertainment
        edu_pct_cut = (base_spending.education - adjusted.education) / base_spending.education
        # Education elasticity (-0.3) < entertainment (-1.2) => smaller % cut
        assert edu_pct_cut < ent_pct_cut
