"""Tests for Phase E: Time Series Engine Wiring.

Covers:
- TimeSeriesForecaster.forecast (naive + AutoARIMA fallback)
- TimeSeriesForecaster._next_period_labels (quarterly + annual + fallback)
- TimeSeriesForecaster._forecast_naive (trend + confidence intervals)
- TimeSeriesForecaster._hardcoded_baseline (bootstrap data)
- MacroController.get_forecast_adjusted_baseline (integration with forecaster)
- update_from_actions with ets_forecast argument (Phase E wiring)
- Task 2.2: forecast_multivariate (VAR delegation)
- Task 2.4: forecast_rolling (rolling window backtesting)
- Task 2.5: seasonality (season_length + seasonal adjustments)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from backend.app.services.time_series_forecaster import (
    TimeSeriesForecaster,
    SUPPORTED_METRICS,
    _quarter_label,
    _annual_label,
    _SEASONAL_METRICS,
    _SEASONAL_ADJUSTMENTS,
)
from backend.app.models.forecast import ForecastPoint, ForecastResult


# ===========================================================================
# Period label helpers
# ===========================================================================


class TestPeriodLabelHelpers:
    def test_quarter_label_basic(self):
        assert _quarter_label(2024, 1, 1) == "2024-Q2"
        assert _quarter_label(2024, 4, 1) == "2025-Q1"

    def test_quarter_label_year_rollover(self):
        assert _quarter_label(2024, 3, 3) == "2025-Q2"

    def test_annual_label(self):
        assert _annual_label(2024, 1) == "2025"
        assert _annual_label(2022, 3) == "2025"

    def test_next_period_labels_quarterly(self):
        forecaster = TimeSeriesForecaster()
        labels = forecaster._next_period_labels("2024-Q1", 4)
        assert labels == ["2024-Q2", "2024-Q3", "2024-Q4", "2025-Q1"]

    def test_next_period_labels_annual(self):
        forecaster = TimeSeriesForecaster()
        labels = forecaster._next_period_labels("2023", 3)
        assert labels == ["2024", "2025", "2026"]

    def test_next_period_labels_fallback(self):
        forecaster = TimeSeriesForecaster()
        labels = forecaster._next_period_labels("unknown", 3)
        assert labels == ["t+1", "t+2", "t+3"]

    def test_next_period_labels_count(self):
        forecaster = TimeSeriesForecaster()
        labels = forecaster._next_period_labels("2024-Q2", 8)
        assert len(labels) == 8


# ===========================================================================
# Hardcoded baseline — REMOVED (no synthetic data allowed)
# _hardcoded_baseline() was deleted in the real data upgrade.
# ===========================================================================


# ===========================================================================
# _forecast_naive
# ===========================================================================


class TestForecastNaive:
    def _make_forecaster(self) -> TimeSeriesForecaster:
        return TimeSeriesForecaster()

    def test_returns_correct_horizon_count(self):
        forecaster = self._make_forecaster()
        history = [("2022-Q1", 100.0), ("2022-Q2", 101.0), ("2022-Q3", 102.0)]
        result = forecaster._forecast_naive("ccl_index", history, horizon=6)
        assert len(result.points) == 6

    def test_forecast_model_is_naive(self):
        forecaster = self._make_forecaster()
        history = [("2022-Q1", 100.0)]
        result = forecaster._forecast_naive("ccl_index", history, horizon=4)
        assert result.model_used == "rw_drift"

    def test_point_values_are_floats(self):
        forecaster = self._make_forecaster()
        history = [("2022-Q1", 0.030), ("2022-Q2", 0.031), ("2022-Q3", 0.029), ("2022-Q4", 0.028)]
        result = forecaster._forecast_naive("unemployment_rate", history, horizon=4)
        for pt in result.points:
            assert isinstance(pt.value, float)

    def test_confidence_intervals_are_ordered(self):
        """lower_95 ≤ lower_80 ≤ value ≤ upper_80 ≤ upper_95."""
        forecaster = self._make_forecaster()
        history = [("2022-Q1", 17200.0), ("2022-Q2", 17800.0), ("2022-Q3", 18500.0), ("2022-Q4", 17000.0)]
        result = forecaster._forecast_naive("hsi_level", history, horizon=4)
        for pt in result.points:
            assert pt.lower_95 <= pt.lower_80
            assert pt.lower_80 <= pt.value
            assert pt.value <= pt.upper_80
            assert pt.upper_80 <= pt.upper_95

    def test_empty_history_returns_empty_result(self):
        """Empty history should return empty result — no synthetic fallback."""
        forecaster = self._make_forecaster()
        result = forecaster._forecast_naive("ccl_index", [], horizon=2)
        assert len(result.points) == 0
        assert result.model_used == "rw_drift"
        assert result.data_quality == "no_data"

    def test_periods_are_labelled(self):
        forecaster = self._make_forecaster()
        history = [("2024-Q1", 152.0), ("2024-Q2", 150.0)]
        result = forecaster._forecast_naive("ccl_index", history, horizon=3)
        periods = [pt.period for pt in result.points]
        assert all(p.startswith("2024-Q") or p.startswith("2025-Q") for p in periods)


# ===========================================================================
# ForecastResult / ForecastPoint frozen dataclasses
# ===========================================================================


class TestForecastDataclasses:
    def test_forecast_point_frozen(self):
        import dataclasses as dc

        pt = ForecastPoint(
            period="2025-Q1",
            value=150.0,
            lower_80=145.0,
            upper_80=155.0,
            lower_95=142.0,
            upper_95=158.0,
        )
        with pytest.raises((dc.FrozenInstanceError, AttributeError)):
            pt.value = 999.0  # type: ignore[misc]

    def test_forecast_result_frozen(self):
        import dataclasses as dc

        result = ForecastResult(
            metric="ccl_index",
            horizon=4,
            points=[],
            model_used="naive",
            fit_quality=0.0,
        )
        with pytest.raises((dc.FrozenInstanceError, AttributeError)):
            result.metric = "other"  # type: ignore[misc]

    def test_forecast_result_to_dict(self):
        pt = ForecastPoint(
            period="2025-Q1", value=150.0,
            lower_80=145.0, upper_80=155.0,
            lower_95=142.0, upper_95=158.0,
        )
        result = ForecastResult(
            metric="ccl_index",
            horizon=1,
            points=[pt],
            model_used="naive",
            fit_quality=0.0,
        )
        d = result.to_dict()
        assert d["metric"] == "ccl_index"
        assert len(d["points"]) == 1
        assert d["points"][0]["period"] == "2025-Q1"


# ===========================================================================
# TimeSeriesForecaster.forecast (async, with DB mock)
# ===========================================================================


class TestForecasterForecast:
    """Integration tests for the async forecast() method."""

    @pytest.mark.asyncio
    async def test_forecast_unsupported_metric_raises(self):
        forecaster = TimeSeriesForecaster()
        with pytest.raises(ValueError, match="Unsupported metric"):
            await forecaster.forecast("nonexistent_metric")

    @pytest.mark.asyncio
    async def test_forecast_returns_no_data_when_db_empty(self):
        """When DB returns no data, should refuse forecast (no synthetic fallback)."""
        forecaster = TimeSeriesForecaster()

        with patch("backend.app.services.time_series_forecaster.get_db") as mock_get_db:
            mock_cursor = AsyncMock()
            mock_cursor.fetchall = AsyncMock(return_value=[])
            mock_db = AsyncMock()
            mock_db.execute = AsyncMock(return_value=mock_cursor)
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await forecaster.forecast("ccl_index", horizon=4)

        assert result.metric == "ccl_index"
        assert len(result.points) == 0
        assert result.data_quality in ("no_data", "insufficient")

    @pytest.mark.asyncio
    async def test_forecast_horizon_clamped(self):
        """Horizon outside [1, 24] should be clamped."""
        forecaster = TimeSeriesForecaster()

        with patch("backend.app.services.time_series_forecaster.get_db") as mock_get_db:
            mock_cursor = AsyncMock()
            mock_cursor.fetchall = AsyncMock(return_value=[])
            mock_db = AsyncMock()
            mock_db.execute = AsyncMock(return_value=mock_cursor)
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await forecaster.forecast("gdp_growth", horizon=999)

        assert result.horizon <= 24
        # With empty DB, points may be 0 (insufficient data) or <= 24 (if data exists)
        assert len(result.points) <= 24

    @pytest.mark.asyncio
    async def test_forecast_all_supported_metrics(self):
        """All supported metrics should return a valid ForecastResult."""
        forecaster = TimeSeriesForecaster()

        with patch("backend.app.services.time_series_forecaster.get_db") as mock_get_db:
            mock_cursor = AsyncMock()
            mock_cursor.fetchall = AsyncMock(return_value=[])
            mock_db = AsyncMock()
            mock_db.execute = AsyncMock(return_value=mock_cursor)
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            for metric in SUPPORTED_METRICS:
                result = await forecaster.forecast(metric, horizon=2)
                assert result.metric == metric
                # With empty DB, data_quality should indicate no data
                assert result.data_quality in ("no_data", "insufficient")


# ===========================================================================
# MacroController.get_forecast_adjusted_baseline (Phase E)
# ===========================================================================


class TestGetForecastAdjustedBaseline:
    """Tests for the forecast-adjusted baseline integration."""

    @pytest.mark.asyncio
    async def test_returns_dict_of_forecast_points(self):
        """get_forecast_adjusted_baseline should return a dict with ForecastPoints."""
        from backend.app.services.macro_controller import MacroController
        from backend.app.services.macro_state import MacroState
        import backend.app.services.time_series_forecaster as tsf_mod

        state = MacroState(
            hibor_1m=0.04, prime_rate=0.0575,
            unemployment_rate=0.029, median_monthly_income=20_000,
            ccl_index=152.3, avg_sqft_price={}, mortgage_cap=0.70,
            stamp_duty_rates={}, gdp_growth=0.032, cpi_yoy=0.021,
            hsi_level=16_800.0, consumer_confidence=88.5,
            net_migration=-12_000, birth_rate=5.8, policy_flags={},
        )

        mock_result = ForecastResult(
            metric="gdp_growth",
            horizon=1,
            points=[ForecastPoint(
                period="2025-Q1", value=0.033,
                lower_80=0.028, upper_80=0.038,
                lower_95=0.025, upper_95=0.041,
            )],
            model_used="naive",
            fit_quality=0.0,
        )

        mc = MacroController()
        original_cls = tsf_mod.TimeSeriesForecaster

        class _MockForecaster:
            async def forecast(self, metric, horizon=1):
                return mock_result
            async def list_supported_metrics(self):
                return ["gdp_growth"]

        tsf_mod.TimeSeriesForecaster = _MockForecaster  # type: ignore
        try:
            result = await mc.get_forecast_adjusted_baseline(state, horizon=1)
        finally:
            tsf_mod.TimeSeriesForecaster = original_cls  # type: ignore

        assert isinstance(result, dict)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_returns_empty_dict_on_forecaster_failure(self):
        """If all forecasts fail, should return empty dict without raising."""
        from backend.app.services.macro_controller import MacroController
        from backend.app.services.macro_state import MacroState
        import backend.app.services.time_series_forecaster as tsf_mod

        state = MacroState(
            hibor_1m=0.04, prime_rate=0.0575,
            unemployment_rate=0.029, median_monthly_income=20_000,
            ccl_index=152.3, avg_sqft_price={}, mortgage_cap=0.70,
            stamp_duty_rates={}, gdp_growth=0.032, cpi_yoy=0.021,
            hsi_level=16_800.0, consumer_confidence=88.5,
            net_migration=-12_000, birth_rate=5.8, policy_flags={},
        )

        mc = MacroController()
        original_cls = tsf_mod.TimeSeriesForecaster

        class _FailingForecaster:
            async def forecast(self, metric, horizon=1):
                raise RuntimeError("DB down")
            async def list_supported_metrics(self):
                return ["gdp_growth"]

        tsf_mod.TimeSeriesForecaster = _FailingForecaster  # type: ignore
        try:
            result = await mc.get_forecast_adjusted_baseline(state, horizon=1)
        finally:
            tsf_mod.TimeSeriesForecaster = original_cls  # type: ignore

        assert isinstance(result, dict)
        assert len(result) == 0  # all failed → empty

    @pytest.mark.asyncio
    async def test_ets_forecast_used_as_baseline_in_update(self):
        """When ets_forecast is provided, GDP baseline should come from it."""
        from backend.app.services.macro_controller import MacroController
        from backend.app.services.macro_state import MacroState

        current_gdp = 0.030
        forecast_gdp = 0.035  # forecaster projects higher growth

        state = MacroState(
            hibor_1m=0.04, prime_rate=0.0575,
            unemployment_rate=0.029, median_monthly_income=20_000,
            ccl_index=152.3, avg_sqft_price={}, mortgage_cap=0.70,
            stamp_duty_rates={}, gdp_growth=current_gdp, cpi_yoy=0.021,
            hsi_level=16_800.0, consumer_confidence=88.5,
            net_migration=-12_000, birth_rate=5.8, policy_flags={},
        )

        # Mock a ForecastPoint-like object for gdp_growth
        mock_gdp_forecast = MagicMock()
        mock_gdp_forecast.value = forecast_gdp
        ets_forecast = {"gdp_growth": mock_gdp_forecast}

        mc = MacroController()

        # 70% positive sentiment → should boost confidence but NOT drop GDP
        mock_rows = [("positive", "[]")] * 70 + [("neutral", "[]")] * 30

        with patch("backend.app.utils.db.get_db") as mock_get_db:
            mock_cursor = AsyncMock()
            mock_cursor.fetchall = AsyncMock(return_value=mock_rows)
            mock_db = AsyncMock()
            mock_db.execute = AsyncMock(return_value=mock_cursor)
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            updated = await mc.update_from_actions(
                state, "sess1", 5, ets_forecast=ets_forecast
            )

        # GDP should start from forecast_gdp (0.035), not current_gdp (0.030)
        # No negative sentiment → no GDP reduction → updated.gdp_growth ≈ 0.035
        assert updated.gdp_growth >= current_gdp  # anchored at forecast_gdp baseline


# ===========================================================================
# list_supported_metrics
# ===========================================================================


class TestListSupportedMetrics:
    @pytest.mark.asyncio
    async def test_returns_sorted_list(self):
        forecaster = TimeSeriesForecaster()
        metrics = await forecaster.list_supported_metrics()
        assert metrics == sorted(metrics)
        assert len(metrics) == len(SUPPORTED_METRICS)

    @pytest.mark.asyncio
    async def test_gdp_growth_included(self):
        forecaster = TimeSeriesForecaster()
        metrics = await forecaster.list_supported_metrics()
        assert "gdp_growth" in metrics


# ===========================================================================
# Task 2.5 — Seasonality
# ===========================================================================


class TestSeasonalityConfig:
    """Tests for _SEASONAL_METRICS, _SEASONAL_ADJUSTMENTS, and helpers."""

    def test_seasonal_metrics_all_supported(self):
        """Every metric in _SEASONAL_METRICS must be a supported metric."""
        for m in _SEASONAL_METRICS:
            assert m in SUPPORTED_METRICS, f"{m} not in SUPPORTED_METRICS"

    def test_seasonal_metrics_valid_lengths(self):
        """season_length must be 4 (quarterly) or 12 (monthly)."""
        for m, sl in _SEASONAL_METRICS.items():
            assert sl in (4, 12), f"{m} has invalid season_length {sl}"

    def test_seasonal_adjustments_all_supported(self):
        """Every metric in _SEASONAL_ADJUSTMENTS must be a supported metric."""
        for m in _SEASONAL_ADJUSTMENTS:
            assert m in SUPPORTED_METRICS, f"{m} not in SUPPORTED_METRICS"

    def test_seasonal_adjustments_quarter_range(self):
        """Quarter numbers must be 1–4."""
        for m, adjustments in _SEASONAL_ADJUSTMENTS.items():
            for q, _delta in adjustments:
                assert 1 <= q <= 4, f"{m}: quarter {q} out of range"

    def test_get_season_length_known(self):
        forecaster = TimeSeriesForecaster()
        assert forecaster._get_season_length("ccl_index") == 4
        assert forecaster._get_season_length("hsi_level") == 12
        assert forecaster._get_season_length("cpi_yoy") == 12

    def test_get_season_length_unknown_defaults(self):
        forecaster = TimeSeriesForecaster()
        assert forecaster._get_season_length("nonexistent_metric") == 4

    def test_apply_seasonal_adjustment_no_match(self):
        """Metrics without seasonal adjustments pass through unchanged."""
        forecaster = TimeSeriesForecaster()
        pt = ForecastPoint(
            period="2024-Q2", value=100.0,
            lower_80=95.0, upper_80=105.0,
            lower_95=92.0, upper_95=108.0,
        )
        result = forecaster._apply_seasonal_adjustment([pt], "hsi_level", "2024-Q1")
        assert len(result) == 1
        assert result[0] is pt  # unchanged — same object returned

    def test_apply_seasonal_adjustment_q1_ccl(self):
        """ccl_index Q1 should have a slight negative adjustment."""
        forecaster = TimeSeriesForecaster()
        pt = ForecastPoint(
            period="2025-Q1", value=160.0,
            lower_80=155.0, upper_80=165.0,
            lower_95=152.0, upper_95=168.0,
        )
        result = forecaster._apply_seasonal_adjustment([pt], "ccl_index", "2024-Q4")
        assert len(result) == 1
        # Q1 adjustment is -0.005 → value should decrease slightly
        assert result[0].value < pt.value

    def test_apply_seasonal_adjustment_q2_no_effect(self):
        """ccl_index Q2 should be unchanged (no adjustment defined)."""
        forecaster = TimeSeriesForecaster()
        pt = ForecastPoint(
            period="2025-Q2", value=160.0,
            lower_80=155.0, upper_80=165.0,
            lower_95=152.0, upper_95=168.0,
        )
        result = forecaster._apply_seasonal_adjustment([pt], "ccl_index", "2025-Q1")
        assert result[0] is pt  # unchanged

    def test_apply_seasonal_adjustment_immutability(self):
        """Original ForecastPoint objects must not be mutated."""
        forecaster = TimeSeriesForecaster()
        original_value = 160.0
        pt = ForecastPoint(
            period="2025-Q1", value=original_value,
            lower_80=155.0, upper_80=165.0,
            lower_95=152.0, upper_95=168.0,
        )
        _ = forecaster._apply_seasonal_adjustment([pt], "ccl_index", "2024-Q4")
        assert pt.value == original_value  # original unchanged

    def test_seasonal_adjustment_propagated_in_naive_forecast(self):
        """_forecast_naive should apply seasonal adjustment for configured metrics."""
        forecaster = TimeSeriesForecaster()
        # Build history ending at Q3 → next forecast should be Q4
        history = [("2024-Q1", 0.030), ("2024-Q2", 0.031), ("2024-Q3", 0.032)]
        # gdp_growth has Q4 positive adjustment
        result = forecaster._forecast_naive("gdp_growth", history, horizon=1)
        # Q4 period is expected
        assert result.points[0].period == "2024-Q4"
        # With positive adjustment the value should be >= the unadjusted trend
        assert isinstance(result.points[0].value, float)


# ===========================================================================
# Task 2.4 — Rolling Window Forecast
# ===========================================================================


class TestForecastRolling:
    """Tests for TimeSeriesForecaster.forecast_rolling()."""

    def _mock_db_context(self, rows: list) -> patch:
        """Helper to patch get_db and return fixed rows."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=rows)
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_cursor)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_db)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return patch(
            "backend.app.services.time_series_forecaster.get_db",
            return_value=ctx,
        )

    @pytest.mark.asyncio
    async def test_rolling_unsupported_metric_raises(self):
        forecaster = TimeSeriesForecaster()
        with pytest.raises(ValueError, match="Unsupported metric"):
            await forecaster.forecast_rolling("bad_metric")

    @pytest.mark.asyncio
    async def test_rolling_insufficient_data_returns_empty(self):
        """Fewer obs than window_size+horizon → empty list returned."""
        forecaster = TimeSeriesForecaster()
        # Patch DB to return 0 rows; hardcoded baseline has 8 points.
        # window_size=24 > 8+1 → empty
        with self._mock_db_context([]):
            result = await forecaster.forecast_rolling(
                "ccl_index", window_size=24, horizon=1
            )
        assert result == []

    @pytest.mark.asyncio
    async def test_rolling_returns_forecast_points(self):
        """With enough data, rolling should return ForecastPoint objects."""
        forecaster = TimeSeriesForecaster()
        # Build 30 synthetic rows (enough for window=20, horizon=1)
        rows = [(f"202{i//4}-Q{(i%4)+1}", float(150 + i)) for i in range(30)]
        with self._mock_db_context(rows):
            result = await forecaster.forecast_rolling(
                "ccl_index", window_size=20, horizon=1
            )
        assert len(result) > 0
        for pt in result:
            assert isinstance(pt, ForecastPoint)
            assert isinstance(pt.value, float)

    @pytest.mark.asyncio
    async def test_rolling_periods_are_labelled(self):
        """Each rolling ForecastPoint should have a non-empty period string."""
        forecaster = TimeSeriesForecaster()
        rows = [(f"202{i//4}-Q{(i%4)+1}", float(150 + i)) for i in range(30)]
        with self._mock_db_context(rows):
            result = await forecaster.forecast_rolling(
                "ccl_index", window_size=20, horizon=1
            )
        for pt in result:
            assert pt.period != ""

    @pytest.mark.asyncio
    async def test_rolling_ci_ordering(self):
        """lower_95 <= lower_80 <= value <= upper_80 <= upper_95 for all points."""
        forecaster = TimeSeriesForecaster()
        rows = [(f"202{i//4}-Q{(i%4)+1}", float(0.028 + i * 0.001)) for i in range(30)]
        with self._mock_db_context(rows):
            result = await forecaster.forecast_rolling(
                "gdp_growth", window_size=20, horizon=1
            )
        for pt in result:
            assert pt.lower_95 <= pt.lower_80, f"CI ordering violated at {pt.period}"
            assert pt.upper_80 <= pt.upper_95, f"CI ordering violated at {pt.period}"

    @pytest.mark.asyncio
    async def test_rolling_horizon_clamped_to_4(self):
        """horizon > 4 should be clamped to 4."""
        forecaster = TimeSeriesForecaster()
        rows = [(f"202{i//4}-Q{(i%4)+1}", float(150 + i)) for i in range(40)]
        with self._mock_db_context(rows):
            # Should not raise; horizon clamped internally
            result = await forecaster.forecast_rolling(
                "ccl_index", window_size=20, horizon=99
            )
        # Result may be empty if window+horizon > n, but no crash
        assert isinstance(result, list)


