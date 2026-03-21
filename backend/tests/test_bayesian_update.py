"""Tests for true Bayesian belief update (Task 8).

Covers:
- _bayesian_core: Bayes formula on [0,1] probability scale
- _stance_to_prob / _prob_to_stance: domain transforms [-1,+1] <-> (0,1)
- bayesian_update: full pipeline on [-1,+1] stance scale
- compute_likelihood_ratio: LR computation with confirmation bias
"""
from __future__ import annotations

import pytest
from dataclasses import replace

from backend.app.models.emotional_state import Belief
from backend.app.services.belief_system import BeliefSystem


@pytest.mark.unit
class TestBayesianCore:
    def test_confirming_evidence_increases_probability(self):
        bs = BeliefSystem()
        posterior = bs._bayesian_core(0.6, 2.0)  # LR=2 supports hypothesis
        assert posterior > 0.6
        expected = (0.6 * 2.0) / (0.6 * 2.0 + 0.4)
        assert abs(posterior - expected) < 0.001

    def test_contradicting_evidence_decreases_probability(self):
        bs = BeliefSystem()
        posterior = bs._bayesian_core(0.6, 0.5)  # LR=0.5 contradicts
        assert posterior < 0.6

    def test_neutral_evidence_no_change(self):
        bs = BeliefSystem()
        posterior = bs._bayesian_core(0.6, 1.0)  # LR=1 = no evidence
        assert abs(posterior - 0.6) < 0.001

    def test_clamp_prevents_certainty(self):
        bs = BeliefSystem()
        posterior = bs._bayesian_core(0.99, 100.0)
        assert posterior <= 0.98

    def test_clamp_prevents_zero(self):
        bs = BeliefSystem()
        posterior = bs._bayesian_core(0.01, 0.01)
        assert posterior >= 0.02

    def test_zero_lr_returns_prior(self):
        bs = BeliefSystem()
        posterior = bs._bayesian_core(0.6, 0.0)
        assert posterior == 0.6

    def test_negative_lr_returns_prior(self):
        bs = BeliefSystem()
        posterior = bs._bayesian_core(0.6, -1.0)
        assert posterior == 0.6

    def test_very_small_prior_stays_above_floor(self):
        bs = BeliefSystem()
        posterior = bs._bayesian_core(0.001, 0.001)
        assert posterior >= 0.02


@pytest.mark.unit
class TestStanceTransform:
    def test_roundtrip_preserves_value(self):
        bs = BeliefSystem()
        for stance in [-0.9, -0.5, 0.0, 0.5, 0.9]:
            prob = bs._stance_to_prob(stance)
            assert 0.0 < prob < 1.0
            back = bs._prob_to_stance(prob)
            assert abs(back - stance) < 0.01

    def test_neutral_stance_maps_to_half(self):
        bs = BeliefSystem()
        assert abs(bs._stance_to_prob(0.0) - 0.5) < 0.001

    def test_extreme_stance_clamps(self):
        bs = BeliefSystem()
        assert bs._stance_to_prob(1.0) <= 0.98
        assert bs._stance_to_prob(-1.0) >= 0.02

    def test_prob_half_maps_to_zero_stance(self):
        bs = BeliefSystem()
        assert abs(bs._prob_to_stance(0.5) - 0.0) < 0.001

    def test_high_prob_maps_to_positive_stance(self):
        bs = BeliefSystem()
        assert bs._prob_to_stance(0.9) > 0.0

    def test_low_prob_maps_to_negative_stance(self):
        bs = BeliefSystem()
        assert bs._prob_to_stance(0.1) < 0.0


@pytest.mark.unit
class TestBayesianUpdate:
    def test_confirming_evidence_increases_stance(self):
        bs = BeliefSystem()
        belief = Belief(topic="economy", stance=0.3, confidence=0.5, evidence_count=0)
        updated = bs.bayesian_update(belief, evidence_stance=0.8, evidence_weight=0.6, openness=0.5)
        assert updated.stance > belief.stance

    def test_contradicting_evidence_decreases_stance(self):
        bs = BeliefSystem()
        belief = Belief(topic="economy", stance=0.3, confidence=0.5, evidence_count=0)
        updated = bs.bayesian_update(belief, evidence_stance=-0.8, evidence_weight=0.6, openness=0.5)
        assert updated.stance < belief.stance

    def test_zero_weight_no_change(self):
        bs = BeliefSystem()
        belief = Belief(topic="economy", stance=0.3, confidence=0.5, evidence_count=0)
        updated = bs.bayesian_update(belief, evidence_stance=0.8, evidence_weight=0.0, openness=0.5)
        assert updated.stance == belief.stance

    def test_evidence_count_increments(self):
        bs = BeliefSystem()
        belief = Belief(topic="economy", stance=0.3, confidence=0.5, evidence_count=5)
        updated = bs.bayesian_update(belief, evidence_stance=0.5, evidence_weight=0.3, openness=0.5)
        assert updated.evidence_count == 6

    def test_extreme_stance_stays_clamped(self):
        bs = BeliefSystem()
        belief = Belief(topic="economy", stance=0.95, confidence=0.9, evidence_count=10)
        updated = bs.bayesian_update(belief, evidence_stance=1.0, evidence_weight=1.0, openness=0.5)
        assert updated.stance <= 0.98
        assert updated.stance >= -0.98

    def test_confirming_evidence_increases_confidence(self):
        bs = BeliefSystem()
        belief = Belief(topic="economy", stance=0.3, confidence=0.5, evidence_count=0)
        updated = bs.bayesian_update(belief, evidence_stance=0.5, evidence_weight=0.5, openness=0.5)
        assert updated.confidence > belief.confidence

    def test_contradicting_evidence_decreases_confidence(self):
        bs = BeliefSystem()
        belief = Belief(topic="economy", stance=0.5, confidence=0.6, evidence_count=0)
        updated = bs.bayesian_update(belief, evidence_stance=-0.8, evidence_weight=0.6, openness=0.5)
        assert updated.confidence < belief.confidence

    def test_confidence_never_below_floor(self):
        bs = BeliefSystem()
        belief = Belief(topic="economy", stance=0.5, confidence=0.15, evidence_count=0)
        for _ in range(50):
            belief = bs.bayesian_update(belief, evidence_stance=-1.0, evidence_weight=1.0, openness=0.5)
        assert belief.confidence >= bs._CONFIDENCE_FLOOR

    def test_confidence_never_above_one(self):
        bs = BeliefSystem()
        belief = Belief(topic="economy", stance=0.0, confidence=0.95, evidence_count=0)
        for _ in range(20):
            belief = bs.bayesian_update(belief, evidence_stance=1.0, evidence_weight=1.0, openness=0.5)
        assert belief.confidence <= 1.0

    def test_negative_stance_confirming_negative_evidence(self):
        """Negative belief + negative evidence = confirming (stance should decrease further)."""
        bs = BeliefSystem()
        belief = Belief(topic="economy", stance=-0.3, confidence=0.5, evidence_count=0)
        updated = bs.bayesian_update(belief, evidence_stance=-0.8, evidence_weight=0.6, openness=0.5)
        assert updated.stance < belief.stance

    def test_immutability(self):
        """Original belief must not be mutated."""
        bs = BeliefSystem()
        belief = Belief(topic="economy", stance=0.3, confidence=0.5, evidence_count=0)
        updated = bs.bayesian_update(belief, evidence_stance=0.8, evidence_weight=0.6, openness=0.5)
        assert belief.stance == 0.3
        assert belief.confidence == 0.5
        assert belief.evidence_count == 0
        assert updated is not belief


