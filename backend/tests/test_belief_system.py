"""Tests for BeliefSystem and Belief models (Phase 3)."""

from __future__ import annotations

import random
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app.models.emotional_state import CORE_BELIEF_TOPICS, Belief, BeliefState
from backend.app.services.belief_system import BeliefSystem

# ---------------------------------------------------------------------------
# Helper fixtures
# ---------------------------------------------------------------------------


def _make_profile(
    agent_id: int = 1,
    age: int = 35,
    occupation: str = "辦公室職員",
    income_bracket: str = "中收入",
    district: str = "九龍城",
    political_stance: float = 0.5,
    openness: float = 0.5,
) -> MagicMock:
    p = MagicMock()
    p.id = agent_id
    p.age = age
    p.occupation = occupation
    p.income_bracket = income_bracket
    p.district = district
    p.political_stance = political_stance
    p.openness = openness
    return p


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


def test_belief_creation():
    """Belief is a frozen dataclass with correct defaults."""
    b = Belief(topic="economy_outlook")
    assert b.stance == 0.0
    assert b.confidence == 0.5
    assert b.evidence_count == 0
    assert b.last_updated == 0


def test_belief_frozen():
    """Belief cannot be mutated."""
    b = Belief(topic="government_trust")
    with pytest.raises((AttributeError, TypeError)):
        b.stance = 0.5  # type: ignore[misc]


def test_belief_replace():
    """Replace() on Belief creates new object."""
    b = Belief(topic="economy_outlook", stance=0.2)
    b2 = replace(b, stance=0.8)
    assert b.stance == 0.2
    assert b2.stance == 0.8


def test_belief_state_creation():
    """BeliefState is a frozen transient container."""
    bs = BeliefState(agent_id=1, session_id="s1")
    assert bs.beliefs == ()


def test_belief_state_max_beliefs():
    """BeliefState should allow up to 8 beliefs."""
    beliefs = tuple(Belief(topic=f"topic_{i}") for i in range(8))
    bs = BeliefState(agent_id=1, session_id="s", beliefs=beliefs)
    assert len(bs.beliefs) == 8


def test_core_belief_topics_count():
    """CORE_BELIEF_TOPICS should contain exactly 6 topics."""
    assert len(CORE_BELIEF_TOPICS) == 6
    assert "property_outlook" in CORE_BELIEF_TOPICS
    assert "government_trust" in CORE_BELIEF_TOPICS


# ---------------------------------------------------------------------------
# initialize_beliefs tests
# ---------------------------------------------------------------------------


def test_initialize_beliefs_returns_six():
    """initialize_beliefs should return 6 beliefs (one per core topic)."""
    system = BeliefSystem()
    profile = _make_profile()
    beliefs = system.initialize_beliefs(1, "s", profile)
    assert len(beliefs) == 6


def test_initialize_beliefs_all_topics_present():
    """All 6 core topics must be present."""
    system = BeliefSystem()
    profile = _make_profile()
    beliefs = system.initialize_beliefs(1, "s", profile)
    topics = {b.topic for b in beliefs}
    assert topics == set(CORE_BELIEF_TOPICS)


def test_initialize_beliefs_stance_in_range():
    """All initial stances should be in [-1, +1]."""
    system = BeliefSystem()
    rng = random.Random(42)
    for _ in range(20):
        profile = _make_profile(
            age=rng.randint(18, 70),
            political_stance=rng.random(),
        )
        beliefs = system.initialize_beliefs(1, "s", profile, rng=rng)
        for b in beliefs:
            assert -1.0 <= b.stance <= 1.0


def test_initialize_beliefs_pro_establishment_trusts_government():
    """Pro-establishment agent (stance=0) should have higher government trust."""
    system = BeliefSystem()
    p_pro = _make_profile(political_stance=0.0)
    p_dem = _make_profile(political_stance=1.0)
    beliefs_pro = {b.topic: b for b in system.initialize_beliefs(1, "s", p_pro)}
    beliefs_dem = {b.topic: b for b in system.initialize_beliefs(1, "s", p_dem)}
    assert beliefs_pro["government_trust"].stance > beliefs_dem["government_trust"].stance


def test_initialize_beliefs_high_income_bullish_property():
    """High income agents should be more bullish on property."""
    system = BeliefSystem()
    p_high = _make_profile(income_bracket="高收入")
    p_low = _make_profile(income_bracket="低收入")
    b_high = {b.topic: b for b in system.initialize_beliefs(1, "s", p_high)}
    b_low = {b.topic: b for b in system.initialize_beliefs(1, "s", p_low)}
    assert b_high["property_outlook"].stance > b_low["property_outlook"].stance