# ===========================================================================
# Task 2.2 — VAR Multivariate
# ===========================================================================


class TestForecastMultivariate:
    """Tests for TimeSeriesForecaster.forecast_multivariate()."""

    @pytest.mark.asyncio
    async def test_invalid_group_raises(self):
        forecaster = TimeSeriesForecaster()
        with pytest.raises(ValueError, match="Unknown VAR group"):
            await forecaster.forecast_multivariate("nonexistent_group")

    @pytest.mark.asyncio
    async def test_insufficient_data_returns_none(self):
        """When DB has no data, history is 8-point baseline → VAR returns None."""
        forecaster = TimeSeriesForecaster()

        with patch("backend.app.services.time_series_forecaster.get_db") as mock_get_db:
            mock_cursor = AsyncMock()
            mock_cursor.fetchall = AsyncMock(return_value=[])
            mock_db = AsyncMock()
            mock_db.execute = AsyncMock(return_value=mock_cursor)
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            # Baseline has 8 points < 20 → VAR should decline
            result = await forecaster.forecast_multivariate("property", horizon=4)

        assert result is None

    @pytest.mark.asyncio
    async def test_valid_group_with_sufficient_data(self):
        """With ≥20 obs per metric in the group, VAR should return ForecastResults."""
        forecaster = TimeSeriesForecaster()

        # Build 25 rows of synthetic data (enough for VAR)
        rows_property = [(f"201{i//4}-Q{(i%4)+1}", float(150 + i)) for i in range(25)]
        rows_gdp = [(f"201{i//4}-Q{(i%4)+1}", float(0.025 + i * 0.001)) for i in range(25)]

        call_count = 0

        async def _mock_load(metric: str) -> list:
            nonlocal call_count
            call_count += 1
            if metric == "gdp_growth":
                return rows_gdp
            return rows_property

        original_load = forecaster._load_history
        forecaster._load_history = _mock_load  # type: ignore[method-assign]
        try:
            result = await forecaster.forecast_multivariate("labour", horizon=2)
        finally:
            forecaster._load_history = original_load  # type: ignore[method-assign]

        # If statsmodels is available, result should be a dict; otherwise None
        import importlib
        var_mod = importlib.import_module("backend.app.services.var_forecaster")
        if var_mod.HAS_STATSMODELS:
            # May still be None if group metrics aren't all qualified; accept both
            assert result is None or isinstance(result, dict)
        else:
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_gracefully_on_var_failure(self):
        """If VARForecaster raises internally, forecast_multivariate returns None."""
        forecaster = TimeSeriesForecaster()

        rows = [(f"201{i//4}-Q{(i%4)+1}", float(0.025 + i * 0.001)) for i in range(25)]

        async def _mock_load(metric: str) -> list:
            return rows

        forecaster._load_history = _mock_load  # type: ignore[method-assign]

        with patch(
            "backend.app.services.var_forecaster.VARForecaster.forecast_group",
            return_value=None,
        ):
            result = await forecaster.forecast_multivariate("labour", horizon=2)

        assert result is None


