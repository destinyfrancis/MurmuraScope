"""Tests for Phase 1B: Temporal Async Activation.

Covers:
  - ActivityProfile model (24-dim vector, chronotype, probability_at_hour)
  - TemporalActivationService (round_to_hour, should_activate, generate_profile)
  - Chronotype assignment rules (age/occupation)
  - Backward compatibility (no profile → always active)
  - Integration: simulation_runner._is_agent_active fallback
"""

from __future__ import annotations

import random

import pytest

from backend.app.models.activity_profile import (
    VALID_CHRONOTYPES,
    ActivityProfile,
)
from backend.app.services.temporal_activation import (
    _CHRONOTYPE_TEMPLATES,
    _START_HOUR,
    TemporalActivationService,
)

# ---------------------------------------------------------------------------
# ActivityProfile model tests
# ---------------------------------------------------------------------------


class TestActivityProfileModel:
    """Unit tests for ActivityProfile frozen dataclass."""

    def _make_profile(
        self,
        chronotype: str = "standard",
        base_rate: float = 0.8,
    ) -> ActivityProfile:
        vector = tuple(_CHRONOTYPE_TEMPLATES[chronotype])
        return ActivityProfile(
            agent_id=1,
            chronotype=chronotype,  # type: ignore[arg-type]
            activity_vector=vector,
            base_activity_rate=base_rate,
        )

    def test_valid_creation(self) -> None:
        profile = self._make_profile()
        assert profile.agent_id == 1
        assert profile.chronotype == "standard"
        assert len(profile.activity_vector) == 24

    def test_all_chronotypes_accepted(self) -> None:
        for ct in VALID_CHRONOTYPES:
            p = self._make_profile(chronotype=ct)
            assert p.chronotype == ct

    def test_invalid_vector_length_raises(self) -> None:
        with pytest.raises(ValueError, match="exactly 24"):
            ActivityProfile(
                agent_id=1,
                chronotype="standard",
                activity_vector=tuple([0.5] * 10),
                base_activity_rate=0.8,
            )

    def test_invalid_chronotype_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown chronotype"):
            ActivityProfile(
                agent_id=1,
                chronotype="vampire",  # type: ignore[arg-type]
                activity_vector=tuple([0.5] * 24),
                base_activity_rate=0.8,
            )

    def test_invalid_base_rate_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="base_activity_rate"):
            ActivityProfile(
                agent_id=1,
                chronotype="standard",
                activity_vector=tuple([0.5] * 24),
                base_activity_rate=0.0,
            )

    def test_invalid_base_rate_over_one_raises(self) -> None:
        with pytest.raises(ValueError, match="base_activity_rate"):
            ActivityProfile(
                agent_id=1,
                chronotype="standard",
                activity_vector=tuple([0.5] * 24),
                base_activity_rate=1.5,
            )

    def test_probability_at_hour_scales_by_base_rate(self) -> None:
        vector = tuple([0.8] * 24)
        profile = ActivityProfile(
            agent_id=1,
            chronotype="standard",
            activity_vector=vector,
            base_activity_rate=0.5,
        )
        # 0.8 × 0.5 = 0.4
        assert abs(profile.probability_at_hour(12) - 0.4) < 1e-9

    def test_probability_at_hour_out_of_range(self) -> None:
        profile = self._make_profile()
        assert profile.probability_at_hour(-1) == 0.0
        assert profile.probability_at_hour(24) == 0.0
        assert profile.probability_at_hour(100) == 0.0

    def test_profile_is_frozen(self) -> None:
        profile = self._make_profile()
        with pytest.raises((AttributeError, TypeError)):
            profile.base_activity_rate = 0.9  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TemporalActivationService tests
# ---------------------------------------------------------------------------


