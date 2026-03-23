"""StockBacktester — walk-forward backtest for weekly stock forecasts.

Splits weekly history at train_end, trains on the train split,
predicts `horizon` weeks forward, and compares against actual test data.
Computes MAPE, RMSE, and directional accuracy.
"""

from __future__ import annotations

import math

from backend.app.models.stock_forecast import StockBacktestResult
from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger
from backend.data_pipeline.stock_downloader import TICKER_REGISTRY

logger = get_logger("stock_backtester")

# Optional statsforecast
try:
    from statsforecast import StatsForecast
    from statsforecast.models import AutoARIMA

    HAS_STATSFORECAST = True
except ImportError:
    HAS_STATSFORECAST = False


def _week_sort_key(week_label: str) -> int:
    """Convert 'YYYY-WNN' to sortable integer YYYYNN."""
    try:
        year, wpart = week_label.split("-W")
        return int(year) * 100 + int(wpart)
    except ValueError:
        return 0


class StockBacktester:
    """Walk-forward backtest for one ticker."""

    async def run(
        self,
        ticker: str,
        train_end: str = "2024-W40",
        horizon: int = 8,
    ) -> StockBacktestResult:
        """Load weekly history, split at train_end, forecast, evaluate.

        Args:
            ticker: Must exist in TICKER_REGISTRY.
            train_end: Week label 'YYYY-WNN' marking the last training week.
            horizon: Number of weeks to forecast into the test set.

        Returns:
            StockBacktestResult with MAPE, RMSE, directional_accuracy.
        """
        if ticker not in TICKER_REGISTRY:
            raise ValueError(f"Unknown ticker: {ticker}")

        history = await self._load_weekly_history(ticker)
        if len(history) < 10:
            raise ValueError(f"Insufficient history for {ticker}: {len(history)} weeks")

        # Sort by week label
        history = sorted(history, key=lambda x: _week_sort_key(x[0]))
        train_key = _week_sort_key(train_end)

        train = [(w, c) for w, c in history if _week_sort_key(w) <= train_key]
        test = [(w, c) for w, c in history if _week_sort_key(w) > train_key]

        if len(train) < 8:
            raise ValueError(f"Train set too small for {ticker}: {len(train)} weeks before {train_end}")

        test = test[:horizon]  # limit to horizon
        if len(test) == 0:
            raise ValueError(f"No test data after {train_end} for {ticker}")

        # Produce forecasts
        predictions = self._predict(train, len(test))
        actuals = [c for _, c in test]

        # Align lengths
        n = min(len(predictions), len(actuals))
        predictions = predictions[:n]
        actuals = actuals[:n]

        mape = self._compute_mape(actuals, predictions)
        rmse = self._compute_rmse(actuals, predictions)
        dir_acc = self._compute_directional_accuracy(train, actuals, predictions)

        logger.info(
            "Backtest %s (train_end=%s, horizon=%d): MAPE=%.3f RMSE=%.2f DirAcc=%.3f n=%d",
            ticker,
            train_end,
            horizon,
            mape,
            rmse,
            dir_acc,
            n,
        )

        return StockBacktestResult(
            ticker=ticker,
            mape=mape,
            rmse=rmse,
            directional_accuracy=dir_acc,
            n_obs=n,
            train_end=train_end,
            horizon=horizon,
        )

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    async def _load_weekly_history(self, ticker: str) -> list[tuple[str, float]]:
        """Load (week_label, close) from market_data where granularity='weekly'."""
        async with get_db() as db:
            rows = await db.execute_fetchall(
                """SELECT date, close FROM market_data
                   WHERE ticker = ? AND granularity = 'weekly' AND close > 0
                   ORDER BY date ASC""",
                (ticker,),
            )
        return [(r[0], float(r[1])) for r in rows]

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def _predict(self, train: list[tuple[str, float]], n_ahead: int) -> list[float]:
        """Produce n_ahead point forecasts from training data.

        Tries AutoARIMA if statsforecast is available; falls back to naive drift.
        """
        closes = [c for _, c in train]

        if HAS_STATSFORECAST:
            try:
                return self._predict_arima(closes, n_ahead)
            except Exception as exc:
                logger.warning("AutoARIMA backtest failed, using drift: %s", exc)

        return self._predict_drift(closes, n_ahead)

    def _predict_arima(self, closes: list[float], n_ahead: int) -> list[float]:
        """AutoARIMA predictions."""
        import pandas as pd

        n = len(closes)
        sf = StatsForecast(
            models=[AutoARIMA(season_length=52, approximation=True)],
            freq="W",
            n_jobs=1,
        )
        df = pd.DataFrame(
            {
                "unique_id": ["ticker"] * n,
                "ds": pd.date_range(end=pd.Timestamp.now(), periods=n, freq="W-FRI"),
                "y": closes,
            }
        )
        sf.fit(df)
        pred = sf.predict(h=n_ahead)
        col = next(
            (c for c in pred.columns if c not in ("unique_id", "ds")),
            None,
        )
        if col is None:
            raise ValueError("No prediction column found in statsforecast output")
        return [float(v) for v in pred[col].tolist()]

    def _predict_drift(self, closes: list[float], n_ahead: int) -> list[float]:
        """Naive random walk with drift."""
        n = len(closes)
        if n >= 2:
            drift = (closes[-1] / closes[0]) ** (1.0 / (n - 1)) - 1.0
        else:
            drift = 0.0

        last = closes[-1]
        return [last * ((1 + drift) ** t) for t in range(1, n_ahead + 1)]

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_mape(actuals: list[float], predictions: list[float]) -> float:
        """Mean Absolute Percentage Error."""
        if not actuals:
            return 0.0
        errors = [abs(a - p) / abs(a) for a, p in zip(actuals, predictions) if abs(a) > 1e-9]
        return round(sum(errors) / len(errors), 4) if errors else 0.0

    @staticmethod
    def _compute_rmse(actuals: list[float], predictions: list[float]) -> float:
        """Root Mean Squared Error."""
        if not actuals:
            return 0.0
        mse = sum((a - p) ** 2 for a, p in zip(actuals, predictions)) / len(actuals)
        return round(math.sqrt(mse), 4)

    @staticmethod
    def _compute_directional_accuracy(
        train: list[tuple[str, float]],
        actuals: list[float],
        predictions: list[float],
    ) -> float:
        """Fraction of steps where predicted direction matches actual direction.

        Direction is measured relative to the last training value.
        """
        if not actuals or not train:
            return 0.0

        last_train_close = train[-1][1]
        correct = 0
        total = 0

        for i, (actual, pred) in enumerate(zip(actuals, predictions)):
            # reference is the previous value: either last_train_close or previous actual
            ref = actuals[i - 1] if i > 0 else last_train_close
            if abs(ref) < 1e-9:
                continue
            actual_dir = 1 if actual > ref else (-1 if actual < ref else 0)
            pred_dir = 1 if pred > ref else (-1 if pred < ref else 0)
            if actual_dir == pred_dir:
                correct += 1
            total += 1

        return round(correct / total, 4) if total > 0 else 0.0
