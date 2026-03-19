"""Step 4-5: Report generation and chat endpoints."""

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel as _BaseModel

from backend.app.models.request import (
    AgentInterviewRequest,
    ReportChatRequest,
    ReportGenerateRequest,
)
from backend.app.models.response import APIResponse
from backend.app.services.report_agent import ReportAgent
from backend.app.services.simulation_ipc import SimulationIPC
from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

_CHAT_AGENT_SYSTEM = """You are roleplaying as a Hong Kong resident agent in a social simulation.
Stay in character based on your demographic profile, personality, and memories.
Answer in Traditional Chinese (繁體中文) mixed with Cantonese colloquialisms where appropriate.
Reference your memories and recent actions when relevant."""

router = APIRouter(prefix="/report", tags=["report"])
logger = get_logger("api.report")


@router.get("/public/{token}", response_model=APIResponse)
async def get_public_report(token: str) -> APIResponse:
    """Retrieve a report by its public share token (read-only)."""
    try:
        async with get_db() as db:
            try:
                cursor = await db.execute("SELECT * FROM reports WHERE share_token = ?", (token,))
                row = await cursor.fetchone()
            except Exception:
                raise HTTPException(status_code=404, detail="Report sharing not available")
        if not row:
            raise HTTPException(status_code=404, detail="Report not found or link expired")
        report = {
            "report_id": row["id"],
            "session_id": row["session_id"],
            "report_type": row["report_type"],
            "title": row["title"],
            "content_markdown": row["content_markdown"],
            "summary": row["summary"],
            "key_findings": json.loads(row["key_findings"]) if row["key_findings"] else [],
            "charts_data": json.loads(row["charts_data"]) if row["charts_data"] else None,
            "created_at": row["created_at"],
        }
        return APIResponse(success=True, data=report)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("get_public_report failed for token %s", token)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/generate", response_model=APIResponse)
