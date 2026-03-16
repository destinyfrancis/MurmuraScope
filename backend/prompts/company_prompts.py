"""LLM prompt templates for B2B company persona and decision generation (Phase 5).

All templates are immutable module-level constants.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Company persona template
# ---------------------------------------------------------------------------

COMPANY_PERSONA_TEMPLATE = """你係一間香港{company_type}企業「{company_name}」嘅決策層。

【企業基本資料】
- 行業：{industry_sector}
- 規模：{company_size}（{employee_count} 名員工）
- 所在地：{district}
- 年收入：HKD {annual_revenue_hkd:,}
- 供應鏈位置：{supply_chain_position}
- 對中國大陸市場依賴度：{china_exposure:.0%}
- 出口業務比例：{export_ratio:.0%}

你需要根據當前宏觀經濟環境，評估企業應該採取咩策略性行動。
請優先考慮企業嘅長遠可持續發展、員工福利，以及香港整體經濟穩定性。
"""

# ---------------------------------------------------------------------------
# B2B decision system prompt
# ---------------------------------------------------------------------------

B2B_DECISION_SYSTEM = """你係一個香港企業決策分析引擎。根據以下企業資料同宏觀環境，評估企業應該採取咩行動。

你嘅分析必須：
1. 基於真實香港商業環境（關稅政策、物流成本、中港貿易）
2. 考慮企業規模同資源限制
3. 平衡短期風險同長期機遇
4. 提供具體、可執行嘅建議

請用 JSON 格式回應，符合以下 schema：
{
  "decision_type": "<expand|contract|relocate|hire|layoff|enter_market|exit_market|stockpile>",
  "action": "<具體行動描述，20字以內>",
  "reasoning": "<決策理由，50-100字>",
  "confidence": <0.0-1.0>,
  "impact_employees": <整數，正數=招聘，負數=裁員，0=無變化>,
  "impact_revenue_pct": <小數，正數=增長，負數=下降，如 0.05 代表 +5%>
}
"""

# ---------------------------------------------------------------------------
# Decision prompt builder
# ---------------------------------------------------------------------------

_DECISION_PROMPT_TEMPLATE = """【企業決策分析請求】

{company_section}

{macro_section}

請根據以上資料，分析「{company_name}」在當前環境下最優先應採取嘅企業行動。
特別關注以下因素對企業嘅影響：
- 進口關稅率變化（{import_tariff_rate:.1%}）
- 物流成本指數（{export_logistics_cost:.2f}，1.0 為基準）
- 供應鏈中斷程度（{supply_chain_disruption:.0%}）
- 中國進口需求變化（{china_import_demand:+.1%}）

以 JSON 格式回應。"""


def build_company_decision_prompt(
    company: dict,
    macro_context: str,
    import_tariff_rate: float = 0.0,
    export_logistics_cost: float = 1.0,
    supply_chain_disruption: float = 0.0,
    china_import_demand: float = 0.0,
) -> str:
    """Build a decision prompt for a single company.

    Args:
        company: Dict with company profile fields.
        macro_context: Pre-formatted macro context string (from MacroState.to_prompt_context()).
        import_tariff_rate: Current import tariff rate.
        export_logistics_cost: Current logistics cost index.
        supply_chain_disruption: Current supply chain disruption severity (0-1).
        china_import_demand: Current China import demand change fraction.

    Returns:
        Formatted prompt string ready for LLM submission.
    """
    company_section = COMPANY_PERSONA_TEMPLATE.format(
        company_type=company.get("company_type", "企業"),
        company_name=company.get("company_name", ""),
        industry_sector=_translate_sector(company.get("industry_sector", "")),
        company_size=_translate_size(company.get("company_size", "")),
        employee_count=company.get("employee_count", 0),
        district=company.get("district", ""),
        annual_revenue_hkd=company.get("annual_revenue_hkd", 0),
        supply_chain_position=_translate_position(company.get("supply_chain_position", "")),
        china_exposure=company.get("china_exposure", 0.5),
        export_ratio=company.get("export_ratio", 0.3),
    )

    return _DECISION_PROMPT_TEMPLATE.format(
        company_section=company_section,
        macro_section=macro_context,
        company_name=company.get("company_name", ""),
        import_tariff_rate=import_tariff_rate,
        export_logistics_cost=export_logistics_cost,
        supply_chain_disruption=supply_chain_disruption,
        china_import_demand=china_import_demand,
    )


def build_batch_decision_prompt(
    companies_batch: list[dict],
    macro_context: str,
    import_tariff_rate: float = 0.0,
    export_logistics_cost: float = 1.0,
    supply_chain_disruption: float = 0.0,
    china_import_demand: float = 0.0,
) -> str:
    """Build a batch decision prompt for multiple companies.

    Returns a prompt requesting JSON array of decisions.

    Args:
        companies_batch: List of company profile dicts.
        macro_context: Pre-formatted macro context string.
        import_tariff_rate: Current tariff rate.
        export_logistics_cost: Logistics cost index.
        supply_chain_disruption: Supply chain disruption 0-1.
        china_import_demand: China demand change fraction.

    Returns:
        Formatted prompt string for batch LLM submission.
    """
    company_lines = []
    for i, c in enumerate(companies_batch, 1):
        company_lines.append(
            f"{i}. 【{c.get('company_name', '')}】"
            f" 行業:{_translate_sector(c.get('industry_sector', ''))}"
            f" 規模:{_translate_size(c.get('company_size', ''))}"
            f" 對華依賴:{c.get('china_exposure', 0.5):.0%}"
            f" 出口比例:{c.get('export_ratio', 0.3):.0%}"
            f" 供應鏈:{_translate_position(c.get('supply_chain_position', ''))}"
        )

    companies_text = "\n".join(company_lines)

    return f"""【批量企業決策分析】

{macro_context}

【宏觀貿易因素】
- 進口關稅率：{import_tariff_rate:.1%}
- 物流成本指數：{export_logistics_cost:.2f}（1.0 為基準）
- 供應鏈中斷程度：{supply_chain_disruption:.0%}
- 中國進口需求變化：{china_import_demand:+.1%}

【企業名單】
{companies_text}

請為以上每間企業評估最優先行動，以 JSON 陣列格式回應：
[
  {{
    "company_name": "<公司名>",
    "decision_type": "<expand|contract|relocate|hire|layoff|enter_market|exit_market|stockpile>",
    "action": "<具體行動，20字以內>",
    "reasoning": "<理由，50字以內>",
    "confidence": <0.0-1.0>,
    "impact_employees": <整數>,
    "impact_revenue_pct": <小數>
  }}
]"""


# ---------------------------------------------------------------------------
# Translation helpers
# ---------------------------------------------------------------------------


def _translate_sector(sector: str) -> str:
    """Translate industry sector enum value to Traditional Chinese."""
    _map = {
        "import_export": "進出口貿易",
        "finance": "金融",
        "retail": "零售",
        "logistics": "物流運輸",
        "manufacturing": "製造業",
        "tech": "科技",
        "real_estate": "房地產",
    }
    return _map.get(sector, sector)


def _translate_size(size: str) -> str:
    """Translate company size to Traditional Chinese."""
    _map = {
        "sme": "中小企業",
        "mnc": "跨國企業",
        "startup": "初創企業",
    }
    return _map.get(size, size)


def _translate_position(position: str) -> str:
    """Translate supply chain position to Traditional Chinese."""
    _map = {
        "upstream": "上游（生產/製造）",
        "midstream": "中游（貿易/分銷）",
        "downstream": "下游（零售/消費者）",
    }
    return _map.get(position, position)
