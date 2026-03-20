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

    logger = logging.getLogger("morai")
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

    # Runtime migration: create users table (Phase 4.8 Auth)
    try:
        from backend.app.utils.db import get_db
        async with get_db() as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS users ("
                "  id TEXT PRIMARY KEY,"
                "  email TEXT UNIQUE NOT NULL,"
                "  password_hash TEXT NOT NULL,"
                "  display_name TEXT,"
                "  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
            await db.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
            await db.commit()
        logger.info("Users table ensured")
    except Exception:
        logger.warning("Users table migration failed", exc_info=True)

    # Runtime migration: create collaborative workspace tables (Phase 4.6)
    try:
        from backend.app.utils.db import get_db
        async with get_db() as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS workspaces ("
                "  id TEXT PRIMARY KEY,"
                "  name TEXT NOT NULL,"
                "  description TEXT,"
                "  owner_id TEXT,"
                "  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
            await db.execute(
                "CREATE TABLE IF NOT EXISTS workspace_members ("
                "  workspace_id TEXT NOT NULL,"
                "  user_id TEXT NOT NULL,"
                "  role TEXT DEFAULT 'viewer',"
                "  joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
                "  PRIMARY KEY (workspace_id, user_id)"
                ")"
            )
            await db.execute(
                "CREATE TABLE IF NOT EXISTS workspace_sessions ("
                "  workspace_id TEXT NOT NULL,"
                "  session_id TEXT NOT NULL,"
                "  added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
                "  PRIMARY KEY (workspace_id, session_id)"
                ")"
            )
            await db.execute(
                "CREATE TABLE IF NOT EXISTS prediction_comments ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  session_id TEXT NOT NULL,"
                "  user_id TEXT,"
                "  content TEXT NOT NULL,"
                "  quote_text TEXT,"
                "  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_comments_session "
                "ON prediction_comments(session_id)"
            )
            await db.commit()
        logger.info("Collaborative workspace tables ensured")
    except Exception:
        logger.warning("Workspace tables migration failed", exc_info=True)

    # Runtime migration: create custom_domain_packs table (Task 10)
    try:
        from backend.app.utils.db import get_db
        async with get_db() as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS custom_domain_packs ("
                "  id TEXT PRIMARY KEY,"
                "  name TEXT NOT NULL,"
                "  description TEXT DEFAULT '',"
                "  regions TEXT NOT NULL,"
                "  occupations TEXT NOT NULL,"
                "  income_brackets TEXT NOT NULL,"
                "  shocks TEXT NOT NULL,"
                "  metrics TEXT NOT NULL,"
                "  persona_template TEXT NOT NULL,"
                "  sentiment_keywords TEXT NOT NULL,"
                "  locale TEXT DEFAULT 'en-US',"
                "  source TEXT DEFAULT 'user_edited',"
                "  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
                "  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_custom_packs_locale "
                "ON custom_domain_packs(locale)"
            )
            await db.commit()
        logger.info("custom_domain_packs table ensured")
    except Exception:
        logger.warning("custom_domain_packs migration failed", exc_info=True)

    # Runtime migration: create Universal Prediction Engine tables (Task 12)
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

    # Runtime migration: create Phase 1C network_events table
    try:
        from backend.app.utils.db import get_db
        async with get_db() as db:
            await db.execute(
                """CREATE TABLE IF NOT EXISTS network_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    round_number INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    agent_a_username TEXT NOT NULL DEFAULT '',
                    agent_b_username TEXT NOT NULL DEFAULT '',
                    trust_delta REAL NOT NULL DEFAULT 0.0,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT DEFAULT (datetime('now'))
                )"""
            )
            await db.execute("CREATE INDEX IF NOT EXISTS idx_nev_session ON network_events(session_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_nev_round ON network_events(session_id, round_number)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_nev_type ON network_events(session_id, event_type)")
            await db.commit()
        logger.info("network_events table ensured")
    except Exception:
        logger.warning("network_events migration failed", exc_info=True)

    # Runtime migration: create Phase 2 Recommendation Engine tables
    try:
        from backend.app.utils.db import get_db
        async with get_db() as db:
            await db.execute(
                """CREATE TABLE IF NOT EXISTS agent_feeds (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    agent_id INTEGER NOT NULL,
                    round_number INTEGER NOT NULL,
                    post_id TEXT NOT NULL,
                    rank INTEGER NOT NULL,
                    score REAL NOT NULL,
                    created_at TEXT DEFAULT (datetime('now'))
                )"""
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_af_session_round "
                "ON agent_feeds(session_id, round_number)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_af_agent "
                "ON agent_feeds(session_id, agent_id, round_number)"
            )
            await db.execute(
                """CREATE TABLE IF NOT EXISTS filter_bubble_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    round_number INTEGER NOT NULL,
                    avg_bubble_score REAL NOT NULL DEFAULT 0.0,
                    median_bubble_score REAL NOT NULL DEFAULT 0.0,
                    pct_in_bubble REAL NOT NULL DEFAULT 0.0,
                    algorithm TEXT NOT NULL DEFAULT 'engagement_first',
                    gini_coefficient REAL NOT NULL DEFAULT 0.0,
                    created_at TEXT DEFAULT (datetime('now')),
                    UNIQUE(session_id, round_number)
                )"""
            )
            await db.execute(
                """CREATE TABLE IF NOT EXISTS virality_scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    post_id TEXT NOT NULL,
                    cascade_depth INTEGER NOT NULL DEFAULT 0,
                    cascade_breadth INTEGER NOT NULL DEFAULT 0,
                    velocity REAL NOT NULL DEFAULT 0.0,
                    reproduction_number REAL NOT NULL DEFAULT 0.0,
                    cross_cluster_reach REAL NOT NULL DEFAULT 0.0,
                    virality_index REAL NOT NULL DEFAULT 0.0,
                    created_at TEXT DEFAULT (datetime('now')),
                    UNIQUE(session_id, post_id)
                )"""
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_vs_session ON virality_scores(session_id)"
            )
            await db.commit()
        logger.info("Phase 2 recommendation engine tables ensured")
    except Exception:
        logger.warning("Phase 2 recommendation engine migration failed", exc_info=True)

    # Phase 3: Emotional state + Belief system + Cognitive dissonance tables
    try:
        async with get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS emotional_states (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    agent_id INTEGER NOT NULL,
                    round_number INTEGER NOT NULL,
                    valence REAL NOT NULL DEFAULT 0.0,
                    arousal REAL NOT NULL DEFAULT 0.3,
                    dominance REAL NOT NULL DEFAULT 0.4,
                    created_at TEXT DEFAULT (datetime('now')),
                    UNIQUE(session_id, agent_id, round_number)
                )""")
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_es_session ON emotional_states(session_id, round_number)"
            )
            await db.execute("""
                CREATE TABLE IF NOT EXISTS belief_states (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    agent_id INTEGER NOT NULL,
                    topic TEXT NOT NULL,
                    stance REAL NOT NULL DEFAULT 0.0,
                    confidence REAL NOT NULL DEFAULT 0.5,
                    evidence_count INTEGER NOT NULL DEFAULT 0,
                    round_number INTEGER NOT NULL,
                    created_at TEXT DEFAULT (datetime('now')),
                    UNIQUE(session_id, agent_id, topic, round_number)
                )""")
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_bs_session ON belief_states(session_id, round_number)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_bs_agent ON belief_states(session_id, agent_id)"
            )
            await db.execute("""
                CREATE TABLE IF NOT EXISTS cognitive_dissonance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    agent_id INTEGER NOT NULL,
                    round_number INTEGER NOT NULL,
                    dissonance_score REAL NOT NULL DEFAULT 0.0,
                    conflicting_pairs_json TEXT NOT NULL DEFAULT '[]',
                    action_belief_gap REAL NOT NULL DEFAULT 0.0,
                    resolution_strategy TEXT NOT NULL DEFAULT 'none',
                    created_at TEXT DEFAULT (datetime('now')),
                    UNIQUE(session_id, agent_id, round_number)
                )""")
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_cd_session ON cognitive_dissonance(session_id, round_number)"
            )
            await db.commit()
        logger.info("Phase 3 emotional/belief/dissonance tables ensured")
    except Exception:
        logger.warning("Phase 3 table migration failed", exc_info=True)

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
    logger = logging.getLogger("morai")

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

    # Apply default rate limit to all POST endpoints (10/minute per IP)
    _limiter._application_limits = ["10/minute"]
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
