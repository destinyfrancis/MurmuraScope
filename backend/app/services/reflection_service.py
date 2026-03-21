"""Reflection service for Tier 1 agent insight synthesis.

Inspired by Generative Agents (Park et al., 2023):
- Periodically triggered (every N rounds) for Tier 1 agents
- Retrieves top memories by salience + importance
- LLM synthesizes 3-5 abstract insights ('thought' nodes)
- Insights stored as high-importance memories for future retrieval

Active in kg_driven mode only. Best-effort — never raises.
"""
from __future__ import annotations

import hashlib

from backend.app.utils.db import get_db
from backend.app.utils.llm_client import LLMClient, get_agent_provider_model
from backend.app.utils.logger import get_logger
from backend.prompts.reflection_prompts import REFLECTION_SYSTEM, REFLECTION_USER

logger = get_logger("reflection_service")

_N_INSIGHTS = 3
_TOP_MEMORIES = 8         # memories to feed into reflection
_INSIGHT_SALIENCE = 0.85  # thoughts start high-salience
_MIN_MEMORIES = 3         # skip reflection if fewer memories exist


class ReflectionService:
    """Generate abstract thought memories for Tier 1 agents via reflection."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm = llm_client or LLMClient()

    async def reflect_for_agents(
        self,
        session_id: str,
        round_number: int,
        stakeholder_agents: list[dict],
        scenario_description: str,
    ) -> int:
        """Run reflection for all Tier 1 agents. Returns total insights stored.

        Best-effort: individual agent failures are logged and skipped.
        """
        total = 0
        for agent in stakeholder_agents:
            try:
                count = await self._reflect_one(
                    session_id=session_id,
                    round_number=round_number,
                    agent=agent,
                    scenario_description=scenario_description,
                )
                total += count
            except Exception:
                logger.debug(
                    "reflection skipped for agent=%s session=%s",
                    agent.get("id", "?"), session_id,
                )
        logger.info(
            "reflect_for_agents session=%s round=%d agents=%d insights=%d",
            session_id, round_number, len(stakeholder_agents), total,
        )
        return total

    async def _reflect_one(
        self,
        session_id: str,
        round_number: int,
        agent: dict,
        scenario_description: str,
    ) -> int:
        """Reflect for one agent. Returns number of insights stored."""
        agent_id_str = str(agent.get("id", ""))
        numeric_id = int(hashlib.md5(agent_id_str.encode()).hexdigest(), 16) % (2**31)

        # Fetch top memories by (salience + importance) for this agent
        memories = await self._fetch_top_memories(session_id, numeric_id)
        if len(memories) < _MIN_MEMORIES:
            return 0

        memories_text = "\n".join(
            f"[重要度{m['importance_score']:.1f}] {m['memory_text']}"
            for m in memories
        )

        provider, model = get_agent_provider_model()
        try:
            raw = await self._llm.chat_json(
                [
                    {"role": "system", "content": REFLECTION_SYSTEM},
                    {"role": "user", "content": REFLECTION_USER.format(
                        name=agent.get("name", agent_id_str),
                        role=agent.get("role", "actor"),
                        scenario_description=scenario_description[:200],
                        memories_text=memories_text,
                        n_insights=_N_INSIGHTS,
                    )},
                ],
                provider=provider,
                model=model,
                temperature=0.6,
                max_tokens=512,
            )
        except Exception:
            logger.debug("reflection LLM failed agent=%s", agent_id_str)
            return 0

        insights = raw.get("insights", [])
        if not isinstance(insights, list):
            return 0

        rows = []
        for item in insights[:_N_INSIGHTS]:
            if not isinstance(item, dict):
                continue
            thought = str(item.get("thought", "")).strip()
            if not thought:
                continue
            importance_raw = float(item.get("importance_score", 7))
            importance = max(0.0, min(1.0, importance_raw / 10.0))
            rows.append((
                session_id,
                numeric_id,
                round_number,
                thought,
                _INSIGHT_SALIENCE,
                "thought",
                importance,
            ))

        if not rows:
            return 0

        try:
            async with get_db() as db:
                await db.executemany(
                    """INSERT INTO agent_memories
                        (session_id, agent_id, round_number, memory_text,
                         salience_score, memory_type, importance_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    rows,
                )
                await db.commit()
        except Exception:
            logger.exception(
                "reflection insert failed session=%s agent=%s", session_id, agent_id_str
            )
            return 0

        return len(rows)

    async def _fetch_top_memories(
        self,
        session_id: str,
        agent_id: int,
    ) -> list[dict]:
        """Fetch top memories ranked by salience × importance."""
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    """SELECT memory_text,
                              salience_score,
                              COALESCE(importance_score, 0.5) AS importance_score
                       FROM agent_memories
                       WHERE session_id = ? AND agent_id = ?
                         AND memory_type != 'thought'
                       ORDER BY (salience_score * COALESCE(importance_score, 0.5)) DESC
                       LIMIT ?""",
                    (session_id, agent_id, _TOP_MEMORIES),
                )
                rows = await cursor.fetchall()
            return [
                {
                    "memory_text": r[0],
                    "salience_score": float(r[1]),
                    "importance_score": float(r[2]),
                }
                for r in rows
            ]
        except Exception:
            logger.exception(
                "_fetch_top_memories failed session=%s agent=%d", session_id, agent_id
            )
            return []