async def generate_report(req: ReportGenerateRequest) -> APIResponse:
    """Generate an analysis report from a completed simulation."""
    try:
        agent = ReportAgent()
        report = await agent.generate_report(
            session_id=req.session_id,
            report_type=req.report_type,
            focus_areas=req.focus_areas or [],
            scenario_question=req.scenario_question,
        )
        return APIResponse(
            success=True,
            data=report,
            meta={
                "session_id": req.session_id,
                "report_type": req.report_type,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("generate_report failed for session %s", req.session_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{report_id}", response_model=APIResponse)
async def get_report(report_id: str) -> APIResponse:
    """Retrieve a previously generated report."""
    try:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT * FROM reports WHERE id = ?", (report_id,)
            )
            row = await cursor.fetchone()

        if row is None:
            raise HTTPException(
                status_code=404, detail=f"Report {report_id} not found"
            )

        report = {
            "report_id": row["id"],
            "session_id": row["session_id"],
            "report_type": row["report_type"],
            "title": row["title"],
            "content_markdown": row["content_markdown"],
            "summary": row["summary"],
            "key_findings": json.loads(row["key_findings"]) if row["key_findings"] else [],
            "charts_data": json.loads(row["charts_data"]) if row["charts_data"] else None,
            "agent_log": json.loads(row["agent_log"]) if row.get("agent_log") else [],
            "created_at": row["created_at"],
        }
        return APIResponse(success=True, data=report)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("get_report failed for report %s", report_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/chat", response_model=APIResponse)
async def chat_with_report(req: ReportChatRequest) -> APIResponse:
    """Chat with the report agent for follow-up analysis."""
    try:
        agent = ReportAgent()
        reply = await agent.chat(
            session_id=req.session_id,
            message=req.message,
        )
        return APIResponse(
            success=True,
            data={
                "session_id": req.session_id,
                "agent_id": req.agent_id,
                "user_message": req.message,
                "reply": reply,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("chat_with_report failed for session %s", req.session_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/interview", response_model=APIResponse)
async def interview_agent(req: AgentInterviewRequest) -> APIResponse:
    """Interview a specific agent about their decisions.

    Enriches the prompt with agent memories and recent actions for realism.
    """
    try:
        # Load agent profile
        async with get_db() as db:
            profile_row = await (
                await db.execute(
                    "SELECT * FROM agent_profiles WHERE id = ? AND session_id = ?",
                    (req.agent_id, req.session_id),
                )
            ).fetchone()

        profile_ctx = ""
        if profile_row:
            profile_ctx = (
                f"姓名：{profile_row.get('username', '未知')}\n"
                f"年齡：{profile_row.get('age', '?')} 歲\n"
                f"職業：{profile_row.get('occupation', '?')}\n"
                f"地區：{profile_row.get('district', '?')}\n"
                f"性格：{profile_row.get('user_char', '')[:200]}\n"
            )

        # Load recent memories
        memory_ctx = ""
        try:
            async with get_db() as db:
                mem_rows = await (
                    await db.execute(
                        """SELECT memory_text, salience_score
                           FROM agent_memories
                           WHERE session_id = ? AND agent_id = ?
                           ORDER BY salience_score DESC LIMIT 5""",
                        (req.session_id, req.agent_id),
                    )
                ).fetchall()
            if mem_rows:
                memory_ctx = "近期記憶：\n" + "\n".join(
                    f"- {r['memory_text']}" for r in mem_rows
                )
        except Exception:
            logger.debug("Could not load memories for agent %d", req.agent_id)

        # Load recent actions
        action_ctx = ""
        try:
            async with get_db() as db:
                action_rows = await (
                    await db.execute(
                        """SELECT content, sentiment, round_number
                           FROM simulation_actions
                           WHERE session_id = ? AND agent_id = ?
                           ORDER BY round_number DESC LIMIT 5""",
                        (req.session_id, req.agent_id),
                    )
                ).fetchall()
            if action_rows:
                action_ctx = "最近發帖：\n" + "\n".join(
                    f"- [第{r['round_number']}輪/{r['sentiment']}] {r['content'][:100]}"
                    for r in action_rows
                )
        except Exception:
            logger.debug("Could not load actions for agent %d", req.agent_id)

        # Build enriched system prompt
        enriched_system = _CHAT_AGENT_SYSTEM
        if profile_ctx or memory_ctx or action_ctx:
            enriched_system += (
                f"\n\n你的角色資料：\n{profile_ctx}"
                f"\n{memory_ctx}\n{action_ctx}"
            )

        # Call LLM with enriched context
        from backend.app.services.report_agent import _call_llm  # noqa: PLC0415

        messages = [{"role": "user", "content": req.question}]
        answer = await _call_llm(messages, enriched_system)

        return APIResponse(
            success=True,
            data={
                "session_id": req.session_id,
                "agent_id": req.agent_id,
                "question": req.question,
                "answer": answer,
                "response": answer,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "interview_agent failed for agent %d session %s",
            req.agent_id,
            req.session_id,
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{report_id}/pdf")
async def export_report_pdf(report_id: str):
    """Export report as PDF"""
    import io
    import re
    try:
        from weasyprint import HTML
    except ImportError:
        raise HTTPException(status_code=500, detail="weasyprint not installed")

    try:
        async with get_db() as db:
            cursor = await db.execute("SELECT * FROM reports WHERE id = ?", (report_id,))
            row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Report not found")

        report = dict(row)
        content = report.get("content_markdown") or report.get("content", "")
        title = report.get("title", f"Report {report_id}")
        created_at = report.get("created_at", "")

        # Convert markdown to basic HTML
        html_content = content.replace("\n\n", "</p><p>").replace("\n", "<br>")
        html_content = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", html_content)
        html_content = re.sub(r"#{1,3} (.+)", r"<h2>\1</h2>", html_content)

        html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body {{ font-family: 'Noto Sans TC', sans-serif; margin: 40px; color: #333; }}
  h1 {{ color: #1a1a2e; border-bottom: 2px solid #e94560; padding-bottom: 10px; }}
  h2 {{ color: #16213e; margin-top: 24px; }}
  p {{ line-height: 1.6; }}
  .meta {{ color: #666; font-size: 0.9em; margin-bottom: 24px; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="meta">生成時間：{created_at} | Session: {report_id}</div>
<p>{html_content}</p>
</body>
</html>"""

        pdf_bytes = HTML(string=html).write_pdf()

        from fastapi.responses import Response  # noqa: PLC0415
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=report-{report_id}.pdf"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("export_report_pdf failed for report %s", report_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{report_id}/share", response_model=APIResponse)
async def share_report(report_id: str) -> APIResponse:
    """Generate a share token for public access to a report."""
    import secrets
    try:
        token = secrets.token_urlsafe(16)
        async with get_db() as db:
            row = await (await db.execute("SELECT id FROM reports WHERE id = ?", (report_id,))).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"Report {report_id} not found")
            # Ensure share_token column exists (runtime migration)
            try:
                await db.execute("ALTER TABLE reports ADD COLUMN share_token TEXT")
            except Exception:
                pass  # Column already exists
            await db.execute("UPDATE reports SET share_token = ? WHERE id = ?", (token, report_id))
            await db.commit()
        return APIResponse(
            success=True,
            data={"token": token, "url": f"/public/report/{token}"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("share_report failed for report %s", report_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# XAI tool interactive endpoint
# ---------------------------------------------------------------------------

class XAIToolRequest(_BaseModel):
    tool_name: str
    params: dict = {}


@router.post("/{session_id}/xai-tool", response_model=APIResponse)
async def invoke_xai_tool(session_id: str, req: XAIToolRequest) -> APIResponse:
    """Invoke a single named XAI tool and return its output."""
    from backend.app.services.report_agent import TOOLS, _TOOL_HANDLERS

    if req.tool_name not in TOOLS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown tool: {req.tool_name!r}. Available: {list(TOOLS.keys())}",
        )
    handler = _TOOL_HANDLERS.get(req.tool_name)
    if handler is None:
        raise HTTPException(
            status_code=501,
            detail=f"No handler registered for tool {req.tool_name!r}",
        )
    try:
        result = await handler(session_id, **req.params)
        return APIResponse(success=True, data={"tool": req.tool_name, "result": result})
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("invoke_xai_tool failed: tool=%s session=%s", req.tool_name, session_id)
        return APIResponse(success=False, data=None, error=str(exc))
