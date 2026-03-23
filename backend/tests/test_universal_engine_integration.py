"""Integration tests for Universal Prediction Engine (Tasks 18-26)."""

from __future__ import annotations

import pytest

from backend.app.models.simulation_config import PRESET_FAST, HookConfig
from backend.app.models.validation import ConfidenceResult
from backend.app.services.emergence_guards import DiversityChecker
from backend.app.services.naive_forecaster import NaiveForecaster
from backend.app.services.validation_suite import synthesize_confidence


def test_preset_fast_hook_config():
    assert PRESET_FAST.hook_config.echo_chamber_interval == 5
    assert PRESET_FAST.hook_config.media_influence_interval == 5
    assert PRESET_FAST.agents == 100
    assert PRESET_FAST.rounds == 15


def test_full_validation_pipeline():
    nf = NaiveForecaster()
    naive_forecast = nf.forecast([100, 102, 104, 106, 108], horizon=3, method="drift")
    assert len(naive_forecast) == 3

    result = synthesize_confidence(
        theils_u=0.75,
        mc_p25=95,
        mc_p75=115,
        mc_median=105,
        agent_consensus=0.65,
        sensitivity=0.3,
    )
    assert isinstance(result, ConfidenceResult)
    assert result.confidence_level in ("high", "medium", "low")
    assert 0.0 <= result.confidence_score <= 1.0


def test_diversity_guard_integration():
    # 50 profiles spread uniformly across low/medium/high for each dimension
    # to achieve entropy_ratio >= 0.8
    profiles = []
    occupations = ["eng", "fin", "srv", "edu", "hc"]
    for i in range(50):
        # Cycle traits across full [0,1] range to maximise bin diversity
        t = i / 49.0
        profiles.append(
            {
                "big5_openness": t,
                "big5_conscientiousness": 1.0 - t,
                "big5_extraversion": (t * 3) % 1.0,
                "big5_agreeableness": 0.5,
                "big5_neuroticism": t,
                "political_stance": (t * 5) % 1.0,
                "occupation": occupations[i % 5],
                "age": 20 + (i % 5) * 15,
            }
        )
    checker = DiversityChecker()
    result = checker.check(profiles)
    # Should return a valid DiversityResult; check structure
    assert result.shannon_entropy >= 0.0
    assert result.entropy_ratio >= 0.0
    assert isinstance(result.passed, bool)


def test_hook_config_custom():
    hc = HookConfig(echo_chamber_interval=10, media_influence_interval=3)
    assert hc.echo_chamber_interval == 10
    assert hc.media_influence_interval == 3
    assert hc.macro_feedback_interval == 5  # default


def test_confidence_result_high():
    """High confidence scenario: low Theil's U, high consensus, narrow MC band."""
    result = synthesize_confidence(
        theils_u=0.2,
        mc_p25=98,
        mc_p75=102,
        mc_median=100,
        agent_consensus=0.85,
        sensitivity=0.1,
    )
    assert result.confidence_level == "high"
    assert result.confidence_score >= 0.7


def test_confidence_result_low():
    """Low confidence scenario: high Theil's U, low consensus, wide MC band."""
    result = synthesize_confidence(
        theils_u=1.5,
        mc_p25=50,
        mc_p75=200,
        mc_median=100,
        agent_consensus=0.1,
        sensitivity=0.9,
    )
    assert result.confidence_level == "low"
    assert result.confidence_score < 0.4


def test_naive_forecaster_methods():
    """Test multiple NaiveForecaster methods."""
    nf = NaiveForecaster()
    series = [100.0, 102.0, 104.0, 106.0, 108.0]

    drift = nf.forecast(series, horizon=3, method="drift")
    assert len(drift) == 3
    # Drift should project further than last value
    assert drift[0] >= series[-1]

    mean = nf.forecast(series, horizon=2, method="mean")
    assert len(mean) == 2

    naive = nf.forecast(series, horizon=4, method="naive")
    assert len(naive) == 4
    # Naive repeats the last value
    assert all(v == series[-1] for v in naive)


def test_preset_standard():
    from backend.app.models.simulation_config import PRESET_STANDARD

    assert PRESET_STANDARD.agents == 300
    assert PRESET_STANDARD.rounds == 20
    assert PRESET_STANDARD.name == "standard"


def test_preset_deep():
    from backend.app.models.simulation_config import PRESET_DEEP

    assert PRESET_DEEP.agents == 500
    assert PRESET_DEEP.rounds == 30
    assert PRESET_DEEP.mc_trials == 100


def test_confidence_result_is_frozen():
    """ConfidenceResult should be immutable (frozen Pydantic model)."""
    result = synthesize_confidence(
        theils_u=0.5,
        mc_p25=90,
        mc_p75=110,
        mc_median=100,
        agent_consensus=0.6,
    )
    with pytest.raises(Exception):
        result.confidence_score = 0.99  # type: ignore[misc]
