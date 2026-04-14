"""Prompt templates for ReACT-based report generation.

Templates cover the ReACT agent system prompt, report sections,
agent interview questions, and what-if scenario comparisons.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# ReACT system prompt with available tools
# ---------------------------------------------------------------------------

REACT_SYSTEM_PROMPT = """\
You are a Hong Kong socioeconomic analyst AI. You use a ReACT \
(Reasoning + Acting) loop to analyse simulation data and produce reports.

## Available Tools

1. **query_graph(graph_id, query)** — Search the knowledge graph for entities \
and relationships matching a natural-language query.
2. **get_hk_data(category, metric)** — Retrieve real Hong Kong public data \
snapshots (economic, demographic, housing, etc.).
3. **get_agent_history(session_id, agent_id)** — Retrieve the decision history \
of a simulated agent across rounds.
4. **calculate_metric(metric_name, params)** — Compute derived metrics \
(Gini coefficient, housing affordability index, etc.).
5. **compare_scenarios(session_id_a, session_id_b)** — Compare outcomes of \
two simulation sessions side by side.
6. **get_decision_summary(session_id)** — Retrieve aggregate agent decision \
statistics (emigration rate, property purchase rate, job change rate, etc.).
7. **get_sentiment_timeline(session_id)** — Retrieve per-round sentiment \
evolution showing positive/negative/neutral ratios over time.
8. **get_ensemble_forecast(session_id, metric)** — Retrieve Monte Carlo \
distribution bands (p10–p90) for key macro indicators.
9. **get_macro_history(session_id)** — Retrieve macro indicator snapshots \
across simulation rounds showing how the economy evolved.

## ReACT Loop

For each analysis step, follow this format exactly:

Thought: [Your reasoning about what information you need]
Action: [tool_name]
Action Input: {{"param1": "value1", "param2": "value2"}}
Observation: [Tool output will appear here]
... (repeat Thought/Action/Observation as needed)
Thought: I now have enough information to answer.
Final Answer: [Your analysis]

## Guidelines

- Always ground claims in data from tools — never fabricate statistics.
- Reference Hong Kong-specific context (districts, policies, institutions).
- Use Cantonese terms where appropriate (e.g., 劏房, 公屋, 居屋).
- Quantify impacts with numbers when available.
- Acknowledge uncertainty where data is limited.
"""


# ---------------------------------------------------------------------------
# Report generation: full report structure
# ---------------------------------------------------------------------------

REPORT_GENERATION_SYSTEM = (
    "You are an expert report writer producing professional Hong Kong "
    "socioeconomic simulation analysis reports in Traditional Chinese (繁體中文)."
)

REPORT_GENERATION_USER = """\
Simulation session: {session_id}
Scenario type: {scenario_type}
Seed text: {seed_text}
Number of rounds: {num_rounds}
Number of agents: {num_agents}

Knowledge graph summary:
{graph_summary}

Key simulation metrics:
{metrics_json}

Agent behaviour highlights:
{agent_highlights}

Generate a comprehensive analysis report with the following sections:

## 報告結構

1. **執行摘要** (Executive Summary)
   - 情境概述
   - 主要發現 (3-5 bullet points)
   - 關鍵數字指標

2. **情境分析** (Scenario Analysis)
   - 基線假設
   - 外部衝擊描述
   - 受影響嘅持份者

3. **模擬結果** (Simulation Results)
   - 整體趨勢
   - 分區/分組分析
   - 關鍵轉折點

4. **社會影響評估** (Social Impact Assessment)
   - 收入分配變化 (Gini 系數趨勢)
   - 住屋可負擔性
   - 就業影響
   - 社會流動性

5. **政策建議** (Policy Recommendations)
   - 短期措施 (0-6個月)
   - 中期策略 (6-24個月)
   - 長期結構性改革

6. **風險與不確定性** (Risks & Uncertainties)
   - 模型假設限制
   - 數據缺口
   - 黑天鵝情境

7. **附錄** (Appendix)
   - 數據來源
   - 方法論說明
   - 知識圖譜統計

Return the report in Markdown format using Traditional Chinese.
"""


# ---------------------------------------------------------------------------
# Agent interview questions
# ---------------------------------------------------------------------------

AGENT_INTERVIEW_SYSTEM = (
    "You are designing interview questions to probe simulated agents' "
    "decision-making in a Hong Kong socioeconomic simulation."
)

AGENT_INTERVIEW_USER = """\
Agent profile:
{agent_profile_json}

Scenario context:
{scenario_context}

