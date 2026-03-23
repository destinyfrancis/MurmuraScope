"""Workspace endpoints for collaborative prediction sharing.

POST /workspace            — create a workspace
GET  /workspace/{id}       — get workspace details + members
POST /workspace/{id}/invite — invite a user by email
GET  /workspace/{id}/predictions — list sessions shared in workspace
POST /workspace/{id}/sessions/{session_id} — add session to workspace
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from backend.app.api.auth import UserProfile, get_current_user
from backend.app.models.response import APIResponse
from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

router = APIRouter(prefix="/workspace", tags=["workspace"])
logger = get_logger("api.workspace")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class CreateWorkspaceRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    description: str = ""


class InviteRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    email: str
    role: str = "viewer"


# ---------------------------------------------------------------------------
# POST /workspace — create workspace
# ---------------------------------------------------------------------------


@router.post("", response_model=APIResponse)
async def create_workspace(
    req: CreateWorkspaceRequest,
    user: Annotated[UserProfile, Depends(get_current_user)],
) -> APIResponse:
    workspace_id = uuid.uuid4().hex
    try:
        async with get_db() as db:
            await db.execute(
                """INSERT INTO workspaces (id, name, description, owner_id)
                   VALUES (?, ?, ?, ?)""",
                (workspace_id, req.name, req.description, user.id),
            )
            # Auto-add owner as admin member
            await db.execute(
                """INSERT INTO workspace_members (workspace_id, user_id, role)
                   VALUES (?, ?, 'admin')""",
                (workspace_id, user.id),
            )
            await db.commit()
    except Exception as exc:
        logger.error("Failed to create workspace: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to create workspace") from exc

    logger.info("Created workspace %s: %s by user %s", workspace_id, req.name, user.id)
    return APIResponse(
        success=True,
        data={
            "id": workspace_id,
            "name": req.name,
            "description": req.description,
            "owner_id": user.id,
        },
    )


# ---------------------------------------------------------------------------
# GET /workspace/{id} — get workspace + members
# ---------------------------------------------------------------------------


@router.get("/{workspace_id}", response_model=APIResponse)
async def get_workspace(
    workspace_id: str,
    user: Annotated[UserProfile, Depends(get_current_user)],
) -> APIResponse:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, name, description, owner_id, created_at FROM workspaces WHERE id = ?",
            (workspace_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Workspace not found")

        # Verify the caller is a member (or the owner)
        cursor = await db.execute(
            "SELECT role FROM workspace_members WHERE workspace_id = ? AND user_id = ?",
            (workspace_id, user.id),
        )
        member_row = await cursor.fetchone()
        if member_row is None and row["owner_id"] != user.id:
            raise HTTPException(status_code=403, detail="Access denied")

        cursor = await db.execute(
            """SELECT user_id, role, joined_at
               FROM workspace_members
               WHERE workspace_id = ?
               ORDER BY joined_at""",
            (workspace_id,),
        )
        members_rows = await cursor.fetchall()

    workspace = {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "owner_id": row["owner_id"],
        "created_at": row["created_at"],
        "members": [{"user_id": m["user_id"], "role": m["role"], "joined_at": m["joined_at"]} for m in members_rows],
    }
    return APIResponse(success=True, data=workspace)


# ---------------------------------------------------------------------------
# POST /workspace/{id}/invite — invite user by email
# ---------------------------------------------------------------------------


@router.post("/{workspace_id}/invite", response_model=APIResponse)
async def invite_to_workspace(
    workspace_id: str,
    req: InviteRequest,
    user: Annotated[UserProfile, Depends(get_current_user)],
) -> APIResponse:
    if req.role not in ("viewer", "editor", "admin"):
        raise HTTPException(status_code=400, detail="Invalid role. Must be viewer, editor, or admin")

    async with get_db() as db:
        # Verify workspace exists and check caller is admin/owner
        cursor = await db.execute(
            "SELECT id, owner_id FROM workspaces WHERE id = ?",
            (workspace_id,),
        )
        ws_row = await cursor.fetchone()
        if ws_row is None:
            raise HTTPException(status_code=404, detail="Workspace not found")

        # Check caller has admin role or is the owner
        cursor = await db.execute(
            "SELECT role FROM workspace_members WHERE workspace_id = ? AND user_id = ?",
            (workspace_id, user.id),
        )
        caller_member = await cursor.fetchone()
        is_owner = ws_row["owner_id"] == user.id
        is_admin = caller_member is not None and caller_member["role"] == "admin"
        if not is_owner and not is_admin:
            raise HTTPException(status_code=403, detail="Only workspace admins can invite members")

        # Resolve invite target: look up user by email, fall back to email as placeholder
        cursor = await db.execute(
            "SELECT id FROM users WHERE email = ?",
            (req.email,),
        )
        invite_user_row = await cursor.fetchone()
        invited_user_id = invite_user_row["id"] if invite_user_row else req.email

        try:
            await db.execute(
                """INSERT INTO workspace_members (workspace_id, user_id, role)
                   VALUES (?, ?, ?)""",
                (workspace_id, invited_user_id, req.role),
            )
            await db.commit()
        except Exception as exc:
            # Likely UNIQUE constraint — user already a member
            logger.warning("Invite failed (already member?): %s", exc)
            raise HTTPException(
                status_code=409,
                detail="User is already a member of this workspace",
            ) from exc

    logger.info("Invited %s to workspace %s as %s (by %s)", req.email, workspace_id, req.role, user.id)
    return APIResponse(
        success=True,
        data={"workspace_id": workspace_id, "user_id": invited_user_id, "role": req.role},
    )


# ---------------------------------------------------------------------------
# GET /workspace/{id}/predictions — shared sessions in workspace
# ---------------------------------------------------------------------------


@router.get("/{workspace_id}/predictions", response_model=APIResponse)
async def get_workspace_predictions(
    workspace_id: str,
    user: Annotated[UserProfile, Depends(get_current_user)],
) -> APIResponse:
    async with get_db() as db:
        # Verify workspace exists
        cursor = await db.execute(
            "SELECT id, owner_id FROM workspaces WHERE id = ?",
            (workspace_id,),
        )
        ws_row = await cursor.fetchone()
        if ws_row is None:
            raise HTTPException(status_code=404, detail="Workspace not found")

        # Verify membership
        cursor = await db.execute(
            "SELECT role FROM workspace_members WHERE workspace_id = ? AND user_id = ?",
            (workspace_id, user.id),
        )
        member_row = await cursor.fetchone()
        if member_row is None and ws_row["owner_id"] != user.id:
            raise HTTPException(status_code=403, detail="Access denied")

        cursor = await db.execute(
            """SELECT s.id, s.name, s.scenario_type, s.status,
                      s.agent_count, s.round_count, s.created_at,
                      ws.added_at
               FROM workspace_sessions ws
               JOIN simulation_sessions s ON s.id = ws.session_id
               WHERE ws.workspace_id = ?
               ORDER BY ws.added_at DESC""",
            (workspace_id,),
        )
        rows = await cursor.fetchall()

    sessions = [
        {
            "session_id": r["id"],
            "name": r["name"],
            "scenario_type": r["scenario_type"],
            "status": r["status"],
            "agent_count": r["agent_count"],
            "round_count": r["round_count"],
            "created_at": r["created_at"],
            "added_at": r["added_at"],
        }
        for r in rows
    ]
    return APIResponse(success=True, data=sessions)


# ---------------------------------------------------------------------------
# POST /workspace/{id}/sessions/{session_id} — add session to workspace
# ---------------------------------------------------------------------------


@router.post("/{workspace_id}/sessions/{session_id}", response_model=APIResponse)
async def add_session_to_workspace(
    workspace_id: str,
    session_id: str,
    user: Annotated[UserProfile, Depends(get_current_user)],
) -> APIResponse:
    async with get_db() as db:
        # Verify workspace exists
        cursor = await db.execute(
            "SELECT id, owner_id FROM workspaces WHERE id = ?",
            (workspace_id,),
        )
        ws_row = await cursor.fetchone()
        if ws_row is None:
            raise HTTPException(status_code=404, detail="Workspace not found")

        # Verify caller has at least editor role (or is owner)
        cursor = await db.execute(
            "SELECT role FROM workspace_members WHERE workspace_id = ? AND user_id = ?",
            (workspace_id, user.id),
        )
        caller_member = await cursor.fetchone()
        is_owner = ws_row["owner_id"] == user.id
        caller_role = caller_member["role"] if caller_member else None
        if not is_owner and caller_role not in ("editor", "admin"):
            raise HTTPException(status_code=403, detail="Editor or admin role required to add sessions")

        # Verify session exists
        cursor = await db.execute(
            "SELECT id FROM simulation_sessions WHERE id = ?",
            (session_id,),
        )
        sess_row = await cursor.fetchone()
        if sess_row is None:
            raise HTTPException(status_code=404, detail="Session not found")

        try:
            await db.execute(
                """INSERT INTO workspace_sessions (workspace_id, session_id)
                   VALUES (?, ?)""",
                (workspace_id, session_id),
            )
            await db.commit()
        except Exception as exc:
            logger.warning("Session already in workspace: %s", exc)
            raise HTTPException(
                status_code=409,
                detail="Session is already in this workspace",
            ) from exc

    logger.info("Added session %s to workspace %s", session_id, workspace_id)
    return APIResponse(
        success=True,
        data={"workspace_id": workspace_id, "session_id": session_id},
    )
