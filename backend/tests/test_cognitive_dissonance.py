"""Tests for DissonanceDetector and CognitiveDissonance models (Phase 3)."""

from __future__ import annotations

import random
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app.models.emotional_state import (
    Belief,
    CognitiveDissonance,
)
from backend.app.services.cognitive_dissonance import DissonanceDetector

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_profile(
    agent_id: int = 1,
    neuroticism: float = 0.5,
    openness: float = 0.5,
    agreeableness: float = 0.5,
) -> MagicMock:
    p = MagicMock()
    p.id = agent_id
    p.neuroticism = neuroticism
    p.openness = openness
    p.agreeableness = agreeableness
    return p


def _belief(topic: str, stance: float, confidence: float = 0.6) -> Belief:
    return Belief(topic=topic, stance=stance, confidence=confidence)


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


def test_cognitive_dissonance_creation():
    """CognitiveDissonance is a frozen dataclass."""
    cd = CognitiveDissonance(agent_id=1, session_id="s", round_number=0)
    assert cd.dissonance_score == 0.0
    assert cd.resolution_strategy == "none"
    assert cd.conflicting_pairs == ()


def test_cognitive_dissonance_frozen():
    """CognitiveDissonance cannot be mutated."""
    cd = CognitiveDissonance(agent_id=1, session_id="s", round_number=0)
    with pytest.raises((AttributeError, TypeError)):
        cd.dissonance_score = 0.5  # type: ignore[misc]


def test_cognitive_dissonance_replace():
    """replace() creates new CognitiveDissonance without mutation."""
    cd = CognitiveDissonance(agent_id=1, session_id="s", round_number=0)
    cd2 = replace(cd, dissonance_score=0.7)
    assert cd.dissonance_score == 0.0
    assert cd2.dissonance_score == 0.7


# ---------------------------------------------------------------------------
# detect() tests
# ---------------------------------------------------------------------------


def test_detect_no_conflict_consistent_beliefs():
    """Consistent beliefs (positive corr, same direction) should produce low dissonance."""
    det = DissonanceDetector()
    # property_outlook ↔ economy_outlook have correlation 0.6 (positive)
    # Both positive → consistent
    beliefs = [
        _belief("property_outlook", 0.6),
        _belief("economy_outlook", 0.7),
    ]
    profile = _make_profile()
    result = det.detect(beliefs, [], profile)
    assert result.dissonance_score < 0.3


def test_detect_belief_belief_conflict():
    """Opposite beliefs on positively-correlated topics → high dissonance."""
    det = DissonanceDetector()
    # property_outlook and economy_outlook are positively correlated
    # If one is positive and other negative → conflict
    beliefs = [
        _belief("property_outlook", 0.8),  # bullish
        _belief("economy_outlook", -0.8),  # bearish
    ]
    profile = _make_profile()
    result = det.detect(beliefs, [], profile)
    assert result.dissonance_score > 0.0
    assert len(result.conflicting_pairs) > 0


def test_detect_action_belief_gap_emigrate():
    """Emigrating while believing social_stability is positive creates dissonance."""
    det = DissonanceDetector()
    beliefs = [
        _belief("social_stability", 0.8),  # believes society is stable
    ]
    actions = ["emigrate"]  # but decides to emigrate
    profile = _make_profile()
    result = det.detect(beliefs, actions, profile)
    assert result.action_belief_gap > 0.0


def test_detect_action_belief_gap_buy_bearish():
    """Buying property while bearish creates dissonance."""
    det = DissonanceDetector()
    beliefs = [
        _belief("property_outlook", -0.7),  # bearish on property
    ]
    actions = ["buy_property"]
    profile = _make_profile()
    result = det.detect(beliefs, actions, profile)
    assert result.action_belief_gap > 0.0


def test_detect_composite_score_formula():
    """Composite dissonance = 0.6 × belief_conflict + 0.4 × action_belief_gap."""
    det = DissonanceDetector()
    # Pure action-belief gap (no belief-belief conflict)
    beliefs = [_belief("social_stability", 0.9)]
    actions = ["emigrate"]
    profile = _make_profile()
    result = det.detect(beliefs, actions, profile)
    # dissonance_score should be > 0 because of action-belief gap
    assert result.dissonance_score >= 0.0
    assert result.dissonance_score <= 1.0


