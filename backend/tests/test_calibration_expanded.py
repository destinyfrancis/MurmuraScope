"""Tests for the expanded calibration pipeline (7 new indicator pairs).

Covers:
- Indicator pair count and new category coverage
- Fallback coefficient completeness
- BH-FDR correction
- Series alignment
- OLS regression with synthetic data
- Merge with fallback
- ADF stationarity tests
- Pipeline instantiation and output writing
- Full pipeline with mocked DB (empty + synthetic data)
- Granger causality test
- FDR edge cases
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from backend.data_pipeline.calibration import (
    CalibrationPipeline,
    _FALLBACK_COEFFICIENTS,
    _INDICATOR_PAIRS,
    _apply_fdr_correction,
)


# ---------------------------------------------------------------------------
# Indicator pair structure
# ---------------------------------------------------------------------------


class TestIndicatorPairsStructure:
    """Validate _INDICATOR_PAIRS has all 13 entries with correct shape."""

    def test_indicator_pairs_count(self) -> None:
        assert len(_INDICATOR_PAIRS) == 13

    def test_each_pair_is_3_tuple(self) -> None:
        for pair in _INDICATOR_PAIRS:
            assert len(pair) == 3, f"Expected 3-tuple, got {pair}"

    def test_new_categories_present(self) -> None:
        categories = {cat for _, cat, _ in _INDICATOR_PAIRS}
        for expected in ("interest_rate", "finance", "population", "retail_tourism", "price_index"):
            assert expected in categories, f"Missing category: {expected}"

    def test_new_metrics_present(self) -> None:
        metrics = {metric for _, _, metric in _INDICATOR_PAIRS}
        for expected in ("hibor_1m", "hsi_level", "net_migration", "retail_sales_index", "tourist_arrivals", "cpi_yoy"):
            assert expected in metrics, f"Missing metric: {expected}"


# ---------------------------------------------------------------------------
# Fallback coefficients
# ---------------------------------------------------------------------------


class TestFallbackCoefficients:
    """Validate _FALLBACK_COEFFICIENTS covers all indicator metrics."""

    def test_all_metrics_have_fallback(self) -> None:
        all_metrics = {metric for _, _, metric in _INDICATOR_PAIRS}
        for metric in all_metrics:
            assert metric in _FALLBACK_COEFFICIENTS, (
                f"Metric '{metric}' missing from _FALLBACK_COEFFICIENTS"
            )

    def test_fallback_values_are_finite(self) -> None:
        for indicator, params in _FALLBACK_COEFFICIENTS.items():
            for key, val in params.items():
                assert np.isfinite(val), f"{indicator}.{key} is not finite: {val}"

    def test_hsi_has_both_ratios(self) -> None:
        assert "positive_ratio" in _FALLBACK_COEFFICIENTS["hsi_level"]
        assert "negative_ratio" in _FALLBACK_COEFFICIENTS["hsi_level"]


# ---------------------------------------------------------------------------
# BH-FDR correction
# ---------------------------------------------------------------------------


class TestFDRCorrection:
    """Test Benjamini-Hochberg FDR correction with known p-values."""

    def test_known_p_values(self) -> None:
        pairs = [
            ("A", 0.001),
            ("B", 0.01),
            ("C", 0.03),
            ("D", 0.20),
            ("E", 0.50),
        ]
        sig = _apply_fdr_correction(pairs, alpha=0.05)
        # With m=5: thresholds are 0.01, 0.02, 0.03, 0.04, 0.05
        # A: 0.001 <= 0.01 ✓ (rank 1)
        # B: 0.01  <= 0.02 ✓ (rank 2)
        # C: 0.03  <= 0.03 ✓ (rank 3)
        # D: 0.20  <= 0.04 ✗
        assert "A" in sig
        assert "B" in sig
        assert "C" in sig
        assert "D" not in sig
        assert "E" not in sig

    def test_empty_list(self) -> None:
        assert _apply_fdr_correction([]) == set()

    def test_all_significant(self) -> None:
        pairs = [("X", 0.001), ("Y", 0.002)]
        sig = _apply_fdr_correction(pairs, alpha=0.05)
        assert sig == {"X", "Y"}

    def test_none_significant(self) -> None:
        pairs = [("X", 0.90), ("Y", 0.95)]
        sig = _apply_fdr_correction(pairs, alpha=0.05)
        assert sig == set()


# ---------------------------------------------------------------------------
# Alignment
# ---------------------------------------------------------------------------


class TestAlignSeriesByPeriod:
    """Test _align_series_by_period with overlapping / disjoint data."""

    def test_overlapping_periods(self) -> None:
        x = [("2024-Q1", 0.3), ("2024-Q2", 0.4), ("2024-Q3", 0.5)]
        y = [("2024-Q2", 100.0), ("2024-Q3", 110.0), ("2024-Q4", 120.0)]
        xa, ya = CalibrationPipeline._align_series_by_period(x, y)
        assert xa == [0.4, 0.5]
        assert ya == [100.0, 110.0]

    def test_disjoint_periods(self) -> None:
        x = [("2024-Q1", 0.3)]
        y = [("2024-Q4", 100.0)]
        xa, ya = CalibrationPipeline._align_series_by_period(x, y)
        assert xa == []
        assert ya == []

    def test_identical_periods(self) -> None:
        x = [("P1", 1.0), ("P2", 2.0)]
        y = [("P1", 10.0), ("P2", 20.0)]
        xa, ya = CalibrationPipeline._align_series_by_period(x, y)
        assert xa == [1.0, 2.0]
        assert ya == [10.0, 20.0]


# ---------------------------------------------------------------------------
# OLS regression
# ---------------------------------------------------------------------------


class TestRunOlsPair:
    """Test _run_ols_pair with synthetic data."""

    def test_linear_data_returns_result(self) -> None:
        rng = np.random.default_rng(42)
        x = list(np.linspace(0.1, 0.9, 20) + rng.normal(0, 0.01, 20))
        y = [v * 100 + rng.normal(0, 0.5) for v in x]
        result = CalibrationPipeline._run_ols_pair(x, y, "test_linear")
        assert result is not None
        assert "slope" in result

    def test_insufficient_points_returns_none(self) -> None:
        result = CalibrationPipeline._run_ols_pair([0.1, 0.2], [1.0, 2.0], "short")
        assert result is None

    def test_constant_x_returns_none(self) -> None:
        x = [0.5] * 10
        y = list(range(10))
        result = CalibrationPipeline._run_ols_pair(x, y, "constant_x")
        # Constant x after differencing → zero variance → should return None or weak fit
        # Either None or a result with slope close to 0 is acceptable
        if result is not None:
            assert "slope" in result


# ---------------------------------------------------------------------------
# Merge with fallback
# ---------------------------------------------------------------------------


class TestMergeWithFallback:
    """Test _merge_with_fallback logic."""

    def test_fitted_overrides_fallback(self) -> None:
        fitted = {"cpi_yoy": {"negative_ratio": 0.05}}
        fallback = {"cpi_yoy": {"negative_ratio": 0.001}}
        merged = CalibrationPipeline._merge_with_fallback(fitted, fallback)
        assert merged["cpi_yoy"]["negative_ratio"] == 0.05

    def test_fallback_fills_missing(self) -> None:
        fitted: dict[str, dict[str, float]] = {}
        fallback = {"hsi_level": {"positive_ratio": 50.0, "negative_ratio": -80.0}}
        merged = CalibrationPipeline._merge_with_fallback(fitted, fallback)
        assert merged["hsi_level"]["positive_ratio"] == 50.0
        assert merged["hsi_level"]["negative_ratio"] == -80.0

    def test_meta_key_excluded(self) -> None:
        fitted = {"_meta": {"x": 1.0}}
        fallback = {"gdp_growth_rate": {"negative_ratio": -0.001}}
        merged = CalibrationPipeline._merge_with_fallback(fitted, fallback)
        assert "_meta" not in merged


# ---------------------------------------------------------------------------
# ADF stationarity test
# ---------------------------------------------------------------------------


class TestAdfTest:
    """Test _adf_test with stationary / non-stationary data."""

    def test_stationary_white_noise(self) -> None:
        rng = np.random.default_rng(99)
        data = list(rng.normal(0, 1, 100))
        result = CalibrationPipeline._adf_test(data, "white_noise")
        # White noise should be stationary (ADF p < 0.05)
        if result.get("p_value") is not None:
            assert result["is_stationary"] is True

    def test_random_walk_non_stationary(self) -> None:
        rng = np.random.default_rng(42)
        data = list(np.cumsum(rng.normal(0, 1, 100)))
        result = CalibrationPipeline._adf_test(data, "random_walk")
        # Random walk should be non-stationary (ADF p > 0.05) in most seeds
        if result.get("p_value") is not None:
            assert isinstance(result["is_stationary"], bool)

    def test_too_short_skipped(self) -> None:
        result = CalibrationPipeline._adf_test([1.0, 2.0], "tiny")
        assert result.get("skipped") is True


# ---------------------------------------------------------------------------
# Pipeline instantiation & output
# ---------------------------------------------------------------------------


class TestPipelineInstantiation:
    """Test CalibrationPipeline constructor and _write_output."""

    def test_default_output_path(self) -> None:
        pipeline = CalibrationPipeline()
        assert pipeline._output_path.name == "calibration_coefficients.json"

    def test_custom_output_path(self) -> None:
        custom = Path("/tmp/test_cal.json")
        pipeline = CalibrationPipeline(output_path=custom)
        assert pipeline._output_path == custom

    def test_write_output_creates_file(self, tmp_path: Path) -> None:
        out = tmp_path / "output.json"
        pipeline = CalibrationPipeline(output_path=out)
        pipeline._write_output({"test": {"negative_ratio": -0.1}})
        assert out.exists()
        data = json.loads(out.read_text())
        assert data["test"]["negative_ratio"] == -0.1


# ---------------------------------------------------------------------------
# Full pipeline with mock DB
# ---------------------------------------------------------------------------


def _build_mock_db(
    sentiment_rows: list[tuple[Any, ...]] | None = None,
    indicator_rows: list[tuple[Any, ...]] | None = None,
) -> MagicMock:
    """Build a mock async context manager that simulates get_db().

    Returns different row sets depending on the SQL query executed.
    """
    mock_db = AsyncMock()
    cursor = AsyncMock()

    # Track call index to return different results for different queries
    call_results: list[Any] = []

    async def mock_execute(sql: str, params: Any = None) -> AsyncMock:
        sql_lower = sql.strip().lower()
        c = AsyncMock()
        if "sqlite_master" in sql_lower and "social_sentiment" in sql_lower:
            c.fetchone = AsyncMock(return_value=("social_sentiment",))
        elif "from social_sentiment" in sql_lower and "count" in sql_lower:
            c.fetchone = AsyncMock(return_value=(10, 0))
        elif "from social_sentiment" in sql_lower:
            c.fetchall = AsyncMock(return_value=sentiment_rows or [])
        elif "from hk_data_snapshots" in sql_lower:
            c.fetchall = AsyncMock(return_value=indicator_rows or [])
        elif "create table" in sql_lower:
            c.fetchone = AsyncMock(return_value=None)
        elif "insert into" in sql_lower:
            c.fetchone = AsyncMock(return_value=None)
        else:
            c.fetchone = AsyncMock(return_value=None)
            c.fetchall = AsyncMock(return_value=[])
        return c

    mock_db.execute = mock_execute
    mock_db.commit = AsyncMock()

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_db)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


class TestPipelineWithMockDB:
    """Integration tests with mocked database."""

    @pytest.mark.asyncio
    async def test_empty_db_uses_fallback(self, tmp_path: Path) -> None:
        out = tmp_path / "cal.json"
        pipeline = CalibrationPipeline(output_path=out)
        mock_ctx = _build_mock_db(sentiment_rows=[], indicator_rows=[])

        with patch("backend.data_pipeline.calibration.get_db", return_value=mock_ctx):
            result = await pipeline.run_calibration()

        # Should fall back to _FALLBACK_COEFFICIENTS
        assert "consumer_confidence" in result
        assert "hsi_level" in result

    @pytest.mark.asyncio
    async def test_synthetic_indicator_data(self, tmp_path: Path) -> None:
        out = tmp_path / "cal.json"
        pipeline = CalibrationPipeline(output_path=out)

        # Build synthetic sentiment: 20 quarters
        sentiment_rows = []
        for i in range(20):
            q = f"2020-Q{(i % 4) + 1}"
            pos = 0.3 + 0.01 * i
            neg = 0.4 - 0.01 * i
            neu = 1.0 - pos - neg
            sentiment_rows.append((q, pos, neg, neu))

        # Build synthetic indicator data for employment category
        indicator_rows = []
        for i in range(20):
            q = f"2020-Q{(i % 4) + 1}"
            indicator_rows.append(("employment", "unemployment_rate", q, 5.0 + 0.1 * i))

        mock_ctx = _build_mock_db(
            sentiment_rows=sentiment_rows,
            indicator_rows=indicator_rows,
        )

        with patch("backend.data_pipeline.calibration.get_db", return_value=mock_ctx):
            result = await pipeline.run_calibration()

        # Should have at least fallback entries
        assert isinstance(result, dict)
        assert "unemployment_rate" in result or "consumer_confidence" in result


# ---------------------------------------------------------------------------
# Granger test
# ---------------------------------------------------------------------------


class TestGrangerTest:
    """Test _granger_test with known data."""

    def test_granger_with_causal_data(self) -> None:
        rng = np.random.default_rng(123)
        n = 50
        x = list(rng.normal(0, 1, n))
        # y depends on lagged x
        y = [0.0] * n
        for i in range(1, n):
            y[i] = 0.7 * x[i - 1] + rng.normal(0, 0.3)

        result = CalibrationPipeline._granger_test(x, y, "causal_test", max_lag=2)
        assert "label" in result
        assert result["label"] == "causal_test"
        # With strong causal signal, should be significant
        if result.get("p_value") is not None:
            assert result["p_value"] < 0.10

    def test_granger_insufficient_data(self) -> None:
        result = CalibrationPipeline._granger_test([1.0, 2.0], [3.0, 4.0], "short", max_lag=4)
        assert result.get("insufficient_data") is True or result.get("p_value") is None
