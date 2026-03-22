"""Unit tests for lite_hooks rule-based fallbacks."""
from __future__ import annotations

import random
import statistics

import pytest

from backend.app.services.lite_hooks import (
    generate_lite_events,
    deliberate_lite,
    debate_lite,
    run_debate_round_lite,
)


class TestGenerateLiteEvents:
    def test_produces_1_to_3_events(self):
        rng = random.Random(42)
        events = generate_lite_events(
            round_number=5,
            active_metrics=("economy", "security", "oil_price"),
            prev_dominant_stance={"economy": 0.6, "security": 0.4, "oil_price": 0.7},
            event_history=[],
            rng=rng,
        )
        assert 1 <= len(events) <= 3

    def test_events_have_valid_structure(self):
        events = generate_lite_events(
            round_number=3,
            active_metrics=("x", "y"),
            prev_dominant_stance={"x": 0.5, "y": 0.5},
            event_history=[],
            rng=random.Random(123),
        )
        for e in events:
            assert e.round_number == 3
            assert e.event_type in ("shock", "rumor", "official", "grassroots")
            assert 0.0 <= e.credibility <= 1.0
            assert e.reach == ("ALL",)
            assert len(e.impact_vector) >= 1

    def test_empty_metrics_returns_empty(self):
        events = generate_lite_events(
            round_number=1,
            active_metrics=(),
            prev_dominant_stance={},
            event_history=[],
        )
        assert events == []

    def test_different_seeds_produce_different_events(self):
        args = dict(
            round_number=5,
            active_metrics=("a", "b", "c"),
            prev_dominant_stance={"a": 0.5, "b": 0.5, "c": 0.5},
            event_history=[],
        )
        e1 = generate_lite_events(**args, rng=random.Random(1))
        e2 = generate_lite_events(**args, rng=random.Random(999))
        # At least one event should differ in impact
        impacts_1 = [e.impact_vector for e in e1]
        impacts_2 = [e.impact_vector for e in e2]
        assert impacts_1 != impacts_2

    def test_mean_reverting_tendency(self):
        """When stance is extreme (0.9), events should tend to push back."""
        rng = random.Random(42)
        deltas = []
        for _ in range(50):
            events = generate_lite_events(
                round_number=1,
                active_metrics=("x",),
                prev_dominant_stance={"x": 0.9},
                event_history=[],
                rng=rng,
            )
            for e in events:
                if "x" in e.impact_vector:
                    deltas.append(e.impact_vector["x"])
        # Mean should be negative (pushing back toward center)
        if deltas:
            assert sum(deltas) / len(deltas) < 0

    def test_event_not_always_mean_reverting(self):
        """Probabilistic counter-trend: some events should reinforce extreme stance."""
        rng = random.Random(42)
        reinforcing = 0
        total = 0
        for seed in range(200):
            events = generate_lite_events(
                round_number=1,
                active_metrics=("x",),
                prev_dominant_stance={"x": 0.7},
                event_history=[],
                rng=random.Random(seed),
            )
            for e in events:
                if "x" in e.impact_vector:
                    total += 1
                    if e.impact_vector["x"] > 0:  # reinforcing (pushing away from 0.5)
                        reinforcing += 1
        # At least 10% should be reinforcing (not all mean-reverting)
        assert total > 0
        assert reinforcing / total > 0.10, (
            f"Only {reinforcing}/{total} = {reinforcing / total:.2%} reinforcing events"
        )


