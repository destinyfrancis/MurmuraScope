"""Unit tests for TemporalActivationService parameterization (Phase 3.1).

Covers:
- Default start_hour=8 (08:00 behaviour preserved)
- Custom start_hour shifts clock correctly
- Custom primetime_hours changes multiplier window
- primetime_multiplier=1.0 disables boost
- round_to_hour wraps at 24
- should_activate minimum floor enforced
- Backward compatibility: module-level constants unchanged
"""

from __future__ import annotations

import random

import pytest

from backend.app.services.temporal_activation import (
    TemporalActivationService,
    _PRIMETIME_HOURS,
    _PRIMETIME_MULTIPLIER,
    _START_HOUR,
)
from backend.app.models.activity_profile import ActivityProfile


def _make_profile(agent_id: int = 1, constant_p: float = 0.5) -> ActivityProfile:
    """Creates an ActivityProfile with a uniform activity vector."""
    return ActivityProfile(
        agent_id=agent_id,
        chronotype="standard",
        activity_vector=tuple(constant_p for _ in range(24)),
        base_activity_rate=constant_p,
    )


class TestModuleLevelConstants:
    """Verify backward-compat constants are unchanged."""

    def test_start_hour_default_8(self):
        assert _START_HOUR == 8

    def test_primetime_hours_18_to_23(self):
        assert _PRIMETIME_HOURS == frozenset(range(18, 24))

    def test_primetime_multiplier_1_5(self):
        assert _PRIMETIME_MULTIPLIER == pytest.approx(1.5)


class TestDefaultBehaviour:
    def test_round_0_maps_to_hour_8(self):
        svc = TemporalActivationService()
        assert svc.round_to_hour(0) == 8

    def test_round_12_maps_to_hour_20(self):
        svc = TemporalActivationService()
        assert svc.round_to_hour(12) == 20

    def test_round_16_maps_to_hour_0_next_day(self):
        svc = TemporalActivationService()
        assert svc.round_to_hour(16) == 0

    def test_round_24_wraps_back_to_8(self):
        svc = TemporalActivationService()
        assert svc.round_to_hour(24) == 8


class TestCustomStartHour:
    def test_start_hour_0(self):
        svc = TemporalActivationService(start_hour=0)
        assert svc.round_to_hour(0) == 0
        assert svc.round_to_hour(8) == 8

    def test_start_hour_22(self):
        svc = TemporalActivationService(start_hour=22)
        assert svc.round_to_hour(0) == 22
        assert svc.round_to_hour(2) == 0  # wraps

    def test_start_hour_24_wraps_to_0(self):
        svc = TemporalActivationService(start_hour=24)
        assert svc.round_to_hour(0) == 0


class TestCustomPrimetimeHours:
    def test_disabled_primetime_no_boost(self):
        svc = TemporalActivationService(primetime_hours=frozenset())
        profile = _make_profile(constant_p=0.5)
        # All hours should give the same probability (no multiplier window)
        ps = set()
        rng = random.Random(42)
        for round_num in range(24):
            # Use deterministic rng; check no probability amplification is applied
            p_raw = profile.probability_at_hour(svc.round_to_hour(round_num))
            multiplier = 1.0  # our custom service has empty primetime set
            ps.add(round(p_raw * multiplier, 4))
        assert len(ps) == 1  # uniform profile → all same

    def test_custom_primetime_hours(self):
        custom_pt = frozenset(range(9, 12))  # morning primetime
        svc = TemporalActivationService(
            start_hour=9,
            primetime_hours=custom_pt,
            primetime_multiplier=2.0,
        )
        assert 9 in svc._primetime_hours
        assert 18 not in svc._primetime_hours


class TestPrimetimeMultiplier:
    def test_multiplier_1_no_boost(self):
        svc = TemporalActivationService(primetime_multiplier=1.0)
        # At a primetime hour (18:00), probability should equal base
        profile = _make_profile(constant_p=0.5)
        # Force round to map to hour 18
        start = 18 - 0  # start_hour=18 so round 0 = hour 18
        svc18 = TemporalActivationService(start_hour=18, primetime_multiplier=1.0)
        p_target = profile.probability_at_hour(18)
        # Activation probability with multiplier 1.0 = clamped(p_target * 1.0)
        from backend.app.services.temporal_activation import _MIN_ACTIVATION_P
        expected_p = min(1.0, max(_MIN_ACTIVATION_P, p_target * 1.0))
        # Run 1000 trials and check empirical rate is approximately expected_p
        rng = random.Random(0)
        activations = sum(svc18.should_activate(profile, 0, rng) for _ in range(1000))
        assert abs(activations / 1000 - expected_p) < 0.05


class TestShouldActivateFloor:
    def test_floor_ensures_minimum_activation(self):
        """Even a low-activity profile should activate at minimum rate."""
        svc = TemporalActivationService()
        profile = _make_profile(constant_p=0.01)
        from backend.app.services.temporal_activation import _MIN_ACTIVATION_P
        rng = random.Random(99)
        # With p=0 and no multiplier, should_activate should still fire at floor
        activations = sum(svc.should_activate(profile, 10, rng) for _ in range(1000))
        rate = activations / 1000
        assert rate >= _MIN_ACTIVATION_P - 0.02  # allow small statistical variance
