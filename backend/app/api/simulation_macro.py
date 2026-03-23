"""Macro-economic history and forecast endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path

from backend.app.models.response import APIResponse
from backend.app.utils.logger import get_logger

router = APIRouter(prefix="/simulation", tags=["simulation"])
logger = get_logger("api.simulation_macro")


@router.get("/{session_id}/macro-history", response_model=APIResponse)
async def get_macro_history(
    session_id: str = Path(..., pattern=r"^[a-f0-9\-]{8,36}$"),
    round_number: int | None = None,
) -> APIResponse:
    """Get macro indicator history across rounds for a session."""
    from backend.app.services.macro_history import MacroHistoryService  # noqa: PLC0415

    try:
        service = MacroHistoryService()

        if round_number is not None:
            snapshot = await service.get_snapshot(session_id, round_number)
            if snapshot is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"No macro snapshot for session={session_id} round={round_number}",
                )
            return APIResponse(
                success=True,
                data=snapshot,
                meta={"session_id": session_id, "round_number": round_number},
            )

        history = await service.get_history(session_id)
        return APIResponse(
            success=True,
            data=history,
            meta={"session_id": session_id, "count": len(history)},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("get_macro_history failed for session %s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/forecast/{metric}", response_model=APIResponse)
async def get_forecast(
    metric: str,
    horizon: int = 12,
) -> APIResponse:
    """Get time-series forecast for a macro indicator."""
    from backend.app.services.time_series_forecaster import TimeSeriesForecaster  # noqa: PLC0415

    try:
        forecaster = TimeSeriesForecaster()
        result = await forecaster.forecast(metric=metric, horizon=horizon)
        return APIResponse(
            success=True,
            data=result.to_dict(),
            meta={"metric": metric, "horizon": horizon},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Bad request") from exc
    except Exception as exc:
        logger.exception("get_forecast failed for metric %s", metric)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/forecast/{metric}/naive", response_model=APIResponse)
async def get_naive_forecast(
    metric: str,
    horizon: int = 12,
    method: str = "drift",
) -> APIResponse:
    """Get a naive baseline forecast (no ARIMA/statsforecast required).

    Args:
        metric: Metric key.
        horizon: Number of periods ahead (1-24).
        method: Naive method — one of 'last_value', 'drift', 'mean'.
    """
    from backend.app.services.naive_forecaster import NaiveForecaster  # noqa: PLC0415
    from backend.app.services.time_series_forecaster import TimeSeriesForecaster  # noqa: PLC0415

    try:
        ts = TimeSeriesForecaster()
        history = await ts._load_history(metric)
        values = [v for _, v in history] if history else []
        if not values:
            raise HTTPException(status_code=404, detail="No historical data for metric")

        forecaster = NaiveForecaster()
        horizon = max(1, min(horizon, 24))
        point_values = forecaster.forecast(values, horizon=horizon, method=method)
        return APIResponse(
            success=True,
            data={
                "metric": metric,
                "method": method,
                "horizon": horizon,
                "forecasts": [round(v, 4) for v in point_values],
                "last_observed": round(values[-1], 4),
                "n_historical": len(values),
            },
            meta={"metric": metric, "method": method},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Bad request") from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("get_naive_forecast failed for metric %s", metric)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/forecast/{metric}/backtest", response_model=APIResponse)
async def get_forecast_backtest(
    metric: str,
    train_end: str = "2022-Q4",
    horizon: int = 8,
) -> APIResponse:
    """Run walk-forward backtest for a macro indicator forecast.

    Trains on data up to *train_end*, predicts *horizon* periods, and
    compares predictions against DB actuals. Returns MAPE, RMSE, and
    Directional Accuracy alongside a per-period prediction trace.

    Args:
        metric: Metric key — one of ccl_index, unemployment_rate, hsi_level,
                cpi_yoy, gdp_growth, consumer_confidence.
        train_end: Last period included in training (default ``"2022-Q4"``).
        horizon: Number of test periods to evaluate (1–24, default 8).
    """
    from backend.app.services.backtester import Backtester  # noqa: PLC0415

    try:
        backtester = Backtester()
        result = await backtester.run(
            metric=metric,
            train_end=train_end,
            horizon=horizon,
        )
        return APIResponse(
            success=True,
            data=result.to_dict(),
            meta={
                "metric": metric,
                "train_end": train_end,
                "horizon": horizon,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Bad request") from exc
    except Exception as exc:
        logger.exception("get_forecast_backtest failed for metric %s", metric)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/forecast/hsi-decomposition", response_model=APIResponse)
async def get_hsi_decomposition(
    n_quarters: int = 20,
) -> APIResponse:
    """Decompose HSI returns into fundamental vs sentiment components.

    Uses OLS regression: ``hsi_return ~ gdp_growth + hibor_change``.
    The residual is attributed to sentiment.

    Args:
        n_quarters: Number of quarterly periods to include (default 20).
    """
    try:
        from backend.app.config import get_settings  # noqa: PLC0415
        from backend.app.services.hsi_decomposer import HSIDecomposer  # noqa: PLC0415

        settings = get_settings()
        decomposer = HSIDecomposer(db_path=settings.DATABASE_PATH)
        result = await decomposer.decompose(n_quarters=n_quarters)
        return APIResponse(
            success=True,
            data=result.to_dict(),
            meta={"n_quarters": n_quarters},
        )
    except ImportError:
        raise HTTPException(status_code=501, detail="HSI decomposition feature not available") from None
    except Exception as exc:
        logger.exception("get_hsi_decomposition failed")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


# ---------------------------------------------------------------------------
# External Data Feed
# ---------------------------------------------------------------------------


@router.get("/data/external-feed", response_model=APIResponse)
async def get_external_feed(force_refresh: bool = False) -> APIResponse:
    """Fetch live FRED / World Bank / Taiwan Strait risk data."""
    try:
        from backend.app.services.external_data_feed import ExternalDataFeed  # noqa: PLC0415

        feed = ExternalDataFeed()
        data = await feed.fetch_with_db_fallback()
        return APIResponse(success=True, data=data, meta={"source": "external_data_feed"})
    except ImportError:
        raise HTTPException(status_code=501, detail="External data feed not available") from None
    except Exception as exc:
        logger.exception("get_external_feed failed")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


# ---------------------------------------------------------------------------
# Sensitivity Analysis
# ---------------------------------------------------------------------------


@router.post("/sensitivity-analysis", response_model=APIResponse)
async def run_sensitivity_analysis(req: dict) -> APIResponse:
    """Run parameter sensitivity sweep (+-25%) across calibrated coefficients."""
    try:
        from backend.app.services.sensitivity_analyzer import SensitivityAnalyzer  # noqa: PLC0415

        analyzer = SensitivityAnalyzer()
        period_start = req.get("period_start", "2021-Q1")
        period_end = req.get("period_end", "2023-Q4")
        result = await analyzer.run(period_start=period_start, period_end=period_end)
        return APIResponse(success=True, data=result, meta={"type": "grid_sweep"})
    except ImportError:
        raise HTTPException(status_code=501, detail="Sensitivity analyzer not available") from None
    except Exception as exc:
        logger.exception("run_sensitivity_analysis failed")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.post("/sensitivity-sobol", response_model=APIResponse)
async def run_sensitivity_sobol(req: dict) -> APIResponse:
    """Run Sobol global sensitivity analysis (requires SALib)."""
    try:
        from backend.app.services.sensitivity_analyzer import SensitivityAnalyzer  # noqa: PLC0415

        analyzer = SensitivityAnalyzer()
        period_start = req.get("period_start", "2021-Q1")
        period_end = req.get("period_end", "2023-Q4")
        n_samples = req.get("n_samples", 64)
        result = await analyzer.run_sobol(
            period_start=period_start,
            period_end=period_end,
            n_samples=n_samples,
        )
        import dataclasses  # noqa: PLC0415

        return APIResponse(success=True, data=dataclasses.asdict(result), meta={"type": "sobol"})
    except ImportError:
        raise HTTPException(status_code=501, detail="Sobol analysis not available (SALib required)") from None
    except Exception as exc:
        logger.exception("run_sensitivity_sobol failed")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.post("/{session_id}/surrogate-forecast", response_model=APIResponse)
async def run_surrogate_forecast(
    session_id: str,
    req: dict | None = None,
) -> APIResponse:
    """Run Monte Carlo using a surrogate model trained from Phase A data.

    For large trial counts (>200), uses a logistic regression surrogate
    to approximate outcome distributions instead of full simulation.

    Args:
        session_id: Phase A simulation session ID.
        req: Optional body with 'n_trials' (int) and 'metrics' (list[str]).
    """
    from backend.app.services.monte_carlo import MonteCarloEngine  # noqa: PLC0415

    try:
        body = req or {}
        n_trials = int(body.get("n_trials", 500))
        metrics = body.get("metrics")
        n_trials = max(10, min(n_trials, 5000))

        engine = MonteCarloEngine()
        result = await engine.run_with_surrogate(
            session_id=session_id,
            n_trials=n_trials,
            metrics=metrics,
        )
        return APIResponse(
            success=True,
            data=result,
            meta={"session_id": session_id, "n_trials": n_trials},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Bad request") from exc
    except Exception as exc:
        logger.exception("surrogate-forecast failed for session %s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


# ---------------------------------------------------------------------------
# Cross-Domain Validation
# ---------------------------------------------------------------------------


@router.get("/validation/cross-domain", response_model=APIResponse)
async def get_cross_domain_validation(
    period_start: str = "2021-Q1",
    period_end: str = "2023-Q4",
) -> APIResponse:
    """Validate engine across 3 domains (HK macro, US markets, geopolitical)."""
    try:
        from backend.app.services.cross_domain_validator import CrossDomainValidator  # noqa: PLC0415

        validator = CrossDomainValidator()
        result = await validator.validate_all(period_start=period_start, period_end=period_end)
        return APIResponse(success=True, data=result, meta={"type": "cross_domain"})
    except ImportError:
        raise HTTPException(status_code=501, detail="Cross-domain validator not available") from None
    except Exception as exc:
        logger.exception("get_cross_domain_validation failed")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/validation/domains", response_model=APIResponse)
async def list_validation_domains() -> APIResponse:
    """List available validation domains and their metric requirements."""
    try:
        from backend.app.services.cross_domain_validator import CrossDomainValidator  # noqa: PLC0415

        domains = CrossDomainValidator.list_domains()
        return APIResponse(success=True, data=domains, meta={})
    except ImportError:
        raise HTTPException(status_code=501, detail="Cross-domain validator not available") from None
    except Exception as exc:
        logger.exception("list_validation_domains failed")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


# ---------------------------------------------------------------------------
# Validation Report (A-F grade summary via ValidationReporter)
# ---------------------------------------------------------------------------


@router.get("/validation/report", response_model=APIResponse)
async def get_validation_report(
    period_start: str = "2021-Q1",
    period_end: str = "2023-Q4",
    metrics: str | None = None,
) -> APIResponse:
    """Return an A-F graded validation report via ValidationReporter.

    Wraps RetrospectiveValidator with composite scoring:
      30% directional accuracy + 30% |Pearson r| + 20% (1-MAPE) + 20% Brier skill.

    Query params:
        period_start: Start period in YYYY-QN format (default 2021-Q1).
        period_end: End period in YYYY-QN format (default 2023-Q4).
        metrics: Comma-separated list of metrics (optional; all if omitted).
    """
    try:
        from backend.app.services.validation_reporter import ValidationReporter  # noqa: PLC0415

        reporter = ValidationReporter()
        metric_list = [m.strip() for m in metrics.split(",")] if metrics else None
        report = await reporter.generate(
            period_start=period_start,
            period_end=period_end,
            metrics=metric_list,
        )
        return APIResponse(
            success=True,
            data=report,
            meta={
                "period_start": period_start,
                "period_end": period_end,
                "overall_grade": report.get("overall_grade", "N/A"),
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Bad request") from exc
    except Exception as exc:
        logger.exception("get_validation_report failed")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


# ---------------------------------------------------------------------------
# Retrospective Validation Pipeline
# ---------------------------------------------------------------------------


@router.get("/validation/retrospective", response_model=APIResponse)
async def get_retrospective_validation(
    period_start: str = "2020-Q1",
    period_end: str = "2020-Q4",
    metrics: str | None = None,
) -> APIResponse:
    """Run retrospective validation for a date range.

    Compares predicted macro trajectories against actual historical data
    from hk_data_snapshots.  Returns directional accuracy, Pearson r,
    MAPE, and timing offset per metric.

    Query params:
        period_start: Start period in YYYY-QN format (default 2020-Q1).
        period_end: End period in YYYY-QN format (default 2020-Q4).
        metrics: Comma-separated list of metrics to validate (optional).
    """
    from backend.app.services.retrospective_validator import RetrospectiveValidator  # noqa: PLC0415

    try:
        validator = RetrospectiveValidator()
        metric_list = [m.strip() for m in metrics.split(",")] if metrics else None
        results = await validator.validate(period_start, period_end, metric_list)

        if not results:
            return APIResponse(
                success=False,
                data=None,
                meta={
                    "error": "insufficient_historical_data",
                    "period_start": period_start,
                    "period_end": period_end,
                },
            )

        import dataclasses  # noqa: PLC0415

        return APIResponse(
            success=True,
            data=[dataclasses.asdict(r) for r in results],
            meta={
                "period_start": period_start,
                "period_end": period_end,
                "count": len(results),
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Bad request") from exc
    except Exception as exc:
        logger.exception("get_retrospective_validation failed")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


# ---------------------------------------------------------------------------
# Polarization Index (Phase 17)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# GraphRAG: Community Summaries + Global Narrative + Triple Conflicts (Phase 18)
# ---------------------------------------------------------------------------


@router.get("/{session_id}/community-summaries", response_model=APIResponse)
async def get_community_summaries(
    session_id: str,
    round_number: int | None = None,
) -> APIResponse:
    """Get community summaries for a session (latest round or specific round)."""
    from backend.app.utils.db import get_db  # noqa: PLC0415

    try:
        async with get_db() as db:
            # Ensure table exists
            await db.execute(
                """CREATE TABLE IF NOT EXISTS community_summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    round_number INTEGER NOT NULL,
                    cluster_id INTEGER NOT NULL,
                    core_narrative TEXT NOT NULL,
                    shared_anxieties TEXT NOT NULL DEFAULT '',
                    main_opposition TEXT NOT NULL DEFAULT '',
                    member_count INTEGER NOT NULL DEFAULT 0,
                    avg_trust REAL NOT NULL DEFAULT 0.0,
                    created_at TEXT DEFAULT (datetime('now')),
                    UNIQUE(session_id, round_number, cluster_id)
                )"""
            )

            if round_number is not None:
                cursor = await db.execute(
                    """SELECT * FROM community_summaries
                       WHERE session_id = ? AND round_number = ?
                       ORDER BY member_count DESC""",
                    (session_id, round_number),
                )
            else:
                cursor = await db.execute(
                    """SELECT * FROM community_summaries
                       WHERE session_id = ?
                       AND round_number = (
                           SELECT MAX(round_number) FROM community_summaries
                           WHERE session_id = ?
                       )
                       ORDER BY member_count DESC""",
                    (session_id, session_id),
                )
            rows = await cursor.fetchall()

        data = [
            {
                "cluster_id": r["cluster_id"],
                "round_number": r["round_number"],
                "core_narrative": r["core_narrative"],
                "shared_anxieties": r["shared_anxieties"],
                "main_opposition": r["main_opposition"],
                "member_count": r["member_count"],
                "avg_trust": r["avg_trust"],
            }
            for r in rows
        ]

        return APIResponse(
            success=True,
            data=data,
            meta={"session_id": session_id, "count": len(data)},
        )
    except Exception as exc:
        logger.exception("get_community_summaries failed for session %s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{session_id}/global-narrative", response_model=APIResponse)
async def get_global_narrative(
    session_id: str,
    round_number: int | None = None,
) -> APIResponse:
    """Generate and return a global narrative analysis across all communities."""
    try:
        from backend.app.services.graph_rag import GraphRAGService  # noqa: PLC0415

        service = GraphRAGService()
        narrative = await service.get_global_narrative(session_id, round_number)

        return APIResponse(
            success=True,
            data={
                "session_id": narrative.session_id,
                "round_number": narrative.round_number,
                "community_count": narrative.community_count,
                "narrative_text": narrative.narrative_text,
                "fault_lines": narrative.fault_lines,
            },
            meta={"session_id": session_id},
        )
    except Exception as exc:
        logger.exception("get_global_narrative failed for session %s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{session_id}/triple-conflicts", response_model=APIResponse)
async def get_triple_conflicts(
    session_id: str,
    min_agents: int = 3,
) -> APIResponse:
    """Get TKG triple conflicts (opposing predicate pairs across agents)."""
    import dataclasses  # noqa: PLC0415

    try:
        from backend.app.services.graph_rag import GraphRAGService  # noqa: PLC0415

        service = GraphRAGService()
        conflicts = await service.detect_triple_conflicts(session_id, min_agents)

        data = [dataclasses.asdict(c) for c in conflicts]

        return APIResponse(
            success=True,
            data=data,
            meta={"session_id": session_id, "count": len(data), "min_agents_per_side": min_agents},
        )
    except Exception as exc:
        logger.exception("get_triple_conflicts failed for session %s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{session_id}/polarization", response_model=APIResponse)
async def get_polarization(
    session_id: str,
    round_number: int | None = None,
) -> APIResponse:
    """Get polarization index for a specific round (or latest)."""
    import json as _json  # noqa: PLC0415

    from backend.app.utils.db import get_db  # noqa: PLC0415

    try:
        async with get_db() as db:
            if round_number is not None:
                cursor = await db.execute(
                    """SELECT * FROM polarization_snapshots
                       WHERE session_id = ? AND round_number = ?""",
                    (session_id, round_number),
                )
            else:
                cursor = await db.execute(
                    """SELECT * FROM polarization_snapshots
                       WHERE session_id = ?
                       ORDER BY round_number DESC LIMIT 1""",
                    (session_id,),
                )
            row = await cursor.fetchone()

        if not row:
            return APIResponse(
                success=True,
                data=None,
                meta={"session_id": session_id, "message": "No polarization data found"},
            )

        return APIResponse(
            success=True,
            data={
                "session_id": session_id,
                "round_number": row[2],
                "polarization_index": row[3],
                "modularity": row[4],
                "opinion_variance": row[5],
                "cross_cluster_hostility": row[6],
                "cluster_stances": _json.loads(row[7]) if row[7] else {},
            },
            meta={"session_id": session_id},
        )
    except Exception as exc:
        logger.exception("get_polarization failed for session %s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


# ---------------------------------------------------------------------------
# Phase 1C: Network Events (Dynamic Network Evolution)
# ---------------------------------------------------------------------------


@router.get("/{session_id}/network-events", response_model=APIResponse)
async def get_network_events(
    session_id: str,
    round_number: int | None = None,
    event_type: str | None = None,
    limit: int = 50,
) -> APIResponse:
    """Get network evolution events for a session.

    Query params:
        round_number: Filter to a specific round (optional).
        event_type: One of TIE_FORMED|TIE_DISSOLVED|BRIDGE_DETECTED|
            TRIADIC_CLOSURE|CLUSTER_SHIFT (optional).
        limit: Max events to return (default 50).
    """
    from backend.app.services.network_evolution import NetworkEvolutionEngine  # noqa: PLC0415

    try:
        engine = NetworkEvolutionEngine()
        events = await engine.get_events(
            session_id=session_id,
            round_number=round_number,
            event_type=event_type,
            limit=max(1, min(limit, 500)),
        )

        # Count per event type for stats summary
        type_counts: dict[str, int] = {}
        for e in events:
            type_counts[e.event_type] = type_counts.get(e.event_type, 0) + 1

        data = [
            {
                "session_id": e.session_id,
                "round_number": e.round_number,
                "event_type": e.event_type,
                "agent_a_username": e.agent_a_username,
                "agent_b_username": e.agent_b_username,
                "trust_delta": e.trust_delta,
                "details": e.details,
            }
            for e in events
        ]
        return APIResponse(
            success=True,
            data=data,
            meta={
                "session_id": session_id,
                "total_count": len(data),
                "event_type_counts": type_counts,
            },
        )
    except Exception as exc:
        logger.exception("get_network_events failed for session %s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


# ---------------------------------------------------------------------------
# Phase 2: Feed Ranking + Filter Bubble + Virality
# ---------------------------------------------------------------------------


@router.get("/{session_id}/feed/{agent_id}", response_model=APIResponse)
async def get_agent_feed(
    session_id: str,
    agent_id: int,
    round_number: int | None = None,
) -> APIResponse:
    """Get the ranked feed for a specific agent at a given round."""
    from backend.app.utils.db import get_db  # noqa: PLC0415

    try:
        async with get_db() as db:
            if round_number is not None:
                cursor = await db.execute(
                    """SELECT post_id, rank, score, round_number
                       FROM agent_feeds
                       WHERE session_id = ? AND agent_id = ? AND round_number = ?
                       ORDER BY rank""",
                    (session_id, agent_id, round_number),
                )
            else:
                cursor = await db.execute(
                    """SELECT post_id, rank, score, round_number
                       FROM agent_feeds
                       WHERE session_id = ? AND agent_id = ?
                         AND round_number = (
                             SELECT MAX(round_number) FROM agent_feeds
                             WHERE session_id = ? AND agent_id = ?
                         )
                       ORDER BY rank""",
                    (session_id, agent_id, session_id, agent_id),
                )
            rows = await cursor.fetchall()

        data = [
            {
                "post_id": r[0],
                "rank": r[1],
                "score": r[2],
                "round_number": r[3],
            }
            for r in rows
        ]
        return APIResponse(
            success=True,
            data=data,
            meta={
                "session_id": session_id,
                "agent_id": agent_id,
                "count": len(data),
            },
        )
    except Exception as exc:
        logger.exception("get_agent_feed failed for session %s agent %s", session_id, agent_id)
        logger.exception("Internal error in get_agent_feed")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{session_id}/filter-bubble", response_model=APIResponse)
async def get_filter_bubble(
    session_id: str,
    round_number: int | None = None,
) -> APIResponse:
    """Get filter bubble snapshot for a session (latest or specific round)."""
    from backend.app.utils.db import get_db  # noqa: PLC0415

    try:
        async with get_db() as db:
            if round_number is not None:
                cursor = await db.execute(
                    """SELECT round_number, avg_bubble_score, median_bubble_score,
                              pct_in_bubble, algorithm, gini_coefficient
                       FROM filter_bubble_snapshots
                       WHERE session_id = ? AND round_number = ?""",
                    (session_id, round_number),
                )
            else:
                cursor = await db.execute(
                    """SELECT round_number, avg_bubble_score, median_bubble_score,
                              pct_in_bubble, algorithm, gini_coefficient
                       FROM filter_bubble_snapshots
                       WHERE session_id = ?
                       ORDER BY round_number DESC LIMIT 1""",
                    (session_id,),
                )
            row = await cursor.fetchone()

        if not row:
            return APIResponse(
                success=True,
                data=None,
                meta={"session_id": session_id, "message": "No filter bubble data found"},
            )

        return APIResponse(
            success=True,
            data={
                "session_id": session_id,
                "round_number": row[0],
                "avg_bubble_score": row[1],
                "median_bubble_score": row[2],
                "pct_in_bubble": row[3],
                "algorithm": row[4],
                "gini_coefficient": row[5],
            },
            meta={"session_id": session_id},
        )
    except Exception as exc:
        logger.exception("get_filter_bubble failed for session %s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{session_id}/filter-bubble-history", response_model=APIResponse)
async def get_filter_bubble_history(session_id: str) -> APIResponse:
    """Get filter bubble time series across all rounds for a session."""
    from backend.app.utils.db import get_db  # noqa: PLC0415

    try:
        async with get_db() as db:
            cursor = await db.execute(
                """SELECT round_number, avg_bubble_score, median_bubble_score,
                          pct_in_bubble, algorithm, gini_coefficient
                   FROM filter_bubble_snapshots
                   WHERE session_id = ?
                   ORDER BY round_number""",
                (session_id,),
            )
            rows = await cursor.fetchall()

        data = [
            {
                "round_number": r[0],
                "avg_bubble_score": r[1],
                "median_bubble_score": r[2],
                "pct_in_bubble": r[3],
                "algorithm": r[4],
                "gini_coefficient": r[5],
            }
            for r in rows
        ]
        return APIResponse(
            success=True,
            data=data,
            meta={"session_id": session_id, "count": len(data)},
        )
    except Exception as exc:
        logger.exception("get_filter_bubble_history failed for session %s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{session_id}/virality", response_model=APIResponse)
async def get_virality(
    session_id: str,
    sort: str = "virality_index",
    limit: int = 20,
) -> APIResponse:
    """Get virality scores for posts in a session.

    Query params:
        sort: Column to sort by — one of virality_index, cascade_depth,
            cascade_breadth, velocity, cross_cluster_reach (default virality_index).
        limit: Maximum number of posts to return (default 20, max 200).
    """
    from backend.app.utils.db import get_db  # noqa: PLC0415

    ALLOWED_SORT = {
        "virality_index",
        "cascade_depth",
        "cascade_breadth",
        "velocity",
        "reproduction_number",
        "cross_cluster_reach",
    }
    if sort not in ALLOWED_SORT:
        sort = "virality_index"
    limit = max(1, min(limit, 200))

    try:
        async with get_db() as db:
            cursor = await db.execute(
                f"""SELECT post_id, cascade_depth, cascade_breadth,
                           velocity, reproduction_number,
                           cross_cluster_reach, virality_index
                    FROM virality_scores
                    WHERE session_id = ?
                    ORDER BY {sort} DESC
                    LIMIT ?""",
                (session_id, limit),
            )
            rows = await cursor.fetchall()

        data = [
            {
                "post_id": r[0],
                "cascade_depth": r[1],
                "cascade_breadth": r[2],
                "velocity": r[3],
                "reproduction_number": r[4],
                "cross_cluster_reach": r[5],
                "virality_index": r[6],
            }
            for r in rows
        ]
        return APIResponse(
            success=True,
            data=data,
            meta={
                "session_id": session_id,
                "sort_by": sort,
                "count": len(data),
            },
        )
    except Exception as exc:
        logger.exception("get_virality failed for session %s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{session_id}/polarization-history", response_model=APIResponse)
async def get_polarization_history(session_id: str) -> APIResponse:
    """Get polarization index time series across all rounds."""
    import json as _json  # noqa: PLC0415

    from backend.app.utils.db import get_db  # noqa: PLC0415

    try:
        async with get_db() as db:
            cursor = await db.execute(
                """SELECT round_number, polarization_index, modularity,
                          opinion_variance, cross_cluster_hostility,
                          cluster_stances_json
                   FROM polarization_snapshots
                   WHERE session_id = ?
                   ORDER BY round_number""",
                (session_id,),
            )
            rows = await cursor.fetchall()

        data = [
            {
                "round_number": r[0],
                "polarization_index": r[1],
                "modularity": r[2],
                "opinion_variance": r[3],
                "cross_cluster_hostility": r[4],
                "cluster_stances": _json.loads(r[5]) if r[5] else {},
            }
            for r in rows
        ]

        return APIResponse(
            success=True,
            data=data,
            meta={"session_id": session_id, "count": len(data)},
        )
    except Exception as exc:
        logger.exception("get_polarization_history failed for session %s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


# ---------------------------------------------------------------------------
# Phase 3: Emotional State + Belief System + Cognitive Dissonance APIs
# ---------------------------------------------------------------------------


@router.get("/{session_id}/agents/{agent_id}/emotional-state", response_model=APIResponse)
async def get_emotional_state(
    session_id: str,
    agent_id: int,
    round: int | None = None,
) -> APIResponse:
    """Get emotional state (VAD) for a specific agent at a round (or latest)."""
    from backend.app.utils.db import get_db  # noqa: PLC0415

    try:
        async with get_db() as db:
            if round is not None:
                cursor = await db.execute(
                    """SELECT round_number, valence, arousal, dominance
                    FROM emotional_states
                    WHERE session_id = ? AND agent_id = ? AND round_number = ?""",
                    (session_id, agent_id, round),
                )
            else:
                cursor = await db.execute(
                    """SELECT round_number, valence, arousal, dominance
                    FROM emotional_states
                    WHERE session_id = ? AND agent_id = ?
                    ORDER BY round_number DESC LIMIT 1""",
                    (session_id, agent_id),
                )
            row = await cursor.fetchone()

        if not row:
            return APIResponse(
                success=True,
                data=None,
                meta={"message": "No emotional state found"},
            )

        return APIResponse(
            success=True,
            data={
                "agent_id": agent_id,
                "session_id": session_id,
                "round_number": row[0],
                "valence": row[1],
                "arousal": row[2],
                "dominance": row[3],
            },
            meta={"session_id": session_id, "agent_id": agent_id},
        )
    except Exception as exc:
        logger.exception("get_emotional_state failed session=%s agent=%d", session_id, agent_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{session_id}/emotional-heatmap", response_model=APIResponse)
async def get_emotional_heatmap(
    session_id: str,
    round_number: int | None = None,
) -> APIResponse:
    """Get emotional state heatmap for all agents at a round (or latest)."""
    import aiosqlite as _aiosqlite  # noqa: PLC0415

    from backend.app.utils.db import get_db  # noqa: PLC0415

    try:
        async with get_db() as db:
            db.row_factory = _aiosqlite.Row

            if round_number is not None:
                cursor = await db.execute(
                    """SELECT e.agent_id, e.round_number, e.valence, e.arousal, e.dominance,
                           ap.district
                    FROM emotional_states e
                    LEFT JOIN agent_profiles ap ON ap.id = e.agent_id AND ap.session_id = e.session_id
                    WHERE e.session_id = ? AND e.round_number = ?""",
                    (session_id, round_number),
                )
            else:
                cursor = await db.execute(
                    """SELECT e.agent_id, e.round_number, e.valence, e.arousal, e.dominance,
                           ap.district
                    FROM emotional_states e
                    LEFT JOIN agent_profiles ap ON ap.id = e.agent_id AND ap.session_id = e.session_id
                    WHERE e.session_id = ?
                      AND e.round_number = (SELECT MAX(round_number) FROM emotional_states WHERE session_id = ?)""",
                    (session_id, session_id),
                )
            rows = await cursor.fetchall()

        data = [
            {
                "agent_id": r["agent_id"],
                "round_number": r["round_number"],
                "valence": r["valence"],
                "arousal": r["arousal"],
                "dominance": r["dominance"],
                "district": r["district"],
            }
            for r in rows
        ]

        return APIResponse(
            success=True,
            data=data,
            meta={"session_id": session_id, "count": len(data)},
        )
    except Exception as exc:
        logger.exception("get_emotional_heatmap failed session=%s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{session_id}/agents/{agent_id}/beliefs", response_model=APIResponse)
async def get_agent_beliefs(
    session_id: str,
    agent_id: int,
    round_number: int | None = None,
) -> APIResponse:
    """Get belief state for a specific agent (latest round or specific round)."""
    from backend.app.utils.db import get_db  # noqa: PLC0415

    try:
        async with get_db() as db:
            if round_number is not None:
                cursor = await db.execute(
                    """SELECT topic, stance, confidence, evidence_count, round_number
                    FROM belief_states
                    WHERE session_id = ? AND agent_id = ? AND round_number = ?
                    ORDER BY topic""",
                    (session_id, agent_id, round_number),
                )
            else:
                cursor = await db.execute(
                    """SELECT topic, stance, confidence, evidence_count, round_number
                    FROM belief_states
                    WHERE session_id = ? AND agent_id = ?
                      AND round_number = (SELECT MAX(round_number) FROM belief_states WHERE session_id = ? AND agent_id = ?)
                    ORDER BY topic""",
                    (session_id, agent_id, session_id, agent_id),
                )
            rows = await cursor.fetchall()

        data = [
            {
                "topic": r[0],
                "stance": r[1],
                "confidence": r[2],
                "evidence_count": r[3],
                "round_number": r[4],
            }
            for r in rows
        ]

        return APIResponse(
            success=True,
            data=data,
            meta={"session_id": session_id, "agent_id": agent_id, "count": len(data)},
        )
    except Exception as exc:
        logger.exception("get_agent_beliefs failed session=%s agent=%d", session_id, agent_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{session_id}/cognitive-dissonance", response_model=APIResponse)
async def get_cognitive_dissonance(
    session_id: str,
    round_number: int | None = None,
    min_score: float = 0.5,
) -> APIResponse:
    """Get cognitive dissonance records above a threshold score."""
    import json as _json  # noqa: PLC0415

    from backend.app.utils.db import get_db  # noqa: PLC0415

    try:
        async with get_db() as db:
            if round_number is not None:
                cursor = await db.execute(
                    """SELECT agent_id, round_number, dissonance_score,
                           conflicting_pairs_json, action_belief_gap, resolution_strategy
                    FROM cognitive_dissonance
                    WHERE session_id = ? AND round_number = ? AND dissonance_score >= ?
                    ORDER BY dissonance_score DESC""",
                    (session_id, round_number, min_score),
                )
            else:
                cursor = await db.execute(
                    """SELECT agent_id, round_number, dissonance_score,
                           conflicting_pairs_json, action_belief_gap, resolution_strategy
                    FROM cognitive_dissonance
                    WHERE session_id = ?
                      AND round_number = (SELECT MAX(round_number) FROM cognitive_dissonance WHERE session_id = ?)
                      AND dissonance_score >= ?
                    ORDER BY dissonance_score DESC""",
                    (session_id, session_id, min_score),
                )
            rows = await cursor.fetchall()

        data = [
            {
                "agent_id": r[0],
                "round_number": r[1],
                "dissonance_score": r[2],
                "conflicting_pairs": _json.loads(r[3]) if r[3] else [],
                "action_belief_gap": r[4],
                "resolution_strategy": r[5],
            }
            for r in rows
        ]

        return APIResponse(
            success=True,
            data=data,
            meta={"session_id": session_id, "count": len(data), "min_score": min_score},
        )
    except Exception as exc:
        logger.exception("get_cognitive_dissonance failed session=%s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{session_id}/emotional-contagion-map", response_model=APIResponse)
async def get_emotional_contagion(
    session_id: str,
    round_number: int | None = None,
) -> APIResponse:
    """Get emotional state distribution for contagion map visualization."""
    from backend.app.utils.db import get_db  # noqa: PLC0415

    try:
        async with get_db() as db:
            if round_number is not None:
                cursor = await db.execute(
                    """SELECT e.agent_id, e.valence, e.arousal, e.dominance,
                           ar.agent_b_id, ar.trust_score
                    FROM emotional_states e
                    LEFT JOIN agent_relationships ar
                      ON ar.session_id = e.session_id AND ar.agent_a_id = e.agent_id
                    WHERE e.session_id = ? AND e.round_number = ?
                      AND e.arousal > 0.5
                    ORDER BY e.arousal DESC
                    LIMIT 200""",
                    (session_id, round_number),
                )
            else:
                cursor = await db.execute(
                    """SELECT e.agent_id, e.valence, e.arousal, e.dominance,
                           ar.agent_b_id, ar.trust_score
                    FROM emotional_states e
                    LEFT JOIN agent_relationships ar
                      ON ar.session_id = e.session_id AND ar.agent_a_id = e.agent_id
                    WHERE e.session_id = ?
                      AND e.round_number = (SELECT MAX(round_number) FROM emotional_states WHERE session_id = ?)
                      AND e.arousal > 0.5
                    ORDER BY e.arousal DESC
                    LIMIT 200""",
                    (session_id, session_id),
                )
            rows = await cursor.fetchall()

        # Aggregate: unique agents with their max arousal connections
        agents: dict[int, dict] = {}
        connections: list[dict] = []
        for r in rows:
            agent_id = r[0]
            if agent_id not in agents:
                agents[agent_id] = {
                    "agent_id": agent_id,
                    "valence": r[1],
                    "arousal": r[2],
                    "dominance": r[3],
                }
            if r[4] is not None and r[5] is not None and r[5] > 0:
                connections.append(
                    {
                        "source": agent_id,
                        "target": r[4],
                        "trust": r[5],
                        "contagion_strength": r[2] * r[5],
                    }
                )

        return APIResponse(
            success=True,
            data={"nodes": list(agents.values()), "edges": connections},
            meta={"session_id": session_id, "node_count": len(agents), "edge_count": len(connections)},
        )
    except Exception as exc:
        logger.exception("get_emotional_contagion failed session=%s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{session_id}/narrative", response_model=APIResponse)
async def get_trend_narrative(
    session_id: str,
    confidence_score: float = 0.5,
    confidence_level: str = "medium",
) -> APIResponse:
    """Generate a natural language trend narrative from session simulation artifacts.

    Collects macro history, decision summaries, and belief data as report_artifacts,
    then calls NarrativeEngine to produce an LLM-generated trend report.
    """
    from backend.app.services.narrative_engine import NarrativeEngine  # noqa: PLC0415
    from backend.app.utils.db import get_db as _get_db  # noqa: PLC0415
    from backend.app.utils.llm_client import get_default_client  # noqa: PLC0415

    try:
        # Gather report artifacts from DB
        artifacts: dict = {"session_id": session_id}
        async with _get_db() as db:
            # Macro history
            cursor = await db.execute(
                "SELECT * FROM macro_scenarios WHERE session_id = ? ORDER BY round_number",
                (session_id,),
            )
            macro_rows = await cursor.fetchall()
            artifacts["macro_history"] = [dict(r) for r in (macro_rows or [])]

            # Decision summary
            cursor = await db.execute(
                "SELECT decision_type, COUNT(*) as cnt FROM simulation_actions "
                "WHERE session_id = ? GROUP BY decision_type ORDER BY cnt DESC LIMIT 20",
                (session_id,),
            )
            dec_rows = await cursor.fetchall()
            artifacts["decision_summary"] = [dict(r) for r in (dec_rows or [])]

        engine = NarrativeEngine(llm_client=get_default_client())
        narrative = await engine.generate(
            report_artifacts=artifacts,
            confidence_score=confidence_score,
            confidence_level=confidence_level,
        )
        return APIResponse(
            success=True,
            data={
                "executive_summary": narrative.executive_summary,
                "trends": [t.model_dump() for t in narrative.trends],
                "deep_dive_summary": narrative.deep_dive_summary,
                "methodology_note": narrative.methodology_note,
                "generated_at": narrative.generated_at.isoformat() if narrative.generated_at else None,
            },
            meta={"session_id": session_id},
        )
    except Exception as exc:
        logger.exception("get_trend_narrative failed for session %s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.post("/calibration/run", response_model=APIResponse)
async def run_calibration(
    method: str = "grid_search",
    label: str = "auto",
) -> APIResponse:
    """Run parameter calibration against historical HK data.

    Query params:
        method: "grid_search" or "random_search" (default "grid_search").
        label: Human-readable label for the calibration run (default "auto").
    """
    from backend.app.services.parameter_calibrator import ParameterCalibrator  # noqa: PLC0415

    if method not in ("grid_search", "random_search"):
        raise HTTPException(status_code=400, detail="method must be 'grid_search' or 'random_search'")

    try:
        calibrator = ParameterCalibrator()
        data = await calibrator.load_historical_data()
        best_params, rmse = await calibrator.calibrate(data, method=method)
        row_id = await calibrator.save_calibration(
            best_params,
            label=label,
            rmse=rmse,
            data_period=f"{data[0].period}–{data[-1].period}" if data else "",
        )
        return APIResponse(
            success=True,
            data={
                "calibration_id": row_id,
                "method": method,
                "label": label,
                "rmse": round(rmse, 6),
                "data_points": len(data),
                "best_params": best_params.to_dict(),
            },
            meta={"method": method},
        )
    except Exception as exc:
        logger.exception("run_calibration failed method=%s", method)
        raise HTTPException(status_code=500, detail="Internal server error") from exc
