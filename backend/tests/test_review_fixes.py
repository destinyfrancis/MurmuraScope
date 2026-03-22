"""Tests for deep review fixes: TDMI permutation, risk appetite, Brier baseline.

Covers:
  - TDMI permutation null-model threshold calibration
  - Risk appetite sigmoid steepness softening (-12 → -6)
  - Brier baseline using dataset prevalence instead of hardcoded 0.25
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# 1. TDMI Permutation Null-Model
# ---------------------------------------------------------------------------


class TestTDMIPermutation:
    """Test the permutation null-model for TDMI emergence detection."""

    def test_permutation_threshold_returns_float(self) -> None:
        """With ≥3 valid pairs, permutation threshold should be a float."""
        from backend.app.services.emergence_metrics import _permutation_threshold

        rng = np.random.RandomState(42)
        pairs = [
            (rng.randn(50), rng.randn(50))
            for _ in range(5)
        ]
        threshold = _permutation_threshold(pairs, np)
        assert threshold is not None
        assert isinstance(threshold, float)
        assert threshold > 0

    def test_permutation_threshold_none_with_few_pairs(self) -> None:
        """With < 3 pairs, should return None (insufficient for null distribution)."""
        from backend.app.services.emergence_metrics import _permutation_threshold

        pairs = [(np.array([1.0, 2.0]), np.array([2.0, 3.0]))]
        threshold = _permutation_threshold(pairs, np)
        assert threshold is None

    def test_permutation_threshold_none_with_empty(self) -> None:
        from backend.app.services.emergence_metrics import _permutation_threshold

        threshold = _permutation_threshold([], np)
        assert threshold is None

    def test_shuffled_data_has_lower_mi_than_structured(self) -> None:
        """Structured temporal data should have higher MI than shuffled null."""
        from backend.app.services.emergence_metrics import (
            _histogram_mi,
            _permutation_threshold,
        )

        # Create strongly correlated pairs (y = x + small noise)
        rng = np.random.RandomState(42)
        x = rng.randn(100)
        y = x + rng.randn(100) * 0.1  # high MI

        real_mi = _histogram_mi(x, y)
        pairs = [(x, y)] * 3  # need ≥3 for permutation
        null_threshold = _permutation_threshold(pairs, np)

        assert null_threshold is not None
        assert real_mi > null_threshold, (
            f"Real MI ({real_mi:.4f}) should exceed null threshold ({null_threshold:.4f})"
        )

    def test_permutation_threshold_has_floor(self) -> None:
        """Threshold should be at least _EMERGENCE_THRESHOLD * 0.5."""
        from backend.app.services.emergence_metrics import (
            _EMERGENCE_THRESHOLD,
            _permutation_threshold,
        )

        # Uniform data → near-zero null MI, but floor should apply
        rng = np.random.RandomState(42)
        pairs = [
            (rng.uniform(0, 1, size=50), rng.uniform(0, 1, size=50))
            for _ in range(5)
        ]
        threshold = _permutation_threshold(pairs, np)
        assert threshold is not None
        assert threshold >= _EMERGENCE_THRESHOLD * 0.5

    def test_permutation_is_deterministic(self) -> None:
        """Same input → same threshold (fixed seed=42)."""
        from backend.app.services.emergence_metrics import _permutation_threshold

        rng = np.random.RandomState(123)
        pairs = [(rng.randn(60), rng.randn(60)) for _ in range(4)]

        t1 = _permutation_threshold(pairs, np)
        t2 = _permutation_threshold(pairs, np)
        assert t1 == t2


# ---------------------------------------------------------------------------
# 2. Risk Appetite Steepness
# ---------------------------------------------------------------------------


class TestRiskAppetiteSteepness:
    """Test that risk appetite uses the softened steepness (-6 instead of -12)."""

    def test_mid_arousal_near_half(self) -> None:
        """At arousal=0.5, amplifier should be exactly 0.5 (regardless of steepness)."""
        from backend.app.services.cognitive_agent_engine import _compute_risk_appetite

        result = _compute_risk_appetite({"valence": 0.0, "arousal": 0.5})
        assert abs(result - 0.5) < 0.01

    def test_smooth_gradient_not_binary(self) -> None:
        """With steepness=-6, arousal=0.3 should give a meaningfully different
        amplifier than arousal=0.7 (not a quasi-step function)."""
        from backend.app.services.cognitive_agent_engine import _compute_risk_appetite

        low = _compute_risk_appetite({"valence": 0.8, "arousal": 0.3})
        mid = _compute_risk_appetite({"valence": 0.8, "arousal": 0.5})
        high = _compute_risk_appetite({"valence": 0.8, "arousal": 0.7})

        # With -6 steepness, the gradient should be smoother
        # Check that mid is meaningfully between low and high
        assert low < mid < high
        # The gap between low and mid should be reasonable (not near-zero)
        gap_low_mid = mid - low
        gap_mid_high = high - mid
        # With -6 steepness, both gaps should be substantial
        assert gap_low_mid > 0.03, f"Low→mid gap too small: {gap_low_mid}"
        assert gap_mid_high > 0.03, f"Mid→high gap too small: {gap_mid_high}"

    def test_negative_valence_cautious(self) -> None:
        """High arousal + negative valence → cautious (< 0.5)."""
        from backend.app.services.cognitive_agent_engine import _compute_risk_appetite

        result = _compute_risk_appetite({"valence": -0.8, "arousal": 0.9})
        assert result < 0.4

    def test_positive_valence_bold(self) -> None:
        """High arousal + positive valence → bold (> 0.5)."""
        from backend.app.services.cognitive_agent_engine import _compute_risk_appetite

        result = _compute_risk_appetite({"valence": 0.8, "arousal": 0.9})
        assert result > 0.6

    def test_bounded_output(self) -> None:
        """Output always in [0.1, 0.9]."""
        from backend.app.services.cognitive_agent_engine import _compute_risk_appetite

        for v in [-1.0, -0.5, 0.0, 0.5, 1.0]:
            for a in [0.0, 0.3, 0.5, 0.7, 1.0]:
                result = _compute_risk_appetite({"valence": v, "arousal": a})
                assert 0.1 <= result <= 0.9, f"Out of bounds: v={v}, a={a} → {result}"


# ---------------------------------------------------------------------------
# 3. Brier Baseline (Dataset Prevalence)
# ---------------------------------------------------------------------------


class TestBrierBaseline:
    """Test that Brier skill score uses climatological baseline."""

    def test_climatological_brier_balanced(self) -> None:
        """50/50 base rate → BS_clim = 0.25."""
        from backend.app.services.validation_reporter import _climatological_brier

        assert abs(_climatological_brier(0.5) - 0.25) < 1e-9

    def test_climatological_brier_skewed(self) -> None:
        """70/30 base rate → BS_clim = 0.7 × 0.3 = 0.21."""
        from backend.app.services.validation_reporter import _climatological_brier

        assert abs(_climatological_brier(0.7) - 0.21) < 1e-9

    def test_climatological_brier_extreme_clamped(self) -> None:
        """Extreme base rates (0, 1) are clamped to prevent division by zero."""
        from backend.app.services.validation_reporter import _climatological_brier

        # base_rate=0.0 clamped to 0.01 → 0.01 * 0.99 ≈ 0.0099
        result = _climatological_brier(0.0)
        assert result > 0.0
        assert result < 0.02

    def test_score_metric_uses_base_rate(self) -> None:
        """_score_metric should use base_rate from ValidationResult."""
        from backend.app.services.validation_reporter import _score_metric
        from backend.app.services.retrospective_validator import ValidationResult

        # Create a result with 70% base rate (imbalanced dataset)
        result = ValidationResult(
            metric="test",
            directional_accuracy=0.7,
            pearson_r=0.5,
            mape=0.1,
            brier_score=0.15,
            timing_offset_quarters=0,
            n_observations=20,
            period_start="2020-Q1",
            period_end="2023-Q4",
            base_rate=0.7,  # 70% of observations are "up"
        )
        score_70 = _score_metric(result)

        # Same result but with balanced base rate
        from dataclasses import replace

        result_50 = replace(result, base_rate=0.5)
        score_50 = _score_metric(result_50)

        # With 70% base rate, BS_clim=0.21 is lower than 0.25,
        # so the same BS=0.15 gives a WORSE skill score against the tighter baseline
        assert score_70 < score_50, (
            f"Score with 70% base rate ({score_70:.4f}) should be lower "
            f"than with 50% ({score_50:.4f}) because climatological baseline is tighter"
        )

    def test_validation_result_has_base_rate(self) -> None:
        """ValidationResult should have base_rate field with default 0.5."""
        from backend.app.services.retrospective_validator import ValidationResult

        r = ValidationResult(
            metric="test",
            directional_accuracy=0.5,
            pearson_r=0.0,
            mape=0.5,
            timing_offset_quarters=0,
            n_observations=10,
            period_start="2020-Q1",
            period_end="2020-Q4",
        )
        assert r.base_rate == 0.5  # default