def test_initialize_beliefs_young_open_on_ai():
    """Young agents should be more positive about AI impact."""
    system = BeliefSystem()
    p_young = _make_profile(age=22)
    p_old = _make_profile(age=65)
    b_young = {b.topic: b for b in system.initialize_beliefs(1, "s", p_young)}
    b_old = {b.topic: b for b in system.initialize_beliefs(1, "s", p_old)}
    assert b_young["ai_impact"].stance >= b_old["ai_impact"].stance


# ---------------------------------------------------------------------------
# update_belief tests
# ---------------------------------------------------------------------------


def test_update_belief_shifts_stance():
    """Evidence should shift belief stance toward evidence direction."""
    system = BeliefSystem()
    belief = Belief(topic="economy_outlook", stance=0.0, confidence=0.5)
    updated = system.update_belief(belief, evidence_stance=1.0, evidence_weight=0.5, openness=0.5)
    assert updated.stance > belief.stance


def test_confirmation_bias_boost():
    """Same-direction evidence should get a higher effective weight than opposing evidence.

    We test this by using a neutral starting belief (0.0) and comparing:
    1. Evidence that confirms a same-direction belief (positive prior, positive evidence)
    2. Evidence that opposes a same-direction belief (negative prior, positive evidence)
    The confirming case should produce larger stance shift per unit of evidence weight.
    """
    system = BeliefSystem()
    # Both beliefs start at 0.0 but we compare effective weights
    # Use a belief with stronger existing stance to show confirmation effect
    belief_pos = Belief(topic="economy_outlook", stance=0.5, confidence=0.5)
    belief_neg = Belief(topic="economy_outlook", stance=-0.5, confidence=0.5)
    # Positive evidence for positive prior (same direction) → should have higher effective weight
    # than positive evidence for negative prior (opposing direction)
    same_dir = system.update_belief(belief_pos, 1.0, 0.5, openness=0.0)
    opp_dir = system.update_belief(belief_neg, 1.0, 0.5, openness=0.0)
    # Same-dir should move further toward 1.0 than opp-dir (per unit distance from 1.0)
    # same_dir: started at 0.5, moved to same_dir.stance
    # opp_dir: started at -0.5, moved to opp_dir.stance
    # Normalize by distance to evidence: effective_shift = (new - old) / (evidence - old)
    same_ratio = (same_dir.stance - belief_pos.stance) / (1.0 - belief_pos.stance + 1e-9)
    opp_ratio = (opp_dir.stance - belief_neg.stance) / (1.0 - belief_neg.stance + 1e-9)
    assert same_ratio > opp_ratio


def test_confirmation_bias_resist():
    """Opposing evidence should be weighted less when openness is low."""
    system = BeliefSystem()
    belief = Belief(topic="economy_outlook", stance=0.5, confidence=0.5)
    # Low openness → strong resistance to opposing evidence
    low_open = system.update_belief(belief, -1.0, 0.5, openness=0.0)
    # High openness → weaker resistance
    high_open = system.update_belief(belief, -1.0, 0.5, openness=1.0)
    # High openness should move stance more toward evidence
    assert high_open.stance < low_open.stance


def test_openness_reduces_confirmation_bias():
    """Higher openness should result in closer-to-unbiased updates."""
    system = BeliefSystem()
    belief = Belief(topic="economy_outlook", stance=0.5, confidence=0.5)
    # Opposing evidence
    low_open = system.update_belief(belief, -1.0, 0.5, openness=0.0)
    high_open = system.update_belief(belief, -1.0, 0.5, openness=1.0)
    # High openness → bigger shift toward evidence
    assert high_open.stance < low_open.stance


def test_confidence_increment():
    """Confidence should increase after update."""
    system = BeliefSystem()
    belief = Belief(topic="economy_outlook", stance=0.0, confidence=0.5)
    updated = system.update_belief(belief, 1.0, 0.5, openness=0.5)
    assert updated.confidence > belief.confidence


def test_confidence_capped_at_one():
    """Confidence should not exceed 1.0."""
    system = BeliefSystem()
    belief = Belief(topic="economy_outlook", stance=0.0, confidence=0.95)
    for _ in range(20):
        belief = system.update_belief(belief, 1.0, 1.0, openness=0.5)
    assert belief.confidence <= 1.0


