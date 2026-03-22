"""FastAPI application factory for Morai."""

from __future__ import annotations

import importlib
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.config import get_settings
from backend.app.utils.db import apply_migrations, init_db
from backend.app.utils.logger import setup_logging

# Router module names under backend.app.api
_ROUTER_MODULES = ("auth", "graph", "simulation_macro", "simulation_branches", "simulation", "simulation_actions", "report", "data", "data_connector", "ws", "domain_packs", "workspace", "comments", "validation", "calibration", "emergence", "prediction_market", "stock_forecast")


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: initialise DB and data scheduler on startup."""
    from backend.app.utils.telemetry import init_telemetry
    init_telemetry()

    logger = logging.getLogger("murmuroscope")
    logger.info("Starting Morai backend")

    # Kill stale simulation subprocesses from previous server instance
    import subprocess as _sp
    _sp.run(
        ["pkill", "-f", "run_(twitter|parallel|facebook|instagram|reddit)_simulation.py"],
        capture_output=True,
    )
    logger.info("Cleaned up any stale simulation subprocesses")

    await init_db()
    await apply_migrations()

    # Runtime migration: add share_token to reports table
    try:
        from backend.app.utils.db import get_db
        async with get_db() as db:
            await db.execute("ALTER TABLE reports ADD COLUMN share_token TEXT")
            await db.commit()
        logger.info("Added share_token column to reports")
    except Exception as exc:
        if "duplicate column" in str(exc).lower():
            pass  # Column already exists
        else:
            logger.warning("share_token migration unexpected error: %s", exc)

    # Runtime migration: add domain_pack_id to simulation_sessions table
    try:
        from backend.app.utils.db import get_db
        async with get_db() as db:
            await db.execute(
                "ALTER TABLE simulation_sessions ADD COLUMN domain_pack_id TEXT DEFAULT 'hk_city'"
            )
            await db.commit()
        logger.info("Added domain_pack_id column to simulation_sessions")
    except Exception as exc:
        if "duplicate column" in str(exc).lower():
            pass  # Column already exists
        else:
            logger.warning("domain_pack_id migration unexpected error: %s", exc)

    # NOTE: All table creation is in database/schema.sql. Only ALTER TABLE
    # migrations and tables not yet in schema.sql are kept here.

    # Runtime migration: create tables not yet in schema.sql
    try:
        from backend.app.utils.db import get_db
        async with get_db() as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS user_data_points ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  session_id TEXT NOT NULL,"
                "  metric TEXT NOT NULL,"
                "  value REAL NOT NULL,"
                "  timestamp TEXT NOT NULL,"
                "  source_type TEXT NOT NULL DEFAULT 'user_file',"
                "  created_at TEXT DEFAULT (datetime('now'))"
                ")"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_udp_session_metric "
                "ON user_data_points(session_id, metric)"
            )
            await db.execute(
                "CREATE TABLE IF NOT EXISTS api_data_sources ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  session_id TEXT NOT NULL,"
                "  name TEXT NOT NULL,"
                "  url TEXT NOT NULL,"
                "  auth_header TEXT,"
                "  field_mappings TEXT,"
                "  last_synced_at TEXT,"
                "  created_at TEXT DEFAULT (datetime('now'))"
                ")"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_ads_session "
                "ON api_data_sources(session_id)"
            )
            await db.commit()
        logger.info("Universal Prediction Engine tables ensured (user_data_points, api_data_sources)")
    except Exception:
        logger.warning("UPE table migration failed", exc_info=True)

    # Runtime migration: create session_api_keys table (BYOK)
    try:
        from backend.app.utils.db import get_db
        async with get_db() as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS session_api_keys ("
                "  session_id TEXT PRIMARY KEY,"
                "  encrypted_key BLOB NOT NULL,"
                "  provider TEXT NOT NULL,"
                "  model TEXT,"
                "  base_url TEXT,"
                "  created_at TEXT DEFAULT (datetime('now'))"
                ")"
            )
            await db.commit()
        logger.info("session_api_keys table ensured")
    except Exception:
        logger.warning("session_api_keys migration failed", exc_info=True)

    # Runtime migration: add granularity column to market_data (Stock Forecast upgrade)
    try:
        from backend.app.utils.db import get_db
        async with get_db() as db:
            await db.execute("ALTER TABLE market_data ADD COLUMN granularity TEXT DEFAULT 'daily'")
            await db.commit()
        logger.info("Added granularity column to market_data")
    except Exception as exc:
        if "duplicate column" in str(exc).lower():
            pass  # Column already exists
        else:
            logger.warning("granularity migration unexpected error: %s", exc)

    # Runtime migration: add valid_from / valid_until to kg_edges (Graphiti temporal pattern)
    try:
        from backend.app.utils.db import get_db
        async with get_db() as db:
            await db.execute("ALTER TABLE kg_edges ADD COLUMN valid_from INTEGER DEFAULT 0")
            await db.commit()
    except Exception as exc:
        if "duplicate column" not in str(exc).lower():
            logger.warning("kg_edges.valid_from migration error: %s", exc)

    try:
        from backend.app.utils.db import get_db
        async with get_db() as db:
            await db.execute("ALTER TABLE kg_edges ADD COLUMN valid_until INTEGER")
            await db.commit()
    except Exception as exc:
        if "duplicate column" not in str(exc).lower():
            logger.warning("kg_edges.valid_until migration error: %s", exc)

    # Backfill valid_from from existing round_number values
    try:
        from backend.app.utils.db import get_db
        async with get_db() as db:
            await db.execute(
                "UPDATE kg_edges SET valid_from = round_number WHERE valid_from = 0 AND round_number IS NOT NULL"
            )
            await db.commit()
    except Exception as exc:
        logger.warning("kg_edges valid_from backfill error: %s", exc)

    # Index for temporal queries
    try:
        from backend.app.utils.db import get_db
        async with get_db() as db:
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_kg_edge_temporal "
                "ON kg_edges(session_id, valid_from, valid_until)"
            )
            await db.commit()
    except Exception as exc:
        logger.warning("idx_kg_edge_temporal index error: %s", exc)

    # 1. Seed static population/census data (legitimate reference data)
    try:
        from backend.data_pipeline.hk_reference_data import seed_population_data
        await seed_population_data()
        logger.info("Population/census data seeded")
    except Exception:
        logger.warning("Population data seeding failed")

    # 2. Run real data pipeline (downloads from live APIs — no synthetic data)
    real_count = 0
    try:
        from backend.data_pipeline.download_all import run_pipeline
        summaries = await run_pipeline(normalize=True)
        real_count = sum(
            getattr(s, "total_records", getattr(s, "row_count", 0))
            for s in summaries
            if getattr(s, "error", None) is None
        )
        logger.info("Data pipeline complete: %d real records from APIs", real_count)
    except Exception:
        logger.warning("Data pipeline failed — limited data available", exc_info=True)

    # 3. Log data gaps
    try:
        from backend.data_pipeline.data_provenance import get_data_gaps, ensure_table
        from backend.app.utils.db import get_db
        async with get_db() as db:
            await ensure_table(db)
            gaps = await get_data_gaps(db)
        if gaps:
            gap_names = [f"{g.category}/{g.metric}" for g in gaps]
            logger.warning("DATA GAPS (no real data): %s", gap_names)
    except Exception:
        logger.debug("Data provenance check skipped")

    # 4. Minimum data threshold check
    if real_count < 50:
        logger.error(
            "Insufficient real data (%d records). "
            "Simulation quality will be limited. "
            "Check network connectivity to data.gov.hk / HKMA / Yahoo Finance.",
            real_count,
        )

    # 5. Calibration — only with sufficient real data
    try:
        from backend.data_pipeline.calibration import CalibrationPipeline
        if real_count >= 100:
            pipeline = CalibrationPipeline()
            await pipeline.run_calibration()
            logger.info("Calibration complete (based on %d real data points)", real_count)
        else:
            logger.warning(
                "Real data insufficient (%d records) — calibration skipped, "
                "using conservative default coefficients", real_count,
            )
    except Exception:
        logger.warning("Calibration failed — using default coefficients")

    # Start data pipeline scheduler (graceful — skip if APScheduler not installed)
    scheduler = None
    try:
        from backend.data_pipeline.scheduler import DataScheduler
        scheduler = DataScheduler()
        scheduler.start()
        logger.info("DataScheduler started")
    except Exception:
        logger.warning("DataScheduler not started (APScheduler may not be installed)")

    # Load custom domain packs from DB into in-memory registry
    try:
        from backend.app.domain.base import DomainPackRegistry
        loaded = await DomainPackRegistry.load_custom_from_db()
        if loaded:
            logger.info("Loaded %d custom domain pack(s) into registry", loaded)
    except Exception:
        logger.warning("Custom domain pack loading failed", exc_info=True)

    yield

    # Kill simulation subprocesses before server exit
    import subprocess as _sp
    _sp.run(
        ["pkill", "-f", "run_(twitter|parallel|facebook|instagram|reddit)_simulation.py"],
        capture_output=True,
    )
    logger.info("Killed simulation subprocesses on shutdown")

    # Shutdown scheduler
    if scheduler is not None:
        try:
            scheduler.stop()
            logger.info("DataScheduler stopped")
        except Exception:
            logger.warning("DataScheduler stop failed")
    logger.info("Shutting down Morai backend")


def create_app() -> FastAPI:
    """Build and return the FastAPI application.

    - Configures CORS from settings.FRONTEND_URL
    - Mounts routers from backend.app.api (graph, simulation, report, data, ws)
    - Registers /api/health endpoint
    - Runs init_db() on startup via lifespan
    """
    settings = get_settings()

    log_level = logging.DEBUG if settings.DEBUG else logging.INFO
    setup_logging(level=log_level)
    logger = logging.getLogger("murmuroscope")

    app = FastAPI(
        title="Morai API",
        version="0.1.0",
        lifespan=_lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.FRONTEND_URL],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Rate limiting (slowapi)
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from slowapi.middleware import SlowAPIMiddleware
    from backend.app.api.auth import _limiter

    # Apply default rate limit (120/minute per IP).
    # Auth endpoints have tighter per-endpoint limits (3-5/min).
    # Previous value of 10/min was too restrictive for dashboard GET polling.
    _limiter._application_limits = ["120/minute"]
    app.state.limiter = _limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    # Health check
    @app.get("/api/health")
    async def health_check() -> dict[str, str]:
        return {"status": "ok"}

    # Mount routers (skip gracefully if module not yet implemented)
    for module_name in _ROUTER_MODULES:
        fqn = f"backend.app.api.{module_name}"
        try:
            module = importlib.import_module(fqn)
            router = getattr(module, "router", None)
            if router is not None:
                app.include_router(router, prefix="/api")
                logger.info("Mounted router: %s", fqn)
            else:
                logger.warning("Module %s has no 'router' attribute, skipping", fqn)
        except (ImportError, ModuleNotFoundError):
            logger.warning("Router module %s not found, skipping", fqn)

    return app
