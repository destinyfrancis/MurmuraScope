"""Tests for PoliticalModel — stance assignment, echo chambers, spiral of silence, monitoring."""

from __future__ import annotations

import pytest

from backend.app.services.political_model import (
    PoliticalModel,
    PoliticalProfile,
    StanceReport,
    _DISTRICT_LEAN,
    _EDUCATION_LEAN,
    _ESTABLISHMENT_MAX,
    _DEMOCRACY_MIN,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def model() -> PoliticalModel:
    return PoliticalModel()


# ---------------------------------------------------------------------------
# Frozen dataclasses
# ---------------------------------------------------------------------------


class TestFrozenDataclasses:
    def test_political_profile_frozen(self) -> None:
        p = PoliticalProfile(agent_id=1, political_stance=0.5, political_label="中間派", engagement_willingness=0.9)
        with pytest.raises(AttributeError):
            p.political_stance = 0.8  # type: ignore[misc]

    def test_stance_report_frozen(self) -> None:
        r = StanceReport(mean=0.5, std=0.1, skewness=0.0, polarization_index=0.3, extremism_ratio=0.05, alert_level="normal")
        with pytest.raises(AttributeError):
            r.alert_level = "critical"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Political label
# ---------------------------------------------------------------------------


class TestGetPoliticalLabel:
    def test_pro_establishment(self, model: PoliticalModel) -> None:
        assert model.get_political_label(0.0) == "建制派"
        assert model.get_political_label(0.29) == "建制派"

    def test_centrist(self, model: PoliticalModel) -> None:
        assert model.get_political_label(0.3) == "中間派"
        assert model.get_political_label(0.5) == "中間派"
        assert model.get_political_label(0.69) == "中間派"

    def test_pro_democracy(self, model: PoliticalModel) -> None:
        assert model.get_political_label(0.7) == "民主派"
        assert model.get_political_label(1.0) == "民主派"

    def test_boundary_values(self, model: PoliticalModel) -> None:
        assert _ESTABLISHMENT_MAX == 0.3
        assert _DEMOCRACY_MIN == 0.7


# ---------------------------------------------------------------------------
# Stance assignment
# ---------------------------------------------------------------------------


class TestAssignPoliticalStance:
    def test_result_bounded_0_to_1(self, model: PoliticalModel) -> None:
        for _ in range(50):
            stance = model.assign_political_stance(
                age=25, district="深水埗", education_level="學位或以上",
                occupation="學生", openness=0.9, neuroticism=0.2,
            )
            assert 0.0 <= stance <= 1.0

    def test_young_agent_leans_pro_democracy(self, model: PoliticalModel) -> None:
        stances = [
            model.assign_political_stance(
                age=25, district="沙田", education_level="學位或以上",
                occupation="IT", openness=0.7, neuroticism=0.3,
            )
            for _ in range(100)
        ]
        avg = sum(stances) / len(stances)
        # Young + university + high openness => clearly above 0.5
        assert avg > 0.55

    def test_old_agent_leans_establishment(self, model: PoliticalModel) -> None:
        stances = [
            model.assign_political_stance(
                age=65, district="元朗", education_level="小學或以下",
                occupation="退休", openness=0.3, neuroticism=0.6,
            )
            for _ in range(100)
        ]
        avg = sum(stances) / len(stances)
        # Old + low education + low openness + establishment district => below 0.5
        assert avg < 0.45

    def test_district_lean_applied(self, model: PoliticalModel) -> None:
        # 深水埗 has +0.05 lean; 元朗 has -0.04 lean
        assert _DISTRICT_LEAN["深水埗"] > 0
        assert _DISTRICT_LEAN["元朗"] < 0

    def test_education_lean_applied(self, model: PoliticalModel) -> None:
        assert _EDUCATION_LEAN["學位或以上"] > 0
        assert _EDUCATION_LEAN["小學或以下"] < 0

    def test_personality_contribution_small_for_moderate_traits(self, model: PoliticalModel) -> None:
        """H5: personality multipliers should be small to avoid double-counting with belief bias."""
        # Moderate personality: openness=0.7, neuroticism=0.6
        # Personality contribution = (0.7-0.5)*multiplier + (0.6-0.5)*multiplier
        # With reduced multipliers (0.05 and 0.02), total ≈ 0.012
        # Must be < 0.05 for moderate traits
        base_stance = model.assign_political_stance(
            age=40, district="沙田", education_level="中學",
            occupation="Clerk", openness=0.5, neuroticism=0.5,
        )
        high_personality_stances = [
            model.assign_political_stance(
                age=40, district="沙田", education_level="中學",
                occupation="Clerk", openness=0.7, neuroticism=0.6,
            )
            for _ in range(200)
        ]
        base_stances = [
            model.assign_political_stance(
                age=40, district="沙田", education_level="中學",
                occupation="Clerk", openness=0.5, neuroticism=0.5,
            )
            for _ in range(200)
        ]
        avg_diff = abs(
            sum(high_personality_stances) / len(high_personality_stances)
            - sum(base_stances) / len(base_stances)
        )
        # Personality contribution for moderate traits must be < 0.02
        # (reduced multipliers to avoid double-counting with belief system)
        assert avg_diff < 0.02, f"Personality contribution {avg_diff:.4f} too large (double-counting risk)"

    def test_unknown_district_no_error(self, model: PoliticalModel) -> None:
        stance = model.assign_political_stance(
            age=40, district="UnknownDistrict", education_level="中學",
            occupation="Clerk", openness=0.5, neuroticism=0.5,
        )
        assert 0.0 <= stance <= 1.0


# ---------------------------------------------------------------------------
# Echo chamber score
# ---------------------------------------------------------------------------


class TestEchoChamberScore:
    def test_empty_neighbors_returns_zero(self, model: PoliticalModel) -> None:
        assert model.echo_chamber_score(0.5, []) == 0.0

    def test_identical_neighbors_returns_one(self, model: PoliticalModel) -> None:
        score = model.echo_chamber_score(0.5, [0.5, 0.5, 0.5])
        assert score == 1.0

    def test_maximally_diverse_returns_zero(self, model: PoliticalModel) -> None:
        # avg_diff = 0.5 => 1 - 0.5*2 = 0.0
        score = model.echo_chamber_score(0.5, [0.0, 1.0])
        assert score == 0.0

    def test_moderate_diversity(self, model: PoliticalModel) -> None:
        # avg_diff = 0.1 => 1 - 0.2 = 0.8
        score = model.echo_chamber_score(0.5, [0.4, 0.6])
        assert score == pytest.approx(0.8, abs=0.01)


# ---------------------------------------------------------------------------
# Spiral of silence
# ---------------------------------------------------------------------------


class TestSpiralOfSilence:
    def test_aligned_agent_full_willingness(self, model: PoliticalModel) -> None:
        w = model.spiral_of_silence(0.5, 0.5, 0.3)
        assert w == 1.0

    def test_minority_agent_reduced_willingness(self, model: PoliticalModel) -> None:
        # diff=0.4 > 0.3 => penalty = 0.4*0.4 = 0.16
        w = model.spiral_of_silence(0.9, 0.5, 0.3)
        assert w < 1.0

    def test_high_neuroticism_amplifies_silence(self, model: PoliticalModel) -> None:
        w_low_n = model.spiral_of_silence(0.9, 0.5, 0.3)
        w_high_n = model.spiral_of_silence(0.9, 0.5, 0.9)
        assert w_high_n < w_low_n

    def test_minimum_willingness_floor(self, model: PoliticalModel) -> None:
        # Extreme minority + high neuroticism => floor at 0.1
        w = model.spiral_of_silence(1.0, 0.0, 1.0)
        assert w >= 0.1

    def test_willingness_bounded(self, model: PoliticalModel) -> None:
        w = model.spiral_of_silence(0.5, 0.5, 0.0)
        assert 0.1 <= w <= 1.0


# ---------------------------------------------------------------------------
# Spiral of silence — district-level static method
# ---------------------------------------------------------------------------


class TestApplySpiralOfSilence:
    def test_conforming_agent_gets_full_multiplier(self) -> None:
        agents = [{"id": 1, "political_stance": 0.5, "district": "沙田"}]
        district_stats = {"沙田": 0.5}
        result = PoliticalModel.apply_spiral_of_silence(agents, district_stats)
        assert result[1] == 1.0

    def test_minority_agent_suppressed(self) -> None:
        agents = [{"id": 1, "political_stance": 0.9, "district": "沙田"}]
        district_stats = {"沙田": 0.3}  # diff = 0.6 > 0.3
        result = PoliticalModel.apply_spiral_of_silence(agents, district_stats)
        assert result[1] == 0.5

    def test_missing_stance_skipped(self) -> None:
        agents = [{"id": 1, "political_stance": None, "district": "沙田"}]
        district_stats = {"沙田": 0.5}
        result = PoliticalModel.apply_spiral_of_silence(agents, district_stats)
        assert len(result) == 0

    def test_unknown_district_defaults_to_05(self) -> None:
        agents = [{"id": 1, "political_stance": 0.5, "district": "火星"}]
        result = PoliticalModel.apply_spiral_of_silence(agents, {})
        assert result[1] == 1.0  # diff=0 from default 0.5


# ---------------------------------------------------------------------------
# Monitor stance distribution
# ---------------------------------------------------------------------------


class TestMonitorStanceDistribution:
    def test_uniform_stances_normal_alert(self) -> None:
        stances = [0.3 + i * 0.01 for i in range(40)]
        report = PoliticalModel.monitor_stance_distribution(stances)
        assert report.alert_level == "normal"

    def test_extreme_bimodal_triggers_warning_or_critical(self) -> None:
        stances = [0.05] * 50 + [0.95] * 50
        report = PoliticalModel.monitor_stance_distribution(stances)
        assert report.alert_level in ("warning", "critical")
        assert report.extremism_ratio > 0.25

    def test_small_sample_returns_normal(self) -> None:
        report = PoliticalModel.monitor_stance_distribution([0.5, 0.6])
        assert report.alert_level == "normal"
        assert report.std == 0.0

    def test_report_is_frozen(self) -> None:
        report = PoliticalModel.monitor_stance_distribution([0.5] * 10)
        with pytest.raises(AttributeError):
            report.mean = 0.99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Depolarization
# ---------------------------------------------------------------------------


class TestApplyDepolarization:
    def test_normal_alert_no_change(self) -> None:
        stances = [0.2, 0.5, 0.8]
        result = PoliticalModel.apply_depolarization(stances, "normal")
        assert result == stances

    def test_warning_pulls_toward_center(self) -> None:
        stances = [0.1, 0.9]
        result = PoliticalModel.apply_depolarization(stances, "warning")
        # strength=0.02 => 0.1 + (0.5-0.1)*0.02 = 0.108
        assert result[0] > 0.1
        assert result[1] < 0.9

    def test_critical_stronger_pull(self) -> None:
        stances = [0.1, 0.9]
        warning_result = PoliticalModel.apply_depolarization(stances, "warning")
        critical_result = PoliticalModel.apply_depolarization(stances, "critical")
        # Critical pulls harder toward 0.5
        assert critical_result[0] > warning_result[0]
        assert critical_result[1] < warning_result[1]

    def test_returns_new_list(self) -> None:
        stances = [0.2, 0.8]
        result = PoliticalModel.apply_depolarization(stances, "warning")
        assert result is not stances
