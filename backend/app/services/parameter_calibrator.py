"""Parameter Calibration Pipeline for HKSimEngine.

Loads historical HK data from ``hk_data_snapshots`` and ``social_sentiment``,
then searches for the ``CalibrationParams`` configuration that minimises the
RMSE between model-predicted macro-indicator changes and observed historical
changes.

Supported search methods:
  - ``"grid_search"``: exhaustive grid over threshold × delta combinations.
  - ``"random_search"``: random sampling (faster for larger search spaces).

Calibrated params are written to the ``calibration_results`` table so that
``macro_controller.update_from_actions()`` can pick them up at runtime.

Usage::

    calibrator = ParameterCalibrator()
    data = await calibrator.load_historical_data()
    best_params, rmse = await calibrator.calibrate(data, method="grid_search")
    await calibrator.save_calibration(best_params, label="auto_2024Q1", rmse=rmse)
"""

from __future__ import annotations

import dataclasses
import itertools
import json
import random
from typing import Any

from backend.app.services.calibration_config import CalibrationParams, DEFAULT_CALIBRATION
from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("parameter_calibrator")

# ---------------------------------------------------------------------------
# Grid search parameter space
# ---------------------------------------------------------------------------

_NEG_THRESHOLD_GRID = [0.45, 0.50, 0.55, 0.60, 0.65, 0.70]
_POS_THRESHOLD_GRID = [0.45, 0.50, 0.55, 0.60, 0.65, 0.70]
_CONFIDENCE_DELTA_NEG_GRID = [0.1, 0.2, 0.3, 0.4, 0.5]
_CONFIDENCE_DELTA_POS_GRID = [0.1, 0.15, 0.2, 0.25, 0.3]
_GDP_DELTA_NEG_GRID = [0.0005, 0.001, 0.0015, 0.002]
_EMIGRATION_THRESHOLD_GRID = [0.10, 0.15, 0.20, 0.25, 0.30]

# Random search samples
_RANDOM_TRIALS = 200


# ---------------------------------------------------------------------------
# HistoricalDataPoint — one paired observation
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class HistoricalDataPoint:
    """A single matched (sentiment_ratios → macro_changes) observation.

    Attributes:
        period: Quarter label, e.g. ``"2024-Q1"``.
        neg_ratio: Fraction of negative social posts in the period.
        pos_ratio: Fraction of positive social posts in the period.
        emigration_freq: Fraction of posts mentioning emigration topics.
        property_neg: True when property topic is mentioned AND sentiment negative.
        employment_neg: True when employment topic is mentioned AND sentiment negative.
        stock_pos: True when stock topic is mentioned AND sentiment positive.
        observed_confidence_delta: Actual change in consumer_confidence vs previous period.
        observed_gdp_delta: Actual change in gdp_growth vs previous period.
        observed_hsi_pct_change: Actual proportional change in hsi_level.
        observed_ccl_pct_change: Actual proportional change in ccl_index.
        observed_unemployment_delta: Actual change in unemployment_rate.
        observed_net_migration_delta: Actual change in net_migration.
    """

    period: str
    neg_ratio: float
    pos_ratio: float
    emigration_freq: float
    property_neg: bool
    employment_neg: bool
    stock_pos: bool
    observed_confidence_delta: float
    observed_gdp_delta: float
    observed_hsi_pct_change: float
    observed_ccl_pct_change: float
    observed_unemployment_delta: float
    observed_net_migration_delta: float


# ---------------------------------------------------------------------------
# ParameterCalibrator
# ---------------------------------------------------------------------------