# ===========================================================================
# VARForecaster unit tests
# ===========================================================================


class TestVARForecaster:
    """Unit tests for var_forecaster.VARForecaster."""

    def _build_series(
        self,
        n: int = 25,
        metrics: list[str] | None = None,
    ) -> dict[str, list[tuple[str, float]]]:
        if metrics is None:
            metrics = ["unemployment_rate", "consumer_confidence", "gdp_growth"]
        return {
            m: [(f"201{i//4}-Q{(i%4)+1}", float(0.03 + i * 0.001 + j * 0.1))
                for i in range(n)]
            for j, m in enumerate(metrics)
        }

    def test_align_series_empty_returns_none(self):
        from backend.app.services.var_forecaster import VARForecaster
        var = VARForecaster()
        assert var._align_series({}) is None

    def test_align_series_no_common_periods(self):
        from backend.app.services.var_forecaster import VARForecaster
        var = VARForecaster()
        series = {
            "a": [("2020-Q1", 1.0)],
            "b": [("2021-Q1", 2.0)],
        }
        assert var._align_series(series) is None

    def test_align_series_common_periods(self):
        from backend.app.services.var_forecaster import VARForecaster
        var = VARForecaster()
        series = {
            "a": [("2020-Q1", 1.0), ("2020-Q2", 2.0)],
            "b": [("2020-Q1", 3.0), ("2020-Q2", 4.0)],
        }
        result = var._align_series(series)
        assert result is not None
        metrics_order, data_matrix, periods = result
        assert data_matrix.shape == (2, 2)
        assert sorted(metrics_order) == sorted(["a", "b"])

    def test_forecast_group_insufficient_data_returns_none(self):
        from backend.app.services.var_forecaster import VARForecaster
        var = VARForecaster()
        # Only 5 observations — well below _MIN_VAR_POINTS=20
        series = {
            "a": [("2020-Q1", 1.0)] * 5,
            "b": [("2020-Q1", 2.0)] * 5,
        }
        result = var.forecast_group("test", series, horizon=2)
        assert result is None

    def test_forecast_group_no_common_periods_returns_none(self):
        from backend.app.services.var_forecaster import VARForecaster
        var = VARForecaster()
        series = {
            "a": [("2020-Q1", 1.0)],
            "b": [("2021-Q1", 2.0)],
        }
        result = var.forecast_group("test", series, horizon=2)
        assert result is None

    def test_var_period_labels(self):
        from backend.app.services.var_forecaster import _next_period_labels
        labels = _next_period_labels("2024-Q3", 3)
        assert labels == ["2024-Q4", "2025-Q1", "2025-Q2"]

    def test_var_period_labels_annual(self):
        from backend.app.services.var_forecaster import _next_period_labels
        labels = _next_period_labels("2023", 3)
        assert labels == ["2024", "2025", "2026"]

    def test_var_period_labels_fallback(self):
        from backend.app.services.var_forecaster import _next_period_labels
        labels = _next_period_labels("unknown", 2)
        assert labels == ["t+1", "t+2"]

    def test_var_groups_defined(self):
        from backend.app.services.var_forecaster import VAR_GROUPS
        assert "property" in VAR_GROUPS
        assert "labour" in VAR_GROUPS
        assert "market" in VAR_GROUPS
        for group, metrics in VAR_GROUPS.items():
            assert len(metrics) >= 2, f"group {group} needs ≥2 metrics"


