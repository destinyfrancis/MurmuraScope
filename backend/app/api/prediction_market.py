"""Prediction Market API endpoints.

Connects HKSimEngine agent simulation output to Polymarket contracts,
generating trading signals from agent consensus.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from backend.app.models.response import APIResponse
from backend.app.utils.logger import get_logger

logger = get_logger("api.prediction_market")

router = APIRouter(prefix="/prediction-market", tags=["prediction-market"])


@router.get("/contracts", response_model=APIResponse)
async def list_contracts(
    category: str | None = None,
    limit: int = Query(default=50, le=200),
) -> APIResponse:
    """List active Polymarket prediction contracts."""
    from backend.app.services.polymarket_client import PolymarketClient

    client = PolymarketClient()
    contracts = await client.fetch_active_markets(category=category, limit=limit)

    return APIResponse(success=True, data=[
        {
            "id": c.id,
            "question": c.question,
            "description": c.description,
            "outcomes": list(c.outcomes),
            "outcome_prices": list(c.outcome_prices),
            "volume": c.volume,
            "liquidity": c.liquidity,
            "slug": c.slug,
            "category": c.category,
            "end_date": c.end_date,
        }
        for c in contracts
    ])


@router.get("/contracts/search", response_model=APIResponse)
async def search_contracts(
    q: str = Query(..., min_length=2),
    limit: int = Query(default=20, le=100),
) -> APIResponse:
    """Search Polymarket contracts by keyword."""
    from backend.app.services.polymarket_client import PolymarketClient

    client = PolymarketClient()
    results = await client.search_markets(q, limit=limit)

    return APIResponse(success=True, data=[
        {
            "id": c.id,
            "question": c.question,
            "outcomes": list(c.outcomes),
            "outcome_prices": list(c.outcome_prices),
            "volume": c.volume,
            "slug": c.slug,
        }
        for c in results
    ])


@router.get("/contracts/matched", response_model=APIResponse)
async def get_matched_contracts(
    session_id: str = Query(...),
    limit: int = Query(default=20, le=50),
) -> APIResponse:
    """Find Polymarket contracts relevant to a simulation session's seed text."""
    from backend.app.services.polymarket_client import PolymarketClient
    from backend.app.services.scenario_matcher import ScenarioMatcher
    from backend.app.utils.db import get_db

    # Load seed text from simulation session
    try:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT seed_text FROM simulation_sessions WHERE id = ?",
                (session_id,),
            )
            row = await cursor.fetchone()
    except Exception:
        logger.exception("DB error fetching seed_text for session=%s", session_id)
        raise HTTPException(status_code=500, detail="Database error")

    if not row or not row[0]:
        raise HTTPException(status_code=404, detail="Session not found or no seed text")

    seed_text = row[0]

    client = PolymarketClient()
    contracts = await client.fetch_active_markets(limit=200)

    matcher = ScenarioMatcher()
    matches = matcher.match_contracts(seed_text, contracts, max_results=limit)

    return APIResponse(success=True, data={
        "session_id": session_id,
        "seed_text_preview": seed_text[:200],
        "matched_count": len(matches),
        "matches": [
            {
                "contract": {
                    "id": m.contract.id,
                    "question": m.contract.question,
                    "outcomes": list(m.contract.outcomes),
                    "outcome_prices": list(m.contract.outcome_prices),
                    "volume": m.contract.volume,
                    "slug": m.contract.slug,
                },
                "relevance_score": m.relevance_score,
                "matched_keywords": list(m.matched_keywords),
                "matched_topics": list(m.matched_topics),
            }
            for m in matches
        ],
    })


@router.get("/signals", response_model=APIResponse)
async def get_signals(
    session_id: str = Query(...),
    limit: int = Query(default=20, le=50),
) -> APIResponse:
    """Generate trading signals for a simulation session.

    Matches session seed text to Polymarket contracts, estimates
    agent consensus probabilities, and compares with market prices.
    """
    from backend.app.services.polymarket_client import PolymarketClient
    from backend.app.services.scenario_matcher import ScenarioMatcher
    from backend.app.services.signal_generator import SignalGenerator
    from backend.app.utils.db import get_db

    # Load seed text
    try:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT seed_text FROM simulation_sessions WHERE id = ?",
                (session_id,),
            )
            row = await cursor.fetchone()
    except Exception:
        logger.exception("DB error fetching seed_text for session=%s", session_id)
        raise HTTPException(status_code=500, detail="Database error")

    if not row or not row[0]:
        raise HTTPException(status_code=404, detail="Session not found or no seed text")

    seed_text = row[0]

    # Fetch + match + signal
    client = PolymarketClient()
    contracts = await client.fetch_active_markets(limit=200)

    matcher = ScenarioMatcher()
    matches = matcher.match_contracts(seed_text, contracts, max_results=limit)

    if not matches:
        return APIResponse(success=True, data={
            "session_id": session_id,
            "signal_count": 0,
            "signals": [],
            "summary": "No matching Polymarket contracts found for this scenario.",
        })

    generator = SignalGenerator()
    signals = await generator.generate_signals(session_id, matches)

    buy_yes = sum(1 for s in signals if s.direction == "BUY_YES")
    buy_no = sum(1 for s in signals if s.direction == "BUY_NO")
    hold = sum(1 for s in signals if s.direction == "HOLD")

    return APIResponse(success=True, data={
        "session_id": session_id,
        "signal_count": len(signals),
        "summary": f"{buy_yes} BUY_YES, {buy_no} BUY_NO, {hold} HOLD",
        "signals": [
            {
                "contract_id": s.contract_id,
                "contract_question": s.contract_question,
                "market_price": s.market_price,
                "engine_probability": s.engine_probability,
                "alpha": s.alpha,
                "direction": s.direction,
                "strength": s.strength,
                "strength_score": s.strength_score,
                "confidence": s.confidence,
                "supporting_agents": s.supporting_agents,
                "opposing_agents": s.opposing_agents,
                "reasoning": s.reasoning,
            }
            for s in signals
        ],
    })


@router.get("/signals/history", response_model=APIResponse)
async def get_signal_history(
    session_id: str = Query(...),
    limit: int = Query(default=50, le=200),
) -> APIResponse:
    """Retrieve persisted prediction signals for a session."""
    from backend.app.utils.db import get_db

    try:
        async with get_db() as db:
            cursor = await db.execute(
                """SELECT contract_id, contract_question, market_price,
                          engine_probability, alpha, direction, strength,
                          strength_score, confidence, supporting_agents,
                          opposing_agents, reasoning, created_at
                   FROM prediction_signals
                   WHERE session_id = ?
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (session_id, limit),
            )
            rows = await cursor.fetchall()
    except Exception:
        return APIResponse(success=True, data=[])

    return APIResponse(success=True, data=[
        {
            "contract_id": r[0],
            "contract_question": r[1],
            "market_price": r[2],
            "engine_probability": r[3],
            "alpha": r[4],
            "direction": r[5],
            "strength": r[6],
            "strength_score": r[7],
            "confidence": r[8],
            "supporting_agents": r[9],
            "opposing_agents": r[10],
            "reasoning": r[11],
            "created_at": r[12],
        }
        for r in rows
    ])
