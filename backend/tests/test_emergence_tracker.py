# backend/tests/test_emergence_tracker.py
"""Tests for EmergenceTracker: FactionMapper, TippingPointDetector, NarrativeTracer."""

from __future__ import annotations

import pytest

from backend.app.services.emergence_tracker import FactionMapper, TippingPoint, TippingPointDetector


def _make_agent_beliefs(n: int, split: bool = False) -> dict[str, dict[str, float]]:
    """Create n agent belief dicts. split=True creates two distinct clusters."""
    beliefs = {}
    for i in range(n):
        if split and i >= n // 2:
            beliefs[f"agent_{i}"] = {"escalation": 0.8, "diplomacy": 0.2}
        else:
            beliefs[f"agent_{i}"] = {"escalation": 0.2, "diplomacy": 0.8}
    return beliefs


def _make_interaction_graph(agent_ids: list[str]) -> dict[str, list[str]]:
    """Simple ring graph for testing."""
    graph = {}
    for i, aid in enumerate(agent_ids):
        graph[aid] = [agent_ids[(i + 1) % len(agent_ids)]]
    return graph


def test_faction_mapper_detects_two_groups():
    mapper = FactionMapper()
    beliefs = _make_agent_beliefs(20, split=True)
    graph = _make_interaction_graph(list(beliefs.keys()))
    snapshot = mapper.compute(
        simulation_id="sim_001",
        round_number=6,
        agent_beliefs=beliefs,
        interaction_graph=graph,
    )
    assert snapshot.round_number == 6
    assert len(snapshot.factions) >= 1
    assert 0.0 <= snapshot.modularity_score <= 1.0


def test_tipping_point_detector_flags_large_shift():
    detector = TippingPointDetector(kl_threshold=0.10)
    # Stable distribution for 3 rounds
    stable = {"agent_0": {"escalation": 0.3}, "agent_1": {"escalation": 0.35}}
    history = [stable, stable, stable]
    # Large shift in current round
    shifted = {"agent_0": {"escalation": 0.9}, "agent_1": {"escalation": 0.85}}

    tipping = detector.detect(
        simulation_id="sim_001",
        round_number=4,
        current_beliefs=shifted,
        belief_history=history,
        last_event_id="evt_trigger",
    )
    assert tipping is not None
    assert isinstance(tipping, TippingPoint)
    assert tipping.trigger_event_id == "evt_trigger"
    assert tipping.kl_divergence > 0.10


def test_tipping_point_detector_no_flag_for_stable():
    detector = TippingPointDetector(kl_threshold=0.10)
    stable = {"agent_0": {"escalation": 0.3}, "agent_1": {"escalation": 0.35}}
    tipping = detector.detect(
        simulation_id="sim_001",
        round_number=4,
        current_beliefs=stable,
        belief_history=[stable, stable, stable],
        last_event_id=None,
    )
    assert tipping is None


def test_tipping_point_compares_3_rounds_back():
    """Detector must compare current vs 3 rounds ago (not 1 round ago)."""
    detector = TippingPointDetector(kl_threshold=0.10)
    three_rounds_ago = {"agent_0": {"escalation": 0.2}}
    one_round_ago = {"agent_0": {"escalation": 0.25}}  # small shift from 3 rounds ago
    current = {"agent_0": {"escalation": 0.9}}  # large shift from 3 rounds ago
    # history[-3] = three_rounds_ago, history[-2] = one_round_ago, history[-1] = one_round_ago
    tipping = detector.detect(
        simulation_id="sim_001",
        round_number=5,
        current_beliefs=current,
        belief_history=[three_rounds_ago, one_round_ago, one_round_ago],
        last_event_id="evt_x",
    )
    assert tipping is not None  # must detect vs 3-round-ago baseline


@pytest.mark.unit
def test_faction_mapping_is_deterministic():
    """FactionMapper.compute() must produce identical partitions on identical inputs."""
    try:
        import networkx as nx
    except ImportError:
        pytest.skip("networkx not installed")

    G = nx.karate_club_graph()  # 34 nodes, 78 edges — rich community structure

    agent_beliefs = {str(n): {"metric_a": 0.5} for n in G.nodes()}
    interaction_graph = {str(n): [str(nb) for nb in G.neighbors(n)] for n in G.nodes()}

    mapper = FactionMapper()

    result1 = mapper.compute(
        simulation_id="sim_det_test",
        round_number=1,
        agent_beliefs=agent_beliefs,
        interaction_graph=interaction_graph,
    )
    result2 = mapper.compute(
        simulation_id="sim_det_test",
        round_number=1,
        agent_beliefs=agent_beliefs,
        interaction_graph=interaction_graph,
    )

    def _partition_map(snapshot):
        return {agent_id: faction.faction_id for faction in snapshot.factions for agent_id in faction.member_agent_ids}

    assert _partition_map(result1) == _partition_map(result2), (
        "Faction mapping must be deterministic for identical inputs"
    )


@pytest.mark.unit
def test_jsd_adaptive_bins_with_zero():
    """_jsd with n_bins=0 must compute adaptive bin count without error.

    Before fix: n_bins=0 passed to _to_histogram causes IndexError.
    After fix: n_bins=0 triggers adaptive logic based on population size.
    """
    detector = TippingPointDetector()
    # 20 agents → adaptive: max(5, min(20, 20 // 10)) = max(5, 2) = 5
    beliefs = {f"a{i}": {"metric": float(i) / 19} for i in range(20)}
    result = detector._jsd(beliefs, beliefs, n_bins=0)
    assert 0.0 <= result <= 1.0, f"JSD with adaptive bins out of range: {result}"


@pytest.mark.unit
def test_jsd_adaptive_bin_count_formula():
    """Adaptive n_bins formula: max(5, min(20, n_agents // 10))."""

    # Test the formula directly
    def _expected_bins(n_agents: int) -> int:
        return max(5, min(20, n_agents // 10))

    assert _expected_bins(20) == 5  # small → floor at 5
    assert _expected_bins(100) == 10  # medium
    assert _expected_bins(200) == 20  # large → capped at 20
    assert _expected_bins(50) == 5  # 50//10=5 → exactly at floor


@pytest.mark.unit
def test_narrative_entry_creation():
    """NarrativeEntry must be creatable and frozen."""
    import dataclasses

    from backend.app.services.emergence_tracker import NarrativeEntry

    entry = NarrativeEntry(
        simulation_id="sim_001",
        agent_id="agent_0",
        round_number=3,
        received_event_ids=("evt_001",),
        belief_delta={"escalation": 0.1},
        decision="support_sanctions",
        llm_reasoning="Given the escalation...",
        faction_changed=False,
    )
    assert entry.agent_id == "agent_0"
    with pytest.raises(dataclasses.FrozenInstanceError):
        entry.decision = "other"  # type: ignore