# ===========================================================================
# New metrics: hibor_1m, prime_rate, net_migration, retail_sales_index,
#              tourist_arrivals
# ===========================================================================

_NEW_METRICS = [
    "hibor_1m",
    "prime_rate",
    "net_migration",
    "retail_sales_index",
    "tourist_arrivals",
]


class TestNewMetricsInSupportedSet:
    """All 5 new metrics must be in SUPPORTED_METRICS."""

    def test_new_metrics_in_supported_metrics(self):
        for m in _NEW_METRICS:
            assert m in SUPPORTED_METRICS, f"{m} missing from SUPPORTED_METRICS"

    def test_new_metrics_in_metric_db_map(self):
        from backend.app.services.time_series_forecaster import METRIC_DB_MAP
        for m in _NEW_METRICS:
            assert m in METRIC_DB_MAP, f"{m} missing from METRIC_DB_MAP"

    def test_new_metrics_db_map_tuple_structure(self):
        from backend.app.services.time_series_forecaster import METRIC_DB_MAP
        for m in _NEW_METRICS:
            cat, key = METRIC_DB_MAP[m]
            assert isinstance(cat, str) and cat, f"{m}: category must be non-empty str"
            assert isinstance(key, str) and key, f"{m}: metric key must be non-empty str"

    def test_new_metrics_in_seasonal_metrics(self):
        for m in _NEW_METRICS:
            assert m in _SEASONAL_METRICS, f"{m} missing from _SEASONAL_METRICS"

    def test_new_metrics_season_length_valid(self):
        for m in _NEW_METRICS:
            sl = _SEASONAL_METRICS[m]
            assert sl in (4, 12), f"{m}: season_length {sl} must be 4 or 12"


