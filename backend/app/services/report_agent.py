"""ReACT loop report generator using Claude.

Implements a Reason-Act-Observe loop that calls analytical tools to gather
simulation insights, then compiles findings into a structured Markdown report.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from backend.app.config import get_settings
from backend.app.services.report_agent_xai import (
    get_agent_story_arcs as _get_agent_story_arcs,
    get_platform_breakdown as _get_platform_breakdown,
    get_topic_evolution as _get_topic_evolution,
    handle_decision_summary as _handle_decision_summary,
    handle_ensemble_forecast as _handle_ensemble_forecast,
    handle_macro_history as _handle_macro_history,
    handle_sentiment_timeline as _handle_sentiment_timeline,
    insight_forge as _insight_forge,
)
from backend.app.services.report_section_generator import _truncate_observation
from backend.app.services.simulation_ipc import SimulationIPC
from backend.app.utils.db import get_db
from backend.app.utils.llm_client import LLMClient, get_report_provider_model
from backend.app.utils.logger import get_logger

logger = get_logger("report_agent")

_MAX_REACT_ITERATIONS = 10

# Module-level LLM client — reused across all legacy ReACT calls to share
# the httpx connection pool and avoid per-call socket leaks.
_llm_client: LLMClient | None = None


def _get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client

TOOLS: dict[str, str] = {
    "query_graph": (
        "Semantic knowledge graph query — retrieves community-level insights, "
        "subgraph structure, and cross-faction dynamics for a topic"
    ),
    "get_global_narrative": (
        "Get cross-community narrative analysis showing social fault lines "
        "and faction dynamics across all agent communities"
    ),
    "get_sentiment_distribution": (
        "Get sentiment distribution across agent demographics"
    ),
    "get_demographic_breakdown": (
        "Get action breakdown by age/sex/district/income"
    ),
    "interview_agents": (
        "Interview sample agents about their decisions"
    ),
    "get_macro_context": (
        "Get current macro-economic context"
    ),
    "calculate_cashflow": (
        "Calculate cashflow projection for property/life decisions"
    ),
    "get_decision_summary": (
        "Get aggregate agent decision statistics (emigration rate, property purchase rate, etc.)"
    ),
    "get_sentiment_timeline": (
        "Get per-round sentiment evolution from simulation actions"
    ),
    "get_ensemble_forecast": (
        "Get Monte Carlo distribution bands from ensemble results"
    ),
    "get_macro_history": (
        "Get macro indicator changes across simulation rounds"
    ),
    "get_validation_summary": (
        "Get prediction confidence score, backtest results, and historical accuracy rate"
    ),
    "insight_forge": (
        "深度洞察查詢 — LLM拆解為子查詢，並行搜索memories/KG/actions，標記可引用原文"
    ),
    "get_topic_evolution": (
        "追蹤議題在模擬輪次中的遷移（如：個案 → 程序正義 → 制度信任）"
    ),
    "get_platform_breakdown": (
        "比較不同社交平台上Agent行為和情緒的差異"
    ),
    "get_agent_story_arcs": (
        "追蹤代表性Agent的跨輪次立場演化故事（kg_driven only）"
    ),
}

_TOOL_DESCRIPTIONS = "\n".join(
    f"- {name}: {desc}" for name, desc in TOOLS.items()
)

_SYSTEM_PROMPT = f"""You are an expert analyst generating reports from Hong Kong social simulation data.

You have access to the following tools:
{_TOOL_DESCRIPTIONS}

Use a ReACT (Reason-Act-Observe) approach:
1. THINK: Reason about what data you need
2. ACT: Call a tool using JSON format: {{"tool": "tool_name", "params": {{...}}}}
3. OBSERVE: Analyse the tool output
4. Repeat until you have enough data
5. REPORT: Write your final report in Markdown

When you have gathered enough data, output your final report starting with "## FINAL_REPORT"

