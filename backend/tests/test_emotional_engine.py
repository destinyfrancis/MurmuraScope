"""Tests for EmotionalEngine and EmotionalState models (Phase 3)."""
from __future__ import annotations

import random
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app.models.emotional_state import INCOME_QUARTILE, EmotionalState
from backend.app.services.emotional_engine import EmotionalEngine


# ---------------------------------------------------------------------------
# Helper fixtures
# ---------------------------------------------------------------------------

def _make_profile(
    agent_id: int = 1,
    extraversion: float = 0.5,
    neuroticism: float = 0.5,
    agreeableness: float = 0.5,
    openness: float = 0.5,
    income_bracket: str = "中收入",
) -> MagicMock:
    p = MagicMock()
    p.id = agent_id
    p.extraversion = extraversion
    p.neuroticism = neuroticism
    p.agreeableness = agreeableness
    p.openness = openness
    p.income_bracket = income_bracket
    return p


def _state(
    agent_id: int = 1,
    round_number: int = 0,
    valence: float = 0.0,
    arousal: float = 0.3,
    dominance: float = 0.4,
) -> EmotionalState:
    return EmotionalState(
        agent_id=agent_id,
        session_id="test-session",
        round_number=round_number,
        valence=valence,
        arousal=arousal,
        dominance=dominance,
    )


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

def test_emotional_state_creation():
    """EmotionalState is a frozen dataclass with correct defaults."""
    es = EmotionalState(agent_id=1, session_id="s1", round_number=0)
    assert es.valence == 0.0
    assert es.arousal == 0.3
    assert es.dominance == 0.4
    assert es.agent_id == 1


def test_emotional_state_frozen():
    """EmotionalState cannot be mutated."""
    es = EmotionalState(agent_id=1, session_id="s1", round_number=0)
    with pytest.raises((AttributeError, TypeError)):
        es.valence = 0.5  # type: ignore[misc]


def test_emotional_state_replace():
    """Replace() creates new state without mutation."""
    es = EmotionalState(agent_id=1, session_id="s1", round_number=0)
    es2 = replace(es, valence=0.8)
    assert es.valence == 0.0
    assert es2.valence == 0.8


def test_income_quartile_mapping():
    """INCOME_QUARTILE correctly maps income bracket strings."""
    assert INCOME_QUARTILE["低收入"] == 0
    assert INCOME_QUARTILE["高收入"] == 4
    assert INCOME_QUARTILE["中收入"] == 2
    assert INCOME_QUARTILE["中低收入"] == 1
    assert INCOME_QUARTILE["中高收入"] == 3


# ---------------------------------------------------------------------------
# initialize_state tests
# ---------------------------------------------------------------------------

def test_initialize_state_returns_emotional_state():
    engine = EmotionalEngine()
    profile = _make_profile(agent_id=5)
    state = engine.initialize_state(5, "sess", profile)
    assert isinstance(state, EmotionalState)
    assert state.agent_id == 5
    assert state.session_id == "sess"
    assert state.round_number == 0


def test_initialize_state_valence_range():
    """Valence should always be in [-1, +1]."""
    engine = EmotionalEngine()
    rng = random.Random(42)
    for _ in range(20):
        profile = _make_profile(
            extraversion=rng.random(),
            neuroticism=rng.random(),
        )
        state = engine.initialize_state(1, "s", profile, rng=rng)
        assert -1.0 <= state.valence <= 1.0


def test_initialize_state_arousal_range():
    """Arousal should always be in [0, 1]."""
    engine = EmotionalEngine()
    rng = random.Random(99)
    for _ in range(20):
        profile = _make_profile(extraversion=rng.random())
        state = engine.initialize_state(1, "s", profile, rng=rng)
        assert 0.0 <= state.arousal <= 1.0


def test_initialize_state_dominance_range():
    """Dominance should always be in [0, 1]."""
    engine = EmotionalEngine()
    rng = random.Random(7)
    for bracket in INCOME_QUARTILE:
        profile = _make_profile(income_bracket=bracket)
        state = engine.initialize_state(1, "s", profile, rng=rng)
        assert 0.0 <= state.dominance <= 1.0