class ParameterCalibrator:
    """Calibrates macro feedback parameters against historical HK data.

    All state is immutable after construction.  Results are persisted to DB
    via ``save_calibration()``.
    """

    async def load_historical_data(self) -> list[HistoricalDataPoint]:
        """Load and pair macro indicator history with social sentiment history.

        Reads:
        - ``hk_data_snapshots`` for macro indicators (quarterly).
        - ``social_sentiment`` for sentiment ratios (quarterly).

        Returns:
            List of ``HistoricalDataPoint`` objects sorted by period.
            Returns synthetic baseline data if DB tables are empty.
        """
        macro_by_period = await self._load_macro_history()
        sentiment_by_period = await self._load_sentiment_history()

        common_periods = sorted(
            set(macro_by_period) & set(sentiment_by_period)
        )

        if len(common_periods) < 2:
            logger.warning(
                "Insufficient paired data (%d periods) — using synthetic baseline",
                len(common_periods),
            )
            return self._synthetic_baseline()

        points: list[HistoricalDataPoint] = []
        sorted_periods = sorted(common_periods)

        for i in range(1, len(sorted_periods)):
            prev_period = sorted_periods[i - 1]
            curr_period = sorted_periods[i]

            prev_macro = macro_by_period[prev_period]
            curr_macro = macro_by_period[curr_period]
            curr_sent = sentiment_by_period[curr_period]

            neg_ratio = float(curr_sent.get("negative_ratio", 0.3))
            pos_ratio = float(curr_sent.get("positive_ratio", 0.3))

            # Derive topic proxies from sentiment category distribution
            property_neg = curr_sent.get("category", "") == "property" and neg_ratio > 0.4
            employment_neg = curr_sent.get("category", "") == "employment" and neg_ratio > 0.4
            stock_pos = curr_sent.get("category", "") == "finance" and pos_ratio > 0.4
            emigration_freq = float(curr_sent.get("emigration_freq", 0.0))

            # Compute observed changes
            conf_prev = float(prev_macro.get("consumer_confidence", 88.0))
            conf_curr = float(curr_macro.get("consumer_confidence", 88.0))
            gdp_prev = float(prev_macro.get("gdp_growth", 0.03))
            gdp_curr = float(curr_macro.get("gdp_growth", 0.03))
            hsi_prev = float(prev_macro.get("hsi_level", 17000.0))
            hsi_curr = float(curr_macro.get("hsi_level", 17000.0))
            ccl_prev = float(prev_macro.get("ccl_index", 152.0))
            ccl_curr = float(curr_macro.get("ccl_index", 152.0))
            unemp_prev = float(prev_macro.get("unemployment_rate", 0.029))
            unemp_curr = float(curr_macro.get("unemployment_rate", 0.029))
            mig_prev = float(prev_macro.get("net_migration", -12000))
            mig_curr = float(curr_macro.get("net_migration", -12000))

            points.append(HistoricalDataPoint(
                period=curr_period,
                neg_ratio=neg_ratio,
                pos_ratio=pos_ratio,
                emigration_freq=emigration_freq,
                property_neg=property_neg,
                employment_neg=employment_neg,
                stock_pos=stock_pos,
                observed_confidence_delta=conf_curr - conf_prev,
                observed_gdp_delta=gdp_curr - gdp_prev,
                observed_hsi_pct_change=(hsi_curr - hsi_prev) / max(hsi_prev, 1.0),
                observed_ccl_pct_change=(ccl_curr - ccl_prev) / max(ccl_prev, 1.0),
                observed_unemployment_delta=unemp_curr - unemp_prev,
                observed_net_migration_delta=mig_curr - mig_prev,
            ))

        logger.info("Loaded %d historical data points for calibration", len(points))
        return points

    async def calibrate(
        self,
        data: list[HistoricalDataPoint],
        method: str = "grid_search",
    ) -> tuple[CalibrationParams, float]:
        """Search for the ``CalibrationParams`` that minimises RMSE.

        Args:
            data: Historical data points (from ``load_historical_data()``).
            method: ``"grid_search"`` or ``"random_search"``.

        Returns:
            Tuple of (best_params, rmse).  Returns DEFAULT_CALIBRATION if
            data is empty.
        """
        if not data:
            logger.warning("No data for calibration — returning defaults")
            return DEFAULT_CALIBRATION, 0.0

        if method == "random_search":
            candidates = self._random_candidates(_RANDOM_TRIALS)
        else:
            candidates = self._grid_candidates()

        best_params = DEFAULT_CALIBRATION
        best_rmse = float("inf")

        for params in candidates:
            rmse = self._compute_rmse(params, data)
            if rmse < best_rmse:
                best_rmse = rmse
                best_params = params

        logger.info(
            "Calibration complete method=%s candidates_evaluated=%d best_rmse=%.6f",
            method,
            len(candidates),
            best_rmse,
        )
        return best_params, best_rmse

    async def save_calibration(
        self,
        params: CalibrationParams,
        label: str,
        rmse: float = 0.0,
        data_period: str = "",
    ) -> int:
        """Persist calibration results to the ``calibration_results`` table.

        Args:
            params: The calibrated parameters to save.
            label: Human-readable label (e.g. ``"auto_2024Q1"``).
            rmse: Root mean square error achieved.
            data_period: Date range of training data (informational).

        Returns:
            Row ID of the inserted record.
        """
        params_json = json.dumps(params.to_dict())

        async with get_db() as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS calibration_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    label TEXT NOT NULL,
                    params_json TEXT NOT NULL,
                    rmse REAL,
                    data_period TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                )
                """,
            )
            cursor = await db.execute(
                """
                INSERT INTO calibration_results (label, params_json, rmse, data_period)
                VALUES (?, ?, ?, ?)
                """,
                (label, params_json, rmse, data_period),
            )
            await db.commit()
            row_id = cursor.lastrowid

        logger.info(
            "Saved calibration results id=%s label=%s rmse=%.6f",
            row_id, label, rmse,
        )
        return row_id or 0

    async def load_best_calibration(self) -> CalibrationParams:
        """Load the best saved calibration from the DB (lowest RMSE).

        Returns ``DEFAULT_CALIBRATION`` if no results exist yet.
        """
        try:
            async with get_db() as db:
                await db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS calibration_results (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        label TEXT NOT NULL,
                        params_json TEXT NOT NULL,
                        rmse REAL,
                        data_period TEXT,
                        created_at TEXT DEFAULT (datetime('now'))
                    )
                    """
                )
                cursor = await db.execute(
                    "SELECT params_json FROM calibration_results ORDER BY rmse ASC LIMIT 1"
                )
                row = await cursor.fetchone()
        except Exception:
            logger.warning("Could not load calibration_results — using defaults")
            return DEFAULT_CALIBRATION

        if row is None:
            return DEFAULT_CALIBRATION

        try:
            params_dict: dict[str, Any] = json.loads(row[0])
            return CalibrationParams(**params_dict)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("Malformed calibration_results row: %s", exc)
            return DEFAULT_CALIBRATION

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_rmse(
        params: CalibrationParams,
        data: list[HistoricalDataPoint],
    ) -> float:
        """Compute the RMSE of macro predictions against observed data.

        For each data point, simulate the ``update_from_actions()`` logic using
        *params* and compare against observed changes.  Returns the mean
        squared error across all indicators and all periods.

        Args:
            params: Calibration parameters to evaluate.
            data: Historical data points.

        Returns:
            RMSE as a float.  Lower is better.
        """
        total_sq_error = 0.0
        n_obs = 0

        for pt in data:
            # --- Predict confidence delta ---
            pred_conf = 0.0
            if pt.neg_ratio > params.neg_threshold:
                pred_conf = -params.confidence_delta_neg
            elif pt.pos_ratio > params.pos_threshold:
                pred_conf = params.confidence_delta_pos

            # --- Predict GDP delta ---
            pred_gdp = 0.0
            if pt.neg_ratio > params.neg_threshold:
                pred_gdp = -params.gdp_delta_neg

            # --- Predict HSI pct change ---
            pred_hsi_pct = 0.0
            if pt.pos_ratio > params.pos_threshold:
                pred_hsi_pct += params.hsi_pos_factor - 1.0
            if pt.stock_pos and pt.pos_ratio > params.secondary_sentiment_threshold:
                pred_hsi_pct += params.stock_pos_hsi_factor - 1.0

            # --- Predict CCL pct change ---
            pred_ccl_pct = 0.0
            if (
                pt.property_neg
                and pt.neg_ratio > params.secondary_sentiment_threshold
                and pt.neg_ratio > params.property_topic_threshold
            ):
                pred_ccl_pct = params.property_neg_ccl_factor - 1.0

            # --- Predict unemployment delta ---
            pred_unemp = 0.0
            if (
                pt.employment_neg
                and pt.neg_ratio > params.secondary_sentiment_threshold
                and pt.neg_ratio > params.employment_topic_threshold
            ):
                pred_unemp = params.employment_neg_unemployment_delta

            # --- Predict net_migration delta ---
            pred_mig = 0.0
            if pt.emigration_freq > params.emigration_threshold:
                pred_mig = -float(params.emigration_net_migration_delta)

            # Scale observations to comparable units (normalise by typical range)
            errors = [
                (pred_conf - pt.observed_confidence_delta) / 2.0,
                (pred_gdp - pt.observed_gdp_delta) / 0.01,
                (pred_hsi_pct - pt.observed_hsi_pct_change) / 0.02,
                (pred_ccl_pct - pt.observed_ccl_pct_change) / 0.02,
                (pred_unemp - pt.observed_unemployment_delta) / 0.005,
                (pred_mig - pt.observed_net_migration_delta) / 500.0,
            ]

            for e in errors:
                total_sq_error += e * e
                n_obs += 1

        if n_obs == 0:
            return float("inf")
        return (total_sq_error / n_obs) ** 0.5

    @staticmethod
    def _grid_candidates() -> list[CalibrationParams]:
        """Generate all grid-search candidate CalibrationParams."""
        candidates: list[CalibrationParams] = []
        for combo in itertools.product(
            _NEG_THRESHOLD_GRID,
            _POS_THRESHOLD_GRID,
            _CONFIDENCE_DELTA_NEG_GRID,
            _CONFIDENCE_DELTA_POS_GRID,
            _GDP_DELTA_NEG_GRID,
            _EMIGRATION_THRESHOLD_GRID,
        ):
            neg_t, pos_t, conf_neg, conf_pos, gdp_neg, emig_t = combo
            candidates.append(dataclasses.replace(
                DEFAULT_CALIBRATION,
                neg_threshold=neg_t,
                pos_threshold=pos_t,
                confidence_delta_neg=conf_neg,
                confidence_delta_pos=conf_pos,
                gdp_delta_neg=gdp_neg,
                emigration_threshold=emig_t,
            ))
        return candidates

    @staticmethod
    def _random_candidates(n: int) -> list[CalibrationParams]:
        """Generate *n* random CalibrationParams within the search space."""
        rng = random.Random(42)  # deterministic seed for reproducibility
        candidates: list[CalibrationParams] = []
        for _ in range(n):
            candidates.append(dataclasses.replace(
                DEFAULT_CALIBRATION,
                neg_threshold=rng.choice(_NEG_THRESHOLD_GRID),
                pos_threshold=rng.choice(_POS_THRESHOLD_GRID),
                confidence_delta_neg=rng.choice(_CONFIDENCE_DELTA_NEG_GRID),
                confidence_delta_pos=rng.choice(_CONFIDENCE_DELTA_POS_GRID),
                gdp_delta_neg=rng.choice(_GDP_DELTA_NEG_GRID),
                emigration_threshold=rng.choice(_EMIGRATION_THRESHOLD_GRID),
            ))
        return candidates

    async def _load_macro_history(self) -> dict[str, dict[str, float]]:
        """Load macro indicator time-series from hk_data_snapshots.

        Returns:
            Dict mapping period → {indicator_name → value}.
        """
        field_map = [
            ("gdp", "gdp_growth_rate", "gdp_growth"),
            ("sentiment", "consumer_confidence", "consumer_confidence"),
            ("finance", "hsi_level", "hsi_level"),
            ("property", "ccl_index", "ccl_index"),
            ("employment", "unemployment_rate", "unemployment_rate"),
            ("population", "net_migration", "net_migration"),
        ]

        result: dict[str, dict[str, float]] = {}
        try:
            async with get_db() as db:
                for category, metric, field in field_map:
                    cursor = await db.execute(
                        """
                        SELECT period, value
                        FROM hk_data_snapshots
                        WHERE category = ? AND metric = ?
                        ORDER BY period ASC
                        """,
                        (category, metric),
                    )
                    rows = await cursor.fetchall()
                    for row in rows:
                        period = str(row[0] if isinstance(row, (list, tuple)) else row["period"])
                        val = float(row[1] if isinstance(row, (list, tuple)) else row["value"])
                        if period not in result:
                            result[period] = {}
                        result[period][field] = val
        except Exception:
            logger.warning("Could not load macro history for calibration")
        return result

    async def _load_sentiment_history(self) -> dict[str, dict[str, float]]:
        """Load social sentiment history from the social_sentiment table.

        Returns:
            Dict mapping period → {positive_ratio, negative_ratio, category, …}.
        """
        result: dict[str, dict[str, float]] = {}
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    """
                    SELECT period, category, positive_ratio, negative_ratio, neutral_ratio
                    FROM social_sentiment
                    ORDER BY period ASC
                    """,
                )
                rows = await cursor.fetchall()
                for row in rows:
                    period = str(row[0] if isinstance(row, (list, tuple)) else row["period"])
                    if period not in result:
                        result[period] = {}
                    result[period].update({
                        "category": str(row[1] if isinstance(row, (list, tuple)) else row["category"]),
                        "positive_ratio": float(row[2] if isinstance(row, (list, tuple)) else row["positive_ratio"]),
                        "negative_ratio": float(row[3] if isinstance(row, (list, tuple)) else row["negative_ratio"]),
                        "neutral_ratio": float(row[4] if isinstance(row, (list, tuple)) else row["neutral_ratio"]),
                        "emigration_freq": 0.0,  # approximation; refined by topic analysis
                    })
        except Exception:
            logger.warning("Could not load social_sentiment for calibration")
        return result

    @staticmethod
    def _synthetic_baseline() -> list[HistoricalDataPoint]:
        """Return synthetic HK data points for bootstrapping calibration.

        Covers 2022-Q1 through 2024-Q1 with approximate real-world trends.
        """
        return [
            HistoricalDataPoint(
                period="2022-Q2",
                neg_ratio=0.62, pos_ratio=0.25, emigration_freq=0.22,
                property_neg=True, employment_neg=False, stock_pos=False,
                observed_confidence_delta=-0.4, observed_gdp_delta=-0.002,
                observed_hsi_pct_change=-0.015, observed_ccl_pct_change=-0.008,
                observed_unemployment_delta=0.001, observed_net_migration_delta=-150.0,
            ),
            HistoricalDataPoint(
                period="2022-Q3",
                neg_ratio=0.58, pos_ratio=0.28, emigration_freq=0.18,
                property_neg=True, employment_neg=False, stock_pos=False,
                observed_confidence_delta=-0.2, observed_gdp_delta=-0.001,
                observed_hsi_pct_change=-0.010, observed_ccl_pct_change=-0.005,
                observed_unemployment_delta=0.0005, observed_net_migration_delta=-80.0,
            ),
            HistoricalDataPoint(
                period="2022-Q4",
                neg_ratio=0.55, pos_ratio=0.32, emigration_freq=0.15,
                property_neg=False, employment_neg=True, stock_pos=False,
                observed_confidence_delta=-0.1, observed_gdp_delta=0.0,
                observed_hsi_pct_change=0.005, observed_ccl_pct_change=-0.002,
                observed_unemployment_delta=0.0008, observed_net_migration_delta=-60.0,
            ),
            HistoricalDataPoint(
                period="2023-Q1",
                neg_ratio=0.48, pos_ratio=0.38, emigration_freq=0.12,
                property_neg=False, employment_neg=False, stock_pos=True,
                observed_confidence_delta=0.15, observed_gdp_delta=0.001,
                observed_hsi_pct_change=0.012, observed_ccl_pct_change=0.003,
                observed_unemployment_delta=-0.0005, observed_net_migration_delta=50.0,
            ),
            HistoricalDataPoint(
                period="2023-Q2",
                neg_ratio=0.45, pos_ratio=0.42, emigration_freq=0.10,
                property_neg=False, employment_neg=False, stock_pos=True,
                observed_confidence_delta=0.18, observed_gdp_delta=0.0015,
                observed_hsi_pct_change=0.015, observed_ccl_pct_change=0.005,
                observed_unemployment_delta=-0.001, observed_net_migration_delta=80.0,
            ),
            HistoricalDataPoint(
                period="2023-Q3",
                neg_ratio=0.52, pos_ratio=0.35, emigration_freq=0.14,
                property_neg=True, employment_neg=False, stock_pos=False,
                observed_confidence_delta=-0.15, observed_gdp_delta=-0.0008,
                observed_hsi_pct_change=-0.008, observed_ccl_pct_change=-0.004,
                observed_unemployment_delta=0.0003, observed_net_migration_delta=-40.0,
            ),
            HistoricalDataPoint(
                period="2024-Q1",
                neg_ratio=0.50, pos_ratio=0.37, emigration_freq=0.12,
                property_neg=False, employment_neg=False, stock_pos=False,
                observed_confidence_delta=0.05, observed_gdp_delta=0.0005,
                observed_hsi_pct_change=0.003, observed_ccl_pct_change=0.001,
                observed_unemployment_delta=-0.0002, observed_net_migration_delta=20.0,
            ),
        ]
