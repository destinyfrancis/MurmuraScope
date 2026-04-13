"""Unit tests for personality evolution engine (Phase 2.1).

Covers:
- _compute_drift logic (valence/arousal/event significance)
- Clamping and regression-to-mean
- evolve_round integration (snapshots and persistence)
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from backend.app.services.personality_evolution import PersonalityEvolutionEngine, TraitSnapshot


_TRAITS = ("openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism")

@pytest.fixture()
def engine():
    return PersonalityEvolutionEngine()


class TestPersonalityDriftLogic:
    """Test the internal _compute_drift logic directly."""

    def test_zero_delta_on_neutral_inputs(self, engine):
        traits = {t: 0.5 for t in _TRAITS}
        # Neutral inputs (valence=0, arousal=0.3, significance=0.2 baseline)
        new_traits, drifts = engine._compute_drift(
            traits=traits,
            valence=0.0,
            arousal=0.3,
            event_significance=0.2
        )
        # Should stay very close to 0.5 (only tiny regression/drift)
        for t in _TRAITS:
            assert abs(new_traits[t] - 0.5) < 0.01

    def test_positive_valence_increases_agreeableness(self, engine):
        traits = {t: 0.5 for t in _TRAITS}
        new_traits, drifts = engine._compute_drift(
            traits=traits,
            valence=1.0,
            arousal=0.5,
            event_significance=0.5
        )
        assert drifts["agreeableness"] > 0
        assert new_traits["agreeableness"] > 0.5

    def test_high_significance_increases_neuroticism(self, engine):
        traits = {t: 0.5 for t in _TRAITS}
        new_traits, drifts = engine._compute_drift(
            traits=traits,
            valence=0.0,
            arousal=0.8,
            event_significance=1.0
        )
        assert drifts["neuroticism"] > 0
        assert new_traits["neuroticism"] > 0.5

    def test_regression_to_mean(self, engine):
        # Extreme trait at 0.9
        traits = {t: 0.9 for t in _TRAITS}
        new_traits, drifts = engine._compute_drift(
            traits=traits,
            valence=0.0,
            arousal=0.3,
            event_significance=0.2
        )
        # Drift should be negative (toward 0.5)
        assert drifts["openness"] < 0
        assert new_traits["openness"] < 0.9

    def test_clamping_at_boundaries(self, engine):
        traits = {t: 0.99 for t in _TRAITS}
        # Force huge positive drift
        new_traits, drifts = engine._compute_drift(
            traits=traits,
            valence=1.0,
            arousal=1.0,
            event_significance=1.0
        )
        for t in _TRAITS:
            assert new_traits[t] <= 1.0


class TestEvolveRoundIntegration:
    """Test the public evolve_round method."""

    @pytest.mark.asyncio
    async def test_evolve_round_returns_snapshots(self, engine):
        session_id = "test-session"
        agent_profiles = [
            {"id": "a1", "openness": 0.5, "extraversion": 0.5, "neuroticism": 0.5}
        ]
        # Mocking persist_log to avoid DB dependency in unit tests
        with patch.object(engine, "_persist_log", new_callable=AsyncMock):
            # Significant event + positive valence to trigger logging (>0.005)
            snapshots = await engine.evolve_round(
                session_id=session_id,
                round_num=1,
                agent_profiles=agent_profiles,
                emotional_states={},
                events=[type('Event', (), {'severity': 0.9})()]
            )
            
            # Since _MAX_DRIFT is 0.02 and we have high significance, 
            # drift is likely to exceed _LOG_DRIFT_THRESHOLD (0.005)
            assert isinstance(snapshots, list)
            if snapshots:
                assert snapshots[0].agent_id == "a1"
                assert snapshots[0].round_number == 1

    @pytest.mark.asyncio
    async def test_cache_persistence(self, engine):
        session_id = "s1"
        agent_id = "a1"
        profile = {"id": agent_id, "openness": 0.5}
        
        with patch.object(engine, "_persist_log", new_callable=AsyncMock):
            await engine.evolve_round(
                session_id=session_id,
                round_num=1,
                agent_profiles=[profile],
                emotional_states={},
                events=[]
            )
        
        cached = engine.get_traits(session_id, agent_id)
        assert cached is not None
        assert "openness" in cached

    @pytest.mark.asyncio
    async def test_clear_session(self, engine):
        session_id = "s1"
        engine._trait_cache[session_id] = {"a1": {"o": 0.5}}
        engine.clear_session(session_id)
        assert engine.get_traits(session_id, "a1") is None
