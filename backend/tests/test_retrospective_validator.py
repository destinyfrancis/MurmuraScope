"""Tests for RetrospectiveValidator service.

~25 tests covering:
- ValidationResult dataclass creation
- _compute_metrics with known inputs
- _load_historical_series with mock DB
- validate() full pipeline
- _persist_results
- Edge cases (NaN, zero division, mismatched lengths, etc.)
"""

from __future__ import annotations

import math
from contextlib import asynccontextmanager
from dataclasses import asdict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.services.retrospective_validator import (
    MIN_METRICS_REQUIRED,
    VALIDATABLE_METRICS,
    RetrospectiveValidator,
    ValidationResult,
    _enumerate_periods,
    _find_best_timing_offset,
    _parse_period,
    _period_to_sortable,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_mock_db(rows_by_query: list[list[tuple]] | None = None):
    """Build an async context manager that yields a mock aiosqlite connection.

    If *rows_by_query* is provided, successive execute() calls return
    successive row lists.
    """
    queue = list(rows_by_query or [])

    class _MockCursor:
        def __init__(self, rows):
            self._rows = rows

        async def fetchall(self):
            return self._rows

    class _MockDB:
        def __init__(self):
            self._call_idx = 0

        async def execute(self, sql, params=None):
            if queue:
                rows = queue.pop(0)
            else:
                rows = []
            return _MockCursor(rows)

        async def commit(self):
            pass

    @asynccontextmanager
    async def _ctx():
        yield _MockDB()

    return _ctx


# ---------------------------------------------------------------------------
# ValidationResult dataclass tests
# ---------------------------------------------------------------------------


class TestValidationResult:
    def test_create_basic(self):
        r = ValidationResult(
            metric="hsi_level",
            directional_accuracy=0.75,
            pearson_r=0.85,
            mape=0.12,
            timing_offset_quarters=1,
            n_observations=4,
            period_start="2020-Q1",
            period_end="2020-Q4",
        )
        assert r.metric == "hsi_level"
        assert r.directional_accuracy == 0.75
        assert r.n_observations == 4

    def test_frozen(self):
        r = ValidationResult(
            metric="ccl_index",
            directional_accuracy=0.5,
            pearson_r=0.3,
            mape=0.2,
            timing_offset_quarters=0,
            n_observations=3,
            period_start="2021-Q1",
            period_end="2021-Q3",
        )
        with pytest.raises(AttributeError):
            r.metric = "other"  # type: ignore[misc]

    def test_asdict(self):
        r = ValidationResult(
            metric="gdp_growth",
            directional_accuracy=1.0,
            pearson_r=0.99,
            mape=0.01,
            timing_offset_quarters=-1,
            n_observations=8,
            period_start="2019-Q1",
            period_end="2020-Q4",
        )
        d = asdict(r)
        assert d["metric"] == "gdp_growth"
        assert d["pearson_r"] == 0.99
        assert isinstance(d, dict)


# ---------------------------------------------------------------------------
# _compute_metrics tests
# ---------------------------------------------------------------------------


class TestComputeMetrics:
    @pytest.mark.asyncio
    async def test_perfect_prediction(self):
        v = RetrospectiveValidator()
        actual = [100.0, 110.0, 120.0, 115.0]
        result = await v._compute_metrics(actual, actual)
        assert result["directional_accuracy"] == 1.0
        assert result["pearson_r"] == 1.0
        assert result["mape"] == 0.0

    @pytest.mark.asyncio
    async def test_opposite_direction(self):
        v = RetrospectiveValidator()
        predicted = [100.0, 110.0, 120.0, 130.0]
        actual = [100.0, 90.0, 80.0, 70.0]
        result = await v._compute_metrics(predicted, actual)
        assert result["directional_accuracy"] == 0.0
        assert result["pearson_r"] < 0

    @pytest.mark.asyncio
    async def test_zero_actuals(self):
        """When actuals are all zero, MAPE should be 0 (skip division)."""
        v = RetrospectiveValidator()
        predicted = [1.0, 2.0, 3.0]
        actual = [0.0, 0.0, 0.0]
        result = await v._compute_metrics(predicted, actual)
        assert result["mape"] == 0.0

    @pytest.mark.asyncio
    async def test_single_point(self):
        v = RetrospectiveValidator()
        result = await v._compute_metrics([42.0], [42.0])
        assert result["directional_accuracy"] == 0.0
        assert result["pearson_r"] == 0.0

    @pytest.mark.asyncio
    async def test_all_same_values(self):
        """Constant series: std=0, so pearson_r should be 0."""
        v = RetrospectiveValidator()
        result = await v._compute_metrics([5.0, 5.0, 5.0], [5.0, 5.0, 5.0])
        assert result["pearson_r"] == 0.0
        assert result["directional_accuracy"] == 1.0  # sign(0) == sign(0)


# ---------------------------------------------------------------------------
# _load_historical_series tests
# ---------------------------------------------------------------------------


class TestLoadHistoricalSeries:
    @pytest.mark.asyncio
    async def test_normal_case(self):
        """Should load rows and return sorted series per metric."""
        rows = [
            {"period": "2020-Q1", "value": 150.0},
            {"period": "2020-Q2", "value": 148.0},
        ]

        mock_db = _make_mock_db([rows] * len(VALIDATABLE_METRICS))

        with patch(
            "backend.app.services.retrospective_validator.get_db",
            return_value=mock_db(),
        ):
            v = RetrospectiveValidator()
            result = await v._load_historical_series("2020-Q1", "2020-Q2")

        # At least one metric should have data
        assert len(result) > 0
        for series in result.values():
            assert len(series) == 2

    @pytest.mark.asyncio
    async def test_empty_result(self):
        """Should return empty dict when DB has no matching rows."""
        mock_db = _make_mock_db([[] for _ in range(len(VALIDATABLE_METRICS))])

        with patch(
            "backend.app.services.retrospective_validator.get_db",
            return_value=mock_db(),
        ):
            v = RetrospectiveValidator()
            result = await v._load_historical_series("2020-Q1", "2020-Q4")

        assert result == {}

    @pytest.mark.asyncio
    async def test_db_exception(self):
        """Should return empty dict on DB error."""

        @asynccontextmanager
        async def _failing_db():
            raise RuntimeError("DB gone")
            yield  # type: ignore[misc]  # pragma: no cover

        with patch(
            "backend.app.services.retrospective_validator.get_db",
            return_value=_failing_db(),
        ):
            v = RetrospectiveValidator()
            result = await v._load_historical_series("2020-Q1", "2020-Q2")

        assert result == {}


# ---------------------------------------------------------------------------
# validate() full pipeline tests
# ---------------------------------------------------------------------------


class TestValidatePipeline:
    @pytest.mark.asyncio
    async def test_normal_validation(self):
        """Full pipeline with mocked DB returning sufficient data."""
        # Build mock: _load_historical_series needs DB, _ensure_table needs DB,
        # _persist_results needs DB.
        rows = [
            {"period": "2020-Q1", "value": 100.0},
            {"period": "2020-Q2", "value": 105.0},
            {"period": "2020-Q3", "value": 110.0},
            {"period": "2020-Q4", "value": 108.0},
        ]

        # Return data for all metrics so we pass the MIN_METRICS_REQUIRED check
        all_rows = [rows] * len(VALIDATABLE_METRICS)

        mock_db = _make_mock_db(all_rows)

        with patch(
            "backend.app.services.retrospective_validator.get_db",
            side_effect=lambda: mock_db(),
        ):
            v = RetrospectiveValidator()
            results = await v.validate("2020-Q1", "2020-Q4")

        assert len(results) > 0
        for r in results:
            assert isinstance(r, ValidationResult)
            assert r.period_start == "2020-Q1"
            assert r.period_end == "2020-Q4"
            assert r.n_observations == 4

    @pytest.mark.asyncio
    async def test_insufficient_data_guard(self):
        """Should return empty list when < MIN_METRICS_REQUIRED have data."""
        # Return empty for all metrics
        mock_db = _make_mock_db([[] for _ in range(len(VALIDATABLE_METRICS))])

        with patch(
            "backend.app.services.retrospective_validator.get_db",
            side_effect=lambda: mock_db(),
        ):
            v = RetrospectiveValidator()
            results = await v.validate("2020-Q1", "2020-Q4")

        assert results == []

    @pytest.mark.asyncio
    async def test_single_metric(self):
        """Requesting a single metric returns empty when < MIN_METRICS_REQUIRED loadable."""
        rows = [
            {"period": "2020-Q1", "value": 20000.0},
            {"period": "2020-Q2", "value": 21000.0},
            {"period": "2020-Q3", "value": 19500.0},
            {"period": "2020-Q4", "value": 20500.0},
        ]

        # Only 1 metric requested, so only 1 is loadable (< MIN_METRICS_REQUIRED)
        all_rows = [rows] * len(VALIDATABLE_METRICS)
        mock_db = _make_mock_db(all_rows)

        with patch(
            "backend.app.services.retrospective_validator.get_db",
            side_effect=lambda: mock_db(),
        ):
            v = RetrospectiveValidator()
            results = await v.validate("2020-Q1", "2020-Q4", metrics=["hsi_level"])

        # Only 1 metric loadable which is < MIN_METRICS_REQUIRED (4)
        assert results == []

    @pytest.mark.asyncio
    async def test_all_metrics(self):
        """When all metrics have data, all should be validated."""
        rows = [
            {"period": "2020-Q1", "value": 50.0},
            {"period": "2020-Q2", "value": 55.0},
            {"period": "2020-Q3", "value": 52.0},
            {"period": "2020-Q4", "value": 58.0},
        ]

        all_rows = [rows] * (len(VALIDATABLE_METRICS) + 10)  # extra for ensure_table + persist
        mock_db = _make_mock_db(all_rows)

        with patch(
            "backend.app.services.retrospective_validator.get_db",
            side_effect=lambda: mock_db(),
        ):
            v = RetrospectiveValidator()
            results = await v.validate("2020-Q1", "2020-Q4")

        assert len(results) == len(VALIDATABLE_METRICS)

    @pytest.mark.asyncio
    async def test_invalid_period_format(self):
        """Should raise ValueError for bad period format."""
        v = RetrospectiveValidator()
        with pytest.raises(ValueError, match="Invalid period format"):
            await v.validate("2020-01", "2020-Q4")

    @pytest.mark.asyncio
    async def test_reversed_period_range(self):
        """Should raise ValueError when start >= end."""
        v = RetrospectiveValidator()
        with pytest.raises(ValueError, match="must be before"):
            await v.validate("2020-Q4", "2020-Q1")


# ---------------------------------------------------------------------------
# _persist_results tests
# ---------------------------------------------------------------------------


class TestPersistResults:
    @pytest.mark.asyncio
    async def test_normal_persist(self):
        """Should call execute for each result and commit."""
        execute_calls = []

        class _TrackingDB:
            async def execute(self, sql, params=None):
                execute_calls.append((sql, params))
                return MagicMock(fetchall=AsyncMock(return_value=[]))

            async def commit(self):
                pass

        @asynccontextmanager
        async def _mock_db():
            yield _TrackingDB()

        with patch(
            "backend.app.services.retrospective_validator.get_db",
            side_effect=lambda: _mock_db(),
        ):
            v = RetrospectiveValidator()
            results = [
                ValidationResult(
                    metric="hsi_level",
                    directional_accuracy=0.8,
                    pearson_r=0.9,
                    mape=0.05,
                    timing_offset_quarters=0,
                    n_observations=4,
                    period_start="2020-Q1",
                    period_end="2020-Q4",
                ),
            ]
            await v._persist_results(results)

        # At least 1 INSERT + 1 CREATE TABLE IF NOT EXISTS
        insert_calls = [c for c in execute_calls if "INSERT" in c[0]]
        assert len(insert_calls) == 1

    @pytest.mark.asyncio
    async def test_empty_results(self):
        """Should not call DB when results list is empty."""
        call_count = 0

        @asynccontextmanager
        async def _mock_db():
            nonlocal call_count
            call_count += 1
            yield MagicMock()

        with patch(
            "backend.app.services.retrospective_validator.get_db",
            side_effect=lambda: _mock_db(),
        ):
            v = RetrospectiveValidator()
            await v._persist_results([])

        # _persist_results returns early, but _ensure_table is NOT called
        # because the empty check is before _ensure_table
        assert call_count == 0

    @pytest.mark.asyncio
    async def test_table_creation(self):
        """_ensure_table should issue CREATE TABLE IF NOT EXISTS."""
        executed_sql: list[str] = []

        class _TrackingDB:
            async def execute(self, sql, params=None):
                executed_sql.append(sql)
                return MagicMock(fetchall=AsyncMock(return_value=[]))

            async def commit(self):
                pass

        @asynccontextmanager
        async def _mock_db():
            yield _TrackingDB()

        with patch(
            "backend.app.services.retrospective_validator.get_db",
            side_effect=lambda: _mock_db(),
        ):
            v = RetrospectiveValidator()
            await v._ensure_table()

        create_stmts = [s for s in executed_sql if "CREATE TABLE" in s]
        assert len(create_stmts) == 1
        assert "validation_runs" in create_stmts[0]


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_nan_in_predicted(self):
        """NaN values should be replaced with 0 and not crash."""
        v = RetrospectiveValidator()
        predicted = [100.0, float("nan"), 120.0]
        actual = [100.0, 110.0, 120.0]
        result = await v._compute_metrics(predicted, actual)
        assert not math.isnan(result["pearson_r"])
        assert not math.isnan(result["mape"])

    @pytest.mark.asyncio
    async def test_inf_in_predicted(self):
        """Inf values should be replaced with 0 and not crash."""
        v = RetrospectiveValidator()
        predicted = [100.0, float("inf"), 120.0]
        actual = [100.0, 110.0, 120.0]
        result = await v._compute_metrics(predicted, actual)
        assert math.isfinite(result["pearson_r"])
        assert math.isfinite(result["mape"])

    @pytest.mark.asyncio
    async def test_mismatched_lengths(self):
        """Should handle predicted and actual of different lengths."""
        v = RetrospectiveValidator()
        predicted = [100.0, 110.0, 120.0, 130.0, 140.0]
        actual = [100.0, 105.0, 110.0]
        result = await v._compute_metrics(predicted, actual)
        # Should use min(5, 3) = 3 observations
        assert result["directional_accuracy"] >= 0.0
        assert math.isfinite(result["pearson_r"])

    @pytest.mark.asyncio
    async def test_empty_arrays(self):
        """Empty input should return all zeros."""
        v = RetrospectiveValidator()
        result = await v._compute_metrics([], [])
        assert result == {"directional_accuracy": 0.0, "pearson_r": 0.0, "mape": 0.0}

    @pytest.mark.asyncio
    async def test_negative_mape_impossible(self):
        """MAPE should always be >= 0."""
        v = RetrospectiveValidator()
        predicted = [50.0, 60.0, 70.0]
        actual = [100.0, 200.0, 300.0]
        result = await v._compute_metrics(predicted, actual)
        assert result["mape"] >= 0.0

    @pytest.mark.asyncio
    async def test_boundary_period_same_quarter(self):
        """Same start and end quarter should raise ValueError."""
        v = RetrospectiveValidator()
        with pytest.raises(ValueError, match="must be before"):
            await v.validate("2020-Q1", "2020-Q1")


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestHelperFunctions:
    def test_parse_period_valid(self):
        assert _parse_period("2020-Q1") == (2020, 1)
        assert _parse_period("2025-Q4") == (2025, 4)

    def test_parse_period_invalid(self):
        with pytest.raises(ValueError):
            _parse_period("2020-01")
        with pytest.raises(ValueError):
            _parse_period("Q1-2020")
        with pytest.raises(ValueError):
            _parse_period("2020-Q5")

    def test_period_to_sortable(self):
        assert _period_to_sortable("2020-Q1") < _period_to_sortable("2020-Q2")
        assert _period_to_sortable("2019-Q4") < _period_to_sortable("2020-Q1")

    def test_enumerate_periods(self):
        periods = _enumerate_periods("2020-Q1", "2020-Q4")
        assert periods == ["2020-Q1", "2020-Q2", "2020-Q3", "2020-Q4"]

    def test_enumerate_periods_cross_year(self):
        periods = _enumerate_periods("2019-Q3", "2020-Q2")
        assert periods == ["2019-Q3", "2019-Q4", "2020-Q1", "2020-Q2"]

    def test_enumerate_periods_single(self):
        periods = _enumerate_periods("2020-Q2", "2020-Q2")
        assert periods == ["2020-Q2"]

    def test_find_best_timing_offset_identical(self):
        """Identical non-linear series should have offset 0."""
        # Use a non-linear series so shifted subsets don't correlate as well
        predicted = [1.0, 4.0, 2.0, 8.0, 3.0, 7.0, 1.0]
        actual = [1.0, 4.0, 2.0, 8.0, 3.0, 7.0, 1.0]
        assert _find_best_timing_offset(predicted, actual) == 0

    def test_find_best_timing_offset_short(self):
        """Very short series should return 0."""
        assert _find_best_timing_offset([1.0, 2.0], [1.0, 2.0]) == 0
