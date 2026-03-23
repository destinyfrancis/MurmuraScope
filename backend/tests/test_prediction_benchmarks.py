"""Tests for Workstream B — Prediction Benchmarks + Residual Tests.

Covers:
  - B1: Random Walk with Drift (#8) — drift value, CI widening, model_used
  - B2: CRPS metric (#8) — formula correctness, non-negativity, coverage_95
  - B3: ARCH/GARCH residual test (#10) — heteroscedasticity detection, frozen result
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# B1: Random Walk with Drift
# ---------------------------------------------------------------------------


class TestRWDrift:
    """Tests for the RW-drift naive forecaster."""

    def test_drift_value_correct(self) -> None:
        """Drift should equal the mean of first differences."""
        from backend.app.services.time_series_forecaster import TimeSeriesForecaster

        forecaster = TimeSeriesForecaster()
        # Simple linear series: 10, 12, 14, 16, 18, 20, 22, 24, 26, 28
        # Use hsi_level (no Q1/Q4 seasonal adjustments) to avoid adjustment noise
        history = [(f"2020-Q{(i % 4) + 1}", 10.0 + 2.0 * i) for i in range(10)]
        result = forecaster._forecast_naive("hsi_level", history, horizon=4)

        # All diffs = 2.0, so drift = 2.0
        last_val = history[-1][1]  # 28.0
        for h, pt in enumerate(result.points, start=1):
            expected = last_val + 2.0 * h
            assert abs(pt.value - expected) < 0.1, f"h={h}: expected ~{expected}, got {pt.value}"

    def test_ci_widens_with_horizon(self) -> None:
        """CI spread should grow proportionally to sqrt(h)."""
        from backend.app.services.time_series_forecaster import TimeSeriesForecaster

        forecaster = TimeSeriesForecaster()
        history = [(f"2020-Q{(i % 4) + 1}", 100.0 + float(i)) for i in range(12)]
        result = forecaster._forecast_naive("ccl_index", history, horizon=8)

        # 80% spread at h=1 vs h=4: ratio should be ~sqrt(4)/sqrt(1) = 2.0
        spread_1 = result.points[0].upper_80 - result.points[0].lower_80
        spread_4 = result.points[3].upper_80 - result.points[3].lower_80
        ratio = spread_4 / spread_1
        assert 1.8 < ratio < 2.2, f"Expected ratio ~2.0, got {ratio}"

    def test_model_used_is_rw_drift(self) -> None:
        """model_used should be 'rw_drift', not 'naive'."""
        from backend.app.services.time_series_forecaster import TimeSeriesForecaster

        forecaster = TimeSeriesForecaster()
        history = [(f"2020-Q{(i % 4) + 1}", 50.0 + float(i)) for i in range(10)]
        result = forecaster._forecast_naive("ccl_index", history, horizon=2)
        assert result.model_used == "rw_drift"


# ---------------------------------------------------------------------------
# B2: CRPS Metric
# ---------------------------------------------------------------------------


class TestCRPS:
    """Tests for the CRPS computation and coverage_95 field."""

    def test_crps_known_values(self) -> None:
        """CRPS for perfect prediction (actual=mean, any sigma) should be sigma * (1/sqrt(pi) - ... )."""
        from backend.app.services.backtester import _compute_crps

        # When z=0: CRPS = sigma * (0 + 2*phi(0) - 1/sqrt(pi))
        #         = sigma * (2 * 0.3989... - 0.5642...) = sigma * 0.2336...
        actuals = np.array([5.0])
        means = np.array([5.0])
        stds = np.array([2.0])
        crps = _compute_crps(actuals, means, stds)
        expected = 2.0 * (2.0 * 0.3989422804014327 - 1.0 / math.sqrt(math.pi))
        assert abs(crps - expected) < 0.001, f"Expected ~{expected}, got {crps}"

    def test_crps_non_negative(self) -> None:
        """CRPS should always be non-negative."""
        from backend.app.services.backtester import _compute_crps

        rng = np.random.default_rng(42)
        actuals = rng.normal(0, 5, size=50)
        means = rng.normal(0, 5, size=50)
        stds = np.abs(rng.normal(1, 0.5, size=50)) + 0.1
        crps = _compute_crps(actuals, means, stds)
        assert crps >= 0.0, f"CRPS should be non-negative, got {crps}"

    def test_crps_empty(self) -> None:
        """CRPS of empty arrays should be 0.0."""
        from backend.app.services.backtester import _compute_crps

        crps = _compute_crps(np.array([]), np.array([]), np.array([]))
        assert crps == 0.0

    def test_coverage_95_field_exists(self) -> None:
        """BacktestResult should have a coverage_95 field."""
        from backend.app.services.backtester import BacktestResult

        result = BacktestResult(
            metric="test",
            train_start="2015-Q1",
            train_end="2022-Q4",
            test_start="2023-Q1",
            test_end="2024-Q4",
            mape=5.0,
            rmse=0.1,
            directional_accuracy=0.75,
            coverage_80=0.8,
            coverage_95=0.95,
            crps=0.5,
            theils_u=0.9,
            predictions=(),
            model_used="rw_drift",
        )
        assert hasattr(result, "coverage_95")
        assert 0.0 <= result.coverage_95 <= 1.0

    def test_coverage_95_in_range(self) -> None:
        """coverage_95 helper should return a value between 0 and 1."""
        from backend.app.services.backtester import _compute_coverage_95

        actuals = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        lower = np.array([0.5, 1.5, 2.5, 3.5, 4.5])
        upper = np.array([1.5, 2.5, 3.5, 4.5, 5.5])
        cov = _compute_coverage_95(actuals, lower, upper)
        assert 0.0 <= cov <= 1.0


# ---------------------------------------------------------------------------
# B3: ARCH / GARCH Residual Test
# ---------------------------------------------------------------------------


class TestARCH:
    """Tests for the ARCH LM test in validation_suite."""

    def test_arch_detects_heteroscedasticity(self) -> None:
        """ARCH test should detect effects in a GARCH-like series."""
        from backend.app.services.validation_suite import validate_arch_effects

        rng = np.random.default_rng(123)
        # Simulate GARCH(1,1)-like process
        n = 200
        e = np.zeros(n)
        sigma2 = np.ones(n)
        for t in range(1, n):
            sigma2[t] = 0.1 + 0.7 * e[t - 1] ** 2 + 0.2 * sigma2[t - 1]
            e[t] = rng.normal(0, math.sqrt(sigma2[t]))

        result = validate_arch_effects(e.tolist(), "garch_test", lags=4)
        assert result.has_arch_effects, f"ARCH test should detect effects in GARCH series, p={result.p_value}"

    def test_arch_no_effects_white_noise(self) -> None:
        """ARCH test should find no effects in white noise."""
        from backend.app.services.validation_suite import validate_arch_effects

        rng = np.random.default_rng(42)
        white_noise = rng.normal(0, 1, size=200).tolist()
        result = validate_arch_effects(white_noise, "white_noise", lags=4)
        # White noise should NOT have ARCH effects (p > 0.05 most of the time)
        assert not result.has_arch_effects, f"White noise should not have ARCH effects, p={result.p_value}"

    def test_arch_result_is_frozen(self) -> None:
        """ARCHTestResult should be a frozen dataclass."""
        from backend.app.services.validation_suite import ARCHTestResult

        result = ARCHTestResult(
            metric="test",
            lm_statistic=5.0,
            p_value=0.03,
            has_arch_effects=True,
            lags_tested=4,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.metric = "changed"  # type: ignore[misc]

    def test_validation_report_includes_arch(self) -> None:
        """ValidationReport should have an arch_results field."""
        from backend.app.services.validation_suite import ValidationReport

        report = ValidationReport(
            stationarity_results=(),
            granger_results=(),
            forecast_accuracy=(),
            arch_results=(),
            overall_score=0.5,
            warnings=(),
            data_sources_used={},
        )
        assert hasattr(report, "arch_results")
        assert isinstance(report.arch_results, tuple)

    def test_arch_p_value_valid_range(self) -> None:
        """ARCH test p-value should be between 0 and 1."""
        from backend.app.services.validation_suite import validate_arch_effects

        rng = np.random.default_rng(99)
        series = rng.normal(0, 2, size=100).tolist()
        result = validate_arch_effects(series, "range_test", lags=4)
        assert 0.0 <= result.p_value <= 1.0, f"p-value out of range: {result.p_value}"


# ---------------------------------------------------------------------------
# New tests: BH FDR, CRPS, RandomWalkDriftForecaster
# ---------------------------------------------------------------------------


class TestBenjaminiHochberg:
    """Tests for the Benjamini-Hochberg FDR correction in validation_suite."""

    def test_benjamini_hochberg_rejects_more_than_bonferroni(self) -> None:
        """BH should reject more hypotheses than Bonferroni for the same p-values."""
        from backend.app.services.validation_suite import _benjamini_hochberg

        # With 12 tests, Bonferroni threshold = 0.05/12 ≈ 0.0042
        # BH should reject the first few (0.001, 0.005 are borderline under Bonferroni)
        p_vals = [0.001, 0.005, 0.01, 0.03, 0.08, 0.15, 0.25, 0.4, 0.5, 0.6, 0.7, 0.9]
        rejects = _benjamini_hochberg(p_vals, alpha=0.05)
        assert sum(rejects) >= 3, f"BH should reject at least 3, got {sum(rejects)}"

    def test_benjamini_hochberg_empty(self) -> None:
        """BH on empty list returns empty list."""
        from backend.app.services.validation_suite import _benjamini_hochberg

        assert _benjamini_hochberg([], alpha=0.05) == []

    def test_benjamini_hochberg_all_significant(self) -> None:
        """All very small p-values should all be rejected."""
        from backend.app.services.validation_suite import _benjamini_hochberg

        p_vals = [0.0001, 0.0002, 0.0003]
        rejects = _benjamini_hochberg(p_vals, alpha=0.05)
        assert all(rejects), "All tiny p-values should be rejected"

    def test_benjamini_hochberg_none_significant(self) -> None:
        """Large p-values should not be rejected."""
        from backend.app.services.validation_suite import _benjamini_hochberg

        p_vals = [0.5, 0.6, 0.7, 0.8, 0.9]
        rejects = _benjamini_hochberg(p_vals, alpha=0.05)
        assert not any(rejects), "Large p-values should not be rejected"


class TestCRPSStandalone:
    """Tests for compute_crps in naive_forecaster."""

    def test_crps_perfect_forecast(self) -> None:
        """When actual == mean and std is small, CRPS should be small."""
        from backend.app.services.naive_forecaster import compute_crps

        crps = compute_crps(actual=5.0, mean=5.0, std=0.1)
        assert crps < 0.1, f"Perfect forecast CRPS should be small, got {crps}"

    def test_crps_poor_forecast(self) -> None:
        """When actual is far from mean with small std, CRPS should be large."""
        from backend.app.services.naive_forecaster import compute_crps

        crps = compute_crps(actual=10.0, mean=5.0, std=0.5)
        assert crps > 1.0, f"Poor forecast CRPS should be > 1, got {crps}"

    def test_crps_non_negative(self) -> None:
        """CRPS should always be non-negative."""
        from backend.app.services.naive_forecaster import compute_crps

        rng = np.random.default_rng(7)
        for _ in range(20):
            actual = float(rng.normal(0, 5))
            mean = float(rng.normal(0, 5))
            std = float(abs(rng.normal(1, 0.5)) + 0.1)
            crps = compute_crps(actual=actual, mean=mean, std=std)
            assert crps >= 0.0, f"CRPS should be non-negative, got {crps}"

    def test_crps_degenerate_std(self) -> None:
        """With std=0, CRPS should equal absolute error."""
        from backend.app.services.naive_forecaster import compute_crps

        crps = compute_crps(actual=7.0, mean=4.0, std=0.0)
        assert abs(crps - 3.0) < 1e-9, f"Expected 3.0, got {crps}"


class TestRandomWalkDriftForecaster:
    """Tests for RandomWalkDriftForecaster in naive_forecaster."""

    def test_random_walk_drift_forecast(self) -> None:
        """Drift=1.0 → predictions should be 6, 7, 8 for 3 steps."""
        from backend.app.services.naive_forecaster import RandomWalkDriftForecaster

        history = [1.0, 2.0, 3.0, 4.0, 5.0]
        forecaster = RandomWalkDriftForecaster()
        preds = forecaster.forecast(history, steps=3)
        assert len(preds) == 3
        assert abs(preds[0] - 6.0) < 0.01, f"Expected 6.0, got {preds[0]}"
        assert abs(preds[1] - 7.0) < 0.01, f"Expected 7.0, got {preds[1]}"
        assert abs(preds[2] - 8.0) < 0.01, f"Expected 8.0, got {preds[2]}"

    def test_random_walk_drift_single_point(self) -> None:
        """Single-point history → repeats last value (no drift available)."""
        from backend.app.services.naive_forecaster import RandomWalkDriftForecaster

        forecaster = RandomWalkDriftForecaster()
        preds = forecaster.forecast([42.0], steps=2)
        assert len(preds) == 2
        assert preds[0] == 42.0
        assert preds[1] == 42.0

    def test_random_walk_drift_empty_history(self) -> None:
        """Empty history → returns zeros."""
        from backend.app.services.naive_forecaster import RandomWalkDriftForecaster

        forecaster = RandomWalkDriftForecaster()
        preds = forecaster.forecast([], steps=3)
        assert preds == [0.0, 0.0, 0.0]

    def test_random_walk_drift_negative_drift(self) -> None:
        """Declining series → negative drift → predictions decrease."""
        from backend.app.services.naive_forecaster import RandomWalkDriftForecaster

        history = [10.0, 8.0, 6.0, 4.0, 2.0]
        forecaster = RandomWalkDriftForecaster()
        preds = forecaster.forecast(history, steps=3)
        assert preds[0] < 2.0, "Declining drift should predict below last value"
        assert preds[1] < preds[0], "Each step should decrease"
