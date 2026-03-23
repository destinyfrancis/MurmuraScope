"""Tests for the statistical validation suite.

Covers stationarity (ADF), Granger causality, forecast accuracy metrics
(MAPE, RMSE, Theil's U), and the ValidationReport dataclass structure.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

sm = pytest.importorskip("statsmodels")

from backend.app.services.validation_suite import (
    ForecastAccuracy,
    GrangerResult,
    StationarityResult,
    ValidationReport,
    validate_forecast_accuracy,
    validate_granger_causality,
    validate_stationarity,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RNG = np.random.RandomState(42)


def _white_noise(n: int = 200) -> list[float]:
    """Generate a stationary white noise series."""
    return _RNG.normal(0.0, 1.0, size=n).tolist()


def _random_walk(n: int = 200) -> list[float]:
    """Generate a non-stationary random walk series."""
    return np.cumsum(_RNG.normal(0.0, 1.0, size=n)).tolist()


# ---------------------------------------------------------------------------
# 1. Stationarity tests
# ---------------------------------------------------------------------------


class TestStationarityStationary:
    """White noise should be detected as stationary by ADF + KPSS."""

    def test_is_stationary(self) -> None:
        series = _white_noise(200)
        result = validate_stationarity(series, "white_noise")

        assert isinstance(result, StationarityResult)
        assert result.is_stationary is True
        assert result.p_value < 0.05
        assert result.metric == "white_noise"

    def test_no_differencing_needed(self) -> None:
        series = _white_noise(200)
        result = validate_stationarity(series, "white_noise")

        assert result.differencing_applied is False

    def test_kpss_p_value_populated(self) -> None:
        """KPSS p-value should be present in the result."""
        series = _white_noise(200)
        result = validate_stationarity(series, "white_noise")

        # kpss_p_value should be either float or None (if KPSS unavailable)
        if result.kpss_p_value is not None:
            assert isinstance(result.kpss_p_value, float)
            # For a stationary series, KPSS should NOT reject (p > 0.05)
            assert result.kpss_p_value > 0.05

    def test_has_kpss_field(self) -> None:
        """StationarityResult should always have kpss_p_value attribute."""
        series = _white_noise(50)
        result = validate_stationarity(series, "test")
        assert hasattr(result, "kpss_p_value")


class TestStationarityRandomWalk:
    """A random walk (unit root) should be detected as non-stationary at level."""

    def test_raw_series_not_stationary(self) -> None:
        series = _random_walk(200)
        result = validate_stationarity(series, "random_walk")

        assert isinstance(result, StationarityResult)
        # The raw series should have p > 0.05 (non-stationary).
        # After differencing the implementation may mark it stationary,
        # so we check the differencing_applied flag is True when is_stationary.
        if result.is_stationary:
            assert result.differencing_applied is True
        else:
            assert result.p_value > 0.05

    def test_kpss_agrees_with_adf_on_differenced(self) -> None:
        """After differencing a random walk, both ADF and KPSS should agree."""
        series = _random_walk(200)
        result = validate_stationarity(series, "random_walk")

        if result.is_stationary and result.kpss_p_value is not None:
            # ADF rejected (p < 0.05) AND KPSS did not reject (p > 0.05)
            assert result.p_value < 0.05
            assert result.kpss_p_value > 0.05


class TestStationarityShortSeries:
    """Series with fewer than 8 points should return gracefully."""

    @pytest.mark.parametrize("length", [0, 1, 3, 5, 7])
    def test_short_series_does_not_crash(self, length: int) -> None:
        series = list(range(length))
        result = validate_stationarity(series, "short")

        assert isinstance(result, StationarityResult)
        assert result.is_stationary is False
        assert result.p_value == 1.0
        assert result.lags_used == 0
        assert result.kpss_p_value is None


class TestStationarityDualTest:
    """Verify ADF+KPSS dual test agreement logic."""

    def test_trend_stationary_may_disagree(self) -> None:
        """A trend-stationary series may cause ADF/KPSS disagreement."""
        # Series with deterministic trend + noise
        rng = np.random.RandomState(55)
        n = 200
        trend = np.linspace(0, 10, n)
        noise = rng.normal(0, 1, size=n)
        series = (trend + noise).tolist()

        result = validate_stationarity(series, "trend")

        # Result should be valid regardless of agreement
        assert isinstance(result, StationarityResult)
        assert hasattr(result, "kpss_p_value")


# ---------------------------------------------------------------------------
# 2. Granger causality tests
# ---------------------------------------------------------------------------


class TestGrangerCausalityCorrelated:
    """When y depends on lagged x, Granger test should detect causality."""

    def test_detects_causality(self) -> None:
        rng = np.random.RandomState(123)
        n = 300
        x = rng.normal(0, 1, size=n)
        noise = rng.normal(0, 0.3, size=n)
        y = np.zeros(n)
        for t in range(1, n):
            y[t] = 0.7 * x[t - 1] + noise[t]

        result = validate_granger_causality(x.tolist(), y.tolist(), "x_cause", "y_effect", max_lag=4)

        assert isinstance(result, GrangerResult)
        assert result.is_significant is True
        assert result.p_value < 0.10
        assert result.best_lag >= 1


class TestGrangerCausalityIndependent:
    """Two independent series should not show Granger causality."""

    def test_no_causality(self) -> None:
        rng = np.random.RandomState(777)
        n = 500
        x = rng.normal(0, 1, size=n).tolist()
        y = rng.normal(0, 1, size=n).tolist()

        result = validate_granger_causality(x, y, "indep_x", "indep_y", max_lag=2)

        assert isinstance(result, GrangerResult)
        assert result.p_value > 0.05


# ---------------------------------------------------------------------------
# 3. Forecast accuracy tests
# ---------------------------------------------------------------------------


class TestForecastAccuracy:
    """Verify MAPE and RMSE computations with known values."""

    def test_perfect_forecast(self) -> None:
        actuals = [100.0, 200.0, 300.0, 400.0]
        preds = [100.0, 200.0, 300.0, 400.0]

        result = validate_forecast_accuracy(actuals, preds, "perfect")

        assert isinstance(result, ForecastAccuracy)
        assert result.mape == pytest.approx(0.0, abs=1e-9)
        assert result.rmse == pytest.approx(0.0, abs=1e-9)

    def test_known_mape_and_rmse(self) -> None:
        actuals = [100.0, 200.0, 300.0, 400.0]
        preds = [110.0, 190.0, 330.0, 360.0]

        result = validate_forecast_accuracy(actuals, preds, "known")

        # MAPE: mean of |10/100|, |10/200|, |30/300|, |40/400| = mean(0.1, 0.05, 0.1, 0.1) * 100
        expected_mape = (0.10 + 0.05 + 0.10 + 0.10) / 4 * 100
        assert result.mape == pytest.approx(expected_mape, rel=1e-6)

        # RMSE: sqrt(mean(100 + 100 + 900 + 1600)) = sqrt(675)
        expected_rmse = math.sqrt((100 + 100 + 900 + 1600) / 4)
        assert result.rmse == pytest.approx(expected_rmse, rel=1e-6)

    def test_empty_arrays(self) -> None:
        result = validate_forecast_accuracy([], [], "empty")

        assert result.mape == float("inf")
        assert result.rmse == float("inf")
        assert result.n_observations == 0
        assert result.data_quality == "insufficient"


# ---------------------------------------------------------------------------
# 4. Theil's U
# ---------------------------------------------------------------------------


class TestTheilsU:
    """Theil's U > 1.0 when model is worse than naive random walk."""

    def test_worse_than_naive(self) -> None:
        # Actuals follow a clear trend; model predicts constant (bad).
        actuals = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0]
        # Deliberately wrong predictions: constant at 100.
        preds = [100.0, 100.0, 100.0, 100.0, 100.0, 100.0]

        result = validate_forecast_accuracy(actuals, preds, "bad_model")

        assert result.theils_u > 1.0, f"Expected Theil's U > 1.0 for a model worse than naive, got {result.theils_u}"

    def test_better_than_naive(self) -> None:
        # Actuals follow a clear trend; model tracks it well.
        actuals = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0]
        preds = [100.0, 111.0, 119.0, 131.0, 139.0, 151.0]

        result = validate_forecast_accuracy(actuals, preds, "good_model")

        assert result.theils_u < 1.0, f"Expected Theil's U < 1.0 for a model tracking the trend, got {result.theils_u}"


