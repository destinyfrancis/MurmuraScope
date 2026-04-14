"""Interview engine for post-simulation agent interaction (Phase 6).

Allows users to query agents about their decisions and state after simulation completion.
"""

from __future__ import annotations

from typing import Any
import aiosqlite

from backend.app.utils.db import get_db
from backend.app.utils.llm_client import LLMClient, get_step_provider_model
from backend.app.utils.logger import get_logger
from backend.app.services.agent_memory import AgentMemoryService

logger = get_logger("interview_engine")

class InterviewEngine:
    """Handles logic for agent interviews."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm = llm_client or LLMClient()
        from backend.app.services.agent_memory import AgentMemoryService # noqa
        self._memory_service = AgentMemoryService(llm_client=self._llm)

    async def generate_response(
        self,
        session_id: str,
        agent_id: str,
        query: str,
    ) -> str:
        """Generate an in-character response from an agent."""
        
        # 1. Fetch Agent Profile
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT * FROM agent_profiles WHERE session_id = ? AND id = ?",
                (session_id, agent_id),
            )
            profile = await cursor.fetchone()
            if not profile:
                raise ValueError(f"Agent {agent_id} not found in session {session_id}")
            profile_dict = dict(profile)

            # 2. Fetch Latest Round
            cursor = await db.execute(
                "SELECT round_number FROM agent_memories WHERE session_id = ? AND agent_id = ? ORDER BY round_number DESC LIMIT 1",
                (session_id, agent_id),
            )
            row = await cursor.fetchone()
            latest_round = row["round_number"] if row else 0

        # 3. Get Context (Memory + Relationships)
        # Using the memory service to get context
        # agent_id stays as str — HK mode uses int-as-str, kg_driven may be UUID
        try:
            agent_id_typed: int | str = int(agent_id)
        except (ValueError, TypeError):
            agent_id_typed = agent_id

        context = await self._memory_service.get_agent_context(
            session_id=session_id,
            agent_id=agent_id_typed,
            current_round=latest_round,
            context_query=query,
        )

        # 4. Construct Prompt
        system_prompt = self._build_system_prompt(profile_dict, context)
        
        # 5. Call LLM
        provider, model = get_step_provider_model(5)
        response = await self._llm.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"我是模擬器的觀察者。我想問你：{query}"},
            ],
            provider=provider,
            model=model,
            temperature=0.8, # Slightly higher for more creative "interview" feel
        )

        # 6. Persist Interview
        await self._persist_interview(session_id, agent_id, query, response.content)

        return response.content

    async def get_history(self, session_id: str, agent_id: str) -> list[dict[str, Any]]:
        """Retrieve interview history for an agent."""
        async with get_db() as db:
            cursor = await db.execute(
                """SELECT user_query, agent_response, created_at 
                   FROM agent_interviews 
                   WHERE session_id = ? AND agent_id = ?
                   ORDER BY created_at ASC""",
                (session_id, agent_id),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    def _build_system_prompt(self, profile: dict[str, Any], context: str) -> str:
        """Construct the system prompt for the agent character."""
        traits = profile.get("personality", "{}")
        if isinstance(traits, str):
            import json
            try:
                traits = json.loads(traits)
            except (json.JSONDecodeError, ValueError):
                traits = {}
        
        traits_str = ", ".join([f"{k}: {v:.2f}" for k, v in traits.items()]) if traits else "未知"
        
        return f"""你是一個在模擬環境中的人工智慧代理人。

【你的身份設定】
姓名/ID: {profile.get('id')}
年齡: {profile.get('age', '未知')}
性別: {profile.get('sex', '未知')}
職業: {profile.get('occupation', '未知')}
背景: {profile.get('backstory', '無')}
性格特質 (Big Five): {traits_str}

【背景記憶與關係】
{context}

【指令】
1. 嚴格遵守你的角色設定進行回答。
2. 你的回答必須基於你的記憶、經歷和性格。
3. 如果有人問你模擬過程中的決定，請根據你的記憶解釋你當時的想法和情感。
4. 保持沈浸感，不要提及你是一個 AI 或這是一個模擬（除非這就是你的角色設定）。
5. 回答請簡潔明瞭，保持真實的人類對話風格。
6. 使用繁體中文回答。
"""

    async def _persist_interview(
        self,
        session_id: str,
        agent_id: str,
        query: str,
        response: str,
    ) -> None:
        """Write interview record to DB."""
        async with get_db() as db:
            await db.execute(
                """INSERT INTO agent_interviews (session_id, agent_id, user_query, agent_response)
                   VALUES (?, ?, ?, ?)""",
                (session_id, agent_id, query, response),
            )
            await db.commit()