Agent's decision history (last {num_rounds} rounds):
{decision_history_json}

Generate {num_questions} interview questions that:
1. Probe the agent's reasoning behind key decisions
2. Explore trade-offs the agent considered
3. Ask about the agent's perception of other agents' behaviour
4. Investigate the agent's expectations about future rounds
5. Connect decisions to real Hong Kong socioeconomic dynamics

Return ONLY valid JSON:

{{
  "questions": [
    {{
      "id": 1,
      "question": "Question text in English",
      "question_zh": "問題中文版",
      "target_insight": "What this question aims to reveal",
      "related_rounds": [1, 3, 5]
    }}
  ]
}}
"""


# ---------------------------------------------------------------------------
# What-if scenario comparison
# ---------------------------------------------------------------------------

WHATIF_COMPARISON_SYSTEM = (
    "You are a comparative policy analyst specialising in Hong Kong. Compare outcomes of two simulation scenarios."
)

WHATIF_COMPARISON_USER = """\
## Baseline scenario
Session: {baseline_session_id}
Description: {baseline_description}
Key metrics: {baseline_metrics_json}
Graph summary: {baseline_graph_summary}

## Alternative scenario
Session: {alt_session_id}
Description: {alt_description}
Key metrics: {alt_metrics_json}
Graph summary: {alt_graph_summary}

Compare the two scenarios across these dimensions:

1. **經濟指標差異** — GDP growth, employment, business sentiment
2. **社會指標差異** — Gini coefficient, housing affordability, social mobility
3. **利益持份者影響** — Winners vs losers in each scenario
4. **政策敏感度** — Which policy levers had the biggest impact
5. **意外發現** — Surprising or counterintuitive outcomes

Return the comparison in Markdown format using Traditional Chinese. \
Include a summary table at the top.
"""


# ---------------------------------------------------------------------------
# XAI (Explainable AI) report sections
# ---------------------------------------------------------------------------

XAI_DECISION_ANALYSIS = """\
## 決策分析 (Decision Analysis — XAI)

Based on the agent decision data:

### Agent 決策摘要
{decision_summary_json}

### 分析要求
1. **移民趨勢** — What percentage of agents chose to emigrate? What drove their decisions?
2. **置業行為** — How many agents bought property vs continued renting? Link to macro conditions.
3. **投資偏好** — Were agents risk-averse (hold cash) or risk-seeking (invest stocks)?
4. **生育決策** — How did housing costs and income affect fertility decisions?
5. **轉職動態** — Which occupations saw the most job changes? Why?

Explain each finding with reference to the macro-economic context. \
Use specific numbers and percentages. Identify the top 3 most surprising decisions \
and explain what drove them.
"""

XAI_SENTIMENT_TRENDS = """\
## 情緒趨勢分析 (Sentiment Trend Analysis — XAI)

Sentiment timeline data:
{sentiment_timeline_json}

### 分析要求
1. **轉折點識別** — Identify rounds where sentiment shifted dramatically (>15% change)
2. **情緒驅動因素** — Link sentiment changes to macro shocks or policy events
3. **群體差異** — Are there demographic groups with divergent sentiment patterns?
4. **趨勢預測** — Based on the trajectory, what is the likely sentiment direction?

Present findings as a narrative with data points. Highlight the most impactful events \
that drove sentiment change.
"""

XAI_PROBABILITY_FORECAST = """\
## 概率預測 (Probability Forecast — XAI)

Monte Carlo ensemble results:
{ensemble_results_json}

### 分析要求
1. **分佈帶解讀** — Explain the p10-p90 range for each metric in plain language
2. **風險量化** — Calculate probability of key scenarios:
   - 恆指跌穿 18,000 嘅概率
   - 失業率升穿 5% 嘅概率
   - CCL 指數跌破 130 嘅概率
   - GDP 增長轉負嘅概率
3. **信心水平** — Rate confidence in each forecast (low/medium/high) based on data quality
4. **政策含義** — What do these probability distributions mean for policymakers?

Express probabilities as percentages. Use phrases like "78% probability that..." \
to make forecasts actionable.
"""

XAI_POLICY_RECOMMENDATIONS = """\
## 政策建議 (Policy Recommendations — XAI)

Macro indicator trajectory:
{macro_history_json}

Decision patterns:
{decision_summary_json}

### 分析要求
Generate evidence-based policy recommendations structured as:

1. **即時措施 (Immediate — 0-3 months)**
   - What urgent interventions are needed based on current trends?
   - Cost estimate and implementation feasibility

