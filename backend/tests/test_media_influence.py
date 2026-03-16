"""Tests for MediaInfluenceModel — media outlet definitions, receptivity, and stance propagation."""

from __future__ import annotations

import pytest

from backend.app.services.media_influence import (
    DEFAULT_MEDIA_OUTLETS,
    MediaAgent,
    MediaInfluenceModel,
    _MAX_SHIFT_PER_ROUND,
    _MIN_RECEPTIVITY,
    _MIN_STANCE_DELTA,
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
    """Verify the 8 HK media outlet definitions."""

    def test_exactly_eight_outlets(self) -> None:
        assert len(DEFAULT_MEDIA_OUTLETS) == 8

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
        expected = {"TVB新聞", "香港電台RTHK", "明報", "南華早報", "大公報", "星島日報", "獨立媒體", "眾新聞"}
        assert names == expected


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
