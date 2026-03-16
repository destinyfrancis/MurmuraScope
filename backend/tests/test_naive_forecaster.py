"""Tests for the naive baseline forecaster."""
import pytest
from backend.app.services.naive_forecaster import NaiveForecaster


def test_last_value_forecast():
    history = [100, 102, 104, 103, 105]
    f = NaiveForecaster()
    result = f.forecast(history, horizon=3, method="last_value")
    assert result == [105, 105, 105]


def test_linear_drift_forecast():
    history = [100, 102, 104, 106, 108]
    f = NaiveForecaster()
    result = f.forecast(history, horizon=3, method="drift")
    assert result == pytest.approx([110.0, 112.0, 114.0])


def test_empty_history():
    f = NaiveForecaster()
    result = f.forecast([], horizon=3)
    assert result == [0.0, 0.0, 0.0]


def test_single_value():
    f = NaiveForecaster()
    result = f.forecast([42], horizon=2, method="drift")
    assert result == [42, 42]


def test_default_method_is_last_value():
    f = NaiveForecaster()
    result = f.forecast([10, 20, 30], horizon=2)
    assert result == [30, 30]


def test_unknown_method_raises():
    f = NaiveForecaster()
    with pytest.raises(ValueError, match="Unknown method"):
        f.forecast([1, 2, 3], method="unknown")


def test_horizon_zero():
    f = NaiveForecaster()
    result = f.forecast([1, 2, 3], horizon=0)
    assert result == []


def test_drift_two_values():
    f = NaiveForecaster()
    result = f.forecast([10, 20], horizon=2, method="drift")
    assert result == pytest.approx([30.0, 40.0])