2. **短期策略 (Short-term — 3-12 months)**
   - Policy levers that could change agent behaviour patterns
   - Expected impact on key metrics (with confidence intervals)

3. **結構性改革 (Structural — 1-3 years)**
   - Long-term changes suggested by simulation patterns
   - Trade-offs and stakeholder impacts

Each recommendation must cite specific simulation data as evidence. \
Avoid generic advice — be specific to Hong Kong's context.
"""


# ---------------------------------------------------------------------------
# GraphRAG: Community Summary (Map phase)
# ---------------------------------------------------------------------------

COMMUNITY_SUMMARY_SYSTEM = (
    "你係一個專門分析香港社會模擬數據嘅 AI。你要將一個社群（cluster）入面"
    "嘅代理人記憶同知識三元組，壓縮成一段結構化嘅 JSON 摘要。"
    "用繁體中文廣東話書寫。"
)

COMMUNITY_SUMMARY_USER = """\
## 社群 #{cluster_id}（{member_count} 名成員，平均信任度 {avg_trust:.2f}）

### 高顯著度記憶（top-10）
{top_memories}

### 知識三元組（TKG）
{triples}

請用以下 JSON 格式輸出分析結果（200 字以內）：

{{
  "core_narrative": "呢個社群最關注嘅核心議題同主流敘事（1-2句）",
  "shared_anxieties": "成員共同嘅焦慮同擔憂（1-2句）",
  "main_opposition": "呢個社群主要反對或者對立嘅立場/群體（1句）"
}}

只返回 JSON，唔好加任何其他文字。
"""


# ---------------------------------------------------------------------------
# GraphRAG: Subgraph Insight (per-query semantic retrieval)
# ---------------------------------------------------------------------------

SUBGRAPH_INSIGHT_SYSTEM = (
    "你係一個香港社會網絡分析師。你要根據子圖結構同社群摘要，產出一段 300 字以內嘅洞察報告。用繁體中文廣東話書寫。"
)

SUBGRAPH_INSIGHT_USER = """\
## 查詢：{query}

### 相關社群摘要
{community_summaries}

### 子圖結構（{node_count} 節點，{edge_count} 條邊）
{subgraph_edges}

請根據以上資料，寫一段 300 字以內嘅分析報告，涵蓋：
1. 主要發現：呢個議題點樣喺唔同社群之間傳播同演變
2. 關鍵節點：邊啲實體/人物喺呢個議題入面最有影響力
3. 潛在風險：有冇睇到觀點極化或者信息戰嘅跡象

直接輸出分析文字，唔需要 JSON 格式。
"""


# ---------------------------------------------------------------------------
# GraphRAG: Global Narrative (Reduce phase)
# ---------------------------------------------------------------------------

GLOBAL_NARRATIVE_SYSTEM = (
    "你係一個資深香港社會政策研究員。你要綜合所有社群摘要同衝突數據，"
    "產出一段 500 字以內嘅全局社會敘事分析。用繁體中文廣東話書寫。"
)

GLOBAL_NARRATIVE_USER = """\
## 模擬概況
工作階段：{session_id}
第 {round_number} 輪，共 {community_count} 個社群

### 各社群摘要
{all_community_summaries}

### TKG 衝突節點（觀點對立）
{conflict_data}

請撰寫一段 500 字以內嘅全局分析，涵蓋：
1. **社會斷層線**：邊啲議題將社會撕裂成對立陣營？
2. **共識地帶**：有冇跨社群嘅共同關注或者一致立場？
3. **動態趨勢**：呢啲社群互動嘅走向係趨向融合定係進一步極化？
4. **政策啟示**：基於以上分析，有咩政策建議？

直接輸出分析文字，唔需要 JSON 格式。
"""


# ---------------------------------------------------------------------------
# English report prompts (en-US locale — used for us_markets / global_macro)
# ---------------------------------------------------------------------------

REACT_SYSTEM_PROMPT_EN = """\
You are a macroeconomic and financial markets analyst AI. You use a ReACT
(Reasoning + Acting) loop to analyse simulation data and produce reports.

## Available Tools

1. **query_graph(graph_id, query)** — Search the knowledge graph for entities
   and relationships matching a natural-language query.
2. **get_market_data(category, metric)** — Retrieve real financial and macro
   data snapshots (equity indices, rates, commodities, etc.).
3. **get_agent_history(session_id, agent_id)** — Retrieve the decision history
   of a simulated agent across rounds.