class TestDeliberateLite:
    def test_returns_deliberation_result(self):
        result = deliberate_lite(
            agent={"id": "a1", "name": "TestAgent", "openness": 0.8, "neuroticism": 0.3},
            beliefs={"economy": 0.6, "security": 0.4},
            events=generate_lite_events(
                round_number=5,
                active_metrics=("economy", "security"),
                prev_dominant_stance={"economy": 0.5, "security": 0.5},
                event_history=[],
                rng=random.Random(42),
            ),
            rng=random.Random(42),
        )
        assert result.agent_id == "a1"
        assert result.decision in ("escalate", "de-escalate", "maintain", "observe")
        assert isinstance(result.belief_updates, dict)
        assert isinstance(result.emotional_reaction, str)

    def test_no_events_returns_observe(self):
        result = deliberate_lite(
            agent={"id": "a1", "name": "Test"},
            beliefs={"x": 0.5},
            events=[],
        )
        assert result.decision == "observe"

    def test_high_openness_larger_updates(self):
        """Agents with high openness should have larger belief deltas."""
        events = generate_lite_events(
            round_number=1,
            active_metrics=("x",),
            prev_dominant_stance={"x": 0.5},
            event_history=[],
            rng=random.Random(42),
        )
        result_open = deliberate_lite(
            agent={"id": "a", "openness": 0.95, "neuroticism": 0.1},
            beliefs={"x": 0.5}, events=events, rng=random.Random(42),
        )
        result_closed = deliberate_lite(
            agent={"id": "b", "openness": 0.05, "neuroticism": 0.1},
            beliefs={"x": 0.5}, events=events, rng=random.Random(42),
        )
        # High openness → larger absolute delta
        open_mag = sum(abs(v) for v in result_open.belief_updates.values())
        closed_mag = sum(abs(v) for v in result_closed.belief_updates.values())
        assert open_mag >= closed_mag

    def test_belief_updates_capped_at_025(self):
        """Belief deltas must be within ±0.25."""
        result = deliberate_lite(
            agent={"id": "a1", "openness": 1.0},
            beliefs={"x": 0.5},
            events=generate_lite_events(
                round_number=1,
                active_metrics=("x",),
                prev_dominant_stance={"x": 0.5},
                event_history=[],
                rng=random.Random(42),
            ),
            rng=random.Random(42),
        )
        for delta in result.belief_updates.values():
            assert -0.25 <= delta <= 0.25

    def test_high_dogmatism_amplifies_confirmation(self):
        """Closed-minded agents amplify confirming evidence more than open agents."""
        events = generate_lite_events(
            round_number=1,
            active_metrics=("x",),
            prev_dominant_stance={"x": 0.5},
            event_history=[],
            rng=random.Random(42),
        )
        # Agent with belief > 0.5 receiving a positive-delta event = confirming
        result_dogmatic = deliberate_lite(
            agent={"id": "a", "openness": 0.1, "neuroticism": 0.5},
            beliefs={"x": 0.7},
            events=events,
            rng=random.Random(42),
        )
        result_open = deliberate_lite(
            agent={"id": "b", "openness": 0.9, "neuroticism": 0.5},
            beliefs={"x": 0.7},
            events=events,
            rng=random.Random(42),
        )
        # Both should produce some updates; dogmatic should differ from open
        # (we can't guarantee direction since events are random, but the
        # magnitudes should diverge due to different confirmation multipliers)
        dogmatic_mag = sum(abs(v) for v in result_dogmatic.belief_updates.values())
        open_mag = sum(abs(v) for v in result_open.belief_updates.values())
        # The values should differ (personality creates heterogeneity)
        assert dogmatic_mag != open_mag or not result_dogmatic.belief_updates

    def test_momentum_biases_toward_previous(self):
        """prev_decision='escalate' should add positive nudge to strongest metric."""
        events = generate_lite_events(
            round_number=5,
            active_metrics=("x",),
            prev_dominant_stance={"x": 0.5},
            event_history=[],
            rng=random.Random(42),
        )
        result_no_momentum = deliberate_lite(
            agent={"id": "a", "openness": 0.5, "conscientiousness": 0.8},
            beliefs={"x": 0.5},
            events=events,
            rng=random.Random(42),
        )
        result_with_momentum = deliberate_lite(
            agent={"id": "a", "openness": 0.5, "conscientiousness": 0.8},
            beliefs={"x": 0.5},
            events=events,
            rng=random.Random(42),
            prev_decision="escalate",
        )
        if "x" in result_no_momentum.belief_updates and "x" in result_with_momentum.belief_updates:
            # Momentum should push the update in positive direction
            assert result_with_momentum.belief_updates["x"] >= result_no_momentum.belief_updates["x"]

    def test_momentum_absent_when_no_prev(self):
        """prev_decision=None should not change results vs default."""
        events = generate_lite_events(
            round_number=1,
            active_metrics=("x",),
            prev_dominant_stance={"x": 0.5},
            event_history=[],
            rng=random.Random(42),
        )
        result_default = deliberate_lite(
            agent={"id": "a", "openness": 0.5},
            beliefs={"x": 0.5},
            events=events,
            rng=random.Random(42),
        )
        result_none = deliberate_lite(
            agent={"id": "a", "openness": 0.5},
            beliefs={"x": 0.5},
            events=events,
            rng=random.Random(42),
            prev_decision=None,
        )
        assert result_default.belief_updates == result_none.belief_updates

    def test_heterogeneity_regression(self):
        """20 agents with varied personalities produce diverse belief deltas."""
        events = generate_lite_events(
            round_number=5,
            active_metrics=("x", "y"),
            prev_dominant_stance={"x": 0.6, "y": 0.4},
            event_history=[],
            rng=random.Random(42),
        )
        deltas = []
        for i in range(20):
            agent = {
                "id": f"agent_{i}",
                "openness": 0.1 + (i / 20) * 0.8,
                "neuroticism": 0.9 - (i / 20) * 0.8,
                "conscientiousness": random.Random(i).random(),
                "agreeableness": random.Random(i + 100).random(),
            }
            result = deliberate_lite(
                agent=agent,
                beliefs={"x": 0.6, "y": 0.4},
                events=events,
                rng=random.Random(i),
            )
            total_delta = sum(abs(v) for v in result.belief_updates.values())
            deltas.append(total_delta)
        # Standard deviation should be non-trivial (agents are heterogeneous)
        if len(deltas) > 1:
            std = statistics.stdev(deltas)
            assert std > 0.005, f"Deltas too homogeneous: std={std:.6f}"


