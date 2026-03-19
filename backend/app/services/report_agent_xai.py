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
from backend.app.utils.llm_client import LLMClient, get_report_provider_model

# Module-level LLM client shared across all XAI calls to reuse httpx pool.
_xai_llm_client: LLMClient | None = None


def _get_xai_llm() -> LLMClient:
    global _xai_llm_client
    if _xai_llm_client is None:
        _xai_llm_client = LLMClient()
    return _xai_llm_client


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
    llm = _get_xai_llm()
    prompt = (
        "將以下查詢分解為3-5個具體的子查詢，每個子查詢針對模擬數據的不同面向。\n"
        "只輸出JSON陣列格式：[\"子查詢1\", \"子查詢2\", ...]\n\n"
        f"查詢：{query}"
    )
    _r_provider, _r_model = get_report_provider_model()
    llm_response = await llm.chat(
        [{"role": "user", "content": prompt}],
        provider=_r_provider,
        model=_r_model,
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
            """SELECT am.memory_text, am.agent_id, ap.oasis_username as agent_name
               FROM agent_memories am
               LEFT JOIN agent_profiles ap ON am.agent_id = ap.id AND ap.session_id = am.session_id
               WHERE am.session_id = ? AND am.memory_text LIKE ?
               ORDER BY am.salience_score DESC LIMIT 5""",
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
            """SELECT kn.title AS label, ke.relation_type, ke.description
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


# ---------------------------------------------------------------------------
# get_topic_evolution — KG-edge topic migration across rounds
# ---------------------------------------------------------------------------


async def get_topic_evolution(
    session_id: str, window_size: int = 5
) -> "TopicEvolutionResult":
    """Analyse how dominant topics in KG edges shift across simulation rounds.

    Divides the simulation into windows of ``window_size`` rounds and uses
    Haiku to extract 2-4 dominant topic labels from the edge descriptions in
    each window.  Falls back to empty topics when the LLM returns malformed
    JSON.

    Args:
        session_id: UUID of the simulation session.
        window_size: Number of rounds per topic window (default 5).

    Returns:
        :class:`~backend.app.models.report_models.TopicEvolutionResult` with
        per-window ``TopicWindow`` objects and a ``migration_path`` summary.
    """
    from backend.app.models.report_models import TopicEvolutionResult, TopicWindow  # noqa: PLC0415

    async with get_db() as db:
        max_row = await (
            await db.execute(
                "SELECT MAX(round_number) as max_rn FROM kg_edges WHERE session_id=?",
                (session_id,),
            )
        ).fetchone()
    max_rn = (max_row["max_rn"] or 0) if max_row else 0

    if max_rn == 0:
        return TopicEvolutionResult(windows=(), migration_path="", inflection_round=None)

    llm = _get_xai_llm()

    async def _process_window(
        session_id: str, start: int, end: int, llm: LLMClient
    ) -> "TopicWindow | None":
        async with get_db() as db:
            rows = await (
                await db.execute(
                    "SELECT description FROM kg_edges "
                    "WHERE session_id=? AND round_number BETWEEN ? AND ? LIMIT 30",
                    (session_id, start, end),
                )
            ).fetchall()
        descriptions = [r["description"] for r in rows if r["description"]]
        if not descriptions:
            return None
        prompt = (
            "從以下描述中提取2-4個主要議題標籤（短詞）：\n"
            + "\n".join(descriptions[:10])
            + "\n只輸出JSON陣列：[\"議題1\",...]"
        )
        _r_provider, _r_model = get_report_provider_model()
        llm_response = await llm.chat(
            [{"role": "user", "content": prompt}],
            provider=_r_provider,
            model=_r_model,
            max_tokens=128,
        )
        response_text = llm_response.content
        match = _re.search(r"\[.*\]", response_text, _re.DOTALL)
        topics: tuple[str, ...] = ()
        if match:
            try:
                topics = tuple(_json.loads(match.group()))
            except _json.JSONDecodeError:
                pass
        return TopicWindow(
            rounds=f"{start}-{end}",
            dominant_topics=topics,
            emerging=(),
            fading=(),
        )

    coros = [
        _process_window(session_id, start, min(start + window_size - 1, max_rn), llm)
        for start in range(1, max_rn + 1, window_size)
    ]
    gather_results = await _asyncio.gather(*coros, return_exceptions=True)
    windows = [w for w in gather_results if isinstance(w, TopicWindow)]

    topic_sequence = [w.dominant_topics[0] for w in windows if w.dominant_topics]
    migration_path = " → ".join(dict.fromkeys(topic_sequence))

    return TopicEvolutionResult(
        windows=tuple(windows),
        migration_path=migration_path,
        inflection_round=None,
    )


# ---------------------------------------------------------------------------
# get_platform_breakdown — per-platform action + sentiment stats
# ---------------------------------------------------------------------------


async def get_platform_breakdown(session_id: str) -> dict:
    """Compare agent behaviour and sentiment across social platforms.

    Queries all distinct platforms present in ``simulation_actions`` for the
    session, then computes per-platform action counts and sentiment ratios.

    Args:
        session_id: UUID of the simulation session.

    Returns:
        Dict mapping platform name → ``{total_actions, sentiment, top_action_types}``.
        Returns an empty dict when no actions exist.
    """
    from collections import Counter  # noqa: PLC0415

    async with get_db() as db:
        platform_rows = await (
            await db.execute(
                "SELECT DISTINCT platform FROM simulation_actions "
                "WHERE session_id=? AND platform IS NOT NULL",
                (session_id,),
            )
        ).fetchall()
    platforms = [r["platform"] for r in platform_rows]

    result: dict = {}
    for platform in platforms:
        async with get_db() as db:
            rows = await (
                await db.execute(
                    "SELECT sentiment, action_type FROM simulation_actions "
                    "WHERE session_id=? AND platform=? LIMIT 200",
                    (session_id, platform),
                )
            ).fetchall()
        total = len(rows)
        if total == 0:
            continue
        sentiments = [r["sentiment"] for r in rows]
        action_types = [r["action_type"] for r in rows]
        sentiment_counts = Counter(sentiments)
        action_counts = Counter(action_types)
        result[platform] = {
            "total_actions": total,
            "sentiment": {k: round(v / total, 2) for k, v in sentiment_counts.items()},
            "top_action_types": [t for t, _ in action_counts.most_common(3)],
        }

    return result


# ---------------------------------------------------------------------------
# get_agent_story_arcs — cross-round narrative arcs for kg_driven agents
# ---------------------------------------------------------------------------


async def get_agent_story_arcs(
    session_id: str,
    sim_mode: str = "kg_driven",
    agents_per_type: int = 1,
) -> list[dict]:
    """Generate LLM narrative arcs for representative kg_driven agents.

    Only applies to ``kg_driven`` mode — returns ``[]`` immediately for
    ``hk_demographic`` sessions.  Selects up to one agent per cognitive
    fingerprint type (capped at 10 agents total) and uses Haiku to summarise
    each agent's stance evolution from their action timeline.

    Args:
        session_id: UUID of the simulation session.
        sim_mode: ``"kg_driven"`` or ``"hk_demographic"``.
        agents_per_type: Agents to select per type (default 1).

    Returns:
        List of arc dicts with ``agent_id``, ``agent_type``, ``arc_summary``,
        ``key_turning_round``, ``stance_shift``, ``sentiment_trajectory``.
        Empty list when ``sim_mode != "kg_driven"`` or no fingerprints exist.
    """
    if sim_mode != "kg_driven":
        return []

    async with get_db() as db:
        rows = await (
            await db.execute(
                """SELECT cf.agent_id,
                          COALESCE(ap.entity_type, ap.agent_type, 'unknown') as agent_type,
                          COUNT(sa.id) as action_count
                   FROM cognitive_fingerprints cf
                   LEFT JOIN agent_profiles ap ON ap.id = cf.agent_id
                   LEFT JOIN simulation_actions sa
                       ON sa.agent_id = cf.agent_id AND sa.session_id = ?
                   WHERE cf.simulation_id = ?
                   GROUP BY cf.agent_id, agent_type
                   ORDER BY action_count DESC""",
                (session_id, session_id),
            )
        ).fetchall()

    if not rows:
        return []

    # Take up to 10 agents
    selected = [dict(r) for r in rows[:10]]

    llm = _get_xai_llm()

    async def _generate_arc(session_id: str, agent: dict, llm: LLMClient) -> dict | None:
        agent_id = agent["agent_id"]
        async with get_db() as db:
            action_rows = await (
                await db.execute(
                    """SELECT round_number, content, sentiment
                       FROM simulation_actions
                       WHERE session_id=? AND agent_id=?
                       ORDER BY round_number LIMIT 20""",
                    (session_id, agent_id),
                )
            ).fetchall()

        if not action_rows:
            return None

        timeline = "\n".join(
            f"Round {r['round_number']}: {r['sentiment']} — {(r['content'] or '')[:80]}"
            for r in action_rows
        )
        prompt = (
            f"這個Agent的行為時間線：\n{timeline}\n\n"
            "用2-3句話描述這個Agent的故事弧（立場如何隨時間演化）："
        )
        _r_provider, _r_model = get_report_provider_model()
        llm_response = await llm.chat(
            [{"role": "user", "content": prompt}],
            provider=_r_provider,
            model=_r_model,
            max_tokens=256,
        )
        arc_summary = llm_response.content.strip()

        sentiments = [r["sentiment"] for r in action_rows if r["sentiment"]]
        sentiment_vals = [
            1.0 if s == "positive" else (-1.0 if s == "negative" else 0.0)
            for s in sentiments
        ]

        return {
            "agent_id": agent_id,
            "agent_type": agent.get("agent_type", "unknown"),
            "arc_summary": arc_summary,
            "key_turning_round": action_rows[len(action_rows) // 2]["round_number"],
            "stance_shift": (
                f"{sentiments[0] if sentiments else '?'} → "
                f"{sentiments[-1] if sentiments else '?'}"
            ),
            "sentiment_trajectory": sentiment_vals[:5],
        }

    coros = [_generate_arc(session_id, agent, llm) for agent in selected]
    results = await _asyncio.gather(*coros, return_exceptions=True)
    arcs = [a for a in results if isinstance(a, dict)]

    return arcs
