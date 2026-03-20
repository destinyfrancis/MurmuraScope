"""Prompt templates for Tier 1 agent reflection synthesis.

Inspired by Generative Agents (Park et al., 2023) reflection mechanism.
Triggered periodically for Tier 1 agents to synthesize abstract insights
from accumulated memories. Generates type='thought' memory nodes.
"""

from __future__ import annotations

REFLECTION_SYSTEM = """\
你係一個模擬角色嘅內省模組。根據呢個角色嘅近期記憶，推導出有洞見嘅高層次想法。
唔好重複記憶嘅表面內容——要提煉出背後嘅規律、信念轉變或深層認識。
每一條想法必須具體到呢個場景，唔好太泛泛而論。用繁體中文廣東話書寫。"""

REFLECTION_USER = """\
你係：{name}（{role}）
當前場景：{scenario_description}

你最近嘅記憶（按重要程度排列）：
{memories_text}

請根據以上記憶，推導出 {n_insights} 條深層洞見或信念轉變。

每條洞見必須：
1. 係基於具體記憶事件嘅推論，唔係泛泛而論
2. 反映你對呢個場景或其他人物嘅新認識
3. 有助於指導你未來嘅決策

返回 JSON：
{{
  "insights": [
    {{
      "thought": "洞見內容（50字以內，用第一人稱「我」）",
      "based_on": "呢個洞見係基於邊條記憶推導出嚟（15字以內）",
      "importance_score": 6-9
    }}
  ]
}}"""