def test_initialize_state_high_income_higher_dominance():
    """High income → higher average dominance than low income."""
    engine = EmotionalEngine()
    rng = random.Random(42)
    high_dominances = []
    low_dominances = []
    for _ in range(50):
        ph = _make_profile(income_bracket="高收入")
        pl = _make_profile(income_bracket="低收入")
        high_dominances.append(engine.initialize_state(1, "s", ph, rng=rng).dominance)
        low_dominances.append(engine.initialize_state(1, "s", pl, rng=rng).dominance)
    assert sum(high_dominances) / len(high_dominances) > sum(low_dominances) / len(low_dominances)


def test_initialize_state_high_extraversion_high_arousal():
    """Extraverted agents tend to have higher arousal at initialization."""
    engine = EmotionalEngine()
    rng = random.Random(42)
    high_arousal = []
    low_arousal = []
    for _ in range(50):
        ph = _make_profile(extraversion=0.9)
        pl = _make_profile(extraversion=0.1)
        high_arousal.append(engine.initialize_state(1, "s", ph, rng=rng).arousal)
        low_arousal.append(engine.initialize_state(1, "s", pl, rng=rng).arousal)
    assert sum(high_arousal) / len(high_arousal) > sum(low_arousal) / len(low_arousal)


# ---------------------------------------------------------------------------
# update_state tests
# ---------------------------------------------------------------------------

def test_update_state_returns_new_state():
    """update_state returns a new EmotionalState object."""
    engine = EmotionalEngine()
    state = _state()
    profile = _make_profile()
    new_state = engine.update_state(state, profile, 0.0, 0.0, 0.0, 0.0)
    assert isinstance(new_state, EmotionalState)
    assert new_state is not state


def test_valence_inertia():
    """Positive valence state should maintain positive valence (inertia)."""
    engine = EmotionalEngine()
    state = _state(valence=0.8, arousal=0.3)
    profile = _make_profile()
    # All influence signals neutral (0.0) → valence should stay positive
    new_state = engine.update_state(state, profile, 0.0, 0.0, 0.0, 0.0)
    assert new_state.valence > 0.0


def test_negative_valence_inertia():
    """Negative valence should persist with inertia."""
    engine = EmotionalEngine()
    state = _state(valence=-0.8)
    profile = _make_profile()
    new_state = engine.update_state(state, profile, 0.0, 0.0, 0.0, 0.0)
    assert new_state.valence < 0.0


def test_social_influence_on_valence():
    """Positive feed sentiment should push valence upward."""
    engine = EmotionalEngine()
    state = _state(valence=-0.5)
    profile = _make_profile(agreeableness=0.8)  # High agreeableness → more social influence
    new_state = engine.update_state(state, profile, 1.0, 0.0, 0.0, 0.0)  # Very positive feed
    assert new_state.valence > state.valence


def test_macro_shock_depresses_valence():
    """Negative macro shock should depress valence."""
    engine = EmotionalEngine()
    state = _state(valence=0.5)
    profile = _make_profile(neuroticism=0.8)  # High neuroticism amplifies macro
    new_state = engine.update_state(state, profile, 0.0, -1.0, 0.0, 0.0)
    assert new_state.valence < state.valence


def test_arousal_spike_on_large_valence_change():
    """Large valence change (negative macro shock) should spike arousal."""
    engine = EmotionalEngine()
    state = _state(valence=0.5, arousal=0.2)
    profile = _make_profile(neuroticism=0.8)
    # Extreme negative macro signal → big valence change
    new_state = engine.update_state(state, profile, 0.0, -1.0, -1.0, 0.5)
    # Arousal should be higher than initial
    assert new_state.arousal > 0.2


def test_arousal_decay_toward_baseline():
    """High arousal should decay toward baseline when no controversy."""
    engine = EmotionalEngine()
    state = _state(arousal=0.95)
    profile = _make_profile(extraversion=0.5)
    new_state = engine.update_state(state, profile, 0.0, 0.0, 0.0, 0.0)
    assert new_state.arousal < 0.95


