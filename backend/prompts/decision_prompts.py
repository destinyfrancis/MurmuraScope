"""LLM prompt templates for the Agent Decision Engine.

All prompts are written in Traditional Chinese (繁體中文) to match the
MurmuraScope language convention for agent-facing content.
"""

from __future__ import annotations

from backend.app.models.decision import DecisionType
from backend.app.services.agent_factory import AgentProfile
from backend.app.services.macro_state import MacroState

# ---------------------------------------------------------------------------
# System prompt (shared across all decision types)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """你係一個香港市民決策分析引擎。你嘅任務係根據每個市民嘅個人資料同宏觀經濟環境，\
分析佢哋最有可能作出嘅生活決定。

規則：
1. 用繁體中文思考，但最終輸出必須係有效 JSON
2. 每個市民嘅決定要獨立評估，唔好互相影響
3. confidence 係 0.0 到 1.0 之間嘅小數，代表你對預測嘅信心程度
4. reasoning 應該係簡短（50字以內）嘅廣東話解釋
5. 只能選擇指定嘅 action 值，唔好自創
6. 輸出必須係 JSON array，每個元素對應一個市民

社交傳染效應：
如果某市民有「社交傳染警報」，代表佢信任嘅朋友/同事大量出現困擾行為。
呢個情況下，即使宏觀經濟數據穩定，都應該大幅提高該市民跟隨朋友決定嘅概率。
群體恐慌可以超越理性分析 — 身邊人嘅行為比統計數字更有說服力。"""

# ---------------------------------------------------------------------------
# Decision-type specific instructions
# ---------------------------------------------------------------------------

_DECISION_INSTRUCTIONS: dict[str, str] = {
    DecisionType.BUY_PROPERTY: """決策類型：置業決定
可選 action：["buy", "wait", "rent_more", "sell"]
- buy: 決定購買物業（可以係首置或換樓）
- wait: 觀望市場，暫不入市
- rent_more: 繼續租樓，放棄短期置業計劃
- sell: 出售現有物業（業主適用）

考慮因素：
- HIBOR 及按揭利率水平
- CCL 指數同物業價格走勢
- 收入相對樓價負擔能力（月供不超過收入 50%）
- 首期能力（儲蓄 vs 樓價 × 按揭成數）
- 印花稅政策""",

    DecisionType.EMIGRATE: """決策類型：移民決定
可選 action：["emigrate", "stay", "consider_later"]
- emigrate: 決定移民離港
- stay: 選擇留港
- consider_later: 考慮中，未有定案

考慮因素：
- 年齡（55歲以上移民概率下降）
- 儲蓄是否足夠支持移民（一般需要 20萬 HKD 以上）
- 神經質（neuroticism）高 + 台海風險高 → 移民傾向增加
- 政治環境及生活質素
- 工作前景""",

    DecisionType.CHANGE_JOB: """決策類型：轉工決定
可選 action：["change_job", "stay", "upskill", "retire_early"]
- change_job: 主動轉工或跳槽
- stay: 繼續現時工作
- upskill: 進修提升技能，為轉職準備
- retire_early: 提早退休

考慮因素：
- 年齡（22-60歲工作年齡）
- 外向性（extraversion）高 → 更願意主動轉工
- 失業率走勢（失業率上升 → 轉工風險增加）
- 學歷同收入水平""",

    DecisionType.INVEST: """決策類型：投資決定
可選 action：["invest_stocks", "invest_property", "invest_crypto", "hold_cash", "diversify"]
- invest_stocks: 買入港股或美股
- invest_property: 投資物業（收租或炒賣）
- invest_crypto: 買入加密貨幣
- hold_cash: 保持現金，暫不投資
- diversify: 分散投資多個資產類別

考慮因素：
- 儲蓄超過 10萬 HKD 先考慮投資
- 開放性（openness）高 → 更願意嘗試新投資
- 恒生指數走勢
- CPI 通脹率（高通脹 → 更傾向投資保值）
- 消費者信心指數""",

    DecisionType.HAVE_CHILD: """決策類型：生育決定
