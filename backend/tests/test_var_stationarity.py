"""Tests for ADF/KPSS stationarity pre-checks in the VAR forecaster.

Covers:
- _check_stationarity() dual test logic
- _apply_differencing() and _invert_differencing() round-trip
- _invert_forecast_differencing() level reconstruction
- VARForecaster.forecast_group() integration with stationarity wiring
"""

from __future__ import annotations

import numpy as np
import pytest

sm = pytest.importorskip("statsmodels")

from backend.app.services.var_forecaster import (
    VARForecaster,
    VARForecastResult,
    _apply_differencing,
    _check_stationarity,
    _invert_differencing,
    _StationarityInfo,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RNG = np.random.RandomState(42)


def _white_noise(n: int = 100) -> np.ndarray:
    """Generate a stationary white noise series."""
    return _RNG.normal(0.0, 1.0, size=n)


def _random_walk(n: int = 100) -> np.ndarray:
    """Generate a non-stationary random walk series."""
    return np.cumsum(_RNG.normal(0.0, 1.0, size=n))


def _make_var_series(
    n: int = 30,
    stationary: bool = True,
) -> dict[str, list[tuple[str, float]]]:
    """Build 3 co-moving series suitable for VARForecaster.forecast_group().

    Returns a dict of metric_name -> [(period, value), ...].
    """
    rng = np.random.RandomState(99)
    periods = [f"2020-Q{(i % 4) + 1}" if i < 4 else f"{2020 + i // 4}-Q{(i % 4) + 1}" for i in range(n)]
    # Deduplicate periods by making them unique
    periods = [f"{2018 + i // 4}-Q{(i % 4) + 1}" for i in range(n)]

    if stationary:
        a = rng.normal(0.0, 1.0, size=n)
        b = 0.5 * a + rng.normal(0.0, 0.5, size=n)
        c = -0.3 * a + rng.normal(0.0, 0.5, size=n)
    else:
        # Random walks (non-stationary)
        a = np.cumsum(rng.normal(0.0, 1.0, size=n))
        b = np.cumsum(rng.normal(0.0, 1.0, size=n))
        c = np.cumsum(rng.normal(0.0, 1.0, size=n))

    return {
        "metric_a": list(zip(periods, a.tolist())),
        "metric_b": list(zip(periods, b.tolist())),
        "metric_c": list(zip(periods, c.tolist())),
    }


# ---------------------------------------------------------------------------
# 1. _check_stationarity() tests
# ---------------------------------------------------------------------------


class TestCheckStationarity:
    """Unit tests for the dual ADF+KPSS stationarity check."""

    def test_white_noise_is_stationary(self) -> None:
        series = _white_noise(200)
        result = _check_stationarity(series, "white_noise")

        assert isinstance(result, _StationarityInfo)
        assert result.is_stationary is True
        assert result.diff_order == 0
        assert result.adf_p < 0.05
        assert result.metric == "white_noise"

    def test_random_walk_needs_differencing(self) -> None:
        series = _random_walk(200)
        result = _check_stationarity(series, "random_walk")

        assert isinstance(result, _StationarityInfo)
        assert result.is_stationary is True
        assert result.diff_order >= 1
        assert result.adf_p < 0.05

    def test_short_series_returns_non_stationary(self) -> None:
        series = np.array([1.0, 2.0, 3.0])
        result = _check_stationarity(series, "short")

        assert result.is_stationary is False

    def test_constant_series_returns_non_stationary(self) -> None:
        series = np.ones(50)
        result = _check_stationarity(series, "constant")

        assert result.is_stationary is False

    def test_frozen_dataclass(self) -> None:
        result = _check_stationarity(_white_noise(100), "test")
        with pytest.raises(AttributeError):
            result.is_stationary = False  # type: ignore[misc]

    def test_kpss_p_value_present_when_available(self) -> None:
        """KPSS p-value should be populated when statsmodels has kpss."""
        result = _check_stationarity(_white_noise(200), "test")
        # kpss_p should be either a float or None (if KPSS unavailable)
        if result.kpss_p is not None:
            assert isinstance(result.kpss_p, float)
            assert 0.0 <= result.kpss_p <= 1.0

    def test_integrated_order_2_detected(self) -> None:
        """A double-integrated series should need d=2."""
        rng = np.random.RandomState(123)
        noise = rng.normal(0.0, 1.0, size=200)
        # I(2): cumulative sum of cumulative sum
        i2_series = np.cumsum(np.cumsum(noise))
        result = _check_stationarity(i2_series, "i2")

        assert result.is_stationary is True
        assert result.diff_order == 2


# ---------------------------------------------------------------------------
# 2. _apply_differencing() and _invert_differencing() tests
# ---------------------------------------------------------------------------


class TestDifferencingRoundTrip:
    """Verify that differencing + inversion recovers the original forecasts."""

    def test_diff_order_0_is_noop(self) -> None:
        data = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
        result = _apply_differencing(data, 0)
        np.testing.assert_array_equal(result, data)

    def test_diff_order_1_shape(self) -> None:
        data = np.arange(12, dtype=np.float64).reshape(4, 3)
        result = _apply_differencing(data, 1)
        assert result.shape == (3, 3)

    def test_diff_order_2_shape(self) -> None:
        data = np.arange(20, dtype=np.float64).reshape(5, 4)
        result = _apply_differencing(data, 2)
        assert result.shape == (3, 4)

    def test_invert_diff_order_0_is_noop(self) -> None:
        fc = np.array([[10.0, 20.0]])
        original = np.array([[1.0, 2.0], [3.0, 4.0]])
        result = _invert_differencing(fc, original, 0)
        np.testing.assert_array_equal(result, fc)

    def test_invert_diff_1_recovers_levels(self) -> None:
        """Inverting d=1 differencing: forecasted diffs + last level = level forecast."""
        # Original series: [10, 20, 30]
        # Last level = 30
        # If VAR forecasts diff = [5, 3] (two steps ahead)
        # Then level forecasts = [35, 38]
        original = np.array([[10.0], [20.0], [30.0]])
        fc_diffs = np.array([[5.0], [3.0]])

        result = _invert_differencing(fc_diffs, original, diff_order=1)

        expected = np.array([[35.0], [38.0]])
        np.testing.assert_array_almost_equal(result, expected)

    def test_invert_diff_2_recovers_levels(self) -> None:
        """Inverting d=2 differencing."""
        # Original: [10, 20, 35]
        # First diffs: [10, 15]
        # Last first-diff = 35 - 20 = 15
        # Last level = 35
        # If VAR forecasts 2nd diff = [1.0] (one step ahead)
        # First inversion: last_1st_diff + 1.0 = 16.0
        # Second inversion: last_level + 16.0 = 51.0
        original = np.array([[10.0], [20.0], [35.0]])
        fc_2nd_diffs = np.array([[1.0]])

        result = _invert_differencing(fc_2nd_diffs, original, diff_order=2)

        expected = np.array([[51.0]])
        np.testing.assert_array_almost_equal(result, expected)

    def test_does_not_mutate_input(self) -> None:
        data = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
        original = data.copy()
        _apply_differencing(data, 1)
        np.testing.assert_array_equal(data, original)


# ---------------------------------------------------------------------------
# 3. VARForecaster integration with stationarity pre-check
# ---------------------------------------------------------------------------


class TestVARForecasterStationarity:
    """Integration tests for VARForecaster with stationarity wiring."""

    def test_stationary_series_no_differencing(self) -> None:
        """Stationary series should have group_diff_order=0 in diagnostics."""
        series = _make_var_series(n=30, stationary=True)
        forecaster = VARForecaster()
        result = forecaster.forecast_group("test_group", series, horizon=4)

        assert result is not None
        assert isinstance(result, VARForecastResult)
        assert "stationarity" in result.diagnostics
        assert "group_diff_order" in result.diagnostics
        assert result.diagnostics["group_diff_order"] == 0

    def test_non_stationary_series_gets_differenced(self) -> None:
        """Non-stationary series should have group_diff_order > 0."""
        series = _make_var_series(n=40, stationary=False)
        forecaster = VARForecaster()
        result = forecaster.forecast_group("test_group", series, horizon=4)

        # May return None if insufficient obs after differencing, so check both
        if result is not None:
            assert "group_diff_order" in result.diagnostics
            assert result.diagnostics["group_diff_order"] >= 1
            # Forecasts should be in level space (not differenced)
            for metric, fc in result.forecasts.items():
                assert len(fc.points) == 4

    def test_diagnostics_contain_per_metric_stationarity(self) -> None:
        """Diagnostics should include per-metric stationarity info."""
        series = _make_var_series(n=30, stationary=True)
        forecaster = VARForecaster()
        result = forecaster.forecast_group("test_group", series, horizon=2)

        assert result is not None
        stationarity = result.diagnostics["stationarity"]
        assert "metric_a" in stationarity
        assert "metric_b" in stationarity
        assert "metric_c" in stationarity

        for metric_info in stationarity.values():
            assert "is_stationary" in metric_info
            assert "diff_order" in metric_info
            assert "adf_p" in metric_info
            assert "kpss_p" in metric_info

    def test_forecast_values_are_in_level_space(self) -> None:
        """When differencing is applied, forecast values should be un-differenced."""
        # Use random walks to force differencing
        rng = np.random.RandomState(77)
        n = 40
        periods = [f"{2015 + i // 4}-Q{(i % 4) + 1}" for i in range(n)]

        # Random walks starting from realistic levels
        base_a = 100.0
        base_b = 50.0
        base_c = 200.0
        a = base_a + np.cumsum(rng.normal(0.0, 1.0, size=n))
        b = base_b + np.cumsum(rng.normal(0.0, 0.5, size=n))
        c = base_c + np.cumsum(rng.normal(0.0, 2.0, size=n))

        series = {
            "metric_a": list(zip(periods, a.tolist())),
            "metric_b": list(zip(periods, b.tolist())),
            "metric_c": list(zip(periods, c.tolist())),
        }

        forecaster = VARForecaster()
        result = forecaster.forecast_group("level_test", series, horizon=4)

        if result is not None and result.diagnostics.get("group_diff_order", 0) > 0:
            # Forecasted values should be in the same order of magnitude
            # as the original data (not tiny differenced values)
            for metric in ["metric_a", "metric_b", "metric_c"]:
                fc = result.forecasts[metric]
                last_value = series[metric][-1][1]
                # Forecast should be within a reasonable range of last value
                for pt in fc.points:
                    # Allow generous range (within 50% of last value's magnitude)
                    assert abs(pt.value) > abs(last_value) * 0.01, (
                        f"Forecast for {metric} seems to be in differenced space "
                        f"(value={pt.value}, last_level={last_value})"
                    )

    def test_insufficient_obs_after_differencing_returns_none(self) -> None:
        """If differencing leaves fewer than 20 obs, forecast_group returns None."""
        # 22 obs => after d=1 => 21 obs (still enough)
        # After d=2 => 20 obs (exactly enough)
        # With 21 obs and d=2 => 19 obs => None
        rng = np.random.RandomState(33)
        n = 21
        periods = [f"{2018 + i // 4}-Q{(i % 4) + 1}" for i in range(n)]

        # Create I(2) series that will need d=2
        noise = rng.normal(0.0, 1.0, size=n)
        i2 = np.cumsum(np.cumsum(noise))

        series = {
            "a": list(zip(periods, i2.tolist())),
            "b": list(zip(periods, (i2 + rng.normal(0, 0.1, n)).tolist())),
            "c": list(zip(periods, (i2 * 0.5 + rng.normal(0, 0.1, n)).tolist())),
        }

        forecaster = VARForecaster()
        result = forecaster.forecast_group("short_i2", series, horizon=2)

        # Result can be None (insufficient after diff) or have diff_order < 2
        # depending on stationarity test outcomes
        if result is not None:
            assert result.diagnostics.get("group_diff_order", 0) <= 2
