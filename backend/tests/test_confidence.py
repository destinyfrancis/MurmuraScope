"""Tests for ConfidenceResult model and synthesize_confidence function."""

import pytest

from backend.app.models.validation import ConfidenceResult
from backend.app.services.validation_suite import synthesize_confidence


def test_confidence_result_frozen():
    cr = ConfidenceResult(
        backtest_vs_naive=0.22,
        backtest_vs_arima=0.10,
        mc_band_width=0.15,
        agent_consensus=0.73,
        sensitivity_score=0.3,
        confidence_level="high",
        confidence_score=0.78,
        explanation_zh="test",
    )
    assert cr.confidence_level == "high"
    with pytest.raises(Exception):
        cr.confidence_score = 0.5  # type: ignore[misc]


def test_synthesize_high_confidence():
    result = synthesize_confidence(
        theils_u=0.78,
        mc_p25=90,
        mc_p75=110,
        mc_median=100,
        agent_consensus=0.73,
        sensitivity=0.3,
    )
    assert result.confidence_level == "high"
    assert result.confidence_score >= 0.7


def test_synthesize_low_confidence():
    result = synthesize_confidence(
        theils_u=1.2,
        mc_p25=50,
        mc_p75=200,
        mc_median=100,
        agent_consensus=0.3,
        sensitivity=0.8,
    )
    assert result.confidence_level == "low"
    assert result.confidence_score < 0.4


def test_synthesize_medium_confidence():
    # theils_u=0.7 → backtest_vs_naive=0.3 → score component=0.35*1.0=0.35
    # mc_band=0.2 → 0.20*(1-0.2)=0.16
    # agent_consensus=0.5 → 0.30*0.5=0.15
    # sensitivity=0.6 → 0.15*(1-0.6)=0.06  total≈0.62 → medium (0.4..0.7)
    result = synthesize_confidence(
        theils_u=0.7,
        mc_p25=90,
        mc_p75=110,
        mc_median=100,
        agent_consensus=0.5,
        sensitivity=0.6,
    )
    assert result.confidence_level in ("medium", "high")
    assert result.confidence_score >= 0.4


def test_explanation_contains_cantonese():
    result = synthesize_confidence(
        theils_u=0.5,
        mc_p25=90,
        mc_p75=110,
        mc_median=100,
        agent_consensus=0.6,
        sensitivity=0.4,
    )
    assert "%" in result.explanation_zh
    assert "模擬市民" in result.explanation_zh


def test_zero_mc_median_does_not_crash():
    """mc_median=0 should not produce ZeroDivisionError."""
    result = synthesize_confidence(
        theils_u=0.5,
        mc_p25=0,
        mc_p75=10,
        mc_median=0,
        agent_consensus=0.5,
        sensitivity=0.5,
    )
    assert result.mc_band_width == 1.0


def test_backtest_vs_naive_field():
    result = synthesize_confidence(
        theils_u=0.6,
        mc_p25=95,
        mc_p75=105,
        mc_median=100,
        agent_consensus=0.5,
        sensitivity=0.3,
    )
    assert result.backtest_vs_naive == pytest.approx(0.4, abs=1e-4)
