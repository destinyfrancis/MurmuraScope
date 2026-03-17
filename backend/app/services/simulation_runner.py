"""OASIS subprocess orchestration for HKSimEngine.

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
from collections import defaultdict
import json
import os
import random
import sys
from pathlib import Path
from typing import Any, Callable, Coroutine

from backend.app.services.simulation_hooks_agent import AgentHooksMixin
from backend.app.services.simulation_hooks_kg import KGHooksMixin
from backend.app.services.simulation_hooks_macro import MacroHooksMixin
from backend.app.services.simulation_hooks_social import SocialHooksMixin
from backend.app.utils.logger import get_logger

logger = get_logger("simulation_runner")

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
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._action_logger: Any | None = None
        self._memory_service: Any | None = None
        self._vector_store: Any | None = None
        self._posts_buffer: dict[str, dict[int, dict[str, list[str]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        self._macro_controller: Any | None = None
        self._macro_history: Any | None = None
        # Tracks the latest MacroState per session for feedback accumulation
        self._macro_state: dict[str, Any] = {}
        self._decision_engine: Any | None = None
        self._media_model: Any | None = None
        self._consumption_tracker: Any | None = None
        self._bank_agent: Any | None = None
        self._trust_service: Any | None = None
        self._social_network: Any | None = None
        self._echo_chamber_result: Any | None = None
        # Track per-session background tasks to cancel them on cleanup
        self._pending_tasks: dict[str, set[asyncio.Task]] = defaultdict(set)  # type: ignore[type-arg]
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
        self._faction_mapper: Any | None = None
        self._tipping_detector: Any | None = None
        # kg_driven per-session state
        self._current_round_events: dict[str, list] = {}  # session_id → events
        self._event_content_history: dict[str, list[str]] = {}  # session_id → strings
        self._tier1_agents: dict[str, list] = {}  # session_id → agent profiles
        self._active_metrics: dict[str, dict[str, float]] = {}  # session_id → metric_id→value
        self._agent_beliefs: dict[str, dict[str, dict[str, float]]] = {}  # session_id → agent_id→beliefs
        self._belief_history: dict[str, list] = {}  # session_id → snapshots
        self._interaction_graph: dict[str, dict[str, list[str]]] = {}  # session_id → adj list
        self._prev_dominant_stance: dict[str, dict[str, float]] = {}  # session_id → metric→value
        self._scenario_description: dict[str, str] = {}  # session_id → text

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
        if session_id in self._processes:
            raise ValueError(f"Session {session_id} is already running")

        # B2B initialisation: generate company profiles if none exist for the session.
        # This is conditional (idempotent) and errors are swallowed to avoid blocking.
        await self._init_b2b_companies(session_id)
        await self._init_social_network(session_id)

        # Restore macro state from DB if this session was previously interrupted.
        if session_id not in self._macro_state:
            restored = await self._restore_macro_state(session_id)
            if restored is not None:
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

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=log_file,
                cwd=str(_PROJECT_ROOT),
                env=subprocess_env,
            )
            self._processes[session_id] = process

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
            _check_exit_code(session_id, process)

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

        finally:
            # --- 1. Cancel all tracked background tasks for this session ---
            pending = list(self._pending_tasks.pop(session_id, set()))
            if pending:
                for t in pending:
                    t.cancel()
                await asyncio.gather(*pending, return_exceptions=True)

            # --- 2. Ensure subprocess is not still running (orphan prevention) ---
            # process is None only if subprocess creation itself failed.
            if process is not None and process.returncode is None:
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

            self._processes.pop(session_id, None)
            # Clean up posts buffer to prevent memory leak
            self._posts_buffer.pop(session_id, None)
            # Clean up macro state cache
            self._macro_state.pop(session_id, None)
            # Phase 1B: clean up temporal activation caches
            self._activity_profiles.pop(session_id, None)
            self._activation_rngs.pop(session_id, None)
            # Phase 3: clean up pending arousal deltas
            self._pending_arousal_deltas.pop(session_id, None)
            # kg_driven mode: clean up per-session state
            self._kg_mode.pop(session_id, None)
            self._current_round_events.pop(session_id, None)
            self._event_content_history.pop(session_id, None)
            self._tier1_agents.pop(session_id, None)
            self._active_metrics.pop(session_id, None)
            self._agent_beliefs.pop(session_id, None)
            self._belief_history.pop(session_id, None)
            self._interaction_graph.pop(session_id, None)
            self._prev_dominant_stance.pop(session_id, None)
            self._scenario_description.pop(session_id, None)
            # Close LanceDB connection to free resources
            if self._vector_store is not None:
                try:
                    await self._vector_store.close()
                except Exception:
                    logger.debug("VectorStore close failed session=%s", session_id)
            # Close log file — guarded so it's safe if open() itself failed
            if log_file is not None:
                log_file.close()

    def _create_tracked_task(self, session_id: str, coro: Any) -> "asyncio.Task[Any]":
        """Create an asyncio task and register it for cleanup on session end.

        All fire-and-forget tasks must go through this method so that the
        finally block in run() can cancel them if the simulation ends before
        the task completes, preventing async task leaks.
        """
        task: asyncio.Task[Any] = asyncio.create_task(coro)
        task_set = self._pending_tasks[session_id]
        task_set.add(task)
        task.add_done_callback(lambda t: task_set.discard(t))
        return task

    async def _execute_round_hooks(self, session_id: str, round_num: int) -> None:
        """Execute round hooks with dependency-aware grouping.

        Group 1 (parallel, awaited): memories + trust (+ emotional_state if emergence)
        Group 2 (sequential after G1): decisions → side effects (+ belief if emergence) → consumption
        Group 3 (periodic, fire-and-forget): all interval-driven hooks
        """
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
        await self._process_round_decisions(session_id, round_num)
        await self._apply_decision_side_effects(session_id, round_num)
        if hc.emergence_enabled:
            await self._process_belief_update(session_id, round_num)
        await self._process_round_consumption(session_id, round_num)
        # kg_driven: Tier 1 cognitive deliberation
        if self._kg_mode.get(session_id):
            await self._kg_tier1_deliberation(session_id, round_num)
        if self._profiler:
            self._profiler.end_hook("group_2", round_num, _t_g2)

        # Group 3: Periodic hooks (fire-and-forget, tracked for cleanup)
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
            )
            if hc.emergence_enabled:
                self._create_tracked_task(
                    session_id,
                    self._process_info_warfare(session_id, round_num),
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
            )
        if round_num > 0 and round_num % hc.kg_evolution_interval == 0:
            self._create_tracked_task(
                session_id,
                self._process_kg_evolution(session_id, round_num),
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
        if round_num > 0 and round_num % hc.network_evolution_interval == 0:
            self._create_tracked_task(
                session_id,
                self._process_network_evolution(session_id, round_num),
            )
        # Phase 2: virality scoring
        if round_num > 0 and round_num % hc.virality_interval == 0:
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
            )

        # Clean up posts buffer for completed round to prevent memory growth
        session_buf = self._posts_buffer.get(session_id)
        if session_buf is not None:
            session_buf.pop(round_num, None)

    async def stop(self, session_id: str) -> None:
        """Stop a running simulation subprocess (SIGTERM → SIGKILL).

        Args:
            session_id: UUID of the session to stop.

        Raises:
            ValueError: If the session is not currently running.
        """
        process = self._processes.get(session_id)
        if process is None:
            raise ValueError(f"No running process for session {session_id}")

        logger.info("Stopping session %s (PID %d)", session_id, process.pid)
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning(
                "Process %d did not terminate — sending SIGKILL", process.pid
            )
            process.kill()
            await process.wait()

        self._processes.pop(session_id, None)
        logger.info("Session %s stopped", session_id)

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
        mock_rounds = min(round_count, 3)

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
            await self._action_logger.log_post(
                session_id=session_id,
                round_number=round_number,
                oasis_username=username,
                content=content,
                platform=platform,
                post_id=post_id,
            )
            # Enrich WS broadcast data with sentiment + timestamp
            sentiment = self._action_logger._detect_sentiment(content) if self._action_logger else "neutral"
            data["sentiment"] = sentiment
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
        if self._faction_mapper is None:
            from backend.app.services.emergence_tracker import FactionMapper  # noqa: PLC0415
            self._faction_mapper = FactionMapper()
        if self._tipping_detector is None:
            from backend.app.services.emergence_tracker import TippingPointDetector  # noqa: PLC0415
            self._tipping_detector = TippingPointDetector()

        # Initialise per-session state
        self._current_round_events[session_id] = []
        self._event_content_history[session_id] = []
        self._tier1_agents[session_id] = []
        self._active_metrics[session_id] = {}
        self._agent_beliefs[session_id] = {}
        self._belief_history[session_id] = []
        self._interaction_graph[session_id] = {}
        self._prev_dominant_stance[session_id] = {}
        self._scenario_description[session_id] = ""

        # Load scenario description + active metrics from DB (if available)
        await self._load_kg_session_context(session_id, config)

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
                    self._scenario_description[session_id] = row["seed_text"][:500]

                # Load tier-1 agents (those with importance >= 0.7 or first 30)
                cursor = await db.execute(
                    """SELECT id, oasis_username AS name,
                              json_extract(properties, '$.role') AS role,
                              json_extract(properties, '$.faction') AS faction
                       FROM agent_profiles
                       WHERE session_id = ?
                       ORDER BY CAST(json_extract(properties, '$.importance') AS REAL) DESC
                       LIMIT 30""",
                    (session_id,),
                )
                rows = await cursor.fetchall()
                tier1 = []
                for r in rows:
                    tier1.append({
                        "id": r["id"],
                        "name": r["name"] or "",
                        "role": r["role"] or "",
                        "faction": r["faction"] or "none",
                    })
                self._tier1_agents[session_id] = tier1

        except Exception:
            logger.warning(
                "Could not load kg_driven context for session %s",
                session_id,
                exc_info=True,
            )

    async def _kg_generate_world_events(
        self, session_id: str, round_num: int
    ) -> None:
        """Pre-round: generate world events for kg_driven mode."""
        if self._world_event_gen is None:
            return
        try:
            events = await self._world_event_gen.generate(
                scenario_description=self._scenario_description.get(session_id, ""),
                round_number=round_num,
                active_metrics=tuple(self._active_metrics.get(session_id, {}).keys()),
                prev_dominant_stance=self._prev_dominant_stance.get(session_id, {}),
                event_history=self._event_content_history.get(session_id, []),
            )
            self._current_round_events[session_id] = events
            hist = self._event_content_history.get(session_id, [])
            hist.extend(e.content for e in events)
            self._event_content_history[session_id] = hist
        except Exception:
            logger.exception(
                "kg_driven world event generation failed session=%s round=%d",
                session_id, round_num,
            )
            self._current_round_events[session_id] = []

    async def _kg_tier1_deliberation(
        self, session_id: str, round_num: int
    ) -> None:
        """Group 2: Tier 1 cognitive deliberation for kg_driven mode."""
        if self._cognitive_engine is None:
            return
        tier1 = self._tier1_agents.get(session_id, [])
        if not tier1:
            return
        current_events = self._current_round_events.get(session_id, [])
        metrics = self._active_metrics.get(session_id, {})
        scenario = self._scenario_description.get(session_id, "")

        for agent in tier1:
            try:
                agent_context = {
                    "agent_id": agent.get("id", ""),
                    "name": agent.get("name", ""),
                    "role": agent.get("role", ""),
                    "current_beliefs": metrics,
                    "recent_events": [e.content for e in current_events],
                    "faction": agent.get("faction", "none"),
                }
                result = await self._cognitive_engine.deliberate(
                    agent_context=agent_context,
                    scenario_description=scenario,
                    active_metrics=tuple(metrics.keys()),
                )
                # Apply belief updates
                for metric_id, delta in result.belief_updates.items():
                    if metric_id in metrics:
                        metrics[metric_id] = max(0.0, min(1.0, metrics[metric_id] + delta))
            except Exception:
                logger.debug(
                    "Tier 1 deliberation failed for agent %s session=%s",
                    agent.get("id", "?"), session_id,
                )
        self._active_metrics[session_id] = metrics

    async def _kg_faction_and_tipping(
        self, session_id: str, round_num: int
    ) -> None:
        """Group 3 periodic: faction mapping + tipping point detection."""
        agent_beliefs = self._agent_beliefs.get(session_id, {})
        if not agent_beliefs:
            return

        # Faction mapping
        if self._faction_mapper is not None:
            try:
                snapshot = self._faction_mapper.compute(
                    simulation_id=session_id,
                    round_number=round_num,
                    agent_beliefs=agent_beliefs,
                    interaction_graph=self._interaction_graph.get(session_id, {}),
                )
                await self._persist_faction_snapshot(snapshot)
            except Exception:
                logger.exception(
                    "Faction mapping failed session=%s round=%d",
                    session_id, round_num,
                )

        # Tipping point detection
        if self._tipping_detector is not None:
            try:
                current_events = self._current_round_events.get(session_id, [])
                tipping = self._tipping_detector.detect(
                    simulation_id=session_id,
                    round_number=round_num,
                    current_beliefs=agent_beliefs,
                    belief_history=self._belief_history.get(session_id, [])[-3:],
                    last_event_id=(
                        current_events[-1].event_id
                        if current_events
                        else None
                    ),
                )
                if tipping is not None:
                    await self._persist_tipping_point(tipping)
            except Exception:
                logger.exception(
                    "Tipping point detection failed session=%s round=%d",
                    session_id, round_num,
                )

        # Snapshot beliefs for history
        belief_copy = {k: dict(v) for k, v in agent_beliefs.items()}
        hist = self._belief_history.get(session_id, [])
        hist.append(belief_copy)
        self._belief_history[session_id] = hist

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


def _check_exit_code(
    session_id: str, process: asyncio.subprocess.Process
) -> None:
    """Raise RuntimeError if the process exited with a non-zero code."""
    exit_code = process.returncode
    if exit_code != 0:
        raise RuntimeError(
            f"OASIS subprocess for session {session_id} exited with code {exit_code}"
        )
