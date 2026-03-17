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
    """Agent with high confirmation_bias should shift less than one with low bias."""
    engine = BeliefPropagationEngine()
    event = _make_event({"escalation_index": 0.3})  # pushes escalation up
    active_metrics = ("escalation_index",)
    # Current belief: escalation is LOW (0.2) — event contradicts this
    current_beliefs = {"escalation_index": 0.2}

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

    # High bias → smaller shift than low bias
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
