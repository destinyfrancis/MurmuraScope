"""Unit tests for RelationshipState, AttachmentStyle, and RelationshipEngine.

TDD: tests written before implementation.
Covers:
- RelationshipState immutability + Rusbult commitment formula
- AttachmentStyle immutability
- RelationshipEngine.initialize_relationship / update_from_interaction
- RelationshipEngine.compute_gottman_score
- RelationshipEngine.batch_update pattern
- infer_attachment_style pure function (Big Five → style)
"""
from __future__ import annotations

import dataclasses
import pytest

from backend.app.models.relationship_state import (
    AttachmentStyle,
    RelationshipState,
)
from backend.app.services.relationship_engine import (
    RelationshipEngine,
    infer_attachment_style,
)


# ---------------------------------------------------------------------------
# RelationshipState
# ---------------------------------------------------------------------------


class TestRelationshipState:
    def test_immutable(self):
        rs = RelationshipState(
            agent_a_id="alice",
            agent_b_id="bob",
        )
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            rs.intimacy = 0.9  # type: ignore[misc]

    def test_default_values_in_range(self):
        rs = RelationshipState(agent_a_id="alice", agent_b_id="bob")
        assert 0.0 <= rs.intimacy <= 1.0
        assert 0.0 <= rs.passion <= 1.0
        assert 0.0 <= rs.commitment <= 1.0
        assert 0.0 <= rs.satisfaction <= 1.0
        assert 0.0 <= rs.alternatives <= 1.0
        assert 0.0 <= rs.investment <= 1.0
        assert -1.0 <= rs.trust <= 1.0

    def test_rusbult_commitment_formula(self):
        """commitment = satisfaction - alternatives + investment (Rusbult Investment Model)."""
        rs = RelationshipState(
            agent_a_id="alice",
            agent_b_id="bob",
            satisfaction=0.8,
            alternatives=0.2,
            investment=0.6,
        )
        expected = 0.8 - 0.2 + 0.6  # = 1.2 → clamp to 1.0
        assert rs.rusbult_commitment == pytest.approx(min(1.0, max(0.0, expected)), abs=1e-6)

    def test_rusbult_commitment_clamped(self):
        rs = RelationshipState(
            agent_a_id="a",
            agent_b_id="b",
            satisfaction=0.1,
            alternatives=0.9,
            investment=0.1,
        )
        assert rs.rusbult_commitment >= 0.0
        assert rs.rusbult_commitment <= 1.0

    def test_replace_returns_new_instance(self):
        rs = RelationshipState(agent_a_id="alice", agent_b_id="bob", intimacy=0.3)
        rs2 = dataclasses.replace(rs, intimacy=0.5)
        assert rs2.intimacy == pytest.approx(0.5)
        assert rs.intimacy == pytest.approx(0.3)  # original unchanged

    def test_directional_asymmetry(self):
        """A→B and B→A are separate, different relationships."""
        ab = RelationshipState(agent_a_id="alice", agent_b_id="bob", intimacy=0.7)
        ba = RelationshipState(agent_a_id="bob", agent_b_id="alice", intimacy=0.3)
        assert ab.intimacy != ba.intimacy


# ---------------------------------------------------------------------------
# AttachmentStyle
# ---------------------------------------------------------------------------


class TestAttachmentStyle:
    def test_immutable(self):
        att = AttachmentStyle(agent_id="alice")
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            att.anxiety = 0.9  # type: ignore[misc]

    def test_valid_styles(self):
        for style in ("secure", "anxious", "avoidant", "disorganized"):
            att = AttachmentStyle(agent_id="x", style=style)
            assert att.style == style

    def test_default_style_is_secure(self):
        att = AttachmentStyle(agent_id="x")
        assert att.style == "secure"

    def test_anxiety_avoidance_in_range(self):
        att = AttachmentStyle(agent_id="x", anxiety=0.7, avoidance=0.3)
        assert 0.0 <= att.anxiety <= 1.0
        assert 0.0 <= att.avoidance <= 1.0


# ---------------------------------------------------------------------------
# infer_attachment_style (pure function)
# ---------------------------------------------------------------------------


class TestInferAttachmentStyle:
    def test_high_neuroticism_high_agreeableness_gives_anxious(self):
        result = infer_attachment_style(
            agent_id="test",
            neuroticism=0.85,
            agreeableness=0.80,
            openness=0.5,
        )
        assert result.style == "anxious"

    def test_low_agreeableness_low_openness_gives_avoidant(self):
        result = infer_attachment_style(
            agent_id="test",
            neuroticism=0.3,
            agreeableness=0.15,
            openness=0.15,
        )
        assert result.style == "avoidant"

    def test_balanced_gives_secure(self):
        result = infer_attachment_style(
            agent_id="test",
            neuroticism=0.4,
            agreeableness=0.6,
            openness=0.5,
        )
        assert result.style == "secure"

    def test_high_neuroticism_low_agreeableness_gives_disorganized(self):
        result = infer_attachment_style(
            agent_id="test",
            neuroticism=0.85,
            agreeableness=0.15,
            openness=0.3,
        )
        assert result.style == "disorganized"

    def test_returns_attachment_style_instance(self):
        result = infer_attachment_style(
            agent_id="alice",
            neuroticism=0.5,
            agreeableness=0.5,
            openness=0.5,
        )
        assert isinstance(result, AttachmentStyle)
        assert result.agent_id == "alice"

    def test_anxiety_reflects_neuroticism(self):
        low = infer_attachment_style("x", neuroticism=0.1, agreeableness=0.5, openness=0.5)
        high = infer_attachment_style("x", neuroticism=0.9, agreeableness=0.5, openness=0.5)
        assert high.anxiety > low.anxiety

    def test_avoidance_reflects_low_agreeableness(self):
        high_agree = infer_attachment_style("x", neuroticism=0.5, agreeableness=0.9, openness=0.5)
        low_agree = infer_attachment_style("x", neuroticism=0.5, agreeableness=0.1, openness=0.5)
        assert low_agree.avoidance > high_agree.avoidance


# ---------------------------------------------------------------------------
# RelationshipEngine
# ---------------------------------------------------------------------------


class TestRelationshipEngine:
    def setup_method(self):
        self.engine = RelationshipEngine()

    def test_initialize_relationship_defaults(self):
        rs = self.engine.initialize_relationship("alice", "bob")
        assert isinstance(rs, RelationshipState)
        assert rs.agent_a_id == "alice"
        assert rs.agent_b_id == "bob"

    def test_initialize_from_description_romantic(self):
        rs = self.engine.initialize_relationship(
            "alice", "bob", edge_description="romantic partner"
        )
        assert rs.intimacy > 0.0  # romantic → elevated intimacy
        assert rs.passion > 0.0

    def test_initialize_from_description_enemy(self):
        rs = self.engine.initialize_relationship(
            "alice", "bob", edge_description="bitter enemy"
        )
        assert rs.trust < 0.0  # enemy → negative trust

    def test_update_from_interaction_returns_new_state(self):
        rs = self.engine.initialize_relationship("alice", "bob")
        updated = self.engine.update_from_interaction(
            state=rs,
            interaction_valence=0.5,  # positive interaction
            profile_a={"agreeableness": 0.7, "neuroticism": 0.3},
            attachment_style_a=None,
        )
        assert updated is not rs
        assert isinstance(updated, RelationshipState)

    def test_positive_interaction_increases_intimacy(self):
        rs = RelationshipState(agent_a_id="alice", agent_b_id="bob", intimacy=0.3)
        updated = self.engine.update_from_interaction(
            state=rs,
            interaction_valence=1.0,
            profile_a={"agreeableness": 0.7, "neuroticism": 0.3},
            attachment_style_a=None,
        )
        assert updated.intimacy >= rs.intimacy

    def test_negative_interaction_decreases_trust(self):
        rs = RelationshipState(agent_a_id="alice", agent_b_id="bob", trust=0.5)
        updated = self.engine.update_from_interaction(
            state=rs,
            interaction_valence=-1.0,
            profile_a={"agreeableness": 0.5, "neuroticism": 0.5},
            attachment_style_a=None,
        )
        assert updated.trust <= rs.trust

    def test_passion_decays_faster_than_intimacy(self):
        """Passion decays at 0.93/round, intimacy at 0.97/round — no interaction."""
        rs = RelationshipState(
            agent_a_id="alice", agent_b_id="bob",
            intimacy=0.8, passion=0.8,
        )
        updated = self.engine.update_from_interaction(
            state=rs,
            interaction_valence=0.0,  # neutral
            profile_a={"agreeableness": 0.5, "neuroticism": 0.5},
            attachment_style_a=None,
        )
        intimacy_decay = rs.intimacy - updated.intimacy
        passion_decay = rs.passion - updated.passion
        assert passion_decay >= intimacy_decay

    def test_investment_accumulates_over_time(self):
        rs = RelationshipState(agent_a_id="alice", agent_b_id="bob", investment=0.2)
        updated = self.engine.update_from_interaction(
            state=rs,
            interaction_valence=0.5,
            profile_a={"agreeableness": 0.7, "neuroticism": 0.3},
            attachment_style_a=None,
        )
        assert updated.investment >= rs.investment

    def test_interaction_count_increments(self):
        rs = RelationshipState(agent_a_id="alice", agent_b_id="bob", interaction_count=5)
        updated = self.engine.update_from_interaction(
            state=rs,
            interaction_valence=0.5,
            profile_a={"agreeableness": 0.5, "neuroticism": 0.5},
            attachment_style_a=None,
        )
        assert updated.interaction_count == 6

    def test_attachment_style_modulates_anxious(self):
        """Anxious attachment → higher sensitivity to negative interactions."""
        rs = RelationshipState(agent_a_id="alice", agent_b_id="bob", trust=0.5)
        secure_att = AttachmentStyle(agent_id="alice", style="secure", anxiety=0.1)
        anxious_att = AttachmentStyle(agent_id="alice", style="anxious", anxiety=0.9)
        profile = {"agreeableness": 0.5, "neuroticism": 0.5}

        updated_secure = self.engine.update_from_interaction(
            state=rs, interaction_valence=-0.5,
            profile_a=profile, attachment_style_a=secure_att,
        )
        updated_anxious = self.engine.update_from_interaction(
            state=rs, interaction_valence=-0.5,
            profile_a=profile, attachment_style_a=anxious_att,
        )
        # Anxious attachment amplifies negative interaction effect on trust
        assert updated_anxious.trust <= updated_secure.trust

    def test_compute_gottman_score_returns_dict(self):
        score = self.engine.compute_gottman_score(
            interaction_valence=-0.6,
            contempt_signal=0.4,
            defensiveness_signal=0.5,
            stonewalling_signal=0.3,
        )
        assert isinstance(score, dict)
        for key in ("criticism", "contempt", "defensiveness", "stonewalling"):
            assert key in score
            assert 0.0 <= score[key] <= 1.0

    def test_compute_gottman_aggregate_score(self):
        score = self.engine.compute_gottman_score(
            interaction_valence=-0.8,
            contempt_signal=0.9,
            defensiveness_signal=0.8,
            stonewalling_signal=0.7,
        )
        # High negativity → high aggregate
        agg = sum(score.values()) / len(score)
        assert agg > 0.5

    def test_batch_update_returns_list(self):
        states = {
            ("alice", "bob"): RelationshipState(agent_a_id="alice", agent_b_id="bob"),
            ("alice", "carol"): RelationshipState(agent_a_id="alice", agent_b_id="carol"),
        }
        interactions = {
            ("alice", "bob"): 0.5,
            ("alice", "carol"): -0.3,
        }
        profiles = {"alice": {"agreeableness": 0.6, "neuroticism": 0.4}}
        styles: dict = {}

        results = self.engine.batch_update(
            states=states,
            interactions=interactions,
            profiles=profiles,
            attachment_styles=styles,
        )
        assert isinstance(results, list)
        assert len(results) == 2
        for rs in results:
            assert isinstance(rs, RelationshipState)

    def test_batch_update_immutable_original(self):
        """Original states must remain unchanged after batch_update."""
        rs = RelationshipState(agent_a_id="alice", agent_b_id="bob", intimacy=0.3)
        states = {("alice", "bob"): rs}
        interactions = {("alice", "bob"): 0.8}
        profiles = {"alice": {"agreeableness": 0.8, "neuroticism": 0.2}}

        self.engine.batch_update(
            states=states,
            interactions=interactions,
            profiles=profiles,
            attachment_styles={},
        )
        assert states[("alice", "bob")].intimacy == pytest.approx(0.3)