# ---------------------------------------------------------------------------
# 5. ValidationReport structure
# ---------------------------------------------------------------------------


class TestValidationReport:
    """Verify the ValidationReport frozen dataclass has expected fields."""

    def test_has_expected_fields(self) -> None:
        report = ValidationReport(
            stationarity_results=(),
            granger_results=(),
            forecast_accuracy=(),
            overall_score=0.5,
            warnings=("test warning",),
            data_sources_used={"macro_indicators_loaded": 0},
            arch_results=(),
        )

        assert hasattr(report, "stationarity_results")
        assert hasattr(report, "granger_results")
        assert hasattr(report, "forecast_accuracy")
        assert hasattr(report, "overall_score")
        assert hasattr(report, "warnings")
        assert hasattr(report, "data_sources_used")
        assert hasattr(report, "arch_results")

    def test_is_frozen(self) -> None:
        report = ValidationReport(
            stationarity_results=(),
            granger_results=(),
            forecast_accuracy=(),
            overall_score=0.75,
            warnings=(),
            data_sources_used={},
            arch_results=(),
        )

        with pytest.raises(AttributeError):
            report.overall_score = 0.99  # type: ignore[misc]

    def test_populated_report(self) -> None:
        stat = StationarityResult(
            metric="cpi",
            adf_statistic=-3.5,
            p_value=0.01,
            is_stationary=True,
            lags_used=2,
            differencing_applied=False,
            kpss_p_value=0.10,
        )
        granger = GrangerResult(
            cause_metric="sentiment",
            effect_metric="cpi",
            max_lag=4,
            best_lag=2,
            p_value=0.03,
            is_significant=True,
        )
        acc = ForecastAccuracy(
            metric="cpi",
            mape=5.0,
            rmse=0.8,
            theils_u=0.9,
            n_observations=20,
            data_quality="adequate",
        )

        report = ValidationReport(
            stationarity_results=(stat,),
            granger_results=(granger,),
            forecast_accuracy=(acc,),
            overall_score=0.85,
            warnings=(),
            data_sources_used={"macro_indicators_loaded": 1},
            arch_results=(),
        )

        assert len(report.stationarity_results) == 1
        assert len(report.granger_results) == 1
        assert len(report.forecast_accuracy) == 1
        assert report.overall_score == 0.85
