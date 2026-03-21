"""OASIS subprocess orchestration for MurmuraScope.

Launches and monitors the OASIS Twitter simulation as an external subprocess,
reading JSONL progress updates from stdout, pushing them to the WebSocket
progress queue, and parking the OASIS output database at a stable path.

Hook methods are organised into four mixin classes:
  - AgentHooksMixin  (memories, trust, decisions, consumption)
  - SocialHooksMixin (echo chambers, media, polarization, groups)
  - MacroHooksMixin  (macro feedback, credit cycle, news, B2B decisions)
  - KGHooksMixin     (KG snapshots, B2B/social init)
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict
import json
import os
import random
import random as _random
import sys
import time as _time
from pathlib import Path
from typing import Any, Callable, Coroutine

from backend.app.models.kg_session_state import KGSessionState
from backend.app.services.simulation_hooks_agent import AgentHooksMixin
from backend.app.services.simulation_hooks_kg import KGHooksMixin
from backend.app.services.simulation_hooks_macro import MacroHooksMixin
from backend.app.services.simulation_hooks_social import SocialHooksMixin
from backend.app.services.simulation_subprocess_manager import SimulationSubprocessManager
from backend.app.utils.logger import get_logger
from backend.app.utils.telemetry import get_tracer as _get_tracer

_sim_tracer = _get_tracer("simulation")

# Imported lazily-by-name to avoid circular import at module load time;
# resolved once at first call via _clear_ws_progress().
def _clear_ws_progress(session_id: str) -> None:
    """Clear WebSocket progress buffer for a completed/failed session."""
    try:
        from backend.app.api.ws import clear_progress  # noqa: PLC0415
        clear_progress(session_id)
    except Exception:
        pass  # WS module not loaded — no buffer to clear

logger = get_logger("simulation_runner")


@contextlib.contextmanager
def _timed_block(hook_name: str, session_id: str, round_num: int = 0):
    """Context manager that logs execution time of a simulation hook at DEBUG level."""
    t0 = _time.monotonic()
    with _sim_tracer.start_as_current_span(f"hook.{hook_name}"):
        try:
            yield
        finally:
            ms = round((_time.monotonic() - t0) * 1000)
            logger.debug(
                "hook=%s session=%s round=%d duration=%dms",
                hook_name,
                session_id[:8],
                round_num,
                ms,
            )


# Paths computed relative to this file's location — portable across deployments.
# This file lives at: backend/app/services/simulation_runner.py
# Project root is 4 levels up: services → app → backend → project_root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_VENV_PYTHON = _PROJECT_ROOT / ".venv311" / "bin" / "python"
_PYTHON_BIN = _VENV_PYTHON if _VENV_PYTHON.exists() else Path(sys.executable)
_SCRIPT_PATH = _PROJECT_ROOT / "backend" / "scripts" / "run_twitter_simulation.py"
_PARALLEL_SCRIPT = _PROJECT_ROOT / "backend" / "scripts" / "run_parallel_simulation.py"
_FACEBOOK_SCRIPT = _PROJECT_ROOT / "backend" / "scripts" / "run_facebook_simulation.py"
_INSTAGRAM_SCRIPT = _PROJECT_ROOT / "backend" / "scripts" / "run_instagram_simulation.py"

ProgressCallback = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class SimulationRunner(
    AgentHooksMixin,
    SocialHooksMixin,
    MacroHooksMixin,
    KGHooksMixin,
):
    """Orchestrates the OASIS Twitter simulation subprocess.

    Hook methods are defined in the mixin base classes to keep this file
    focused on subprocess lifecycle and round dispatch.
    """

    def __init__(
        self,
        dry_run: bool = False,
        preset: "SimPreset | None" = None,
    ) -> None:
        from backend.app.models.simulation_config import PRESET_STANDARD, SimPreset  # noqa: PLC0415
        self._preset: SimPreset = preset or PRESET_STANDARD
        self._dry_run = dry_run
        self._subprocess_mgr = SimulationSubprocessManager()
        self._action_logger: Any | None = None
        self._memory_service: Any | None = None
        self._vector_store: Any | None = None
        self._posts_buffer: dict[str, dict[int, dict[str, list[str]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        self._macro_controller: Any | None = None
        self._macro_history: Any | None = None
        # Tracks the latest MacroState per session for feedback accumulation
        self._macro_state: dict[str, Any] = {}
        # Per-session locks protecting _macro_state writes (Plan A — H3 race condition)
        self._macro_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._decision_engine: Any | None = None
        self._media_model: Any | None = None
        self._consumption_tracker: Any | None = None
        self._bank_agent: Any | None = None
        self._trust_service: Any | None = None
        self._social_network: Any | None = None
        self._echo_chamber_result: Any | None = None
        # Track per-session background tasks to cancel them on cleanup
        self._pending_tasks: dict[str, set[asyncio.Task]] = defaultdict(set)  # type: ignore[type-arg]
        # Round-level profile cache: populated once per round before Group 1, cleared at session end.
        # Keyed by session_id. Stores raw aiosqlite.Row objects (dict-style access supported).
        # MUST NOT be cleared per-round — Group 3 fire-and-forget tasks (_process_wealth_transfers)
        # may read the cache after the round boundary.
        self._round_profiles: dict[str, list] = {}
        # Phase 1B: per-session activity profiles (username → ActivityProfile)
        self._activity_profiles: dict[str, dict[str, Any]] = {}
        # Per-session RNG for activation sampling (seeded per session for reproducibility)
        self._activation_rngs: dict[str, random.Random] = {}
        # Phase 3: pending arousal deltas from cognitive dissonance denial
        self._pending_arousal_deltas: dict[str, dict[int, float]] = defaultdict(dict)
        # Phase 4A: optional scale profiler (None = profiling disabled)
        self._profiler: Any | None = None
        # kg_driven mode services (initialised lazily per session in run())
        self._kg_mode: dict[str, bool] = {}  # session_id → True if kg_driven
        self._world_event_gen: Any | None = None
        self._cognitive_engine: Any | None = None
        self._belief_propagation: Any | None = None
        self._faction_mapper: Any | None = None
        self._tipping_detector: Any | None = None
        # kg_driven per-session state — all 12 fields consolidated into KGSessionState
        self._kg_sessions: dict[str, KGSessionState] = {}
        # Phase 4: relationship lifecycle service (kg_driven + emergence)
        self._relationship_lifecycle: Any | None = None
        # Phase 4: relationship memory service (dyadic memory storage)
        self._relationship_memory: Any | None = None
        # Phase 4: strategic planner for Tier 1 multi-round planning
        self._strategic_planner: Any | None = None
        # Consensus debate engine for structured multi-agent argumentation
        self._consensus_debate: Any | None = None
        # Reflection loop: periodic insight synthesis for Tier 1 agents
        self._reflection_service: Any | None = None
        # Phase 4A: per-session RoundCache for in-memory agent profile lookups
        self._round_caches: dict[str, "RoundCache"] = {}
        # Phase 4A: BatchWriter for high-throughput bulk inserts
        self._batch_writer: Any | None = None
        # Phase 4D: optional shard coordinator for large-scale subprocess sharding
        # Activated only when DB_SHARDING_ENABLED=true env var is set.
        self._shard_coordinators: dict[str, Any] = {}
        self._init_batch_writer()

    def _init_batch_writer(self) -> None:
        """Lazily initialise the BatchWriter and register hot-path tables."""
        try:
            from backend.app.services.batch_writer import BatchWriter  # noqa: PLC0415
            writer = BatchWriter(flush_threshold=500)
            writer.register_table("belief_states", [
                "session_id", "agent_id", "topic", "stance",
                "confidence", "evidence_count", "round_number",
            ])
            writer.register_table("relationship_states", [
                "session_id", "agent_a_id", "agent_b_id", "round_number",
                "intimacy", "passion", "commitment", "satisfaction",
                "alternatives", "investment", "trust",
                "interaction_count", "rounds_since_change", "updated_at",
            ])
            writer.register_table("simulation_actions", [
                "session_id", "oasis_username", "round_number",
                "action_type", "content", "sentiment",
                "target_agent_username",
            ])
            self._batch_writer = writer
            logger.debug("BatchWriter initialised with 3 registered tables")
        except Exception:
            logger.warning("BatchWriter init failed — falling back to direct executemany", exc_info=True)
            self._batch_writer = None

    def _is_sharding_enabled(self) -> bool:
        """Check if subprocess sharding is enabled via env var."""
        return os.environ.get("DB_SHARDING_ENABLED", "").lower() == "true"

    def _get_shard_coordinator(
        self,
        session_id: str,
        python_bin: Path,
        script_path: Path,
    ) -> Any:
        """Create or retrieve a ShardCoordinator for the given session.

        Returns None if sharding is not enabled.
        """
        if not self._is_sharding_enabled():
            return None

        if session_id not in self._shard_coordinators:
            from backend.app.services.shard_coordinator import ShardCoordinator  # noqa: PLC0415
            coord = ShardCoordinator(
                session_id=session_id,
                python_bin=python_bin,
                script_path=script_path,
            )
            self._shard_coordinators[session_id] = coord
            logger.info("Created ShardCoordinator for session %s", session_id)

        return self._shard_coordinators[session_id]

    async def _cleanup_shard_coordinator(self, session_id: str) -> None:
        """Shutdown and remove the shard coordinator for a session."""
        coord = self._shard_coordinators.pop(session_id, None)
        if coord is not None:
            try:
                await coord.shutdown_all()
                logger.info("ShardCoordinator cleaned up for session %s", session_id)
            except Exception:
                logger.exception("ShardCoordinator cleanup failed for session %s", session_id)

    async def run(
        self,
        session_id: str,
        config: dict[str, Any],
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        """Launch the OASIS subprocess and stream JSONL progress.

        1. Validates prerequisites (python bin, script path, agent CSV).
        2. Writes the merged config (with all LLM fields) to
           ``data/sessions/{session_id}/sim_config.json``.
        3. Spawns the subprocess.
        4. For every JSONL line on stdout: parses it, calls
           ``push_progress`` (WebSocket) and the optional *progress_callback*.
        5. Waits for the process to exit and raises on non-zero exit code.

        Args:
            session_id: Unique session identifier.
            config: Simulation configuration dict (see _build_full_config).
            progress_callback: Optional async callback invoked per update.

        Raises:
            ValueError: If session is already running.
            RuntimeError: If prerequisites are missing or subprocess fails.
        """
        if self._subprocess_mgr.is_running(session_id):
            raise ValueError(f"Session {session_id} is already running")

        # B2B initialisation: generate company profiles if none exist for the session.
        # This is conditional (idempotent) and errors are swallowed to avoid blocking.
        await self._init_b2b_companies(session_id)
        await self._init_social_network(session_id)

        # Restore macro state from DB if this session was previously interrupted.
        if session_id not in self._macro_state:
            restored = await self._restore_macro_state(session_id)
            if restored is not None:
                async with self._macro_locks[session_id]:
                    self._macro_state[session_id] = restored

        # Detect kg_driven mode and initialise services
        await self._init_kg_driven_mode(session_id, config)

        # Run BiasProbe before simulation starts (fire-and-forget, tracked)
        self._create_tracked_task(session_id, self._run_bias_probe(session_id))

        if self._dry_run:
            await self._run_dry(session_id, config, progress_callback)
            return

        # Late import to avoid circular dependency: ws imports nothing from here.
        from backend.app.api.ws import push_progress  # noqa: PLC0415

        # Validate prerequisites.
        _require_path(_PYTHON_BIN, "Python venv binary")

        agent_csv = config.get("agent_csv_path", "")
        if not agent_csv or not Path(agent_csv).is_file():
            raise RuntimeError(
                f"agent_csv_path not found or missing: '{agent_csv}'. "
                "Ensure create_session wrote the CSV before calling run()."
            )

        # Select simulation script based on enabled platforms.
        platforms = config.get("platforms", {"facebook": True, "instagram": True})
        facebook_on = platforms.get("facebook", False)
        instagram_on = platforms.get("instagram", False)
        twitter_on = platforms.get("twitter", False)
        reddit_on = platforms.get("reddit", False)

        # Multiple platforms → parallel script
        enabled_count = sum(1 for v in platforms.values() if v)
        if enabled_count > 1 and _PARALLEL_SCRIPT.exists():
            script_to_run = _PARALLEL_SCRIPT
        elif facebook_on:
            script_to_run = _FACEBOOK_SCRIPT
        elif instagram_on:
            script_to_run = _INSTAGRAM_SCRIPT
        elif twitter_on:
            script_to_run = _SCRIPT_PATH
        else:
            script_to_run = _SCRIPT_PATH  # fallback
        _require_path(script_to_run, "Simulation script")

        # Phase 1B: Load temporal activity profiles for this session.
        self._load_activity_profiles(session_id)

        # Write the full config (without API key) to a session-specific file.
        full_config = _build_full_config(config, session_id)
        config_dir = _PROJECT_ROOT / "data" / "sessions" / session_id
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "sim_config.json"
        config_path.write_text(
            json.dumps(full_config, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        cmd = [
            str(_PYTHON_BIN),
            str(script_to_run),
            "--config",
            str(config_path),
        ]

        logger.info(
            "Launching OASIS subprocess for session %s: %s",
            session_id,
            " ".join(cmd),
        )

        # Write stderr to a log file to avoid pipe buffer blocking.
        log_file_path = config_dir / "sim.log"
        # log_file and process are initialised to None so the finally clause
        # can safely guard their cleanup even if creation fails mid-way.
        log_file = None
        process = None
        import time as _time_mod  # noqa: PLC0415
        _sim_start_time = _time_mod.perf_counter()
        try:
            log_file = log_file_path.open("wb")

            # Pass API key via env var (not in the config file on disk).
            subprocess_env = {**os.environ, "OPENROUTER_API_KEY": _get_api_key()}

            process = await self._subprocess_mgr.launch(
                session_id,
                cmd,
                subprocess_env,
                log_file,
                _PROJECT_ROOT,
            )

            assert process.stdout is not None  # guaranteed by PIPE
            async for raw_line in process.stdout:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                update = _try_parse_jsonl(line)
                if update is None:
                    logger.debug("Non-JSON stdout: %s", line[:200])
                    continue

                # Push to WebSocket queue (broadcast to any connected client).
                try:
                    await push_progress(session_id, update)
                except Exception:
                    logger.exception(
                        "push_progress failed for session %s", session_id
                    )

                # Log posts and accumulate for memory service
                if update.get("type") == "post":
                    await self._handle_post_update(session_id, update)

                # Log non-content actions (follow, like, lurk, etc.)
                if update.get("type") == "action":
                    await self._handle_action_update(session_id, update)

                # Also call the manager's progress callback (DB round update).
                if progress_callback is not None:
                    try:
                        await progress_callback(update)
                    except Exception:
                        logger.exception(
                            "Progress callback error for session %s", session_id
                        )

                # Process memories when a round completes
                if update.get("type") == "progress":
                    completed_round = update.get("data", {}).get("round")
                    if completed_round is not None:
                        completed_round_int = int(completed_round)
                        await self._execute_round_hooks(session_id, completed_round_int)

            await process.wait()
            self._subprocess_mgr.check_exit_code(session_id)

            # Take final KG snapshot at completion
            try:
                total_rounds = int(config.get("round_count", 0))
                if total_rounds > 0:
                    await self._process_kg_snapshot(session_id, total_rounds)
            except Exception:
                logger.exception("Final KG snapshot failed session=%s", session_id)

            # Generate emergence scorecard at simulation completion
            try:
                await self._generate_emergence_scorecard(session_id)
            except Exception:
                logger.exception("Emergence scorecard failed session=%s", session_id)

            # Run mini-ensemble (10 trials, top 4 metrics) for quick IQR
            try:
                from backend.app.services.monte_carlo import MonteCarloEngine  # noqa: PLC0415
                mc = MonteCarloEngine()
                _domain = config.get("domain_pack_id", "hk_city")
                await mc.run_mini(session_id, domain_pack_id=_domain)
                logger.info("Mini-ensemble complete session=%s", session_id)
            except Exception:
                logger.exception("Mini-ensemble failed session=%s", session_id)

            # Phase 4A: persist benchmark result if profiler is active
            if self._profiler is not None:
                try:
                    _total_s = _time_mod.perf_counter() - _sim_start_time
                    _agent_count = int(config.get("agent_count", 0))
                    _result = self._profiler.get_summary(
                        preset_name=self._preset.name if hasattr(self._preset, "name") else "standard",
                        agent_count=_agent_count,
                        total_duration_s=_total_s,
                        peak_memory_mb=0.0,
                    )
                    from backend.app.utils.db import get_db as _get_db  # noqa: PLC0415
                    async with _get_db() as _bdb:
                        await self._profiler.persist(_result, _bdb)
                    self._profiler.clear()
                except Exception:
                    logger.exception("Benchmark persist failed session=%s", session_id)

            # Keep subprocess alive so the report agent can interview agents.
            await self._subprocess_mgr.keep_alive_for_report(session_id)

        finally:
            # --- 1. Ensure subprocess is not still running (orphan prevention) ---
            # process is None only if subprocess creation itself failed.
            # Skip killing if report generation is pending — the subprocess must
            # stay alive so the report agent can interview agents.
            if (process is not None
                    and process.returncode is None
                    and not self._subprocess_mgr._report_pending.get(session_id)):
                logger.warning(
                    "Cleaning up orphaned subprocess for session %s (PID %d)",
                    session_id,
                    process.pid,
                )
                try:
                    process.kill()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=3.0)
                    except asyncio.TimeoutError:
                        logger.error(
                            "Failed to wait for process %d to die, proceeding.",
                            process.pid,
                        )
                except OSError:
                    pass  # Process already exited between check and kill

            # --- 2. Flush BatchWriter before general cleanup ---
            if self._batch_writer is not None:
                try:
                    from backend.app.utils.db import get_db as _get_db_cleanup  # noqa: PLC0415
                    async with _get_db_cleanup() as db:
                        await self._batch_writer.flush_all(db)
                except Exception:
                    logger.debug("BatchWriter final flush failed session=%s", session_id, exc_info=True)
                self._batch_writer.clear()

            # --- 3. Close resources that are session-run-scoped (not in cleanup_session) ---
            if self._vector_store is not None:
                try:
                    await self._vector_store.close()
                except Exception:
                    logger.debug("VectorStore close failed session=%s", session_id)
            if log_file is not None:
                log_file.close()

            # --- 4. Delegate common cleanup (idempotent — safe even if stop() already called it) ---
            await self.cleanup_session(session_id)

    def _create_tracked_task(
        self,
        session_id: str,
        coro: Any,
        timeout_s: float = 60.0,
    ) -> "asyncio.Task[Any]":
        """Create an asyncio task and register it for cleanup on session end.

        All fire-and-forget tasks must go through this method so that the
        finally block in run() can cancel them if the simulation ends before
        the task completes, preventing async task leaks.

        Args:
            timeout_s: Per-task timeout in seconds. Exceeded tasks are cancelled
                and logged as warnings rather than crashing the simulation.
        """
        coro_name = getattr(coro, "__qualname__", type(coro).__name__)

        async def _wrapped() -> None:
            try:
                await asyncio.wait_for(coro, timeout=timeout_s)
            except asyncio.TimeoutError:
                logger.warning(
                    "Task timeout after %.0fs session=%s task=%s",
                    timeout_s,
                    session_id,
                    coro_name,
                )
            except asyncio.CancelledError:
                pass  # Expected on clean shutdown
            except Exception:
                logger.error(
                    "Tracked task crashed session=%s task=%s",
                    session_id,
                    coro_name,
                    exc_info=True,
                )

        task: asyncio.Task[Any] = asyncio.create_task(_wrapped())
        task_set = self._pending_tasks[session_id]
        task_set.add(task)
        task.add_done_callback(lambda t: task_set.discard(t))
        return task

    async def _fetch_and_cache_profiles(self, session_id: str) -> list:
        """Fetch all agent profiles for a session and cache for the current round.

        Called once per round at the start of _execute_round_hooks, before Group 1.
        All hooks that need profiles read from self._round_profiles[session_id] instead
        of issuing their own SELECT queries.

        Cache is cleared at session end (not per-round) because Group 3 fire-and-forget
        tasks may read the cache after the round boundary.

        The cache stores raw aiosqlite.Row objects. Consuming code may:
        - Access columns via r["column_name"] (dict-style, supported by aiosqlite.Row)
        - Reconstruct AgentProfile from the row fields
        NOTE: `tier` and `oasis_username` are in the cache but are NOT AgentProfile
        fields — access them via r["tier"] directly, never via a reconstructed AgentProfile.
        """
        from backend.app.utils.db import get_db  # noqa: PLC0415
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    """SELECT id, agent_type, age, sex, district, occupation, income_bracket,
                       education_level, marital_status, housing_type,
                       openness, conscientiousness, extraversion,
                       agreeableness, neuroticism, monthly_income,
                       savings, political_stance, oasis_username, tier
                       FROM agent_profiles WHERE session_id = ?""",
                    (session_id,),
                )
                rows = await cursor.fetchall()
        except Exception:
            logger.error(
                "_fetch_and_cache_profiles failed session=%s — using empty cache",
                session_id, exc_info=True,
            )
            rows = []
        self._round_profiles[session_id] = rows

        # Populate RoundCache with agent data keyed by oasis_username for O(1) lookups
        try:
            from backend.app.services.round_cache import RoundCache  # noqa: PLC0415
            cache = self._round_caches.get(session_id)
            if cache is None:
                cache = RoundCache()
                self._round_caches[session_id] = cache
            agents_dict: dict[str, dict] = {}
            for r in rows:
                uname = r["oasis_username"] if r["oasis_username"] else str(r["id"])
                agents_dict[uname] = {
                    "id": r["id"],
                    "agent_type": r["agent_type"],
                    "oasis_username": r["oasis_username"],
                    "tier": r["tier"],
                    "political_stance": r["political_stance"],
                    "openness": r["openness"],
                    "conscientiousness": r["conscientiousness"],
                    "extraversion": r["extraversion"],
                    "agreeableness": r["agreeableness"],
                    "neuroticism": r["neuroticism"],
                }
            cache.bulk_load_agents(agents_dict)
        except Exception:
            logger.debug(
                "_fetch_and_cache_profiles: RoundCache population failed session=%s",
                session_id, exc_info=True,
            )

        return rows

    async def _execute_round_hooks(self, session_id: str, round_num: int) -> None:
        """Execute round hooks with dependency-aware grouping.

        Group 1 (parallel, awaited): memories + trust (+ emotional_state if emergence)
        Group 2 (sequential after G1): decisions → side effects (+ belief if emergence) → consumption
        Group 3 (periodic, fire-and-forget): all interval-driven hooks
        """
        _round_t0 = _time.monotonic()
        # Populate per-round profile cache (shared by all hooks this round via self._round_profiles)
        await self._fetch_and_cache_profiles(session_id)
        agent_count = len(self._round_profiles.get(session_id, []))

        hc = self._preset.hook_config

        # Pre-round: kg_driven world event generation
        if self._kg_mode.get(session_id):
            await self._kg_generate_world_events(session_id, round_num)

        # Phase 2: feed ranking must complete before agent decision hooks read the feed
        if self._profiler:
            _t_feed = self._profiler.start_hook("feed_ranking", round_num)
        await self._process_feed_ranking(session_id, round_num)
        if self._profiler:
            self._profiler.end_hook("feed_ranking", round_num, _t_feed)

        # Emergence monitoring: phase transition detection (every round, lightweight)
        self._create_tracked_task(
            session_id,
            self._process_emergence_monitoring(session_id, round_num),
        )

        # Group 1: Independent critical hooks (run in parallel, AWAIT completion)
        if self._profiler:
            _t_g1 = self._profiler.start_hook("group_1", round_num)
        critical = [
            self._process_round_memories(session_id, round_num),
            self._process_round_trust(session_id, round_num),
        ]
        if hc.emergence_enabled:
            critical.append(self._process_emotional_state(session_id, round_num))
        # kg_driven + emergence: update multi-dimensional relationship states
        if self._kg_mode.get(session_id) and hc.emergence_enabled:
            critical.append(self._process_relationship_states(session_id, round_num))
        with _timed_block("group1_parallel", session_id, round_num=round_num):
            results = await asyncio.gather(*critical, return_exceptions=True)
        if self._profiler:
            self._profiler.end_hook("group_1", round_num, _t_g1)
        for r in results:
            if isinstance(r, Exception):
                logger.error(
                    "Critical hook failed session=%s round=%d: %s",
                    session_id, round_num, r,
                )

        # Group 2: Depends on memories being stored
        if self._profiler:
            _t_g2 = self._profiler.start_hook("group_2", round_num)
        with _timed_block("group2_sequential", session_id, round_num=round_num):
            await self._process_round_decisions(session_id, round_num)
            await self._apply_decision_side_effects(session_id, round_num)
            if hc.emergence_enabled:
                await self._process_belief_update(session_id, round_num)
            await self._process_round_consumption(session_id, round_num)
            # kg_driven: strategic planning + stochastic cognitive deliberation + consensus debate + belief propagation
            if self._kg_mode.get(session_id):
                await self._kg_strategic_planning(session_id, round_num)
                await self._kg_deliberation(session_id, round_num)
                await self._kg_consensus_debate(session_id, round_num)
                await self._kg_belief_propagation(session_id, round_num)
        if self._profiler:
            self._profiler.end_hook("group_2", round_num, _t_g2)

        # Group 3: Periodic hooks (fire-and-forget, tracked for cleanup)
        logger.debug(
            "hook=group3_fired session=%s round=%d",
            session_id[:8],
            round_num,
        )
        if round_num > 0 and round_num % hc.company_decision_interval == 0:
            self._create_tracked_task(
                session_id,
                self._process_round_company_decisions(session_id, round_num),
            )
            self._create_tracked_task(
                session_id,
                self._process_credit_cycle(session_id, round_num),
            )
        if round_num > 0 and round_num % hc.media_influence_interval == 0:
            self._create_tracked_task(
                session_id,
                self._process_media_influence(session_id, round_num),
                timeout_s=90.0,
            )
            if hc.emergence_enabled:
                self._create_tracked_task(
                    session_id,
                    self._process_info_warfare(session_id, round_num),
                    timeout_s=90.0,
                )
        if round_num > 0 and round_num % hc.echo_chamber_interval == 0:
            self._create_tracked_task(
                session_id,
                self._process_echo_chambers(session_id, round_num),
            )
        if round_num > 0 and round_num % hc.macro_feedback_interval == 0:
            self._create_tracked_task(
                session_id,
                self._process_macro_feedback(session_id, round_num),
            )
            if hc.emergence_enabled:
                self._create_tracked_task(
                    session_id,
                    self._process_wealth_transfers(session_id, round_num),
                )
        if round_num > 0 and round_num % hc.news_shock_interval == 0:
            self._create_tracked_task(
                session_id,
                self._process_news_shock(session_id, round_num),
                timeout_s=90.0,
            )
        if round_num > 0 and round_num % hc.kg_evolution_interval == 0:
            self._create_tracked_task(
                session_id,
                self._process_kg_evolution(session_id, round_num),
                timeout_s=90.0,
            )
        if round_num > 0 and round_num % hc.kg_snapshot_interval == 0:
            self._create_tracked_task(
                session_id,
                self._process_kg_snapshot(session_id, round_num),
            )
        if round_num > 0 and round_num % hc.polarization_interval == 0:
            self._create_tracked_task(
                session_id,
                self._process_polarization(session_id, round_num),
            )
            self._create_tracked_task(
                session_id,
                self._process_community_summaries(session_id, round_num),
            )
        # Bug 2 fix: group_formation uses collective_action_interval, not polarization_interval
        if hc.emergence_enabled and round_num > 0 and round_num % hc.collective_action_interval == 0:
            self._create_tracked_task(
                session_id,
                self._process_group_formation(session_id, round_num),
            )
        # Collective action momentum (moved from Group 2 to Group 3, periodic)
        if hc.emergence_enabled and round_num > 0 and round_num % hc.collective_action_interval == 0:
            self._create_tracked_task(
                session_id,
                self._process_collective_action_momentum(session_id, round_num),
            )
        # Bug 1 fix: attention_allocation moved from Group 1 to Group 3 with interval check
        if hc.emergence_enabled and round_num > 0 and round_num % hc.attention_economy_interval == 0:
            self._create_tracked_task(
                session_id,
                self._process_attention_allocation(session_id, round_num),
            )
        # Phase 1C: network evolution (structural tie / bridge / triadic closure detection)
        if hc.emergence_enabled and round_num > 0 and round_num % hc.network_evolution_interval == 0:
            self._create_tracked_task(
                session_id,
                self._process_network_evolution(session_id, round_num),
            )
        # Phase 2: virality scoring
        if hc.emergence_enabled and round_num > 0 and round_num % hc.virality_interval == 0:
            self._create_tracked_task(
                session_id,
                self._process_virality_scoring(session_id, round_num),
            )
        # Phase 3: emotional contagion (periodic, emergence-gated)
        if hc.emergence_enabled and round_num > 0 and round_num % hc.emotional_contagion_interval == 0:
            self._create_tracked_task(
                session_id,
                self._process_emotional_contagion(session_id, round_num),
            )

        # kg_driven: faction mapping + tipping point detection (every 3 rounds)
        if self._kg_mode.get(session_id) and round_num > 0 and round_num % 3 == 0:
            self._create_tracked_task(
                session_id,
                self._kg_faction_and_tipping(session_id, round_num),
                timeout_s=90.0,
            )

        # kg_driven + emergence: relationship lifecycle detection (every 3 rounds)
        if (
            self._kg_mode.get(session_id)
            and hc.emergence_enabled
            and round_num > 0
            and round_num % 3 == 0
            and self._relationship_lifecycle is not None
        ):
            self._create_tracked_task(
                session_id,
                self._process_relationship_lifecycle(session_id, round_num),
            )

        # TDMI emergence measurement (every 5 rounds, both modes)
        if round_num > 0 and round_num % 5 == 0:
            self._create_tracked_task(
                session_id,
                self._compute_tdmi(session_id, round_num),
                timeout_s=30.0,
            )

        # Round-level wall-clock summary (Groups 1+2 synchronous work only;
        # Group 3 fire-and-forget tasks finish asynchronously after this point).
        _round_total_ms = int((_time.monotonic() - _round_t0) * 1000)
        logger.info(
            "session=%s round=%d agents=%d total_round_ms=%d",
            session_id, round_num, agent_count, _round_total_ms,
        )

        # Clean up posts buffer for completed round to prevent memory growth
        session_buf = self._posts_buffer.get(session_id)
        if session_buf is not None:
            session_buf.pop(round_num, None)

    async def stop(self, session_id: str) -> None:
        """Stop a running simulation subprocess (SIGTERM → SIGKILL).

        Delegates to SimulationSubprocessManager.stop() which owns the
        process lifecycle, then runs immediate resource cleanup.

        Args:
            session_id: UUID of the session to stop.

        Raises:
            ValueError: If the session is not currently running.
        """
        await self._subprocess_mgr.stop(session_id)
        await self.cleanup_session(session_id)

    async def cleanup_session(self, session_id: str) -> None:
        """Release all in-memory resources held for *session_id*.

        Safe to call multiple times or for sessions that have already been
        cleaned up (all operations are idempotent pop/discard).

        Called automatically by run() finally block on normal completion,
        and explicitly by stop() for user-initiated cancellation so that
        resources are freed immediately instead of waiting for asyncio
        task timeouts.
        """
        # Cancel tracked background tasks (Group 3 fire-and-forget)
        pending = list(self._pending_tasks.pop(session_id, set()))
        if pending:
            for t in pending:
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

        # Subprocess tracking
        await self._subprocess_mgr.cleanup(session_id)

        # Memory caches
        self._posts_buffer.pop(session_id, None)
        self._macro_state.pop(session_id, None)
        self._round_profiles.pop(session_id, None)
        rc = self._round_caches.pop(session_id, None)
        if rc is not None:
            rc.clear()
        self._activity_profiles.pop(session_id, None)
        self._activation_rngs.pop(session_id, None)
        self._pending_arousal_deltas.pop(session_id, None)

        # kg_driven state
        self._kg_mode.pop(session_id, None)
        self._kg_sessions.pop(session_id, None)
        if self._relationship_lifecycle is not None:
            self._relationship_lifecycle.cleanup_session(session_id)

        # Shard coordinator
        await self._cleanup_shard_coordinator(session_id)

        # Cost tracker
        try:
            from backend.app.services.cost_tracker import clear_session as _clear_cost  # noqa: PLC0415
            _clear_cost(session_id)
        except Exception:
            pass

        # WebSocket progress buffer
        _clear_ws_progress(session_id)

    async def get_action_logs(
        self, session_id: str
    ) -> list[dict[str, Any]]:
        """Read action logs from the OASIS output database for *session_id*.

        Returns:
            List of action log dicts, or an empty list if the DB is absent.
        """
        db_path = (
            _PROJECT_ROOT / "data" / "sessions" / session_id / "oasis.db"
        )
        if not db_path.exists():
            logger.warning("No OASIS DB found for session %s", session_id)
            return []

        import aiosqlite  # noqa: PLC0415

        actions: list[dict[str, Any]] = []
        async with aiosqlite.connect(str(db_path)) as db:
            db.row_factory = aiosqlite.Row
            try:
                cursor = await db.execute(
                    "SELECT * FROM action_logs ORDER BY round_num, agent_id"
                )
                rows = await cursor.fetchall()
                for row in rows:
                    actions.append(dict(row))
            except Exception:
                logger.exception(
                    "Failed to read action_logs for session %s", session_id
                )
        return actions

    async def _run_dry(
        self,
        session_id: str,
        config: dict[str, Any],
        progress_callback: ProgressCallback | None,
    ) -> None:
        """Execute a dry-run: emit mock progress events without spawning a subprocess.

        Generates 3 simulated rounds of progress + post events, then triggers all
        processing hooks (macro_feedback, memory, decisions, consumption, media
        influence) so that the full pipeline can be tested without LLM API keys
        or the OASIS framework being installed.

        Args:
            session_id: Simulation session UUID.
            config: Simulation configuration dict.
            progress_callback: Optional async callback invoked per mock update.
        """
        logger.info("dry_run=True — skipping subprocess for session %s", session_id)
        await self._init_social_network(session_id)

        # Late import to avoid circular dependency: ws imports nothing from here.
        try:
            from backend.app.api.ws import push_progress  # noqa: PLC0415
        except Exception:
            async def push_progress(sid: str, data: dict[str, Any]) -> None:  # type: ignore[misc]
                pass

        round_count: int = int(config.get("round_count", 3))
        # lite_ensemble mode: run all requested rounds to allow emergence.
        # Original dry_run test mode: cap at 3 for fast testing.
        lite_ensemble: bool = config.get("lite_ensemble", False)
        mock_rounds = round_count if lite_ensemble else min(round_count, 3)

        for rnd in range(1, mock_rounds + 1):
            # Emit 2 mock post events per round
            for i in range(2):
                post_update: dict[str, Any] = {
                    "type": "post",
                    "data": {
                        "platform": "facebook",
                        "username": f"dry_user_{i}",
                        "content": f"[dry-run] Round {rnd} mock post #{i}",
                        "round": rnd,
                        "post_id": f"dry-{session_id}-r{rnd}-p{i}",
                    },
                }
                try:
                    await push_progress(session_id, post_update)
                except Exception:
                    pass
                await self._handle_post_update(session_id, post_update)
                if progress_callback is not None:
                    try:
                        await progress_callback(post_update)
                    except Exception:
                        logger.exception("dry_run progress_callback error session=%s", session_id)

            # Emit progress event for round completion
            progress_update: dict[str, Any] = {
                "type": "progress",
                "data": {"round": rnd, "total_rounds": mock_rounds, "status": "running"},
            }
            try:
                await push_progress(session_id, progress_update)
            except Exception:
                pass
            if progress_callback is not None:
                try:
                    await progress_callback(progress_update)
                except Exception:
                    logger.exception("dry_run progress_callback error session=%s", session_id)

            # Trigger per-round hooks (same as the real run() loop)
            await self._execute_round_hooks(session_id, rnd)

        # Final KG snapshot at dry_run completion
        try:
            await self._process_kg_snapshot(session_id, mock_rounds)
        except Exception:
            logger.exception("dry_run final KG snapshot failed session=%s", session_id)

        # Final complete event
        complete_update: dict[str, Any] = {
            "type": "complete",
            "data": {"rounds_completed": mock_rounds, "status": "complete"},
        }
        try:
            await push_progress(session_id, complete_update)
        except Exception:
            pass
        if progress_callback is not None:
            try:
                await progress_callback(complete_update)
            except Exception:
                logger.exception("dry_run progress_callback error session=%s", session_id)

        # Clean up buffers (mirrors the finally block in run())
        self._posts_buffer.pop(session_id, None)
        self._macro_state.pop(session_id, None)
        self._round_profiles.pop(session_id, None)
        rc = self._round_caches.pop(session_id, None)
        if rc is not None:
            rc.clear()
        if self._batch_writer is not None:
            self._batch_writer.clear()
        logger.info("dry_run complete for session %s (%d rounds)", session_id, mock_rounds)

    # ------------------------------------------------------------------
    # Phase 1B: Temporal activation helpers
    # ------------------------------------------------------------------

    def _load_activity_profiles(self, session_id: str) -> None:
        """Load activity profiles JSON for a session into memory cache.

        Reads ``data/sessions/{session_id}/activity_profiles.json``.
        Silently skips if the file does not exist (backward compatible).
        """
        json_path = _PROJECT_ROOT / "data" / "sessions" / session_id / "activity_profiles.json"
        if not json_path.is_file():
            return
        try:
            raw = json.loads(json_path.read_text(encoding="utf-8"))
            self._activity_profiles[session_id] = raw
            self._activation_rngs[session_id] = random.Random(session_id)
            logger.info(
                "Loaded activity profiles for %d agents (session %s)",
                len(raw),
                session_id,
            )
        except Exception:
            logger.warning(
                "Failed to load activity_profiles.json for session %s",
                session_id,
                exc_info=True,
            )

    def _is_agent_active(
        self,
        session_id: str,
        username: str,
        round_number: int,
    ) -> bool:
        """Return True if the agent is temporally active in this round.

        Falls back to True (always active) when no profile is available,
        ensuring backward compatibility with sessions created before Phase 1B.
        """
        profiles = self._activity_profiles.get(session_id)
        if not profiles:
            return True  # No profiles loaded — always active

        agent_data = profiles.get(username)
        if agent_data is None:
            return True  # Unknown agent — always active

        try:
            from backend.app.services.temporal_activation import TemporalActivationService  # noqa: PLC0415
            from backend.app.models.activity_profile import ActivityProfile  # noqa: PLC0415

            profile = ActivityProfile(
                agent_id=agent_data.get("agent_id", 0),
                chronotype=agent_data["chronotype"],
                activity_vector=tuple(agent_data["activity_vector"]),
                base_activity_rate=agent_data["base_activity_rate"],
            )
            rng = self._activation_rngs.get(session_id)
            if rng is None:
                rng = random.Random(session_id)
                self._activation_rngs[session_id] = rng

            svc = TemporalActivationService()
            return svc.should_activate(profile, round_number, rng)
        except Exception:
            logger.debug(
                "Temporal activation check failed for %s round %d",
                username,
                round_number,
            )
            return True  # Fail open

    # ------------------------------------------------------------------

    async def _handle_post_update(
        self,
        session_id: str,
        update: dict[str, Any],
    ) -> None:
        """Handle a 'post' type update: log action + accumulate for memory."""
        data = update.get("data", {})
        username = data.get("username") or data.get("oasis_username", "")
        content = data.get("content", "")
        platform = data.get("platform", "twitter")
        round_number = int(data.get("round", 0))
        post_id = str(data.get("post_id", "")) or None

        if not username or not content:
            return

        # Phase 1B: Skip logging if agent is temporally inactive this round.
        if not self._is_agent_active(session_id, username, round_number):
            logger.debug(
                "Temporal gate: skipping post from %s round %d (inactive)",
                username, round_number,
            )
            return

        # 1. Log structured action
        try:
            from backend.scripts.action_logger import ActionLogger  # noqa: PLC0415
            if self._action_logger is None:
                self._action_logger = ActionLogger()
            logged = await self._action_logger.log_post(
                session_id=session_id,
                round_number=round_number,
                oasis_username=username,
                content=content,
                platform=platform,
                post_id=post_id,
            )
            # Enrich WS broadcast data with sentiment from the logged action
            data["sentiment"] = logged.sentiment
        except Exception:
            logger.exception("action_logger.log_post failed session=%s", session_id)

        if "timestamp" not in data:
            from datetime import datetime as _dt  # noqa: PLC0415
            data["timestamp"] = _dt.now().isoformat()

        # 2. Accumulate for memory service (batch per round)
        self._posts_buffer[session_id][round_number][username].append(content)

    async def _handle_action_update(
        self,
        session_id: str,
        update: dict[str, Any],
    ) -> None:
        """Handle an 'action' type update: log non-content actions.

        Routes follow/unfollow events to social_network for relationship
        tracking, and logs all action types to simulation_actions for
        action diversity analytics.
        """
        data = update.get("data", {})
        username = data.get("username", "")
        action_type = data.get("action_type", "")
        platform = data.get("platform", "twitter")
        round_number = int(data.get("round", 0))
        info = data.get("info", {})

        if not username or not action_type:
            return

        # Phase 1B: passive DO_NOTHING always passes (no cost to log passivity);
        # other non-content actions are gated by temporal activation.
        if action_type != "do_nothing" and not self._is_agent_active(
            session_id, username, round_number
        ):
            logger.debug(
                "Temporal gate: skipping action %s from %s round %d (inactive)",
                action_type, username, round_number,
            )
            return

        # Extract target username from info payload (for follow/unfollow/like)
        target_username = None
        if isinstance(info, dict):
            target_username = info.get("user_name") or info.get("target_user")

        # 1. Log the action to simulation_actions
        try:
            from backend.scripts.action_logger import ActionLogger  # noqa: PLC0415
            if self._action_logger is None:
                self._action_logger = ActionLogger()
            await self._action_logger.log_action(
                session_id=session_id,
                round_number=round_number,
                oasis_username=username,
                action_type=action_type,
                platform=platform,
                target_agent_username=target_username,
                info=info,
            )
        except Exception:
            logger.exception(
                "action_logger.log_action failed session=%s action=%s",
                session_id, action_type,
            )

        # 2. Route graph-affecting actions to social_network service
        _graph_actions = {"follow", "unfollow", "mute", "unmute"}
        if action_type in _graph_actions and target_username:
            try:
                await self._process_graph_action(
                    session_id, username, target_username, action_type, round_number,
                )
            except Exception:
                logger.exception(
                    "graph action routing failed session=%s action=%s",
                    session_id, action_type,
                )

    async def _process_graph_action(
        self,
        session_id: str,
        source_username: str,
        target_username: str,
        action_type: str,
        round_number: int,
    ) -> None:
        """Update agent_relationships based on follow/unfollow/mute actions."""
        from backend.app.utils.db import get_db  # noqa: PLC0415

        async with get_db() as db:
            # Resolve agent IDs from oasis_username
            cursor = await db.execute(
                "SELECT id, oasis_username FROM agent_profiles "
                "WHERE session_id = ? AND oasis_username IN (?, ?)",
                (session_id, source_username, target_username),
            )
            rows = await cursor.fetchall()

        id_map = {r[1]: r[0] for r in rows}
        source_id = id_map.get(source_username)
        target_id = id_map.get(target_username)

        if source_id is None or target_id is None:
            return

        async with get_db() as db:
            if action_type == "follow":
                await db.execute(
                    """INSERT INTO agent_relationships
                       (session_id, agent_a_id, agent_b_id, relationship_type, trust_score)
                       VALUES (?, ?, ?, 'follows', 0.1)
                       ON CONFLICT(session_id, agent_a_id, agent_b_id) DO UPDATE
                       SET trust_score = MIN(1.0, trust_score + 0.05)""",
                    (session_id, source_id, target_id),
                )
            elif action_type == "unfollow":
                await db.execute(
                    """UPDATE agent_relationships
                       SET trust_score = MAX(-1.0, trust_score - 0.15)
                       WHERE session_id = ? AND agent_a_id = ? AND agent_b_id = ?""",
                    (session_id, source_id, target_id),
                )
            elif action_type == "mute":
                await db.execute(
                    """INSERT INTO agent_relationships
                       (session_id, agent_a_id, agent_b_id, relationship_type, trust_score)
                       VALUES (?, ?, ?, 'muted', -0.5)
                       ON CONFLICT(session_id, agent_a_id, agent_b_id) DO UPDATE
                       SET relationship_type = 'muted', trust_score = MAX(-1.0, trust_score - 0.3)""",
                    (session_id, source_id, target_id),
                )
            elif action_type == "unmute":
                await db.execute(
                    """UPDATE agent_relationships
                       SET relationship_type = 'follows',
                           trust_score = MIN(0.0, trust_score + 0.2)
                       WHERE session_id = ? AND agent_a_id = ? AND agent_b_id = ?""",
                    (session_id, source_id, target_id),
                )
            await db.commit()

    # ------------------------------------------------------------------
    # Stochastic activation
    # ------------------------------------------------------------------

    def get_active_agents_for_round(
        self,
        session_id: str,
        round_num: int,
        all_agents: list[dict[str, Any]],
        seed: int | None = None,
    ) -> list[dict[str, Any]]:
        """Stochastic activation: each agent independently activated by activity_level.

        Stakeholders have a floor of 0.8 to ensure they participate most rounds.
        When *seed* is provided, activation is deterministic for the given
        (seed, round_num) pair — enabling reproducible simulation runs.
        """
        rng = _random.Random(f"{seed}_{round_num}" if seed is not None else None)
        active: list[dict[str, Any]] = []
        for agent in all_agents:
            level = agent.get("activity_level", 0.5)
            if agent.get("is_stakeholder"):
                level = max(level, 0.8)  # stakeholder floor
            if rng.random() < level:
                active.append(agent)
        return active

    # ------------------------------------------------------------------
    # kg_driven mode helpers
    # ------------------------------------------------------------------

    async def _init_kg_driven_mode(
        self, session_id: str, config: dict[str, Any]
    ) -> None:
        """Detect kg_driven mode from config and initialise services.

        Only activates when ``sim_mode`` in the config is ``"kg_driven"``
        (or falls back to DB lookup). For hk_demographic this is a no-op.
        """
        sim_mode = config.get("sim_mode", "")
        if not sim_mode:
            # Fallback: check DB for the session's sim_mode
            try:
                from backend.app.utils.db import get_db  # noqa: PLC0415
                async with get_db() as db:
                    cursor = await db.execute(
                        "SELECT sim_mode FROM simulation_sessions WHERE id = ?",
                        (session_id,),
                    )
                    row = await cursor.fetchone()
                    sim_mode = row["sim_mode"] if row else ""
            except Exception:
                logger.debug("Could not load sim_mode from DB for %s", session_id)

        if sim_mode != "kg_driven":
            return

        self._kg_mode[session_id] = True
        logger.info("kg_driven mode activated for session %s", session_id)

        # Lazily create shared service instances (singleton across sessions)
        if self._world_event_gen is None:
            from backend.app.services.world_event_generator import WorldEventGenerator  # noqa: PLC0415
            self._world_event_gen = WorldEventGenerator()
        if self._cognitive_engine is None:
            from backend.app.services.cognitive_agent_engine import CognitiveAgentEngine  # noqa: PLC0415
            self._cognitive_engine = CognitiveAgentEngine()
        if self._belief_propagation is None:
            from backend.app.services.belief_propagation import BeliefPropagationEngine  # noqa: PLC0415
            self._belief_propagation = BeliefPropagationEngine()
        if self._consensus_debate is None:
            from backend.app.services.consensus_debate_engine import ConsensusDebateEngine  # noqa: PLC0415
            self._consensus_debate = ConsensusDebateEngine()
        if self._faction_mapper is None:
            from backend.app.services.emergence_tracker import FactionMapper  # noqa: PLC0415
            self._faction_mapper = FactionMapper()
        if self._tipping_detector is None:
            from backend.app.services.emergence_tracker import TippingPointDetector  # noqa: PLC0415
            self._tipping_detector = TippingPointDetector()
        if self._relationship_lifecycle is None:
            from backend.app.services.relationship_lifecycle import RelationshipLifecycleService  # noqa: PLC0415
            self._relationship_lifecycle = RelationshipLifecycleService()
        if self._relationship_memory is None:
            from backend.app.services.relationship_memory import RelationshipMemoryService  # noqa: PLC0415
            self._relationship_memory = RelationshipMemoryService()
        if self._strategic_planner is None:
            from backend.app.services.strategic_planner import StrategicPlanner  # noqa: PLC0415
            self._strategic_planner = StrategicPlanner()
        if self._reflection_service is None:
            from backend.app.services.reflection_service import ReflectionService  # noqa: PLC0415
            self._reflection_service = ReflectionService()

        # Initialise per-session state via KGSessionState
        lite = config.get("lite_ensemble", False)
        self._kg_sessions[session_id] = KGSessionState(lite_ensemble=lite)
        if lite:
            logger.info("lite_ensemble mode: rule-based hooks for session %s", session_id)

        # Load scenario description + active metrics from DB (if available)
        await self._load_kg_session_context(session_id, config)

        # Initialise relationship states and attachment styles from KG edges
        await self._init_relationship_and_attachment(session_id, config)

    async def _load_kg_session_context(
        self, session_id: str, config: dict[str, Any]
    ) -> None:
        """Load seed text, scenario config, and tier-1 agents for kg_driven."""
        try:
            from backend.app.utils.db import get_db  # noqa: PLC0415
            async with get_db() as db:
                # Seed text as scenario description
                cursor = await db.execute(
                    "SELECT seed_text FROM simulation_sessions WHERE id = ?",
                    (session_id,),
                )
                row = await cursor.fetchone()
                if row and row["seed_text"]:
                    self._kg_sessions[session_id].scenario_description = row["seed_text"][:500]

                # Load ALL agent profiles with stakeholder/activity metadata
                cursor = await db.execute(
                    """SELECT id, oasis_username AS name,
                              json_extract(properties, '$.role') AS role,
                              json_extract(properties, '$.faction') AS faction,
                              is_stakeholder,
                              activity_level
                       FROM agent_profiles
                       WHERE session_id = ?
                       ORDER BY CAST(json_extract(properties, '$.importance') AS REAL) DESC""",
                    (session_id,),
                )
                rows = await cursor.fetchall()
                all_agents: list[dict[str, Any]] = []
                stakeholders: list[dict[str, Any]] = []
                for r in rows:
                    agent_dict: dict[str, Any] = {
                        "id": r["id"],
                        "name": r["name"] or "",
                        "role": r["role"] or "",
                        "faction": r["faction"] or "none",
                        "is_stakeholder": bool(r["is_stakeholder"]) if r["is_stakeholder"] else False,
                        "activity_level": float(r["activity_level"]) if r["activity_level"] else 0.5,
                    }
                    all_agents.append(agent_dict)
                    if agent_dict["is_stakeholder"]:
                        stakeholders.append(agent_dict)
                self._kg_sessions[session_id].stakeholder_agents = stakeholders
                self._kg_sessions[session_id].all_agent_dicts = all_agents

                # Store activation seed from config or hook_config
                hook_cfg = getattr(getattr(self, "_preset", None), "hook_config", None)
                self._kg_sessions[session_id].activation_seed = (
                    config.get("activation_seed")
                    or getattr(hook_cfg, "activation_seed", None)
                )

                # Generate scenario config (decision types, metrics, shocks) via LLM
                # Only if active_metrics not already populated
                if not self._kg_sessions[session_id].active_metrics:
                    seed_desc = self._kg_sessions[session_id].scenario_description
                    if seed_desc:
                        try:
                            from backend.app.services.scenario_generator import ScenarioGenerator  # noqa: PLC0415
                            from backend.app.models.universal_agent_profile import UniversalAgentProfile  # noqa: PLC0415

                            # Resolve graph_id for this session
                            gcursor = await db.execute(
                                "SELECT graph_id FROM simulation_sessions WHERE id = ?",
                                (session_id,),
                            )
                            grow = await gcursor.fetchone()
                            graph_id = grow["graph_id"] if grow else None

                            kg_nodes: list[dict] = []
                            kg_edges: list[dict] = []
                            if graph_id:
                                ncursor = await db.execute(
                                    "SELECT id, entity_type, title, description"
                                    " FROM kg_nodes WHERE session_id = ?",
                                    (graph_id,),
                                )
                                kg_nodes = [
                                    {"id": r["id"], "label": r["title"], "type": r["entity_type"]}
                                    for r in await ncursor.fetchall()
                                ]
                                ecursor = await db.execute(
                                    "SELECT source_id, target_id, relation_type"
                                    " FROM kg_edges WHERE session_id = ?",
                                    (graph_id,),
                                )
                                kg_edges = [
                                    {"source": r["source_id"], "target": r["target_id"], "relation": r["relation_type"]}
                                    for r in await ecursor.fetchall()
                                ]

                            # Build minimal UniversalAgentProfile stubs from tier-1 agents
                            agent_profiles: list[UniversalAgentProfile] = [
                                UniversalAgentProfile(
                                    id=a["id"],
                                    name=a["name"],
                                    role=a["role"],
                                    entity_type="Person",
                                    persona="",
                                    goals=(),
                                    capabilities=(),
                                    stance_axes=(),
                                    relationships=(),
                                    kg_node_id=a["id"],
                                )
                                for a in tier1
                            ]

                            gen = ScenarioGenerator()
                            scenario_cfg = await gen.generate(
                                seed_desc, kg_nodes, kg_edges, agent_profiles
                            )
                            if scenario_cfg and scenario_cfg.metrics:
                                self._kg_sessions[session_id].active_metrics = [
                                    m.id for m in scenario_cfg.metrics
                                ]
                                logger.info(
                                    "ScenarioGenerator: %d metrics for session %s: %s",
                                    len(self._kg_sessions[session_id].active_metrics),
                                    session_id,
                                    self._kg_sessions[session_id].active_metrics[:5],
                                )
                        except Exception:
                            logger.warning(
                                "ScenarioGenerator failed for session %s — using empty metrics",
                                session_id,
                                exc_info=True,
                            )

        except Exception:
            logger.warning(
                "Could not load kg_driven context for session %s",
                session_id,
                exc_info=True,
            )

    async def _init_relationship_and_attachment(
        self, session_id: str, config: dict[str, Any]
    ) -> None:
        """Initialise relationship states and attachment styles for kg_driven.

        Loads KG edges for the session's graph and creates a RelationshipState
        for each directed edge pair via RelationshipEngine.initialize_relationship().
        Derives AttachmentStyle for every agent from their Big Five traits stored
        in agent_profiles.

        Errors are caught and logged — missing data leaves the dicts empty, which
        is safe (hooks guard on empty dicts).
        """
        kg_state = self._kg_sessions.get(session_id)
        if kg_state is None:
            return
        try:
            from backend.app.services.relationship_engine import RelationshipEngine  # noqa: PLC0415
            from backend.app.services.relationship_engine import infer_attachment_style  # noqa: PLC0415
            from backend.app.utils.db import get_db  # noqa: PLC0415

            engine = RelationshipEngine()

            async with get_db() as db:
                # Resolve graph_id from the session
                cursor = await db.execute(
                    "SELECT graph_id FROM simulation_sessions WHERE id = ?",
                    (session_id,),
                )
                row = await cursor.fetchone()
                graph_id = row["graph_id"] if row and row["graph_id"] else None

                # Load KG edges and seed relationship states
                if graph_id:
                    cursor = await db.execute(
                        """SELECT source_id, target_id, label
                           FROM kg_edges
                           WHERE graph_id = ?""",
                        (graph_id,),
                    )
                    edges = await cursor.fetchall()
                    rel_states: dict[tuple[str, str], Any] = {}
                    for edge in edges:
                        src = str(edge["source_id"])
                        tgt = str(edge["target_id"])
                        desc = str(edge["label"] or "")
                        state = engine.initialize_relationship(
                            agent_a_id=src,
                            agent_b_id=tgt,
                            edge_description=desc,
                        )
                        rel_states[(src, tgt)] = state
                    kg_state.relationship_states = rel_states
                    logger.debug(
                        "_init_relationship_and_attachment: %d edges → %d relationship states session=%s",
                        len(edges),
                        len(rel_states),
                        session_id,
                    )

                # Load agent Big Five traits and derive attachment styles
                cursor = await db.execute(
                    """SELECT id,
                              CAST(json_extract(properties, '$.neuroticism') AS REAL) AS neuroticism,
                              CAST(json_extract(properties, '$.agreeableness') AS REAL) AS agreeableness,
                              CAST(json_extract(properties, '$.openness') AS REAL) AS openness
                       FROM agent_profiles
                       WHERE session_id = ?""",
                    (session_id,),
                )
                agent_rows = await cursor.fetchall()
                attachment_styles: dict[str, Any] = {}
                for ar in agent_rows:
                    agent_id = str(ar["id"])
                    neuroticism = float(ar["neuroticism"] or 0.5)
                    agreeableness = float(ar["agreeableness"] or 0.5)
                    openness = float(ar["openness"] or 0.5)
                    attachment_styles[agent_id] = infer_attachment_style(
                        agent_id=agent_id,
                        neuroticism=neuroticism,
                        agreeableness=agreeableness,
                        openness=openness,
                    )
                kg_state.attachment_styles = attachment_styles
                logger.debug(
                    "_init_relationship_and_attachment: %d attachment styles session=%s",
                    len(attachment_styles),
                    session_id,
                )

        except Exception:
            logger.warning(
                "_init_relationship_and_attachment failed session=%s — proceeding with empty states",
                session_id,
                exc_info=True,
            )

    async def _kg_generate_world_events(
        self, session_id: str, round_num: int
    ) -> None:
        """Pre-round: generate world events for kg_driven mode."""
        kg_state = self._kg_sessions.get(session_id)
        if kg_state is None:
            return

        # Lite ensemble: rule-based event generation (no LLM)
        if kg_state.lite_ensemble:
            from backend.app.services.lite_hooks import generate_lite_events  # noqa: PLC0415
            events = generate_lite_events(
                round_number=round_num,
                active_metrics=tuple(kg_state.active_metrics.keys()),
                prev_dominant_stance=kg_state.prev_dominant_stance,
                event_history=kg_state.event_content_history,
            )
            kg_state.current_round_events = events
            kg_state.event_content_history = kg_state.event_content_history + [
                e.content for e in events
            ]
            return

        if self._world_event_gen is None:
            return
        try:
            events = await self._world_event_gen.generate(
                scenario_description=kg_state.scenario_description,
                round_number=round_num,
                active_metrics=tuple(kg_state.active_metrics.keys()),
                prev_dominant_stance=kg_state.prev_dominant_stance,
                event_history=kg_state.event_content_history,
            )
            kg_state.current_round_events = events
            kg_state.event_content_history = kg_state.event_content_history + [
                e.content for e in events
            ]
        except Exception:
            logger.exception(
                "kg_driven world event generation failed session=%s round=%d",
                session_id, round_num,
            )
            kg_state.current_round_events = []

    async def _kg_deliberation(
        self, session_id: str, round_num: int
    ) -> None:
        """Group 2: stochastic cognitive deliberation for kg_driven mode.

        Replaces the former Tier-1-only gate: every round a stochastic subset
        of ALL agents is activated (probability = activity_level, stakeholder
        floor = 0.8).  All activated agents receive full LLM deliberation.
        """
        kg_state = self._kg_sessions.get(session_id)
        if kg_state is None:
            return

        # Determine active agents for this round via stochastic activation
        all_agents = kg_state.all_agent_dicts
        if not all_agents:
            # Fallback: use stakeholder list if all_agent_dicts not populated
            all_agents = kg_state.stakeholder_agents
        if not all_agents:
            return

        active = self.get_active_agents_for_round(
            session_id, round_num, all_agents,
            seed=kg_state.activation_seed,
        )
        if not active:
            return

        # Lite ensemble: rule-based deliberation (no LLM)
        if kg_state.lite_ensemble:
            from backend.app.services.lite_hooks import deliberate_lite  # noqa: PLC0415
            events = kg_state.current_round_events
            for agent in active:
                agent_id = agent.get("id", "")
                beliefs = kg_state.agent_beliefs.get(agent_id, {})
                emotional = kg_state.emotional_states.get(agent_id)
                result = deliberate_lite(
                    agent=agent,
                    beliefs=beliefs,
                    events=events,
                    emotional_state=emotional,
                )
                # Apply belief updates
                if agent_id in kg_state.agent_beliefs:
                    updated = dict(kg_state.agent_beliefs[agent_id])
                    for metric, delta in result.belief_updates.items():
                        if metric in updated:
                            updated[metric] = max(0.0, min(1.0, updated[metric] + delta))
                    kg_state.agent_beliefs[agent_id] = updated
            return

        if self._cognitive_engine is None:
            return
        current_events = kg_state.current_round_events
        metrics = dict(kg_state.active_metrics)
        scenario = kg_state.scenario_description

        # Build id->profile lookup for relationship-depth disclosure
        active_agents_by_id: dict[str, dict] = {
            a.get("id", ""): a for a in active if a.get("id")
        }

        # Snapshot metrics once -- all agents deliberate against the same baseline.
        # Belief updates are accumulated after all coroutines complete so that
        # parallel execution is equivalent to sequential reads of round-start state.
        baseline_metrics = dict(metrics)
        active_metric_keys = tuple(baseline_metrics.keys())
        recent_event_contents = [e.content for e in current_events]

        concurrency = getattr(
            getattr(self, "_preset", None), "hook_config", None
        )
        concurrency = getattr(concurrency, "llm_concurrency", 50) if concurrency else 50
        semaphore = asyncio.Semaphore(concurrency)

        async def _deliberate_one(agent: dict) -> "Any":
            """Run deliberation for one activated agent under semaphore guard."""
            async with semaphore:
                import hashlib as _hashlib  # noqa: PLC0415
                agent_id = agent.get("id", "")
                emotional_state = kg_state.emotional_states.get(agent_id)
                attachment = kg_state.attachment_styles.get(agent_id)
                rel_states = kg_state.relationship_states
                key_relationships = _build_key_relationships(
                    agent_id=agent_id,
                    rel_states=rel_states,
                    stakeholder_agents_by_id=active_agents_by_id,
                )

                # Task 2.6: retrieve salient memories to ground deliberation.
                recent_memories = ""
                if self._memory_service is not None:
                    try:
                        numeric_id = int(
                            _hashlib.md5(agent_id.encode()).hexdigest(), 16
                        ) % (2**31)
                        recent_memories = await self._memory_service.get_agent_context(
                            session_id=session_id,
                            agent_id=numeric_id,
                            current_round=round_num,
                            context_query=scenario,
                        )
                    except Exception:
                        pass  # memory unavailable -- degrade gracefully

                # Task 2.3: use dynamically detected faction (set every 3 rounds);
                # fall back to static value from agent profile.
                dynamic_faction = kg_state.agent_factions.get(agent_id)
                faction_str = dynamic_faction if dynamic_faction else agent.get("faction", "none")

                # Phase 4: inject strategic plan context if available
                strategy_context = ""
                if self._strategic_planner is not None:
                    strategy_context = self._strategic_planner.get_strategy_context(
                        kg_state=kg_state,
                        agent_id=agent_id,
                        current_round=round_num,
                    )

                agent_context = {
                    "agent_id": agent_id,
                    "name": agent.get("name", ""),
                    "role": agent.get("role", ""),
                    "persona": agent.get("persona", ""),
                    "goals": list(agent.get("goals", [])),
                    "current_beliefs": baseline_metrics,
                    "recent_events": recent_event_contents,
                    "faction": faction_str,
                    "recent_memories": recent_memories,
                    "strategic_context": strategy_context,
                    "emotional_state": (
                        {
                            "valence": getattr(emotional_state, "valence", 0.0),
                            "arousal": getattr(emotional_state, "arousal", 0.3),
                        }
                        if emotional_state is not None else {}
                    ),
                    "attachment_style": (
                        {
                            "style": attachment.style,
                            "anxiety": attachment.anxiety,
                            "avoidance": attachment.avoidance,
                        }
                        if attachment is not None else {}
                    ),
                    "key_relationships": key_relationships,
                }
                return await self._cognitive_engine.deliberate(
                    agent_context=agent_context,
                    scenario_description=scenario,
                    active_metrics=active_metric_keys,
                )

        # Fan out: deliberate all activated agents in parallel (bounded by semaphore)
        results = await asyncio.gather(
            *[_deliberate_one(agent) for agent in active],
            return_exceptions=True,
        )

        # Accumulate belief updates from all agents sequentially after gathering
        for agent, result in zip(active, results):
            if isinstance(result, Exception):
                logger.warning(
                    "Deliberation failed for agent %s session=%s: %s",
                    agent.get("id", "?"), session_id, result,
                )
                continue
            for metric_id, delta in result.belief_updates.items():
                if metric_id in metrics:
                    metrics[metric_id] = max(0.0, min(1.0, metrics[metric_id] + delta))

        kg_state.active_metrics = metrics

        # Reflection loop: synthesise 'thought' memories for activated agents
        # every reflection_interval rounds (Generative Agents-inspired).
        hook_cfg = self._preset.hook_config
        if (
            self._reflection_service is not None
            and round_num > 0
            and round_num % hook_cfg.reflection_interval == 0
        ):
            try:
                n = await self._reflection_service.reflect_for_agents(
                    session_id=session_id,
                    round_number=round_num,
                    stakeholder_agents=active,
                    scenario_description=scenario,
                )
                logger.debug(
                    "Reflection loop: %d thoughts generated session=%s round=%d",
                    n, session_id, round_num,
                )
            except Exception:
                logger.debug(
                    "Reflection loop failed session=%s round=%d", session_id, round_num
                )

    async def _kg_strategic_planning(
        self, session_id: str, round_num: int
    ) -> None:
        """Group 2: refresh strategic plans every _PLAN_HORIZON rounds.

        Phase 4 -- multi-round planning.  On plan rounds, each activated agent
        produces a 3-round intent plan via LLM.  The plan is stored in
        kg_state.agent_strategies and injected into the deliberation prompt
        for subsequent rounds so agents act with strategic consistency.

        Uses stochastic activation instead of a fixed Tier-1 gate.
        """
        kg_state = self._kg_sessions.get(session_id)
        if kg_state is None:
            return
        # Lite ensemble: skip LLM strategic planning (deliberate_lite handles it)
        if kg_state.lite_ensemble:
            return
        if self._strategic_planner is None:
            return

        all_agents = kg_state.all_agent_dicts or kg_state.stakeholder_agents
        if not all_agents:
            return

        active = self.get_active_agents_for_round(
            session_id, round_num, all_agents,
            seed=kg_state.activation_seed,
        )
        if not active:
            return

        try:
            await self._strategic_planner.update_plans(
                kg_state=kg_state,
                stakeholder_agents=active,
                round_num=round_num,
                scenario_description=kg_state.scenario_description,
            )
        except Exception:
            logger.debug("_kg_strategic_planning: planner failed session=%s round=%d", session_id, round_num)

    async def _kg_consensus_debate(
        self, session_id: str, round_num: int
    ) -> None:
        """Group 2: structured multi-agent debate on divergent topics.

        Runs every N rounds (default 3). Pairs stochastically activated agents
        with opposing stances on high-divergence topics for pairwise LLM debate.
        Debate deltas feed into agent_beliefs before belief_propagation.
        """
        kg_state = self._kg_sessions.get(session_id)
        if kg_state is None or not kg_state.agent_beliefs:
            return

        all_agents = kg_state.all_agent_dicts or kg_state.stakeholder_agents
        if not all_agents:
            return

        active = self.get_active_agents_for_round(
            session_id, round_num, all_agents,
            seed=kg_state.activation_seed,
        )
        if not active:
            return

        # Lite ensemble: rule-based debate (no LLM)
        if kg_state.lite_ensemble:
            from backend.app.services.lite_hooks import run_debate_round_lite  # noqa: PLC0415
            kg_state.agent_beliefs = run_debate_round_lite(
                stakeholder_agents=active,
                agent_beliefs=kg_state.agent_beliefs,
                round_num=round_num,
            )
            return

        if self._consensus_debate is None:
            return
        if not self._consensus_debate.should_trigger(round_num):
            return

        try:
            # Build agent_profiles lookup for enrichment
            agent_profiles: dict[str, dict] = {}
            for agent in active:
                aid = agent["id"]
                profile: dict = {"persona": "", "recent_memories": ""}
                # Enrich with strategy context if available
                strategy = kg_state.agent_strategies.get(aid)
                if strategy:
                    profile["persona"] = strategy.get("plan", "")
                agent_profiles[aid] = profile

            result = await self._consensus_debate.run_debate(
                session_id=session_id,
                round_num=round_num,
                stakeholder_agents=active,
                agent_beliefs=kg_state.agent_beliefs,
                scenario_description=kg_state.scenario_description,
                agent_profiles=agent_profiles,
            )

            # Apply debate belief deltas to agent_beliefs
            if result.exchanges:
                deltas = self._consensus_debate.get_belief_deltas(result)
                updated = {
                    aid: dict(b) for aid, b in kg_state.agent_beliefs.items()
                }
                for agent_id, topic_deltas in deltas.items():
                    if agent_id not in updated:
                        continue
                    for topic, delta in topic_deltas.items():
                        if topic in updated[agent_id]:
                            updated[agent_id][topic] = max(
                                0.0, min(1.0, updated[agent_id][topic] + delta)
                            )
                kg_state.agent_beliefs = updated

                logger.info(
                    "consensus_debate session=%s round=%d pairs=%d topics=%d avg_consensus=%.2f",
                    session_id[:8],
                    round_num,
                    result.pairs_debated,
                    result.topics_debated,
                    (
                        sum(result.consensus_scores.values()) / len(result.consensus_scores)
                        if result.consensus_scores
                        else 0.0
                    ),
                )
        except Exception:
            logger.exception(
                "_kg_consensus_debate failed session=%s round=%d",
                session_id[:8],
                round_num,
            )

    async def _kg_belief_propagation(
        self, session_id: str, round_num: int
    ) -> None:
        """Group 2: propagate world events into agent beliefs, then 1-hop cascade.

        Tasks 2.1 + 2.2: wires BeliefPropagationEngine (previously never called)
        and adds neighbour cascade so one agent's significant belief shift
        pulls its interaction partners in the same direction.
        """
        if self._belief_propagation is None:
            return
        kg_state = self._kg_sessions.get(session_id)
        if kg_state is None or not kg_state.agent_beliefs:
            return

        events = kg_state.current_round_events
        active_metrics = tuple(kg_state.active_metrics.keys())
        if not active_metrics:
            return

        from backend.app.models.cognitive_fingerprint import CognitiveFingerprint  # noqa: PLC0415

        # --- Propagation: world events → per-agent belief deltas ---
        all_deltas: dict[str, dict[str, float]] = {}
        for agent_id, beliefs in kg_state.agent_beliefs.items():
            # Build a default fingerprint from session state.
            # CognitiveFingerprints are not yet persisted in SimulationRunner;
            # defaults give reasonable confirmation_bias / conformity values.
            fingerprint = CognitiveFingerprint(
                agent_id=agent_id,
                values={"authority": 0.5, "openness": 0.5, "loyalty": 0.5},
                info_diet=("news", "social_media", "state_media"),
                group_memberships=(),
                susceptibility={m: 0.5 for m in active_metrics},
                confirmation_bias=0.4,
                conformity=0.3,
            )
            faction_id = kg_state.agent_factions.get(agent_id, "")
            faction_peer_stance = _compute_faction_peer_stance(
                faction_id=faction_id,
                agent_id=agent_id,
                agent_beliefs=kg_state.agent_beliefs,
                agent_factions=kg_state.agent_factions,
            )
            delta = await self._belief_propagation.propagate(
                fingerprint=fingerprint,
                events=list(events),
                faction_peer_stance=faction_peer_stance,
                active_metrics=active_metrics,
                current_beliefs=beliefs,
            )
            if delta:
                all_deltas[agent_id] = delta

        # Apply propagation deltas via Bayesian core (immutable update)
        from backend.app.services.belief_system import BeliefSystem  # noqa: PLC0415
        _bs = BeliefSystem()

        updated: dict[str, dict[str, float]] = {
            aid: dict(b) for aid, b in kg_state.agent_beliefs.items()
        }
        for agent_id, deltas in all_deltas.items():
            for m, d in deltas.items():
                if m in updated.get(agent_id, {}):
                    current = updated[agent_id][m]
                    # Convert delta to likelihood ratio for Bayesian update
                    lr = _bs.compute_likelihood_ratio(
                        evidence_stance=d,
                        evidence_weight=abs(d),
                        belief_stance=current * 2.0 - 1.0,
                        confirmation_bias=0.4,
                    )
                    updated[agent_id][m] = _bs._bayesian_core(current, lr)

        # --- Cascade: 1-hop neighbour pull for large shifts (Task 2.2) ---
        cascade_deltas = self._belief_propagation.cascade(
            all_deltas=all_deltas,
            interaction_graph=kg_state.interaction_graph,
        )
        for agent_id, c_deltas in cascade_deltas.items():
            if agent_id in updated:
                for m, d in c_deltas.items():
                    if m in updated[agent_id]:
                        current = updated[agent_id][m]
                        lr = _bs.compute_likelihood_ratio(
                            evidence_stance=d,
                            evidence_weight=abs(d),
                            belief_stance=current * 2.0 - 1.0,
                            confirmation_bias=0.4,
                        )
                        updated[agent_id][m] = _bs._bayesian_core(current, lr)

        kg_state.agent_beliefs = updated

        # --- Persist beliefs to belief_states table for multi-run ensemble ---
        try:
            import hashlib  # noqa: PLC0415

            belief_rows = []
            for aid, metric_dict in updated.items():
                # Convert string agent_id (slug) to deterministic int for DB
                agent_int = int(hashlib.md5(aid.encode()).hexdigest()[:12], 16)
                for metric_name, stance_val in metric_dict.items():
                    belief_rows.append((
                        session_id, agent_int, metric_name,
                        stance_val, 0.5, 0, round_num,
                    ))
            if belief_rows:
                # Route through BatchWriter if available for reduced DB round-trips
                if self._batch_writer is not None:
                    for row in belief_rows:
                        self._batch_writer.queue("belief_states", row)
                    async with get_db() as db:
                        await self._batch_writer.flush("belief_states", db)
                else:
                    async with get_db() as db:
                        await db.executemany(
                            """INSERT OR REPLACE INTO belief_states
                               (session_id, agent_id, topic, stance,
                                confidence, evidence_count, round_number)
                               VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            belief_rows,
                        )
                        await db.commit()
        except Exception:
            logger.debug(
                "_kg_belief_propagation: persist to belief_states failed session=%s",
                session_id, exc_info=True,
            )

        logger.debug(
            "_kg_belief_propagation session=%s round=%d agents=%d cascades=%d",
            session_id, round_num, len(all_deltas), len(cascade_deltas),
        )

    async def _process_relationship_states(
        self, session_id: str, round_num: int
    ) -> None:
        """Group 1 parallel: update multi-dimensional relationship states.

        Reads interaction valences from simulation_actions for this round,
        runs RelationshipEngine.batch_update(), and stores updated states
        both in the in-memory cache and in the relationship_states table.

        Active only in kg_driven mode + emergence_enabled.
        """
        from backend.app.services.relationship_engine import RelationshipEngine  # noqa: PLC0415

        kg_state = self._kg_sessions.get(session_id)
        if kg_state is None or not kg_state.relationship_states:
            return

        try:
            engine = RelationshipEngine()
            rel_states = kg_state.relationship_states

            # Gather interaction valences from simulation_actions this round
            valences: dict[tuple[str, str], float] = {}
            try:
                async with __import__("backend.app.utils.db", fromlist=["get_db"]).get_db() as db:
                    cursor = await db.execute(
                        """
                        SELECT oasis_username, target_agent_username, sentiment
                        FROM simulation_actions
                        WHERE session_id = ? AND round_number = ?
                          AND target_agent_username IS NOT NULL
                          AND target_agent_username != ''
                        """,
                        (session_id, round_num),
                    )
                    rows = await cursor.fetchall()
                    for row in rows:
                        aid, bid, sentiment = row[0], row[1], (row[2] or "neutral")
                        v = 0.5 if sentiment == "positive" else (-0.5 if sentiment == "negative" else 0.0)
                        valences[(str(aid), str(bid))] = v
            except Exception:
                logger.debug(
                    "_process_relationship_states: could not load valences session=%s",
                    session_id,
                )

            profiles = {
                r["oasis_username"]: {
                    "agreeableness": float(r.get("agreeableness", 0.5) or 0.5),
                    "neuroticism": float(r.get("neuroticism", 0.5) or 0.5),
                }
                for r in self._round_profiles.get(session_id, [])
                if r.get("oasis_username")
            }
            attachment_styles = kg_state.attachment_styles

            updated = engine.batch_update(
                states=rel_states,
                interactions=valences,
                profiles=profiles,
                attachment_styles=attachment_styles,
            )

            # Update in-memory cache (immutable replace)
            new_states = dict(rel_states)
            for state in updated:
                new_states[(state.agent_a_id, state.agent_b_id)] = state
            kg_state.relationship_states = new_states

            # Validate relationship coherence (best-effort, never blocks simulation)
            try:
                from backend.app.services.relationship_validator import RelationshipValidator  # noqa: PLC0415
                validator = RelationshipValidator()
                validation = await validator.validate(session_id)
                if validation.dunbar_violation:
                    logger.warning(
                        "Dunbar violation session=%s round=%d avg_degree=%.2f",
                        session_id, round_num, validation.avg_meaningful_degree,
                    )
            except Exception:
                logger.debug(
                    "Relationship validation skipped session=%s round=%d",
                    session_id, round_num,
                )

            # Persist updated states to DB via BatchWriter or direct executemany
            if updated:
                from datetime import datetime as _rel_dt  # noqa: PLC0415
                from datetime import timezone as _rel_tz  # noqa: PLC0415
                _now_str = _rel_dt.now(_rel_tz.utc).strftime("%Y-%m-%d %H:%M:%S")
                rel_rows = [
                    (
                        session_id,
                        s.agent_a_id, s.agent_b_id, round_num,
                        s.intimacy, s.passion, s.commitment,
                        s.satisfaction, s.alternatives, s.investment,
                        s.trust, s.interaction_count, s.rounds_since_change,
                        _now_str,
                    )
                    for s in updated
                ]
                if self._batch_writer is not None:
                    for row in rel_rows:
                        self._batch_writer.queue("relationship_states", row)
                    async with __import__("backend.app.utils.db", fromlist=["get_db"]).get_db() as db:
                        await self._batch_writer.flush("relationship_states", db)
                else:
                    async with __import__("backend.app.utils.db", fromlist=["get_db"]).get_db() as db:
                        await db.executemany(
                            """
                            INSERT OR REPLACE INTO relationship_states
                                (session_id, agent_a_id, agent_b_id, round_number,
                                 intimacy, passion, commitment, satisfaction,
                                 alternatives, investment, trust,
                                 interaction_count, rounds_since_change,
                                 updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            rel_rows,
                        )
                        await db.commit()

        except Exception:
            logger.exception(
                "_process_relationship_states failed session=%s round=%d",
                session_id, round_num,
            )

    async def _process_relationship_lifecycle(
        self, session_id: str, round_num: int
    ) -> None:
        """Group 3 periodic: detect and persist relationship lifecycle events.

        Active only in kg_driven mode + emergence_enabled.
        Reads current relationship states from KGSessionState.relationship_states, detects
        lifecycle transitions, and persists events to network_events table.
        """
        if self._relationship_lifecycle is None:
            return
        kg_state = self._kg_sessions.get(session_id)
        rel_states = kg_state.relationship_states if kg_state is not None else {}
        if not rel_states:
            return
        try:
            events = self._relationship_lifecycle.detect_events(
                session_id=session_id,
                round_number=round_num,
                rel_states=rel_states,
            )
            if events:
                async with __import__("backend.app.utils.db", fromlist=["get_db"]).get_db() as db:
                    await self._relationship_lifecycle.persist_events(events, db)
                # Store lifecycle events as dyadic relationship memories
                if self._relationship_memory is not None:
                    for evt in events:
                        agent_a = getattr(evt, "agent_id", None) or getattr(evt, "source_id", "")
                        agent_b = getattr(evt, "related_agent_id", None) or getattr(evt, "target_id", "")
                        evt_type = getattr(evt, "event_type", "interaction")
                        if agent_a and agent_b:
                            content = f"{evt_type}: relationship event between {agent_a} and {agent_b} at round {round_num}"
                            salience = 0.7 if evt_type in ("CRISIS", "DISSOLVED") else 0.5
                            await self._relationship_memory.store_interaction_memory(
                                session_id=session_id,
                                agent_id=str(agent_a),
                                related_agent_id=str(agent_b),
                                content=content,
                                round_number=round_num,
                                salience=salience,
                            )
                logger.debug(
                    "_process_relationship_lifecycle: %d events session=%s round=%d",
                    len(events), session_id, round_num,
                )
        except Exception:
            logger.exception(
                "_process_relationship_lifecycle failed session=%s round=%d",
                session_id, round_num,
            )

    async def _kg_faction_and_tipping(
        self, session_id: str, round_num: int
    ) -> None:
        """Group 3 periodic: faction mapping + tipping point detection."""
        kg_state = self._kg_sessions.get(session_id)
        if kg_state is None:
            return
        agent_beliefs = kg_state.agent_beliefs
        if not agent_beliefs:
            return

        # Faction mapping
        if self._faction_mapper is not None:
            try:
                snapshot = self._faction_mapper.compute(
                    simulation_id=session_id,
                    round_number=round_num,
                    agent_beliefs=agent_beliefs,
                    interaction_graph=kg_state.interaction_graph,
                )
                await self._persist_faction_snapshot(snapshot)
                # Task 2.3: feed detected factions back into KGSessionState so
                # _kg_deliberation and _kg_belief_propagation can use them
                # in subsequent rounds (data is 3 rounds old — intentional lag).
                new_factions: dict[str, str] = {}
                for record in snapshot.factions:
                    for member_id in record.member_agent_ids:
                        new_factions[member_id] = record.faction_id
                kg_state.agent_factions = new_factions
            except Exception:
                logger.exception(
                    "Faction mapping failed session=%s round=%d",
                    session_id, round_num,
                )

        # Tipping point detection
        if self._tipping_detector is not None:
            try:
                current_events = kg_state.current_round_events
                tipping = self._tipping_detector.detect(
                    simulation_id=session_id,
                    round_number=round_num,
                    current_beliefs=agent_beliefs,
                    belief_history=kg_state.belief_history[-3:],
                    last_event_id=(
                        current_events[-1].event_id
                        if current_events
                        else None
                    ),
                )
                if tipping is not None:
                    await self._persist_tipping_point(tipping)
                    # Auto-fork: create divergent branches at tipping point
                    if (
                        kg_state.auto_fork_count < 3
                        and round_num not in kg_state.auto_fork_rounds
                    ):
                        self._create_tracked_task(
                            session_id,
                            self._auto_fork_at_tipping(
                                session_id, round_num, tipping, kg_state,
                            ),
                            timeout_s=30.0,
                        )
            except Exception:
                logger.exception(
                    "Tipping point detection failed session=%s round=%d",
                    session_id, round_num,
                )

        # Snapshot beliefs for history
        belief_copy = {k: dict(v) for k, v in agent_beliefs.items()}
        kg_state.belief_history = kg_state.belief_history + [belief_copy]

    async def _auto_fork_at_tipping(
        self,
        session_id: str,
        round_num: int,
        tipping: Any,
        kg_state: Any,
    ) -> None:
        """Fire-and-forget: create divergent branches at a detected tipping point."""
        from backend.app.services.auto_fork_service import fork_at_tipping_point  # noqa: PLC0415

        result = await fork_at_tipping_point(
            session_id=session_id,
            tipping=tipping,
            current_beliefs=kg_state.agent_beliefs,
            auto_fork_count=kg_state.auto_fork_count,
            round_count=self._preset.rounds,
        )
        if result is not None:
            kg_state.auto_fork_count += 1
            kg_state.auto_fork_rounds = kg_state.auto_fork_rounds + [round_num]
            logger.info(
                "Auto-fork #%d created session=%s round=%d: natural=%s nudged=%s",
                kg_state.auto_fork_count, session_id, round_num,
                result.natural_branch_id[:8], result.nudged_branch_id[:8],
            )
            # Notify frontend via WebSocket
            try:
                from backend.app.api.ws import push_progress  # noqa: PLC0415
                await push_progress(session_id, {
                    "type": "auto_fork",
                    "round": round_num,
                    "direction": result.tipping_direction,
                    "natural_branch_id": result.natural_branch_id,
                    "nudged_branch_id": result.nudged_branch_id,
                    "description": result.nudge_description,
                })
            except Exception:
                pass  # WS notification is best-effort

    async def _persist_faction_snapshot(self, snapshot: Any) -> None:
        """Persist FactionSnapshot to faction_snapshots_v2 table."""
        import uuid as _uuid  # noqa: PLC0415
        from backend.app.utils.db import get_db  # noqa: PLC0415

        try:
            async with get_db() as db:
                await db.execute(
                    """INSERT OR REPLACE INTO faction_snapshots_v2
                       (id, simulation_id, round_number, factions_json,
                        bridge_agents_json, modularity_score, inter_faction_hostility)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(_uuid.uuid4()),
                        snapshot.simulation_id,
                        snapshot.round_number,
                        json.dumps([
                            {
                                "faction_id": f.faction_id,
                                "member_agent_ids": list(f.member_agent_ids),
                                "belief_center": f.belief_center,
                            }
                            for f in snapshot.factions
                        ]),
                        json.dumps(list(snapshot.bridge_agents)),
                        snapshot.modularity_score,
                        snapshot.inter_faction_hostility,
                    ),
                )
                await db.commit()
        except Exception:
            logger.exception(
                "Failed to persist faction snapshot sim=%s round=%d",
                snapshot.simulation_id, snapshot.round_number,
            )

    async def _persist_tipping_point(self, tipping: Any) -> None:
        """Persist TippingPoint to tipping_points table."""
        import uuid as _uuid  # noqa: PLC0415
        from backend.app.utils.db import get_db  # noqa: PLC0415

        try:
            async with get_db() as db:
                await db.execute(
                    """INSERT INTO tipping_points
                       (id, simulation_id, round_number, trigger_event_id,
                        kl_divergence, change_direction, affected_factions_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(_uuid.uuid4()),
                        tipping.simulation_id,
                        tipping.round_number,
                        tipping.trigger_event_id,
                        tipping.kl_divergence,
                        tipping.change_direction,
                        json.dumps(list(tipping.affected_faction_ids)),
                    ),
                )
                await db.commit()
        except Exception:
            logger.exception(
                "Failed to persist tipping point sim=%s round=%d",
                tipping.simulation_id, tipping.round_number,
            )

    async def _compute_tdmi(self, session_id: str, round_num: int) -> None:
        """Group 3 periodic: TDMI emergence measurement (every 5 rounds, both modes).

        Reads belief_states table, computes Time-Delayed Mutual Information for
        each topic × lag, and persists results to emergence_metrics table.
        Logged at INFO level; failures are non-fatal.
        """
        try:
            from backend.app.services.emergence_metrics import EmergenceMetricsCalculator  # noqa: PLC0415
            calculator = EmergenceMetricsCalculator()
            await calculator.compute_and_persist(session_id, round_num)
        except Exception:
            logger.exception(
                "_compute_tdmi failed session=%s round=%d", session_id, round_num,
            )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _require_path(path: Path, label: str) -> None:
    if not path.exists():
        raise RuntimeError(
            f"{label} not found at {path}. "
            "Check that the .venv311 virtual environment is set up correctly."
        )


def _build_full_config(config: dict[str, Any], session_id: str) -> dict[str, Any]:
    """Merge simulation config with LLM settings (excluding API key).

    Adds:
    - llm_provider  (default: fireworks)
    - llm_model     (default: deepseek/deepseek-v3.2)
    - llm_base_url  (Fireworks AI endpoint)
    - oasis_db_path (stable per-session path)

    Note: llm_api_key is intentionally excluded from the written config file
    to prevent credentials being stored on disk. Pass it via subprocess env.
    """
    session_dir = _PROJECT_ROOT / "data" / "sessions" / session_id
    oasis_db_path = str(session_dir / "oasis.db")

    provider = config.get("llm_provider", "openrouter")
    model = config.get("llm_model", "deepseek/deepseek-v3.2")
    base_url = config.get(
        "llm_base_url", "https://openrouter.ai/api/v1"
    )

    # Strip llm_api_key so it is never written to sim_config.json
    safe_config = {k: v for k, v in config.items() if k != "llm_api_key"}

    return {
        **safe_config,
        "session_id": session_id,
        "llm_provider": provider,
        "llm_model": model,
        "llm_base_url": base_url,
        "oasis_db_path": oasis_db_path,
    }


def _get_api_key() -> str:
    """Read OpenRouter API key from settings or OS env."""
    try:
        from backend.app.config import get_settings as _get_settings  # noqa: PLC0415
        key = getattr(_get_settings(), 'OPENROUTER_API_KEY', '') or ""
    except Exception:
        key = ""
    if not key:
        key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        logger.warning("OPENROUTER_API_KEY is not set — simulation will fail at LLM call")
    return key


def _try_parse_jsonl(line: str) -> dict[str, Any] | None:
    """Parse *line* as JSON; return None on failure."""
    try:
        return json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None


def _compute_faction_peer_stance(
    faction_id: str,
    agent_id: str,
    agent_beliefs: dict[str, dict[str, float]],
    agent_factions: dict[str, str],
) -> dict[str, float]:
    """Return average belief values of other agents in the same faction.

    Used by BeliefPropagationEngine to compute conformity peer pressure.
    Returns an empty dict if the faction has no other members.
    """
    if not faction_id:
        return {}
    peer_beliefs = [
        b for aid, b in agent_beliefs.items()
        if aid != agent_id and agent_factions.get(aid) == faction_id
    ]
    if not peer_beliefs:
        return {}
    all_metrics = {m for b in peer_beliefs for m in b}
    return {
        m: sum(b.get(m, 0.5) for b in peer_beliefs) / len(peer_beliefs)
        for m in all_metrics
    }


def _build_key_relationships(
    agent_id: str,
    rel_states: dict,
    stakeholder_agents_by_id: dict[str, dict] | None = None,
) -> list[dict]:
    """Extract top-5 key relationships for agent_id from relationship_states dict.

    Args:
        agent_id: The agent whose perspective we use.
        rel_states: Dict keyed by (agent_a_id, agent_b_id) → RelationshipState.
        stakeholder_agents_by_id: Optional map of agent_id → agent profile dict.
            When provided, high-intimacy peers (>0.6) reveal their goals and
            faction — implementing Sotopia-style relationship-depth disclosure.

    Returns:
        List of relationship dicts suitable for CognitiveAgentEngine context.
    """
    from backend.app.models.relationship_state import RelationshipState  # noqa: PLC0415

    relationships: list[dict] = []
    for (aid, bid), state in rel_states.items():
        if aid != agent_id:
            continue
        if not isinstance(state, RelationshipState):
            continue
        entry: dict = {
            "other_id": bid,
            "rel_type": _infer_rel_type(state),
            "intimacy": state.intimacy,
            "trust": state.trust,
            "commitment": state.commitment,
            "passion": state.passion,
        }
        # Relationship-depth disclosure: high-intimacy peers share goals + faction
        if state.intimacy > 0.6 and stakeholder_agents_by_id:
            peer = stakeholder_agents_by_id.get(bid)
            if peer:
                peer_goals = peer.get("goals", [])
                peer_faction = peer.get("faction", "")
                if peer_goals:
                    entry["peer_goals"] = list(peer_goals)
                if peer_faction:
                    entry["peer_faction"] = peer_faction
        relationships.append(entry)
    # Sort by intimacy + |trust| (most salient relationships first)
    relationships.sort(
        key=lambda r: r["intimacy"] + abs(r["trust"]),
        reverse=True,
    )
    return relationships[:5]


def _infer_rel_type(state: Any) -> str:
    """Heuristically label relationship type from state dimensions."""
    if state.passion > 0.4 and state.intimacy > 0.3:
        return "romantic"
    if state.trust < -0.3:
        return "adversarial"
    if state.commitment > 0.6:
        return "committed"
    if state.intimacy > 0.3:
        return "close"
    return "associate"
