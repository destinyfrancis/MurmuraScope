"""Macro scenario prompt injection templates for OASIS simulation."""

from __future__ import annotations

from string import Template

# =========================================================================
# Macro State Context — injected into every agent persona
# =========================================================================

MACRO_CONTEXT_TEMPLATE = Template(
    "\n【香港宏觀經濟環境】\n"
    "一個月 HIBOR：${hibor_1m}\n"
    "最優惠利率（P Rate）：${prime_rate}\n"
    "失業率：${unemployment_rate}\n"
    "每月入息中位數：HK$$${median_monthly_income}\n"
    "中原城市領先指數（CCL）：${ccl_index}\n"
    "最貴地區（每呎均價）：${top_districts}\n"
    "按揭成數上限：${mortgage_cap}\n"
    "GDP 增長：${gdp_growth}\n"
    "CPI 按年變幅：${cpi_yoy}\n"
    "恒生指數：${hsi_level}\n"
    "消費者信心指數：${consumer_confidence}\n"
    "淨遷移人數：${net_migration}\n"
    "出生率：${birth_rate}‰\n"
    "政策標記：\n${policy_lines}\n\n"
    "你嘅所有決策同意見都應該考慮以上宏觀環境。\n"
)

# =========================================================================
# Shock Event News Post Templates (for OASIS ManualAction)
# =========================================================================

SHOCK_NEWS_TEMPLATES: dict[str, Template] = {
    "interest_rate_hike": Template(
        "【突發】金管局宣佈跟隨美聯儲加息，"
        "一個月 HIBOR 升至 ${hibor_1m}，"
        "最優惠利率調整至 ${prime_rate}。"
        "供樓人士每月供款預計增加 ${payment_increase_pct}。"
        "業界預料樓市短期內將受壓，"
        "CCL 指數現報 ${ccl_index}。"
        "銀行同業拆息走高，浮息按揭借款人首當其衝。\n"
        "#加息 #香港樓市 #HIBOR #按揭"
    ),
    "property_crash": Template(
        "【樓市急跌】中原城市領先指數跌至 ${ccl_index}，"
        "創${period}新低。多個屋苑錄得蝕讓成交，"
        "銀行收緊估值，部分物業估值跌穿買入價。"
        "恒指同步下跌至 ${hsi_level} 點。"
        "代理行報告指睇樓量急降 ${viewing_drop_pct}，"
        "市場瀰漫觀望氣氛，業主減價 ${discount_pct} 求售。\n"
        "#樓市 #CCL #香港地產 #負資產"
    ),
    "unemployment_spike": Template(
        "【經濟警號】統計處公佈最新失業率升至 ${unemployment_rate}，"
        "為${period}高位。${affected_sectors}等行業受影響最大。"
        "每月入息中位數跌至 HK$$${median_monthly_income}。"
        "勞工處就業中心查詢量急增，"
        "政府表示正研究包括${relief_measures}在內嘅紓困措施。\n"
        "#失業率 #香港經濟 #裁員"
    ),
    "policy_change": Template(
        "【施政報告】政府宣佈多項房屋及經濟政策調整：\n"
        "${policy_details}\n"
        "按揭成數上限調整至 ${mortgage_cap}。"
        "印花稅方面：${stamp_duty_changes}。"
        "業界反應不一——${industry_reaction}。"
        "市民密切關注對樓價同租金嘅影響。\n"
        "#施政報告 #房屋政策 #香港 #印花稅"
    ),
    "market_rally": Template(
        "【港股急升】恒生指數大漲至 ${hsi_level} 點，"
        "單日升幅 ${daily_gain_pct}，成交額破${turnover}億。"
        "北水持續流入，${leading_sectors}領漲。"
        "消費者信心指數回升至 ${consumer_confidence}。"
        "分析師${analyst_view}。\n"
        "#恒指 #港股 #牛市 #北水"
    ),
    "emigration_wave": Template(
        "【人口流失】統計處數據顯示淨遷出人數達 ${net_outflow} 人，"
        "較上年度增加 ${yoy_increase_pct}。"
        "${affected_professions}等專業界別出現人才荒，"
        "部分行業薪酬因供應緊張而上調 ${salary_increase_pct}。"
        "學校收生不足，${school_impact}。"
        "政府加推「高才通」等計劃吸引人才。\n"
        "#移民潮 #人才荒 #香港人口 #高才通"
    ),
}

# =========================================================================
# Scenario Comparison Prompt
# =========================================================================

