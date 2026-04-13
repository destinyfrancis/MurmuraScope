"""API endpoints for agent interviews post-simulation (Phase 6)."""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, HTTPException, Path, Body

from backend.app.models.response import APIResponse
from backend.app.services.interview_engine import InterviewEngine
from backend.app.utils.logger import get_logger

router = APIRouter(prefix="/simulation", tags=["simulation-interview"])
logger = get_logger("api.interview")

@router.post("/{session_id}/agents/{agent_id}/interview", response_model=APIResponse)
async def interview_agent(
    session_id: str = Path(..., pattern=r"^[a-f0-9\-]{8,36}$"),
    agent_id: str = Path(...),
    query: str = Body(..., embed=True),
) -> APIResponse:
    """Send a query to an agent and get an in-character response."""
    try:
        engine = InterviewEngine()
        response = await engine.generate_response(session_id, agent_id, query)
        return APIResponse(
            success=True,
            data={"response": response},
            meta={"session_id": session_id, "agent_id": agent_id}
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.exception("interview_agent failed for session %s agent %s", session_id, agent_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc

@router.get("/{session_id}/agents/{agent_id}/interview/history", response_model=APIResponse)
async def get_interview_history(
    session_id: str = Path(..., pattern=r"^[a-f0-9\-]{8,36}$"),
    agent_id: str = Path(...),
) -> APIResponse:
    """Retrieve the conversation history for a specific agent interview."""
    try:
        engine = InterviewEngine()
        history = await engine.get_history(session_id, agent_id)
        return APIResponse(
            success=True,
            data={"history": history},
            meta={"session_id": session_id, "agent_id": agent_id, "count": len(history)}
        )
    except Exception as exc:
        logger.exception("get_interview_history failed for session %s agent %s", session_id, agent_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc
