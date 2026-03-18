"""XAI (Explainable AI) tool handlers for ReportAgent.

These handlers provide decision-level transparency: agent decision summaries,
sentiment timelines, ensemble forecast bands, macro indicator history,
and the deep-query insight_forge tool.
"""

from __future__ import annotations

import asyncio as _asyncio
import json
import json as _json
import re as _re
from typing import Any

from backend.app.services.simulation_ipc import SimulationIPC
from backend.app.utils.db import get_db
from backend.app.utils.llm_client import LLMClient


async def handle_decision_summary(
    session_id: str, params: dict[str, Any], _ipc: SimulationIPC
) -> str:
    """Get aggregate decision statistics for the session.

    Args:
        session_id: UUID of the simulation session.
        params: Optional ``round_number`` to filter by a specific round.
        _ipc: Unused SimulationIPC reference (required by handler signature).

    Returns:
        JSON string with total agent count and per-decision-type breakdown.
    """
    round_number = params.get("round_number")

    async with get_db() as db:
        if round_number is not None:
            cursor = await db.execute(
                """SELECT decision_type, action, COUNT(*) as count,
                          ROUND(AVG(confidence), 2) as avg_confidence
                   FROM agent_decisions
                   WHERE session_id = ? AND round_number = ?
                   GROUP BY decision_type, action
                   ORDER BY count DESC""",
                (session_id, round_number),
            )
        else:
            cursor = await db.execute(
                """SELECT decision_type, action, COUNT(*) as count,
                          ROUND(AVG(confidence), 2) as avg_confidence
                   FROM agent_decisions
                   WHERE session_id = ?
                   GROUP BY decision_type, action
                   ORDER BY count DESC""",
                (session_id,),
            )
        rows = await cursor.fetchall()

        cursor2 = await db.execute(
            "SELECT COUNT(DISTINCT id) as total FROM agent_profiles WHERE session_id = ?",
            (session_id,),
        )
        total_row = await cursor2.fetchone()

    if not rows:
        return "No agent decisions found for this session."

    total_agents = total_row["total"] if total_row else 0

    results = []
    for r in rows:
        rate = round(r["count"] / total_agents * 100, 1) if total_agents > 0 else 0
        results.append({
            "decision_type": r["decision_type"],
            "action": r["action"],
            "count": r["count"],
            "avg_confidence": r["avg_confidence"],
            "rate_pct": rate,
        })

    return json.dumps({"total_agents": total_agents, "decisions": results}, indent=2)


async def handle_sentiment_timeline(
    session_id: str, params: dict[str, Any], _ipc: SimulationIPC
) -> str:
    """Get per-round sentiment evolution from simulation actions.

    Args:
        session_id: UUID of the simulation session.
        params: Unused (reserved for future filtering options).
        _ipc: Unused SimulationIPC reference.

    Returns:
        JSON array of per-round positive/negative/neutral ratios.
    """
    async with get_db() as db:
        cursor = await db.execute(
            """SELECT round_number,
                      SUM(CASE WHEN sentiment = 'positive' THEN 1 ELSE 0 END) as positive,
                      SUM(CASE WHEN sentiment = 'negative' THEN 1 ELSE 0 END) as negative,
                      SUM(CASE WHEN sentiment = 'neutral' THEN 1 ELSE 0 END) as neutral,
                      COUNT(*) as total
               FROM simulation_actions
               WHERE session_id = ?
               GROUP BY round_number
               ORDER BY round_number""",
            (session_id,),
        )
        rows = await cursor.fetchall()

    if not rows:
        return "No sentiment data found for this session."

    timeline = []
    for r in rows:
        total = r["total"] or 1
        timeline.append({
            "round": r["round_number"],
            "positive_ratio": round(r["positive"] / total, 3),
            "negative_ratio": round(r["negative"] / total, 3),
            "neutral_ratio": round(r["neutral"] / total, 3),
            "total_actions": total,
        })

    return json.dumps(timeline, indent=2)


