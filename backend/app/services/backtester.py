"""Walk-forward backtesting framework for MurmuraScope time series models.

Implements walk-forward validation:
  - Train on data up to ``train_end`` (default 2022-Q4).
  - Predict ``horizon`` periods ahead.
  - Compare predictions with actuals from the DB.
  - Report MAPE, RMSE, and Directional Accuracy.

Design notes:
  - Uses TimeSeriesForecaster with auto-model selection (Task 2.3) when >= 20
    training points are available.
  - ``BacktestResult`` is a frozen dataclass (immutable per project style).
  - DB path resolves relative to this file regardless of cwd.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from backend.app.services.time_series_forecaster import (
    SUPPORTED_METRICS,
    TimeSeriesForecaster,
    _quarter_label,
)
from backend.app.utils.logger import get_logger

logger = get_logger("backtester")

# ---------------------------------------------------------------------------
# DB path (project root / data / murmuroscope.db)
# ---------------------------------------------------------------------------

_DB_PATH: Path = Path(__file__).resolve().parent.parent.parent.parent / "data" / "murmuroscope.db"

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BacktestResult:
    """Immutable walk-forward backtest evaluation result.

    Attributes:
        metric: Forecast metric key (e.g. ``"gdp_growth"``).
        train_start: First period in the training window (e.g. ``"2015-Q1"``).
        train_end: Last period in the training window (e.g. ``"2022-Q4"``).
        test_start: First period in the test window.
        test_end: Last period in the test window.
        mape: Mean Absolute Percentage Error on held-out test set (%).
        rmse: Root Mean Squared Error on held-out test set.
        directional_accuracy: Fraction of steps where direction matches (0–1).
        coverage_80: Fraction of actuals that fall within the 80% CI bounds (0–1).
        predictions: Tuple of (period, predicted, actual) for each test step.
        model_used: Name of the model selected for the backtest.
    """

    metric: str
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    mape: float
    rmse: float
    directional_accuracy: float
    coverage_80: float
    coverage_95: float
    crps: float
    theils_u: float
    predictions: tuple  # tuple[tuple[str, float, float], ...]
    model_used: str
    data_quality_flag: str = "real_data"  # "real_data" | "partial_real" | "insufficient"

    def to_dict(self) -> dict:
        """Serialise to a plain dict suitable for JSON API responses."""
        return {
            "metric": self.metric,
            "train_start": self.train_start,
            "train_end": self.train_end,
            "test_start": self.test_start,
            "test_end": self.test_end,
            "mape": round(self.mape, 4),
            "rmse": round(self.rmse, 6),
            "directional_accuracy": round(self.directional_accuracy, 4),
            "coverage_80": round(self.coverage_80, 4),
            "coverage_95": round(self.coverage_95, 4),
            "crps": round(self.crps, 6),
            "theils_u": round(self.theils_u, 4),
            "predictions": [
                {"period": p, "predicted": round(pred, 6), "actual": round(act, 6)} for p, pred, act in self.predictions
            ],
            "model_used": self.model_used,
            "data_quality_flag": self.data_quality_flag,
            "n_test": len(self.predictions),
        }


# ---------------------------------------------------------------------------
# Period helpers
# ---------------------------------------------------------------------------


def _period_sort_key(period: str) -> float:
    """Convert a period label to a numeric sort key.

    Supports ``"YYYY-QN"`` and plain ``"YYYY"`` labels.
    Returns ``float("inf")`` for unrecognised formats.
    """
    parts = period.split("-")
    try:
        if len(parts) == 2 and parts[1].startswith("Q"):
            return int(parts[0]) + (int(parts[1][1]) - 1) / 4.0
        if len(parts) == 1:
            return float(parts[0])
    except (ValueError, IndexError):
        pass
    return float("inf")


def _period_le(period_a: str, period_b: str) -> bool:
    """Return True if period_a <= period_b chronologically."""
    return _period_sort_key(period_a) <= _period_sort_key(period_b)


def _next_period_labels_from(last_period: str, horizon: int) -> list[str]:
    """Generate *horizon* period labels starting one step after *last_period*."""
    parts = last_period.split("-")
    try:
        if len(parts) == 2 and parts[1].startswith("Q"):
            base_year = int(parts[0])
            base_q = int(parts[1][1])
            return [_quarter_label(base_year, base_q, i) for i in range(1, horizon + 1)]
        if len(parts) == 1:
            base_year = int(parts[0])
            return [str(base_year + i) for i in range(1, horizon + 1)]
    except (ValueError, IndexError):
        pass
    return [f"t+{i}" for i in range(1, horizon + 1)]


# ---------------------------------------------------------------------------
# Error metric computation
# ---------------------------------------------------------------------------


def _compute_mape(actuals: np.ndarray, predictions: np.ndarray) -> float:
    """Mean Absolute Percentage Error (%)."""
    if len(actuals) == 0:
        return 0.0
    with np.errstate(divide="ignore", invalid="ignore"):
        ape = np.where(actuals != 0.0, np.abs((actuals - predictions) / actuals) * 100.0, 0.0)
    return float(np.mean(ape))


def _compute_rmse(actuals: np.ndarray, predictions: np.ndarray) -> float:
    """Root Mean Squared Error."""
    if len(actuals) == 0:
        return 0.0
    return float(math.sqrt(float(np.mean((actuals - predictions) ** 2))))


def _compute_coverage_80(
    actuals: np.ndarray,
    lower_bounds: np.ndarray,
    upper_bounds: np.ndarray,
) -> float:
    """Fraction of actual values falling within the 80% CI bounds (0–1).

    An actual value is considered "covered" when lower_80 <= actual <= upper_80.
    Returns 0.0 for an empty array.
    """
    if len(actuals) == 0:
        return 0.0
    covered = np.sum((actuals >= lower_bounds) & (actuals <= upper_bounds))
    return float(covered) / len(actuals)


def _compute_theils_u(
    actuals: np.ndarray,
    predictions: np.ndarray,
    last_train_value: float,
) -> float:
    """Theil's U statistic — ratio of model RMSE to naive (random walk) RMSE.

    U < 1.0 means model beats naive forecast; U > 1.0 means naive is better.
    Returns 0.0 for empty arrays or when naive RMSE is zero.
    """
    if len(actuals) < 2:
        return 0.0
    # Model RMSE
    model_rmse = _compute_rmse(actuals, predictions)
    # Naive forecast: each step = previous actual (walk forward)
    naive_preds = np.empty_like(actuals)
    naive_preds[0] = last_train_value
    naive_preds[1:] = actuals[:-1]
    naive_rmse = _compute_rmse(actuals, naive_preds)
    if naive_rmse < 1e-12:
        return 0.0
    return model_rmse / naive_rmse


def _compute_coverage_95(
    actuals: np.ndarray,
    lower_bounds: np.ndarray,
    upper_bounds: np.ndarray,
) -> float:
    """Fraction of actual values falling within the 95% CI bounds (0-1)."""
    if len(actuals) == 0:
        return 0.0
    covered = np.sum((actuals >= lower_bounds) & (actuals <= upper_bounds))
    return float(covered) / len(actuals)


def _compute_crps(
    actuals: np.ndarray,
    pred_means: np.ndarray,
    pred_stds: np.ndarray,
) -> float:
    """Continuous Ranked Probability Score for Gaussian predictive distributions.

    Formula per observation:
        CRPS = sigma * (z * (2*Phi(z) - 1) + 2*phi(z) - 1/sqrt(pi))
    where z = (actual - mean) / sigma, Phi = standard normal CDF, phi = PDF.

    Returns the mean CRPS across all observations.
    Returns 0.0 for empty arrays.
    """
    if len(actuals) == 0:
        return 0.0

    from scipy.stats import norm  # noqa: PLC0415

    # Clamp sigma to avoid division by zero
    safe_stds = np.maximum(pred_stds, 1e-12)
    z = (actuals - pred_means) / safe_stds

    phi_z = norm.pdf(z)
    big_phi_z = norm.cdf(z)

    crps_per_obs = safe_stds * (z * (2.0 * big_phi_z - 1.0) + 2.0 * phi_z - 1.0 / math.sqrt(math.pi))
    return float(np.mean(crps_per_obs))


def _compute_directional_accuracy(
    actuals: np.ndarray,
    predictions: np.ndarray,
    last_train_value: float,
) -> float:
    """Fraction of steps where direction of change is correctly predicted.

    Direction is evaluated relative to the *previous* value in the sequence.
    Step 1 uses ``last_train_value`` as the reference; subsequent steps use
    the previous actual (walk-forward).
    """
    if len(actuals) == 0:
        return 0.0

    correct = 0
    prev = last_train_value
    for act, pred in zip(actuals, predictions):
        act_dir = act - prev
        pred_dir = pred - prev
        if (act_dir >= 0) == (pred_dir >= 0):
            correct += 1
        prev = act  # walk forward on actuals

    return correct / len(actuals)


# ---------------------------------------------------------------------------
# Data splitting helpers
# ---------------------------------------------------------------------------


def _split_at_period(
    history: list[tuple[str, float]],
    train_end: str,
    horizon: int,
) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """Split *history* at *train_end* (inclusive) into (train, test).

    Test set contains at most *horizon* records immediately after train_end.
    Records are sorted chronologically before splitting.
    """
    sorted_history = sorted(history, key=lambda t: _period_sort_key(t[0]))
    train: list[tuple[str, float]] = []
    rest: list[tuple[str, float]] = []
    for period, value in sorted_history:
        if _period_le(period, train_end):
            train.append((period, value))
        else:
            rest.append((period, value))
    return train, rest[:horizon]


# ---------------------------------------------------------------------------
# Backtester
# ---------------------------------------------------------------------------


class Backtester:
    """Walk-forward backtester for HK economic time series.

    Steps:
    1. Load full history from DB (with hardcoded fallback).
    2. Split into train (up to train_end) and test (next horizon periods).
    3. Run TimeSeriesForecaster on training data only.
       - Auto-selects model (AutoARIMA / AutoETS / Naive) when train >= 20 pts.
    4. Align forecast periods with actual test-set values.
    5. Compute MAPE, RMSE, Directional Accuracy.

    Usage::

        bt = Backtester()
        result = await bt.run("gdp_growth", train_end="2022-Q4", horizon=8)
        print(result.to_dict())
    """

    def __init__(self) -> None:
        self._forecaster = TimeSeriesForecaster()

    async def run(
        self,
        metric: str,
        train_end: str = "2022-Q4",
        horizon: int = 8,
    ) -> BacktestResult:
        """Run walk-forward backtest for *metric*.

        Args:
            metric: One of the keys in SUPPORTED_METRICS.
            train_end: Last training period label (inclusive), e.g. ``"2022-Q4"``.
            horizon: Number of test periods to evaluate (1–24).

        Returns:
            A frozen :class:`BacktestResult`.

        Raises:
            ValueError: If metric is not supported.
        """
        if metric not in SUPPORTED_METRICS:
            available = ", ".join(sorted(SUPPORTED_METRICS))
            raise ValueError(f"Unsupported metric '{metric}'. Available: {available}")

        horizon = max(1, min(horizon, 24))

        # ------------------------------------------------------------------
        # 1. Load full history (DB → hardcoded fallback)
        # ------------------------------------------------------------------
        full_history = await self._forecaster._load_history(metric)
        if not full_history:
            raise ValueError(f"No historical data found for metric '{metric}'. Populate hk_data_snapshots first.")

        # ------------------------------------------------------------------
        # 2. Split into train / test
        # ------------------------------------------------------------------
        train_data, test_data = _split_at_period(full_history, train_end, horizon)

        if not train_data:
            raise ValueError(f"No training data on or before '{train_end}' for metric '{metric}'.")

        train_start = train_data[0][0]
        actual_train_end = train_data[-1][0]
        last_train_value = float(train_data[-1][1])

        logger.info(
            "Backtest metric=%s train=%s→%s n_train=%d n_test=%d horizon=%d",
            metric,
            train_start,
            actual_train_end,
            len(train_data),
            len(test_data),
            horizon,
        )

        # ------------------------------------------------------------------
        # 3. Forecast from training window only
        # ------------------------------------------------------------------
        forecast_result = await self._forecast_from_train(metric, train_data, horizon)
        model_used = forecast_result.model_used

        # ------------------------------------------------------------------
        # 4. Align predictions with actuals
        # ------------------------------------------------------------------
        test_labels = _next_period_labels_from(actual_train_end, horizon)
        test_map: dict[str, float] = {p: v for p, v in test_data}

        predictions: list[tuple[str, float, float]] = []
        lower_80_list: list[float] = []
        upper_80_list: list[float] = []
        lower_95_list: list[float] = []
        upper_95_list: list[float] = []
        pred_std_list: list[float] = []
        for label, fp in zip(test_labels, forecast_result.points):
            if label not in test_map:
                continue  # skip periods without actual data
            predictions.append((label, fp.value, test_map[label]))
            lower_80_list.append(fp.lower_80)
            upper_80_list.append(fp.upper_80)
            lower_95_list.append(fp.lower_95)
            upper_95_list.append(fp.upper_95)
            # Estimate predictive std from 95% CI: span / (2 * 1.96)
            pred_std_list.append(max((fp.upper_95 - fp.lower_95) / (2.0 * 1.96), 1e-12))

        # ------------------------------------------------------------------
        # 5. Compute error metrics
        # ------------------------------------------------------------------
        pred_arr = np.array([p for _, p, _ in predictions], dtype=np.float64)
        act_arr = np.array([a for _, _, a in predictions], dtype=np.float64)
        lower_80_arr = np.array(lower_80_list, dtype=np.float64)
        upper_80_arr = np.array(upper_80_list, dtype=np.float64)
        lower_95_arr = np.array(lower_95_list, dtype=np.float64)
        upper_95_arr = np.array(upper_95_list, dtype=np.float64)
        pred_std_arr = np.array(pred_std_list, dtype=np.float64)

        mape = _compute_mape(act_arr, pred_arr)
        rmse = _compute_rmse(act_arr, pred_arr)
        dir_acc = _compute_directional_accuracy(act_arr, pred_arr, last_train_value)
        cov_80 = _compute_coverage_80(act_arr, lower_80_arr, upper_80_arr)
        cov_95 = _compute_coverage_95(act_arr, lower_95_arr, upper_95_arr)
        crps = _compute_crps(act_arr, pred_arr, pred_std_arr)
        theils_u = _compute_theils_u(act_arr, pred_arr, last_train_value)

        test_start = predictions[0][0] if predictions else actual_train_end
        test_end = predictions[-1][0] if predictions else actual_train_end

        # Data quality classification
        n_train = len(train_data)
        if n_train >= 20:
            data_quality_flag = "real_data"
        elif n_train >= 8:
            data_quality_flag = "partial_real"
        else:
            data_quality_flag = "insufficient"

        logger.info(
            "Backtest complete metric=%s model=%s mape=%.2f%% rmse=%.4f da=%.2f cov80=%.2f cov95=%.2f crps=%.4f theils_u=%.3f dq=%s",
            metric,
            model_used,
            mape,
            rmse,
            dir_acc,
            cov_80,
            cov_95,
            crps,
            theils_u,
            data_quality_flag,
        )

        return BacktestResult(
            metric=metric,
            train_start=train_start,
            train_end=actual_train_end,
            test_start=test_start,
            test_end=test_end,
            mape=mape,
            rmse=rmse,
            directional_accuracy=dir_acc,
            coverage_80=cov_80,
            coverage_95=cov_95,
            crps=crps,
            theils_u=theils_u,
            predictions=tuple(predictions),
            model_used=model_used,
            data_quality_flag=data_quality_flag,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _forecast_from_train(
        self,
        metric: str,
        train_data: list[tuple[str, float]],
        horizon: int,
    ):
        """Produce a forecast using only the training window.

        Temporarily patches ``_load_history`` on the forecaster instance so
        that auto-selection and model fitting operate solely on train_data.
        The patch is restored in a ``finally`` block to avoid side effects.
        """
        original_load = self._forecaster._load_history

        async def _patched_load(
            m: str,
            metric_db_map: dict | None = None,  # noqa: ARG001
        ) -> list[tuple[str, float]]:
            return train_data

        # Patch instance method (Python allows assigning to instance __dict__)
        self._forecaster._load_history = _patched_load  # type: ignore[method-assign]
        try:
            result = await self._forecaster.forecast(metric=metric, horizon=horizon)
        finally:
            self._forecaster._load_history = original_load  # type: ignore[method-assign]

        return result