Always structure reports with:
- Executive Summary
- Key Findings (numbered)
- Detailed Analysis sections
- Charts/Data recommendations
- Methodology notes"""

_CHAT_SYSTEM_PROMPT = """You are an expert analyst discussing simulation results with a user.
You have context from a previously generated report. Answer questions about
the findings, methodology, or suggest further analysis.
Be specific and reference data points when possible."""


class ReportAgent:
    """ReACT-based report generation agent using Claude."""

    def __init__(self, ipc: SimulationIPC | None = None) -> None:
        self._ipc = ipc or SimulationIPC()

    async def generate_report(
        self,
        session_id: str,
        report_type: str = "full",
        focus_areas: list[str] | None = None,
        scenario_question: str | None = None,
    ) -> dict[str, Any]:
        """Generate report using 3-phase orchestrator (with ReACT fallback).

        When ``scenario_question`` is provided or ``report_type == "full"``,
        delegates to :class:`ReportOrchestrator` for structured 3-phase
        generation (outline → per-section ReACT → assembly).  Otherwise falls
        back to the classic flat ReACT loop.

        Args:
            session_id: UUID of the simulation session.
            report_type: Type of report (full, summary, demographic, sentiment).
            focus_areas: Optional list of areas to focus on.
            scenario_question: Optional framing question ("如果X發生，Y會怎樣？").

        Returns:
            Dict with report_id, title, content_markdown, summary,
            key_findings, charts_data, agent_log.
        """
        # --- 3-phase orchestrated path ---
        # Only engage when caller explicitly provides a scenario_question.
        # report_type=="full" without a question still uses the legacy ReACT loop
        # to preserve backward compatibility with existing callers.
        if scenario_question is not None:
            from backend.app.services.report_orchestrator import ReportOrchestrator  # noqa: PLC0415

            orchestrator = ReportOrchestrator(llm_client=_get_llm_client())

            async def _tool_handler(name: str, params: dict[str, Any]) -> str:
                return await self._execute_tool(name, params, session_id)

            content_md = await orchestrator.generate(
                session_id=session_id,
                scenario_question=scenario_question,
                report_type=report_type,
                tool_handler=_tool_handler,
                tool_names=list(TOOLS.keys()),
            )
            report = _parse_report(session_id, content_md)
            report["agent_log"] = []
            await _persist_report(session_id, report, report_type, [])
            return report

        # --- Legacy flat ReACT path (non-full report types without a question) ---
        focus = focus_areas or []
        initial_prompt = _build_initial_prompt(
            session_id, report_type, focus
        )

        messages: list[dict[str, str]] = [
            {"role": "user", "content": initial_prompt},
        ]

        observations: list[dict[str, Any]] = []
        react_steps: list[dict[str, Any]] = []

        def _log_step(step_type: str, content: str) -> None:
            react_steps.append({
                "step_type": step_type,
                "content": content,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        _log_step("Thought", f"開始生成 {report_type} 報告，工作階段 {session_id}")

        for iteration in range(_MAX_REACT_ITERATIONS):
            logger.info(
                "ReACT iteration %d/%d for session %s",
                iteration + 1,
                _MAX_REACT_ITERATIONS,
                session_id,
            )

            response = await _call_llm(messages, _SYSTEM_PROMPT)
            messages.append({"role": "assistant", "content": response})

            # Check if the agent has produced a final report
            if "## FINAL_REPORT" in response:
                _log_step(
                    "Thought",
                    f"已收集足夠數據，於第 {iteration + 1} 次迭代後生成最終報告",
                )
                report_content = _extract_final_report(response)
                report = _parse_report(session_id, report_content)
                report["agent_log"] = react_steps
                await _persist_report(session_id, report, report_type, react_steps)
                # Record predictions for calibration tracking
                try:
                    from backend.app.services.calibration_tracker import CalibrationTracker  # noqa: PLC0415
                    from datetime import timedelta  # noqa: PLC0415
                    tracker = CalibrationTracker()
                    target_date = (datetime.now(timezone.utc) + timedelta(days=30)).date().isoformat()
                    for finding in report.get("key_findings", [])[:3]:
                        await tracker.record(
                            session_id=session_id,
                            metric=finding[:50],
                            predicted_direction="up",
                            predicted_magnitude=0.0,
                            target_date=target_date,
                        )
                except Exception:
                    logger.debug("Calibration record skipped", exc_info=True)
                logger.info(
                    "Report generated for session %s after %d iterations",
                    session_id,
                    iteration + 1,
                )
                return report

            # Try to extract and execute a tool call
            tool_call = _extract_tool_call(response)
            if tool_call is not None:
                tool_name = tool_call["tool"]
                params = tool_call.get("params", {})

                _log_step(
                    "Action",
                    f"調用工具 `{tool_name}`，參數：{json.dumps(params, ensure_ascii=False)}",
                )

                observation = await self._execute_tool(
                    tool_name, params, session_id
                )
                observations.append({
                    "tool": tool_name,
                    "params": params,
                    "result": observation,
                })

                # Truncate long observations for log readability
                obs_preview = observation[:300] + "..." if len(observation) > 300 else observation
                _log_step("Observation", f"工具 `{tool_name}` 返回：{obs_preview}")

                messages.append({
                    "role": "user",
                    "content": f"OBSERVATION from {tool_name}:\n{_truncate_observation(observation)}",
                })
            else:
                _log_step(
                    "Thought",
                    f"第 {iteration + 1} 次迭代：正在整合數據，繼續分析...",
                )
                # No tool call and no final report — prompt to continue
                messages.append({
                    "role": "user",
                    "content": (
                        "Please either call a tool for more data or "
                        "produce your final report starting with "
                        "'## FINAL_REPORT'."
                    ),
                })

        # Max iterations reached — ask for final report
        _log_step("Thought", "已達最大迭代次數，強制生成最終報告")
        messages.append({
            "role": "user",
            "content": (
                "Maximum analysis iterations reached. Please produce your "
                "final report now, starting with '## FINAL_REPORT'."
            ),
        })
        response = await _call_llm(messages, _SYSTEM_PROMPT)
        report_content = _extract_final_report(response)
        report = _parse_report(session_id, report_content)
        report["agent_log"] = react_steps
        await _persist_report(session_id, report, report_type, react_steps)
        return report

    async def chat(
        self,
        session_id: str,
        message: str,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        """Continue conversation about the report.

        Args:
            session_id: UUID of the simulation session.
            message: User's message.
            history: Previous conversation messages.

        Returns:
            Assistant's response string.
        """
        if not message or not message.strip():
            raise ValueError("Message cannot be empty")

        report_context = await _load_report_context(session_id)

        messages: list[dict[str, str]] = []

        if report_context:
            messages.append({
                "role": "user",
                "content": f"Reference report:\n{report_context}",
            })
            messages.append({
                "role": "assistant",
                "content": "I have the report context. How can I help?",
            })

        if history:
            messages.extend(history)

        messages.append({"role": "user", "content": message})

        response = await _call_llm(messages, _CHAT_SYSTEM_PROMPT)
        return response

    async def _execute_tool(
        self,
        tool_name: str,
        params: dict[str, Any],
        session_id: str,
    ) -> str:
        """Execute a ReACT tool and return observation.

        Args:
            tool_name: Name of the tool to call.
            params: Parameters for the tool.
            session_id: Current session ID.

        Returns:
            String observation from the tool execution.
        """
        if tool_name not in TOOLS:
            return f"Error: Unknown tool '{tool_name}'. Available: {list(TOOLS.keys())}"

        try:
            handler = _TOOL_HANDLERS.get(tool_name)
            if handler is None:
                return f"Error: Tool '{tool_name}' has no handler implementation."
            return await handler(session_id, params, self._ipc)
        except Exception as exc:
            logger.exception("Tool %s failed for session %s", tool_name, session_id)
            return f"Error executing {tool_name}: {exc}"


# ---------------------------------------------------------------------------
# Tool handler implementations
# ---------------------------------------------------------------------------


async def _handle_query_graph(
    session_id: str, params: dict[str, Any], _ipc: SimulationIPC
) -> str:
    """Semantic knowledge graph query via GraphRAG (with legacy fallback)."""
    query = params.get("query", "")
    if not query:
        return "Error: 'query' parameter is required."

    # Try GraphRAG semantic subgraph query first
    try:
        from backend.app.services.graph_rag import GraphRAGService  # noqa: PLC0415

        service = GraphRAGService()
        insight = await service.semantic_subgraph_query(session_id, query)
        return (
            f"## 語義子圖分析\n\n"
            f"**查詢：** {insight.query}\n"
            f"**相關社群：** {insight.relevant_communities}\n"
            f"**子圖規模：** {insight.node_count} 節點, {insight.edge_count} 條邊\n\n"
            f"{insight.insight_report}"
        )
    except Exception as exc:
        logger.debug("GraphRAG query failed (%s), falling back to legacy LIKE search", exc)

    # Legacy fallback: SQL LIKE search
    return await _handle_query_graph_legacy(session_id, params, _ipc)


async def _handle_query_graph_legacy(
    session_id: str, params: dict[str, Any], _ipc: SimulationIPC
) -> str:
    """Legacy knowledge graph query using SQL LIKE search."""
    query = params.get("query", "")
    entity_type = params.get("entity_type", "")

    async with get_db() as db:
        cursor = await db.execute(
            """SELECT source_id, target_id, relation_type, weight
               FROM kg_edges
               WHERE session_id = ?
               AND (source_id LIKE ? OR target_id LIKE ? OR relation_type LIKE ?)
               ORDER BY weight DESC
               LIMIT 50""",
            (session_id, f"%{query}%", f"%{query}%", f"%{entity_type}%"),
        )
        rows = await cursor.fetchall()

    if not rows:
        return "No matching graph relationships found."

    results = [
        {
            "source_id": r["source_id"],
            "target_id": r["target_id"],
            "relation_type": r["relation_type"],
            "weight": r["weight"],
        }
        for r in rows
    ]
    return json.dumps(results, indent=2)


async def _handle_global_narrative(
    session_id: str, params: dict[str, Any], _ipc: SimulationIPC
) -> str:
    """Get global narrative analysis across all communities."""
    try:
        from backend.app.services.graph_rag import GraphRAGService  # noqa: PLC0415

        round_number = params.get("round_number")
        service = GraphRAGService()
        narrative = await service.get_global_narrative(session_id, round_number)

        fault_lines_text = "\n".join(f"- {fl}" for fl in narrative.fault_lines) if narrative.fault_lines else "(未偵測到明顯斷層線)"

        return (
            f"## 全局社會敘事分析\n\n"
            f"**工作階段：** {narrative.session_id}\n"
            f"**第 {narrative.round_number} 輪，{narrative.community_count} 個社群**\n\n"
            f"### 社會斷層線\n{fault_lines_text}\n\n"
            f"### 詳細分析\n{narrative.narrative_text}"
        )
    except Exception as exc:
        logger.exception("get_global_narrative failed for session %s", session_id)
        return f"Error generating global narrative: {exc}"


_SAFE_DIMENSIONS = frozenset({
    "district", "age", "sex", "income_bracket",
    "occupation", "education_level", "agent_type",
    "marital_status", "housing_type",
})


async def _handle_sentiment_distribution(
    session_id: str, params: dict[str, Any], _ipc: SimulationIPC
) -> str:
    """Get sentiment distribution across demographics."""
    group_by = params.get("group_by", "district")

    if group_by not in _SAFE_DIMENSIONS:
        return f"Error: '{group_by}' is not a valid dimension. Use one of: {sorted(_SAFE_DIMENSIONS)}"

    async with get_db() as db:
        cursor = await db.execute(
            f"""SELECT {group_by}, agent_type, COUNT(*) as count
                FROM agent_profiles
                WHERE session_id = ?
                GROUP BY {group_by}, agent_type
                ORDER BY count DESC""",
            (session_id,),
        )
        rows = await cursor.fetchall()

    if not rows:
        return "No agent profile data available."

    results = [dict(r) for r in rows]
    return json.dumps(results, indent=2)


async def _handle_demographic_breakdown(
    session_id: str, params: dict[str, Any], _ipc: SimulationIPC
) -> str:
    """Get agent count breakdown by demographics."""
    dimensions = params.get("dimensions", ["age", "sex", "district"])

    results: dict[str, list[dict[str, Any]]] = {}
    async with get_db() as db:
        for dim in dimensions:
            if dim not in _SAFE_DIMENSIONS:
                results[dim] = [{"error": f"'{dim}' is not a valid dimension"}]
                continue
            cursor = await db.execute(
                f"""SELECT {dim}, agent_type, COUNT(*) as count
                    FROM agent_profiles
                    WHERE session_id = ?
                    GROUP BY {dim}, agent_type
                    ORDER BY count DESC
                    LIMIT 30""",
                (session_id,),
            )
            rows = await cursor.fetchall()
            results[dim] = [dict(r) for r in rows]

    return json.dumps(results, indent=2)


async def _handle_interview_agents(
    session_id: str, params: dict[str, Any], ipc: SimulationIPC
) -> str:
    """Interview sample agents about their decisions.

    Enriches each agent's interview context with the latest deliberation
    history (reasoning, topic_tags, emotional_reaction) from ``agent_decisions``
    before delegating to the IPC interview call.
    """
    question = params.get("question", "Why did you make these decisions?")
    agent_ids = params.get("agent_ids", [])
    sample_size = params.get("sample_size", 3)

    if not agent_ids:
        async with get_db() as db:
            cursor = await db.execute(
                """SELECT DISTINCT id FROM agent_profiles
                   WHERE session_id = ?
                   ORDER BY RANDOM()
                   LIMIT ?""",
                (session_id, sample_size),
            )
            rows = await cursor.fetchall()
            agent_ids = [r["id"] for r in rows]

    responses: list[dict[str, Any]] = []
    for agent_id in agent_ids:
        # Fetch deliberation context for richer interview prompt
        delib_context = ""
        try:
            async with get_db() as db:
                delib_rows = await (
                    await db.execute(
                        """SELECT reasoning, topic_tags, emotional_reaction, round_number
                           FROM agent_decisions
                           WHERE session_id=? AND agent_id=?
                           ORDER BY round_number DESC LIMIT 3""",
                        (session_id, agent_id),
                    )
                ).fetchall()
            if delib_rows:
                latest = delib_rows[0]
                delib_context = (
                    f"\n[第{latest['round_number']}輪推理過程]："
                    f"「{(latest['reasoning'] or '')[:200]}」"
                    f"\n[情緒反應]：{latest['emotional_reaction'] or '未記錄'}"
                    f"\n[議題標籤]：{latest['topic_tags'] or '[]'}"
                )
        except Exception:
            logger.warning(
                "Could not fetch deliberation context for agent %s", agent_id, exc_info=True
            )

        enriched_question = question + delib_context if delib_context else question

        try:
            answer = await ipc.interview_agent(session_id, agent_id, enriched_question)
            responses.append({"agent_id": agent_id, "response": answer})
        except Exception as exc:
            responses.append({"agent_id": agent_id, "error": str(exc)})

    return json.dumps(responses, indent=2)


async def _handle_macro_context(
    session_id: str, params: dict[str, Any], _ipc: SimulationIPC
) -> str:
    """Get macro-economic context for the simulation."""
    async with get_db() as db:
        cursor = await db.execute(
            """SELECT config_json FROM simulation_sessions WHERE id = ?""",
            (session_id,),
        )
        row = await cursor.fetchone()

    if row is None:
        return "Session not found."

    config = json.loads(row["config_json"]) if row["config_json"] else {}
    macro_id = config.get("macro_scenario_id")

    context = {
        "scenario_type": config.get("scenario_type", "unknown"),
        "macro_scenario_id": macro_id,
        "agent_count": config.get("agent_count", 0),
        "round_count": config.get("round_count", 0),
    }

    if macro_id:
        async with get_db() as db:
            cursor = await db.execute(
                """SELECT data_snapshot FROM macro_scenarios WHERE id = ?""",
                (macro_id,),
            )
            macro_row = await cursor.fetchone()
            if macro_row:
                context["macro_data"] = json.loads(macro_row["data_snapshot"])

    return json.dumps(context, indent=2)


async def _handle_calculate_cashflow(
    session_id: str, params: dict[str, Any], _ipc: SimulationIPC
) -> str:
    """Calculate cashflow projection for property/life decisions."""
    property_price = params.get("property_price", 5_000_000)
    monthly_income = params.get("monthly_income", 30_000)
    down_payment_pct = params.get("down_payment_pct", 0.3)
    mortgage_rate = params.get("mortgage_rate", 0.035)
    mortgage_years = params.get("mortgage_years", 30)
    monthly_expenses = params.get("monthly_expenses", 15_000)

    down_payment = property_price * down_payment_pct
    loan_amount = property_price - down_payment

    # Monthly mortgage payment (amortisation formula)
    monthly_rate = mortgage_rate / 12
    num_payments = mortgage_years * 12
    if monthly_rate > 0:
        monthly_payment = (
            loan_amount
            * monthly_rate
            * (1 + monthly_rate) ** num_payments
            / ((1 + monthly_rate) ** num_payments - 1)
        )
    else:
        monthly_payment = loan_amount / num_payments

    disposable = monthly_income - monthly_payment - monthly_expenses
    dti_ratio = monthly_payment / monthly_income if monthly_income > 0 else 0

    projection = {
        "property_price": property_price,
        "down_payment": round(down_payment),
        "loan_amount": round(loan_amount),
        "monthly_payment": round(monthly_payment),
        "monthly_disposable": round(disposable),
        "debt_to_income_ratio": round(dti_ratio, 3),
        "total_interest": round(monthly_payment * num_payments - loan_amount),
        "affordable": disposable > 0 and dti_ratio < 0.5,
    }

    return json.dumps(projection, indent=2)


async def _handle_get_validation_summary(
    session_id: str, params: dict[str, Any], _ipc: SimulationIPC
) -> str:
    from backend.app.services.calibration_tracker import CalibrationTracker  # noqa: PLC0415
    tracker = CalibrationTracker()
    accuracy = await tracker.get_accuracy()
    hit_rate_pct = accuracy["hit_rate"] * 100
    total = accuracy["total"]
    return (
        f"Historical prediction accuracy: {hit_rate_pct:.1f}% "
        f"over {total} verified predictions."
    )


async def _handle_insight_forge(
    session_id: str, params: dict[str, Any], _ipc: SimulationIPC
) -> str:
    """Deep query tool: LLM sub-query decomposition + parallel DB search."""
    query = params.get("query", "")
    if not query:
        return "Error: 'query' parameter is required."

    result = await _insight_forge(session_id, query)
    excerpts_text = "\n".join(result.quotable_excerpts) if result.quotable_excerpts else "(無可引用原文)"
    facts_text = "\n".join(result.facts[:5]) if result.facts else "(無相關事實)"
    return (
        "InsightForge結果:\n"
        f"子查詢：{', '.join(result.sub_queries)}\n\n"
        "引用原文:\n" + excerpts_text +
        "\n\n事實:\n" + facts_text
    )


async def _handle_get_topic_evolution(
    session_id: str, params: dict[str, Any], _ipc: SimulationIPC
) -> str:
    """Trace topic migration across simulation rounds via KG edges."""
    window_size = int(params.get("window_size", 5))
    result = await _get_topic_evolution(session_id, window_size=window_size)
    if not result.windows:
        return "議題演化：（無 KG 邊緣數據）"
    windows_desc = ", ".join(w.rounds for w in result.windows)
    return (
        f"議題演化：{result.migration_path}\n"
        f"時間窗口：{windows_desc}"
    )


async def _handle_get_platform_breakdown(
    session_id: str, params: dict[str, Any], _ipc: SimulationIPC
) -> str:
    """Compare agent behaviour and sentiment across social platforms."""
    result = await _get_platform_breakdown(session_id)
    if not result:
        return "無平台行為數據。"
    return json.dumps(result, indent=2, ensure_ascii=False)


async def _handle_get_agent_story_arcs(
    session_id: str, params: dict[str, Any], _ipc: SimulationIPC
) -> str:
    """Generate narrative story arcs for representative kg_driven agents."""
    sim_mode = params.get("sim_mode", "kg_driven")
    arcs = await _get_agent_story_arcs(session_id, sim_mode=sim_mode)
    if not arcs:
        return "無Agent故事弧數據（僅適用於 kg_driven 模式）。"
    return "\n".join(
        f"[{a['agent_type']}] {a['arc_summary']}"
        for a in arcs
    )


_TOOL_HANDLERS: dict[str, Any] = {
    "query_graph": _handle_query_graph,
    "get_global_narrative": _handle_global_narrative,
    "get_sentiment_distribution": _handle_sentiment_distribution,
    "get_demographic_breakdown": _handle_demographic_breakdown,
    "interview_agents": _handle_interview_agents,
    "get_macro_context": _handle_macro_context,
    "calculate_cashflow": _handle_calculate_cashflow,
    "get_decision_summary": _handle_decision_summary,
    "get_sentiment_timeline": _handle_sentiment_timeline,
    "get_ensemble_forecast": _handle_ensemble_forecast,
    "get_macro_history": _handle_macro_history,
    "get_validation_summary": _handle_get_validation_summary,
    "insight_forge": _handle_insight_forge,
    "get_topic_evolution": _handle_get_topic_evolution,
    "get_platform_breakdown": _handle_get_platform_breakdown,
    "get_agent_story_arcs": _handle_get_agent_story_arcs,
}


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def _build_initial_prompt(
    session_id: str,
    report_type: str,
    focus_areas: list[str],
) -> str:
    """Build the initial prompt for the ReACT loop."""
    focus_text = (
        f"Focus areas: {', '.join(focus_areas)}" if focus_areas else ""
    )
    return (
        f"Generate a {report_type} analysis report for simulation "
        f"session {session_id}.\n"
        f"{focus_text}\n\n"
        "Use the available tools to gather data before writing your report. "
        "Start by understanding the simulation context, then analyse "
        "sentiment, demographics, and interview sample agents."
    )


# ---------------------------------------------------------------------------
# Report parsing
# ---------------------------------------------------------------------------


def _extract_final_report(response: str) -> str:
    """Extract the final report content after the FINAL_REPORT marker."""
    marker = "## FINAL_REPORT"
    idx = response.find(marker)
    if idx == -1:
        return response
    return response[idx + len(marker) :].strip()


def _extract_tool_call(response: str) -> dict[str, Any] | None:
    """Extract a JSON tool call from the response."""
    # Look for JSON blocks with "tool" key
    start = response.find("{")
    if start == -1:
        return None

    # Try to find matching closing brace
    depth = 0
    for i in range(start, len(response)):
        if response[i] == "{":
            depth += 1
        elif response[i] == "}":
            depth -= 1
            if depth == 0:
                candidate = response[start : i + 1]
                try:
                    parsed = json.loads(candidate)
                    if "tool" in parsed:
                        return parsed
                except (json.JSONDecodeError, ValueError):
                    pass
                break

    return None


def _parse_report(session_id: str, content: str) -> dict[str, Any]:
    """Parse report content into structured result dict."""
    lines = content.strip().split("\n")
    title = "Simulation Analysis Report"
    key_findings: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# ") and title == "Simulation Analysis Report":
            title = stripped[2:].strip()
        elif stripped.startswith("1.") or stripped.startswith("2.") or stripped.startswith("3."):
            finding = stripped.split(".", 1)[-1].strip()
            if finding:
                key_findings.append(finding)

    # Generate summary from first paragraph
    summary_lines = []
    for line in lines:
        if line.strip():
            summary_lines.append(line.strip())
        elif summary_lines:
            break
    summary = " ".join(summary_lines[:3])

    return {
        "report_id": str(uuid4()),
        "title": title,
        "content_markdown": content,
        "summary": summary[:500],
        "key_findings": key_findings[:10],
        "charts_data": None,
        "agent_log": [],
    }


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


async def _persist_report(
    session_id: str,
    report: dict[str, Any],
    report_type: str = "full",
    react_steps: list[dict[str, Any]] | None = None,
) -> None:
    """Save generated report to the database."""
    agent_log_json = json.dumps(react_steps or report.get("agent_log") or [])
    async with get_db() as db:
        await db.execute(
            """INSERT INTO reports
               (id, session_id, report_type, title, content_markdown, summary,
                key_findings, charts_data, agent_log, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            (
                report["report_id"],
                session_id,
                report_type,
                report["title"],
                report["content_markdown"],
                report["summary"],
                json.dumps(report["key_findings"]),
                json.dumps(report["charts_data"]) if report["charts_data"] else None,
                agent_log_json,
            ),
        )
        await db.commit()


async def _load_report_context(session_id: str) -> str | None:
    """Load the most recent report for a session."""
    async with get_db() as db:
        cursor = await db.execute(
            """SELECT content_markdown FROM reports
               WHERE session_id = ?
               ORDER BY created_at DESC
               LIMIT 1""",
            (session_id,),
        )
        row = await cursor.fetchone()

    if row is None:
        return None
    return row["content_markdown"]


# ---------------------------------------------------------------------------
# LLM API call
# ---------------------------------------------------------------------------


async def _call_llm(
    messages: list[dict[str, str]],
    system_prompt: str,
) -> str:
    """Call LLM for report generation / chat (shares module-level connection pool)."""
    client = _get_llm_client()
    full_messages = [
        {"role": "system", "content": system_prompt},
        *messages,
    ]
    try:
        _r_provider, _r_model = get_report_provider_model()
        response = await client.chat(
            full_messages,
            provider=_r_provider,
            model=_r_model,
            max_tokens=4096,
        )
        return response.content
    except Exception as exc:
        logger.error("LLM call failed for report: %s", exc)
        return (
            "## FINAL_REPORT\n"
            "# Report Generation Error\n\n"
            f"LLM call failed: {exc}"
        )
