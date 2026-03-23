"""Prompt templates for natural language config generation (ConfigGenerator)."""

from __future__ import annotations

CONFIG_SYSTEM = """你係香港社會模擬引擎嘅配置助手。
根據用戶嘅自然語言描述，生成最合適嘅模擬配置。
你熟悉香港社會各方面：樓市、移民、生育、職場、教育、宏觀經濟。
配置要具體、合理，反映真實嘅香港社會場景。"""

CONFIG_USER = """用戶想模擬以下場景：

{user_query}

{seed_context}

請生成模擬配置。返回以下 JSON：
{{
  "scenario_type": "property|emigration|fertility|career|education|b2b|macro",
  "agent_count": 100-1000 整數,
  "round_count": 20-80 整數,
  "district_focus": ["重點地區列表，從香港18區選取"],
  "suggested_shocks": [
    {{
      "round_number": 第幾輪觸發（整數）,
      "shock_type": "policy_change|economic_shock|social_event|news_release",
      "description": "事件描述（繁體中文）",
      "post_content": "模擬帖子內容（廣東話，50-100字）"
    }}
  ],
  "macro_scenario": "baseline|rate_cut|rate_hike|property_boom|property_crash|emigration_surge",
  "rationale": "配置理由說明（繁體中文，100字以內）",
  "confidence": 0.0-1.0
}}

Few-shot 示例：

用戶輸入："分析取消限購令後樓市反應"
→ scenario_type: "property", agent_count: 400, shocks: [{{round: 3, type: "policy_change", desc: "政府宣布撤銷所有辣招"}}]

用戶輸入："模擬移民潮對樓市影響"
→ scenario_type: "emigration", agent_count: 300, shocks: [{{round: 5, type: "social_event", desc: "英國宣布BNO新政策"}}]

用戶輸入："生育率下跌嘅社會影響"
→ scenario_type: "fertility", agent_count: 200, round_count: 40

注意：
- district_focus 最多 5 個地區
- suggested_shocks 最多 4 個
- agent_count 最小 50，最大 1000
- round_count 最小 20，最大 80"""

_VALID_SCENARIOS = ("property", "emigration", "fertility", "career", "education", "b2b", "macro")
_VALID_SHOCK_TYPES = ("policy_change", "economic_shock", "social_event", "news_release")
_VALID_MACRO_SCENARIOS = (
    "baseline",
    "rate_cut",
    "rate_hike",
    "property_boom",
    "property_crash",
    "emigration_surge",
)
