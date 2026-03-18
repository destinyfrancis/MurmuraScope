# backend/app/services/validation_reporter.py
"""Automated backtest reporting service.

Generates human-readable validation reports comparing simulation predictions
against historical HK macro data.  Wraps RetrospectiveValidator and formats
results into structured summary dicts suitable for the API or logging.

Usage::

    reporter = ValidationReporter()
    report = await reporter.generate("2022-Q1", "2023-Q4")
    print(report["summary"])
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from backend.app.services.retrospective_validator import (
    RetrospectiveValidator,
    ValidationResult,
)
from backend.app.utils.logger import get_logger

logger = get_logger(__name__)

# Thresholds for interpreting metric quality.
_DIRECTIONAL_GOOD = 0.65   # >= 65% directional accuracy is considered good
_PEARSON_GOOD = 0.50       # |r| >= 0.50 is considered meaningful correlation
_MAPE_GOOD = 0.15          # MAPE <= 15% is considered good

_GRADE_THRESHOLDS: list[tuple[float, str]] = [
    (0.80, "A"),
    (0.65, "B"),
    (0.50, "C"),
    (0.35, "D"),
    (0.0,  "F"),
]


def _score_metric(result: ValidationResult) -> float:
    """Compute a composite score [0, 1] from the three validation metrics.

    Weights:
      - Directional accuracy: 40%
      - |Pearson r|: 40%
      - 1 - min(MAPE, 1): 20%
    """
    dir_score = result.directional_accuracy
    corr_score = abs(result.pearson_r)
    mape_score = max(0.0, 1.0 - min(result.mape, 1.0))
    return 0.4 * dir_score + 0.4 * corr_score + 0.2 * mape_score


def _grade(score: float) -> str:
    for threshold, grade in _GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return "F"


def _interpret(result: ValidationResult) -> str:
    """Return a one-line interpretation string for a single metric result."""
    dir_ok = result.directional_accuracy >= _DIRECTIONAL_GOOD
    corr_ok = abs(result.pearson_r) >= _PEARSON_GOOD
    mape_ok = result.mape <= _MAPE_GOOD

    good_count = sum([dir_ok, corr_ok, mape_ok])
    if good_count == 3:
        return "Strong predictive signal across all three metrics."
    if good_count == 2:
        return "Moderate predictive signal; at least one metric needs improvement."
    if good_count == 1:
        parts: list[str] = []
        if dir_ok:
            parts.append("directional trend captured")
        if corr_ok:
            parts.append("meaningful correlation found")
        if mape_ok:
            parts.append("magnitude error acceptable")
        return "Weak signal — only " + ", ".join(parts) + "."
    return "Poor predictive signal — model requires recalibration for this metric."


class ValidationReporter:
    """Generate structured backtest reports over a period range."""

    def __init__(self) -> None:
        self._validator = RetrospectiveValidator()

    async def generate(
        self,
        period_start: str,
        period_end: str,
        metrics: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run validation and return a structured report dict.

        Args:
            period_start: Start quarter, e.g. '2020-Q1'.
            period_end: End quarter, e.g. '2023-Q4'.
            metrics: Optional subset of metrics to include.

        Returns:
            Dict with keys:
              - period_start, period_end
              - metrics_validated: int
              - overall_grade: str (A-F)
              - overall_score: float [0,1]
              - summary: str (human-readable)
              - results: list[dict] — one entry per validated metric, sorted
                by score descending
        """
        try:
            results = await self._validator.validate(
                period_start=period_start,
                period_end=period_end,
                metrics=metrics,
            )
        except Exception as exc:
            logger.warning("ValidationReporter: validation failed: %s", exc)
            results = []

        if not results:
            return {
                "period_start": period_start,
                "period_end": period_end,
                "metrics_validated": 0,
                "overall_grade": "N/A",
                "overall_score": 0.0,
                "summary": "Insufficient data for validation.",
                "results": [],
            }

        metric_rows = []
        for r in results:
            score = _score_metric(r)
            metric_rows.append({
                **asdict(r),
                "composite_score": round(score, 4),
                "grade": _grade(score),
                "interpretation": _interpret(r),
            })

        metric_rows.sort(key=lambda x: x["composite_score"], reverse=True)

        scores = [row["composite_score"] for row in metric_rows]
        overall_score = sum(scores) / len(scores)
        overall_grade = _grade(overall_score)

        good_metrics = [
            row["metric"] for row in metric_rows if row["composite_score"] >= 0.50
        ]
        poor_metrics = [
            row["metric"] for row in metric_rows if row["composite_score"] < 0.35
        ]

        summary_parts: list[str] = [
            f"Validated {len(results)} metrics for {period_start}–{period_end}.",
            f"Overall grade: {overall_grade} (score={overall_score:.2f}).",
        ]
        if good_metrics:
            summary_parts.append(
                f"Strong predictors: {', '.join(good_metrics)}."
            )
        if poor_metrics:
            summary_parts.append(
                f"Needs recalibration: {', '.join(poor_metrics)}."
            )

        logger.info(
            "ValidationReport %s→%s: grade=%s score=%.2f metrics=%d",
            period_start, period_end, overall_grade, overall_score, len(results),
        )

        return {
            "period_start": period_start,
            "period_end": period_end,
            "metrics_validated": len(results),
            "overall_grade": overall_grade,
            "overall_score": round(overall_score, 4),
            "summary": " ".join(summary_parts),
            "results": metric_rows,
        }

    async def generate_multi_period(
        self,
        periods: list[tuple[str, str]],
    ) -> list[dict[str, Any]]:
        """Generate reports for multiple period ranges sequentially.

        Args:
            periods: List of (period_start, period_end) tuples.

        Returns:
            List of report dicts in the same order as input.
        """
        reports: list[dict[str, Any]] = []
        for start, end in periods:
            report = await self.generate(start, end)
            reports.append(report)
        return reports