可選 action：["have_child", "delay", "no_child"]
- have_child: 決定生育
- delay: 暫時延遲生育計劃
- no_child: 決定不生育

考慮因素：
- 年齡（25-45歲生育年齡段）
- 婚姻狀況（已婚先考慮）
- 月收入超過 15,000 HKD
- 生活成本（CPI、樓價）
- 消費者信心""",

    DecisionType.ADJUST_SPENDING: """決策類型：消費調整決定
可選 action：["cut_spending", "maintain", "increase_savings", "spend_more"]
- cut_spending: 削減非必要開支
- maintain: 維持現有消費水平
- increase_savings: 增加儲蓄比率
- spend_more: 增加消費（樂觀情緒）

考慮因素：
- CPI 通脹率
- 消費者信心指數
- 個人收入同儲蓄狀況
- 失業率環境""",

    DecisionType.EMPLOYMENT_CHANGE: """決策類型：就業狀態改變
可選 action：["quit", "strike", "lie_flat", "seek_employment", "maintain"]
- quit: 辭職離開現時工作（主動選擇）
- strike: 罷工或集體行動（政治傾向高 + 信心低）
- lie_flat: 躺平，主動減少工作量（年輕一代）
- seek_employment: 積極搵工（現時失業）
- maintain: 維持現有就業狀態

考慮因素：
- 失業率走勢（低失業率 → 敢辭職）
- 政治立場（民主派傾向罷工）
- 消費者信心（低信心 → 罷工可能性高）
- 開放性同責任感（低開放性 + 低責任感 → 躺平）
- 年齡（22-35歲較易躺平）
- 儲蓄是否足夠支撐辭職後生活""",

    DecisionType.RELOCATE: """決策類型：區內遷居決定
可選 action：["relocate_nt", "relocate_kln", "relocate_hk_island", "relocate_gba", "stay"]
- relocate_nt: 遷往新界（元朗/屯門/沙田/大埔/北區等）
- relocate_kln: 遷往九龍（深水埗/觀塘/旺角等）
- relocate_hk_island: 遷往港島（灣仔/東區/南區等）
- relocate_gba: 遷往大灣區（深圳/廣州/東莞等跨境）
- stay: 留在現居住地區

考慮因素：
- 租金壓力（地區呎價 / 月收入比例）
- 子女教育需求（已婚、30-50歲）
- 仕紳化壓力（低收入 + 高呎價地區）
- 住屋類型（公屋住戶受限制）
- 工作地點距離""",
}

# ---------------------------------------------------------------------------
# Few-shot examples per decision type
# ---------------------------------------------------------------------------

_FEW_SHOT_EXAMPLES: dict[str, str] = {
    DecisionType.BUY_PROPERTY: """示例輸出（不要照抄，只係格式參考）：
[
  {"agent_id": 42, "action": "wait", "reasoning": "月供佔收入 65%，壓力測試唔過，等HIBOR跌先", "confidence": 0.82},
  {"agent_id": 67, "action": "buy", "reasoning": "儲夠首期，趁CCL回落入市，長線自住", "confidence": 0.71}
]""",

    DecisionType.EMIGRATE: """示例輸出：
[
  {"agent_id": 12, "action": "stay", "reasoning": "工作穩定，家庭係香港，冇理由走", "confidence": 0.88},
  {"agent_id": 34, "action": "consider_later", "reasoning": "有移民念頭但儲蓄唔夠，再儲多兩年", "confidence": 0.65}
]""",

    DecisionType.CHANGE_JOB: """示例輸出：
[
  {"agent_id": 5, "action": "upskill", "reasoning": "失業率上升，先增值自己再轉工較安全", "confidence": 0.74},
  {"agent_id": 18, "action": "change_job", "reasoning": "外向性高，主動搵新機會，現職無前途", "confidence": 0.79}
]""",

    DecisionType.INVEST: """示例輸出：
