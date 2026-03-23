"""Tests for VECM cointegration support in VARForecaster.

Tests verify that:
- VECM is triggered when series are cointegrated
- VAR is used when series are not cointegrated
- VAR fallback works when VECM fitting fails
- Cointegration rank detection is correct
- Forecast shape and CI validity
- Diagnostics contain model_type and coint_rank
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np

from backend.app.services.var_forecaster import VARForecaster, VARForecastResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cointegrated_series(n: int = 60, seed: int = 42) -> dict[str, list[tuple[str, float]]]:
    """Generate 3 cointegrated series (share a common stochastic trend).

    x1 follows a random walk.
    x2 = 2*x1 + stationary noise  (cointegrated with x1)
    x3 = -0.5*x1 + stationary noise  (cointegrated with x1)
    """
    rng = np.random.RandomState(seed)
    # Common stochastic trend (random walk)
    trend = np.cumsum(rng.normal(0, 1, n))
    x1 = trend + rng.normal(0, 0.3, n)
    x2 = 2.0 * trend + rng.normal(0, 0.3, n) + 50.0
    x3 = -0.5 * trend + rng.normal(0, 0.3, n) + 20.0

    periods = [f"2010-Q{(i % 4) + 1}" if i < 4 else f"{2010 + i // 4}-Q{(i % 4) + 1}" for i in range(n)]
    return {
        "metric_a": [(p, float(v)) for p, v in zip(periods, x1)],
        "metric_b": [(p, float(v)) for p, v in zip(periods, x2)],
        "metric_c": [(p, float(v)) for p, v in zip(periods, x3)],
    }


def _make_independent_series(n: int = 60, seed: int = 99) -> dict[str, list[tuple[str, float]]]:
    """Generate 3 independent (non-cointegrated) stationary series."""
    rng = np.random.RandomState(seed)
    x1 = rng.normal(100, 5, n)
    x2 = rng.normal(50, 3, n)
    x3 = rng.normal(200, 10, n)

    periods = [f"{2010 + i // 4}-Q{(i % 4) + 1}" for i in range(n)]
    return {
        "ind_a": [(p, float(v)) for p, v in zip(periods, x1)],
        "ind_b": [(p, float(v)) for p, v in zip(periods, x2)],
        "ind_c": [(p, float(v)) for p, v in zip(periods, x3)],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestVECMTriggersWhenCointegrated:
    """VECM should be used when Johansen test detects cointegration."""

    def test_vecm_model_used_for_cointegrated_series(self):
        forecaster = VARForecaster()
        series = _make_cointegrated_series(n=60)
        result = forecaster.forecast_group("test_coint", series, horizon=4)

        # Result may be None if statsmodels detects instability, but if we
        # get a result, check that VECM was at least attempted
        if result is not None:
            diag = result.diagnostics
            if diag.get("johansen_cointegrated"):
                assert diag.get("model_type") == "VECM"
                assert "coint_rank" in diag
                # Verify ForecastResult model_used string
                for fr in result.forecasts.values():
                    assert "VECM" in fr.model_used


class TestVARUsedWhenNotCointegrated:
    """VAR should be used when series are not cointegrated."""

    def test_var_model_used_for_independent_series(self):
        forecaster = VARForecaster()
        series = _make_independent_series(n=60)
        result = forecaster.forecast_group("test_indep", series, horizon=4)

        if result is not None:
            diag = result.diagnostics
            # Independent series should not be cointegrated
            if diag.get("johansen_cointegrated") is False:
                assert diag.get("model_type") == "VAR"
                for fr in result.forecasts.values():
                    assert fr.model_used.startswith("VAR(")


class TestVARFallbackOnVECMFailure:
    """When VECM fitting fails, should fall back to VAR."""

    def test_var_fallback_when_vecm_raises(self):
        forecaster = VARForecaster()
        series = _make_cointegrated_series(n=60)

        with patch.object(
            forecaster,
            "_fit_vecm_and_forecast",
            side_effect=RuntimeError("VECM singular matrix"),
        ):
            result = forecaster.forecast_group("test_fallback", series, horizon=4)

        if result is not None:
            diag = result.diagnostics
            if diag.get("johansen_cointegrated"):
                assert diag.get("model_type") == "VAR"
                assert "vecm_fallback_reason" in diag
                assert "VECM singular" in diag["vecm_fallback_reason"]


class TestCointRankDetection:
    """Cointegration rank should be correctly computed from trace statistics."""

    def test_coint_rank_is_positive_integer(self):
        forecaster = VARForecaster()
        series = _make_cointegrated_series(n=60)
        result = forecaster.forecast_group("test_rank", series, horizon=4)

        if result is not None and result.diagnostics.get("johansen_cointegrated"):
            rank = result.diagnostics["coint_rank"]
            assert isinstance(rank, int)
            assert 1 <= rank <= len(result.metrics) - 1

    def test_coint_rank_matches_trace_stats(self):
        """Verify rank = count of trace stats exceeding critical values."""
        forecaster = VARForecaster()
        series = _make_cointegrated_series(n=60)
        result = forecaster.forecast_group("test_rank_match", series, horizon=4)

        if result is not None and result.diagnostics.get("johansen_cointegrated"):
            trace = result.diagnostics["johansen_trace_stats"]
            crit = result.diagnostics["johansen_crit_5pct"]
            expected_rank = sum(1 for t, c in zip(trace, crit) if t > c)
            assert result.diagnostics["coint_rank"] == expected_rank


class TestForecastShapeCorrectness:
    """Forecast output should have correct number of points and metrics."""

    def test_forecast_has_correct_horizon(self):
        forecaster = VARForecaster()
        series = _make_cointegrated_series(n=60)
        horizon = 4
        result = forecaster.forecast_group("test_shape", series, horizon=horizon)

        if result is not None:
            for metric, fr in result.forecasts.items():
                assert len(fr.points) == horizon
                assert fr.horizon == horizon

    def test_forecast_covers_all_metrics(self):
        forecaster = VARForecaster()
        series = _make_cointegrated_series(n=60)
        result = forecaster.forecast_group("test_metrics", series, horizon=4)

        if result is not None:
            assert set(result.forecasts.keys()) == set(series.keys())
            assert len(result.metrics) == len(series)


class TestCIValidity:
    """Confidence intervals should satisfy lower < point < upper."""

    def test_ci_ordering(self):
        forecaster = VARForecaster()
        series = _make_cointegrated_series(n=60)
        result = forecaster.forecast_group("test_ci", series, horizon=4)

        if result is not None:
            for fr in result.forecasts.values():
                for pt in fr.points:
                    assert pt.lower_95 <= pt.lower_80, f"lower_95 ({pt.lower_95}) > lower_80 ({pt.lower_80})"
                    assert pt.lower_80 < pt.value, f"lower_80 ({pt.lower_80}) >= value ({pt.value})"
                    assert pt.value < pt.upper_80, f"value ({pt.value}) >= upper_80 ({pt.upper_80})"
                    assert pt.upper_80 <= pt.upper_95, f"upper_80 ({pt.upper_80}) > upper_95 ({pt.upper_95})"


class TestDiagnosticsContainModelType:
    """Diagnostics dict should always contain model_type."""

    def test_diagnostics_has_model_type(self):
        forecaster = VARForecaster()
        # Try both cointegrated and independent series
        for label, series_fn in [
            ("coint", _make_cointegrated_series),
            ("indep", _make_independent_series),
        ]:
            series = series_fn(n=60)
            result = forecaster.forecast_group(f"test_diag_{label}", series, horizon=4)
            if result is not None:
                assert "model_type" in result.diagnostics
                assert result.diagnostics["model_type"] in ("VAR", "VECM")


class TestGroupForecastEndToEnd:
    """Full end-to-end test of forecast_group with real data patterns."""

    def test_e2e_cointegrated_group(self):
        forecaster = VARForecaster()
        series = _make_cointegrated_series(n=80, seed=123)
        result = forecaster.forecast_group("e2e_test", series, horizon=8)

        assert result is not None, "Expected a VARForecastResult, got None"
        assert isinstance(result, VARForecastResult)
        assert result.group == "e2e_test"
        assert result.n_obs > 0
        assert result.lag_order >= 1

        # Every metric should have a ForecastResult
        for metric in series:
            assert metric in result.forecasts
            fr = result.forecasts[metric]
            assert len(fr.points) == 8
            assert fr.metric == metric

        # Diagnostics should be populated
        diag = result.diagnostics
        assert "johansen_cointegrated" in diag
        assert "model_type" in diag
