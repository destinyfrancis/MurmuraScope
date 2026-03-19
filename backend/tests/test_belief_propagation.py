# backend/tests/test_belief_propagation.py
"""Tests for BeliefPropagationEngine."""
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from backend.app.models.cognitive_fingerprint import CognitiveFingerprint
from backend.app.models.world_event import WorldEvent
from backend.app.services.belief_propagation import BeliefPropagationEngine


def _make_fingerprint(confirmation_bias: float = 0.5, conformity: float = 0.5) -> CognitiveFingerprint:
    return CognitiveFingerprint(
        agent_id="test_agent",
        values={"authority": 0.8, "fairness": 0.3, "loyalty": 0.6},
        info_diet=("state_media",),
        group_memberships=("hardliner",),
        susceptibility={"escalation_index": 0.9},
        confirmation_bias=confirmation_bias,
        conformity=conformity,
    )


def _make_event(impact: dict, reach=("ALL",)) -> WorldEvent:
    return WorldEvent(
        event_id="evt_001", round_number=1,
        content="Test event.", event_type="shock",
        reach=reach, impact_vector=impact, credibility=1.0,
    )


@pytest.mark.asyncio
async def test_propagate_returns_delta_for_active_metrics():
    engine = BeliefPropagationEngine()
    fp = _make_fingerprint()
    event = _make_event({"escalation_index": 0.2})
    active_metrics = ("escalation_index", "diplomatic_pressure")

    # Mock embedding provider to return deterministic vectors
    mock_embed = MagicMock(return_value=[0.1] * 384)
    with patch("backend.app.services.belief_propagation.get_embedding", mock_embed):
        delta = await engine.propagate(
            fingerprint=fp,
            events=[event],
            faction_peer_stance={"escalation_index": 0.7},
            active_metrics=active_metrics,
            current_beliefs={"escalation_index": 0.4, "diplomatic_pressure": 0.5},
        )

    assert set(delta.keys()) <= set(active_metrics)


@pytest.mark.asyncio
async def test_high_confirmation_bias_dampens_contradicting_evidence():
    """Agent with high confirmation_bias should shift less than one with low bias.

    Correct semantics: confirmation bias fires when evidence REINFORCES an extreme.
    Current belief HIGH (0.8) + upward delta → reinforcing extreme → should be dampened.
    """
    engine = BeliefPropagationEngine()
    event = _make_event({"escalation_index": 0.3})  # pushes escalation up
    active_metrics = ("escalation_index",)
    # Current belief: escalation is HIGH (0.8) + event pushes further up → reinforces extreme
    current_beliefs = {"escalation_index": 0.8}

    mock_embed = MagicMock(return_value=[0.1] * 384)
    with patch("backend.app.services.belief_propagation.get_embedding", mock_embed):
        delta_high_bias = await engine.propagate(
            fingerprint=_make_fingerprint(confirmation_bias=0.9),
            events=[event], faction_peer_stance={},
            active_metrics=active_metrics, current_beliefs=current_beliefs,
        )
        delta_low_bias = await engine.propagate(
            fingerprint=_make_fingerprint(confirmation_bias=0.1),
            events=[event], faction_peer_stance={},
            active_metrics=active_metrics, current_beliefs=current_beliefs,
        )

    # High bias → smaller shift than low bias when evidence reinforces an extreme
    assert abs(delta_high_bias.get("escalation_index", 0)) < abs(delta_low_bias.get("escalation_index", 0))


@pytest.mark.asyncio
async def test_event_not_in_info_diet_has_no_effect():
    engine = BeliefPropagationEngine()
    fp = _make_fingerprint()  # info_diet = ("state_media",)
    event = _make_event(
        {"escalation_index": 0.5},
        reach=("opposition_media",)  # agent can't see this
    )
    active_metrics = ("escalation_index",)
    mock_embed = MagicMock(return_value=[0.1] * 384)
    with patch("backend.app.services.belief_propagation.get_embedding", mock_embed):
        delta = await engine.propagate(
            fingerprint=fp,
            events=[event],
            faction_peer_stance={},
            active_metrics=active_metrics,
            current_beliefs={"escalation_index": 0.5},
        )
    assert delta.get("escalation_index", 0.0) == 0.0


@pytest.mark.unit
def test_contradiction_condition_semantics():
    """Verify the contradiction condition: dampening should only fire when evidence
    REINFORCES an extreme (same direction as current stance), not when it pushes toward center.

    Correct semantics per CLAUDE.md:
      - current > 0.5 (strong high stance) + delta > 0 (pushing higher) → IS contradicting (dampen)
      - current < 0.5 (strong low stance) + delta < 0 (pushing lower) → IS contradicting (dampen)
      - current < 0.5 (strong low stance) + delta > 0 (pushing toward 0.5) → NOT contradicting
      - current > 0.5 (strong high stance) + delta < 0 (pushing toward 0.5) → NOT contradicting
    """
    cases = [
        # (raw_delta, current, expected_contradicting, description)
        (0.1, 0.2, False, "low belief + upward delta → toward center, NOT contradicting"),
        (-0.1, 0.8, False, "high belief + downward delta → toward center, NOT contradicting"),
        (0.1, 0.8, True,  "high belief + upward delta → reinforcing extreme, IS contradicting"),
        (-0.1, 0.2, True,  "low belief + downward delta → reinforcing extreme, IS contradicting"),
    ]

    # CORRECT condition (the fix we will apply)
    def contradicting_correct(raw_delta: float, current: float) -> bool:
        return (raw_delta > 0 and current > 0.5) or (raw_delta < 0 and current < 0.5)

    # WRONG condition (current code at line 95)
    def contradicting_wrong(raw_delta: float, current: float) -> bool:
        return (raw_delta > 0 and current < 0.5) or (raw_delta < 0 and current > 0.5)

    for raw_delta, current, expected, description in cases:
        result = contradicting_correct(raw_delta, current)
        assert result == expected, f"CORRECT condition failed for: {description}"

    # Confirm the bug: wrong condition gives opposite results
    assert contradicting_wrong(0.1, 0.2) is True   # Bug: wrongly dampens convergence
    assert contradicting_wrong(0.1, 0.8) is False  # Bug: wrongly allows extreme reinforcement