@pytest.mark.unit
class TestLikelihoodRatio:
    def test_confirming_evidence_lr_above_1(self):
        bs = BeliefSystem()
        lr = bs.compute_likelihood_ratio(0.5, 0.5, 0.3, 0.5)
        assert lr > 1.0

    def test_contradicting_evidence_lr_smaller_than_confirming(self):
        """Contradicting evidence produces a smaller LR than confirming evidence.

        LR is always >= 1 (evidence strength); direction is handled by the
        caller choosing which probability space to apply the LR in.
        """
        bs = BeliefSystem()
        lr_contradict = bs.compute_likelihood_ratio(-0.5, 0.5, 0.3, 0.5)
        lr_confirm = bs.compute_likelihood_ratio(0.5, 0.5, 0.3, 0.5)
        assert lr_contradict >= 1.0
        assert lr_contradict < lr_confirm

    def test_zero_weight_lr_is_1(self):
        bs = BeliefSystem()
        lr = bs.compute_likelihood_ratio(0.5, 0.0, 0.3, 0.5)
        assert lr == 1.0

    def test_higher_bias_stronger_confirming(self):
        """Higher confirmation bias should produce larger LR for confirming evidence."""
        bs = BeliefSystem()
        lr_low = bs.compute_likelihood_ratio(0.5, 0.5, 0.3, confirmation_bias=0.1)
        lr_high = bs.compute_likelihood_ratio(0.5, 0.5, 0.3, confirmation_bias=0.9)
        assert lr_high > lr_low

    def test_higher_weight_larger_lr(self):
        """Higher evidence weight should produce a larger base LR."""
        bs = BeliefSystem()
        lr_low = bs.compute_likelihood_ratio(0.5, 0.2, 0.3, 0.5)
        lr_high = bs.compute_likelihood_ratio(0.5, 0.8, 0.3, 0.5)
        assert lr_high > lr_low

    def test_negative_evidence_negative_belief_confirms(self):
        """Negative evidence for negative belief = confirming (LR > 1)."""
        bs = BeliefSystem()
        lr = bs.compute_likelihood_ratio(-0.5, 0.5, -0.3, 0.5)
        assert lr > 1.0


@pytest.mark.unit
class TestUpdateBeliefDelegates:
    """Verify that update_belief delegates to bayesian_update."""

    def test_update_belief_equals_bayesian_update(self):
        bs = BeliefSystem()
        belief = Belief(topic="economy", stance=0.3, confidence=0.5, evidence_count=0)
        via_update = bs.update_belief(belief, 0.5, 0.4, 0.6)
        via_bayesian = bs.bayesian_update(belief, 0.5, 0.4, 0.6)
        assert via_update.stance == via_bayesian.stance
        assert via_update.confidence == via_bayesian.confidence
        assert via_update.evidence_count == via_bayesian.evidence_count


@pytest.mark.unit
class TestLegacyUpdatePreserved:
    """Verify that update_belief_legacy still works and differs from Bayesian."""

    def test_legacy_shifts_stance(self):
        bs = BeliefSystem()
        belief = Belief(topic="economy", stance=0.0, confidence=0.5, evidence_count=0)
        updated = bs.update_belief_legacy(belief, evidence_stance=1.0, evidence_weight=0.5, openness=0.5)
        assert updated.stance > belief.stance

    def test_legacy_increments_evidence_count(self):
        bs = BeliefSystem()
        belief = Belief(topic="economy", stance=0.0, confidence=0.5, evidence_count=3)
        updated = bs.update_belief_legacy(belief, 0.5, 0.3, 0.5)
        assert updated.evidence_count == 4