[
  {"agent_id": 99, "action": "hold_cash", "reasoning": "市場波動大，保留現金等待入市時機", "confidence": 0.80},
  {"agent_id": 103, "action": "invest_stocks", "reasoning": "恒指低位，定期定額買ETF長線增值", "confidence": 0.72}
]""",

    DecisionType.HAVE_CHILD: """示例輸出：
[
  {"agent_id": 55, "action": "delay", "reasoning": "樓價貴，育兒開支大，等生活穩定先", "confidence": 0.85},
  {"agent_id": 61, "action": "have_child", "reasoning": "已婚、收入穩定，時機成熟", "confidence": 0.78}
]""",

    DecisionType.ADJUST_SPENDING: """示例輸出：
[
  {"agent_id": 7, "action": "cut_spending", "reasoning": "通脹高，削減娛樂開支，優先儲蓄", "confidence": 0.83},
  {"agent_id": 22, "action": "maintain", "reasoning": "收入穩定，消費習慣唔變", "confidence": 0.70}
]""",

    DecisionType.EMPLOYMENT_CHANGE: """示例輸出：
[
  {"agent_id": 31, "action": "quit", "reasoning": "神經質高，儲蓄夠三年，趁失業率低辭職休息", "confidence": 0.75},
  {"agent_id": 48, "action": "lie_flat", "reasoning": "28歲，對未來冇期望，決定躺平唔拚搏", "confidence": 0.68},
  {"agent_id": 77, "action": "seek_employment", "reasoning": "失業中，積極搵工，需要收入支持家庭", "confidence": 0.85}
]""",

    DecisionType.RELOCATE: """示例輸出：
[
  {"agent_id": 14, "action": "relocate_nt", "reasoning": "港島租金太貴，決定搬去沙田，減輕租金壓力", "confidence": 0.79},
  {"agent_id": 56, "action": "stay", "reasoning": "住慣呢區，搬遷成本高，唔值得", "confidence": 0.82},
  {"agent_id": 88, "action": "relocate_gba", "reasoning": "大灣區樓價低，跨境生活成本划算，考慮搬去深圳", "confidence": 0.61}
]""",
}


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def build_deliberation_prompt(
    agents_batch: list[AgentProfile],
    macro_state: MacroState,
    decision_type: str,
    contagion_context: str | None = None,
) -> list[dict[str, str]]:
    """Build the message list for a batch LLM deliberation call.

    Args:
        agents_batch: List of eligible agent profiles (max 10 recommended).
        macro_state: Current macro-economic state.
        decision_type: One of ``DecisionType`` values.
        contagion_context: Optional social contagion prompt section. When
            provided, injected between the agent profiles and the output
            instruction to enable herd/panic behaviour.

    Returns:
        OpenAI-style message list ready for ``LLMClient.chat_json()``.
    """
    macro_context = macro_state.to_prompt_context()
    instructions = _DECISION_INSTRUCTIONS.get(decision_type, "")
    few_shot = _FEW_SHOT_EXAMPLES.get(decision_type, "")

    # Build agent profile section
    agent_lines: list[str] = []
    for p in agents_batch:
        line = (
            f"agent_id={p.id} | 年齡={p.age} | 性別={p.sex} | 地區={p.district} | "
            f"職業={p.occupation} | 收入HKD={p.monthly_income:,}/月 | "
            f"儲蓄HKD={p.savings:,} | 學歷={p.education_level} | "
            f"婚況={p.marital_status} | 住屋={p.housing_type} | "
            f"OCEAN=[O={p.openness:.2f} C={p.conscientiousness:.2f} "
            f"E={p.extraversion:.2f} A={p.agreeableness:.2f} N={p.neuroticism:.2f}]"
        )
        agent_lines.append(line)

    agents_section = "\n".join(agent_lines)

    # Build contagion section (injected between profiles and output instruction)
    contagion_section = ""
    if contagion_context:
        contagion_section = f"""

---
{contagion_context}
"""

    user_content = f"""{macro_context}

---
{instructions}