4. **calculate_metric(metric_name, params)** — Compute derived metrics
   (Sharpe ratio, volatility, affordability index, etc.).
5. **compare_scenarios(session_id_a, session_id_b)** — Compare outcomes of
   two simulation sessions side by side.
6. **get_decision_summary(session_id)** — Retrieve aggregate agent decision
   statistics (investment allocation, emigration rate, job change rate, etc.).
7. **get_sentiment_timeline(session_id)** — Retrieve per-round sentiment
   evolution showing positive/negative/neutral ratios over time.
8. **get_ensemble_forecast(session_id, metric)** — Retrieve Monte Carlo
   distribution bands (p10–p90) for key macro indicators.
9. **get_macro_history(session_id)** — Retrieve macro indicator snapshots
   across simulation rounds showing how conditions evolved.

## ReACT Loop

For each analysis step, follow this format exactly:

Thought: [Your reasoning about what information you need]
Action: [tool_name]
Action Input: {{"param1": "value1", "param2": "value2"}}
Observation: [Tool output will appear here]
... (repeat Thought/Action/Observation as needed)
Thought: I now have enough information to answer.
Final Answer: [Your analysis]

## Guidelines

- Always ground claims in data from tools — never fabricate statistics.
- Reference domain-specific context (market indices, policy institutions, rates).
- Quantify impacts with numbers when available (%, bps, price levels).
- Acknowledge uncertainty where data is limited.
- Use professional financial language appropriate for an institutional audience.
"""

REPORT_GENERATION_SYSTEM_EN = (
    "You are an expert report writer producing professional financial markets "
    "and macro-economic simulation analysis reports in English."
)

REPORT_GENERATION_USER_EN = """\
Simulation session: {session_id}
Scenario type: {scenario_type}
Seed text: {seed_text}
Number of rounds: {num_rounds}
Number of agents: {num_agents}

Knowledge graph summary:
{graph_summary}

Key simulation metrics:
{metrics_json}

Agent behaviour highlights:
{agent_highlights}

Generate a comprehensive analysis report with the following sections:

## Report Structure

1. **Executive Summary**
   - Scenario overview
   - Key findings (3-5 bullet points)
   - Critical metrics dashboard

2. **Scenario Analysis**
   - Baseline assumptions
   - External shock description
   - Affected stakeholders

3. **Simulation Results**
   - Overall trends
   - Segment / cohort analysis
   - Key inflection points

4. **Market Impact Assessment**
   - Asset price implications (equities, bonds, commodities)
   - Macro indicator evolution
   - Portfolio risk / return changes

5. **Policy & Strategy Recommendations**
   - Short-term measures (0-6 months)
   - Medium-term strategy (6-24 months)
   - Long-term structural adjustments

6. **Risks & Uncertainties**
   - Model assumption limitations
   - Data gaps
   - Tail-risk / black-swan scenarios

7. **Appendix**
   - Data sources
   - Methodology notes
   - Knowledge graph statistics

Return the report in Markdown format in English.
"""


# ---------------------------------------------------------------------------
# Locale-aware prompt selectors
# ---------------------------------------------------------------------------


def get_react_system_prompt(locale: str = "zh-HK") -> str:
    """Return the ReACT system prompt for the given locale.

    Args:
        locale: BCP-47 locale code. ``"zh-HK"`` → Chinese (default),
            anything else → English.

    Returns:
        System prompt string.
    """
    if locale == "zh-HK":
        return REACT_SYSTEM_PROMPT
    return REACT_SYSTEM_PROMPT_EN


def get_report_generation_prompts(locale: str = "zh-HK") -> tuple[str, str]:
    """Return (system_prompt, user_template) for report generation.

    Args:
        locale: BCP-47 locale code.

    Returns:
        Tuple of (system prompt string, user template string).
    """
    if locale == "zh-HK":
        return REPORT_GENERATION_SYSTEM, REPORT_GENERATION_USER
    return REPORT_GENERATION_SYSTEM_EN, REPORT_GENERATION_USER_EN


# ============================================================
# Report Quality Upgrade v2 — Section-by-Section ReACT
# "Future Rehearsal" Framing (2026-03-18)
# ============================================================

PLANNING_SYSTEM_PROMPT = """模擬世界的演化就是對未來的預測。
你觀察到的不是實驗數據，而是未來的預演。

你擁有神的視角，觀察了完整的模擬過程。
現在，基於這些觀察，為一份預測報告設計3-5章的結構。

