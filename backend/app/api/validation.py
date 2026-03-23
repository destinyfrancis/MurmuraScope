"""Validation confidence API."""

from __future__ import annotations

from fastapi import APIRouter

from backend.app.services.validation_suite import synthesize_confidence
from backend.app.utils.db import get_db

router = APIRouter(prefix="/validation", tags=["validation"])


@router.get("/{session_id}")
async def get_validation(session_id: str) -> dict:
    """Synthesize confidence for a simulation session."""
    async with get_db() as db:
        # Fetch MC ensemble results
        cursor = await db.execute(
            "SELECT p25, p75, median FROM ensemble_results WHERE session_id=? ORDER BY id DESC LIMIT 1",
            (session_id,),
        )
        mc_row = await cursor.fetchone()

        # Fetch Theil's U from validation if available
        cursor2 = await db.execute(
            "SELECT theils_u FROM ensemble_results "
            "WHERE session_id=? AND theils_u IS NOT NULL ORDER BY id DESC LIMIT 1",
            (session_id,),
        )
        theils_row = await cursor2.fetchone()

        # Compute agent consensus from decisions
        cursor3 = await db.execute(
            "SELECT COUNT(*), COUNT(DISTINCT action) FROM agent_decisions WHERE session_id=?",
            (session_id,),
        )
        consensus_row = await cursor3.fetchone()

    mc_p25 = mc_row[0] if mc_row else 90
    mc_p75 = mc_row[1] if mc_row else 110
    mc_median = mc_row[2] if mc_row else 100
    theils_u = theils_row[0] if theils_row else 0.85

    total_decisions = consensus_row[0] if consensus_row else 1
    distinct_actions = consensus_row[1] if consensus_row else 1
    agent_consensus = 1.0 - (distinct_actions / max(total_decisions, 1))

    result = synthesize_confidence(
        theils_u=theils_u,
        mc_p25=mc_p25,
        mc_p75=mc_p75,
        mc_median=mc_median,
        agent_consensus=min(agent_consensus, 1.0),
    )
    return result.model_dump()
