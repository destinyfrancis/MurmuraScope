"""Narrative-driven meta-analysis engine (Phase 6).

Synthesizes raw simulation data into a compelling chronological story
with emergent pattern highlights.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from backend.app.utils.db import get_db
from backend.app.utils.llm_client import LLMClient, get_report_provider_model
from backend.app.utils.logger import get_logger

logger = get_logger("narrative_analyst")

class NarrativeAnalyst:
    """Orchestrates narrative-driven reporting for simulations."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm = llm_client or LLMClient()

    async def generate_dossier(self, session_id: str) -> dict[str, Any]:
        """Generate a deep narrative dossier for the simulation."""
        
        # 1. Fetch simulation metadata
        async with get_db() as db:
            row = await (await db.execute(
                "SELECT name, scenario_type, round_count, current_round FROM simulation_sessions WHERE id = ?",
                (session_id,)
            )).fetchone()
            if not row:
                raise ValueError(f"Session {session_id} not found")
            session_info = dict(row)

        # 2. Map Phase: Extract per-round summaries
        # To avoid context overflow, we harvest summaries round by round or in blocks.
        round_summaries = await self._harvest_round_data(session_id, session_info["current_round"])

        # 3. Reduce Phase: Narratize
        provider, model = get_report_provider_model()
        
        system_prompt = """你是一位專業的社會動態與敘事分析師。
你的任務是將模擬數據轉化為一份具有說服力、富有洞見且引人入勝的「深度敘事檔案」(Narrative Dossier)。

這份檔案應包含：
1. **事件全景 (The Grand Narrative)**：整個過程的核心故事線。
2. **關鍵轉折點 (Critical Turning Points)**：哪些關鍵人物、事件或推文導致了群體情緒的重大轉向？
3. **因果鏈分析 (Causal Chain Analysis)**：解釋「為什麼」發生。例如：事件 A 觸發了 Agent B 的恐懼，導致其發表了病毒式帖文 C，最終讓群體 D 轉向對立面。
4. **湧現模式 (Emergent Patterns)**：觀察到了哪些非預期的集體行為？
5. **未來展望 (Counterfactual Outlook)**：基於目前的終態，未來可能演變的方向。

請使用專業、敏銳且充滿敘事感的語氣編寫。"""

        user_prompt = f"""模擬名稱：{session_info['name']}
場景類型：{session_info['scenario_type']}
總輪數：{session_info['current_round']}

以下是逐輪的關鍵數據摘要：
{json.dumps(round_summaries, ensure_ascii=False, indent=1)}

請基於以上數據生成最終的 Markdown 格式敘事檔案。"""

        response = await self._llm.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            provider=provider,
            model=model,
            temperature=0.7,
        )

        return {
            "session_id": session_id,
            "title": f"【深度敘事檔案】{session_info['name']}",
            "content_markdown": response.content,
            "summary": "此報告基於模擬全過程的因果鏈分析生成，著重於敘事演化與轉折點。",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _harvest_round_data(self, session_id: str, current_round: int) -> list[dict[str, Any]]:
        """Gather key indicators and viral content for each round.

        Uses a single DB connection for all rounds to avoid N+1 connection overhead.
        """
        summaries: list[dict[str, Any]] = []

        async with get_db() as db:
            for r in range(1, current_round + 1):
                # Top viral posts — sorted by engagement_metrics.likes (Phase 6 schema)
                cursor = await db.execute(
                    """SELECT content, agent_id, sentiment FROM simulation_actions
                       WHERE session_id = ? AND round_number = ?
                       ORDER BY CAST(
                           json_extract(engagement_metrics, '$.likes') AS INTEGER
                       ) DESC NULLS LAST
                       LIMIT 3""",
                    (session_id, r),
                )
                posts = [dict(row) for row in await cursor.fetchall()]

                # Decision stats for this round
                cursor = await db.execute(
                    """SELECT COUNT(*) as shift_count, AVG(confidence) as avg_conf
                       FROM agent_decisions
                       WHERE session_id = ? AND round_number = ?""",
                    (session_id, r),
                )
                stats = await cursor.fetchone()

                # Global narrative from community_summaries (GraphRAG, optional)
                cursor = await db.execute(
                    """SELECT narrative_text, fault_lines
                       FROM community_summaries
                       WHERE session_id = ? AND round_number = ? LIMIT 1""",
                    (session_id, r),
                )
                gn = await cursor.fetchone()

                summaries.append({
                    "round": r,
                    "top_posts": posts,
                    "decision_stats": dict(stats) if stats else {},
                    "global_narrative": gn["narrative_text"] if gn else "N/A",
                    "fault_lines": json.loads(gn["fault_lines"]) if gn and gn["fault_lines"] else [],
                })

        return summaries
