"""Comment system for simulation predictions.

POST   /simulation/{session_id}/comments              — add comment
GET    /simulation/{session_id}/comments              — list comments
DELETE /simulation/{session_id}/comments/{comment_id} — delete own comment
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from backend.app.models.response import APIResponse
from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

router = APIRouter(prefix="/simulation", tags=["comments"])
logger = get_logger("api.comments")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class CreateCommentRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    content: str
    user_id: str | None = None
    quote_text: str | None = None


# ---------------------------------------------------------------------------
# POST /simulation/{session_id}/comments — add comment
# ---------------------------------------------------------------------------

@router.post("/{session_id}/comments", response_model=APIResponse)
async def create_comment(session_id: str, req: CreateCommentRequest) -> APIResponse:
    if not req.content.strip():
        raise HTTPException(status_code=400, detail="Comment content cannot be empty")

    async with get_db() as db:
        # Verify session exists
        cursor = await db.execute(
            "SELECT id FROM simulation_sessions WHERE id = ?",
            (session_id,),
        )
        sess_row = await cursor.fetchone()
        if sess_row is None:
            raise HTTPException(status_code=404, detail="Session not found")

        cursor = await db.execute(
            """INSERT INTO prediction_comments (session_id, user_id, content, quote_text)
               VALUES (?, ?, ?, ?)""",
            (session_id, req.user_id, req.content.strip(), req.quote_text),
        )
        comment_id = cursor.lastrowid
        await db.commit()

        # Fetch the created comment to return full data
        cursor = await db.execute(
            """SELECT id, session_id, user_id, content, quote_text, created_at
               FROM prediction_comments WHERE id = ?""",
            (comment_id,),
        )
        row = await cursor.fetchone()

    comment = {
        "id": row["id"],
        "session_id": row["session_id"],
        "user_id": row["user_id"],
        "content": row["content"],
        "quote_text": row["quote_text"],
        "created_at": row["created_at"],
    }
    logger.info("Comment %d added to session %s", comment_id, session_id)
    return APIResponse(success=True, data=comment)


# ---------------------------------------------------------------------------
# GET /simulation/{session_id}/comments — list comments
# ---------------------------------------------------------------------------

@router.get("/{session_id}/comments", response_model=APIResponse)
async def list_comments(session_id: str) -> APIResponse:
    async with get_db() as db:
        # Verify session exists
        cursor = await db.execute(
            "SELECT id FROM simulation_sessions WHERE id = ?",
            (session_id,),
        )
        sess_row = await cursor.fetchone()
        if sess_row is None:
            raise HTTPException(status_code=404, detail="Session not found")

        cursor = await db.execute(
            """SELECT id, session_id, user_id, content, quote_text, created_at
               FROM prediction_comments
               WHERE session_id = ?
               ORDER BY created_at ASC""",
            (session_id,),
        )
        rows = await cursor.fetchall()

    comments = [
        {
            "id": r["id"],
            "session_id": r["session_id"],
            "user_id": r["user_id"],
            "content": r["content"],
            "quote_text": r["quote_text"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]
    return APIResponse(success=True, data=comments, meta={"count": len(comments)})


# ---------------------------------------------------------------------------
# DELETE /simulation/{session_id}/comments/{comment_id} — delete own comment
# ---------------------------------------------------------------------------

@router.delete("/{session_id}/comments/{comment_id}", response_model=APIResponse)
async def delete_comment(
    session_id: str,
    comment_id: int,
    user_id: str | None = None,
) -> APIResponse:
    async with get_db() as db:
        cursor = await db.execute(
            """SELECT id, user_id FROM prediction_comments
               WHERE id = ? AND session_id = ?""",
            (comment_id, session_id),
        )
        row = await cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Comment not found")

        # If user_id provided, verify ownership (soft auth)
        comment_owner = row["user_id"]
        if user_id is not None and comment_owner is not None and user_id != comment_owner:
            raise HTTPException(status_code=403, detail="Cannot delete another user's comment")

        await db.execute(
            "DELETE FROM prediction_comments WHERE id = ? AND session_id = ?",
            (comment_id, session_id),
        )
        await db.commit()

    logger.info("Deleted comment %d from session %s", comment_id, session_id)
    return APIResponse(success=True, data={"deleted_comment_id": comment_id})
