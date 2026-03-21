"""Unit tests for SwarmEnsemble probability cloud pipeline."""
from __future__ import annotations

import pytest

from backend.app.services.swarm_ensemble import (
    ProbabilityCloud,
    SwarmEnsemble,
    TrajectoryOutcome,
    _wilson_ci,
    _DEFAULT_REPLICAS,
    _MAX_REPLICAS,
)


# ---------------------------------------------------------------------------
# TrajectoryOutcome classification
# ---------------------------------------------------------------------------

class TestTrajectoryClassification:
    """Verify outcome classification from emergence patterns."""

    def _make_outcome(
        self,
        polar: float = 0.1,
        dominant: float = 0.3,
        tipping_rounds: tuple[int, ...] = (),
        factions: int = 3,
    ) -> TrajectoryOutcome:
        return TrajectoryOutcome(
            replica_index=0,
            branch_session_id="test",
            faction_count=factions,
            tipping_point_rounds=tipping_rounds,
            dominant_faction_size_ratio=dominant,
            final_belief_centroid={"x": 0.5},
            polarization_score=polar,
        )

    def test_disruption_polarized(self):
        o = self._make_outcome(polar=0.4, tipping_rounds=(5, 10))
        label = SwarmEnsemble()._classify_trajectory(o)
        assert label == "disruption_polarized"

    def test_disruption_converged(self):
        o = self._make_outcome(polar=0.1, tipping_rounds=(8,))
        label = SwarmEnsemble()._classify_trajectory(o)
        assert label == "disruption_converged"

    def test_fragmentation(self):
        o = self._make_outcome(polar=0.4, dominant=0.3)
        label = SwarmEnsemble()._classify_trajectory(o)
        assert label == "fragmentation"

    def test_consensus(self):
        o = self._make_outcome(polar=0.1, dominant=0.8)
        label = SwarmEnsemble()._classify_trajectory(o)
        assert label == "consensus"

    def test_stalemate(self):
        o = self._make_outcome(polar=0.15, dominant=0.4)
        label = SwarmEnsemble()._classify_trajectory(o)
        assert label == "stalemate"


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

class TestAggregation:
    """Verify probability cloud aggregation from multiple trajectories."""

    def test_empty_outcomes(self):
        cloud = SwarmEnsemble()._aggregate("sess1", 10, [])
        assert cloud.n_completed == 0
        assert cloud.outcome_distribution == {}

    def test_basic_aggregation(self):
        outcomes = [
            TrajectoryOutcome(
                replica_index=i,
                branch_session_id=f"b{i}",
                faction_count=3,
                tipping_point_rounds=(5,) if i % 2 == 0 else (),
                dominant_faction_size_ratio=0.5,
                final_belief_centroid={"economy": 0.3 + i * 0.1},
                polarization_score=0.2,
            )
            for i in range(10)
        ]
        cloud = SwarmEnsemble()._aggregate("sess1", 10, outcomes)

        assert cloud.n_completed == 10
        assert cloud.n_replicas == 10
        assert cloud.tipping_probability == 0.5  # 5 out of 10
        assert cloud.avg_faction_count == 3.0
        assert "economy" in cloud.belief_cloud
        assert len(cloud.outcome_distribution) > 0
        assert sum(cloud.outcome_distribution.values()) == pytest.approx(1.0, abs=0.01)

    def test_belief_cloud_has_percentiles(self):
        outcomes = [
            TrajectoryOutcome(
                replica_index=i,
                branch_session_id=f"b{i}",
                faction_count=2,
                tipping_point_rounds=(),
                dominant_faction_size_ratio=0.7,
                final_belief_centroid={"security": i / 10},
                polarization_score=0.1,
            )
            for i in range(10)
        ]
        cloud = SwarmEnsemble()._aggregate("sess1", 10, outcomes)
        p25, median, p75 = cloud.belief_cloud["security"]
        assert p25 <= median <= p75


# ---------------------------------------------------------------------------
# Wilson CI
# ---------------------------------------------------------------------------

class TestWilsonCI:
    def test_basic_ci(self):
        lo, hi = _wilson_ci(50, 100)
        assert 0.35 < lo < 0.45
        assert 0.55 < hi < 0.65

    def test_zero_total(self):
        assert _wilson_ci(0, 0) == (0.0, 0.0)

    def test_all_successes(self):
        lo, hi = _wilson_ci(100, 100)
        assert lo > 0.9
        assert hi == 1.0

    def test_no_successes(self):
        lo, hi = _wilson_ci(0, 100)
        assert lo == 0.0
        assert hi < 0.1


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_default_replicas(self):
        assert _DEFAULT_REPLICAS == 50

    def test_max_replicas(self):
        assert _MAX_REPLICAS == 500


# ---------------------------------------------------------------------------
# Frozen dataclasses
# ---------------------------------------------------------------------------

class TestFrozenDataclasses:
    def test_trajectory_outcome_frozen(self):
        o = TrajectoryOutcome(
            replica_index=0, branch_session_id="x", faction_count=2,
            tipping_point_rounds=(), dominant_faction_size_ratio=0.5,
            final_belief_centroid={}, polarization_score=0.1,
        )
        import dataclasses
        with pytest.raises(dataclasses.FrozenInstanceError):
            o.faction_count = 5  # type: ignore[misc]

    def test_probability_cloud_frozen(self):
        cloud = ProbabilityCloud(
            parent_session_id="x", n_replicas=10, n_completed=10,
            trajectories=(), avg_faction_count=2.0,
            tipping_probability=0.5, avg_polarization=0.2,
            belief_cloud={}, outcome_distribution={},
            confidence_intervals={},
        )
        import dataclasses
        with pytest.raises(dataclasses.FrozenInstanceError):
            cloud.n_replicas = 20  # type: ignore[misc]
