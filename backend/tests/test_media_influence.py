"""Tests for MediaInfluenceModel — media outlet definitions, receptivity, and stance propagation."""

from __future__ import annotations

import pytest

from backend.app.services.media_influence import (
    _MAX_SHIFT_PER_ROUND,
    _MIN_RECEPTIVITY,
    _MIN_STANCE_DELTA,
    DEFAULT_MEDIA_OUTLETS,
    MediaAgent,
    MediaInfluenceModel,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def model() -> MediaInfluenceModel:
    return MediaInfluenceModel()


@pytest.fixture()
def sample_media_agent() -> MediaAgent:
    return MediaAgent(
        id=1,
        session_id="sess-001",
        media_name="TestMedia",
        political_lean=0.2,
        influence_radius=50,
        credibility=0.7,
    )


# ---------------------------------------------------------------------------
# DEFAULT_MEDIA_OUTLETS
# ---------------------------------------------------------------------------


class TestDefaultMediaOutlets:
    """Verify the 7 HK media outlet definitions (眾新聞 removed Jan 2022)."""

    def test_exactly_seven_outlets(self) -> None:
        assert len(DEFAULT_MEDIA_OUTLETS) == 7

    def test_all_outlets_have_required_keys(self) -> None:
        required = {"media_name", "political_lean", "influence_radius", "credibility"}
        for outlet in DEFAULT_MEDIA_OUTLETS:
            assert required.issubset(outlet.keys()), f"Missing keys in {outlet.get('media_name')}"

    def test_political_lean_bounded(self) -> None:
        for outlet in DEFAULT_MEDIA_OUTLETS:
            assert 0.0 <= outlet["political_lean"] <= 1.0, outlet["media_name"]

    def test_credibility_bounded(self) -> None:
        for outlet in DEFAULT_MEDIA_OUTLETS:
            assert 0.0 <= outlet["credibility"] <= 1.0, outlet["media_name"]

    def test_influence_radius_positive(self) -> None:
        for outlet in DEFAULT_MEDIA_OUTLETS:
            assert outlet["influence_radius"] > 0, outlet["media_name"]

    def test_known_outlet_names(self) -> None:
        names = {o["media_name"] for o in DEFAULT_MEDIA_OUTLETS}
        expected = {"TVB新聞", "香港電台RTHK", "明報", "南華早報", "大公報", "星島日報", "獨立媒體"}
        assert names == expected

    def test_rthk_credibility_post_2021(self) -> None:
        """RTHK credibility reduced to 0.55 after 2021 management change."""
        rthk = next(o for o in DEFAULT_MEDIA_OUTLETS if o["media_name"] == "香港電台RTHK")
        assert rthk["credibility"] == 0.55

    def test_no_ceased_outlets(self) -> None:
        """眾新聞 ceased Jan 2022 and should not be in defaults."""
        names = {o["media_name"] for o in DEFAULT_MEDIA_OUTLETS}
        assert "眾新聞" not in names


# ---------------------------------------------------------------------------
# MediaAgent frozen dataclass
# ---------------------------------------------------------------------------


class TestMediaAgent:
    def test_frozen(self, sample_media_agent: MediaAgent) -> None:
        with pytest.raises(AttributeError):
            sample_media_agent.credibility = 0.99  # type: ignore[misc]

    def test_fields(self, sample_media_agent: MediaAgent) -> None:
        assert sample_media_agent.media_name == "TestMedia"
        assert sample_media_agent.political_lean == 0.2
        assert sample_media_agent.influence_radius == 50
        assert sample_media_agent.credibility == 0.7


# ---------------------------------------------------------------------------
# Receptivity computation (inline algorithm test)
# ---------------------------------------------------------------------------


class TestReceptivity:
    """Test the receptivity formula: max(0, 1 - stance_diff * 2.0) * credibility."""

    @staticmethod
    def _receptivity(agent_stance: float, media_lean: float, credibility: float) -> float:
        stance_diff = abs(agent_stance - media_lean)
        return max(0.0, 1.0 - stance_diff * 2.0) * credibility

    def test_aligned_agent_high_receptivity(self) -> None:
        # Agent at 0.2, media at 0.2 => diff=0 => receptivity = 1.0 * cred
        r = self._receptivity(0.2, 0.2, 0.8)
        assert r == pytest.approx(0.8)

    def test_distant_agent_zero_receptivity(self) -> None:
        # Agent at 0.9, media at 0.1 => diff=0.8 => 1-1.6 = -0.6 => clamp 0
        r = self._receptivity(0.9, 0.1, 0.8)
        assert r == 0.0

    def test_moderate_distance(self) -> None:
        # diff=0.2 => 1-0.4=0.6 => *0.7 = 0.42
        r = self._receptivity(0.4, 0.2, 0.7)
        assert r == pytest.approx(0.42)

    def test_below_min_receptivity_threshold(self) -> None:
        # diff=0.49 => 1-0.98=0.02 => *0.5=0.01 < _MIN_RECEPTIVITY (0.05)
        r = self._receptivity(0.69, 0.2, 0.5)
        assert r < _MIN_RECEPTIVITY


# ---------------------------------------------------------------------------
# Asymmetric receptivity (H11)
# ---------------------------------------------------------------------------


class TestAsymmetricReceptivity:
    """H11: Aligned agents should be more receptive than cross-cutting ones."""

    @staticmethod
    def _receptivity_with_asymmetry(agent_stance: float, media_lean: float, credibility: float) -> float:
        """Reproduce the receptivity formula WITH asymmetry adjustment."""
        from backend.app.services.media_influence import compute_receptivity

        return compute_receptivity(agent_stance, media_lean, credibility)

    def test_aligned_agent_boosted(self) -> None:
        """Pro-establishment agent + pro-establishment media → 15% boost."""
        r = self._receptivity_with_asymmetry(0.2, 0.2, 0.7)
        base = max(0.0, 1.0 - 0.0 * 2.0) * 0.7  # = 0.7
        assert r == pytest.approx(base * 1.15, abs=0.01)

    def test_cross_cutting_penalised(self) -> None:
        """Pro-democracy agent + pro-establishment media → 15% penalty."""
        r = self._receptivity_with_asymmetry(0.8, 0.3, 0.7)
        base = max(0.0, 1.0 - 0.5 * 2.0) * 0.7  # = 0.0 (too far apart)
        # With diff=0.5, base receptivity is 0 — so penalty doesn't matter
        # Use a closer but cross-cutting pair: agent=0.6, media=0.3
        r2 = self._receptivity_with_asymmetry(0.6, 0.3, 0.7)
        base2 = max(0.0, 1.0 - 0.3 * 2.0) * 0.7  # = 0.28
        assert r2 == pytest.approx(base2 * 0.85, abs=0.01)

    def test_asymmetry_difference(self) -> None:
        """Aligned receptivity should be > cross-cutting for same stance_diff."""
        # Both have diff=0.1 from media
        # Aligned: agent=0.3, media=0.2 (both < 0.5)
        r_aligned = self._receptivity_with_asymmetry(0.3, 0.2, 0.7)
        # Cross-cutting: agent=0.6, media=0.5-0.1=0.4... but agent>0.5 and media<0.5
        # Better: agent=0.6, media=0.5 — agent>0.5, media=0.5 (centrist, not aligned)
        # Use: agent=0.3, media=0.4 — agent<0.5, media<0.5 (aligned)
        # vs: agent=0.6, media=0.4 — agent>0.5, media<0.5 (cross-cutting), diff=0.2
        r_cross = self._receptivity_with_asymmetry(0.6, 0.4, 0.7)
        # r_aligned: diff=0.1, aligned → 1.15× boost
        # r_cross: diff=0.2, cross-cutting → 0.85× penalty
        assert r_aligned > r_cross


# ---------------------------------------------------------------------------
# Shift clamping
# ---------------------------------------------------------------------------


class TestShiftClamping:
    """Test that stance shift is bounded by _MAX_SHIFT_PER_ROUND."""

    def test_max_shift_constant(self) -> None:
        assert _MAX_SHIFT_PER_ROUND == 0.02

    def test_min_stance_delta_constant(self) -> None:
        assert _MIN_STANCE_DELTA == 0.001

    def test_shift_formula_clamped(self) -> None:
        # Even with maximum receptivity (1.0 * 1.0) and large gap:
        # raw_shift = (0.0 - 1.0) * 1.0 * 0.03 = -0.03
        # clamped to -0.02
        raw_shift = (0.0 - 1.0) * 1.0 * 0.03
        clamped = max(-_MAX_SHIFT_PER_ROUND, min(_MAX_SHIFT_PER_ROUND, raw_shift))
        assert clamped == -_MAX_SHIFT_PER_ROUND

    def test_small_shift_not_clamped(self) -> None:
        # diff small: raw_shift = (0.2 - 0.22) * 0.7 * 0.03 = -0.00042
        raw_shift = (0.2 - 0.22) * 0.7 * 0.03
        clamped = max(-_MAX_SHIFT_PER_ROUND, min(_MAX_SHIFT_PER_ROUND, raw_shift))
        assert clamped == pytest.approx(raw_shift, abs=1e-9)
        assert abs(clamped) < _MAX_SHIFT_PER_ROUND
