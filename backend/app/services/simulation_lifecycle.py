"""Simulation lifecycle methods: run, stop, cleanup, dry-run, action logs.

Mixin class extracted from SimulationRunner to keep file sizes manageable.
All methods access SimulationRunner state via ``self`` (cooperative MRO).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Coroutine

from backend.app.utils.logger import get_logger

logger = get_logger("simulation_runner")

# Paths computed relative to this file's location — portable across deployments.
# This file lives at: backend/app/services/simulation_lifecycle.py
# Project root is 4 levels up: services → app → backend → project_root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_VENV_PYTHON = _PROJECT_ROOT / ".venv311" / "bin" / "python"
_PYTHON_BIN = _VENV_PYTHON if _VENV_PYTHON.exists() else Path(sys.executable)
_SCRIPT_PATH = _PROJECT_ROOT / "backend" / "scripts" / "run_twitter_simulation.py"
_PARALLEL_SCRIPT = _PROJECT_ROOT / "backend" / "scripts" / "run_parallel_simulation.py"
_FACEBOOK_SCRIPT = _PROJECT_ROOT / "backend" / "scripts" / "run_facebook_simulation.py"
_INSTAGRAM_SCRIPT = _PROJECT_ROOT / "backend" / "scripts" / "run_instagram_simulation.py"

ProgressCallback = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


def _clear_ws_progress(session_id: str) -> None:
    """Clear WebSocket progress buffer for a completed/failed session."""
    try:
        from backend.app.api.ws import clear_progress  # noqa: PLC0415
        clear_progress(session_id)
    except Exception:
        pass  # WS module not loaded — no buffer to clear


class SimulationLifecycleMixin:
    """Simulation lifecycle: run, stop, cleanup, dry-run, and action-log retrieval."""

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
        from backend.app.services.simulation_helpers import (  # noqa: PLC0415
            _require_path, _build_full_config, _get_api_key, _try_parse_jsonl,
        )

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
                if session_id not in self._macro_locks:
                    self._macro_locks[session_id] = asyncio.Lock()
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
        self._macro_locks.pop(session_id, None)
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

        # External feed per-session cache
        try:
            from backend.app.services.simulation_hooks_macro import _external_feed_cache  # noqa: PLC0415
            _external_feed_cache.pop(session_id, None)
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