async def handle_ensemble_forecast(
    session_id: str, params: dict[str, Any], _ipc: SimulationIPC
) -> str:
    """Get Monte Carlo ensemble distribution bands.

    Args:
        session_id: UUID of the simulation session.
        params: Optional ``metric`` to retrieve a single indicator.
        _ipc: Unused SimulationIPC reference.

    Returns:
        JSON array with p10–p90 percentile bands per metric.
    """
    metric = params.get("metric")

    async with get_db() as db:
        if metric:
            cursor = await db.execute(
                """SELECT metric, p10, p25, p50, p75, p90, mean, std_dev
                   FROM ensemble_results
                   WHERE session_id = ? AND metric = ?""",
                (session_id, metric),
            )
        else:
            cursor = await db.execute(
                """SELECT metric, p10, p25, p50, p75, p90, mean, std_dev
                   FROM ensemble_results
                   WHERE session_id = ?""",
                (session_id,),
            )
        rows = await cursor.fetchall()

    if not rows:
        return "No ensemble forecast results found. Run Monte Carlo simulation first."

    results = [dict(r) for r in rows]
    return json.dumps(results, indent=2)


async def handle_macro_history(
    session_id: str, params: dict[str, Any], _ipc: SimulationIPC
) -> str:
    """Get macro indicator snapshots across simulation rounds.

    Args:
        session_id: UUID of the simulation session.
        params: Unused (reserved for future round filtering).
        _ipc: Unused SimulationIPC reference.

    Returns:
        JSON array of key macro indicators per round.
    """
    async with get_db() as db:
        cursor = await db.execute(
            """SELECT round_number, snapshot_json
               FROM macro_snapshots
               WHERE session_id = ?
               ORDER BY round_number""",
            (session_id,),
        )
        rows = await cursor.fetchall()

    if not rows:
        return "No macro history snapshots found for this session."

    history = []
    for r in rows:
        snapshot = json.loads(r["snapshot_json"]) if r["snapshot_json"] else {}
        history.append({
            "round": r["round_number"],
            "consumer_confidence": snapshot.get("consumer_confidence"),
            "hsi_level": snapshot.get("hsi_level"),
            "unemployment_rate": snapshot.get("unemployment_rate"),
            "gdp_growth": snapshot.get("gdp_growth"),
            "ccl_index": snapshot.get("ccl_index"),
            "net_migration": snapshot.get("net_migration"),
        })

    return json.dumps(history, indent=2)


# ---------------------------------------------------------------------------
# insight_forge — deep query tool
# ---------------------------------------------------------------------------


async def _generate_sub_queries(query: str) -> tuple[str, ...]:
    """Use Haiku to decompose a query into 3-5 concrete sub-queries.

    Uses the cheap Haiku model to keep cost low.  Falls back to the original
    query string when the LLM returns malformed JSON.

    Args:
        query: High-level research question to decompose.

    Returns:
        Tuple of sub-query strings (1–5 elements).
    """
    llm = LLMClient()
    prompt = (
        "將以下查詢分解為3-5個具體的子查詢，每個子查詢針對模擬數據的不同面向。\n"
        "只輸出JSON陣列格式：[\"子查詢1\", \"子查詢2\", ...]\n\n"
        f"查詢：{query}"
    )
    llm_response = await llm.chat(
        [{"role": "user", "content": prompt}],
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        max_tokens=256,
    )
    response = llm_response.content
    match = _re.search(r"\[.*\]", response, _re.DOTALL)
    if not match:
        return (query,)
    try:
        parsed = _json.loads(match.group())
        if isinstance(parsed, list) and parsed:
            return tuple(str(s) for s in parsed)
        return (query,)
    except _json.JSONDecodeError:
        return (query,)


