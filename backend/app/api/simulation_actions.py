"""Phase 18 API endpoints for Layer 1-4 agent action space.

Provides read-only query endpoints for:
- Agent groups (collective organisation)
- Collective actions and momentum
- Attention allocation per agent
- Wealth transfers
- Fact-check results
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

router = APIRouter(prefix="/simulation", tags=["simulation-actions"])
logger = get_logger("api.simulation_actions")


# ---------------------------------------------------------------------------
# Agent Groups
# ---------------------------------------------------------------------------

@router.get("/{session_id}/groups")
async def list_groups(
    session_id: str,
    status: str | None = Query(None, description="Filter by status: active|dissolved|succeeded"),
) -> list[dict[str, Any]]:
    """List agent groups for a simulation session.

    Args:
        session_id: Simulation session UUID.
        status: Optional status filter.

    Returns:
        List of group records.
    """
    try:
        async with get_db() as db:
            if status:
                cursor = await db.execute(
                    """
                    SELECT id, group_name, agenda, leader_agent_id,
                           member_count, shared_resources, formed_round, status, created_at
                    FROM agent_groups
                    WHERE session_id = ? AND status = ?
                    ORDER BY formed_round DESC
                    """,
                    (session_id, status),
                )
            else:
                cursor = await db.execute(
                    """
                    SELECT id, group_name, agenda, leader_agent_id,
                           member_count, shared_resources, formed_round, status, created_at
                    FROM agent_groups
                    WHERE session_id = ?
                    ORDER BY formed_round DESC
                    """,
                    (session_id,),
                )
            rows = await cursor.fetchall()
    except Exception as exc:
        logger.exception("list_groups failed session=%s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc

    return [dict(row) for row in rows]


@router.get("/{session_id}/groups/{group_id}/members")
async def get_group_members(
    session_id: str,
    group_id: int,
) -> list[dict[str, Any]]:
    """List members of a specific agent group.

    Args:
        session_id: Simulation session UUID.
        group_id: Group ID.

    Returns:
        List of agent member records with profile details.
    """
    try:
        async with get_db() as db:
            # Verify group belongs to session
            cursor = await db.execute(
                "SELECT id FROM agent_groups WHERE id = ? AND session_id = ?",
                (group_id, session_id),
            )
            if not await cursor.fetchone():
                raise HTTPException(status_code=404, detail="Group not found")

            cursor = await db.execute(
                """
                SELECT agm.agent_id, agm.joined_round,
                       ap.age, ap.sex, ap.district, ap.occupation,
                       ap.monthly_income, ap.political_stance, ap.extraversion
                FROM agent_group_members agm
                LEFT JOIN agent_profiles ap
                    ON ap.id = agm.agent_id AND ap.session_id = agm.session_id
                WHERE agm.session_id = ? AND agm.group_id = ?
                ORDER BY agm.joined_round
                """,
                (session_id, group_id),
            )
            rows = await cursor.fetchall()
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("get_group_members failed session=%s group=%d", session_id, group_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc

    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Collective Actions
# ---------------------------------------------------------------------------

@router.get("/{session_id}/collective-actions")
async def list_collective_actions(
    session_id: str,
    status: str | None = Query(None, description="Filter: building|active|succeeded|failed"),
) -> list[dict[str, Any]]:
    """List collective actions for a simulation session.

    Args:
        session_id: Simulation session UUID.
        status: Optional status filter.

    Returns:
        List of collective action records ordered by round (newest first).
    """
    try:
        async with get_db() as db:
            if status:
                cursor = await db.execute(
                    """
                    SELECT id, group_id, initiator_agent_id, action_type, target,
                           participant_count, momentum, round_initiated, status, created_at
                    FROM collective_actions
                    WHERE session_id = ? AND status = ?
                    ORDER BY round_initiated DESC
                    """,
                    (session_id, status),
                )
            else:
                cursor = await db.execute(
                    """
                    SELECT id, group_id, initiator_agent_id, action_type, target,
                           participant_count, momentum, round_initiated, status, created_at
                    FROM collective_actions
                    WHERE session_id = ?
                    ORDER BY round_initiated DESC
                    """,
                    (session_id,),
                )
            rows = await cursor.fetchall()
    except Exception as exc:
        logger.exception("list_collective_actions failed session=%s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc

    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Attention Allocation
# ---------------------------------------------------------------------------

@router.get("/{session_id}/attention/{agent_id}")
async def get_agent_attention(
    session_id: str,
    agent_id: int,
    round_number: int | None = Query(None, description="Filter by round (default: latest)"),
) -> list[dict[str, Any]]:
    """Get attention allocation for an agent in a specific round.

    Args:
        session_id: Simulation session UUID.
        agent_id: Agent ID.
        round_number: Optional round filter (defaults to latest round).

    Returns:
        List of topic attention records (topic, points_spent, sensitivity).
    """
    try:
        async with get_db() as db:
            if round_number is not None:
                cursor = await db.execute(
                    """
                    SELECT topic, points_spent, sensitivity, round_number
                    FROM agent_attention
                    WHERE session_id = ? AND agent_id = ? AND round_number = ?
                    ORDER BY points_spent DESC
                    """,
                    (session_id, agent_id, round_number),
                )
            else:
                # Latest round
                cursor = await db.execute(
                    """
                    SELECT topic, points_spent, sensitivity, round_number
                    FROM agent_attention
                    WHERE session_id = ? AND agent_id = ?
                    ORDER BY round_number DESC, points_spent DESC
                    LIMIT 20
                    """,
                    (session_id, agent_id),
                )
            rows = await cursor.fetchall()
    except Exception as exc:
        logger.exception(
            "get_agent_attention failed session=%s agent=%d", session_id, agent_id
        )
        logger.exception("Internal error in get_agent_attention")
        raise HTTPException(status_code=500, detail="Internal server error") from exc

    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Wealth Transfers
# ---------------------------------------------------------------------------

@router.get("/{session_id}/wealth-transfers")
async def list_wealth_transfers(
    session_id: str,
    round_number: int | None = Query(None, description="Filter by specific round"),
    limit: int = Query(100, ge=1, le=1000),
) -> list[dict[str, Any]]:
    """List wealth transfer events for a simulation session.

    Args:
        session_id: Simulation session UUID.
        round_number: Optional round filter.
        limit: Maximum records to return.

    Returns:
        List of wealth transfer records.
    """
    try:
        async with get_db() as db:
            if round_number is not None:
                cursor = await db.execute(
                    """
                    SELECT id, from_agent_id, to_agent_id, to_entity,
                           amount, reason, round_number, created_at
                    FROM wealth_transfers
                    WHERE session_id = ? AND round_number = ?
                    ORDER BY amount DESC
                    LIMIT ?
                    """,
                    (session_id, round_number, limit),
                )
            else:
                cursor = await db.execute(
                    """
                    SELECT id, from_agent_id, to_agent_id, to_entity,
                           amount, reason, round_number, created_at
                    FROM wealth_transfers
                    WHERE session_id = ?
                    ORDER BY round_number DESC, amount DESC
                    LIMIT ?
                    """,
                    (session_id, limit),
                )
            rows = await cursor.fetchall()
    except Exception as exc:
        logger.exception("list_wealth_transfers failed session=%s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc

    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Fact Checks
# ---------------------------------------------------------------------------

@router.get("/{session_id}/fact-checks")
async def list_fact_checks(
    session_id: str,
    round_number: int | None = Query(None, description="Filter by round"),
    verdict: str | None = Query(None, description="Filter: accurate|misleading|fabricated|unverifiable"),
    limit: int = Query(100, ge=1, le=1000),
) -> list[dict[str, Any]]:
    """List fact-check results for a simulation session.

    Args:
        session_id: Simulation session UUID.
        round_number: Optional round filter.
        verdict: Optional verdict filter.
        limit: Maximum records to return.

    Returns:
        List of fact-check records.
    """
    clauses = ["session_id = ?"]
    params: list[Any] = [session_id]

    if round_number is not None:
        clauses.append("round_number = ?")
        params.append(round_number)
    if verdict is not None:
        clauses.append("verdict = ?")
        params.append(verdict)

    where = " AND ".join(clauses)
    params.append(limit)

    try:
        async with get_db() as db:
            cursor = await db.execute(
                f"""
                SELECT id, checker_agent_id, post_id, verdict,
                       confidence, round_number, created_at
                FROM fact_checks
                WHERE {where}
                ORDER BY round_number DESC, confidence DESC
                LIMIT ?
                """,
                tuple(params),
            )
            rows = await cursor.fetchall()
    except Exception as exc:
        logger.exception("list_fact_checks failed session=%s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc

    return [dict(row) for row in rows]