---
以下係需要分析嘅市民資料（共 {len(agents_batch)} 人）：
{agents_section}
{contagion_section}
---
{few_shot}

請根據每個市民嘅資料同宏觀環境，輸出 JSON array，\
包含 {len(agents_batch)} 個決定（每個市民一個）。\
必須包含以下欄位：agent_id, action, reasoning, confidence。"""

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


# ---------------------------------------------------------------------------
# English (en-US) prompt variants for non-HK domain packs
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_EN = """You are an agent decision analysis engine. Your task is to analyse
each agent's personal profile and the macro-economic environment to determine the most
likely life decisions they would make.

Rules:
1. Think step-by-step, but output must be valid JSON
2. Each agent's decision must be evaluated independently
3. confidence is a float between 0.0 and 1.0 representing prediction certainty
4. reasoning should be a brief (under 60 chars) English explanation
5. Only select from the specified action values — do not invent new ones
6. Output must be a JSON array with one element per agent

Social contagion:
If an agent has a 'social contagion alert', their trusted contacts are exhibiting
high-distress behaviour. Even if macro data looks stable, significantly increase the
probability that this agent follows their peers. Herd panic overrides rational analysis —
what people around you do is more persuasive than statistics."""


_DECISION_INSTRUCTIONS_EN: dict[str, str] = {
    DecisionType.BUY_PROPERTY: """Decision type: Property Purchase
Available actions: ["buy", "wait", "rent_more", "sell"]
- buy: Decide to purchase a property
- wait: Watch the market, hold off for now
- rent_more: Continue renting, defer purchase plans
- sell: Sell existing property (owners only)

Factors to consider:
- Mortgage interest rates and credit conditions
- Property price trends and affordability index
- Income vs monthly mortgage payment (keep under 43% DTI)
- Down payment availability (savings vs price × LTV)
- Tax implications""",

    DecisionType.EMIGRATE: """Decision type: Emigration Decision
Available actions: ["emigrate", "stay", "consider_later"]
- emigrate: Decide to emigrate
- stay: Choose to remain
- consider_later: Still considering, no decision yet

Factors to consider:
- Age (probability decreases sharply above 55)
- Savings sufficient to support relocation ($20K+ USD typically)
- High neuroticism + geopolitical risk → increased emigration tendency
- Career prospects and quality of life abroad
- Family ties""",

    DecisionType.CHANGE_JOB: """Decision type: Job Change Decision
Available actions: ["change_job", "stay", "upskill", "retire_early"]
- change_job: Actively switch jobs or get promoted elsewhere
- stay: Remain in current job
- upskill: Enrol in training to prepare for a career change
- retire_early: Choose early retirement

Factors to consider:
- Age range 18-65
- High extraversion → more likely to proactively job-hunt
- Unemployment rate trends (rising rate = higher risk)
- Education level and current compensation""",

    DecisionType.INVEST: """Decision type: Investment Decision
Available actions: ["invest_stocks", "invest_property", "invest_crypto", "hold_cash", "diversify"]
- invest_stocks: Buy equities (S&P 500, ETFs, individual stocks)
- invest_property: Buy investment property
- invest_crypto: Buy cryptocurrency
- hold_cash: Retain cash, sit out the market
- diversify: Spread across multiple asset classes

Factors to consider:
- Savings above $10,000 before considering investment
- High openness → more willing to try new investments
- Equity index trends (SPX, NDX)
- CPI inflation rate (high inflation → seek inflation hedges)
- Consumer confidence index""",

    DecisionType.HAVE_CHILD: """Decision type: Childbearing Decision
Available actions: ["have_child", "delay", "no_child"]
- have_child: Decide to have a child
- delay: Temporarily postpone childbearing plans
- no_child: Decide not to have children

Factors to consider:
- Age range 20-45
- Marital status (married considered first)
- Monthly income above $3,500 USD
- Cost of living (CPI, housing costs)
- Consumer confidence""",

    DecisionType.ADJUST_SPENDING: """Decision type: Spending Adjustment
