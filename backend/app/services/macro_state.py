"""MacroState dataclass and baseline constants for HK macro-economic simulation."""

from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from typing import Any

# ---------------------------------------------------------------------------
# Shock type constants
# ---------------------------------------------------------------------------
SHOCK_INTEREST_RATE_HIKE = "interest_rate_hike"
SHOCK_PROPERTY_CRASH = "property_crash"
SHOCK_UNEMPLOYMENT_SPIKE = "unemployment_spike"
SHOCK_POLICY_CHANGE = "policy_change"
SHOCK_MARKET_RALLY = "market_rally"
SHOCK_EMIGRATION_WAVE = "emigration_wave"
# External shocks
SHOCK_FED_RATE_HIKE = "fed_rate_hike"
SHOCK_FED_RATE_CUT = "fed_rate_cut"
SHOCK_CHINA_SLOWDOWN = "china_slowdown"
SHOCK_CHINA_STIMULUS = "china_stimulus"
SHOCK_TAIWAN_STRAIT_TENSION = "taiwan_strait_tension"
SHOCK_TAIWAN_STRAIT_EASE = "taiwan_strait_ease"
SHOCK_SHENZHEN_MAGNET = "shenzhen_magnet"
SHOCK_GREATER_BAY_BOOST = "greater_bay_boost"
# B2B shocks (Phase 5)
SHOCK_TARIFF_INCREASE = "tariff_increase"
SHOCK_SUPPLY_CHAIN_DISRUPTION = "supply_chain_disruption"
SHOCK_CHINA_DEMAND_COLLAPSE = "china_demand_collapse"
SHOCK_RCEP_BENEFIT = "rcep_benefit"

VALID_SHOCK_TYPES = frozenset(
    {
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
    }
)


# ---------------------------------------------------------------------------
# Baseline HK macro snapshot (approx. 2024-Q1 estimates)
# ---------------------------------------------------------------------------
BASELINE_AVG_SQFT_PRICE: dict[str, int] = {
    "中西區": 18_500,
    "灣仔": 19_200,
    "東區": 14_800,
    "南區": 15_600,
    "油尖旺": 16_200,
    "深水埗": 13_500,
    "九龍城": 15_900,
    "黃大仙": 11_800,
    "觀塘": 12_600,
    "葵青": 10_800,
    "荃灣": 11_500,
    "屯門": 9_200,
    "元朗": 9_600,
    "北區": 9_000,
    "大埔": 10_200,
    "沙田": 12_800,
    "西貢": 11_900,
    "離島": 10_500,
}

BASELINE_STAMP_DUTY: dict[str, float] = {
    "ad_valorem_scale_1": 0.015,  # ≤$3M
    "ad_valorem_scale_2": 0.0375,  # $3M–$6M
    "ad_valorem_scale_3": 0.075,  # $6M–$10M (post撤辣)
    "non_first_time": 0.075,
    "non_hkpr": 0.075,
}


