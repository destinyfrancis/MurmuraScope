"""Prompt templates for seed text analysis (TextProcessor)."""

from __future__ import annotations

ANALYZE_SEED_SYSTEM = """你係一個香港社會分析專家，專長係分析新聞事件、政策文件同社會議題。
你嘅任務係將一段文本分析成結構化數據，用於香港社會模擬引擎。
請務必用繁體中文回答，所有輸出欄位都要符合香港本地語境。"""

ANALYZE_SEED_USER = """請分析以下文本，提取關鍵信息並返回 JSON 格式結果。

文本內容：
{seed_text}

請返回以下 JSON 結構（所有字符串用繁體中文）：
{{
  "language": "zh-HK 或 en 或 mixed",
  "entities": [
    {{"name": "實體名稱", "type": "person|org|location|policy|economic|event", "relevance": 0.0-1.0}}
  ],
  "timeline": [
    {{"date_hint": "時間提示（如「2024年3月」或「近期」）", "event": "事件描述"}}
  ],
  "stakeholders": [
    {{"group": "持份者群體（如「首置買家」「政府」「發展商」）", "impact": "正面|負面|中性", "description": "影響說明"}}
  ],
  "sentiment": "positive|negative|neutral|mixed",
  "key_claims": ["核心論點1", "核心論點2"],
  "suggested_scenario": "property|emigration|fertility|career|education|b2b|macro",
  "suggested_districts": ["建議重點地區，從香港18區選取，可為空列表"],
  "confidence": 0.0-1.0
}}

注意：
- entities 最多 10 個，按相關性降序排列
- timeline 最多 5 個
- stakeholders 最多 6 個，涵蓋最受影響群體
- key_claims 最多 5 個
- suggested_districts 從以下選擇：中西區、灣仔、東區、南區、油尖旺、深水埗、九龍城、黃大仙、觀塘、葵青、荃灣、屯門、元朗、北區、大埔、沙田、西貢、離島"""

SUGGEST_AGENTS_SYSTEM = """你係一個香港人口統計專家，熟悉香港各社會階層同地區分布。
根據事件分析結果，建議最能反映該議題嘅 agent 角色組合。"""

SUGGEST_AGENTS_USER = """根據以下事件分析，建議 agent 角色分布：

事件摘要：{summary}
建議情景：{scenario}
主要持份者：{stakeholders}
重點地區：{districts}

請返回 JSON，包含建議嘅 agent 類型及比例：
{{
  "agent_suggestions": [
    {{
      "agent_type": "角色描述（如「首置買家」「換樓客」「租客」「業主」「投資者」等）",
      "proportion": 0.0-1.0,
      "district_focus": ["重點地區"],
      "rationale": "為什麼這個群體對此議題重要"
    }}
  ],
  "recommended_total": 推薦 agent 總數（100-500 整數）,
  "recommended_rounds": 推薦模擬輪數（20-60 整數）
}}

確保所有 proportion 加起來約等於 1.0。"""
