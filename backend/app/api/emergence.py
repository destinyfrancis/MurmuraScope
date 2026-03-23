"""Emergence Validation Framework API endpoints.

Provides endpoints for bias probing, phase transition alerts,
and emergence scorecards for simulation sessions.
"""

from __future__ import annotations

import aiosqlite
from fastapi import APIRouter, HTTPException

from backend.app.models.response import APIResponse
from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

router = APIRouter(prefix="/simulation", tags=["emergence"])
logger = get_logger("api.emergence")


@router.get("/{session_id}/emergence/bias-probe", response_model=APIResponse)
async def get_bias_probe(session_id: str) -> APIResponse:
    """Get BiasProbe results for a session.

    Returns a list of bias probe results (may be empty if no probe
    has been run yet).
    """
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, session_id, scenario, sample_size, agreement_rate, "
            "stance_kurtosis, persona_compliance, diversity_index, "
            "bias_detected, details_json, created_at "
            "FROM bias_probe_results WHERE session_id = ? "
            "ORDER BY created_at DESC",
            (session_id,),
        )
        rows = await cursor.fetchall()
        return APIResponse(success=True, data=[dict(r) for r in rows])


@router.get("/{session_id}/emergence/alerts", response_model=APIResponse)
async def get_emergence_alerts(
    session_id: str,
    severity: str | None = None,
) -> APIResponse:
    """Get phase transition alerts, optionally filtered by severity.

    Args:
        session_id: Simulation session UUID.
        severity: Optional filter -- ``'warning'`` or ``'critical'``.
    """
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        if severity is not None:
            cursor = await db.execute(
                "SELECT id, session_id, round_number, metric_name, "
                "z_score, delta, direction, severity, created_at "
                "FROM emergence_alerts "
                "WHERE session_id = ? AND severity = ? "
                "ORDER BY round_number ASC",
                (session_id, severity),
            )
        else:
            cursor = await db.execute(
                "SELECT id, session_id, round_number, metric_name, "
                "z_score, delta, direction, severity, created_at "
                "FROM emergence_alerts WHERE session_id = ? "
                "ORDER BY round_number ASC",
                (session_id,),
            )
        rows = await cursor.fetchall()
        return APIResponse(success=True, data=[dict(r) for r in rows])


@router.get("/{session_id}/emergence/scorecard", response_model=APIResponse)
async def get_emergence_scorecard(session_id: str) -> APIResponse:
    """Get emergence scorecard for a completed simulation.

    Returns 404 if no scorecard exists for the given session.
    """
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, session_id, max_cascade_depth, cascade_count, "
            "avg_cascade_breadth, polarization_delta, "
            "echo_chamber_count_delta, opinion_entropy_trend, "
            "stance_bimodality_p, emergence_ratio, "
            "bias_contamination, transition_count, grade, "
            "details_json, created_at "
            "FROM emergence_scorecards WHERE session_id = ?",
            (session_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"No emergence scorecard found for session {session_id}",
            )
        return APIResponse(success=True, data=dict(row))


@router.post("/{session_id}/emergence/run-bias-probe", response_model=APIResponse)
async def run_bias_probe(session_id: str, sample_size: int = 30) -> APIResponse:
    """Trigger a manual bias probe run.

    Runs a BiasProbe against the specified session's agents and returns
    the result.  Note: this is a potentially slow operation as it makes
    LLM calls for each sampled agent.

    Args:
        session_id: Simulation session UUID.
        sample_size: Number of agents to sample (default 30).
    """
    from backend.app.services.emergence_guards import BiasProbe

    probe = BiasProbe()
    result = await probe.probe(session_id, sample_size=sample_size)
    return APIResponse(
        success=True,
        data={
            "session_id": result.session_id,
            "scenario": result.scenario,
            "agreement_rate": result.agreement_rate,
            "persona_compliance": result.persona_compliance,
            "bias_detected": result.bias_detected,
            "diversity_index": result.diversity_index,
        },
    )