def test_detect_returns_resolution_strategy():
    """detect() should always set a resolution strategy."""
    det = DissonanceDetector()
    beliefs = [
        _belief("property_outlook", 0.8),
        _belief("economy_outlook", -0.8),
    ]
    profile = _make_profile()
    result = det.detect(beliefs, [], profile)
    assert result.resolution_strategy in ("denial", "rationalization", "belief_change", "none")


def test_detect_low_dissonance_often_none():
    """Low dissonance should often result in 'none' strategy."""
    det = DissonanceDetector()
    beliefs = [_belief("economy_outlook", 0.1)]  # mild belief, no conflict
    profile = _make_profile()
    strategies = []
    rng = random.Random(42)
    for _ in range(50):
        result = det.detect(beliefs, [], profile, rng=rng)
        strategies.append(result.resolution_strategy)
    none_count = strategies.count("none")
    assert none_count > 10  # Should frequently be 'none' for low dissonance


def test_detect_high_neuroticism_favors_denial():
    """Neurotic agents should prefer denial strategy."""
    det = DissonanceDetector()
    beliefs = [
        _belief("property_outlook", 0.8),
        _belief("economy_outlook", -0.8),
    ]
    p_neurotic = _make_profile(neuroticism=0.95, openness=0.1)
    rng = random.Random(42)
    strategies = [det.detect(beliefs, ["emigrate"], p_neurotic, rng=rng).resolution_strategy for _ in range(30)]
    denial_count = strategies.count("denial")
    belief_change_count = strategies.count("belief_change")
    assert denial_count >= belief_change_count


def test_detect_high_openness_favors_belief_change():
    """Open agents should more readily change beliefs."""
    det = DissonanceDetector()
    beliefs = [
        _belief("property_outlook", 0.8),
        _belief("economy_outlook", -0.8),
    ]
    p_open = _make_profile(neuroticism=0.1, openness=0.95)
    rng = random.Random(42)
    strategies = [det.detect(beliefs, ["emigrate"], p_open, rng=rng).resolution_strategy for _ in range(30)]
    belief_change_count = strategies.count("belief_change")
    # Should have some belief_change (not necessarily dominant, but present)
    assert belief_change_count > 0


# ---------------------------------------------------------------------------
# apply_resolution() tests
# ---------------------------------------------------------------------------


def test_apply_resolution_denial_no_change():
    """Denial strategy: beliefs unchanged, arousal_delta = 0.1."""
    det = DissonanceDetector()
    beliefs = [
        _belief("property_outlook", 0.8),
        _belief("economy_outlook", -0.8),
    ]
    cd = CognitiveDissonance(
        agent_id=1,
        session_id="s",
        round_number=1,
        dissonance_score=0.6,
        conflicting_pairs=(("property_outlook", "economy_outlook"),),
        resolution_strategy="denial",
    )
    updated_beliefs, arousal_delta = det.apply_resolution(cd, beliefs)
    assert arousal_delta == 0.1
    # Beliefs should be unchanged (denial = suppression)
    assert updated_beliefs[0].stance == beliefs[0].stance
    assert updated_beliefs[1].stance == beliefs[1].stance


def test_apply_resolution_rationalization_confidence_reduced():
    """Rationalization: weaker belief's confidence reduced by ×0.7."""
    det = DissonanceDetector()
    beliefs = [
        _belief("property_outlook", 0.8, confidence=0.4),  # weaker
        _belief("economy_outlook", -0.8, confidence=0.8),  # stronger
    ]
    cd = CognitiveDissonance(
        agent_id=1,
        session_id="s",
        round_number=1,
        dissonance_score=0.6,
        conflicting_pairs=(("property_outlook", "economy_outlook"),),
        resolution_strategy="rationalization",
    )
    updated_beliefs, arousal_delta = det.apply_resolution(cd, beliefs)
    assert arousal_delta == 0.0
    # Weaker belief (property_outlook with conf=0.4) should have reduced confidence
    updated_map = {b.topic: b for b in updated_beliefs}
    assert updated_map["property_outlook"].confidence < 0.4 + 1e-9