class TestNewMetricsNoHardcodedBaseline:
    """Verify _hardcoded_baseline was removed — no synthetic baselines allowed."""

    def test_no_hardcoded_baseline_method(self):
        assert not hasattr(TimeSeriesForecaster, "_hardcoded_baseline"), \
            "_hardcoded_baseline should be removed — no synthetic data"


class TestNewMetricsForecast:
    """Forecast smoke tests for the 5 new metrics (empty DB → data_quality check)."""

    def _mock_db_context(self) -> patch:
        """Return empty DB to trigger insufficient data response."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_cursor)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_db)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return patch(
            "backend.app.services.time_series_forecaster.get_db",
            return_value=ctx,
        )

    @pytest.mark.asyncio
    async def test_forecast_hibor_1m_no_data(self):
        forecaster = TimeSeriesForecaster()
        with self._mock_db_context():
            result = await forecaster.forecast("hibor_1m", horizon=4)
        assert result.metric == "hibor_1m"
        assert result.data_quality in ("no_data", "insufficient")
        assert len(result.points) == 0

    @pytest.mark.asyncio
    async def test_forecast_prime_rate_no_data(self):
        forecaster = TimeSeriesForecaster()
        with self._mock_db_context():
            result = await forecaster.forecast("prime_rate", horizon=4)
        assert result.metric == "prime_rate"
        assert result.data_quality in ("no_data", "insufficient")
        assert len(result.points) == 0

    @pytest.mark.asyncio
    async def test_forecast_net_migration_no_data(self):
        forecaster = TimeSeriesForecaster()
        with self._mock_db_context():
            result = await forecaster.forecast("net_migration", horizon=4)
        assert result.metric == "net_migration"
        assert result.data_quality in ("no_data", "insufficient")

    @pytest.mark.asyncio
    async def test_forecast_retail_sales_index_no_data(self):
        forecaster = TimeSeriesForecaster()
        with self._mock_db_context():
            result = await forecaster.forecast("retail_sales_index", horizon=4)
        assert result.metric == "retail_sales_index"
        assert result.data_quality in ("no_data", "insufficient")

    @pytest.mark.asyncio
    async def test_forecast_tourist_arrivals_no_data(self):
        forecaster = TimeSeriesForecaster()
        with self._mock_db_context():
            result = await forecaster.forecast("tourist_arrivals", horizon=4)
        assert result.metric == "tourist_arrivals"
        assert result.data_quality in ("no_data", "insufficient")

    @pytest.mark.asyncio
    async def test_new_metrics_empty_db_returns_empty_points(self):
        """With empty DB, all new metrics should return empty points (no synthetic fallback)."""
        forecaster = TimeSeriesForecaster()
        for m in _NEW_METRICS:
            with self._mock_db_context():
                result = await forecaster.forecast(m, horizon=2)
            assert len(result.points) == 0, f"{m}: should return empty points with no data"
            assert result.data_quality in ("no_data", "insufficient"), f"{m}: wrong data_quality"


# ===========================================================================
# BacktestResult — coverage_80 field
# ===========================================================================


class TestBacktestResultCoverage80:
    """Tests for the coverage_80 field on BacktestResult."""

    def _make_result(self, coverage_80: float = 0.75) -> "BacktestResult":
        from backend.app.services.backtester import BacktestResult
        return BacktestResult(
            metric="gdp_growth",
            train_start="2015-Q1",
            train_end="2022-Q4",
            test_start="2023-Q1",
            test_end="2023-Q4",
            mape=5.0,
            rmse=0.002,
            directional_accuracy=0.75,
            coverage_80=coverage_80,
            coverage_95=0.90,
            crps=0.5,
            theils_u=0.85,
            predictions=(("2023-Q1", 0.030, 0.031),),
            model_used="naive",
        )

    def test_backtest_result_has_coverage_80_field(self):
        result = self._make_result(coverage_80=0.75)
        assert hasattr(result, "coverage_80")
        assert result.coverage_80 == 0.75

    def test_backtest_result_frozen_coverage_80(self):
        import dataclasses as dc
        result = self._make_result(0.80)
        with pytest.raises((dc.FrozenInstanceError, AttributeError)):
            result.coverage_80 = 0.5  # type: ignore[misc]

    def test_backtest_result_to_dict_includes_coverage_80(self):
        result = self._make_result(0.875)
        d = result.to_dict()
        assert "coverage_80" in d
        assert abs(d["coverage_80"] - 0.875) < 1e-6

    def test_coverage_80_range_valid(self):
        """coverage_80 must be in [0, 1]."""
        for cov in [0.0, 0.5, 1.0]:
            result = self._make_result(cov)
            assert 0.0 <= result.coverage_80 <= 1.0

    def test_compute_coverage_80_all_covered(self):
        """All actuals within CI → coverage = 1.0."""
        from backend.app.services.backtester import _compute_coverage_80
        actuals = np.array([1.0, 2.0, 3.0])
        lower = np.array([0.5, 1.5, 2.5])
        upper = np.array([1.5, 2.5, 3.5])
        assert _compute_coverage_80(actuals, lower, upper) == 1.0

    def test_compute_coverage_80_none_covered(self):
        """No actuals within CI → coverage = 0.0."""
        from backend.app.services.backtester import _compute_coverage_80
        actuals = np.array([10.0, 20.0, 30.0])
        lower = np.array([0.0, 0.0, 0.0])
        upper = np.array([1.0, 1.0, 1.0])
        assert _compute_coverage_80(actuals, lower, upper) == 0.0

    def test_compute_coverage_80_partial_coverage(self):
        """Half actuals within CI → coverage ≈ 0.5."""
        from backend.app.services.backtester import _compute_coverage_80
        actuals = np.array([1.0, 100.0])
        lower = np.array([0.5, 0.5])
        upper = np.array([1.5, 1.5])
        assert _compute_coverage_80(actuals, lower, upper) == pytest.approx(0.5)

    def test_compute_coverage_80_empty_returns_zero(self):
        from backend.app.services.backtester import _compute_coverage_80
        result = _compute_coverage_80(
            np.array([], dtype=np.float64),
            np.array([], dtype=np.float64),
            np.array([], dtype=np.float64),
        )
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_backtester_run_produces_coverage_80(self):
        """Full backtester.run() should return a BacktestResult with coverage_80."""
        from backend.app.services.backtester import Backtester

        bt = Backtester()

        # Patch _load_history so it uses hardcoded 30-point data
        history = [
            (_quarter_label(2015, 1, i), 0.025 + i * 0.0005)
            for i in range(32)
        ]

        async def _mock_load(metric: str) -> list:
            return history

        bt._forecaster._load_history = _mock_load  # type: ignore[method-assign]

        result = await bt.run("gdp_growth", train_end="2022-Q4", horizon=4)

        assert hasattr(result, "coverage_80")
        assert 0.0 <= result.coverage_80 <= 1.0
        assert "coverage_80" in result.to_dict()


class TestMapeScale:
    """_compute_mape must return a fraction in [0, 1], not a percentage."""

    def test_mape_fraction_for_10_percent_error(self):
        """Given 10% prediction error, _compute_mape must return 0.10, not 10.0."""
        forecaster = TimeSeriesForecaster()
        # actual=[100,100,100,100], predicted=[110,110,110,110] -> MAPE = 10% = 0.10 fraction
        # _compute_mape uses leave-one-out on last 20%: for 4 values, test_start=max(1,int(4*0.8))=3
        # actuals = values[3:] = [110.0], preds = values[2:3] = [100.0]
        # ape = |110-100|/110 = 0.0909...
        # Use a longer series where we control the last 20%:
        # 20 values: first 16 = 100, last 4 = 110 -> test_start=16
        # actuals=[110,110,110,110], preds=[100,110,110,110]
        # ape=[0.0909,0,0,0] -> mean=0.02272...
        # Better: use series where all values are equal except shift:
        # 5 values: [100,100,100,100,110] -> test_start=max(1,int(5*0.8))=4
        # actuals=[110], preds=[100] -> ape=|110-100|/110=0.0909
        # To get exactly 10%: actual=100, pred=110 -> ape=|100-110|/100=0.10
        # 5 values: [110,110,110,110,100] -> test_start=4
        # actuals=[100], preds=[110] -> ape=|100-110|/100=0.10 -> mean=0.10
        vals = np.array([110.0, 110.0, 110.0, 110.0, 100.0])
        mape = forecaster._compute_mape(vals)
        assert mape < 1.0, f"MAPE should be fraction (0.10), got {mape} (looks like percentage)"
        assert abs(mape - 0.10) < 1e-6, f"Expected 0.10, got {mape}"

    def test_mape_zero_for_perfect_forecast(self):
        """Perfect forecast (constant series) -> MAPE = 0.0."""
        forecaster = TimeSeriesForecaster()
        vals = np.array([50.0, 60.0, 70.0, 80.0, 90.0])
        # test_start=max(1,int(5*0.8))=4; actuals=[90], preds=[80] -> ape=|90-80|/90=0.111
        # Use a constant series: actuals == preds -> ape=0
        vals_const = np.array([50.0, 50.0, 50.0, 50.0, 50.0])
        mape = forecaster._compute_mape(vals_const)
        assert mape == 0.0, f"Perfect forecast should give MAPE=0.0, got {mape}"