SCENARIO_COMPARISON_TEMPLATE = Template(
    "【情景比較分析】\n\n"
    "基準情景（${baseline_name}）：\n"
    "${baseline_summary}\n\n"
    "對比情景（${scenario_name}）：\n"
    "${scenario_summary}\n\n"
    "主要差異：\n"
    "${differences}\n\n"
    "請根據以上兩個情景嘅差異，分析對以下方面嘅影響：\n"
    "1. 樓市成交量同樓價走勢\n"
    "2. 租金市場變化\n"
    "3. 市民消費同儲蓄行為\n"
    "4. 置業意欲同按揭需求\n"
    "5. 投資市場情緒\n"
)

# =========================================================================
# Agent Decision Context — injected when agent needs to make a decision
# =========================================================================

AGENT_DECISION_CONTEXT_TEMPLATE = Template(
    "【決策情境】\n"
    "你而家需要就「${decision_topic}」作出決定。\n\n"
    "你嘅財務狀況：\n"
    "- 每月收入：${monthly_income}\n"
    "- 儲蓄：${savings}\n"
    "- 住屋：${housing_type}\n"
    "- 每月支出估算：${monthly_expenses}\n\n"
    "市場環境：\n"
    "- HIBOR：${hibor_1m}\n"
    "- 樓價指數：${ccl_index}\n"
    "- 失業率：${unemployment_rate}\n"
    "- 消費者信心：${consumer_confidence}\n\n"
    "請根據你嘅性格特徵、財務狀況同市場環境，"
    "用廣東話表達你嘅決定同理由。\n"
)

# =========================================================================
# Macro State Formatter — helper to build template variables
# =========================================================================

def format_macro_for_template(
    hibor_1m: float,
    prime_rate: float,
    unemployment_rate: float,
    median_monthly_income: int,
    ccl_index: float,
    avg_sqft_price: dict[str, int],
    mortgage_cap: float,
    gdp_growth: float,
    cpi_yoy: float,
    hsi_level: float,
    consumer_confidence: float,
    net_migration: int,
    birth_rate: float,
    policy_flags: dict[str, object],
) -> dict[str, str]:
    """Convert raw macro values to formatted strings for template substitution."""
    top_3 = sorted(avg_sqft_price.items(), key=lambda kv: kv[1], reverse=True)[:3]
    top_districts = "、".join(f"{d}（${p:,}/呎）" for d, p in top_3)

    policy_lines = "\n".join(
        f"  - {k}: {v}" for k, v in policy_flags.items()
    ) if policy_flags else "  （無特殊政策標記）"

    return {
        "hibor_1m": f"{hibor_1m:.2%}",
        "prime_rate": f"{prime_rate:.2%}",
        "unemployment_rate": f"{unemployment_rate:.1%}",
        "median_monthly_income": f"{median_monthly_income:,}",
        "ccl_index": f"{ccl_index:.1f}",
        "top_districts": top_districts,
        "mortgage_cap": f"{mortgage_cap:.0%}",
        "gdp_growth": f"{gdp_growth:.1%}",
        "cpi_yoy": f"{cpi_yoy:.1%}",
        "hsi_level": f"{hsi_level:,.0f}",
        "consumer_confidence": f"{consumer_confidence:.1f}",
        "net_migration": f"{net_migration:+,}",
        "birth_rate": f"{birth_rate:.1f}",
        "policy_lines": policy_lines,
    }


def build_macro_context_prompt(
    hibor_1m: float,
    prime_rate: float,
    unemployment_rate: float,
    median_monthly_income: int,
    ccl_index: float,
    avg_sqft_price: dict[str, int],
    mortgage_cap: float,
    gdp_growth: float,
    cpi_yoy: float,
    hsi_level: float,
    consumer_confidence: float,
    net_migration: int,
    birth_rate: float,
    policy_flags: dict[str, object],
) -> str:
    """Build a complete macro context prompt string from raw values."""
    variables = format_macro_for_template(
        hibor_1m=hibor_1m,
        prime_rate=prime_rate,
        unemployment_rate=unemployment_rate,
        median_monthly_income=median_monthly_income,
        ccl_index=ccl_index,
        avg_sqft_price=avg_sqft_price,
        mortgage_cap=mortgage_cap,
        gdp_growth=gdp_growth,
        cpi_yoy=cpi_yoy,
        hsi_level=hsi_level,
        consumer_confidence=consumer_confidence,
        net_migration=net_migration,
        birth_rate=birth_rate,
        policy_flags=policy_flags,
    )
    return MACRO_CONTEXT_TEMPLATE.substitute(variables)


def build_scenario_comparison(
    baseline_name: str,
    baseline_summary: str,
    scenario_name: str,
    scenario_summary: str,
    differences: str,
) -> str:
    """Build a scenario comparison prompt for analysis."""
    return SCENARIO_COMPARISON_TEMPLATE.substitute(
        baseline_name=baseline_name,
        baseline_summary=baseline_summary,
        scenario_name=scenario_name,
        scenario_summary=scenario_summary,
        differences=differences,
    )