def test_contradictory_evidence_reduces_confidence():
    """Contradictory evidence should reduce confidence (not increase it).

    Without a decrease path, confidence grows monotonically throughout a long
    simulation — agents become irrationally certain and stop updating their
    beliefs.  This test guards against that regression.
    """
    system = BeliefSystem()
    belief = Belief(topic="economy_outlook", stance=0.5, confidence=0.6)
    # Negative evidence contradicts positive prior (stance > 0)
    updated = system.update_belief(belief, -1.0, 0.5, openness=0.5)
    assert updated.confidence < belief.confidence, (
        f"Contradictory evidence must reduce confidence; was {belief.confidence}, got {updated.confidence}"
    )


def test_confidence_floor_on_contradiction():
    """Confidence should not fall below _CONFIDENCE_FLOOR even after many contradictions."""
    system = BeliefSystem()
    belief = Belief(topic="economy_outlook", stance=0.5, confidence=0.6)
    for _ in range(100):
        belief = system.update_belief(belief, -1.0, 1.0, openness=0.5)
    assert belief.confidence >= system._CONFIDENCE_FLOOR


def test_confirming_evidence_still_increases_confidence():
    """Same-direction evidence must still increase confidence (regression guard)."""
    system = BeliefSystem()
    belief = Belief(topic="economy_outlook", stance=0.5, confidence=0.5)
    updated = system.update_belief(belief, 1.0, 0.5, openness=0.5)
    assert updated.confidence > belief.confidence


def test_evidence_count_increments():
    """Evidence count should increment with each update."""
    system = BeliefSystem()
    belief = Belief(topic="economy_outlook")
    updated = system.update_belief(belief, 0.5, 0.3, openness=0.5)
    assert updated.evidence_count == 1


# ---------------------------------------------------------------------------
# extract_stance tests
# ---------------------------------------------------------------------------


def test_extract_stance_property_positive():
    """Positive property keyword should return positive stance."""
    system = BeliefSystem()
    result = system.extract_stance("樓市向好，買樓時機來了", "property_outlook")
    assert result is not None
    assert result > 0


def test_extract_stance_economy_negative():
    """Negative economy keyword should return negative stance."""
    system = BeliefSystem()
    result = system.extract_stance("經濟衰退，失業率上升", "economy_outlook")
    assert result is not None
    assert result < 0


def test_extract_stance_no_topic_keywords():
    """Text with no relevant keywords should return None."""
    system = BeliefSystem()
    result = system.extract_stance("今天天氣很好", "property_outlook")
    assert result is None


def test_extract_stance_unknown_topic():
    """Unknown topic should return None."""
    system = BeliefSystem()
    result = system.extract_stance("Some text", "unknown_topic")
    assert result is None


def test_extract_stance_government_trust():
    """Government trust keywords should work."""
    system = BeliefSystem()
    result = system.extract_stance("信任政府，政府做得好", "government_trust")
    assert result is not None
    assert result > 0


def test_extract_stance_mixed_signals():
    """Mixed positive/negative keywords should produce partial stance."""
    system = BeliefSystem()
    # Both positive and negative keywords present
    result = system.extract_stance("樓市向好但也有人認為跌市", "property_outlook")
    assert result is not None
    # Should be between -1 and +1
    assert -1.0 <= result <= 1.0


# ---------------------------------------------------------------------------
# Async persist/load tests (mock DB)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_beliefs():
    """persist_beliefs should call executemany and commit."""
    system = BeliefSystem()
    mock_db = AsyncMock()
    beliefs = [
        Belief(topic="economy_outlook", stance=0.2, confidence=0.6),
        Belief(topic="government_trust", stance=-0.3, confidence=0.4),
    ]
    await system.persist_beliefs("s", 1, beliefs, 2, mock_db)
    mock_db.executemany.assert_awaited_once()
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_persist_empty_beliefs():
    """persist_beliefs with empty list should not touch DB."""
    system = BeliefSystem()
    mock_db = AsyncMock()
    await system.persist_beliefs("s", 1, [], 2, mock_db)
    mock_db.executemany.assert_not_awaited()


@pytest.mark.asyncio
async def test_load_beliefs():
    """load_beliefs should parse DB rows into Belief objects."""
    system = BeliefSystem()
    mock_db = AsyncMock()
    mock_cursor = AsyncMock()
    mock_cursor.fetchall.return_value = [
        ("economy_outlook", 0.3, 0.6, 2),
        ("government_trust", -0.2, 0.5, 1),
    ]
    mock_db.execute.return_value = mock_cursor

    beliefs = await system.load_beliefs("s", 1, 3, mock_db)
    assert len(beliefs) == 2
    assert beliefs[0].topic == "economy_outlook"
    assert beliefs[0].stance == 0.3
    assert all(isinstance(b, Belief) for b in beliefs)