async def _search_agent_memories(session_id: str, query: str) -> list[dict]:
    """Fetch top-5 agent memories matching the query prefix.

    Args:
        session_id: UUID of the simulation session.
        query: Search term (first 20 chars used for LIKE match).

    Returns:
        List of dicts with ``content``, ``agent_id``, ``agent_name``.
    """
    async with get_db() as db:
        cursor = await db.execute(
            """SELECT am.content, am.agent_id, ap.name as agent_name
               FROM agent_memories am
               LEFT JOIN agent_profiles ap ON am.agent_id = ap.id
               WHERE am.session_id = ? AND am.content LIKE ?
               ORDER BY am.salience DESC LIMIT 5""",
            (session_id, f"%{query[:20]}%"),
        )
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def _search_kg_nodes_edges(session_id: str, query: str) -> list[dict]:
    """Fetch KG edges whose description matches the query prefix.

    Args:
        session_id: UUID of the simulation session.
        query: Search term (first 20 chars used for LIKE match).

    Returns:
        List of dicts with ``label``, ``relation_type``, ``description``.
    """
    async with get_db() as db:
        cursor = await db.execute(
            """SELECT kn.label, ke.relation_type, ke.description
               FROM kg_edges ke
               JOIN kg_nodes kn ON ke.source_id = kn.id
               WHERE ke.session_id = ? AND ke.description LIKE ?
               LIMIT 5""",
            (session_id, f"%{query[:20]}%"),
        )
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def _search_simulation_actions(session_id: str, query: str) -> list[dict]:
    """Fetch recent simulation actions matching the query prefix.

    Args:
        session_id: UUID of the simulation session.
        query: Search term (first 20 chars used for LIKE match).

    Returns:
        List of dicts with ``content``, ``agent_id``, ``round_number``,
        ``sentiment``.
    """
    async with get_db() as db:
        cursor = await db.execute(
            """SELECT sa.content, sa.agent_id, sa.round_number, sa.sentiment
               FROM simulation_actions sa
               WHERE sa.session_id = ? AND sa.content LIKE ?
               ORDER BY sa.round_number DESC LIMIT 5""",
            (session_id, f"%{query[:20]}%"),
        )
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def insight_forge(session_id: str, query: str) -> "InsightForgeResult":
    """Deep query tool: LLM-decomposed parallel search across all data sources.

    Decomposes the query into sub-queries via Haiku, then fans out concurrent
    searches across agent memories, KG edges, and simulation actions.
    Exceptions from individual searches are swallowed so a partial DB outage
    never kills the whole report.

    Args:
        session_id: UUID of the simulation session.
        query: High-level research question.

    Returns:
        :class:`~backend.app.models.report_models.InsightForgeResult` with
        deduplicated facts, attributed quotable excerpts, and source agents.
    """
    from backend.app.models.report_models import InsightForgeResult  # noqa: PLC0415

    sub_queries = await _generate_sub_queries(query)

    all_coros = []
    for sq in sub_queries:
        all_coros.append(_search_agent_memories(session_id, sq))
        all_coros.append(_search_kg_nodes_edges(session_id, sq))
        all_coros.append(_search_simulation_actions(session_id, sq))

    results = await _asyncio.gather(*all_coros, return_exceptions=True)

    facts: list[str] = []
    quotable: list[str] = []
    agents: set[str] = set()

    for r in results:
        if isinstance(r, Exception):
            continue
        for item in r:
            if not isinstance(item, dict):
                continue
            content = item.get("content") or item.get("description") or ""
            agent_id = str(item.get("agent_id") or item.get("agent_name") or "")
            if content:
                facts.append(content[:200])
                if agent_id and agent_id != "None":
                    quotable.append(f"[{agent_id}]: {content[:150]}")
                    agents.add(agent_id)

    return InsightForgeResult(
        query=query,
        sub_queries=sub_queries,
        facts=tuple(dict.fromkeys(facts)),
        quotable_excerpts=tuple(quotable[:10]),
        source_agents=tuple(agents),
    )
