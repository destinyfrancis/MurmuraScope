"""Prompt templates for agent memory system (AgentMemoryService)."""

from __future__ import annotations

MEMORY_SUMMARIZE_SYSTEM = """你係一個香港社會模擬系統嘅記憶分析模組。
你嘅任務係分析社交媒體帖子，提取對特定 agent 有意義嘅記憶點。
記憶要精簡、具體，反映 agent 嘅觀察、情感反應或信念更新。
所有記憶必須用繁體中文廣東話。"""

MEMORY_SUMMARIZE_USER = """以下係模擬第 {round_number} 輪中，用戶「{username}」在社交媒體上嘅帖子和互動：

{posts_text}

請為呢位用戶提取最多 3 條有意義嘅記憶（唔一定要 3 條，有多少算多少）。

返回 JSON：
{{
  "memories": [
    {{
      "memory_text": "記憶描述（50字以內，用第一人稱「我」）",
      "memory_type": "observation|belief_update|emotional_reaction|social_interaction",
      "salience_score": 0.0-1.0,
      "importance_score": 1-10,
      "triples": [
        {{"subject": "主體", "predicate": "關係動詞", "object": "客體"}}
      ]
    }}
  ]
}}

importance_score 代表記憶嘅永久重要性（唔受時間衰減影響）：
- 1-3: 平凡日常，唔太重要
- 4-6: 中等重要，有一定影響
- 7-9: 重要事件，影響信念或關係
- 10: 極端重要，關鍵轉折點

記憶類型說明：
- observation: 觀察到嘅事實或事件
- belief_update: 觀點或信念嘅改變
- emotional_reaction: 情緒反應（憤怒、擔心、開心等）
- social_interaction: 同其他用戶嘅互動記憶

salience_score 代表記憶嘅重要程度，影響後續行為嘅程度。

triples 欄位可選，格式為 (主體, 關係, 客體) 三元組，例如：
- {{"subject": "我", "predicate": "擔心", "object": "樓價繼續跌"}}
- {{"subject": "HIBOR", "predicate": "影響", "object": "月供壓力"}}
如果無明顯關係可提取，可以返回空陣列 []。"""

MEMORY_CONTEXT_FORMAT = """【第 {round_number} 輪記憶（{memory_type}，重要度 {salience:.2f}）】
{memory_text}"""

# ---------------------------------------------------------------------------
# Memory Summarization prompts (Phase 17 — local Zep-style compression)
# ---------------------------------------------------------------------------

MEMORY_COMPRESSION_SYSTEM = """你係一個記憶壓縮專家。將一個人嘅多條記憶整合成一段精煉嘅摘要。
保留最重要嘅事實、情感轉變、同關鍵人物關係。用繁體中文廣東話書寫。"""

MEMORY_COMPRESSION_USER = """以下係 Agent #{agent_id} 嘅 {memory_count} 條舊記憶：

{memories}

請將以上記憶壓縮成一段 200 字以內嘅摘要，保留：
1. 最核心嘅事實同觀點變化
2. 重要嘅人際關係同信任變動
3. 關鍵嘅情感轉折點
只輸出摘要文字，唔好加任何標題或格式。"""
