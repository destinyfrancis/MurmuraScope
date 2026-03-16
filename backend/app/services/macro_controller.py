"""Macro-economic state management and shock injection for HK simulation.

This module re-exports key symbols from the split sub-modules and provides
the MacroController class for scenario management and feedback loops.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.app.services.calibration_config import (
    CalibrationParams,
    DEFAULT_CALIBRATION,
)

from backend.app.services.macro_state import (  # noqa: F401 — re-exports
    MacroState,
    VALID_SHOCK_TYPES,
    BASELINE_AVG_SQFT_PRICE,
    BASELINE_STAMP_DUTY,
    SHOCK_INTEREST_RATE_HIKE,
    SHOCK_PROPERTY_CRASH,
    SHOCK_UNEMPLOYMENT_SPIKE,
    SHOCK_POLICY_CHANGE,
    SHOCK_MARKET_RALLY,
    SHOCK_EMIGRATION_WAVE,
    SHOCK_FED_RATE_HIKE,
    SHOCK_FED_RATE_CUT,
    SHOCK_CHINA_SLOWDOWN,
    SHOCK_CHINA_STIMULUS,
    SHOCK_TAIWAN_STRAIT_TENSION,
    SHOCK_TAIWAN_STRAIT_EASE,
    SHOCK_SHENZHEN_MAGNET,
    SHOCK_GREATER_BAY_BOOST,
    SHOCK_TARIFF_INCREASE,
    SHOCK_SUPPLY_CHAIN_DISRUPTION,
    SHOCK_CHINA_DEMAND_COLLAPSE,
    SHOCK_RCEP_BENEFIT,
    apply_overrides,
)
from backend.app.services.macro_shocks import SHOCK_HANDLERS
from backend.app.services.macro_posts import SHOCK_POST_GENERATORS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DB → MacroState field mapping
# ---------------------------------------------------------------------------
_DB_FIELD_MAP: list[tuple[str, str, str]] = [
    ("interest_rate", "hibor_1m", "hibor_1m"),
    ("interest_rate", "hibor_3m", "hibor_1m"),
    ("interest_rate", "prime_rate", "prime_rate"),
    ("employment", "unemployment_rate", "unemployment_rate"),
    ("employment", "median_monthly_income", "median_monthly_income"),
    ("property", "ccl_index", "ccl_index"),
    ("property", "mortgage_cap", "mortgage_cap"),
    ("gdp", "gdp_growth_rate", "gdp_growth"),
    ("price_index", "cpi_yoy", "cpi_yoy"),
    ("finance", "hsi_level", "hsi_level"),
    ("sentiment", "consumer_confidence", "consumer_confidence"),
    ("population", "net_migration", "net_migration"),
    ("population", "birth_rate", "birth_rate"),
    ("housing", "public_housing_wait_years", "public_housing_wait_years"),
    ("external", "fed_rate", "fed_rate"),
    ("external", "usd_hkd", "usd_hkd"),
    ("external", "us_recession_prob", "us_recession_prob"),
    ("external", "china_gdp_growth", "china_gdp_growth"),
    ("external", "rmb_hkd", "rmb_hkd"),
    ("external", "china_property_crisis", "china_property_crisis"),
    ("external", "northbound_capital_bn", "northbound_capital_bn"),
    ("external", "taiwan_strait_risk", "taiwan_strait_risk"),
    ("external", "us_china_trade_tension", "us_china_trade_tension"),
    ("external", "shenzhen_cost_ratio", "shenzhen_cost_ratio"),
    ("external", "cross_border_residents", "cross_border_residents"),
    ("external", "greater_bay_policy_score", "greater_bay_policy_score"),
]


async def _load_user_data_points(session_id: str) -> dict[str, float]:
    """Load latest user-uploaded data points for a given session.

    Returns a mapping of MacroState field name → value.
    Falls through gracefully if the table does not exist or is empty.
    """
    from backend.app.utils.db import get_db  # noqa: PLC0415

    result: dict[str, float] = {}
    if not session_id:
        return result
    try:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT metric, value FROM user_data_points "
                "WHERE session_id=? ORDER BY timestamp DESC",
                (session_id,),
            )
            user_rows = await cursor.fetchall()
        for row in user_rows:
            metric = row[0] if isinstance(row, (list, tuple)) else row["metric"]
            value = row[1] if isinstance(row, (list, tuple)) else row["value"]
            if metric and metric not in result:
                result[str(metric)] = float(value)
    except Exception:
        logger.debug("_load_user_data_points: DB read skipped")
    return result


async def _load_from_data_lake(
    session_id: str = "",
    domain_pack_id: str = "hk_city",
) -> dict[str, float]:
    """Read latest values from data sources for all MacroState fields.

    For ``hk_city`` domain: reads from ``hk_data_snapshots`` table (backward compat).
    For other domains: uses the pack's ``macro_baselines`` + user-uploaded data.

    If *session_id* is provided, user-uploaded data points for that session
    are applied on top (user data takes precedence).
    """
    from backend.app.utils.db import get_db  # noqa: PLC0415

    result: dict[str, float] = {}

    # For non-HK domains, use pack baselines instead of hk_data_snapshots
    if domain_pack_id != "hk_city":
        try:
            from backend.app.domain.base import DomainPackRegistry  # noqa: PLC0415
            pack = DomainPackRegistry.get(domain_pack_id)
            if pack.macro_baselines:
                result = {k: float(v) for k, v in pack.macro_baselines.items()}
                logger.info(
                    "_load_from_data_lake: loaded %d baselines from pack '%s'",
                    len(result), domain_pack_id,
                )
        except (KeyError, Exception):
            logger.debug(
                "_load_from_data_lake: pack '%s' not found, using defaults",
                domain_pack_id,
            )

        # Override with user-uploaded data
        if session_id:
            user_data = await _load_user_data_points(session_id)
            if user_data:
                result.update(user_data)
        return result

    # HK domain: read from hk_data_snapshots (original behavior)
    try:
        async with get_db() as db:
            cursor = await db.execute(
                """
                SELECT h.category, h.metric, h.value
                FROM hk_data_snapshots h
                INNER JOIN (
                    SELECT category, metric, MAX(period || '|' || created_at) AS max_key
                    FROM hk_data_snapshots
                    GROUP BY category, metric
                ) latest
                ON h.category = latest.category
                   AND h.metric = latest.metric
                   AND (h.period || '|' || h.created_at) = latest.max_key
                """
            )
            rows = await cursor.fetchall()

        db_lookup: dict[tuple[str, str], float] = {}
        for row in rows:
            key = (row["category"], row["metric"])
            if key not in db_lookup:
                db_lookup[key] = float(row["value"])

        _RATE_FIELDS = {"hibor_1m", "prime_rate", "fed_rate"}

        for category, metric, field in _DB_FIELD_MAP:
            if field not in result:
                val = db_lookup.get((category, metric))
                if val is not None:
                    if field in _RATE_FIELDS and val > 0.5:
                        val = val / 100.0
                    result[field] = val

    except Exception:
        logger.debug("_load_from_data_lake: DB read skipped (table may be empty)")

    # Override with user-uploaded data (takes precedence over data lake)
    if session_id:
        user_data = await _load_user_data_points(session_id)
        if user_data:
            logger.info(
                "_load_from_data_lake: applying %d user data overrides for session=%s",
                len(user_data), session_id,
            )
            result.update(user_data)

    return result


class MacroController:
    """Manages macro scenarios and shock injection."""

    # Lag rules: how many rounds of delay before sentiment affects each indicator
    _SENTIMENT_LAG: dict[str, int] = {
        "consumer_confidence": 0,  # immediate
        "hsi_level": 0,            # market reacts fast
        "ccl_index": 2,            # property market is slow
        "unemployment_rate": 2,    # labour market is slow
        "gdp_growth": 3,           # GDP is lagging
        "net_migration": 4,        # emigration decisions are slow
    }

    def __init__(self) -> None:
        self._scenarios: dict[str, MacroState] = {}
        # Sentiment buffer: stores recent rounds' sentiment ratios for lag effects
        self._sentiment_buffer: list[dict[str, float]] = []

    async def get_baseline(
        self,
        session_id: str = "",
        domain_pack_id: str = "hk_city",
    ) -> MacroState:
        """Load baseline from DB or fall back to hardcoded 2024-Q1 snapshot.

        If *session_id* is provided, user-uploaded data points override
        the corresponding data-lake values for that session.
        For non-HK domains, uses the pack's macro_baselines.
        """
        db_values = await _load_from_data_lake(
            session_id=session_id,
            domain_pack_id=domain_pack_id,
        )

        return MacroState(
            hibor_1m=db_values.get("hibor_1m", 0.040),
            prime_rate=db_values.get("prime_rate", 0.055),
            unemployment_rate=db_values.get("unemployment_rate", 0.032),
            median_monthly_income=int(db_values.get("median_monthly_income", 20_800)),
            ccl_index=db_values.get("ccl_index", 150.0),
            avg_sqft_price=dict(BASELINE_AVG_SQFT_PRICE),
            mortgage_cap=db_values.get("mortgage_cap", 0.70),
            stamp_duty_rates=dict(BASELINE_STAMP_DUTY),
            gdp_growth=db_values.get("gdp_growth", 0.025),
            cpi_yoy=db_values.get("cpi_yoy", 0.019),
            hsi_level=db_values.get("hsi_level", 20_060.0),
            consumer_confidence=db_values.get("consumer_confidence", 45.0),
            net_migration=int(db_values.get("net_migration", 2_000)),
            birth_rate=db_values.get("birth_rate", 5.3),
            policy_flags={
                "辣招撤銷": True,
                "高才通計劃": True,
                "公屋輪候年期": db_values.get("public_housing_wait_years", 5.5),
            },
            fed_rate=db_values.get("fed_rate", 0.045),
            usd_hkd=db_values.get("usd_hkd", 7.80),
            china_gdp_growth=db_values.get("china_gdp_growth", 0.048),
            rmb_hkd=db_values.get("rmb_hkd", 1.072),
            china_property_crisis=db_values.get("china_property_crisis", 0.5),
            northbound_capital_bn=db_values.get("northbound_capital_bn", 130.0),
            taiwan_strait_risk=db_values.get("taiwan_strait_risk", 0.25),
            us_china_trade_tension=db_values.get("us_china_trade_tension", 0.65),
            shenzhen_cost_ratio=db_values.get("shenzhen_cost_ratio", 0.36),
            cross_border_residents=int(db_values.get("cross_border_residents", 55_000)),
            greater_bay_policy_score=db_values.get("greater_bay_policy_score", 0.60),
        )

    async def get_baseline_for_scenario(self, scenario_type: str) -> MacroState:
        """Get a baseline MacroState pre-tuned for a specific simulation scenario."""
        base = await self.get_baseline()

        scenario_overrides: dict[str, dict[str, Any]] = {
            "property": {
                "policy_flags": {
                    **base.policy_flags,
                    "按揭保險上限提高": True,
                    "大灣區置業試點": True,
                },
            },
            "emigration": {
                "taiwan_strait_risk": base.taiwan_strait_risk + 0.1,
                "net_migration": base.net_migration - 5_000,
                "policy_flags": {
                    **base.policy_flags,
                    "BNO簽證": True,
                    "加拿大移民配額": True,
                    "澳洲技術移民": True,
                },
            },
            "fertility": {
                "shenzhen_cost_ratio": base.shenzhen_cost_ratio - 0.03,
                "cross_border_residents": base.cross_border_residents + 10_000,
                "policy_flags": {
                    **base.policy_flags,
                    "生育津貼計劃": True,
                    "跨境學位認可": True,
                },
            },
            "career": {
                "us_china_trade_tension": base.us_china_trade_tension + 0.05,
                "china_gdp_growth": base.china_gdp_growth - 0.005,
                "policy_flags": {
                    **base.policy_flags,
                    "高才通": True,
                    "科技人才入境計劃": True,
                },
            },
            "b2b": {
                "us_china_trade_tension": base.us_china_trade_tension,
                "china_gdp_growth": base.china_gdp_growth,
                "policy_flags": {
                    **base.policy_flags,
                    "RCEP生效": True,
                    "數字人民幣試點": True,
                },
            },
            "opinion": {
                "taiwan_strait_risk": base.taiwan_strait_risk,
                "us_china_trade_tension": base.us_china_trade_tension,
                "policy_flags": {
                    **base.policy_flags,
                    "23條立法": True,
                    "選舉制度改革": True,
                },
            },
        }

        overrides = scenario_overrides.get(scenario_type, {})
        if overrides:
            logger.info("Applying scenario-specific overrides for '%s'", scenario_type)
            return apply_overrides(base, overrides)
        return base

    async def create_scenario(
        self, name: str, overrides: dict[str, Any]
    ) -> MacroState:
        """Create a named scenario by applying overrides to the baseline."""
        baseline = await self.get_baseline()
        scenario = apply_overrides(baseline, overrides)
        self._scenarios = {**self._scenarios, name: scenario}
        logger.info("Created macro scenario '%s' with %d overrides", name, len(overrides))
        return scenario

    def get_scenario(self, name: str) -> MacroState | None:
        return self._scenarios.get(name)

    def apply_shock(
        self,
        state: MacroState,
        shock_type: str,
        params: dict[str, Any],
        domain_pack_id: str = "hk_city",
    ) -> MacroState:
        """Return a new MacroState with the specified shock applied."""
        from backend.app.domain.base import DomainPackRegistry  # noqa: PLC0415

        try:
            pack = DomainPackRegistry.get(domain_pack_id)
            valid_types = pack.valid_shock_types
        except KeyError:
            valid_types = VALID_SHOCK_TYPES

        if shock_type not in valid_types:
            raise ValueError(
                f"Unknown shock type '{shock_type}'. "
                f"Valid types: {sorted(valid_types)}"
            )

        handler = SHOCK_HANDLERS.get(shock_type)
        if handler is None:
            raise NotImplementedError(f"Handler for '{shock_type}' not registered")
        return handler(state, params)

    def generate_shock_post(self, shock_type: str, state: MacroState) -> str:
        """Generate a news-style social media post for OASIS ManualAction injection."""
        if shock_type not in VALID_SHOCK_TYPES:
            raise ValueError(f"Unknown shock type '{shock_type}'")

        generator = SHOCK_POST_GENERATORS.get(shock_type)
        if generator is None:
            raise NotImplementedError(
                f"Post generator for '{shock_type}' not registered"
            )
        return generator(state)

    async def update_from_actions(
        self,
        current_state: MacroState,
        session_id: str,
        round_number: int,
        lookback_rounds: int = 5,
        calibration: CalibrationParams = DEFAULT_CALIBRATION,
        ets_forecast: dict[str, Any] | None = None,
    ) -> MacroState:
        """Compute macro adjustments based on agent sentiment and topics.

        All magic numbers are sourced from *calibration* so they can be tuned
        without modifying source code.  An optional *ets_forecast* dict (from
        ``TimeSeriesForecaster``) provides a trend baseline for GDP / CPI /
        HSI; when present the sentiment delta is applied on top of the
        forecast point rather than the current state value.

        Args:
            current_state: The most recent ``MacroState``.
            session_id: Simulation session UUID (used to query action logs).
            round_number: The round that just completed.
            lookback_rounds: How many rounds of history to aggregate.
            calibration: Parameter set controlling thresholds and deltas.
            ets_forecast: Optional mapping of indicator_name → ForecastPoint
                for trend-adjusted baselines (Phase E integration).

        Returns:
            New ``MacroState`` with sentiment-adjusted indicators.
        """
        from backend.app.utils.db import get_db  # noqa: PLC0415

        min_round = max(0, round_number - lookback_rounds + 1)

        try:
            async with get_db() as db:
                cursor = await db.execute(
                    """
                    SELECT sentiment, topics
                    FROM simulation_actions
                    WHERE session_id = ?
                      AND round_number BETWEEN ? AND ?
                    """,
                    (session_id, min_round, round_number),
                )
                rows = await cursor.fetchall()
        except Exception:
            logger.exception(
                "update_from_actions: DB read failed session=%s round=%d",
                session_id, round_number,
            )
            return current_state

        if not rows:
            return current_state

        total = len(rows)
        pos_count = 0
        neg_count = 0
        topic_counter: dict[str, int] = {}

        for row in rows:
            sentiment = row[0] if isinstance(row, (list, tuple)) else row["sentiment"]
            topics_raw = row[1] if isinstance(row, (list, tuple)) else row["topics"]

            if sentiment == "positive":
                pos_count += 1
            elif sentiment == "negative":
                neg_count += 1

            try:
                topics: list[str] = json.loads(topics_raw) if topics_raw else []
            except (json.JSONDecodeError, TypeError):
                topics = []
            for t in topics:
                topic_counter[t] = topic_counter.get(t, 0) + 1

        pos_ratio = pos_count / total
        neg_ratio = neg_count / total

        # Store current sentiment in lag buffer (keep last 5 rounds)
        self._sentiment_buffer.append({
            "pos_ratio": pos_ratio,
            "neg_ratio": neg_ratio,
            "round": round_number,
        })
        if len(self._sentiment_buffer) > 5:
            self._sentiment_buffer = self._sentiment_buffer[-5:]

        # Helper: get lagged sentiment ratio for a given indicator
        def _get_lagged_ratio(indicator: str, ratio_type: str) -> float:
            lag = self._SENTIMENT_LAG.get(indicator, 0)
            if lag == 0:
                return pos_ratio if ratio_type == "pos" else neg_ratio
            # Look back 'lag' entries in buffer
            buf_idx = len(self._sentiment_buffer) - 1 - lag
            if buf_idx < 0:
                return 0.0  # not enough history yet
            entry = self._sentiment_buffer[buf_idx]
            return entry.get(f"{ratio_type}_ratio", 0.0)

        # Log which fields use default vs real data
        db_values_used = await _load_from_data_lake(session_id=session_id)
        defaults_used = []
        for field in ("hibor_1m", "unemployment_rate", "hsi_level", "gdp_growth"):
            if field not in db_values_used:
                defaults_used.append(field)
        if defaults_used:
            logger.debug("MacroController using defaults for: %s", defaults_used)

        # Phase E: use forecast point as baseline when available.
        # The sentiment delta is applied on top of the trend forecast.
        def _forecast_base(indicator: str, fallback: float) -> float:
            if ets_forecast and indicator in ets_forecast:
                pt = ets_forecast[indicator]
                return float(pt.value) if hasattr(pt, "value") else float(pt)
            return fallback

        new_consumer_confidence = current_state.consumer_confidence
        new_gdp_growth = _forecast_base("gdp_growth", current_state.gdp_growth)
        new_hsi_level = _forecast_base("hsi_level", current_state.hsi_level)
        new_ccl_index = _forecast_base("ccl_index", current_state.ccl_index)
        new_unemployment_rate = current_state.unemployment_rate
        new_net_migration = current_state.net_migration

        # Primary sentiment signal (with lag effects)
        # Consumer confidence and HSI react immediately (lag 0)
        neg_conf = _get_lagged_ratio("consumer_confidence", "neg")
        pos_conf = _get_lagged_ratio("consumer_confidence", "pos")
        if neg_conf > calibration.neg_threshold:
            new_consumer_confidence = round(
                new_consumer_confidence - calibration.confidence_delta_neg, 2
            )
        elif pos_conf > calibration.pos_threshold:
            new_consumer_confidence = round(
                new_consumer_confidence + calibration.confidence_delta_pos, 2
            )

        # GDP reacts with lag 3
        neg_gdp = _get_lagged_ratio("gdp_growth", "neg")
        if neg_gdp > calibration.neg_threshold:
            new_gdp_growth = round(new_gdp_growth - calibration.gdp_delta_neg, 4)

        # HSI reacts immediately
        pos_hsi = _get_lagged_ratio("hsi_level", "pos")
        if pos_hsi > calibration.pos_threshold:
            new_hsi_level = round(new_hsi_level * calibration.hsi_pos_factor, 0)

        # Topic-specific adjustments
        property_freq = topic_counter.get("property", 0) / total
        employment_freq = topic_counter.get("employment", 0) / total
        emigration_freq = topic_counter.get("emigration", 0) / total
        stock_freq = topic_counter.get("stock_market", 0) / total

        if (
            property_freq > calibration.property_topic_threshold
            and neg_ratio > calibration.secondary_sentiment_threshold
        ):
            new_ccl_index = round(new_ccl_index * calibration.property_neg_ccl_factor, 2)

        if (
            employment_freq > calibration.employment_topic_threshold
            and neg_ratio > calibration.secondary_sentiment_threshold
        ):
            new_unemployment_rate = round(
                new_unemployment_rate + calibration.employment_neg_unemployment_delta, 4
            )

        if emigration_freq > calibration.emigration_threshold:
            new_net_migration = new_net_migration - calibration.emigration_net_migration_delta

        if (
            stock_freq > calibration.stock_topic_threshold
            and pos_ratio > calibration.secondary_sentiment_threshold
        ):
            new_hsi_level = round(new_hsi_level * calibration.stock_pos_hsi_factor, 0)

        # Clamp to safe ranges
        new_consumer_confidence = max(
            calibration.clamp_confidence_min,
            min(calibration.clamp_confidence_max, new_consumer_confidence),
        )
        new_gdp_growth = max(
            calibration.clamp_gdp_min, min(calibration.clamp_gdp_max, new_gdp_growth)
        )
        new_hsi_level = max(
            calibration.clamp_hsi_min, min(calibration.clamp_hsi_max, new_hsi_level)
        )
        new_ccl_index = max(
            calibration.clamp_ccl_min, min(calibration.clamp_ccl_max, new_ccl_index)
        )
        new_unemployment_rate = max(
            calibration.clamp_unemployment_min,
            min(calibration.clamp_unemployment_max, new_unemployment_rate),
        )
        new_net_migration = max(
            calibration.clamp_net_migration_min,
            min(calibration.clamp_net_migration_max, new_net_migration),
        )

        from dataclasses import replace as _replace  # noqa: PLC0415
        return _replace(
            current_state,
            consumer_confidence=new_consumer_confidence,
            gdp_growth=new_gdp_growth,
            hsi_level=new_hsi_level,
            ccl_index=new_ccl_index,
            unemployment_rate=new_unemployment_rate,
            net_migration=new_net_migration,
        )

    async def get_forecast_adjusted_baseline(
        self,
        state: MacroState,
        horizon: int = 1,
    ) -> dict[str, Any]:
        """Return a dict of ForecastPoint values for key macro indicators.

        Uses ``TimeSeriesForecaster`` to project 1 step ahead.  The result
        can be passed directly as *ets_forecast* to ``update_from_actions()``.

        Falls back to empty dict if the forecaster is unavailable.

        Args:
            state: Current macro state (used if forecaster has no data).
            horizon: Forecast horizon in quarters.  Default 1.

        Returns:
            Dict mapping indicator name → ForecastPoint (or plain float).
        """
        from backend.app.services.time_series_forecaster import (  # noqa: PLC0415
            TimeSeriesForecaster,
            SUPPORTED_METRICS,
        )

        forecaster = TimeSeriesForecaster()
        result: dict[str, Any] = {}

        for metric in SUPPORTED_METRICS:
            try:
                forecast_result = await forecaster.forecast(metric, horizon=horizon)
                if forecast_result.points:
                    result[metric] = forecast_result.points[0]
            except Exception:
                logger.debug(
                    "get_forecast_adjusted_baseline: forecaster failed for metric=%s", metric
                )

        logger.info(
            "Forecast-adjusted baseline ready: %d indicators", len(result)
        )
        return result

    @staticmethod
    def _apply_overrides(
        state: MacroState, overrides: dict[str, Any]
    ) -> MacroState:
        """Backward-compatible static method — delegates to module-level function."""
        return apply_overrides(state, overrides)