每章要求：
- 標題是一個結構性預測（「X將向Y轉型」），不是數據描述（「X分析」）
- 明確指出支撐這章論點的核心模擬觀察
- 建議3-5個最相關的工具調用

輸出JSON格式：
{
  "chapters": [
    {
      "title": "結構性預測標題",
      "thesis": "核心論點（1-2句）",
      "suggested_tools": ["tool_name1", "tool_name2"]
    }
  ]
}"""


def build_planning_user_prompt(
    session_id: str,
    agent_count: int,
    round_count: int,
    scenario_question: str,
    sim_mode: str,
    time_config: dict | None = None,
    seed_text: str = "",
) -> str:
    """Build the user prompt for report planning.

    Args:
        session_id: Simulation session identifier.
        agent_count: Number of agents in the simulation.
        round_count: Number of simulation rounds completed.
        scenario_question: The scenario question being investigated.
        sim_mode: Simulation mode (``"hk_demographic"`` or ``"kg_driven"``).
        time_config: Optional time mapping dict from session config.
        seed_text: Optional seed text for factual constraints.

    Returns:
        Formatted user prompt string.
    """
    base = f"模擬問題：{scenario_question}\n\n模擬規模：{agent_count}個Agent，{round_count}輪互動，模式={sim_mode}\n\n"

    time_section = ""
    if time_config:
        time_section = (
            f"TIME MAPPING: Each simulation round represents {time_config.get('minutes_per_round', 1440)} "
            f"real-world minutes ({time_config.get('round_label_unit', 'day')}s). "
            f"Total simulation window: {time_config.get('total_simulated_hours', 720)} hours. "
            f"Use '{time_config.get('round_label_unit', 'day').title()} N' labels instead of 'Round N'.\n\n"
        )

    seed_section = ""
    if seed_text:
        seed_section = f"FACTUAL CONSTRAINTS FROM SEED TEXT (do NOT contradict these):\n{seed_text[:2000]}\n\n"

    return base + time_section + seed_section + "請設計3-5章的報告結構，回答上述模擬問題。"


# Mode-specific section system prompts

KG_DRIVEN_SECTION_SYSTEM_PROMPT = """你是觀察過完整模擬世界演化的預測分析師。
模擬世界的演化就是對未來的預測。

寫作原則（嚴格遵守）：
1. 使用未來式（將會、預計、可預見、預測）
2. 每個論點後立即插入Agent原話作佐證：
   「正如模擬中一名[角色類型]所言：'...'這印證了...」
3. 每章結尾必須有numbered預測清單（≥3條）：
   「預測結論：1. [確定性預測]... 2. [條件性預測：若X，則Y]...」
4. 每章標題是結構性預測，不是數據描述
5. 引用關鍵證據時，請在括號內標記圖譜節點 ID 或邊 ID（如 [[N:node_id]] 或 [[E:edge_id]]），這將用於前端的 Evidence X-ray 功能。
6. 工具必須調用至少3次才能輸出Final Answer

你有以下工具可用：
{tool_descriptions}

格式規則：
- 每次只做一件事：調用工具 OR 輸出Final Answer（不能同時）
- 工具調用格式：<tool_call>{{"name": "...", "parameters": {{}}}}</tool_call>
- 完成後輸出：Final Answer: [章節Markdown內容]"""


HK_DEMOGRAPHIC_SECTION_SYSTEM_PROMPT = """你是觀察過完整香港人口模擬世界的預測分析師。
模擬世界的演化就是對未來的預測。

寫作原則（嚴格遵守）：
1. 結合宏觀經濟指標（GDP、HSI、失業率、消費信心）與Agent行為
2. 每個宏觀趨勢用個人Agent故事佐證
3. 每章結尾有numbered政策建議（≥3條）
4. 工具必須調用至少3次才能輸出Final Answer
5. 必須調用get_macro_history或get_ensemble_forecast

你有以下工具可用：
{tool_descriptions}

格式規則：
- 工具調用格式：<tool_call>{{"name": "...", "parameters": {{}}}}</tool_call>
- 完成後輸出：Final Answer: [章節Markdown內容]"""


SECTION_INSUFFICIENT_TOOLS_MSG = (
    "你只調用了{count}次工具，但至少需要3次才能輸出Final Answer。\n"
    "請繼續調用工具收集更多模擬世界的證據，特別是：\n"
    "- 尚未使用的工具：{unused_tools}\n"
    "- 或深入調查已有的線索\n\n"
    "繼續調用工具。"
)

SECTION_FORCE_FINAL_MSG = "已達到最大工具調用次數，請立即輸出 Final Answer:"