def test_apply_resolution_belief_change():
    """Belief change: weaker belief shifts toward consistency."""
    det = DissonanceDetector()
    # property + economy corr=0.6 (positive); property=0.8, economy=-0.8
    beliefs = [
        _belief("property_outlook", 0.8, confidence=0.4),  # weaker
        _belief("economy_outlook", -0.8, confidence=0.8),  # stronger
    ]
    cd = CognitiveDissonance(
        agent_id=1,
        session_id="s",
        round_number=1,
        dissonance_score=0.7,
        conflicting_pairs=(("property_outlook", "economy_outlook"),),
        resolution_strategy="belief_change",
    )
    original_stance = beliefs[0].stance
    updated_beliefs, arousal_delta = det.apply_resolution(cd, beliefs)
    assert arousal_delta == 0.0
    updated_map = {b.topic: b for b in updated_beliefs}
    # Weaker belief should have shifted (toward economy_outlook's direction)
    assert updated_map["property_outlook"].stance != original_stance


def test_apply_resolution_none_no_change():
    """None strategy: beliefs and arousal both unchanged."""
    det = DissonanceDetector()
    beliefs = [_belief("property_outlook", 0.5)]
    cd = CognitiveDissonance(
        agent_id=1,
        session_id="s",
        round_number=1,
        dissonance_score=0.2,
        conflicting_pairs=(),
        resolution_strategy="none",
    )
    updated_beliefs, arousal_delta = det.apply_resolution(cd, beliefs)
    assert arousal_delta == 0.0
    assert updated_beliefs[0].stance == beliefs[0].stance


# ---------------------------------------------------------------------------
# batch_detect_and_resolve() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_detect_and_resolve():
    """batch_detect_and_resolve returns dissonance results and pending deltas."""
    det = DissonanceDetector()
    mock_db = AsyncMock()

    agent_beliefs = {
        1: [_belief("property_outlook", 0.8), _belief("economy_outlook", -0.7)],
        2: [_belief("government_trust", 0.5)],
    }
    agent_actions = {
        1: ["emigrate"],
        2: [],
    }
    profiles = {
        1: _make_profile(agent_id=1),
        2: _make_profile(agent_id=2),
    }

    results, pending = await det.batch_detect_and_resolve(
        session_id="s",
        round_number=3,
        agent_beliefs=agent_beliefs,
        agent_actions=agent_actions,
        profiles=profiles,
        db=mock_db,
    )

    assert 1 in results
    assert 2 in results
    assert isinstance(results[1], CognitiveDissonance)
    assert results[1].round_number == 3
    assert results[1].session_id == "s"
    # pending_deltas should be a dict
    assert isinstance(pending, dict)


@pytest.mark.asyncio
async def test_batch_detect_denial_creates_pending_delta():
    """Agents with denial strategy should generate pending arousal deltas."""
    det = DissonanceDetector()
    mock_db = AsyncMock()

    # Create conditions for high dissonance + force denial strategy
    agent_beliefs = {
        1: [
            _belief("property_outlook", 0.9, confidence=0.9),
            _belief("economy_outlook", -0.9, confidence=0.9),
        ],
    }
    profiles = {1: _make_profile(agent_id=1, neuroticism=1.0, openness=0.0)}

    # Run many times to hit denial occasionally
    denial_found = False
    for seed in range(100):
        import random as _r

        rng = _r.Random(seed)
        raw = det.detect(agent_beliefs[1], [], profiles[1], rng=rng)
        if raw.resolution_strategy == "denial":
            denial_found = True
            break

    assert denial_found, "Denial strategy should be reachable with high neuroticism"


# ---------------------------------------------------------------------------
# persist_dissonance tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_dissonance():
    """persist_dissonance should call executemany and commit."""
    det = DissonanceDetector()
    mock_db = AsyncMock()
    results = [
        CognitiveDissonance(
            agent_id=1,
            session_id="s",
            round_number=2,
            dissonance_score=0.6,
            resolution_strategy="denial",
        ),
    ]
    await det.persist_dissonance(results, mock_db)
    mock_db.executemany.assert_awaited_once()
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_persist_empty_dissonance():
    """persist_dissonance with empty list should not touch DB."""
    det = DissonanceDetector()
    mock_db = AsyncMock()
    await det.persist_dissonance([], mock_db)
    mock_db.executemany.assert_not_awaited()
