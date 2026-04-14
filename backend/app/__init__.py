"""FastAPI application factory for Morai."""

from __future__ import annotations

import importlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.config import get_settings
from backend.app.utils.db import apply_migrations, init_db
from backend.app.utils.logger import setup_logging

# Router module names under backend.app.api
_ROUTER_MODULES = (
    "auth",
    "graph",
    "simulation_macro",
    "simulation_branches",
    "simulation",
    "simulation_actions",
    "report",
    "data",
    "data_connector",
    "ws",
    "domain_packs",
    "workspace",
    "comments",
    "validation",
    "calibration",
    "emergence",
    "prediction_market",
    "stock_forecast",
    "interview",
    "settings",
)

# Patterns that identify OASIS simulation subprocesses.
_OASIS_SCRIPT_PATTERNS = (
    "run_parallel_simulation.py",
    "run_twitter_simulation.py",
    "run_facebook_simulation.py",
    "run_instagram_simulation.py",
    "run_reddit_simulation.py",
)


async def _reap_orphaned_oasis_processes(logger: logging.Logger) -> None:
    """Terminate any OASIS simulation subprocesses left by a previous server run.

    Uses psutil to enumerate all OS processes and matches against known OASIS
    script names.  Sends SIGTERM first, then SIGKILL after 5 seconds if the
    process has not exited.

    Falls back to a ``pkill`` invocation when psutil is unavailable.

    Args:
        logger: Logger instance for status/error messages.
    """
    try:
        import psutil
    except ImportError:
        # psutil not installed — fall back to the best-effort pkill approach.
        logger.warning("psutil not installed — falling back to pkill for orphan reaping")
        import subprocess as _sp

        _sp.run(
            ["pkill", "-f", "run_(twitter|parallel|facebook|instagram|reddit)_simulation.py"],
            capture_output=True,
        )
        logger.info("Cleaned up stale simulation subprocesses via pkill (fallback)")
        return

    reaped: list[int] = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline = proc.info.get("cmdline") or []
            cmdline_str = " ".join(cmdline)
            if any(pattern in cmdline_str for pattern in _OASIS_SCRIPT_PATTERNS):
                logger.warning(
                    "Reaping orphaned OASIS process PID %d: %s",
                    proc.pid,
                    cmdline_str[:120],
                )
                proc.terminate()
                reaped.append(proc.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if reaped:
        # Give processes a chance to exit gracefully before force-killing.
        import asyncio

        await asyncio.sleep(5.0)
        for pid in reaped:
            try:
                p = psutil.Process(pid)
                if p.is_running():
                    logger.warning(
                        "Orphaned OASIS process PID %d did not terminate — sending SIGKILL",
                        pid,
                    )
                    p.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass  # Already gone — expected.

        logger.info("Reaped %d orphaned OASIS subprocess(es): PIDs %s", len(reaped), reaped)
    else:
        logger.info("No orphaned OASIS subprocesses found at startup")


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: initialise DB and data scheduler on startup."""
    from backend.app.utils.telemetry import init_telemetry

    init_telemetry()

    logger = logging.getLogger("murmuroscope")
    logger.info("Starting Morai backend")

    # API Key Validation (L4)
    settings = get_settings()
    if not settings.DEMO_MODE and not settings.OPENROUTER_API_KEY.strip():
        logger.warning("=" * 60)
        logger.warning("WARNING: OPENROUTER_API_KEY is not set!")
        logger.warning("The application is running in LIVE mode but has no LLM provider.")
        logger.warning("Simulations will fail. Please set the key in .env or use DEMO_MODE=true.")
        logger.warning("=" * 60)

    # Demo Seed DB (L2)
    if settings.DEMO_MODE:
        db_path = Path(settings.DATABASE_PATH)
        seed_path = Path("data/demo/seed.db")
        if not db_path.exists() and seed_path.exists():
            logger.info("Demo Mode: Seeding database from %s", seed_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            import shutil # noqa: PLC0415
            shutil.copy(str(seed_path), str(db_path))

    # Reap orphaned OASIS simulation subprocesses from a previous server instance.
    await _reap_orphaned_oasis_processes(logger)

    await init_db()
    await apply_migrations()

    # Start the serialised write queue — prevents "database is locked" errors
    # under concurrent load (3-5+ simultaneous users / active simulations).
    from backend.app.services.db_write_queue import get_write_queue

    await get_write_queue()
    logger.info("SQLite WriteQueue started")

    # Runtime migration: create session_costs table for cost persistence (Phase 0.4)
    try:
        from backend.app.utils.db import get_db

        async with get_db() as db:
            await db.execute(
                """CREATE TABLE IF NOT EXISTS session_costs (
                    session_id TEXT PRIMARY KEY,
                    total_cost_usd REAL NOT NULL DEFAULT 0.0,
                    is_paused BOOLEAN NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )"""
            )
            await db.commit()
        logger.info("session_costs table ensured")
    except Exception:
        logger.warning("session_costs table creation failed", exc_info=True)

    # Restore persisted cost state so hard-cap enforcement survives restarts
    try:
        from backend.app.services.cost_tracker import restore_costs_from_db

        await restore_costs_from_db()
    except Exception:
        logger.warning("restore_costs_from_db failed at startup")

    # Runtime migration: create personality_evolution_log table (Phase 2.1)
    try:
        from backend.app.utils.db import get_db

        async with get_db() as db:
            await db.execute(
                """CREATE TABLE IF NOT EXISTS personality_evolution_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    round_number INTEGER NOT NULL,
                    trait TEXT NOT NULL,
                    old_value REAL NOT NULL,
                    new_value REAL NOT NULL,
                    delta REAL NOT NULL,
                    recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
                )"""
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_pel_session_round ON personality_evolution_log(session_id, round_number)"
            )
            await db.commit()
        logger.info("personality_evolution_log table ensured")
    except Exception:
        logger.warning("personality_evolution_log table creation failed", exc_info=True)

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

    # Runtime migration: add is_admin to users table (Phase 0.1 security)
    try:
        from backend.app.utils.db import get_db

        async with get_db() as db:
            await db.execute("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0")
            await db.commit()
        logger.info("Added is_admin column to users")
    except Exception as exc:
        if "duplicate column" in str(exc).lower():
            pass  # Column already exists
        else:
            logger.warning("is_admin migration unexpected error: %s", exc)

    # Runtime migration: add domain_pack_id to simulation_sessions table
    try:
        from backend.app.utils.db import get_db

        async with get_db() as db:
            await db.execute("ALTER TABLE simulation_sessions ADD COLUMN domain_pack_id TEXT DEFAULT 'hk_city'")
            await db.commit()
        logger.info("Added domain_pack_id column to simulation_sessions")
    except Exception as exc:
        if "duplicate column" in str(exc).lower():
            pass  # Column already exists
        else:
            logger.warning("domain_pack_id migration unexpected error: %s", exc)

    # Runtime migration: create simulation_jobs table (Phase 7)
    try:
        from backend.app.utils.db import get_db

        async with get_db() as db:
            await db.execute(
                """CREATE TABLE IF NOT EXISTS simulation_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES simulation_sessions(id) ON DELETE CASCADE,
                    status TEXT NOT NULL DEFAULT 'pending',
                    last_heartbeat TEXT,
                    error_message TEXT,
                    worker_pid INTEGER,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                )"""
            )
            # Mark any 'running' jobs as 'interrupted' on startup (zombie detection)
            await db.execute(
                "UPDATE simulation_jobs SET status = 'interrupted', updated_at = datetime('now') "
                "WHERE status = 'running'"
            )
            await db.commit()
        logger.info("simulation_jobs table ensured and zombies reaped")
    except Exception:
        logger.warning("simulation_jobs table migration failed", exc_info=True)

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
                "CREATE INDEX IF NOT EXISTS idx_udp_session_metric ON user_data_points(session_id, metric)"
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
            await db.execute("CREATE INDEX IF NOT EXISTS idx_ads_session ON api_data_sources(session_id)")
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
                "CREATE INDEX IF NOT EXISTS idx_kg_edge_temporal ON kg_edges(session_id, valid_from, valid_until)"
            )
            await db.commit()
    except Exception as exc:
        logger.warning("idx_kg_edge_temporal index error: %s", exc)

    # Validate ExternalDataFeed configuration when enabled
    import os as _os

    if _os.environ.get("EXTERNAL_FEED_ENABLED", "false").lower() == "true":
        if not _os.environ.get("FRED_API_KEY", "").strip():
            logger.warning("EXTERNAL_FEED_ENABLED=true but FRED_API_KEY not set — FRED data source will be unavailable")
        else:
            logger.info("ExternalDataFeed enabled with FRED + World Bank + Taiwan risk sources")

    import os as _os_startup

    _skip_pipeline = _os_startup.environ.get("SKIP_STARTUP_PIPELINE", "false").lower() == "true"

    async def _run_startup_pipeline() -> None:
        """Background task: seed population data, run live data pipeline, calibrate."""
        nonlocal scheduler

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
            from backend.app.utils.db import get_db
            from backend.data_pipeline.data_provenance import ensure_table, get_data_gaps

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
                    "Real data insufficient (%d records) — calibration skipped, using conservative default coefficients",
                    real_count,
                )
        except Exception:
            logger.warning("Calibration failed — using default coefficients")

    if not _skip_pipeline:
        import asyncio as _asyncio_startup

        _asyncio_startup.create_task(_run_startup_pipeline(), name="startup-data-pipeline")
        logger.info("Data pipeline launched in background (non-blocking)")
    else:
        logger.info("SKIP_STARTUP_PIPELINE=true — skipping live data pipeline")

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

    # Runtime migration: create app_settings table (Settings Page)
    try:
        from backend.app.utils.db import get_db

        async with get_db() as db:
            await db.execute(
                """CREATE TABLE IF NOT EXISTS app_settings (
                    key        TEXT PRIMARY KEY,
                    value      TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )"""
            )
            await db.commit()
        logger.info("app_settings table ensured")
    except Exception:
        logger.warning("app_settings table creation failed", exc_info=True)

    # Load runtime settings overrides from DB into in-memory store
    try:
        from backend.app.services.runtime_settings import load_from_rows
        from backend.app.utils.db import get_db

        async with get_db() as db:
            cursor = await db.execute("SELECT key, value FROM app_settings")
            rows = await cursor.fetchall()
        load_from_rows(rows)
        logger.info("RuntimeSettingsStore loaded %d override(s) from DB", len(rows))
    except Exception:
        logger.warning("RuntimeSettingsStore load failed", exc_info=True)

    # Start SimulationWorker background loop (Phase 7)
    try:
        from backend.app.services.simulation_worker import get_simulation_worker

        worker = await get_simulation_worker()
        await worker.start()
        app.state.simulation_worker = worker
        logger.info("SimulationWorker background loop started")
    except Exception:
        logger.warning("Failed to start SimulationWorker", exc_info=True)

    yield

    # Shutdown SimulationWorker
    if hasattr(app.state, "simulation_worker"):
        try:
            await app.state.simulation_worker.stop()
            logger.info("SimulationWorker stopped")
        except Exception:
            logger.warning("SimulationWorker stop failed")

    # Kill any remaining simulation subprocesses before server exit.
    await _reap_orphaned_oasis_processes(logger)

    # Stop the serialised write queue and flush final metrics.
    from backend.app.services.db_write_queue import shutdown_write_queue

    await shutdown_write_queue()
    logger.info("SQLite WriteQueue stopped")

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

    # Rate limiting (slowapi) — middleware disabled temporarily due to
    # slowapi 0.1.9 / Starlette compatibility issue (AttributeError in sync_check_limits).
    # Exception handler still registered so @limiter.limit decorators don't crash.
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded

    from backend.app.api.auth import _limiter

    app.state.limiter = _limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    # app.add_middleware(SlowAPIMiddleware)  # re-enable after upgrading slowapi

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
