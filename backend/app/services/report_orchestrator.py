"""3-phase report coordinator.

Phase 1: Generate outline (LLM → JSON chapters)
Phase 2: Per-section ReACT (ReportSectionGenerator)
Phase 3: Assembly + executive summary
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Awaitable

from backend.app.services.report_section_generator import generate_section
from backend.app.utils.db import get_db
from backend.app.utils.llm_client import LLMClient
from backend.app.utils.logger import get_logger
from backend.prompts.report_prompts import (
    PLANNING_SYSTEM_PROMPT,
    KG_DRIVEN_SECTION_SYSTEM_PROMPT,
    HK_DEMOGRAPHIC_SECTION_SYSTEM_PROMPT,
    build_planning_user_prompt,
)

logger = get_logger("report_orchestrator")

_FALLBACK_CHAPTERS = [
    {"title": "核心趨勢預測", "thesis": "基於模擬觀察的主要趨勢", "suggested_tools": ["insight_forge"]},
    {"title": "多角色反應分析", "thesis": "不同stakeholder的行為分化", "suggested_tools": ["interview_agents"]},
    {"title": "結構性影響預測", "thesis": "長期制度與社會影響", "suggested_tools": ["get_topic_evolution"]},
]


class ReportOrchestrator:
    """Coordinates 3-phase report generation."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm = llm_client or LLMClient()

    def _parse_outline(self, raw: str) -> list[dict[str, Any]]:
        """Extract chapters list from LLM outline response.

        Uses a balanced-brace parser to avoid greedy regex dropping chapters
        on trailing prose after the JSON block.

        Args:
            raw: Raw string from LLM which may contain JSON.

        Returns:
            List of chapter dicts, or empty list if parsing fails.
        """
        start = raw.find("{")
        if start == -1:
            return []
        depth = 0
        for i in range(start, len(raw)):
            if raw[i] == "{":
                depth += 1
            elif raw[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        data = json.loads(raw[start:i + 1])
                        return data.get("chapters", [])
                    except json.JSONDecodeError:
                        logger.warning("Failed to parse outline JSON: %.200s", raw)
                        return []
        return []

    async def _get_session_meta(self, session_id: str) -> dict[str, Any]:
        """Fetch session metadata from DB.

        Args:
            session_id: The simulation session ID.

        Returns:
            Dict with sim_mode, agent_count, round_count.
        """
        try:
            async with get_db() as db:
                session_row = await (await db.execute(
                    "SELECT sim_mode, preset FROM simulation_sessions WHERE id=?",
                    (session_id,)
                )).fetchone()
                agent_count_row = await (await db.execute(
                    "SELECT COUNT(*) as cnt FROM agent_profiles WHERE session_id=?",
                    (session_id,)
                )).fetchone()
                round_count_row = await (await db.execute(
                    "SELECT MAX(round_number) as max_round FROM simulation_actions WHERE session_id=?",
                    (session_id,)
                )).fetchone()
        except Exception:
            logger.warning("Failed to fetch session meta for %s", session_id)
            return {"sim_mode": "kg_driven", "agent_count": 0, "round_count": 0}

        if not session_row:
            return {"sim_mode": "kg_driven", "agent_count": 0, "round_count": 0}

        return {
            "sim_mode": session_row["sim_mode"] or "kg_driven",
            "agent_count": agent_count_row["cnt"] if agent_count_row else 0,
            "round_count": (round_count_row["max_round"] or 0) if round_count_row else 0,
        }

    async def generate(
        self,
        session_id: str,
        scenario_question: str | None,
        report_type: str,
        tool_handler: Callable[[str, dict[str, Any]], Awaitable[str]],
        tool_names: list[str] | None = None,
    ) -> str:
        """Run full 3-phase report generation.

        Args:
            session_id: Simulation session identifier.
            scenario_question: Optional question framing the report.
            report_type: Report type (e.g. "full", "summary").
            tool_handler: Async function (tool_name, params) -> result string.
            tool_names: Names of available tools.

        Returns:
            Assembled Markdown report string.
        """
        meta = await self._get_session_meta(session_id)
        sim_mode = meta.get("sim_mode", "kg_driven")

        if not scenario_question:
            scenario_question = "基於模擬結果，預測未來的發展趨勢和主要影響。"

        # Phase 1: Outline
        planning_prompt = build_planning_user_prompt(
            session_id=session_id,
            agent_count=meta.get("agent_count", 0),
            round_count=meta.get("round_count", 0),
            scenario_question=scenario_question,
            sim_mode=sim_mode,
        )
        outline_response = await self._llm.complete([
            {"role": "system", "content": PLANNING_SYSTEM_PROMPT},
            {"role": "user", "content": planning_prompt},
        ])
        chapters = self._parse_outline(outline_response)
        if not chapters:
            chapters = list(_FALLBACK_CHAPTERS)

        # Phase 2: Per-section generation
        all_tools = tool_names or []
        # Fix 1: substitute {tool_descriptions} placeholder before passing to generate_section
        tool_desc_text = (
            "\n".join(f"- {t}" for t in all_tools)
            if all_tools
            else "insight_forge, interview_agents, get_sentiment_timeline"
        )
        section_prompt = (
            KG_DRIVEN_SECTION_SYSTEM_PROMPT if sim_mode == "kg_driven"
            else HK_DEMOGRAPHIC_SECTION_SYSTEM_PROMPT
        ).format(tool_descriptions=tool_desc_text)

        completed_sections: list[str] = []

        for chapter in chapters:
            async def _handler(name: str, params: dict) -> str:
                return await tool_handler(name, params)

            # Fix 2: use chapter's suggested_tools as nudge hints instead of
            # computing unused before generate_section runs (which always gave empty set)
            unused = chapter.get("suggested_tools", all_tools)
            section_md = await generate_section(
                system_prompt=section_prompt,
                section_outline=chapter,
                previous_sections=completed_sections,
                tool_handler=_handler,
                llm_caller=lambda msgs: self._llm.complete(msgs),
                unused_tools=unused,
            )
            completed_sections.append(f"## {chapter['title']}\n\n{section_md}")

        # Phase 3: Assembly
        header = f"# 預測報告\n\n> 模擬問題：{scenario_question}\n\n---\n\n"
        return header + "\n\n---\n\n".join(completed_sections)