Available actions: ["cut_spending", "maintain", "increase_savings", "spend_more"]
- cut_spending: Reduce non-essential expenditure
- maintain: Keep current spending level unchanged
- increase_savings: Boost savings rate
- spend_more: Increase spending (optimism-driven)

Factors to consider:
- CPI inflation rate
- Consumer confidence index
- Personal income and savings level
- Unemployment environment""",

    DecisionType.EMPLOYMENT_CHANGE: """Decision type: Employment Status Change
Available actions: ["quit", "strike", "lie_flat", "seek_employment", "maintain"]
- quit: Voluntarily leave current job
- strike: Participate in labour action (high political stance + low confidence)
- lie_flat: Reduce work effort dramatically (younger cohort)
- seek_employment: Actively look for work (currently unemployed)
- maintain: Keep current employment status

Factors to consider:
- Unemployment rate (low rate = safe to quit)
- Political stance (progressive leaning → more likely to strike)
- Consumer confidence (low confidence → higher strike probability)
- Openness and conscientiousness (low both → lie flat)
- Age 18-35 more susceptible to lying flat
- Savings sufficient to sustain quitting""",

    DecisionType.RELOCATE: """Decision type: Residential Relocation
Available actions: ["relocate_urban", "relocate_suburban", "relocate_rural", "relocate_abroad", "stay"]
- relocate_urban: Move to a major city centre
- relocate_suburban: Move to suburban areas for more space
- relocate_rural: Move to rural areas for lower cost of living
- relocate_abroad: Relocate to another country
- stay: Remain in current location

Factors to consider:
- Rent/price burden (housing cost vs income)
- School district needs (married, age 28-50)
- Gentrification pressure (low income + high-cost area)
- Housing type (renters more mobile than owners)
- Commute distance to work""",
}

_FEW_SHOT_EXAMPLES_EN: dict[str, str] = {
    DecisionType.BUY_PROPERTY: """Example output (format reference only — do not copy):
[
  {"agent_id": 42, "action": "wait", "reasoning": "Mortgage payment 65% of income, fails stress test", "confidence": 0.82},
  {"agent_id": 67, "action": "buy", "reasoning": "Saved enough for down payment, prices dipping", "confidence": 0.71}
]""",

    DecisionType.EMIGRATE: """Example output:
[
  {"agent_id": 12, "action": "stay", "reasoning": "Stable career and family here, no reason to leave", "confidence": 0.88},
  {"agent_id": 34, "action": "consider_later", "reasoning": "Wants to emigrate but savings insufficient", "confidence": 0.65}
]""",

    DecisionType.CHANGE_JOB: """Example output:
[
  {"agent_id": 5, "action": "upskill", "reasoning": "Unemployment rising, safer to reskill first", "confidence": 0.74},
  {"agent_id": 18, "action": "change_job", "reasoning": "High extraversion, proactively hunting better role", "confidence": 0.79}
]""",

    DecisionType.INVEST: """Example output:
[
  {"agent_id": 99, "action": "hold_cash", "reasoning": "High volatility, waiting for clearer entry", "confidence": 0.80},
  {"agent_id": 103, "action": "invest_stocks", "reasoning": "SPX dip, dollar-cost averaging into ETF", "confidence": 0.72}
]""",

    DecisionType.HAVE_CHILD: """Example output:
[
  {"agent_id": 55, "action": "delay", "reasoning": "Housing unaffordable, childcare costs too high", "confidence": 0.85},
  {"agent_id": 61, "action": "have_child", "reasoning": "Married, income stable, timing feels right", "confidence": 0.78}
]""",

    DecisionType.ADJUST_SPENDING: """Example output:
[
  {"agent_id": 7, "action": "cut_spending", "reasoning": "Inflation high, cutting entertainment to save", "confidence": 0.83},
  {"agent_id": 22, "action": "maintain", "reasoning": "Income stable, no reason to change habits", "confidence": 0.70}
]""",

    DecisionType.EMPLOYMENT_CHANGE: """Example output:
[
  {"agent_id": 31, "action": "quit", "reasoning": "High neuroticism, savings cover 3 years, low unemployment", "confidence": 0.75},
  {"agent_id": 48, "action": "lie_flat", "reasoning": "27 years old, burnt out, stepping back from hustle", "confidence": 0.68},
  {"agent_id": 77, "action": "seek_employment", "reasoning": "Currently unemployed, actively job hunting", "confidence": 0.85}
]""",

    DecisionType.RELOCATE: """Example output:
[
  {"agent_id": 14, "action": "relocate_suburban", "reasoning": "City rent too high, suburban has better value", "confidence": 0.79},
  {"agent_id": 56, "action": "stay", "reasoning": "Comfortable in neighborhood, moving costs not worth it", "confidence": 0.82}
]""",
}


def build_deliberation_prompt_en(
    agents_batch: list[AgentProfile],
    macro_context: str,
    decision_type: str,
    contagion_context: str | None = None,
) -> list[dict[str, str]]:
    """Build English-language deliberation prompt messages.

    Args:
        agents_batch: List of eligible agent profiles (max 10 recommended).
        macro_context: Pre-rendered macro state string.
        decision_type: One of ``DecisionType`` values.
        contagion_context: Optional social contagion prompt section.

    Returns:
        OpenAI-style message list for ``LLMClient.chat_json()``.
    """
    instructions = _DECISION_INSTRUCTIONS_EN.get(decision_type, "")
    few_shot = _FEW_SHOT_EXAMPLES_EN.get(decision_type, "")

    agent_lines: list[str] = []
    for p in agents_batch:
        line = (
            f"agent_id={p.id} | age={p.age} | sex={p.sex} | region={p.district} | "
            f"occupation={p.occupation} | income={p.monthly_income:,}/mo | "
            f"savings={p.savings:,} | education={p.education_level} | "
            f"marital={p.marital_status} | housing={p.housing_type} | "
            f"OCEAN=[O={p.openness:.2f} C={p.conscientiousness:.2f} "
            f"E={p.extraversion:.2f} A={p.agreeableness:.2f} N={p.neuroticism:.2f}]"
        )
        agent_lines.append(line)

    agents_section = "\n".join(agent_lines)

    contagion_section = ""
    if contagion_context:
        contagion_section = f"\n\n---\n{contagion_context}\n"

    user_content = f"""{macro_context}

---
{instructions}

---
Agents to analyse ({len(agents_batch)} total):
{agents_section}
{contagion_section}
---
{few_shot}

Output a JSON array with exactly {len(agents_batch)} decisions (one per agent).
Required fields: agent_id, action, reasoning, confidence."""

    return [
        {"role": "system", "content": SYSTEM_PROMPT_EN},
        {"role": "user", "content": user_content},
    ]


def get_deliberation_prompt(
    agents_batch: list[AgentProfile],
    macro_state: MacroState,
    decision_type: str,
    contagion_context: str | None = None,
    locale: str = "zh-HK",
) -> list[dict[str, str]]:
    """Locale-aware deliberation prompt dispatcher.

    Args:
        agents_batch: List of eligible agents.
        macro_state: Current macro state (must support ``to_prompt_context()``).
        decision_type: One of ``DecisionType`` values.
        contagion_context: Optional social contagion context string.
        locale: BCP-47 locale code.  ``"zh-HK"`` → Chinese prompts (default),
            anything else → English prompts.

    Returns:
        OpenAI-style message list.
    """
    if locale == "zh-HK":
        return build_deliberation_prompt(
            agents_batch=agents_batch,
            macro_state=macro_state,
            decision_type=decision_type,
            contagion_context=contagion_context,
        )
    # English path — pass pre-rendered macro context string
    macro_context = macro_state.to_prompt_context()
    return build_deliberation_prompt_en(
        agents_batch=agents_batch,
        macro_context=macro_context,
        decision_type=decision_type,
        contagion_context=contagion_context,
    )