class TestRoundToHour:
    """Tests for TemporalActivationService.round_to_hour."""

    def setup_method(self) -> None:
        self.svc = TemporalActivationService()

    def test_round_zero_is_start_hour(self) -> None:
        assert self.svc.round_to_hour(0) == _START_HOUR

    def test_round_one_is_next_hour(self) -> None:
        assert self.svc.round_to_hour(1) == (_START_HOUR + 1) % 24

    def test_wraps_at_24(self) -> None:
        assert self.svc.round_to_hour(24) == _START_HOUR

    def test_midnight_round(self) -> None:
        # 24 - START_HOUR rounds after start → midnight (hour 0)
        midnight_offset = (24 - _START_HOUR) % 24
        assert self.svc.round_to_hour(midnight_offset) == 0

    def test_all_rounds_in_0_23(self) -> None:
        for r in range(100):
            h = self.svc.round_to_hour(r)
            assert 0 <= h <= 23, f"round {r} → hour {h} out of range"


class TestShouldActivate:
    """Tests for TemporalActivationService.should_activate."""

    def setup_method(self) -> None:
        self.svc = TemporalActivationService()

    def _flat_profile(self, p: float) -> ActivityProfile:
        return ActivityProfile(
            agent_id=99,
            chronotype="standard",
            activity_vector=tuple([p] * 24),
            base_activity_rate=1.0,
        )

    def test_always_active_with_probability_one(self) -> None:
        profile = self._flat_profile(1.0)
        rng = random.Random(42)
        results = [self.svc.should_activate(profile, r, rng) for r in range(50)]
        assert all(results), "p=1.0 should always activate"

    def test_minimum_floor_prevents_zero(self) -> None:
        """Even a zero-probability vector should activate at least sometimes (5% floor)."""
        profile = self._flat_profile(0.0)
        rng = random.Random(1)
        results = [self.svc.should_activate(profile, r, rng) for r in range(200)]
        # With 5% floor, roughly 10 activations expected from 200 trials
        assert sum(results) > 0, "5% floor should produce at least one activation"

    def test_activation_is_probabilistic(self) -> None:
        """p=0.5 should produce roughly 50% activations."""
        profile = self._flat_profile(0.5)
        rng = random.Random(7)
        results = [self.svc.should_activate(profile, r, rng) for r in range(200)]
        ratio = sum(results) / len(results)
        assert 0.3 <= ratio <= 0.7, f"Expected ~50%, got {ratio:.0%}"


class TestGenerateProfile:
    """Tests for TemporalActivationService.generate_profile."""

    def setup_method(self) -> None:
        self.svc = TemporalActivationService()
        self.rng = random.Random(42)

    def test_returns_activity_profile(self) -> None:
        p = self.svc.generate_profile(1, 35, "文員", self.rng)
        assert isinstance(p, ActivityProfile)

    def test_activity_vector_length(self) -> None:
        p = self.svc.generate_profile(2, 30, "專業人員", self.rng)
        assert len(p.activity_vector) == 24

    def test_all_vector_values_in_range(self) -> None:
        p = self.svc.generate_profile(3, 45, "經理及行政人員", self.rng)
        for v in p.activity_vector:
            assert 0.0 <= v <= 1.0, f"Vector value {v} out of [0,1]"

    def test_base_rate_in_range(self) -> None:
        for age in (20, 35, 50, 70):
            p = self.svc.generate_profile(age, age, "文員", self.rng)
            assert 0.0 < p.base_activity_rate <= 1.0

    def test_elderly_gets_morning_lark(self) -> None:
        """Agents 65+ should predominantly be morning_lark."""
        morning_count = sum(
            1 for _ in range(50) if self.svc.generate_profile(1, 70, "退休", self.rng).chronotype == "morning_lark"
        )
        # Expect at least 40% morning_lark (true rate is 60%)
        assert morning_count >= 20, f"Only {morning_count}/50 were morning_lark for 退休"

    def test_student_gets_evening_owl(self) -> None:
        """Students under 25 should predominantly be evening_owl."""
        owl_count = sum(
            1 for _ in range(50) if self.svc.generate_profile(1, 20, "學生", self.rng).chronotype == "evening_owl"
        )
        assert owl_count >= 20, f"Only {owl_count}/50 were evening_owl for 學生"

    def test_night_shift_occupation(self) -> None:
        """Non技術工人 should have some night_shift chronotypes."""
        night_count = sum(
            1 for _ in range(50) if self.svc.generate_profile(1, 35, "非技術工人", self.rng).chronotype == "night_shift"
        )
        assert night_count >= 5, f"Expected some night_shift, got {night_count}/50"

    def test_standard_worker_mostly_standard(self) -> None:
        """Office workers (文員, 30) should mostly be standard chronotype."""
        std_count = sum(
            1 for _ in range(50) if self.svc.generate_profile(1, 30, "文員", self.rng).chronotype == "standard"
        )
        assert std_count >= 20, f"Only {std_count}/50 standard for office worker"