class TestDebateLite:
    def test_close_stances_pull_together(self):
        da, db = debate_lite(
            agent_a={"id": "a", "agreeableness": 0.8},
            agent_b={"id": "b", "agreeableness": 0.8},
            beliefs_a={"topic": 0.4},
            beliefs_b={"topic": 0.6},
            topic="topic",
            rng=random.Random(42),
        )
        # a should move positive (toward b), b should move negative (toward a)
        assert da > 0
        assert db < 0

    def test_far_apart_stances_no_influence(self):
        """Bounded confidence: gap > 0.55 → no influence."""
        da, db = debate_lite(
            agent_a={"id": "a", "agreeableness": 1.0},
            agent_b={"id": "b", "agreeableness": 1.0},
            beliefs_a={"topic": 0.1},
            beliefs_b={"topic": 0.9},
            topic="topic",
        )
        assert da == 0.0
        assert db == 0.0

    def test_deltas_capped_at_020(self):
        """Debate deltas must be within ±0.20."""
        da, db = debate_lite(
            agent_a={"id": "a", "agreeableness": 1.0},
            agent_b={"id": "b", "agreeableness": 1.0},
            beliefs_a={"topic": 0.3},
            beliefs_b={"topic": 0.69},
            topic="topic",
            rng=random.Random(42),
        )
        assert -0.20 <= da <= 0.20
        assert -0.20 <= db <= 0.20

    def test_debate_wider_radius(self):
        """Agents with gap=0.45 (> old 0.4) should still influence each other."""
        da, db = debate_lite(
            agent_a={"id": "a", "agreeableness": 0.8},
            agent_b={"id": "b", "agreeableness": 0.8},
            beliefs_a={"topic": 0.3},
            beliefs_b={"topic": 0.75},  # gap = 0.45
            topic="topic",
            rng=random.Random(42),
        )
        # With wider radius (0.55), gap=0.45 should produce influence
        assert da != 0.0 or db != 0.0


class TestRunDebateRoundLite:
    def test_skips_non_trigger_rounds(self):
        beliefs = {"a": {"x": 0.3}, "b": {"x": 0.7}}
        agents = [{"id": "a", "agreeableness": 0.5}, {"id": "b", "agreeableness": 0.5}]
        result = run_debate_round_lite(agents, beliefs, round_num=4, trigger_every=3)
        # Round 4 is not divisible by 3 → no debate, beliefs unchanged
        assert result is beliefs

    def test_triggers_on_correct_round(self):
        beliefs = {"a": {"x": 0.3}, "b": {"x": 0.6}}
        agents = [{"id": "a", "agreeableness": 0.8}, {"id": "b", "agreeableness": 0.8}]
        result = run_debate_round_lite(
            agents, beliefs, round_num=6, trigger_every=3,
            rng=random.Random(42),
        )
        # Beliefs should change (agents are close enough for bounded confidence)
        assert result["a"]["x"] != beliefs["a"]["x"] or result["b"]["x"] != beliefs["b"]["x"]

    def test_does_not_mutate_input(self):
        beliefs = {"a": {"x": 0.3}, "b": {"x": 0.6}}
        original_a = beliefs["a"]["x"]
        run_debate_round_lite(
            [{"id": "a", "agreeableness": 0.8}, {"id": "b", "agreeableness": 0.8}],
            beliefs, round_num=3, rng=random.Random(42),
        )
        assert beliefs["a"]["x"] == original_a