def test_controversy_boosts_arousal():
    """High controversy exposure should increase arousal."""
    engine = EmotionalEngine()
    state = _state(arousal=0.3)
    profile = _make_profile()
    new_state = engine.update_state(state, profile, 0.0, 0.0, 0.0, 1.0)  # max controversy
    assert new_state.arousal > 0.3


def test_pending_arousal_delta_applied():
    """Pending arousal delta from dissonance denial should increase arousal."""
    engine = EmotionalEngine()
    state = _state(arousal=0.3)
    profile = _make_profile()
    new_state_with = engine.update_state(state, profile, 0.0, 0.0, 0.0, 0.0, pending_arousal_delta=0.3)
    new_state_without = engine.update_state(state, profile, 0.0, 0.0, 0.0, 0.0, pending_arousal_delta=0.0)
    assert new_state_with.arousal > new_state_without.arousal


def test_valence_clamped_to_bounds():
    """Valence must stay in [-1, +1]."""
    engine = EmotionalEngine()
    state = _state(valence=0.9)
    profile = _make_profile()
    for _ in range(10):
        state = engine.update_state(state, profile, 1.0, 1.0, 1.0, 0.0)
    assert -1.0 <= state.valence <= 1.0


def test_arousal_clamped_to_bounds():
    """Arousal must stay in [0, 1]."""
    engine = EmotionalEngine()
    state = _state(arousal=0.9)
    profile = _make_profile()
    for _ in range(10):
        state = engine.update_state(state, profile, 1.0, 1.0, 1.0, 1.0, pending_arousal_delta=0.5)
    assert 0.0 <= state.arousal <= 1.0


def test_neurotic_amplifies_negative_valence():
    """Highly neurotic agents should show stronger negative valence shifts."""
    engine = EmotionalEngine()
    state = _state(valence=0.2)
    p_neurotic = _make_profile(neuroticism=0.9)
    p_stable = _make_profile(neuroticism=0.1)
    ns_n = engine.update_state(state, p_neurotic, 0.0, -1.0, 0.0, 0.0)
    ns_s = engine.update_state(state, p_stable, 0.0, -1.0, 0.0, 0.0)
    assert ns_n.valence < ns_s.valence


def test_agreeable_boosts_social_influence():
    """Agreeable agents should be more influenced by feed sentiment."""
    engine = EmotionalEngine()
    state = _state(valence=-0.5)
    p_agree = _make_profile(agreeableness=0.9)
    p_disagree = _make_profile(agreeableness=0.1)
    ns_agree = engine.update_state(state, p_agree, 1.0, 0.0, 0.0, 0.0)
    ns_disagree = engine.update_state(state, p_disagree, 1.0, 0.0, 0.0, 0.0)
    # Agreeable should shift more toward positive feed
    assert ns_agree.valence > ns_disagree.valence


# ---------------------------------------------------------------------------
# Async persist/load tests (mock DB)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_persist_states():
    """persist_states should call executemany and commit."""
    engine = EmotionalEngine()
    mock_db = AsyncMock()
    states = [
        EmotionalState(agent_id=1, session_id="s", round_number=1, valence=0.1, arousal=0.3, dominance=0.4),
        EmotionalState(agent_id=2, session_id="s", round_number=1, valence=-0.2, arousal=0.5, dominance=0.3),
    ]
    await engine.persist_states(states, mock_db)
    mock_db.executemany.assert_awaited_once()
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_persist_empty_states():
    """persist_states with empty list should not touch DB."""
    engine = EmotionalEngine()
    mock_db = AsyncMock()
    await engine.persist_states([], mock_db)
    mock_db.executemany.assert_not_awaited()


@pytest.mark.asyncio
async def test_load_states():
    """load_states should parse DB rows into EmotionalState objects."""
    engine = EmotionalEngine()
    mock_db = AsyncMock()
    mock_cursor = AsyncMock()
    mock_cursor.fetchall.return_value = [
        (1, 0.2, 0.4, 0.5),
        (2, -0.1, 0.3, 0.45),
    ]
    mock_db.execute.return_value = mock_cursor

    states = await engine.load_states("session-x", 3, mock_db)
    assert len(states) == 2
    assert states[1].valence == 0.2
    assert states[2].valence == -0.1
    assert all(isinstance(s, EmotionalState) for s in states.values())
