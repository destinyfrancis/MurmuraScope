"""Ensemble / Monte Carlo result models for HKSimEngine.

All dataclasses are frozen (immutable) per project coding style.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DistributionBand:
    """Percentile distribution band for a single simulation metric.

    Attributes:
        metric_name: Name of the metric (e.g. ``ccl_index_change``).
        p10: 10th percentile value across Monte Carlo trials.
        p25: 25th percentile value.
        p50: Median (50th percentile).
        p75: 75th percentile value.
        p90: 90th percentile value.
    """

    metric_name: str
    p10: float
    p25: float
    p50: float
    p75: float
    p90: float

    def to_dict(self) -> dict:
        """Serialise to a plain dict for JSON responses."""
        return {
            "metric_name": self.metric_name,
            "p10": self.p10,
            "p25": self.p25,
            "p50": self.p50,
            "p75": self.p75,
            "p90": self.p90,
        }

    @property
    def spread_90(self) -> float:
        """P90 - P10 inter-decile range."""
        return self.p90 - self.p10

    @property
    def iqr(self) -> float:
        """Interquartile range (P75 - P25)."""
        return self.p75 - self.p25


@dataclass(frozen=True)
class EnsembleResult:
    """Aggregated Monte Carlo ensemble result for a simulation session.

    Attributes:
        session_id: Source simulation session UUID.
        n_trials: Number of Monte Carlo trials that were run.
        distributions: Percentile bands for each tracked metric.
    """

    session_id: str
    n_trials: int
    distributions: list[DistributionBand]
    data_integrity_score: float = 1.0  # 0.0–1.0: 1.0 = all real data, 0.0 = all synthetic
    sampling_method: str = "lhs_t_copula"

    def to_dict(self) -> dict:
        """Serialise to a plain dict for JSON responses."""
        return {
            "session_id": self.session_id,
            "n_trials": self.n_trials,
            "distributions": [d.to_dict() for d in self.distributions],
            "data_integrity_score": round(self.data_integrity_score, 2),
            "sampling_method": self.sampling_method,
        }

    def get_band(self, metric_name: str) -> DistributionBand | None:
        """Return the DistributionBand for *metric_name*, or None."""
        for band in self.distributions:
            if band.metric_name == metric_name:
                return band
        return None
