# backend/tests/test_phase3_validation.py
"""Unit tests for Phase 3 validation framework.

Covers:
- Calibration R² threshold change (0.30)
- ValidationReporter._score_metric + _grade + _interpret
- ValidationReporter.generate (mocked validator)
- RetrospectiveValidator.bootstrap_ci
- RetrospectiveValidator.kfold_validate (mocked)
- SensitivityAnalyzer._make_grid + _make_summary
- SensitivityAnalyzer._PatchedCoefficients
- TimeSeriesForecaster: _MIN_ARIMA_POINTS guard
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from backend.app.services.calibrated_coefficients import CalibratedCoefficients
from backend.app.services.retrospective_validator import (
    RetrospectiveValidator,
    ValidationResult,
    _enumerate_periods,
    _find_best_timing_offset,
    _parse_period,
    _period_to_sortable,
)
from backend.app.services.sensitivity_analyzer import (
    SensitivityAnalyzer,
    SensitivityRow,
    _make_grid,
    _make_summary,
    _PatchedCoefficients,
)
from backend.app.services.validation_reporter import (
    ValidationReporter,
    _grade,
    _interpret,
    _score_metric,
)


# ---------------------------------------------------------------------------
# 3.1 — Calibration R² threshold
# ---------------------------------------------------------------------------

def test_calibration_r2_threshold_is_30_percent() -> None:
    import backend.data_pipeline.calibration as cal_module  # noqa: PLC0415
    assert cal_module._R_SQUARED_THRESHOLD == 0.30, (
        "R² threshold must be 0.30 (was raised from 0.10 in Phase 3)"
    )


# ---------------------------------------------------------------------------
# 3.x — TimeSeriesForecaster min ARIMA points guard
# ---------------------------------------------------------------------------

def test_min_arima_points_is_16() -> None:
    import backend.app.services.time_series_forecaster as ts  # noqa: PLC0415
    assert ts._MIN_ARIMA_POINTS == 16


# ---------------------------------------------------------------------------
# ValidationReporter helpers
# ---------------------------------------------------------------------------

def _make_result(**kwargs) -> ValidationResult:
    defaults = dict(
        metric="ccl_index",
        directional_accuracy=0.7,
        pearson_r=0.6,
        mape=0.10,
        timing_offset_quarters=0,
        n_observations=8,
        period_start="2020-Q1",
        period_end="2020-Q4",
    )
    defaults.update(kwargs)
    return ValidationResult(**defaults)


class TestScoreMetric:
    def test_perfect_result(self) -> None:
        # brier_score=0.0 gives BSS=1.0; all four components perfect → composite=1.0
        r = _make_result(directional_accuracy=1.0, pearson_r=1.0, mape=0.0, brier_score=0.0)
        assert _score_metric(r) == pytest.approx(1.0)

    def test_poor_result(self) -> None:
        # brier_score=0.25 gives BSS=0.0; all four components zero → composite=0.0
        r = _make_result(directional_accuracy=0.0, pearson_r=0.0, mape=1.0, brier_score=0.25)
        assert _score_metric(r) == pytest.approx(0.0)

    def test_typical_result(self) -> None:
        # Uninformative brier (default 0.25) contributes 0 skill; range check still valid
        r = _make_result(directional_accuracy=0.7, pearson_r=0.6, mape=0.10)
        score = _score_metric(r)
        assert 0.4 < score < 0.9


class TestGrade:
    def test_a_grade(self) -> None:
        assert _grade(0.85) == "A"

    def test_b_grade(self) -> None:
        assert _grade(0.70) == "B"

    def test_c_grade(self) -> None:
        assert _grade(0.55) == "C"

    def test_d_grade(self) -> None:
        assert _grade(0.40) == "D"

    def test_f_grade(self) -> None:
        assert _grade(0.20) == "F"


class TestInterpret:
    def test_strong_signal(self) -> None:
        r = _make_result(directional_accuracy=0.75, pearson_r=0.60, mape=0.10)
        text = _interpret(r)
        assert "Strong" in text

    def test_poor_signal(self) -> None:
        r = _make_result(directional_accuracy=0.40, pearson_r=0.10, mape=0.50)
        text = _interpret(r)
        assert "Poor" in text or "Weak" in text


class TestValidationReporterGenerate:
    @pytest.mark.asyncio
    async def test_generate_no_results(self) -> None:
        reporter = ValidationReporter()
        reporter._validator.validate = AsyncMock(return_value=[])
        report = await reporter.generate("2020-Q1", "2020-Q4")
        assert report["metrics_validated"] == 0
        assert report["overall_grade"] == "N/A"

    @pytest.mark.asyncio
    async def test_generate_with_results(self) -> None:
        reporter = ValidationReporter()
        mock_results = [
            _make_result(metric="ccl_index", directional_accuracy=0.8, pearson_r=0.7, mape=0.08),
            _make_result(metric="hsi_level", directional_accuracy=0.6, pearson_r=0.5, mape=0.20),
        ]
        reporter._validator.validate = AsyncMock(return_value=mock_results)
        report = await reporter.generate("2020-Q1", "2020-Q4")
        assert report["metrics_validated"] == 2
        assert report["overall_grade"] in {"A", "B", "C", "D", "F"}
        assert 0.0 <= report["overall_score"] <= 1.0
        assert len(report["results"]) == 2
        # Results sorted descending by composite_score
        scores = [r["composite_score"] for r in report["results"]]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_generate_exception_handled(self) -> None:
        reporter = ValidationReporter()
        reporter._validator.validate = AsyncMock(side_effect=ValueError("bad"))
        report = await reporter.generate("2020-Q1", "2020-Q4")
        assert report["metrics_validated"] == 0


# ---------------------------------------------------------------------------
# RetrospectiveValidator bootstrap_ci
# ---------------------------------------------------------------------------

class TestBootstrapCI:
    def test_empty_input(self) -> None:
        ci = RetrospectiveValidator.bootstrap_ci([])
        assert ci == {"mean": 0.0, "lower": 0.0, "upper": 0.0, "n_samples": 0}

    def test_single_value(self) -> None:
        ci = RetrospectiveValidator.bootstrap_ci([0.8])
        assert ci["mean"] == pytest.approx(0.8, abs=0.01)
        assert ci["n_samples"] == 1

    def test_ci_contains_mean(self) -> None:
        values = [0.5, 0.6, 0.7, 0.65, 0.55, 0.72, 0.61]
        ci = RetrospectiveValidator.bootstrap_ci(values, n_boot=500)
        assert ci["lower"] <= ci["mean"] <= ci["upper"]

    def test_ci_reasonable_width(self) -> None:
        # Wide-spread values → wider CI
        values = [0.0, 1.0, 0.5, 0.5]
        ci = RetrospectiveValidator.bootstrap_ci(values, n_boot=500)
        assert ci["upper"] - ci["lower"] > 0.0


# ---------------------------------------------------------------------------
# RetrospectiveValidator kfold_validate
# ---------------------------------------------------------------------------

class TestKfoldValidate:
    @pytest.mark.asyncio
    async def test_k_too_small_raises(self) -> None:
        v = RetrospectiveValidator()
        with pytest.raises(ValueError, match="k must be"):
            await v.kfold_validate("2020-Q1", "2023-Q4", k=1)

    @pytest.mark.asyncio
    async def test_kfold_returns_expected_keys(self) -> None:
        v = RetrospectiveValidator()
        mock_result = [
            _make_result(metric="ccl_index", directional_accuracy=0.7),
        ]
        v.validate = AsyncMock(return_value=mock_result)
        result = await v.kfold_validate("2020-Q1", "2023-Q4", k=4, metrics=["ccl_index"])
        assert "fold_results" in result
        assert "mean_directional_accuracy" in result
        assert "bootstrap_ci" in result
        assert result["k"] >= 2


# ---------------------------------------------------------------------------
# SensitivityAnalyzer helpers
# ---------------------------------------------------------------------------

class TestMakeGrid:
    def test_grid_has_correct_length(self) -> None:
        grid = _make_grid(0.5, n_steps=5, perturbation=0.25)
        assert len(grid) == 5

    def test_grid_near_zero_baseline(self) -> None:
        grid = _make_grid(0.0, n_steps=5, perturbation=0.25)
        assert len(grid) == 5

    def test_grid_is_ascending(self) -> None:
        grid = _make_grid(0.5, n_steps=5, perturbation=0.25)
        assert grid == sorted(grid)

    def test_grid_centred_on_baseline(self) -> None:
        baseline = 0.4
        grid = _make_grid(baseline, n_steps=5, perturbation=0.25)
        # midpoint should be close to baseline
        midpoint = grid[len(grid) // 2]
        assert abs(midpoint - baseline) < baseline * 0.30


class TestMakeSummary:
    def test_empty_rows(self) -> None:
        text = _make_summary([], "2020-Q1", "2023-Q4")
        assert "No sensitivity" in text

    def test_summary_mentions_top_param(self) -> None:
        rows = [
            SensitivityRow("negative_ratio", "ccl_index", -0.001, 0.15, "negative"),
            SensitivityRow("positive_ratio", "hsi_level", 0.002, 0.05, "positive"),
        ]
        text = _make_summary(rows, "2020-Q1", "2023-Q4")
        assert "negative_ratio" in text
        assert "ccl_index" in text


class TestPatchedCoefficients:
    def test_overrides_target(self) -> None:
        base = MagicMock()
        base.get_all.return_value = {"negative_ratio": -0.002, "positive_ratio": 0.001}
        patched = _PatchedCoefficients(base, "negative_ratio", "ccl_index", -0.010)
        result = patched.get_all("ccl_index")
        assert result["negative_ratio"] == pytest.approx(-0.010)

    def test_passthrough_other_metric(self) -> None:
        base = MagicMock()
        base.get_all.return_value = {"negative_ratio": -0.002}
        patched = _PatchedCoefficients(base, "negative_ratio", "hsi_level", 0.999)
        # For a different metric, should not override
        result = patched.get_all("ccl_index")
        assert result["negative_ratio"] == pytest.approx(-0.002)


# ---------------------------------------------------------------------------
# Brier skill score integration in _score_metric
# ---------------------------------------------------------------------------

class TestBrierScoreIntegration:
    """_score_metric must include Brier skill score in composite."""

    def _make_result(self, *, directional_accuracy, pearson_r, mape, brier_score):
        return ValidationResult(
            metric="test_metric",
            directional_accuracy=directional_accuracy,
            pearson_r=pearson_r,
            mape=mape,
            brier_score=brier_score,
            timing_offset_quarters=0,
            n_observations=20,
            period_start="2020-Q1",
            period_end="2022-Q4",
        )

    def test_perfect_brier_raises_score(self):
        """Perfect Brier (0.0) must produce higher composite than uninformative (0.25)."""
        base = dict(directional_accuracy=0.6, pearson_r=0.5, mape=0.2)
        perfect = _score_metric(self._make_result(**base, brier_score=0.0))
        baseline = _score_metric(self._make_result(**base, brier_score=0.25))
        assert perfect > baseline, (
            f"Perfect Brier score ({perfect:.4f}) should exceed uninformative ({baseline:.4f})"
        )

    def test_uninformative_brier_contributes_zero_skill(self):
        """Brier=0.25 (uninformative) must contribute 0 to composite."""
        r = self._make_result(directional_accuracy=0.7, pearson_r=0.6, mape=0.1, brier_score=0.25)
        score = _score_metric(r)
        expected = 0.3 * 0.7 + 0.3 * 0.6 + 0.2 * (1.0 - 0.1) + 0.2 * 0.0
        assert abs(score - expected) < 1e-6, f"Expected {expected:.6f}, got {score:.6f}"

    def test_perfect_score_all_metrics(self):
        """Perfect result on all metrics must give composite = 1.0."""
        r = self._make_result(directional_accuracy=1.0, pearson_r=1.0, mape=0.0, brier_score=0.0)
        assert abs(_score_metric(r) - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# CalibratedCoefficients.get_all_by_sentiment (Phase 3 addition)
# ---------------------------------------------------------------------------

class TestGetAllBySentiment:
    def test_returns_dict(self) -> None:
        cc = CalibratedCoefficients()
        result = cc.get_all_by_sentiment("negative_ratio")
        assert isinstance(result, dict)

    def test_negative_ratio_includes_consumer_confidence(self) -> None:
        cc = CalibratedCoefficients()
        result = cc.get_all_by_sentiment("negative_ratio")
        # consumer_confidence has negative_ratio in defaults (may be overridden by file)
        assert "consumer_confidence" in result
        assert isinstance(result["consumer_confidence"], float)

    def test_unknown_sentiment_metric(self) -> None:
        cc = CalibratedCoefficients()
        result = cc.get_all_by_sentiment("__nonexistent__")
        assert result == {}
