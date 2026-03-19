"""Simulation create, start, status, and agent-list endpoints.

All handlers delegate to real service implementations:
  POST /simulation/create  → AgentFactory + ProfileGenerator + MacroController
                             → write agents.csv → SimulationManager.create_session
  POST /simulation/start   → SimulationManager.start_session (background task)
  GET  /simulation/{id}    → SimulationManager.get_session (DB read)
  GET  /simulation/{id}/agents → SimulationManager.get_agents (DB read)
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile
from backend.app.api.auth import _limiter

from backend.app.models.request import (
    SimulationCreateRequest,
    SimulationStartRequest,
    ConfigSuggestRequest,
    ScheduledShock,
    _B2B_SCENARIO_KEYWORDS,
)
from backend.app.models.response import APIResponse
from backend.app.services.agent_factory import AgentFactory
from backend.app.services.company_factory import CompanyFactory
from backend.app.services.macro_controller import MacroController
from backend.app.services.profile_generator import ProfileGenerator
from backend.app.services.simulation_manager import (
    SimulationManager,
    get_simulation_manager,
    store_agent_profiles,
    store_activity_profiles,
)
from backend.app.services.supply_chain_builder import SupplyChainBuilder
from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger
from backend.app.utils.prompt_security import sanitize_scenario_description

# Default company count when scenario_type triggers auto-B2B generation
_DEFAULT_B2B_COMPANY_COUNT = 30

# Default scenario outcomes used when no decision_type data exists in Phase B
_DEFAULT_SCENARIO_OUTCOMES: list[str] = ["escalate", "negotiate", "de_escalate"]

router = APIRouter(prefix="/simulation", tags=["simulation"])
logger = get_logger("api.simulation")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


@router.get("/sessions", response_model=APIResponse)
async def list_sessions(limit: int = 20, offset: int = 0) -> APIResponse:
    """List all simulation sessions, newest first."""
    from backend.app.utils.db import get_db
    try:
        async with get_db() as db:
            total_row = await (await db.execute("SELECT COUNT(*) as c FROM simulation_sessions")).fetchone()
            rows = await (await db.execute(
                "SELECT id, name, scenario_type, status, agent_count, round_count, current_round, created_at FROM simulation_sessions ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (min(limit, 100), max(offset, 0)),
            )).fetchall()
        return APIResponse(
            success=True,
            data={"sessions": [dict(r) for r in (rows or [])], "total": total_row["c"] if total_row else 0, "limit": limit, "offset": offset},
        )
    except Exception as exc:
        logger.exception("list_sessions failed")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.post("/create", response_model=APIResponse)
async def create_simulation(req: SimulationCreateRequest) -> APIResponse:
    """Create a new simulation session."""
    try:
        enriched_shocks = [
            s.model_copy(update={"post_content": s.description})
            if not s.post_content
            else s
            for s in req.shocks
        ]
        req = req.model_copy(update={"shocks": enriched_shocks})

        # Resolve preset if provided
        if req.preset:
            from backend.app.models.simulation_config import resolve_preset  # noqa: PLC0415
            preset = resolve_preset(
                req.preset,
                agent_count=req.agent_count,
                round_count=req.round_count,
            )
            req = req.model_copy(update={
                "agent_count": preset.agents,
                "round_count": preset.rounds,
            })

        # Load domain pack demographics for agent generation
        demographics = None
        try:
            from backend.app.domain.base import DomainPackRegistry  # noqa: PLC0415
            pack = DomainPackRegistry.get(req.domain_pack_id)
            demographics = pack.demographics
        except (KeyError, Exception):
            logger.debug("Domain pack '%s' not found or has no demographics, using defaults", req.domain_pack_id)

        factory = AgentFactory(demographics=demographics)
        profile_gen = ProfileGenerator(agent_factory=factory)
        macro = MacroController()

        distribution = req.agent_distribution or {}
        profiles = factory.generate_population(req.agent_count, distribution or None)

        if req.family_members:
            for fm in req.family_members:
                twin = factory.generate_twin(fm.model_dump())
                profiles = [*profiles, twin]

        if req.crm_data:
            crm_records = [c.model_dump() for c in req.crm_data]
            crm_profiles = factory.generate_crm_agents(crm_records)
            profiles = [*profiles, *crm_profiles]

        macro_state = await macro.get_baseline_for_scenario(req.scenario_type or "property")

        manager = get_simulation_manager()
        request_dict = req.model_dump()
        session_data = await manager.create_session(request_dict, csv_path=None)
        session_id = session_data["session_id"]

        session_dir = _PROJECT_ROOT / "data" / "sessions" / session_id
        csv_path = str(session_dir / "agents.csv")
        csv_content = profile_gen.to_oasis_csv(profiles, macro_state)
        await asyncio.to_thread(Path(csv_path).write_text, csv_content, encoding="utf-8")
        logger.info("Wrote %d agents to %s", len(profiles), csv_path)

        from backend.app.utils.db import get_db  # noqa: PLC0415
        import json as _json  # noqa: PLC0415
        async with get_db() as db:
            row = await (await db.execute(
                "SELECT config_json FROM simulation_sessions WHERE id = ?",
                (session_id,),
            )).fetchone()
            if row and row["config_json"]:
                cfg = _json.loads(row["config_json"])
                cfg["agent_csv_path"] = csv_path
                await db.execute(
                    "UPDATE simulation_sessions SET config_json = ? WHERE id = ?",
                    (_json.dumps(cfg), session_id),
                )
                await db.commit()

        try:
            await store_agent_profiles(session_id, profiles, profile_gen, macro_state)
        except Exception:
            logger.warning(
                "Could not store agent profiles for session %s", session_id,
                exc_info=True,
            )

        # Phase 1B: generate temporal activity profiles and persist alongside agents.
        try:
            session_dir = _PROJECT_ROOT / "data" / "sessions" / session_id
            await store_activity_profiles(session_id, profiles, session_dir, factory)
        except Exception:
            logger.warning(
                "Could not store activity profiles for session %s", session_id,
                exc_info=True,
            )

        # ---- B2B enterprise auto-generation ----
        scenario_lower = (req.scenario_type or "").lower()
        is_b2b_scenario = any(kw in scenario_lower for kw in _B2B_SCENARIO_KEYWORDS)
        effective_company_count = req.company_count or (
            _DEFAULT_B2B_COMPANY_COUNT if is_b2b_scenario else 0
        )

        supply_chain_graph = None
        if effective_company_count > 0:
            try:
                company_factory = CompanyFactory()
                companies = await company_factory.generate_companies(
                    session_id=session_id,
                    count=effective_company_count,
                )
                stored_companies = await company_factory.store_companies(
                    session_id=session_id,
                    companies=companies,
                )

                sc_builder = SupplyChainBuilder()
                supply_chain_graph = await sc_builder.build_supply_chain(
                    session_id=session_id,
                    companies=stored_companies,
                    graph_id=req.graph_id,
                )

                logger.info(
                    "B2B generation complete for session=%s: %d companies, %d supply-chain edges",
                    session_id,
                    len(stored_companies),
                    supply_chain_graph.edge_count,
                )
            except Exception:
                logger.warning(
                    "B2B company generation failed for session %s — continuing without B2B data",
                    session_id,
                    exc_info=True,
                )

        b2b_meta: dict = {}
        if supply_chain_graph is not None:
            b2b_meta = {
                "company_count": supply_chain_graph.node_count,
                "supply_chain_edges": supply_chain_graph.edge_count,
            }

        return APIResponse(
            success=True,
            data={**session_data, "session_id": session_id},
            meta={
                "graph_id": req.graph_id,
                "llm_provider": req.llm_provider,
                "agent_csv_path": csv_path,
                **b2b_meta,
            },
        )

    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Bad request") from exc
    except Exception as exc:
        logger.exception("create_simulation failed")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.post("/start", response_model=APIResponse)
@_limiter.limit("10/minute")
async def start_simulation(request: Request, req: SimulationStartRequest) -> APIResponse:
    """Start a previously created simulation session."""
    try:
        manager = get_simulation_manager()
        await manager.start_session(req.session_id)
        return APIResponse(
            success=True,
            data={
                "session_id": req.session_id,
                "status": "running",
                "message": "Simulation started. Connect to WebSocket /ws/progress/{session_id} for live updates.",
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Bad request") from exc
    except Exception as exc:
        logger.exception("start_simulation failed for session %s", req.session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.post("/estimate-cost", response_model=APIResponse)
async def estimate_simulation_cost(req: dict) -> APIResponse:
    """Estimate LLM cost for a simulation before running it."""
    from backend.app.services.cost_estimator import estimate_cost  # noqa: PLC0415
    try:
        breakdown = estimate_cost(
            provider=req.get("llm_provider", "openrouter"),
            model=req.get("llm_model"),
            agent_count=req.get("agent_count", 300),
            round_count=req.get("round_count", 20),
        )
        from dataclasses import asdict  # noqa: PLC0415
        return APIResponse(success=True, data=asdict(breakdown))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Bad request") from exc


_QUICK_START_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_QUICK_START_ALLOWED_EXTS = {".pdf", ".txt", ".md", ".markdown"}


async def _run_quick_start(seed_text: str, scenario_question: str = "", preset: str = "fast") -> APIResponse:
    """Shared business logic for both JSON and file-upload quick-start endpoints."""
    from backend.app.utils.prompt_security import sanitize_seed_text as _sanitize_seed  # noqa: PLC0415
    from backend.app.services.zero_config import ZeroConfigService  # noqa: PLC0415
    from backend.app.services.graph_builder import GraphBuilderService  # noqa: PLC0415

    # Sanitize all user-controlled text before it reaches any LLM service.
    seed_text = _sanitize_seed(seed_text)

    zc = ZeroConfigService()
    config = await zc.prepare(seed_text)

    # Apply preset overrides — the preset param was accepted but never applied before.
    from backend.app.models.simulation_config import resolve_preset  # noqa: PLC0415
    resolved = resolve_preset(preset)
    agent_count_final = resolved.agents
    round_count_final = resolved.rounds
    estimated_duration = round_count_final * agent_count_final // 50

    graph_builder = GraphBuilderService()
    graph_result = await graph_builder.build_graph(
        session_id="quick",
        scenario_type=config.domain_pack_id,
        seed_text=seed_text,
        hk_data={},
    )
    graph_id = graph_result.get("graph_id", "")

    manager = get_simulation_manager()
    session_data = await manager.create_session(
        {
            "name": f"Quick Start: {seed_text[:50]}",
            "scenario_type": "property",
            "seed_text": seed_text,
            "agent_count": agent_count_final,
            "round_count": round_count_final,
            "graph_id": graph_id,
            "domain_pack_id": config.domain_pack_id,
            "platforms": {"facebook": True, "instagram": True},
        },
        csv_path=None,
    )
    session_id = session_data["session_id"]

    demographics = None
    try:
        from backend.app.domain.base import DomainPackRegistry as _DPR  # noqa: PLC0415
        pack = _DPR.get(config.domain_pack_id)
        demographics = pack.demographics
    except (KeyError, Exception):
        pass

    factory = AgentFactory(demographics=demographics)
    profiles = factory.generate_population(agent_count_final, None)

    macro = MacroController()
    macro_state = await macro.get_baseline_for_scenario("property")

    profile_gen = ProfileGenerator(agent_factory=factory)
    csv_content = profile_gen.to_oasis_csv(profiles, macro_state)
    session_dir = _PROJECT_ROOT / "data" / "sessions" / session_id
    csv_path = str(session_dir / "agents.csv")
    await asyncio.to_thread(Path(csv_path).write_text, csv_content, encoding="utf-8")

    try:
        await store_agent_profiles(session_id, profiles, profile_gen, macro_state)
    except Exception:
        logger.warning("Could not store agent profiles for quick-start session %s", session_id, exc_info=True)

    try:
        await store_activity_profiles(session_id, profiles, session_dir, factory)
    except Exception:
        logger.warning("Could not store activity profiles for quick-start session %s", session_id, exc_info=True)

    asyncio.create_task(manager.start_session(session_id))

    return APIResponse(
        success=True,
        data={
            "session_id": session_id,
            "graph_id": graph_id,
            "status_url": f"/api/simulation/{session_id}/status",
            "estimated_duration_seconds": estimated_duration,
            "domain_pack_id": config.domain_pack_id,
            "agent_count": agent_count_final,
            "round_count": round_count_final,
            "scenario_question": scenario_question,
        },
    )


@router.post("/quick-start", response_model=APIResponse)
async def quick_start(req: dict) -> APIResponse:
    """One-click quick start: paste text and run simulation."""
    try:
        seed_text = (req.get("seed_text") or "").strip()
        if not seed_text:
            raise HTTPException(status_code=400, detail="seed_text is required")
        scenario_question_raw = (req.get("scenario_question") or "").strip()
        scenario_question = sanitize_scenario_description(scenario_question_raw) if scenario_question_raw else ""
        preset = (req.get("preset") or "fast").strip()
        return await _run_quick_start(seed_text, scenario_question, preset)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("quick_start failed")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.post("/quick-start/upload", response_model=APIResponse)
async def quick_start_upload(
    file: UploadFile,
    scenario_question: str = "",
    preset: str = "fast",
) -> APIResponse:
    """Quick-start via file upload (PDF / TXT / Markdown, max 10 MB).

    Extracts text then delegates to ``_run_quick_start()``.
    """
    import io as _io  # noqa: PLC0415

    try:
        content = await file.read()
        if len(content) > _QUICK_START_MAX_BYTES:
            raise HTTPException(status_code=400, detail="File exceeds 10 MB limit")

        ext = Path(file.filename or "").suffix.lower()
        if ext not in _QUICK_START_ALLOWED_EXTS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type '{ext}'. Allowed: PDF, TXT, Markdown",
            )

        if ext == ".pdf":
            seed_text = ""
            try:
                import pypdf  # noqa: PLC0415
                reader = pypdf.PdfReader(_io.BytesIO(content))
                seed_text = "\n\n".join(p.extract_text() or "" for p in reader.pages).strip()
            except ImportError:
                try:
                    import PyPDF2  # noqa: PLC0415, N813
                    reader = PyPDF2.PdfReader(_io.BytesIO(content))
                    seed_text = "\n\n".join(p.extract_text() or "" for p in reader.pages).strip()
                except ImportError:
                    raise HTTPException(
                        status_code=422,
                        detail="PDF library not installed. Please upload TXT or Markdown.",
                    ) from None
            except Exception as exc:
                raise HTTPException(status_code=422, detail=f"PDF extraction failed: {exc}") from exc
        else:
            seed_text = content.decode("utf-8", errors="replace").strip()

        if not seed_text:
            raise HTTPException(status_code=422, detail="Could not extract text from file")

        scenario_question_raw = (scenario_question or "").strip()
        scenario_question = sanitize_scenario_description(scenario_question_raw) if scenario_question_raw else ""
        return await _run_quick_start(seed_text, scenario_question, preset)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("quick_start_upload failed")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


# ---------------------------------------------------------------------------
# Admin benchmark endpoints (Phase 4D)
# IMPORTANT: These static routes MUST be registered BEFORE /{session_id}
# to avoid FastAPI matching "admin" as a session_id.
# ---------------------------------------------------------------------------


@router.get("/admin/benchmarks", response_model=APIResponse)
async def list_benchmarks(limit: int = 50) -> APIResponse:
    """List all stored scale benchmark results, newest first."""
    from backend.app.utils.db import get_db  # noqa: PLC0415
    import json as _json  # noqa: PLC0415

    try:
        async with get_db() as db:
            rows = await (
                await db.execute(
                    """SELECT id, target_name, agent_count, rounds_completed,
                              total_duration_s, avg_round_duration_s,
                              peak_memory_mb, throughput, bottleneck_hook,
                              passed, created_at
                       FROM scale_benchmarks
                       ORDER BY created_at DESC
                       LIMIT ?""",
                    (min(limit, 200),),
                )
            ).fetchall()
        return APIResponse(
            success=True,
            data={"benchmarks": [dict(r) for r in (rows or [])], "count": len(rows or [])},
        )
    except Exception as exc:
        logger.exception("list_benchmarks failed")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/admin/benchmarks/{target}", response_model=APIResponse)
async def get_benchmark(target: str) -> APIResponse:
    """Get the most recent benchmark result for a given scale target (1k/3k/10k)."""
    from backend.app.utils.db import get_db  # noqa: PLC0415

    valid_targets = {"1k", "3k", "10k"}
    if target not in valid_targets:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid target '{target}'. Choose from: {', '.join(valid_targets)}",
        )

    try:
        async with get_db() as db:
            row = await (
                await db.execute(
                    """SELECT * FROM scale_benchmarks
                       WHERE target_name = ?
                       ORDER BY created_at DESC
                       LIMIT 1""",
                    (target,),
                )
            ).fetchone()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"No benchmark results found for target '{target}'",
            )
        return APIResponse(success=True, data=dict(row))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("get_benchmark failed for target %s", target)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.post("/admin/benchmarks/run", response_model=APIResponse)
async def run_benchmark_endpoint(target: str = "1k") -> APIResponse:
    """Trigger a scale benchmark run and persist results to the DB."""
    from backend.app.models.scale import SCALE_1K, SCALE_3K, SCALE_10K  # noqa: PLC0415
    from backend.app.scripts_compat import run_benchmark_bg  # noqa: PLC0415 — optional
    import json as _json  # noqa: PLC0415

    valid_targets = {"1k": SCALE_1K, "3k": SCALE_3K, "10k": SCALE_10K}
    if target not in valid_targets:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid target '{target}'. Choose from: {', '.join(valid_targets)}",
        )

    scale_target = valid_targets[target]

    async def _run_and_persist() -> None:
        from backend.scripts.scale_benchmark import run_benchmark  # noqa: PLC0415
        from backend.app.utils.db import get_db  # noqa: PLC0415
        import dataclasses as _dc  # noqa: PLC0415

        try:
            result = await run_benchmark(scale_target)
            async with get_db() as db:
                try:
                    await db.execute(
                        """CREATE TABLE IF NOT EXISTS scale_benchmarks (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            target_name TEXT NOT NULL,
                            agent_count INTEGER NOT NULL,
                            rounds_completed INTEGER NOT NULL,
                            total_duration_s REAL NOT NULL,
                            avg_round_duration_s REAL NOT NULL,
                            peak_memory_mb REAL NOT NULL DEFAULT 0,
                            db_queries_total INTEGER NOT NULL DEFAULT 0,
                            db_avg_query_ms REAL NOT NULL DEFAULT 0.0,
                            llm_calls_total INTEGER NOT NULL DEFAULT 0,
                            llm_avg_latency_ms REAL NOT NULL DEFAULT 0.0,
                            hook_durations_json TEXT NOT NULL DEFAULT '{}',
                            bottleneck_hook TEXT NOT NULL DEFAULT '',
                            throughput REAL NOT NULL DEFAULT 0.0,
                            passed INTEGER NOT NULL DEFAULT 0,
                            created_at TEXT DEFAULT (datetime('now'))
                        )"""
                    )
                    await db.execute(
                        """INSERT INTO scale_benchmarks
                           (target_name, agent_count, rounds_completed, total_duration_s,
                            avg_round_duration_s, peak_memory_mb,
                            hook_durations_json, bottleneck_hook, throughput, passed)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            result.preset_name,
                            result.agent_count,
                            result.rounds_completed,
                            result.total_duration_s,
                            result.avg_round_duration_s,
                            result.peak_memory_mb,
                            _json.dumps(result.hook_durations),
                            result.bottleneck_hook,
                            result.throughput_agents_per_sec,
                            1 if result.passed else 0,
                        ),
                    )
                    await db.commit()
                    logger.info("Persisted benchmark result for target '%s'", target)
                except Exception as db_exc:
                    logger.error("Failed to persist benchmark result: %s", db_exc)
        except Exception as exc:
            logger.error("Background benchmark run failed: %s", exc)

    asyncio.create_task(_run_and_persist(), name=f"benchmark-{target}")

    return APIResponse(
        success=True,
        data={"message": f"Benchmark started for target '{target}'"},
        meta={"target": target, "agent_count": scale_target.agent_count},
    )


