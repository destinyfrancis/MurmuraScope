"""Naive baseline forecasters for validation comparison.

Supported methods:
  - ``last_value`` / ``naive``: repeat the last observed value
  - ``drift``: linear trend extrapolation from first to last value
  - ``mean``: repeat the historical mean

Additional utilities:
  - ``compute_crps``: Continuous Ranked Probability Score for probabilistic forecasts
  - ``RandomWalkDriftForecaster``: Random walk with drift (mean of first-differences)
"""
from __future__ import annotations

import math


class NaiveForecaster:
    def forecast(
        self,
        history: list[float],
        horizon: int = 6,
        method: str = "last_value",
    ) -> list[float]:
        """Generate a naive forecast.

        Args:
            history: Historical time series values.
            horizon: Number of steps to forecast.
            method: One of ``"last_value"``, ``"naive"``, ``"drift"``,
                ``"mean"``.

        Returns:
            List of *horizon* forecast values.

        Raises:
            ValueError: If *method* is not recognised.
        """
        if not history:
            return [0.0] * horizon

        # "naive" is an alias for "last_value"
        if method in ("last_value", "naive"):
            return [history[-1]] * horizon

        if method == "drift":
            n = len(history)
            if n < 2:
                return [history[-1]] * horizon
            drift = (history[-1] - history[0]) / (n - 1)
            return [history[-1] + drift * (i + 1) for i in range(horizon)]

        if method == "mean":
            avg = sum(history) / len(history)
            return [avg] * horizon

        raise ValueError(
            f"Unknown method: {method!r}. "
            "Valid methods: 'last_value', 'naive', 'drift', 'mean'."
        )


def compute_crps(actual: float, mean: float, std: float) -> float:
    """Continuous Ranked Probability Score for a normal predictive distribution.

    CRPS measures the compatibility of a probabilistic forecast with a single
    observed value. Lower is better; CRPS = 0 for a perfect point forecast.

    Formula for normal distribution N(mean, std^2):
        CRPS = std * (z * (2*Phi(z) - 1) + 2*phi(z) - 1/sqrt(pi))
    where z = (actual - mean) / std, phi = standard normal PDF,
    Phi = standard normal CDF.

    Args:
        actual: Observed value.
        mean: Predictive distribution mean.
        std: Predictive distribution standard deviation (must be > 0).

    Returns:
        CRPS value (non-negative float).
    """
    if std <= 0.0:
        # Degenerate case: point forecast — CRPS equals absolute error
        return abs(actual - mean)

    z = (actual - mean) / std
    # Standard normal PDF and CDF
    phi_z = math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)
    # Use math.erf for CDF: Phi(z) = 0.5 * (1 + erf(z / sqrt(2)))
    cap_phi_z = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    crps = std * (z * (2.0 * cap_phi_z - 1.0) + 2.0 * phi_z - 1.0 / math.sqrt(math.pi))
    return max(0.0, crps)


class RandomWalkDriftForecaster:
    """Random Walk with Drift forecaster.

    Computes drift as the mean of first-differences of the historical series.
    Forecast at step h = last_value + drift * h.

    This is more principled than a simple linear extrapolation from endpoints
    (used in NaiveForecaster.drift) because it uses all available differences.
    """

    def forecast(self, history: list[float], steps: int = 1) -> list[float]:
        """Generate a random walk with drift forecast.

        Args:
            history: Historical time series values (at least 2 points).
            steps: Number of steps ahead to forecast.

        Returns:
            List of *steps* forecast values.
        """
        if not history:
            return [0.0] * steps

        if len(history) < 2:
            return [history[-1]] * steps

        # Drift = mean of first-differences
        diffs = [history[i] - history[i - 1] for i in range(1, len(history))]
        drift = sum(diffs) / len(diffs)

        last_val = history[-1]
        return [last_val + drift * h for h in range(1, steps + 1)]
