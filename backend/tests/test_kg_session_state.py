"""Unit tests for KGSessionState dataclass.

Tests:
- Field defaults (all collections empty, string empty)
- Mutability (fields can be reassigned)
- No cross-instance contamination (default_factory gives fresh objects)
"""

from __future__ import annotations

import pytest

from backend.app.models.kg_session_state import KGSessionState


class TestKGSessionStateDefaults:
    """Verify that a fresh KGSessionState has correct empty defaults."""

    def test_current_round_events_default_empty(self) -> None:
        state = KGSessionState()
        assert state.current_round_events == []

    def test_event_content_history_default_empty(self) -> None:
        state = KGSessionState()
        assert state.event_content_history == []

    def test_stakeholder_agents_default_empty(self) -> None:
        state = KGSessionState()
        assert state.stakeholder_agents == []

    def test_active_metrics_default_empty(self) -> None:
        state = KGSessionState()
        assert state.active_metrics == {}

    def test_agent_beliefs_default_empty(self) -> None:
        state = KGSessionState()
        assert state.agent_beliefs == {}

    def test_belief_history_default_empty(self) -> None:
        state = KGSessionState()
        assert state.belief_history == []

    def test_interaction_graph_default_empty(self) -> None:
        state = KGSessionState()
        assert state.interaction_graph == {}

    def test_prev_dominant_stance_default_empty(self) -> None:
        state = KGSessionState()
        assert state.prev_dominant_stance == {}

    def test_scenario_description_default_empty_string(self) -> None:
        state = KGSessionState()
        assert state.scenario_description == ""

    def test_relationship_states_default_empty(self) -> None:
        state = KGSessionState()
        assert state.relationship_states == {}

    def test_attachment_styles_default_empty(self) -> None:
        state = KGSessionState()
        assert state.attachment_styles == {}

    def test_emotional_states_default_empty(self) -> None:
        state = KGSessionState()
        assert state.emotional_states == {}


class TestKGSessionStateMutability:
    """Verify that KGSessionState fields are mutable (not frozen)."""

    def test_can_assign_current_round_events(self) -> None:
        state = KGSessionState()
        sentinel = object()
        state.current_round_events = [sentinel]  # type: ignore[list-item]
        assert state.current_round_events[0] is sentinel

    def test_can_assign_event_content_history(self) -> None:
        state = KGSessionState()
        state.event_content_history = ["hello", "world"]
        assert state.event_content_history == ["hello", "world"]

    def test_can_assign_stakeholder_agents(self) -> None:
        state = KGSessionState()
        agent = {"id": "a1", "name": "Alice"}
        state.stakeholder_agents = [agent]
        assert state.stakeholder_agents[0]["id"] == "a1"

    def test_can_assign_active_metrics(self) -> None:
        state = KGSessionState()
        state.active_metrics = {"gdp": 0.7, "unemployment": 0.3}
        assert state.active_metrics["gdp"] == pytest.approx(0.7)

    def test_can_assign_agent_beliefs(self) -> None:
        state = KGSessionState()
        state.agent_beliefs = {"agent_1": {"metric_a": 0.5}}
        assert state.agent_beliefs["agent_1"]["metric_a"] == pytest.approx(0.5)

    def test_can_assign_belief_history(self) -> None:
        state = KGSessionState()
        snapshot = {"agent_1": {"metric_a": 0.5}}
        state.belief_history = [snapshot]
        assert state.belief_history[0] is snapshot

    def test_can_assign_interaction_graph(self) -> None:
        state = KGSessionState()
        state.interaction_graph = {"a1": ["a2", "a3"]}
        assert state.interaction_graph["a1"] == ["a2", "a3"]

    def test_can_assign_prev_dominant_stance(self) -> None:
        state = KGSessionState()
        state.prev_dominant_stance = {"support": 0.6}
        assert state.prev_dominant_stance["support"] == pytest.approx(0.6)

    def test_can_assign_scenario_description(self) -> None:
        state = KGSessionState()
        state.scenario_description = "Test scenario"
        assert state.scenario_description == "Test scenario"

    def test_can_assign_relationship_states(self) -> None:
        state = KGSessionState()
        state.relationship_states = {("a", "b"): "fake_state"}
        assert state.relationship_states[("a", "b")] == "fake_state"

    def test_can_assign_attachment_styles(self) -> None:
        state = KGSessionState()
        state.attachment_styles = {"agent_1": "fake_attachment"}
        assert state.attachment_styles["agent_1"] == "fake_attachment"

    def test_can_assign_emotional_states(self) -> None:
        state = KGSessionState()
        state.emotional_states = {"agent_1": "fake_emotion"}
        assert state.emotional_states["agent_1"] == "fake_emotion"

    def test_in_place_dict_mutation(self) -> None:
        """Verify in-place mutation of dict fields works (mutable container)."""
        state = KGSessionState()
        state.active_metrics["gdp"] = 0.9
        assert state.active_metrics["gdp"] == pytest.approx(0.9)

    def test_in_place_list_append(self) -> None:
        """Verify in-place append to list fields works (mutable container)."""
        state = KGSessionState()
        state.stakeholder_agents.append({"id": "x"})
        assert len(state.stakeholder_agents) == 1


class TestKGSessionStateIsolation:
    """Verify default_factory prevents cross-instance contamination."""

    def test_active_metrics_not_shared(self) -> None:
        s1 = KGSessionState()
        s2 = KGSessionState()
        s1.active_metrics["key"] = 1.0
        assert "key" not in s2.active_metrics

    def test_stakeholder_agents_not_shared(self) -> None:
        s1 = KGSessionState()
        s2 = KGSessionState()
        s1.stakeholder_agents.append({"id": "a"})
        assert s2.stakeholder_agents == []

    def test_relationship_states_not_shared(self) -> None:
        s1 = KGSessionState()
        s2 = KGSessionState()
        s1.relationship_states[("a", "b")] = "state"
        assert ("a", "b") not in s2.relationship_states

    def test_belief_history_not_shared(self) -> None:
        s1 = KGSessionState()
        s2 = KGSessionState()
        s1.belief_history.append({"snap": 1})
        assert s2.belief_history == []
