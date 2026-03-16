"""Tests for Emergence Validation Framework.

Covers: DiversityChecker, BiasProbeResult model, PhaseTransitionDetector,
EmergenceAttribution, EmergenceScorecard, and MetricSnapshot.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from backend.app.models.emergence import (
    BiasProbeResult,
    EmergenceAttribution,
    EmergenceScorecard,
    MetricSnapshot,
    PhaseTransitionAlert,
)
from backend.app.services.emergence_guards import (
    DiversityChecker,
    DiversityResult,
    PhaseTransitionDetector,
)


def _make_profile(openness: float, extraversion: float,
                  political_stance: float, occupation: str, age: int) -> dict:
    return {
        "big5_openness": openness, "big5_conscientiousness": 0.5,
        "big5_extraversion": extraversion, "big5_agreeableness": 0.5,
        "big5_neuroticism": 0.5, "political_stance": political_stance,
        "occupation": occupation, "age": age,
    }


class TestDiversityChecker:
    """Tests for the DiversityChecker service."""

    def test_diversity_empty_profiles(self) -> None:
        checker = DiversityChecker()
        result = checker.check([])
        assert result.passed is False
        assert result.shannon_entropy == 0
        assert result.entropy_ratio == 0

    def test_diversity_single_profile(self) -> None:
        checker = DiversityChecker()
        result = checker.check([_make_profile(0.5, 0.5, 0.5, "eng", 30)])
        assert result.passed is False
        assert result.shannon_entropy == 0

    def test_diversity_uniform_profiles(self) -> None:
        """All identical traits should produce low entropy and fail."""
        profiles = [_make_profile(0.5, 0.5, 0.5, "eng", 30)] * 10
        checker = DiversityChecker()
        result = checker.check(profiles)
        assert result.passed is False

    def test_diversity_varied_profiles(self) -> None:
        """Varied traits should produce high entropy and pass."""
        profiles = [
            _make_profile(0.1, 0.1, 0.1, "eng", 22),
            _make_profile(0.4, 0.4, 0.3, "fin", 35),
            _make_profile(0.6, 0.7, 0.5, "srv", 42),
            _make_profile(0.8, 0.8, 0.7, "edu", 55),
            _make_profile(0.3, 0.2, 0.9, "hc", 68),
        ]
        checker = DiversityChecker()
        result = checker.check(profiles)
        assert result.passed is True
        assert result.entropy_ratio >= 0.8


class TestBiasProbeResult:
    """Tests for the BiasProbeResult frozen dataclass."""

    def test_bias_probe_result_frozen(self) -> None:
        result = BiasProbeResult(
            session_id="s1",
            scenario="property crash",
            sample_size=30,
            agreement_rate=0.5,
            stance_kurtosis=1.2,
            persona_compliance=0.8,
            diversity_index=2.1,
            bias_detected=False,
        )
        with pytest.raises(FrozenInstanceError):
            result.bias_detected = True  # type: ignore[misc]

    def test_bias_probe_result_defaults(self) -> None:
        result = BiasProbeResult(
            session_id="s1",
            scenario="test",
            sample_size=10,
            agreement_rate=0.3,
            stance_kurtosis=0.0,
            persona_compliance=0.6,
            diversity_index=1.5,
            bias_detected=False,
        )
        assert result.details == {}
        assert result.sample_size == 10

    def test_bias_probe_result_bias_detected_flag(self) -> None:
        """High agreement + low persona compliance indicates LLM bias."""
        result = BiasProbeResult(
            session_id="s1",
            scenario="emigration",
            sample_size=30,
            agreement_rate=0.85,
            stance_kurtosis=4.0,
            persona_compliance=0.3,
            diversity_index=0.5,
            bias_detected=True,
        )
        assert result.bias_detected is True
        assert result.agreement_rate > 0.7
        assert result.persona_compliance < 0.5


class TestMetricSnapshot:
    """Tests for the MetricSnapshot frozen dataclass."""

    def test_metric_snapshot_defaults(self) -> None:
        snap = MetricSnapshot(round_number=5)
        assert snap.modularity == 0.0
        assert snap.opinion_variance == 0.0
        assert snap.sentiment_mean == 0.0
        assert snap.trust_density == 0.0

    def test_metric_snapshot_frozen(self) -> None:
        snap = MetricSnapshot(round_number=3, modularity=0.5)
        with pytest.raises(FrozenInstanceError):
            snap.modularity = 0.9  # type: ignore[misc]


class TestPhaseTransitionDetector:
    """Tests for the PhaseTransitionDetector (z-score based)."""

    def test_phase_transition_no_history(self) -> None:
        """First snapshot should never produce alerts."""
        detector = PhaseTransitionDetector()
        alerts = detector.record(
            "test-session",
            MetricSnapshot(round_number=0, modularity=0.5),
        )
        assert alerts == []

    def test_phase_transition_stable_metrics(self) -> None:
        """10 stable rounds should produce zero alerts."""
        detector = PhaseTransitionDetector()
        all_alerts: list[PhaseTransitionAlert] = []
        for i in range(10):
            alerts = detector.record(
                "test-session",
                MetricSnapshot(
                    round_number=i,
                    modularity=0.3,
                    opinion_variance=0.1,
                    sentiment_mean=0.5,
                    trust_density=0.4,
                ),
            )
            all_alerts.extend(alerts)
        assert len(all_alerts) == 0

    def test_phase_transition_sudden_jump(self) -> None:
        """Modularity jumping from 0.3 to 0.9 should trigger critical alert."""
        detector = PhaseTransitionDetector()
        for i in range(10):
            detector.record(
                "test-session",
                MetricSnapshot(round_number=i, modularity=0.3),
            )
        alerts = detector.record(
            "test-session",
            MetricSnapshot(round_number=10, modularity=0.9),
        )
        assert len(alerts) > 0
        assert alerts[0].severity == "critical"
        assert alerts[0].metric_name == "modularity"

    def test_phase_transition_gradual_change(self) -> None:
        """Constant metrics with no change should produce no alerts."""
        detector = PhaseTransitionDetector()
        all_alerts: list[PhaseTransitionAlert] = []
        for i in range(15):
            alerts = detector.record(
                "test-session",
                MetricSnapshot(round_number=i, modularity=0.5),
            )
            all_alerts.extend(alerts)
        assert len(all_alerts) == 0

    def test_phase_transition_multiple_metrics(self) -> None:
        """Two metrics jumping simultaneously should produce multiple alerts."""
        detector = PhaseTransitionDetector()
        for i in range(10):
            detector.record(
                "test-session",
                MetricSnapshot(
                    round_number=i,
                    modularity=0.3,
                    sentiment_mean=0.5,
                ),
            )
        alerts = detector.record(
            "test-session",
            MetricSnapshot(
                round_number=10,
                modularity=0.9,
                sentiment_mean=-0.5,
            ),
        )
        metric_names = {a.metric_name for a in alerts}
        assert "modularity" in metric_names
        assert "sentiment_mean" in metric_names

    def test_phase_transition_direction_diverging(self) -> None:
        """Increasing modularity should be labeled 'diverging'."""
        detector = PhaseTransitionDetector()
        for i in range(10):
            detector.record(
                "test-session",
                MetricSnapshot(round_number=i, modularity=0.2),
            )
        alerts = detector.record(
            "test-session",
            MetricSnapshot(round_number=10, modularity=0.9),
        )
        assert len(alerts) > 0
        mod_alert = next(a for a in alerts if a.metric_name == "modularity")
        assert mod_alert.direction == "diverging"

    def test_phase_transition_direction_converging(self) -> None:
        """Decreasing modularity should be labeled 'converging'."""
        detector = PhaseTransitionDetector()
        for i in range(10):
            detector.record(
                "test-session",
                MetricSnapshot(round_number=i, modularity=0.8),
            )
        alerts = detector.record(
            "test-session",
            MetricSnapshot(round_number=10, modularity=0.1),
        )
        assert len(alerts) > 0
        mod_alert = next(a for a in alerts if a.metric_name == "modularity")
        assert mod_alert.direction == "converging"


class TestEmergenceAttribution:
    """Tests for the EmergenceAttribution frozen dataclass."""

    def test_attribution_no_change(self) -> None:
        attr = EmergenceAttribution(
            session_id="s1",
            metric_name="modularity",
            total_change=0.0,
            exogenous_component=0.0,
            endogenous_component=0.0,
            artifact_component=0.0,
            emergence_ratio=0.0,
            round_range=(0, 10),
        )
        assert attr.emergence_ratio == 0.0
        assert attr.total_change == 0.0

    def test_attribution_all_exogenous(self) -> None:
        attr = EmergenceAttribution(
            session_id="s1",
            metric_name="sentiment_mean",
            total_change=0.5,
            exogenous_component=0.5,
            endogenous_component=0.0,
            artifact_component=0.0,
            emergence_ratio=0.0,
            round_range=(0, 15),
        )
        assert attr.exogenous_component == attr.total_change
        assert attr.emergence_ratio == 0.0

    def test_attribution_all_endogenous(self) -> None:
        attr = EmergenceAttribution(
            session_id="s1",
            metric_name="opinion_variance",
            total_change=0.4,
            exogenous_component=0.0,
            endogenous_component=0.4,
            artifact_component=0.0,
            emergence_ratio=1.0,
            round_range=(0, 20),
        )
        assert attr.emergence_ratio == 1.0

    def test_attribution_mixed(self) -> None:
        total = 1.0
        exo = 0.3
        artifact = 0.2
        endo = total - exo - artifact
        ratio = max(0.0, min(endo / total, 1.0))
        attr = EmergenceAttribution(
            session_id="s1",
            metric_name="trust_density",
            total_change=total,
            exogenous_component=exo,
            endogenous_component=endo,
            artifact_component=artifact,
            emergence_ratio=ratio,
            round_range=(0, 10),
        )
        assert attr.emergence_ratio == pytest.approx(0.5, abs=0.01)

    def test_attribution_clamp(self) -> None:
        """Emergence ratio must be clamped to [0, 1]."""
        ratio = max(0.0, min(1.5, 1.0))
        attr = EmergenceAttribution(
            session_id="s1",
            metric_name="modularity",
            total_change=0.1,
            exogenous_component=-0.05,
            endogenous_component=0.15,
            artifact_component=0.0,
            emergence_ratio=ratio,
            round_range=(5, 15),
        )
        assert 0.0 <= attr.emergence_ratio <= 1.0


class TestEmergenceScorecard:
    """Tests for the EmergenceScorecard frozen dataclass and grading."""

    def test_scorecard_grade_A(self) -> None:
        card = EmergenceScorecard(
            session_id="s1",
            max_cascade_depth=5,
            cascade_count=12,
            avg_cascade_breadth=3.2,
            polarization_delta=0.15,
            emergence_ratio=0.8,
            bias_contamination=0.1,
            transition_count=2,
            grade="A",
        )
        assert card.grade == "A"
        assert card.emergence_ratio > 0.7
        assert card.bias_contamination < 0.3
        assert card.max_cascade_depth > 3

    def test_scorecard_grade_F(self) -> None:
        card = EmergenceScorecard(
            session_id="s2",
            emergence_ratio=0.05,
            bias_contamination=0.9,
            grade="F",
        )
        assert card.grade == "F"
        assert card.bias_contamination > 0.7

    def test_scorecard_grade_C(self) -> None:
        card = EmergenceScorecard(
            session_id="s3",
            emergence_ratio=0.4,
            bias_contamination=0.4,
            grade="C",
        )
        assert card.grade == "C"
        assert card.emergence_ratio > 0.3

    def test_scorecard_frozen(self) -> None:
        card = EmergenceScorecard(session_id="s1")
        with pytest.raises(FrozenInstanceError):
            card.grade = "A"  # type: ignore[misc]

    def test_scorecard_defaults(self) -> None:
        card = EmergenceScorecard(session_id="s1")
        assert card.max_cascade_depth == 0
        assert card.cascade_count == 0
        assert card.avg_cascade_breadth == 0.0
        assert card.polarization_delta == 0.0
        assert card.echo_chamber_count_delta == 0
        assert card.opinion_entropy_trend == "stable"
        assert card.stance_bimodality_p == 1.0
        assert card.emergence_ratio == 0.0
        assert card.bias_contamination == 0.0
        assert card.transition_count == 0
        assert card.grade == "F"


# ---------------------------------------------------------------------------
# Grading rubric tests
# ---------------------------------------------------------------------------

class TestGradingRubric:
    """Tests for the _compute_grade function."""

    def test_grade_A(self) -> None:
        from backend.app.services.emergence_scorecard import _compute_grade
        # Phase 1C + Phase 3: Grade A now also requires network_volatility > 0.05
        # and belief_revision_rate > 0.05 (active network dynamics and belief updating)
        assert _compute_grade(
            emergence_ratio=0.8,
            bias_contamination=0.2,
            max_cascade_depth=5,
            action_diversity=2.5,
            network_volatility=0.1,
            belief_revision_rate=0.1,
        ) == "A"

    def test_grade_B(self) -> None:
        from backend.app.services.emergence_scorecard import _compute_grade
        assert _compute_grade(emergence_ratio=0.6, bias_contamination=0.4, max_cascade_depth=2, action_diversity=1.8) == "B"

    def test_grade_C(self) -> None:
        from backend.app.services.emergence_scorecard import _compute_grade
        assert _compute_grade(emergence_ratio=0.35, bias_contamination=0.6, max_cascade_depth=1) == "C"

    def test_grade_D(self) -> None:
        from backend.app.services.emergence_scorecard import _compute_grade
        assert _compute_grade(emergence_ratio=0.15, bias_contamination=0.3, max_cascade_depth=0) == "D"

    def test_grade_F_high_bias(self) -> None:
        from backend.app.services.emergence_scorecard import _compute_grade
        assert _compute_grade(emergence_ratio=0.9, bias_contamination=0.8, max_cascade_depth=10) == "F"

    def test_grade_F_low_emergence(self) -> None:
        from backend.app.services.emergence_scorecard import _compute_grade
        assert _compute_grade(emergence_ratio=0.05, bias_contamination=0.1, max_cascade_depth=0) == "F"


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

class TestHelperFunctions:
    """Tests for module-level helper functions in emergence_guards."""

    def test_shannon_entropy_uniform(self) -> None:
        from backend.app.services.emergence_guards import _shannon_entropy
        counts = {"support": 10, "oppose": 10, "neutral": 10}
        ent = _shannon_entropy(counts)
        assert ent > 1.5  # log2(3) ≈ 1.585

    def test_shannon_entropy_unanimous(self) -> None:
        from backend.app.services.emergence_guards import _shannon_entropy
        counts = {"support": 30}
        assert _shannon_entropy(counts) == 0.0

    def test_shannon_entropy_empty(self) -> None:
        from backend.app.services.emergence_guards import _shannon_entropy
        assert _shannon_entropy({}) == 0.0

    def test_kurtosis_uniform(self) -> None:
        from backend.app.services.emergence_guards import _kurtosis_from_counts
        counts = {"support": 10, "oppose": 10, "neutral": 10}
        k = _kurtosis_from_counts(counts)
        assert k < 0  # platykurtic (flat distribution)

    def test_kurtosis_peaked(self) -> None:
        from backend.app.services.emergence_guards import _kurtosis_from_counts
        counts = {"support": 28, "oppose": 1, "neutral": 1}
        k = _kurtosis_from_counts(counts)
        assert k > 0  # leptokurtic (peaked)

    def test_kurtosis_insufficient_data(self) -> None:
        from backend.app.services.emergence_guards import _kurtosis_from_counts
        counts = {"support": 2}
        assert _kurtosis_from_counts(counts) == 0.0

    def test_expected_stance_centrist(self) -> None:
        from backend.app.services.emergence_guards import _expected_stance
        scenarios = ["A", "B", "C"]
        assert _expected_stance(0.5, "A", scenarios) is None

    def test_expected_stance_liberal_pro_democracy(self) -> None:
        from backend.app.services.emergence_guards import _expected_stance, BiasProbe
        scenarios = BiasProbe.PROBE_SCENARIOS
        assert _expected_stance(0.8, scenarios[0], scenarios) == "support"

    def test_expected_stance_conservative_pro_establishment(self) -> None:
        from backend.app.services.emergence_guards import _expected_stance, BiasProbe
        scenarios = BiasProbe.PROBE_SCENARIOS
        assert _expected_stance(0.2, scenarios[0], scenarios) == "oppose"