# ---------------------------------------------------------------------------
# Parameterized session routes (MUST come AFTER all static routes)
# ---------------------------------------------------------------------------


@router.get("/{session_id}/status", response_model=APIResponse)
async def get_session_status_alias(session_id: str) -> APIResponse:
    """Frontend poller alias — delegates to GET /{session_id}."""
    return await get_session_status(session_id)


@router.get("/{session_id}", response_model=APIResponse)
async def get_session_status(session_id: str) -> APIResponse:
    """Get the current status and metadata of a simulation session."""
    try:
        manager = get_simulation_manager()
        session_data = await manager.get_session(session_id)

        # Include mini-ensemble summary (p25/p50/p75) if available
        ensemble_summary = None
        try:
            from backend.app.services.monte_carlo import MonteCarloEngine  # noqa: PLC0415
            mc = MonteCarloEngine()
            cached = await mc.get_cached_result(session_id)
            if cached and cached.distributions:
                ensemble_summary = {
                    b.metric_name: {"p25": b.p25, "p50": b.p50, "p75": b.p75}
                    for b in cached.distributions
                }
        except Exception:
            pass  # ensemble is optional

        data = session_data if isinstance(session_data, dict) else {"session": session_data}
        if ensemble_summary:
            data["ensemble_summary"] = ensemble_summary

        return APIResponse(success=True, data=data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    except Exception as exc:
        logger.exception("get_session_status failed for session %s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{session_id}/agents", response_model=APIResponse)
async def list_agents(session_id: str) -> APIResponse:
    """List all agent profiles stored for a simulation session."""
    try:
        manager = get_simulation_manager()
        agents = await manager.get_agents(session_id)
        return APIResponse(
            success=True,
            data=agents,
            meta={"session_id": session_id, "count": len(agents)},
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    except Exception as exc:
        logger.exception("list_agents failed for session %s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.post("/suggest-config", response_model=APIResponse)
async def suggest_config(req: ConfigSuggestRequest) -> APIResponse:
    """Generate simulation config suggestion from natural language query."""
    from backend.app.services.config_generator import ConfigGenerator  # noqa: PLC0415

    try:
        generator = ConfigGenerator()
        config = await generator.generate(
            user_query=req.user_query,
            processed_seed_summary=req.processed_seed_summary,
        )

        return APIResponse(
            success=True,
            data={
                "scenario_type": config.scenario_type,
                "agent_count": config.agent_count,
                "round_count": config.round_count,
                "district_focus": list(config.district_focus),
                "suggested_shocks": [
                    {
                        "round_number": s.round_number,
                        "shock_type": s.shock_type,
                        "description": s.description,
                        "post_content": s.post_content,
                    }
                    for s in config.suggested_shocks
                ],
                "macro_scenario": config.macro_scenario,
                "rationale": config.rationale,
                "confidence": config.confidence,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Bad request") from exc
    except Exception as exc:
        logger.exception("suggest_config failed")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{session_id}/actions", response_model=APIResponse)
async def get_session_actions(
    session_id: str,
    round: int | None = None,
    platform: str | None = None,
    limit: int = 200,
) -> APIResponse:
    """Get logged simulation actions for a session."""
    from backend.scripts.action_logger import ActionLogger  # noqa: PLC0415

    try:
        action_logger = ActionLogger()
        actions = await action_logger.get_round_actions(
            session_id=session_id,
            round_number=round,
            platform=platform,
            limit=min(limit, 1000),
        )
        return APIResponse(
            success=True,
            data=actions,
            meta={
                "session_id": session_id,
                "count": len(actions),
                "round": round,
                "platform": platform,
            },
        )
    except Exception as exc:
        logger.exception("get_session_actions failed for session %s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{session_id}/actions/sentiment", response_model=APIResponse)
async def get_sentiment_summary(session_id: str) -> APIResponse:
    """Get per-round sentiment summary for a session."""
    from backend.scripts.action_logger import ActionLogger  # noqa: PLC0415

    try:
        action_logger = ActionLogger()
        summary = await action_logger.get_sentiment_summary(session_id)
        return APIResponse(
            success=True,
            data=summary,
            meta={"session_id": session_id},
        )
    except Exception as exc:
        logger.exception("get_sentiment_summary failed for session %s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{session_id}/agents/{agent_id}/memories", response_model=APIResponse)
async def get_agent_memories(
    session_id: str,
    agent_id: int,
    limit: int = 50,
) -> APIResponse:
    """Get memory records for a specific agent in a session."""
    from backend.app.services.agent_memory import AgentMemoryService  # noqa: PLC0415

    try:
        memory_service = AgentMemoryService()
        memories = await memory_service.get_agent_memories(
            session_id=session_id,
            agent_id=agent_id,
            limit=min(limit, 200),
        )
        triples = await memory_service.get_agent_triples(
            session_id=session_id,
            agent_id=agent_id,
            limit=200,
        )
        return APIResponse(
            success=True,
            data={"memories": memories, "triples": triples},
            meta={
                "session_id": session_id,
                "agent_id": agent_id,
                "memory_count": len(memories),
                "triple_count": len(triples),
            },
        )
    except Exception as exc:
        logger.exception(
            "get_agent_memories failed for session %s agent %d", session_id, agent_id
        )
        logger.exception("Internal error in get_agent_memories")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get(
    "/{session_id}/agents/{agent_id}/memories/search",
    response_model=APIResponse,
)
async def search_agent_memories(
    session_id: str,
    agent_id: int,
    q: str = "",
    top_k: int = 10,
) -> APIResponse:
    """Semantic search across an agent's memories using vector similarity."""
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query parameter 'q' is required")

    from backend.app.services.agent_memory import AgentMemoryService  # noqa: PLC0415

    try:
        from backend.app.services.vector_store import VectorStore  # noqa: PLC0415
        vs = VectorStore()
        memory_service = AgentMemoryService(vector_store=vs)
    except Exception:
        logger.warning("VectorStore unavailable, semantic search disabled")
        raise HTTPException(
            status_code=503,
            detail="Semantic search unavailable — vector store not initialised",
        )

    try:
        results = await memory_service.search_memories(
            session_id=session_id,
            agent_id=agent_id,
            query=q.strip(),
            top_k=min(top_k, 50),
        )
        return APIResponse(
            success=True,
            data=results,
            meta={
                "session_id": session_id,
                "agent_id": agent_id,
                "query": q,
                "count": len(results),
            },
        )
    except RuntimeError as exc:
        logger.exception("Internal error in search_agent_memories")
        raise HTTPException(status_code=503, detail="Internal server error") from exc
    except Exception as exc:
        logger.exception(
            "search_agent_memories failed session=%s agent=%d q=%s",
            session_id, agent_id, q,
        )
        logger.exception("Internal error in search_agent_memories")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


# ---------------------------------------------------------------------------
# Decision endpoints (Phase 1)
# ---------------------------------------------------------------------------

@router.get("/{session_id}/decisions", response_model=APIResponse)
async def get_decisions(
    session_id: str,
    round_number: int | None = None,
    decision_type: str | None = None,
    limit: int = 200,
) -> APIResponse:
    """Get agent decisions for a session."""
    from backend.app.utils.db import get_db  # noqa: PLC0415

    try:
        conditions = ["session_id = ?"]
        params: list = [session_id]
        if round_number is not None:
            conditions.append("round_number = ?")
            params.append(round_number)
        if decision_type:
            conditions.append("decision_type = ?")
            params.append(decision_type)
        params.append(min(limit, 1000))

        where = " AND ".join(conditions)
        async with get_db() as db:
            rows = await (
                await db.execute(
                    f"SELECT * FROM agent_decisions WHERE {where} ORDER BY round_number, agent_id LIMIT ?",
                    params,
                )
            ).fetchall()
        return APIResponse(
            success=True,
            data=[dict(r) for r in rows],
            meta={"session_id": session_id, "count": len(rows)},
        )
    except Exception as exc:
        logger.exception("get_decisions failed for session %s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{session_id}/decisions/summary", response_model=APIResponse)
async def get_decisions_summary(session_id: str) -> APIResponse:
    """Get aggregated decision summary for a session."""
    from backend.app.utils.db import get_db  # noqa: PLC0415

    try:
        async with get_db() as db:
            rows = await (
                await db.execute(
                    """SELECT decision_type, action, COUNT(*) as count,
                              AVG(confidence) as avg_confidence
                       FROM agent_decisions
                       WHERE session_id = ?
                       GROUP BY decision_type, action
                       ORDER BY count DESC""",
                    (session_id,),
                )
            ).fetchall()
        return APIResponse(
            success=True,
            data=[dict(r) for r in rows],
            meta={"session_id": session_id},
        )
    except Exception as exc:
        logger.exception("get_decisions_summary failed for session %s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


# ---------------------------------------------------------------------------
# Company / B2B endpoints (Phase 5)
# ---------------------------------------------------------------------------

@router.get("/{session_id}/companies", response_model=APIResponse)
async def list_companies(session_id: str) -> APIResponse:
    """List all company profiles for a simulation session."""
    from backend.app.utils.db import get_db  # noqa: PLC0415

    try:
        async with get_db() as db:
            rows = await (
                await db.execute(
                    "SELECT * FROM company_profiles WHERE session_id = ? ORDER BY id",
                    (session_id,),
                )
            ).fetchall()
        return APIResponse(
            success=True,
            data=[dict(r) for r in rows],
            meta={"session_id": session_id, "count": len(rows)},
        )
    except Exception as exc:
        logger.exception("list_companies failed for session %s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{session_id}/companies/{company_id}/decisions", response_model=APIResponse)
async def get_company_decisions(
    session_id: str, company_id: int, limit: int = 100
) -> APIResponse:
    """Get decision history for a specific company."""
    from backend.app.utils.db import get_db  # noqa: PLC0415

    try:
        async with get_db() as db:
            rows = await (
                await db.execute(
                    """SELECT * FROM company_decisions
                       WHERE session_id = ? AND company_id = ?
                       ORDER BY round_number LIMIT ?""",
                    (session_id, company_id, min(limit, 500)),
                )
            ).fetchall()
        return APIResponse(
            success=True,
            data=[dict(r) for r in rows],
            meta={"session_id": session_id, "company_id": company_id, "count": len(rows)},
        )
    except Exception as exc:
        logger.exception("get_company_decisions failed for session %s company %d", session_id, company_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{session_id}/supply-chain", response_model=APIResponse)
async def get_supply_chain(session_id: str) -> APIResponse:
    """Get supply chain KG edges for a session."""
    from backend.app.utils.db import get_db  # noqa: PLC0415

    try:
        async with get_db() as db:
            rows = await (
                await db.execute(
                    """SELECT source_id, target_id, relation_type, weight
                       FROM kg_edges
                       WHERE session_id = ?
                         AND relation_type IN ('SUPPLIES_TO', 'BUYS_FROM', 'DEPENDS_ON')
                       ORDER BY weight DESC""",
                    (session_id,),
                )
            ).fetchall()
        return APIResponse(
            success=True,
            data=[dict(r) for r in rows],
            meta={"session_id": session_id, "count": len(rows)},
        )
    except Exception as exc:
        logger.exception("get_supply_chain failed for session %s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{session_id}/consumption", response_model=APIResponse)
async def get_consumption_trends(
    session_id: str,
    limit_rounds: int = 50,
) -> APIResponse:
    """Get per-round B2C consumption trends for a simulation session.

    Returns aggregated spending category averages (food, housing, transport,
    entertainment, education, healthcare, savings_rate) grouped by round,
    sorted chronologically.

    Args:
        session_id: Simulation session UUID.
        limit_rounds: Maximum number of rounds to return (default 50).
    """
    from backend.app.services.consumption_model import ConsumptionTracker  # noqa: PLC0415

    try:
        tracker = ConsumptionTracker()
        summaries = await tracker.get_consumption_trends(
            session_id=session_id,
            limit_rounds=min(limit_rounds, 200),
        )
        return APIResponse(
            success=True,
            data=[s.to_dict() for s in summaries],
            meta={
                "session_id": session_id,
                "count": len(summaries),
                "rounds_returned": len(summaries),
            },
        )
    except Exception as exc:
        logger.exception("get_consumption_trends failed for session %s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{session_id}/agents/{agent_id}/consumption", response_model=APIResponse)
async def get_agent_consumption(
    session_id: str,
    agent_id: int,
    limit_rounds: int = 30,
) -> APIResponse:
    """Get per-round spending breakdown for a specific agent.

    Returns raw category × round rows for the agent detail panel.
    """
    from backend.app.services.consumption_model import ConsumptionTracker  # noqa: PLC0415

    try:
        tracker = ConsumptionTracker()
        rows = await tracker.get_agent_consumption(
            session_id=session_id,
            agent_id=agent_id,
            limit_rounds=min(limit_rounds, 100),
        )
        return APIResponse(
            success=True,
            data=rows,
            meta={
                "session_id": session_id,
                "agent_id": agent_id,
                "count": len(rows),
            },
        )
    except Exception as exc:
        logger.exception(
            "get_agent_consumption failed for session %s agent %d", session_id, agent_id
        )
        logger.exception("Internal error in get_agent_consumption")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.post("/{session_id}/companies/summary", response_model=APIResponse)
async def get_company_summary(session_id: str) -> APIResponse:
    """Aggregated company decision summary by industry/size."""
    from backend.app.utils.db import get_db  # noqa: PLC0415

    try:
        async with get_db() as db:
            rows = await (
                await db.execute(
                    """SELECT cp.industry_sector, cp.company_size,
                              cd.decision_type, cd.action, COUNT(*) as count,
                              AVG(cd.confidence) as avg_confidence
                       FROM company_decisions cd
                       JOIN company_profiles cp ON cp.id = cd.company_id AND cp.session_id = cd.session_id
                       WHERE cd.session_id = ?
                       GROUP BY cp.industry_sector, cp.company_size, cd.decision_type, cd.action
                       ORDER BY count DESC""",
                    (session_id,),
                )
            ).fetchall()
        return APIResponse(
            success=True,
            data=[dict(r) for r in rows],
            meta={"session_id": session_id},
        )
    except Exception as exc:
        logger.exception("get_company_summary failed for session %s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


# ---------------------------------------------------------------------------
# God-Mode live shock injection
# ---------------------------------------------------------------------------

@router.get("/{session_id}/echo-chambers", response_model=APIResponse)
async def get_echo_chambers(
    session_id: str,
    round_number: int | None = None,
) -> APIResponse:
    """Get echo chamber snapshot(s) for a simulation session.

    If round_number is provided, returns that specific snapshot.
    Otherwise returns the latest snapshot.
    """
    from backend.app.utils.db import get_db  # noqa: PLC0415
    import json as _json  # noqa: PLC0415

    try:
        async with get_db() as db:
            if round_number is not None:
                cursor = await db.execute(
                    """SELECT session_id, round_number, num_clusters, modularity,
                              cluster_data_json, agent_to_cluster_json, created_at
                       FROM echo_chamber_snapshots
                       WHERE session_id = ? AND round_number = ?
                       ORDER BY id DESC LIMIT 1""",
                    (session_id, round_number),
                )
            else:
                cursor = await db.execute(
                    """SELECT session_id, round_number, num_clusters, modularity,
                              cluster_data_json, agent_to_cluster_json, created_at
                       FROM echo_chamber_snapshots
                       WHERE session_id = ?
                       ORDER BY round_number DESC LIMIT 1""",
                    (session_id,),
                )
            row = await cursor.fetchone()

        if not row:
            return APIResponse(
                success=True,
                data=None,
                meta={"session_id": session_id, "message": "No echo chamber data found"},
            )

        return APIResponse(
            success=True,
            data={
                "session_id": row[0],
                "round_number": row[1],
                "num_clusters": row[2],
                "modularity": row[3],
                "cluster_data": _json.loads(row[4]) if row[4] else [],
                "agent_to_cluster": _json.loads(row[5]) if row[5] else {},
                "created_at": row[6],
            },
            meta={"session_id": session_id},
        )
    except Exception as exc:
        logger.exception("get_echo_chambers failed for session %s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{session_id}/contagion", response_model=APIResponse)
async def get_contagion_data(session_id: str) -> APIResponse:
    """Get agents with active social contagion (>=3 distress signals from trusted peers).

    Returns a list of agent_ids where contagion is active, based on recent
    distress signals from trusted peers (trust_score >= 0.3).
    """
    from backend.app.utils.db import get_db  # noqa: PLC0415

    _DISTRESS_PREDICATES = (
        "worries_about", "emigrated", "lost_job", "decreases", "opposes", "causes",
    )
    _DISTRESS_ACTIONS = (
        "wait", "sell", "emigrate", "cut_spending", "reduce_investment",
    )
    _TRUST_THRESHOLD = 0.3
    _SIGNAL_THRESHOLD = 3

    try:
        async with get_db() as db:
            # Get all agents in session
            cursor = await db.execute(
                "SELECT DISTINCT id FROM agent_profiles WHERE session_id = ?",
                (session_id,),
            )
            agent_rows = await cursor.fetchall()
            all_agent_ids = [r[0] for r in agent_rows]

        if not all_agent_ids:
            return APIResponse(
                success=True,
                data={"contagion_agents": [], "total_agents": 0},
                meta={"session_id": session_id},
            )

        contagion_agents: list[dict] = []

        async with get_db() as db:
            for agent_id in all_agent_ids:
                signal_count = 0

                # Count distress triples from trusted peers
                placeholders = ",".join("?" for _ in _DISTRESS_PREDICATES)
                cursor = await db.execute(
                    f"""
                    SELECT COUNT(DISTINCT mt.agent_id) FROM memory_triples mt
                    JOIN agent_relationships ar
                        ON ar.session_id = mt.session_id
                        AND ar.agent_b_id = mt.agent_id
                        AND ar.agent_a_id = ?
                    WHERE mt.session_id = ?
                      AND mt.predicate IN ({placeholders})
                      AND ar.trust_score >= ?
                    """,
                    (agent_id, session_id, *_DISTRESS_PREDICATES, _TRUST_THRESHOLD),
                )
                row = await cursor.fetchone()
                signal_count += row[0] if row else 0

                # Count distress decisions from trusted peers
                d_placeholders = ",".join("?" for _ in _DISTRESS_ACTIONS)
                cursor = await db.execute(
                    f"""
                    SELECT COUNT(DISTINCT ad.agent_id) FROM agent_decisions ad
                    JOIN agent_relationships ar
                        ON ar.session_id = ad.session_id
                        AND ar.agent_b_id = ad.agent_id
                        AND ar.agent_a_id = ?
                    WHERE ad.session_id = ?
                      AND ad.action IN ({d_placeholders})
                      AND ar.trust_score >= ?
                    """,
                    (agent_id, session_id, *_DISTRESS_ACTIONS, _TRUST_THRESHOLD),
                )
                row = await cursor.fetchone()
                signal_count += row[0] if row else 0

                if signal_count >= _SIGNAL_THRESHOLD:
                    contagion_agents.append({
                        "agent_id": agent_id,
                        "distress_signal_count": signal_count,
                        "contagion_active": True,
                    })

        return APIResponse(
            success=True,
            data={
                "contagion_agents": contagion_agents,
                "total_agents": len(all_agent_ids),
                "contagion_count": len(contagion_agents),
            },
            meta={"session_id": session_id},
        )
    except Exception as exc:
        logger.exception("get_contagion_data failed for session %s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.post("/{session_id}/shock", response_model=APIResponse)
async def inject_live_shock(session_id: str, shock: ScheduledShock) -> APIResponse:
    """Inject a live shock into a running simulation (God Mode)."""
    from backend.app.api.ws import push_progress  # noqa: PLC0415
    from backend.app.utils.db import get_db  # noqa: PLC0415

    try:
        async with get_db() as db:
            row = await (
                await db.execute(
                    "SELECT status FROM simulation_sessions WHERE id = ?",
                    (session_id,),
                )
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Session not found")
            if row["status"] != "running":
                raise HTTPException(status_code=400, detail="Simulation is not running")

            content = shock.post_content or shock.description

            # Broadcast via WebSocket
            await push_progress(session_id, {
                "type": "post",
                "data": {
                    "source": "shock",
                    "shock_type": shock.shock_type,
                    "content": content,
                    "platform": "god_mode",
                    "round": shock.round_number,
                },
            })

            # Persist to simulation_actions
            await db.execute(
                "INSERT INTO simulation_actions "
                "(session_id, round_number, agent_id, oasis_username, action_type, "
                "platform, content, sentiment, topics, created_at) "
                "VALUES (?, ?, 0, '[God Mode]', 'CREATE_POST', 'god_mode', ?, 'neutral', ?, datetime('now'))",
                (session_id, shock.round_number, content, shock.shock_type),
            )
            await db.commit()

        return APIResponse(
            success=True,
            data={"injected": True, "shock_type": shock.shock_type},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("inject_live_shock failed for session %s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


# ---------------------------------------------------------------------------
# Contagion Tree (Phase 17)
# ---------------------------------------------------------------------------

@router.get("/{session_id}/contagion-tree", response_model=APIResponse)
async def get_contagion_tree(
    session_id: str,
    post_id: int = 0,
    max_depth: int = 5,
) -> APIResponse:
    """Recursive cascade tree for a specific post.

    Returns D3-compatible tree JSON with trust deltas.
    """
    from backend.app.utils.db import get_db  # noqa: PLC0415

    if post_id <= 0:
        raise HTTPException(status_code=400, detail="post_id is required and must be > 0")

    try:
        async with get_db() as db:
            # Recursive CTE to get cascade tree
            rows = await (await db.execute("""
                WITH RECURSIVE cascade AS (
                    SELECT id, agent_id, oasis_username, content, sentiment,
                           round_number, parent_action_id,
                           COALESCE(spread_depth, 0) AS spread_depth, 0 AS depth
                    FROM simulation_actions
                    WHERE id = ? AND session_id = ?

                    UNION ALL

                    SELECT sa.id, sa.agent_id, sa.oasis_username, sa.content, sa.sentiment,
                           sa.round_number, sa.parent_action_id,
                           COALESCE(sa.spread_depth, 0), c.depth + 1
                    FROM simulation_actions sa
                    JOIN cascade c ON sa.parent_action_id = c.id
                    WHERE sa.session_id = ? AND c.depth < ?
                )
                SELECT * FROM cascade ORDER BY depth, round_number
            """, (post_id, session_id, session_id, max_depth))).fetchall()

        if not rows:
            return APIResponse(
                success=True,
                data=None,
                meta={"session_id": session_id, "post_id": post_id, "message": "Post not found or no cascade"},
            )

        # Build tree structure
        nodes: dict[int, dict] = {}
        for r in rows:
            nodes[r[0]] = {
                "id": r[0],
                "agent_id": r[1],
                "username": r[2],
                "content": (r[3] or "")[:200],
                "sentiment": r[4],
                "round": r[5],
                "spread_depth": r[7],
                "children": [],
            }

        # Link parent-child
        root = None
        for r in rows:
            node_id = r[0]
            parent_id = r[6]
            if parent_id and parent_id in nodes:
                nodes[parent_id]["children"].append(nodes[node_id])
            if r[8] == 0:  # depth == 0 → root
                root = nodes[node_id]

        return APIResponse(
            success=True,
            data=root or nodes.get(post_id),
            meta={
                "session_id": session_id,
                "post_id": post_id,
                "total_nodes": len(nodes),
                "max_depth": max(r[8] for r in rows) if rows else 0,
            },
        )
    except Exception as exc:
        logger.exception("get_contagion_tree failed for session %s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{session_id}/contagion-stats", response_model=APIResponse)
async def get_contagion_stats(
    session_id: str,
    round_start: int = 0,
    round_end: int = 999,
) -> APIResponse:
    """Aggregate contagion metrics across all cascades."""
    from backend.app.utils.db import get_db  # noqa: PLC0415

    try:
        async with get_db() as db:
            # Total cascades (root posts that have children)
            cursor = await db.execute(
                """SELECT COUNT(DISTINCT parent_action_id)
                   FROM simulation_actions
                   WHERE session_id = ? AND parent_action_id IS NOT NULL
                     AND round_number BETWEEN ? AND ?""",
                (session_id, round_start, round_end),
            )
            total_cascades = (await cursor.fetchone())[0] or 0

            # Depth stats
            cursor = await db.execute(
                """SELECT AVG(COALESCE(spread_depth, 0)), MAX(COALESCE(spread_depth, 0))
                   FROM simulation_actions
                   WHERE session_id = ? AND parent_action_id IS NOT NULL
                     AND round_number BETWEEN ? AND ?""",
                (session_id, round_start, round_end),
            )
            depth_row = await cursor.fetchone()
            avg_depth = round(float(depth_row[0] or 0), 2)
            max_depth = int(depth_row[1] or 0)

            # Top spreaders
            cursor = await db.execute(
                """SELECT sa.agent_id, COUNT(*) as cascade_count,
                          AVG(COALESCE(child.spread_depth, 0)) as avg_child_depth
                   FROM simulation_actions sa
                   JOIN simulation_actions child ON child.parent_action_id = sa.id
                   WHERE sa.session_id = ? AND sa.round_number BETWEEN ? AND ?
                   GROUP BY sa.agent_id
                   ORDER BY cascade_count DESC
                   LIMIT 10""",
                (session_id, round_start, round_end),
            )
            spreader_rows = await cursor.fetchall()
            top_spreaders = [
                {
                    "agent_id": r[0],
                    "cascade_count": r[1],
                    "avg_depth": round(float(r[2] or 0), 2),
                }
                for r in spreader_rows
            ]

        return APIResponse(
            success=True,
            data={
                "total_cascades": total_cascades,
                "avg_depth": avg_depth,
                "max_depth": max_depth,
                "top_spreaders": top_spreaders,
            },
            meta={"session_id": session_id, "round_range": [round_start, round_end]},
        )
    except Exception as exc:
        logger.exception("get_contagion_stats failed for session %s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


# ---------------------------------------------------------------------------
# Confidence Assessment (Phase 18)
# ---------------------------------------------------------------------------


@router.get("/{session_id}/confidence-report", response_model=APIResponse)
async def get_confidence_report(session_id: str) -> APIResponse:
    """Return confidence assessment for a simulation session."""
    import dataclasses  # noqa: PLC0415

    from backend.app.services.confidence_assessor import ConfidenceAssessor  # noqa: PLC0415

    try:
        assessor = ConfidenceAssessor()
        report = await assessor.assess(session_id)
        return APIResponse(
            success=True,
            data=dataclasses.asdict(report),
            meta={"session_id": session_id},
        )
    except Exception as exc:
        logger.exception("get_confidence_report failed for session %s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


# ---------------------------------------------------------------------------
# Evidence search (Phase 4)
# ---------------------------------------------------------------------------


@router.get("/{session_id}/evidence-search", response_model=APIResponse)
async def evidence_search(
    session_id: str,
    q: str,
    limit: int = 20,
) -> APIResponse:
    """Search across agent memories, KG nodes, and simulation actions."""
    from backend.app.utils.db import get_db  # noqa: PLC0415

    if not q.strip():
        raise HTTPException(status_code=400, detail="Query parameter 'q' is required")

    search_term = f"%{q}%"

    try:
        async with get_db() as db:
            # Search agent memories
            memory_rows = await (
                await db.execute(
                    """SELECT am.id, am.agent_id, am.content, am.salience_score,
                              am.round_number, ap.oasis_username
                       FROM agent_memories am
                       LEFT JOIN agent_profiles ap ON ap.id = am.agent_id
                       WHERE am.session_id = ? AND am.content LIKE ?
                       ORDER BY am.salience_score DESC LIMIT ?""",
                    (session_id, search_term, min(limit, 200)),
                )
            ).fetchall()

            # Search KG nodes (nodes belong to graph, tied to session via simulation_sessions)
            node_rows = await (
                await db.execute(
                    """SELECT id, label, entity_type, description, weight
                       FROM kg_nodes
                       WHERE graph_id IN (
                           SELECT id FROM simulation_sessions WHERE id = ?
                       ) AND (label LIKE ? OR description LIKE ?)
                       LIMIT ?""",
                    (session_id, search_term, search_term, min(limit, 200)),
                )
            ).fetchall()

            # Search simulation actions
            action_rows = await (
                await db.execute(
                    """SELECT sa.id, sa.agent_id, sa.content, sa.sentiment,
                              sa.round_number, ap.oasis_username
                       FROM simulation_actions sa
                       LEFT JOIN agent_profiles ap ON ap.id = sa.agent_id
                       WHERE sa.session_id = ? AND sa.content LIKE ?
                       ORDER BY sa.round_number DESC LIMIT ?""",
                    (session_id, search_term, min(limit, 200)),
                )
            ).fetchall()

        return APIResponse(
            success=True,
            data={
                "query": q,
                "memories": [dict(r) for r in memory_rows],
                "graph_nodes": [dict(r) for r in node_rows],
                "actions": [dict(r) for r in action_rows],
            },
            meta={
                "session_id": session_id,
                "memory_count": len(memory_rows),
                "node_count": len(node_rows),
                "action_count": len(action_rows),
            },
        )
    except Exception as exc:
        logger.exception("evidence_search failed for session %s q=%s", session_id, q)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


# ---------------------------------------------------------------------------
# New read-only endpoints: factions, tipping-points, multi-run (Phase B)
# ---------------------------------------------------------------------------


@router.get("/{simulation_id}/factions", response_model=APIResponse)
async def get_faction_snapshots(simulation_id: str) -> APIResponse:
    """Return all faction snapshots for a kg_driven simulation."""
    from backend.app.utils.db import get_db  # noqa: PLC0415

    try:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT * FROM faction_snapshots_v2 WHERE simulation_id = ? ORDER BY round_number",
                (simulation_id,),
            )
            rows = await cursor.fetchall()
        return APIResponse(
            success=True,
            data={"simulation_id": simulation_id, "snapshots": [dict(r) for r in (rows or [])]},
            meta={"simulation_id": simulation_id},
        )
    except Exception as exc:
        logger.exception("get_faction_snapshots failed for simulation %s", simulation_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{simulation_id}/tipping-points", response_model=APIResponse)
async def get_tipping_points(simulation_id: str) -> APIResponse:
    """Return all tipping points detected for a simulation."""
    from backend.app.utils.db import get_db  # noqa: PLC0415

    try:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT * FROM tipping_points WHERE simulation_id = ? ORDER BY round_number",
                (simulation_id,),
            )
            rows = await cursor.fetchall()
        return APIResponse(
            success=True,
            data={"simulation_id": simulation_id, "tipping_points": [dict(r) for r in (rows or [])]},
            meta={"simulation_id": simulation_id},
        )
    except Exception as exc:
        logger.exception("get_tipping_points failed for simulation %s", simulation_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{simulation_id}/multi-run", response_model=APIResponse)
async def get_multi_run_result(simulation_id: str) -> APIResponse:
    """Return Phase B ensemble result for a simulation."""
    from backend.app.utils.db import get_db  # noqa: PLC0415

    try:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT * FROM multi_run_results WHERE simulation_id = ? ORDER BY created_at DESC LIMIT 1",
                (simulation_id,),
            )
            row = await cursor.fetchone()
        result = dict(row) if row else None
        return APIResponse(
            success=True,
            data={"simulation_id": simulation_id, "result": result},
            meta={"simulation_id": simulation_id},
        )
    except Exception as exc:
        logger.exception("get_multi_run_result failed for simulation %s", simulation_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


async def _load_canonical_inputs(
    simulation_id: str,
) -> tuple[int, list[str], dict[str, dict[str, list[float]]]]:
    """Load Phase B inputs from DB: round_count, scenario_outcomes, raw_belief_data."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT current_round FROM simulation_sessions WHERE id = ?",
            (simulation_id,),
        )
        sess_row = await cur.fetchone()
        round_count = int(sess_row["current_round"] or 20) if sess_row else 20

        cur2 = await db.execute(
            "SELECT DISTINCT decision_type FROM agent_decisions "
            "WHERE session_id = ? LIMIT 10",
            (simulation_id,),
        )
        decision_rows = await cur2.fetchall()

        cur3 = await db.execute(
            "SELECT agent_id, topic, stance FROM belief_states "
            "WHERE session_id = ? ORDER BY round_number DESC",
            (simulation_id,),
        )
        belief_rows = await cur3.fetchall()

    scenario_outcomes = [r["decision_type"] for r in decision_rows if r["decision_type"]]
    if not scenario_outcomes:
        scenario_outcomes = list(_DEFAULT_SCENARIO_OUTCOMES)

    raw: dict[str, dict[str, list[float]]] = {}
    for r in belief_rows:
        raw.setdefault(str(r["agent_id"]), {}).setdefault(r["topic"], []).append(float(r["stance"]))

    return round_count, scenario_outcomes, raw


def _build_belief_dists(
    raw: dict[str, dict[str, list[float]]],
) -> tuple[tuple[str, ...], dict[str, dict[str, tuple[float, float]]]]:
    """Build agent belief distributions from raw stance data."""
    dists = {
        aid: {
            topic: (
                sum(vals) / len(vals),
                max(0.05, (max(vals) - min(vals)) / 2),
            )
            for topic, vals in topics.items()
        }
        for aid, topics in raw.items()
    }
    metrics = tuple({t for topics in dists.values() for t in topics})
    return metrics, dists


@router.post("/{simulation_id}/multi-run", status_code=202)
async def trigger_multi_run(simulation_id: str) -> APIResponse:
    """Trigger Phase B stochastic ensemble for a completed simulation."""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, status, sim_mode FROM simulation_sessions WHERE id = ?",
            (simulation_id,),
        )
        row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    async def _run_phase_b() -> None:
        import json as _json  # noqa: PLC0415
        try:
            from backend.app.services.multi_run_orchestrator import (  # noqa: PLC0415
                CanonicalResult,
                MultiRunOrchestrator,
            )

            round_count, scenario_outcomes, raw = await _load_canonical_inputs(simulation_id)
            metrics, agent_belief_dists = _build_belief_dists(raw)

            canonical = CanonicalResult(
                simulation_id=simulation_id,
                scenario_metrics=metrics,
                agent_belief_distributions=agent_belief_dists,
                scenario_outcomes=scenario_outcomes,
                round_count=round_count,
            )
            orchestrator = MultiRunOrchestrator()
            result = await orchestrator.run(canonical, trial_count=100)

            async with get_db() as db:
                await db.execute(
                    """INSERT OR REPLACE INTO multi_run_results
                       (id, simulation_id, trial_count,
                        outcome_distribution_json, most_common_path_json,
                        confidence_intervals_json, avg_tipping_point_round,
                        faction_stability_score, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                    (
                        f"mr_{simulation_id}",
                        simulation_id,
                        result.trial_count,
                        _json.dumps(result.outcome_distribution),
                        _json.dumps(result.most_common_path),
                        _json.dumps({k: list(v) for k, v in result.confidence_intervals.items()}),
                        result.avg_tipping_point_round,
                        result.faction_stability_score,
                    ),
                )
                await db.commit()
        except Exception:
            logger.exception("Phase B failed for session %s", simulation_id)

    asyncio.create_task(_run_phase_b())
    return APIResponse(
        success=True,
        data={"simulation_id": simulation_id, "status": "queued"},
        meta={"simulation_id": simulation_id},
    )


@router.get("/{simulation_id}/world-events", response_model=APIResponse)
async def get_world_events(simulation_id: str) -> APIResponse:
    """Return all world events generated for a kg_driven simulation."""
    try:
        async with get_db() as db:
            # Check session exists first
            cur = await db.execute(
                "SELECT id FROM simulation_sessions WHERE id = ?",
                (simulation_id,),
            )
            if not await cur.fetchone():
                raise HTTPException(status_code=404, detail="Session not found")
            cursor = await db.execute(
                "SELECT * FROM world_events WHERE simulation_id = ? ORDER BY round_number",
                (simulation_id,),
            )
            rows = await cursor.fetchall()
        return APIResponse(
            success=True,
            data={"simulation_id": simulation_id, "events": [dict(r) for r in (rows or [])]},
            meta={"simulation_id": simulation_id},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("get_world_events failed for simulation %s", simulation_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc
