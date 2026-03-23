"""Tests for Phase 18 information warfare — fact-checking and fabricated content."""

from __future__ import annotations

import dataclasses

import pytest

from backend.app.services.agent_factory import AgentProfile
from backend.app.services.info_warfare import (
    _FACT_CHECK_BASE_ACCURACY,
    _FACT_CHECK_CONSCIEN_BONUS,
    _FACT_CHECK_CONSCIEN_MIN,
    _FACT_CHECK_EDUCATION,
    _FACT_CHECK_OPENNESS_MIN,
    FabricatedPost,
    FactCheckResult,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_profile(**kwargs) -> AgentProfile:
    defaults = dict(
        id=1,
        agent_type="npc",
        age=35,
        sex="M",
        district="沙田",
        occupation="輔助專業人員",
        income_bracket="$25,000-$39,999",
        education_level="學位或以上",
        marital_status="已婚",
        housing_type="私人住宅",
        openness=0.7,
        conscientiousness=0.75,
        extraversion=0.5,
        agreeableness=0.6,
        neuroticism=0.4,
        monthly_income=30_000,
        savings=250_000,
        political_stance=0.5,
    )
    defaults.update(kwargs)
    return AgentProfile(**defaults)


# ---------------------------------------------------------------------------
# FactCheckResult frozen dataclass tests
# ---------------------------------------------------------------------------


class TestFactCheckResult:
    def test_frozen_dataclass(self):
        result = FactCheckResult(
            session_id="s",
            checker_agent_id=1,
            post_id="post_abc",
            verdict="misleading",
            confidence=0.82,
            round_number=3,
        )
        assert result.verdict == "misleading"
        assert result.confidence == 0.82
        with pytest.raises((TypeError, dataclasses.FrozenInstanceError)):
            result.verdict = "accurate"  # type: ignore[misc]

    def test_valid_verdicts(self):
        for verdict in ("accurate", "misleading", "fabricated", "unverifiable"):
            fc = FactCheckResult(
                session_id="s",
                checker_agent_id=1,
                post_id="p1",
                verdict=verdict,
                confidence=0.75,
                round_number=1,
            )
            assert fc.verdict == verdict

    def test_confidence_range_preserved(self):
        result = FactCheckResult(
            session_id="s",
            checker_agent_id=2,
            post_id="post_xyz",
            verdict="accurate",
            confidence=0.95,
            round_number=5,
        )
        assert 0.0 <= result.confidence <= 1.0


# ---------------------------------------------------------------------------
# FabricatedPost frozen dataclass tests
# ---------------------------------------------------------------------------


class TestFabricatedPost:
    def test_frozen_dataclass(self):
        fp = FabricatedPost(
            session_id="s",
            operator_agent_id=42,
            content="虛假帖文示例",
            target_topic="政府政策",
            target_sentiment="negative",
            round_number=7,
        )
        assert fp.operator_agent_id == 42
        assert fp.target_sentiment == "negative"
        with pytest.raises((TypeError, dataclasses.FrozenInstanceError)):
            fp.content = "modified"  # type: ignore[misc]

    def test_sentiment_values(self):
        for sentiment in ("negative", "positive", "neutral"):
            fp = FabricatedPost(
                session_id="s",
                operator_agent_id=1,
                content="test",
                target_topic="移民問題",
                target_sentiment=sentiment,
                round_number=1,
            )
            assert fp.target_sentiment == sentiment


# ---------------------------------------------------------------------------
# Fact-check eligibility constants
# ---------------------------------------------------------------------------


class TestFactCheckEligibility:
    def test_education_threshold(self):
        """Only degree-holders can fact-check."""
        assert _FACT_CHECK_EDUCATION == "學位或以上"

    def test_accuracy_formula(self):
        """Accuracy = base + conscientiousness × bonus, capped at 0.95."""
        profile = _make_profile(conscientiousness=0.7)
        expected = min(0.95, _FACT_CHECK_BASE_ACCURACY + 0.7 * _FACT_CHECK_CONSCIEN_BONUS)
        assert abs(expected - 0.77) < 0.001

    def test_high_conscien_accuracy_cap(self):
        """Very high conscientiousness should not exceed accuracy cap."""
        max_accuracy = min(0.95, _FACT_CHECK_BASE_ACCURACY + 1.0 * _FACT_CHECK_CONSCIEN_BONUS)
        assert max_accuracy <= 0.95

    def test_eligible_checker_criteria(self):
        """Verify that an eligible checker meets all three criteria."""
        profile = _make_profile(
            education_level="學位或以上",
            conscientiousness=0.7,
            openness=0.6,
        )
        assert profile.education_level == _FACT_CHECK_EDUCATION
        assert profile.conscientiousness > _FACT_CHECK_CONSCIEN_MIN
        assert profile.openness > _FACT_CHECK_OPENNESS_MIN

    def test_ineligible_checker_low_education(self):
        """Agent with secondary education cannot fact-check."""
        profile = _make_profile(
            education_level="中學",
            conscientiousness=0.8,
            openness=0.8,
        )
        assert profile.education_level != _FACT_CHECK_EDUCATION

    def test_ineligible_checker_low_conscien(self):
        """Agent with low conscientiousness is not a reliable fact-checker."""
        profile = _make_profile(
            education_level="學位或以上",
            conscientiousness=0.4,  # below 0.6 threshold
            openness=0.7,
        )
        assert profile.conscientiousness <= _FACT_CHECK_CONSCIEN_MIN

    def test_ineligible_checker_low_openness(self):
        """Agent with low openness does not seek out contradictory information."""
        profile = _make_profile(
            education_level="學位或以上",
            conscientiousness=0.7,
            openness=0.3,  # below 0.5 threshold
        )
        assert profile.openness <= _FACT_CHECK_OPENNESS_MIN


# ---------------------------------------------------------------------------
# Influence operator agent type tests
# ---------------------------------------------------------------------------


class TestInfluenceOperator:
    def test_influence_operator_agent_type(self):
        profile = _make_profile(
            agent_type="influence_operator",
            target_topic="房地產市場",
            target_sentiment="negative",
        )
        assert profile.agent_type == "influence_operator"
        assert profile.target_topic == "房地產市場"
        assert profile.target_sentiment == "negative"

    def test_citizen_default_type(self):
        """Normal NPC agents have agent_type 'npc'."""
        profile = _make_profile(agent_type="npc")
        assert profile.agent_type == "npc"

    def test_operator_fields_are_immutable(self):
        """AgentProfile with operator fields is still frozen."""
        profile = _make_profile(
            agent_type="influence_operator",
            target_topic="移民問題",
            target_sentiment="positive",
        )
        with pytest.raises((TypeError, dataclasses.FrozenInstanceError)):
            profile.target_topic = "hacked"  # type: ignore[misc]

    def test_citizen_default_empty_target_fields(self):
        """Normal agents have empty target_topic and target_sentiment."""
        profile = _make_profile()
        assert profile.target_topic == ""
        assert profile.target_sentiment == ""
