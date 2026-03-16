"""Branch, compare, scenario scan, and Monte Carlo endpoints for simulation."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app.models.request import BranchRequest
from backend.app.models.response import APIResponse
from backend.app.utils.logger import get_logger

router = APIRouter(prefix="/simulation", tags=["simulation"])
logger = get_logger("api.simulation_branches")


@router.post("/{session_id}/branch", response_model=APIResponse)
async def create_branch(session_id: str, req: BranchRequest | None = None) -> APIResponse:
    """Create a branch from an existing simulation session."""
    import json as _json  # noqa: PLC0415
    import uuid as _uuid  # noqa: PLC0415
    from backend.app.utils.db import get_db  # noqa: PLC0415

    if req is None:
        req = BranchRequest()

    try:
        async with get_db() as db:
            row = await (
                await db.execute(
                    "SELECT config_json, scenario_type FROM simulation_sessions WHERE id = ?",
                    (session_id,),
                )
            ).fetchone()

        if row is None:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

        branch_id = str(_uuid.uuid4())
        orig_cfg = _json.loads(row["config_json"]) if row["config_json"] else {}

        branch_cfg: dict = {**orig_cfg, "parent_session_id": session_id}
        if req.fork_round is not None:
            branch_cfg["fork_round"] = req.fork_round
        if req.shock_overrides is not None:
            branch_cfg["shocks"] = req.shock_overrides

        branch_label = req.label.strip() if req.label else f"Branch from {session_id[:8]}"

        async with get_db() as db:
            await db.execute(
                """INSERT INTO simulation_sessions
                   (id, name, sim_mode, scenario_type, status, config_json,
                    agent_count, round_count, llm_provider, llm_model,
                    oasis_db_path, created_at)
                   VALUES (?, ?, 'parallel', ?, 'created', ?,
                           ?, ?, ?, ?,
                           '', datetime('now'))""",
                (
                    branch_id, branch_label, row["scenario_type"],
                    _json.dumps(branch_cfg),
                    orig_cfg.get("agent_count", 0),
                    orig_cfg.get("round_count", 0),
                    orig_cfg.get("llm_provider", "openrouter"),
                    orig_cfg.get("llm_model", "deepseek/deepseek-v3.2"),
                ),
            )

            await db.execute(
                """INSERT INTO agent_profiles
                   (id, session_id, agent_type, age, sex, district, occupation,
                    income_bracket, education_level, marital_status, housing_type,
                    openness, conscientiousness, extraversion, agreeableness,
                    neuroticism, monthly_income, savings, oasis_persona,
                    oasis_username, created_at)
                   SELECT
                    NULL, ?, agent_type, age, sex, district, occupation,
                    income_bracket, education_level, marital_status, housing_type,
                    openness, conscientiousness, extraversion, agreeableness,
                    neuroticism, monthly_income, savings, oasis_persona,
                    oasis_username, datetime('now')
                   FROM agent_profiles WHERE session_id = ?""",
                (branch_id, session_id),
            )

            if req.fork_round is not None:
                await db.execute(
                    """INSERT INTO agent_memories
                       (session_id, agent_id, round_number, memory_text,
                        salience_score, memory_type, created_at)
                       SELECT ?, agent_id, round_number, memory_text,
                              salience_score, memory_type, datetime('now')
                       FROM agent_memories
                       WHERE session_id = ? AND round_number <= ?""",
                    (branch_id, session_id, req.fork_round),
                )
                await db.execute(
                    """INSERT INTO simulation_actions
                       (session_id, round_number, agent_id, oasis_username,
                        action_type, platform, content, target_agent_username,
                        sentiment, topics, post_id, created_at)
                       SELECT ?, round_number, agent_id, oasis_username,
                              action_type, platform, content, target_agent_username,
                              sentiment, topics, post_id, datetime('now')
                       FROM simulation_actions
                       WHERE session_id = ? AND round_number <= ?""",
                    (branch_id, session_id, req.fork_round),
                )
            else:
                await db.execute(
                    """INSERT INTO agent_memories
                       (session_id, agent_id, round_number, memory_text,
                        salience_score, memory_type, created_at)
                       SELECT ?, agent_id, round_number, memory_text,
                              salience_score, memory_type, datetime('now')
                       FROM agent_memories WHERE session_id = ?""",
                    (branch_id, session_id),
                )
                await db.execute(
                    """INSERT INTO simulation_actions
                       (session_id, round_number, agent_id, oasis_username,
                        action_type, platform, content, target_agent_username,
                        sentiment, topics, post_id, created_at)
                       SELECT ?, round_number, agent_id, oasis_username,
                              action_type, platform, content, target_agent_username,
                              sentiment, topics, post_id, datetime('now')
                       FROM simulation_actions WHERE session_id = ?""",
                    (branch_id, session_id),
                )

            try:
                await db.execute(
                    """INSERT OR IGNORE INTO scenario_branches
                       (parent_session_id, branch_session_id, scenario_variant,
                        label, fork_round, created_at)
                       VALUES (?, ?, 'branch', ?, ?, datetime('now'))""",
                    (session_id, branch_id, branch_label, req.fork_round),
                )
            except Exception:
                await db.execute(
                    """INSERT OR IGNORE INTO scenario_branches
                       (parent_session_id, branch_session_id, scenario_variant,
                        label, created_at)
                       VALUES (?, ?, 'branch', ?, datetime('now'))""",
                    (session_id, branch_id, branch_label),
                )
            await db.commit()

        return APIResponse(
            success=True,
            data={
                "branch_id": branch_id,
                "parent_session_id": session_id,
                "fork_round": req.fork_round,
                "label": branch_label,
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("create_branch failed for session %s", session_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{session_id}/branches", response_model=APIResponse)
async def list_branches(session_id: str) -> APIResponse:
    """List all branches created from a parent session."""
    from backend.app.utils.db import get_db  # noqa: PLC0415

    try:
        async with get_db() as db:
            rows = await (
                await db.execute(
                    """SELECT sb.branch_session_id, sb.label, sb.fork_round,
                              sb.created_at, ss.status
                       FROM scenario_branches sb
                       LEFT JOIN simulation_sessions ss ON ss.id = sb.branch_session_id
                       WHERE sb.parent_session_id = ?
                       ORDER BY sb.created_at""",
                    (session_id,),
                )
            ).fetchall()

        branches = [
            {
                "branch_session_id": r["branch_session_id"],
                "label": r["label"],
                "fork_round": r["fork_round"],
                "created_at": r["created_at"],
                "status": r["status"],
            }
            for r in rows
        ]
        return APIResponse(
            success=True,
            data=branches,
            meta={"parent_session_id": session_id, "count": len(branches)},
        )
    except Exception as exc:
        logger.exception("list_branches failed for session %s", session_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/compare/{session_a}/{session_b}", response_model=APIResponse)
async def compare_sessions(session_a: str, session_b: str) -> APIResponse:
    """Compare two simulation sessions."""
    import json as _json  # noqa: PLC0415
    from backend.app.utils.db import get_db  # noqa: PLC0415

    try:
        async with get_db() as db:

            async def _session_meta(sid: str) -> dict:
                row = await (
                    await db.execute(
                        "SELECT config_json, status, scenario_type FROM simulation_sessions WHERE id = ?",
                        (sid,),
                    )
                ).fetchone()
                if row is None:
                    return {}
                cfg = _json.loads(row["config_json"]) if row["config_json"] else {}
                return {
                    "session_id": sid,
                    "status": row["status"],
                    "scenario_type": row["scenario_type"],
                    "agent_count": cfg.get("agent_count", 0),
                    "round_count": cfg.get("round_count", 0),
                }

            async def _sentiment_by_round(sid: str) -> list:
                srows = await (
                    await db.execute(
                        """SELECT round_number,
                                  SUM(CASE WHEN sentiment='positive' THEN 1 ELSE 0 END) as pos,
                                  SUM(CASE WHEN sentiment='negative' THEN 1 ELSE 0 END) as neg,
                                  SUM(CASE WHEN sentiment='neutral'  THEN 1 ELSE 0 END) as neu,
                                  COUNT(*) as total
                           FROM simulation_actions
                           WHERE session_id = ?
                           GROUP BY round_number
                           ORDER BY round_number""",
                        (sid,),
                    )
                ).fetchall()
                return [dict(r) for r in srows]

            async def _key_events(sid: str) -> list:
                rows = await (
                    await db.execute(
                        """SELECT round_number, oasis_username, platform, content,
                                  sentiment, topics
                           FROM simulation_actions
                           WHERE session_id = ?
                             AND sentiment IN ('positive', 'negative')
                           ORDER BY
                             CASE WHEN sentiment = 'negative' THEN 1 ELSE 2 END,
                             length(content) DESC
                           LIMIT 5""",
                        (sid,),
                    )
                ).fetchall()
                return [dict(r) for r in rows]

            async def _memory_divergence(sid: str) -> dict:
                rows = await (
                    await db.execute(
                        """SELECT memory_type, COUNT(*) as count
                           FROM agent_memories
                           WHERE session_id = ?
                           GROUP BY memory_type""",
                        (sid,),
                    )
                ).fetchall()
                themes = {r["memory_type"]: r["count"] for r in rows}
                return {
                    "unique_themes": len(themes),
                    "total_memories": sum(themes.values()),
                    "theme_breakdown": themes,
                }

            async def _agent_sentiment_distribution(sid: str) -> dict:
                rows = await (
                    await db.execute(
                        """SELECT sentiment, COUNT(*) as count
                           FROM simulation_actions
                           WHERE session_id = ?
                           GROUP BY sentiment""",
                        (sid,),
                    )
                ).fetchall()
                dist = {r["sentiment"]: r["count"] for r in rows}
                total = sum(dist.values())
                return {
                    "positive": dist.get("positive", 0),
                    "negative": dist.get("negative", 0),
                    "neutral": dist.get("neutral", 0),
                    "total": total,
                }

            async def _fork_info(sid_a: str, sid_b: str) -> dict | None:
                row = await (
                    await db.execute(
                        """SELECT fork_round, label FROM scenario_branches
                           WHERE (parent_session_id = ? AND branch_session_id = ?)
                              OR (parent_session_id = ? AND branch_session_id = ?)
                           LIMIT 1""",
                        (sid_a, sid_b, sid_b, sid_a),
                    )
                ).fetchone()
                if row is None:
                    return None
                return {"fork_round": row["fork_round"], "label": row["label"]}

            meta_a, meta_b = await _session_meta(session_a), await _session_meta(session_b)
            sent_a, sent_b = await _sentiment_by_round(session_a), await _sentiment_by_round(session_b)
            events_a, events_b = await _key_events(session_a), await _key_events(session_b)
            mdiv_a, mdiv_b = await _memory_divergence(session_a), await _memory_divergence(session_b)
            asd_a, asd_b = (
                await _agent_sentiment_distribution(session_a),
                await _agent_sentiment_distribution(session_b),
            )
            fork_info = await _fork_info(session_a, session_b)

        return APIResponse(
            success=True,
            data={
                "session_a": {
                    **meta_a,
                    "sentiment_by_round": sent_a,
                    "key_events": events_a,
                    "memory_divergence": mdiv_a,
                    "agent_sentiment_distribution": asd_a,
                },
                "session_b": {
                    **meta_b,
                    "sentiment_by_round": sent_b,
                    "key_events": events_b,
                    "memory_divergence": mdiv_b,
                    "agent_sentiment_distribution": asd_b,
                },
                "fork_info": fork_info,
            },
        )
    except Exception as exc:
        logger.exception("compare_sessions failed for %s vs %s", session_a, session_b)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Scenario Scan endpoint (Phase 2A)
# ---------------------------------------------------------------------------

@router.post("/{session_id}/scan", response_model=APIResponse)
async def scan_scenarios(session_id: str, body: dict | None = None) -> APIResponse:
    """Auto-scan parameter space and create multiple branches."""
    from backend.app.services.scenario_scanner import ScenarioScanner  # noqa: PLC0415

    body = body or {}
    try:
        scanner = ScenarioScanner()
        branch_ids = await scanner.scan(
            session_id=session_id,
            parameter_space=body.get("parameter_space", {}),
            max_variants=body.get("max_variants", 10),
        )
        return APIResponse(
            success=True,
            data={"branch_ids": branch_ids, "count": len(branch_ids)},
            meta={"session_id": session_id},
        )
    except Exception as exc:
        logger.exception("scan_scenarios failed for session %s", session_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Monte Carlo endpoint (Phase 2B)
# ---------------------------------------------------------------------------

@router.post("/{session_id}/monte-carlo", response_model=APIResponse)
async def run_monte_carlo(session_id: str, body: dict | None = None) -> APIResponse:
    """Run Monte Carlo uncertainty quantification on a completed session."""
    from backend.app.services.monte_carlo import MonteCarloEngine  # noqa: PLC0415

    body = body or {}
    try:
        engine = MonteCarloEngine()
        results = await engine.run(
            session_id=session_id,
            n_trials=body.get("n_trials", 100),
            metrics=body.get("metrics"),
        )
        return APIResponse(
            success=True,
            data=results,
            meta={"session_id": session_id},
        )
    except Exception as exc:
        logger.exception("run_monte_carlo failed for session %s", session_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{session_id}/ensemble-results", response_model=APIResponse)
async def get_ensemble_results(session_id: str) -> APIResponse:
    """Retrieve stored ensemble (Monte Carlo) results."""
    from backend.app.utils.db import get_db  # noqa: PLC0415

    try:
        async with get_db() as db:
            rows = await (
                await db.execute(
                    """SELECT metric_name, n_trials, p10, p25, p50, p75, p90, created_at
                       FROM ensemble_results
                       WHERE session_id = ?
                       ORDER BY created_at DESC""",
                    (session_id,),
                )
            ).fetchall()
        return APIResponse(
            success=True,
            data=[dict(r) for r in rows],
            meta={"session_id": session_id, "count": len(rows)},
        )
    except Exception as exc:
        logger.exception("get_ensemble_results failed for session %s", session_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Real Ensemble endpoints (Phase A) — spawns actual simulation trials
# ---------------------------------------------------------------------------


@router.post("/{session_id}/ensemble", response_model=APIResponse)
async def run_real_ensemble(
    session_id: str,
    body: dict | None = None,
) -> APIResponse:
    """Run a real Monte Carlo ensemble by spawning N trial simulations.

    Unlike ``POST /{id}/monte-carlo`` (statistical MC), this endpoint
    actually runs the OASIS simulation for each trial with Gaussian-perturbed
    MacroState fields.

    Request body (all optional):
        n_trials (int): Number of trials to run (default 20, max 50).
        perturbation_std (float): Gaussian σ as fraction of field value (default 0.05).

    Returns:
        EnsembleResult with percentile bands for each perturbable macro field.
    """
    from backend.app.services.ensemble_runner import EnsembleRunner  # noqa: PLC0415

    body = body or {}
    n_trials: int = int(body.get("n_trials", 20))
    perturbation_std: float = float(body.get("perturbation_std", 0.05))

    try:
        runner = EnsembleRunner()
        result = await runner.run_ensemble(
            session_id=session_id,
            n_trials=n_trials,
            perturbation_std=perturbation_std,
        )
        return APIResponse(
            success=True,
            data=result.to_dict(),
            meta={
                "session_id": session_id,
                "n_trials": result.n_trials,
                "metric_count": len(result.distributions),
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("run_real_ensemble failed for session %s", session_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{session_id}/ensemble/results", response_model=APIResponse)
async def get_real_ensemble_results(session_id: str) -> APIResponse:
    """Retrieve real-ensemble results and probability statements.

    Returns both the stored DistributionBands (from ensemble_results table)
    and auto-generated Traditional Chinese probability statements for each
    metric.

    Returns:
        {
          "distributions": [...DistributionBand dicts],
          "probability_statements": [...ProbabilityStatement dicts],
          "trial_metadata": [...TrialRecord dicts],
        }
    """
    from backend.app.services.ensemble_analyzer import EnsembleAnalyzer  # noqa: PLC0415
    from backend.app.services.ensemble_runner import EnsembleRunner  # noqa: PLC0415
    from backend.app.models.ensemble import DistributionBand  # noqa: PLC0415
    from backend.app.utils.db import get_db  # noqa: PLC0415

    try:
        # Load stored distribution bands (create table if not yet migrated)
        async with get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS ensemble_results (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    n_trials   INTEGER NOT NULL,
                    metric_name TEXT NOT NULL,
                    p10 REAL, p25 REAL, p50 REAL, p75 REAL, p90 REAL,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)
            rows = await (
                await db.execute(
                    """
                    SELECT metric_name, n_trials, p10, p25, p50, p75, p90
                    FROM ensemble_results
                    WHERE session_id = ?
                    ORDER BY created_at DESC
                    """,
                    (session_id,),
                )
            ).fetchall()

        if not rows:
            return APIResponse(
                success=True,
                data={
                    "distributions": [],
                    "probability_statements": [],
                    "trial_metadata": [],
                },
                meta={"session_id": session_id, "message": "尚未有集成結果，請先運行 POST /{id}/ensemble"},
            )

        bands: list[DistributionBand] = []
        for row in rows:
            r = dict(row)
            bands.append(DistributionBand(
                metric_name=r["metric_name"],
                p10=r["p10"] or 0.0,
                p25=r["p25"] or 0.0,
                p50=r["p50"] or 0.0,
                p75=r["p75"] or 0.0,
                p90=r["p90"] or 0.0,
            ))
        n_trials: int = rows[0]["n_trials"] if rows else 0

        # Generate probability statements
        analyzer = EnsembleAnalyzer()
        probability_statements = analyzer.generate_all_statements(bands)

        # Fetch trial metadata
        runner = EnsembleRunner()
        trial_metadata = await runner.get_trial_metadata(session_id)

        return APIResponse(
            success=True,
            data={
                "distributions": [b.to_dict() for b in bands],
                "probability_statements": probability_statements,
                "trial_metadata": trial_metadata,
            },
            meta={
                "session_id": session_id,
                "n_trials": n_trials,
                "metric_count": len(bands),
            },
        )
    except Exception as exc:
        logger.exception("get_real_ensemble_results failed for session %s", session_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
