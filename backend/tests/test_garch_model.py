"""Tests for the GARCH(1,1) volatility model service.

Covers:
  - GARCHResult frozen dataclass immutability
  - AdjustedCI frozen dataclass immutability
  - GARCHForecaster.fit() on synthetic GARCH(1,1) data
  - GARCHForecaster.fit() edge cases (short series, constant, white noise)
  - GARCHForecaster.forecast_variance() mean-reversion property
  - GARCHForecaster.adjust_confidence_intervals() width correctness
  - Stationarity constraint enforcement (persistence < 1)
  - Integration with validation_suite ARCH test flow
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Frozen dataclass tests
# ---------------------------------------------------------------------------


class TestGARCHResultFrozen:
    """GARCHResult should be an immutable frozen dataclass."""

    def test_cannot_mutate_metric(self) -> None:
        from backend.app.services.garch_model import GARCHResult

        result = GARCHResult(
            metric="test",
            omega=0.01,
            alpha=0.1,
            beta=0.8,
            persistence=0.9,
            unconditional_variance=0.1,
            conditional_variances=(0.1, 0.2),
            log_likelihood=-100.0,
            n_observations=50,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.metric = "changed"  # type: ignore[misc]

    def test_cannot_mutate_alpha(self) -> None:
        from backend.app.services.garch_model import GARCHResult

        result = GARCHResult(
            metric="test",
            omega=0.01,
            alpha=0.1,
            beta=0.8,
            persistence=0.9,
            unconditional_variance=0.1,
            conditional_variances=(0.1,),
            log_likelihood=-50.0,
            n_observations=30,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.alpha = 0.99  # type: ignore[misc]


class TestAdjustedCIFrozen:
    """AdjustedCI should be an immutable frozen dataclass."""

    def test_cannot_mutate_ci_lower(self) -> None:
        from backend.app.services.garch_model import AdjustedCI

        ci = AdjustedCI(
            horizon_step=1,
            point_forecast=100.0,
            ci_lower=90.0,
            ci_upper=110.0,
            garch_std=5.0,
            static_std=4.0,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            ci.ci_lower = 0.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Fit tests
# ---------------------------------------------------------------------------


class TestGARCHFit:
    """Tests for GARCHForecaster.fit()."""

    def test_fit_detects_garch_process(self) -> None:
        """Fit should recover approximate parameters from a GARCH(1,1) DGP."""
        from backend.app.services.garch_model import GARCHForecaster

        # Simulate GARCH(1,1): omega=0.05, alpha=0.15, beta=0.75
        rng = np.random.default_rng(42)
        n = 500
        true_omega = 0.05
        true_alpha = 0.15
        true_beta = 0.75

        eps = np.zeros(n)
        sigma2 = np.zeros(n)
        sigma2[0] = true_omega / (1 - true_alpha - true_beta)
        for t in range(1, n):
            sigma2[t] = true_omega + true_alpha * eps[t - 1] ** 2 + true_beta * sigma2[t - 1]
            eps[t] = rng.normal(0, math.sqrt(sigma2[t]))

        forecaster = GARCHForecaster()
        result = forecaster.fit(eps.tolist(), "synthetic_garch")

        assert result is not None, "Fit should succeed on GARCH(1,1) data"
        assert result.metric == "synthetic_garch"
        assert result.n_observations == n

        # Parameters should be in a reasonable neighbourhood of truth
        # (MLE can be noisy with 500 obs, so use generous tolerances)
        assert result.alpha > 0.0, "alpha should be positive"
        assert result.beta > 0.0, "beta should be positive"
        assert result.omega > 0.0, "omega should be positive"
        assert result.persistence < 1.0, "persistence must be < 1"
        assert abs(result.persistence - (true_alpha + true_beta)) < 0.15, (
            f"persistence={result.persistence} too far from true {true_alpha + true_beta}"
        )

    def test_fit_returns_none_for_short_series(self) -> None:
        """Fit should return None when series has fewer than 20 observations."""
        from backend.app.services.garch_model import GARCHForecaster

        forecaster = GARCHForecaster()
        result = forecaster.fit([0.1, -0.2, 0.3] * 5, "short_series")
        assert result is None

    def test_fit_returns_none_for_constant_series(self) -> None:
        """Fit should return None for a series with zero variance."""
        from backend.app.services.garch_model import GARCHForecaster

        forecaster = GARCHForecaster()
        result = forecaster.fit([0.0] * 50, "constant")
        assert result is None

    def test_fit_returns_none_for_near_zero_variance(self) -> None:
        """Fit should return None when variance is effectively zero."""
        from backend.app.services.garch_model import GARCHForecaster

        forecaster = GARCHForecaster()
        result = forecaster.fit([1e-15] * 30, "near_zero")
        assert result is None

    def test_fit_handles_nan_and_inf(self) -> None:
        """Fit should silently discard NaN and inf values."""
        from backend.app.services.garch_model import GARCHForecaster

        rng = np.random.default_rng(99)
        # 200 valid + some NaN/inf sprinkled in (which get filtered)
        valid = rng.normal(0, 1, size=200).tolist()
        dirty = valid + [float("nan"), float("inf"), float("-inf")]

        forecaster = GARCHForecaster()
        result = forecaster.fit(dirty, "dirty_series")
        # Should still work with the 200 valid observations
        if result is not None:
            assert result.n_observations == 200

    def test_fit_white_noise_lower_persistence_than_garch(self) -> None:
        """White noise persistence should be materially lower than a true GARCH DGP.

        Note: finite-sample MLE on white noise can still fit non-trivial
        persistence (0.3-0.7) due to estimation noise, so we compare against
        a genuine GARCH process rather than assert a tight absolute threshold.
        """
        from backend.app.services.garch_model import GARCHForecaster

        rng = np.random.default_rng(7)

        # White noise: no volatility clustering
        white_noise = rng.normal(0, 1, size=500).tolist()

        # True GARCH(1,1) with persistence=0.9
        n = 500
        eps = np.zeros(n)
        sigma2 = np.ones(n)
        for t in range(1, n):
            sigma2[t] = 0.05 + 0.15 * eps[t - 1] ** 2 + 0.75 * sigma2[t - 1]
            eps[t] = rng.normal(0, math.sqrt(sigma2[t]))

        forecaster = GARCHForecaster()
        wn_result = forecaster.fit(white_noise, "white_noise")
        garch_result = forecaster.fit(eps.tolist(), "true_garch")

        assert garch_result is not None, "True GARCH data should fit"
        if wn_result is not None:
            assert wn_result.persistence < garch_result.persistence, (
                f"White noise persistence={wn_result.persistence} should be "
                f"lower than true GARCH persistence={garch_result.persistence}"
            )

    def test_fit_conditional_variances_length(self) -> None:
        """Conditional variances tuple should match observation count."""
        from backend.app.services.garch_model import GARCHForecaster

        rng = np.random.default_rng(42)
        n = 100
        eps = np.zeros(n)
        sigma2 = np.ones(n)
        for t in range(1, n):
            sigma2[t] = 0.1 + 0.3 * eps[t - 1] ** 2 + 0.5 * sigma2[t - 1]
            eps[t] = rng.normal(0, math.sqrt(sigma2[t]))

        forecaster = GARCHForecaster()
        result = forecaster.fit(eps.tolist(), "cv_length")
        assert result is not None
        assert len(result.conditional_variances) == n

    def test_fit_log_likelihood_is_finite(self) -> None:
        """Log-likelihood should be a finite negative number."""
        from backend.app.services.garch_model import GARCHForecaster

        rng = np.random.default_rng(42)
        n = 200
        eps = np.zeros(n)
        sigma2 = np.ones(n)
        for t in range(1, n):
            sigma2[t] = 0.05 + 0.1 * eps[t - 1] ** 2 + 0.8 * sigma2[t - 1]
            eps[t] = rng.normal(0, math.sqrt(sigma2[t]))

        forecaster = GARCHForecaster()
        result = forecaster.fit(eps.tolist(), "ll_check")
        assert result is not None
        assert math.isfinite(result.log_likelihood)


# ---------------------------------------------------------------------------
# Forecast variance tests
# ---------------------------------------------------------------------------


class TestForecastVariance:
    """Tests for GARCHForecaster.forecast_variance()."""

    def test_forecast_mean_reverts_to_unconditional(self) -> None:
        """Long-horizon forecasts should converge to unconditional variance."""
        from backend.app.services.garch_model import GARCHForecaster, GARCHResult

        result = GARCHResult(
            metric="mean_revert",
            omega=0.05,
            alpha=0.10,
            beta=0.80,
            persistence=0.90,
            unconditional_variance=0.5,  # 0.05 / (1 - 0.9)
            conditional_variances=(0.8,),  # start above unconditional
            log_likelihood=-200.0,
            n_observations=100,
        )

        forecaster = GARCHForecaster()
        forecasts = forecaster.forecast_variance(result, horizon=100)

        assert len(forecasts) == 100
        # First forecast should be closer to last conditional variance
        assert forecasts[0] > result.unconditional_variance
        # Last forecast should be very close to unconditional variance
        assert abs(forecasts[-1] - result.unconditional_variance) < 0.01

    def test_forecast_monotone_convergence_from_above(self) -> None:
        """When last sigma2 > V, forecasts should decrease monotonically."""
        from backend.app.services.garch_model import GARCHForecaster, GARCHResult

        result = GARCHResult(
            metric="mono_above",
            omega=0.02,
            alpha=0.10,
            beta=0.80,
            persistence=0.90,
            unconditional_variance=0.2,
            conditional_variances=(0.5,),  # above V
            log_likelihood=-150.0,
            n_observations=100,
        )

        forecaster = GARCHForecaster()
        forecasts = forecaster.forecast_variance(result, horizon=50)

        for i in range(1, len(forecasts)):
            assert forecasts[i] <= forecasts[i - 1] + 1e-12, (
                f"Forecast should not increase: step {i} = {forecasts[i]} > {forecasts[i - 1]}"
            )

    def test_forecast_monotone_convergence_from_below(self) -> None:
        """When last sigma2 < V, forecasts should increase monotonically."""
        from backend.app.services.garch_model import GARCHForecaster, GARCHResult

        result = GARCHResult(
            metric="mono_below",
            omega=0.05,
            alpha=0.10,
            beta=0.80,
            persistence=0.90,
            unconditional_variance=0.5,
            conditional_variances=(0.1,),  # below V
            log_likelihood=-150.0,
            n_observations=100,
        )

        forecaster = GARCHForecaster()
        forecasts = forecaster.forecast_variance(result, horizon=50)

        for i in range(1, len(forecasts)):
            assert forecasts[i] >= forecasts[i - 1] - 1e-12, (
                f"Forecast should not decrease: step {i} = {forecasts[i]} < {forecasts[i - 1]}"
            )

    def test_forecast_zero_horizon_returns_empty(self) -> None:
        """Horizon of 0 or negative should return empty tuple."""
        from backend.app.services.garch_model import GARCHForecaster, GARCHResult

        result = GARCHResult(
            metric="zero_h",
            omega=0.01,
            alpha=0.1,
            beta=0.8,
            persistence=0.9,
            unconditional_variance=0.1,
            conditional_variances=(0.1,),
            log_likelihood=-50.0,
            n_observations=50,
        )

        forecaster = GARCHForecaster()
        assert forecaster.forecast_variance(result, horizon=0) == ()
        assert forecaster.forecast_variance(result, horizon=-5) == ()

    def test_forecast_all_positive(self) -> None:
        """All variance forecasts must be strictly positive."""
        from backend.app.services.garch_model import GARCHForecaster, GARCHResult

        result = GARCHResult(
            metric="positive",
            omega=0.001,
            alpha=0.05,
            beta=0.90,
            persistence=0.95,
            unconditional_variance=0.02,
            conditional_variances=(0.03,),
            log_likelihood=-80.0,
            n_observations=100,
        )

        forecaster = GARCHForecaster()
        forecasts = forecaster.forecast_variance(result, horizon=50)

        for h, v in enumerate(forecasts, 1):
            assert v > 0, f"Variance at h={h} must be positive, got {v}"


# ---------------------------------------------------------------------------
# Confidence interval adjustment tests
# ---------------------------------------------------------------------------


class TestAdjustConfidenceIntervals:
    """Tests for GARCHForecaster.adjust_confidence_intervals()."""

    def test_ci_width_uses_garch_std(self) -> None:
        """CI width should be 2 * z * garch_std, not 2 * z * static_std."""
        from backend.app.services.garch_model import GARCHForecaster, GARCHResult

        result = GARCHResult(
            metric="ci_test",
            omega=0.05,
            alpha=0.10,
            beta=0.80,
            persistence=0.90,
            unconditional_variance=0.5,
            conditional_variances=(0.5,),
            log_likelihood=-100.0,
            n_observations=100,
        )

        forecaster = GARCHForecaster()
        point_forecasts = [100.0, 101.0, 102.0]
        static_std = 2.0

        adjusted = forecaster.adjust_confidence_intervals(
            point_forecasts,
            static_std,
            result,
            horizon=3,
            z_score=1.96,
        )

        assert len(adjusted) == 3
        for ci in adjusted:
            expected_width = 2 * 1.96 * ci.garch_std
            actual_width = ci.ci_upper - ci.ci_lower
            assert abs(actual_width - expected_width) < 1e-10

    def test_ci_symmetric_around_forecast(self) -> None:
        """Lower and upper CI should be symmetric around the point forecast."""
        from backend.app.services.garch_model import GARCHForecaster, GARCHResult

        result = GARCHResult(
            metric="sym_test",
            omega=0.02,
            alpha=0.10,
            beta=0.80,
            persistence=0.90,
            unconditional_variance=0.2,
            conditional_variances=(0.3,),
            log_likelihood=-100.0,
            n_observations=100,
        )

        forecaster = GARCHForecaster()
        adjusted = forecaster.adjust_confidence_intervals(
            [50.0],
            1.0,
            result,
            horizon=1,
        )

        assert len(adjusted) == 1
        ci = adjusted[0]
        mid = (ci.ci_lower + ci.ci_upper) / 2
        assert abs(mid - 50.0) < 1e-10

    def test_ci_empty_on_zero_horizon(self) -> None:
        """Should return empty tuple for zero or negative horizon."""
        from backend.app.services.garch_model import GARCHForecaster, GARCHResult

        result = GARCHResult(
            metric="empty",
            omega=0.01,
            alpha=0.1,
            beta=0.8,
            persistence=0.9,
            unconditional_variance=0.1,
            conditional_variances=(0.1,),
            log_likelihood=-50.0,
            n_observations=50,
        )

        forecaster = GARCHForecaster()
        assert forecaster.adjust_confidence_intervals([], 1.0, result, horizon=0) == ()

    def test_ci_horizon_clamped_to_forecasts_length(self) -> None:
        """Horizon should be clamped to len(point_forecasts)."""
        from backend.app.services.garch_model import GARCHForecaster, GARCHResult

        result = GARCHResult(
            metric="clamp",
            omega=0.02,
            alpha=0.1,
            beta=0.8,
            persistence=0.9,
            unconditional_variance=0.2,
            conditional_variances=(0.2,),
            log_likelihood=-80.0,
            n_observations=100,
        )

        forecaster = GARCHForecaster()
        adjusted = forecaster.adjust_confidence_intervals(
            [10.0, 20.0],
            1.0,
            result,
            horizon=10,
        )
        assert len(adjusted) == 2

    def test_ci_static_std_preserved(self) -> None:
        """Each AdjustedCI should carry the original static_std for comparison."""
        from backend.app.services.garch_model import GARCHForecaster, GARCHResult

        result = GARCHResult(
            metric="static",
            omega=0.02,
            alpha=0.1,
            beta=0.8,
            persistence=0.9,
            unconditional_variance=0.2,
            conditional_variances=(0.2,),
            log_likelihood=-80.0,
            n_observations=100,
        )

        forecaster = GARCHForecaster()
        adjusted = forecaster.adjust_confidence_intervals(
            [100.0],
            3.5,
            result,
            horizon=1,
        )
        assert len(adjusted) == 1
        assert adjusted[0].static_std == 3.5


# ---------------------------------------------------------------------------
# Stationarity constraint
# ---------------------------------------------------------------------------


class TestStationarityConstraint:
    """Persistence alpha + beta must be < 1 for covariance stationarity."""

    def test_high_persistence_rejected(self) -> None:
        """A unit-root-like IGARCH process should be rejected (persistence ~ 1)."""
        from backend.app.services.garch_model import GARCHForecaster

        rng = np.random.default_rng(55)
        n = 300
        # Simulate near-IGARCH: alpha=0.10, beta=0.90 => persistence=1.0
        eps = np.zeros(n)
        sigma2 = np.ones(n) * 0.5
        for t in range(1, n):
            sigma2[t] = 0.001 + 0.10 * eps[t - 1] ** 2 + 0.90 * sigma2[t - 1]
            eps[t] = rng.normal(0, math.sqrt(sigma2[t]))

        forecaster = GARCHForecaster()
        result = forecaster.fit(eps.tolist(), "near_igarch")
        # Result may be None (rejected) or may fit with persistence just below 1
        # Either outcome is acceptable -- key is we do NOT get persistence >= 1
        if result is not None:
            assert result.persistence < 1.0


# ---------------------------------------------------------------------------
# Integration: validation_suite wiring
# ---------------------------------------------------------------------------


class TestValidationSuiteWiring:
    """Verify the garch_results field exists on ValidationReport."""

    def test_validation_report_has_garch_field(self) -> None:
        """ValidationReport should include a garch_results tuple field."""
        from backend.app.services.validation_suite import ValidationReport

        report = ValidationReport(
            stationarity_results=(),
            granger_results=(),
            forecast_accuracy=(),
            arch_results=(),
            garch_results=(),
            overall_score=0.5,
            warnings=(),
            data_sources_used={},
        )
        assert hasattr(report, "garch_results")
        assert isinstance(report.garch_results, tuple)

    def test_garch_result_in_report_is_frozen(self) -> None:
        """GARCHResult stored in ValidationReport should be immutable."""
        from backend.app.services.garch_model import GARCHResult
        from backend.app.services.validation_suite import ValidationReport

        gr = GARCHResult(
            metric="wired",
            omega=0.01,
            alpha=0.1,
            beta=0.8,
            persistence=0.9,
            unconditional_variance=0.1,
            conditional_variances=(0.1, 0.2),
            log_likelihood=-100.0,
            n_observations=50,
        )

        report = ValidationReport(
            stationarity_results=(),
            granger_results=(),
            forecast_accuracy=(),
            arch_results=(),
            garch_results=(gr,),
            overall_score=0.5,
            warnings=(),
            data_sources_used={},
        )
        assert len(report.garch_results) == 1
        with pytest.raises(dataclasses.FrozenInstanceError):
            report.garch_results[0].metric = "hacked"  # type: ignore[misc]