# ---------------------------------------------------------------------------
# Template sanity checks
# ---------------------------------------------------------------------------


class TestChronotypeTemplates:
    """Basic sanity checks for the built-in activity templates."""

    def test_all_chronotypes_have_templates(self) -> None:
        for ct in VALID_CHRONOTYPES:
            assert ct in _CHRONOTYPE_TEMPLATES, f"{ct} missing from templates"

    def test_all_templates_24_slots(self) -> None:
        for ct, tmpl in _CHRONOTYPE_TEMPLATES.items():
            assert len(tmpl) == 24, f"{ct} template has {len(tmpl)} slots (expected 24)"

    def test_all_template_values_in_range(self) -> None:
        for ct, tmpl in _CHRONOTYPE_TEMPLATES.items():
            for i, v in enumerate(tmpl):
                assert 0.0 <= v <= 1.0, f"{ct}[{i}] = {v} out of [0,1]"

    def test_each_template_has_peak_at_1_0(self) -> None:
        """Every template should have at least one peak slot at 1.0."""
        for ct, tmpl in _CHRONOTYPE_TEMPLATES.items():
            assert max(tmpl) == 1.0, f"{ct} template has no peak at 1.0"

    def test_morning_lark_peaks_in_morning(self) -> None:
        tmpl = _CHRONOTYPE_TEMPLATES["morning_lark"]
        peak_hour = tmpl.index(max(tmpl))
        assert 6 <= peak_hour <= 10, f"morning_lark peaks at hour {peak_hour}"

    def test_evening_owl_peaks_in_evening(self) -> None:
        tmpl = _CHRONOTYPE_TEMPLATES["evening_owl"]
        peak_hour = tmpl.index(max(tmpl))
        assert 18 <= peak_hour <= 23, f"evening_owl peaks at hour {peak_hour}"

    def test_night_shift_peaks_at_night(self) -> None:
        tmpl = _CHRONOTYPE_TEMPLATES["night_shift"]
        peak_hour = tmpl.index(max(tmpl))
        assert peak_hour <= 4 or peak_hour >= 20, f"night_shift peaks at hour {peak_hour}"


# ---------------------------------------------------------------------------
# Backward-compatibility: no profile → always active
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """When no activity profile exists, _is_agent_active must return True."""

    def test_is_agent_active_no_profiles(self) -> None:
        """SimulationRunner._is_agent_active must return True when no profiles loaded."""
        from backend.app.services.simulation_runner import SimulationRunner

        runner = SimulationRunner(dry_run=True)
        # No profiles loaded for this session → should always return True
        result = runner._is_agent_active("nonexistent-session", "agent_001", 5)
        assert result is True

    def test_is_agent_active_unknown_username(self) -> None:
        """Unknown username within a loaded session returns True (safe fallback)."""
        from backend.app.services.simulation_runner import SimulationRunner

        runner = SimulationRunner(dry_run=True)
        # Inject a stub profile map that doesn't include the queried username
        runner._activity_profiles["test-session"] = {
            "known_agent": {
                "agent_id": 1,
                "chronotype": "standard",
                "activity_vector": list(_CHRONOTYPE_TEMPLATES["standard"]),
                "base_activity_rate": 0.8,
            }
        }
        result = runner._is_agent_active("test-session", "unknown_agent", 5)
        assert result is True
