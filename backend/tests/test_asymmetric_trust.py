"""Unit tests for RelationshipState asymmetric trust/deception (Phase 2.2).

Covers:
- New field defaults (trust_b_perspective, deception_a_to_b, deception_b_to_a)
- Computed properties: trust_asymmetry, net_deception
- RelationshipEngine.update_asymmetric_trust() — perspective "a" and "b"
- Clamping behaviour on out-of-range deltas
- Immutability (dataclasses.replace pattern)
"""

from __future__ import annotations

import pytest

from backend.app.models.relationship_state import RelationshipState
from backend.app.services.relationship_engine import RelationshipEngine


class TestRelationshipStateDefaults:
    def test_trust_b_perspective_defaults_zero(self):
        state = RelationshipState(agent_a_id="a", agent_b_id="b")
        assert state.trust_b_perspective == pytest.approx(0.0)

    def test_deception_a_to_b_defaults_zero(self):
        state = RelationshipState(agent_a_id="a", agent_b_id="b")
        assert state.deception_a_to_b == pytest.approx(0.0)

    def test_deception_b_to_a_defaults_zero(self):
        state = RelationshipState(agent_a_id="a", agent_b_id="b")
        assert state.deception_b_to_a == pytest.approx(0.0)


class TestTrustAsymmetryProperty:
    def test_symmetric_trust_asymmetry_zero(self):
        state = RelationshipState(agent_a_id="a", agent_b_id="b", trust=0.5, trust_b_perspective=0.5)
        assert state.trust_asymmetry == pytest.approx(0.0)

    def test_positive_asymmetry_a_trusts_more(self):
        state = RelationshipState(agent_a_id="a", agent_b_id="b", trust=0.7, trust_b_perspective=0.3)
        assert state.trust_asymmetry == pytest.approx(0.4)

    def test_negative_asymmetry_b_trusts_more(self):
        state = RelationshipState(agent_a_id="a", agent_b_id="b", trust=0.2, trust_b_perspective=0.6)
        assert state.trust_asymmetry == pytest.approx(-0.4)


class TestNetDeceptionProperty:
    def test_equal_deception_net_zero(self):
        state = RelationshipState(
            agent_a_id="a", agent_b_id="b",
            deception_a_to_b=0.3, deception_b_to_a=0.3,
        )
        assert state.net_deception == pytest.approx(0.0)

    def test_a_more_deceptive_positive(self):
        state = RelationshipState(
            agent_a_id="a", agent_b_id="b",
            deception_a_to_b=0.6, deception_b_to_a=0.2,
        )
        assert state.net_deception == pytest.approx(0.4)

    def test_b_more_deceptive_negative(self):
        state = RelationshipState(
            agent_a_id="a", agent_b_id="b",
            deception_a_to_b=0.1, deception_b_to_a=0.5,
        )
        assert state.net_deception == pytest.approx(-0.4)


class TestUpdateAsymmetricTrust:
    @pytest.fixture()
    def engine(self):
        return RelationshipEngine()

    @pytest.fixture()
    def base_state(self):
        return RelationshipState(
            agent_a_id="alice",
            agent_b_id="bob",
            trust=0.5,
            trust_b_perspective=0.5,
            deception_a_to_b=0.0,
            deception_b_to_a=0.0,
        )

    def test_perspective_a_updates_trust(self, engine, base_state):
        new = engine.update_asymmetric_trust(base_state, perspective="a", trust_delta=0.2)
        assert new.trust == pytest.approx(0.7)
        assert new.trust_b_perspective == pytest.approx(0.5)  # unchanged

    def test_perspective_b_updates_trust_b(self, engine, base_state):
        new = engine.update_asymmetric_trust(base_state, perspective="b", trust_delta=-0.3)
        assert new.trust_b_perspective == pytest.approx(0.2)
        assert new.trust == pytest.approx(0.5)  # unchanged

    def test_perspective_a_updates_deception_a_to_b(self, engine, base_state):
        new = engine.update_asymmetric_trust(base_state, perspective="a", deception_delta=0.4)
        assert new.deception_a_to_b == pytest.approx(0.4)
        assert new.deception_b_to_a == pytest.approx(0.0)  # unchanged

    def test_perspective_b_updates_deception_b_to_a(self, engine, base_state):
        new = engine.update_asymmetric_trust(base_state, perspective="b", deception_delta=0.6)
        assert new.deception_b_to_a == pytest.approx(0.6)
        assert new.deception_a_to_b == pytest.approx(0.0)  # unchanged

    def test_trust_clamped_at_plus_one(self, engine, base_state):
        new = engine.update_asymmetric_trust(base_state, perspective="a", trust_delta=5.0)
        assert new.trust == pytest.approx(1.0)

    def test_trust_clamped_at_minus_one(self, engine, base_state):
        new = engine.update_asymmetric_trust(base_state, perspective="a", trust_delta=-5.0)
        assert new.trust == pytest.approx(-1.0)

    def test_deception_clamped_at_one(self, engine, base_state):
        new = engine.update_asymmetric_trust(base_state, perspective="b", deception_delta=99.0)
        assert new.deception_b_to_a == pytest.approx(1.0)

    def test_deception_clamped_at_zero(self, engine, base_state):
        state = RelationshipState(
            agent_a_id="a", agent_b_id="b",
            deception_a_to_b=0.1,
        )
        new = engine.update_asymmetric_trust(state, perspective="a", deception_delta=-99.0)
        assert new.deception_a_to_b == pytest.approx(0.0)

    def test_returns_new_instance_not_mutated(self, engine, base_state):
        new = engine.update_asymmetric_trust(base_state, perspective="a", trust_delta=0.1)
        assert new is not base_state
        assert base_state.trust == pytest.approx(0.5)  # original unchanged

    def test_values_rounded_to_4dp(self, engine, base_state):
        new = engine.update_asymmetric_trust(base_state, perspective="a", trust_delta=0.12345678)
        # Should be rounded to 4 decimal places
        assert new.trust == round(0.5 + 0.12345678, 4)

    def test_combined_trust_and_deception_update(self, engine, base_state):
        new = engine.update_asymmetric_trust(
            base_state, perspective="b", trust_delta=-0.15, deception_delta=0.2
        )
        assert new.trust_b_perspective == pytest.approx(0.35)
        assert new.deception_b_to_a == pytest.approx(0.2)
