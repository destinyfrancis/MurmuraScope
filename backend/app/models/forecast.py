"""Time series forecast result models for HKSimEngine.

All dataclasses are frozen (immutable) per project coding style.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ForecastPoint:
    """A single forecasted value with confidence intervals.

    Attributes:
        period: Human-readable period label (e.g. ``"2024-Q2"``).
        value: Point forecast (median estimate).
        lower_80: Lower bound of the 80% prediction interval.
        upper_80: Upper bound of the 80% prediction interval.
        lower_95: Lower bound of the 95% prediction interval.
        upper_95: Upper bound of the 95% prediction interval.
    """

    period: str
    value: float
    lower_80: float
    upper_80: float
    lower_95: float
    upper_95: float

    def to_dict(self) -> dict:
        """Serialise to a plain dict for JSON responses."""
        return {
            "period": self.period,
            "value": self.value,
            "lower_80": self.lower_80,
            "upper_80": self.upper_80,
            "lower_95": self.lower_95,
            "upper_95": self.upper_95,
        }

    @property
    def interval_width_80(self) -> float:
        """Width of the 80% interval."""
        return self.upper_80 - self.lower_80

    @property
    def interval_width_95(self) -> float:
        """Width of the 95% interval."""
        return self.upper_95 - self.lower_95


@dataclass(frozen=True)
class ForecastResult:
    """Complete forecast for a single economic metric.

    Attributes:
        metric: Metric identifier (e.g. ``"ccl_index"``).
        horizon: Number of periods forecasted.
        points: Ordered sequence of ForecastPoint from t+1 to t+horizon.
        model_used: Model name — ``"AutoARIMA"`` or ``"naive"``.
        fit_quality: In-sample fit quality score (lower is better for MAPE,
                     higher is better for R²). Interpretation depends on metric.
    """

    metric: str
    horizon: int
    points: list[ForecastPoint]
    model_used: str  # "AutoARIMA" or "naive"
    fit_quality: float  # MAPE fraction [0-1] for AutoARIMA, or 0.0 for naive
    data_quality: str = "real_data"  # "real_data" | "partial_real" | "insufficient" | "no_data"
    diagnostics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialise to a plain dict for JSON responses."""
        result = {
            "metric": self.metric,
            "horizon": self.horizon,
            "points": [p.to_dict() for p in self.points],
            "model_used": self.model_used,
            "fit_quality": self.fit_quality,
            "data_quality": self.data_quality,
        }
        if self.diagnostics:
            result["diagnostics"] = self.diagnostics
        return result

    @property
    def point_values(self) -> list[float]:
        """Return just the point forecast values in period order."""
        return [p.value for p in self.points]

    @property
    def period_labels(self) -> list[str]:
        """Return the period labels in order."""
        return [p.period for p in self.points]
