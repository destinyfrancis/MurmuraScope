"""Retail Forecaster — links ConsumerModel to HK retail baseline data.

Reads agent decisions and spending profiles to produce sector-level retail
trend forecasts grounded in actual HK retail sales data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.services.agent_factory import AgentProfile
from backend.app.services.consumer_model import ConsumerModel, SpendingProfile
from backend.app.services.macro_state import MacroState
from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("retail_forecaster")

# ---------------------------------------------------------------------------
# HK Retail Baseline (2023 annual, HKD billion, approximate)
# Source: Census & Statistics Department
# ---------------------------------------------------------------------------

_RETAIL_BASELINE_HKD_BN: dict[str, float] = {
    "food":           72.5,   # Food, alcoholic drinks & tobacco
    "entertainment":  38.2,   # Clothing, footwear, recreation & gifts
    "healthcare":     22.8,   # Medicines & cosmetics
    "education":       8.4,   # Books, stationery, education services
    "transport":      15.6,   # Fuel, vehicle parts, transport services
    "housing":        18.9,   # Furniture, furnishings, household goods
}

_TOTAL_RETAIL_BASELINE_HKD_BN: float = sum(_RETAIL_BASELINE_HKD_BN.values())

# Tourist contribution to retail (approx. 30% in 2023)
_TOURIST_RETAIL_SHARE: float = 0.30

# ---------------------------------------------------------------------------
# RetailForecast dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RetailForecast:
    """Immutable retail forecast snapshot for one simulation round."""

    session_id: str
    round_number: int
    sector_index: dict[str, float]     # sector → index (100 = baseline)
    total_index: float                 # overall retail index
    yoy_change_pct: float              # estimated YoY change %
    tourist_impact: float              # scaled visitor arrivals factor
    top_sector: str                    # highest growth sector
    bottom_sector: str                 # lowest growth sector
    agent_count: int
    avg_savings_rate: float


# ---------------------------------------------------------------------------
# RetailForecaster
# ---------------------------------------------------------------------------

class RetailForecaster:
    """Links ConsumerModel outputs to HK retail sector forecasts."""

    def __init__(self) -> None:
        self._consumer_model = ConsumerModel()

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    async def forecast_retail(
        self,
        session_id: str,
        round_number: int,
        macro_state: MacroState,
    ) -> RetailForecast:
        """Produce a retail sector forecast for a simulation round.

        Reads agent profiles and recent decision data from the DB, computes
        spending profiles for each agent, then scales against the HK retail
        baseline.

        Args:
            session_id: Simulation session UUID.
            round_number: Current round number.
            macro_state: Current macro-economic state.

        Returns:
            Immutable ``RetailForecast``.
        """
        profiles = await self._load_agent_profiles(session_id)
        if not profiles:
            logger.warning(
                "No agent profiles found for session=%s — returning baseline forecast",
                session_id,
            )
            return self._baseline_forecast(session_id, round_number)

        sentiment_map = await self._load_sentiment_map(session_id, round_number)

        spending_profiles = self._consumer_model.generate_batch(
            profiles, macro_state, sentiment_map
        )
        incomes = [p.monthly_income for p in profiles]

        agg = self._consumer_model.aggregate_retail_forecast(spending_profiles, incomes)
        if not agg:
            return self._baseline_forecast(session_id, round_number)

        sector_index = self._compute_sector_index(agg, macro_state)
        total_index = sum(sector_index.values()) / max(len(sector_index), 1)
        yoy_change_pct = (total_index - 100.0) / 100.0 * 100.0   # as %

        top_sector = max(sector_index, key=sector_index.get)  # type: ignore[arg-type]
        bottom_sector = min(sector_index, key=sector_index.get)  # type: ignore[arg-type]

        tourist_impact = self._estimate_tourist_impact(macro_state)

        forecast = RetailForecast(
            session_id=session_id,
            round_number=round_number,
            sector_index=sector_index,
            total_index=round(total_index, 2),
            yoy_change_pct=round(yoy_change_pct, 2),
            tourist_impact=round(tourist_impact, 4),
            top_sector=top_sector,
            bottom_sector=bottom_sector,
            agent_count=agg.get("agent_count", 0),
            avg_savings_rate=agg.get("avg_savings_rate", 0.0),
        )

        logger.info(
            "Retail forecast: session=%s round=%d total_idx=%.1f yoy=%.2f%% top=%s",
            session_id,
            round_number,
            total_index,
            yoy_change_pct,
            top_sector,
        )
        return forecast

    def generate_narrative(self, forecast: RetailForecast) -> str:
        """Generate a Cantonese narrative summary of the retail forecast.

        Args:
            forecast: The computed ``RetailForecast``.

        Returns:
            Multi-line Traditional Chinese narrative string.
        """
        direction = "上升" if forecast.yoy_change_pct >= 0 else "下跌"
        abs_change = abs(forecast.yoy_change_pct)

        sector_zh = {
            "food": "食品飲料",
            "entertainment": "娛樂消閒",
            "healthcare": "醫療保健",
            "education": "教育書籍",
            "transport": "交通運輸",
            "housing": "家居用品",
        }

        top_zh = sector_zh.get(forecast.top_sector, forecast.top_sector)
        bot_zh = sector_zh.get(forecast.bottom_sector, forecast.bottom_sector)

        tourist_label = (
            "旅客消費強勁" if forecast.tourist_impact > 1.1
            else "旅客消費疲弱" if forecast.tourist_impact < 0.9
            else "旅客消費平穩"
        )

        savings_label = (
            "市民傾向多儲蓄" if forecast.avg_savings_rate > 0.22
            else "市民消費意欲較強"
        )

        return (
            f"【零售業前景預測｜第 {forecast.round_number} 輪】\n"
            f"整體零售指數：{forecast.total_index:.1f}（按年{direction} {abs_change:.1f}%）\n"
            f"最強板塊：{top_zh}（指數 {forecast.sector_index.get(forecast.top_sector, 100):.1f}）\n"
            f"最弱板塊：{bot_zh}（指數 {forecast.sector_index.get(forecast.bottom_sector, 100):.1f}）\n"
            f"旅遊業影響：{tourist_label}（因子 {forecast.tourist_impact:.2f}）\n"
            f"住戶儲蓄率：{forecast.avg_savings_rate:.1%}（{savings_label}）\n"
            f"樣本代理人數：{forecast.agent_count:,} 人"
        )

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    async def _load_agent_profiles(self, session_id: str) -> list[AgentProfile]:
        """Load all agent profiles for a session from the DB."""
        profiles: list[AgentProfile] = []
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    "SELECT * FROM agent_profiles WHERE session_id = ?",
                    (session_id,),
                )
                rows = await cursor.fetchall()

            for r in rows:
                profiles.append(
                    AgentProfile(
                        id=r["id"],
                        agent_type=r["agent_type"],
                        age=r["age"],
                        sex=r["sex"],
                        district=r["district"],
                        occupation=r["occupation"],
                        income_bracket=r["income_bracket"],
                        education_level=r["education_level"],
                        marital_status=r["marital_status"],
                        housing_type=r["housing_type"],
                        openness=r["openness"],
                        conscientiousness=r["conscientiousness"],
                        extraversion=r["extraversion"],
                        agreeableness=r["agreeableness"],
                        neuroticism=r["neuroticism"],
                        monthly_income=r["monthly_income"] or 0,
                        savings=r["savings"] or 0,
                    )
                )
        except Exception:
            logger.exception("Failed to load agent profiles for session=%s", session_id)
        return profiles

    async def _load_sentiment_map(
        self, session_id: str, round_number: int
    ) -> dict[int, str]:
        """Load sentiment per agent for the given round from simulation_actions."""
        sentiment_map: dict[int, str] = {}
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    """
                    SELECT agent_id, sentiment
                    FROM simulation_actions
                    WHERE session_id = ? AND round_number = ?
                      AND sentiment IS NOT NULL
                    """,
                    (session_id, round_number),
                )
                rows = await cursor.fetchall()

            for r in rows:
                agent_id = r["agent_id"]
                if agent_id and agent_id not in sentiment_map:
                    sentiment_map[agent_id] = r["sentiment"] or "neutral"
        except Exception:
            logger.debug(
                "Could not load sentiment_map for session=%s round=%d",
                session_id,
                round_number,
            )
        return sentiment_map

    def _compute_sector_index(
        self,
        agg: dict[str, Any],
        macro_state: MacroState,
    ) -> dict[str, float]:
        """Compute sector retail indices (100 = baseline) from aggregate data.

        Combines agent spending proportions with macro adjustments.
        """
        breakdown: dict[str, float] = agg.get("sector_breakdown", {})
        total_agent_spend = sum(breakdown.values())
        if total_agent_spend <= 0:
            return {s: 100.0 for s in _RETAIL_BASELINE_HKD_BN}

        # Tourist impact multiplier
        tourist_factor = self._estimate_tourist_impact(macro_state)

        indices: dict[str, float] = {}
        for sector, baseline_bn in _RETAIL_BASELINE_HKD_BN.items():
            agent_spend = breakdown.get(sector, 0.0)
            # Share of total agent spending vs baseline share
            agent_share = agent_spend / total_agent_spend
            baseline_share = baseline_bn / _TOTAL_RETAIL_BASELINE_HKD_BN

            if baseline_share <= 0:
                indices[sector] = 100.0
                continue

            raw_index = (agent_share / baseline_share) * 100.0

            # Tourist-sensitive sectors get boosted/dampened
            tourist_sensitive = sector in ("entertainment", "healthcare", "food")
            if tourist_sensitive:
                raw_index = raw_index * (1.0 + (tourist_factor - 1.0) * _TOURIST_RETAIL_SHARE)

            indices[sector] = round(raw_index, 2)

        return indices

    def _estimate_tourist_impact(self, macro_state: MacroState) -> float:
        """Estimate a tourist spending multiplier based on macro conditions.

        Factors: geopolitical risk, consumer confidence, USD/HKD (affordability).
        Returns a multiplier (1.0 = baseline, >1 = above baseline).
        """
        # High geopolitical risk reduces tourism
        geo_penalty = macro_state.taiwan_strait_risk * 0.3

        # Consumer confidence correlates with visitor sentiment
        confidence_boost = (macro_state.consumer_confidence - 50.0) / 100.0 * 0.2

        # Weaker HKD (higher usd_hkd) → more affordable for USD tourists
        fx_boost = max(0.0, (macro_state.usd_hkd - 7.75) / 7.75 * 0.5)

        return max(0.5, min(1.8, 1.0 - geo_penalty + confidence_boost + fx_boost))

    def _baseline_forecast(self, session_id: str, round_number: int) -> RetailForecast:
        """Return a neutral baseline forecast when agent data is unavailable."""
        return RetailForecast(
            session_id=session_id,
            round_number=round_number,
            sector_index={s: 100.0 for s in _RETAIL_BASELINE_HKD_BN},
            total_index=100.0,
            yoy_change_pct=0.0,
            tourist_impact=1.0,
            top_sector="food",
            bottom_sector="education",
            agent_count=0,
            avg_savings_rate=0.18,
        )
