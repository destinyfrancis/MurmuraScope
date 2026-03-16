"""XAI (Explainable AI) tool handlers for ReportAgent.

These handlers provide decision-level transparency: agent decision summaries,
sentiment timelines, ensemble forecast bands, and macro indicator history.
"""

from __future__ import annotations

import json
from typing import Any

from backend.app.services.simulation_ipc import SimulationIPC
from backend.app.utils.db import get_db


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
