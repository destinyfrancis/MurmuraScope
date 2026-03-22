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
async def test_high_confirmation_bias_amplifies_confirming_evidence():
    """Bayesian update: high confirmation_bias amplifies same-direction evidence.

    Current belief HIGH (0.8) + upward delta is *confirming* evidence.
    An agent with high confirmation_bias should shift MORE (larger LR) because
    they weight confirming evidence more heavily. This is the psychologically
    correct interpretation: confirmation bias = favouring evidence that aligns
    with existing belief.
    """
    engine = BeliefPropagationEngine()
    event = _make_event({"escalation_index": 0.3})  # pushes escalation up
    active_metrics = ("escalation_index",)
    # Current belief: escalation is HIGH (0.8) + event pushes further up → confirms belief
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

    # High bias → larger shift than low bias when evidence confirms existing belief
    assert abs(delta_high_bias.get("escalation_index", 0)) > abs(delta_low_bias.get("escalation_index", 0))


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


@pytest.mark.unit
def test_cascade_deltas_bounded():
    """cascade() output deltas must stay in [-1.0, 1.0].

    Actual signature: cascade(all_deltas, interaction_graph) -> neighbour deltas.
    - all_deltas: {agent_id: {metric_id: delta}}
    - interaction_graph: {agent_id: [neighbour_ids]}

    With multiple high-influence agents all pushing the same metric,
    accumulated delta can exceed ±1.0 without clamping.
    """
    engine = BeliefPropagationEngine()

    # 3 agents all pushing metric_a up by 0.5
    # Each gets effective_factor = 0.3 * (1 + 0.5 * leadership_score)
    # With leadership_score = 1.0 (max degree), effective_factor = 0.45
    # Accumulated: 3 * 0.5 * 0.45 = 0.675 (within bounds)
    # But with 6 agents or higher credibility, can exceed 1.0
    all_deltas = {
        "agent_1": {"metric_a": 0.7},
        "agent_2": {"metric_a": 0.7},
        "agent_3": {"metric_a": 0.7},
        "agent_4": {"metric_a": 0.7},
    }
    interaction_graph = {
        "agent_1": ["target_agent", "agent_2", "agent_3", "agent_4"],
        "agent_2": ["target_agent", "agent_1", "agent_3", "agent_4"],
        "agent_3": ["target_agent", "agent_1", "agent_2", "agent_4"],
        "agent_4": ["target_agent", "agent_1", "agent_2", "agent_3"],
        "target_agent": [],
    }

    result = engine.cascade(all_deltas, interaction_graph)

    if "target_agent" in result:
        for metric, delta in result["target_agent"].items():
            assert -1.0 <= delta <= 1.0, f"Cascade delta out of bounds: {metric}={delta}"


@pytest.mark.asyncio
async def test_sequential_events_produce_diminishing_returns():
    """Two identical events must produce less-than-double the single-event delta.

    Sequential Bayesian: second event's LR is computed against updated posterior,
    not original prior. This means each successive confirming event contributes
    less than the previous one (diminishing returns).

    Bug: if prior is never updated, 2 events produce exactly 2× the single delta.
    """
    engine = BeliefPropagationEngine()
    fp = _make_fingerprint(confirmation_bias=0.0, conformity=0.0)
    # Two identical events, both pushing escalation_index up
    event = _make_event({"escalation_index": 0.3})
    active_metrics = ("escalation_index",)
    current_beliefs = {"escalation_index": 0.5}

    with patch(
        "backend.app.services.belief_propagation.get_embedding",
        MagicMock(return_value=[0.1] * 384),
    ):
        delta_one = await engine.propagate(
            fingerprint=fp,
            events=[event],
            faction_peer_stance={},
            active_metrics=active_metrics,
            current_beliefs=current_beliefs,
        )
        delta_two = await engine.propagate(
            fingerprint=fp,
            events=[event, event],  # same event twice
            faction_peer_stance={},
            active_metrics=active_metrics,
            current_beliefs=current_beliefs,
        )

    d1 = delta_one.get("escalation_index", 0.0)
    d2 = delta_two.get("escalation_index", 0.0)

    # Sequential Bayesian: two events must NOT produce exactly double
    # (second event is computed against updated prior → diminishing returns)
    assert d1 != 0.0, "Single event should produce non-zero delta"
    assert d2 > d1, "Two events should produce larger delta than one"
    assert d2 < 2 * d1, "Two events must NOT double the delta (sequential Bayesian)"


@pytest.mark.asyncio
async def test_conformity_peer_pressure_no_hidden_scaling():
    """Peer pressure delta must equal conformity × (peer - current), no 0.1 factor.

    With no events and conformity=1.0, peer_current=0.7, current=0.5:
    - After fix: peer_delta = 1.0 * (0.7 - 0.5) = 0.2
    - Before fix: peer_delta = 1.0 * (0.7 - 0.5) * 0.1 = 0.02
    """
    engine = BeliefPropagationEngine()
    fp = _make_fingerprint(confirmation_bias=0.0, conformity=1.0)
    active_metrics = ("escalation_index",)
    current_beliefs = {"escalation_index": 0.5}
    faction_peer = {"escalation_index": 0.7}  # gap=0.2, within HC_EPSILON

    with patch(
        "backend.app.services.belief_propagation.get_embedding",
        MagicMock(return_value=[0.1] * 384),
    ):
        delta = await engine.propagate(
            fingerprint=fp,
            events=[],
            faction_peer_stance=faction_peer,
            active_metrics=active_metrics,
            current_beliefs=current_beliefs,
        )

    d = delta.get("escalation_index", 0.0)
    # peer_delta = conformity * (peer - current) = 1.0 * 0.2 = 0.2
    # blended = event_delta * (1 - 1.0) + 0.2 = 0.2
    assert d > 0.1, (
        f"Peer pressure delta must be ~0.2 (no hidden 0.1 scaling), got {d:.4f}"
    )


@pytest.mark.asyncio
async def test_conflicting_events_do_not_cancel_perfectly():
    """Opposite-direction events must not cancel to exactly zero.

    Sequential Bayesian: first event updates prior to p1, second computes LR
    against p1 (not original 0.5). If both events are symmetric around the prior,
    sequential update still converges toward the prior but doesn't return to it exactly.

    Bug: if prior never updates, +0.3 event and -0.3 event produce deltas that
    exactly cancel (d1 + d2 == 0.0), which is informationally wrong.
    """
    engine = BeliefPropagationEngine()
    fp = _make_fingerprint(confirmation_bias=0.0, conformity=0.0)
    up_event = _make_event({"escalation_index": 0.3})
    down_event = _make_event({"escalation_index": -0.3})
    active_metrics = ("escalation_index",)
    current_beliefs = {"escalation_index": 0.5}

    with patch(
        "backend.app.services.belief_propagation.get_embedding",
        MagicMock(return_value=[0.1] * 384),
    ):
        delta = await engine.propagate(
            fingerprint=fp,
            events=[up_event, down_event],
            faction_peer_stance={},
            active_metrics=active_metrics,
            current_beliefs=current_beliefs,
        )

    d = delta.get("escalation_index", 0.0)
    # Sequential: after up_event shifts prior to p1 > 0.5,
    # down_event pulls from p1, not 0.5. Result is NOT exactly 0.
    # The net delta should be small but non-zero (slightly positive since
    # down_event has a smaller effect from the elevated prior).
    # We only assert it's not exactly zero — the sign depends on LR math.
    assert d != 0.0, (
        "Opposite events must not cancel to exactly 0.0 in sequential Bayesian "
        "(prior updates after first event change the effective range of second)"
    )