@dataclass(frozen=True)
class MacroState:
    """Immutable Hong Kong macro-economic snapshot.

    Includes both local HK indicators and external macro factors
    (US Fed, China economy, Taiwan Strait risk, Shenzhen competition).
    """

    # ---- Local HK indicators ----
    hibor_1m: float
    prime_rate: float
    unemployment_rate: float
    median_monthly_income: int
    ccl_index: float
    avg_sqft_price: dict[str, int]
    mortgage_cap: float
    stamp_duty_rates: dict[str, float]
    gdp_growth: float
    cpi_yoy: float
    hsi_level: float
    consumer_confidence: float
    net_migration: int
    birth_rate: float
    policy_flags: dict[str, Any]

    # ---- External / geopolitical factors ----
    # US Federal Reserve
    fed_rate: float = 0.053  # Fed Funds Rate upper bound (2024-Q1)
    usd_hkd: float = 7.82  # USD/HKD exchange rate (linked rate band)

    # China economy
    china_gdp_growth: float = 0.052  # China real GDP growth (2024 forecast)
    rmb_hkd: float = 1.076  # RMB/HKD (higher = weaker RMB vs HKD)
    china_property_crisis: float = 0.6  # 0-1 severity (Evergrande aftermath)
    northbound_capital_bn: float = 120.0  # Stock Connect north flow HKD bn/yr

    # Geopolitical risk
    taiwan_strait_risk: float = 0.3  # 0=calm, 1=crisis
    us_china_trade_tension: float = 0.6  # 0=free trade, 1=full decoupling

    # Shenzhen / Greater Bay Area
    shenzhen_cost_ratio: float = 0.38  # SZ living cost / HK living cost
    cross_border_residents: int = 50_000  # HKers living in GBA (cross-border)
    greater_bay_policy_score: float = 0.55  # 0-1 GBA integration progress

    # ---- B2B / Trade factors (Phase 5) ----
    import_tariff_rate: float = 0.0  # weighted average tariff %
    export_logistics_cost: float = 1.0  # logistics cost index (1.0 = baseline)
    supply_chain_disruption: float = 0.0  # 0-1 supply chain disruption severity
    china_import_demand: float = 0.0  # China import demand change %

    # ---- Banking / Credit cycle (Workstream E3) ----
    bank_ltv_cap: float = 0.60  # HKMA LTV cap (currently 60%)
    credit_growth_yoy: float = 0.02  # YoY credit growth (2% baseline)
    interbank_spread: float = 0.005  # interbank spread (50bps baseline)
    mortgage_delinquency: float = 0.015  # NPL/delinquency ratio (~1.5%)
    bank_reserve_ratio: float = 0.08  # reserve ratio (8% baseline)

    def to_prompt_context(self) -> str:
        """Return a Chinese-language prompt block summarising the full macro environment."""
        top_3_expensive = sorted(self.avg_sqft_price.items(), key=lambda kv: kv[1], reverse=True)[:3]
        top_districts = "、".join(f"{d}（${p:,}/呎）" for d, p in top_3_expensive)

        policy_lines = (
            "\n".join(f"  - {k}: {v}" for k, v in self.policy_flags.items())
            if self.policy_flags
            else "  （無特殊政策標記）"
        )

        taiwan_risk_label = (
            "高危" if self.taiwan_strait_risk > 0.7 else "中等緊張" if self.taiwan_strait_risk > 0.4 else "相對穩定"
        )
        trade_label = (
            "嚴重對立"
            if self.us_china_trade_tension > 0.7
            else "持續摩擦"
            if self.us_china_trade_tension > 0.4
            else "相對緩和"
        )

        return (
            "【香港宏觀經濟環境】\n"
            f"一個月 HIBOR：{self.hibor_1m:.2%}\n"
            f"最優惠利率（P Rate）：{self.prime_rate:.2%}\n"
            f"失業率：{self.unemployment_rate:.1%}\n"
            f"每月入息中位數：HK${self.median_monthly_income:,}\n"
            f"中原城市領先指數（CCL）：{self.ccl_index:.1f}\n"
            f"最貴地區（每呎均價）：{top_districts}\n"
            f"按揭成數上限：{self.mortgage_cap:.0%}\n"
            f"GDP 增長：{self.gdp_growth:.1%}\n"
            f"CPI 按年變幅：{self.cpi_yoy:.1%}\n"
            f"恒生指數：{self.hsi_level:,.0f}\n"
            f"消費者信心指數：{self.consumer_confidence:.1f}\n"
            f"淨遷移人數：{self.net_migration:+,}\n"
            f"出生率：{self.birth_rate:.1f}‰\n"
            f"政策標記：\n{policy_lines}\n"
            "\n【外圍因素】\n"
            f"美聯儲利率（Fed Rate）：{self.fed_rate:.2%}｜美元/港元：{self.usd_hkd:.2f}（聯繫匯率）\n"
            f"中國GDP增長：{self.china_gdp_growth:.1%}｜人民幣/港元：{self.rmb_hkd:.3f}\n"
            f"中國房地產危機嚴重程度：{self.china_property_crisis:.0%}｜北水流入：HKD {self.northbound_capital_bn:.0f}億/年\n"
            f"台海局勢：{taiwan_risk_label}（風險指數 {self.taiwan_strait_risk:.1f}）\n"
            f"中美貿易關係：{trade_label}（緊張指數 {self.us_china_trade_tension:.1f}）\n"
            f"深圳生活成本比率：香港嘅 {self.shenzhen_cost_ratio:.0%}（越低越吸引北上）\n"
            f"估計跨境居住港人：約 {self.cross_border_residents:,} 人\n"
            f"大灣區政策整合進度：{self.greater_bay_policy_score:.0%}\n"
        )

    def to_brief_context(self) -> str:
        """Return a compact 3-line macro summary for agent persona prompts.

        Deliberately omits GBA/Shenzhen bullet points so individual agents
        can discuss different topics based on their personal concerns, rather
        than all repeating the same macro talking points.
        """
        hibor_pct = f"{self.hibor_1m:.2%}"
        ccl = f"{self.ccl_index:.1f}"
        unemployment = f"{self.unemployment_rate:.1%}"
        gdp = f"{self.gdp_growth:.1%}"
        cpi = f"{self.cpi_yoy:.1%}"
        return (
            f"【香港當前經濟背景（一句話）】"
            f"HIBOR {hibor_pct}、失業率 {unemployment}、"
            f"CCL {ccl}、GDP增長 {gdp}、CPI {cpi}。"
        )


def apply_overrides(state: MacroState, overrides: dict[str, Any]) -> MacroState:
    """Return a new MacroState with *overrides* applied (deep-copy dicts)."""
    safe_overrides: dict[str, Any] = {}
    for key, value in overrides.items():
        if isinstance(value, dict):
            safe_overrides[key] = copy.deepcopy(value)
        else:
            safe_overrides[key] = value
    return replace(state, **safe_overrides)
