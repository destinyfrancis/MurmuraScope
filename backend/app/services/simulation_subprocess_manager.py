"""Subprocess lifecycle management for MurmuraScope simulations.

Owns the mapping of session_id → asyncio subprocess, and provides a clean
interface for launching, monitoring, and terminating OASIS simulation
subprocesses.  All hook logic and session-level state remain in
SimulationRunner; this class is deliberately narrow.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from backend.app.utils.logger import get_logger

logger = get_logger("simulation_subprocess_manager")

# Memory limit for OASIS subprocesses in megabytes.
# Subprocess is killed after exceeding this threshold for 2 consecutive checks.
_MEMORY_LIMIT_MB: int = int(os.environ.get("SUBPROCESS_MEMORY_LIMIT_MB", "2048"))
_HEALTH_CHECK_INTERVAL_S: float = 30.0
# Number of consecutive over-limit checks before killing the process.
_MEMORY_STRIKE_LIMIT: int = 2


class SimulationSubprocessManager:
    """Manages the lifecycle of OASIS simulation subprocesses.

    One instance is owned by SimulationRunner.  The manager holds no
    simulation business logic — it only tracks live processes and
    provides SIGTERM→SIGKILL escalation for clean shutdown.
    """

    def __init__(self) -> None:
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._report_pending: dict[str, bool] = {}
        self._auto_release_tasks: dict[str, asyncio.Task] = {}
        self._health_monitors: dict[str, asyncio.Task] = {}
        self._memory_warnings: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Launch
    # ------------------------------------------------------------------

    async def launch(
        self,
        session_id: str,
        cmd: list[str],
        env: dict[str, str],
        log_file: Any,
        cwd: str | Path,
    ) -> asyncio.subprocess.Process:
        """Spawn a subprocess and register it under *session_id*.

        Args:
            session_id: Unique session identifier.
            cmd:        Command + arguments list (e.g. [python_bin, script, ...]).
            env:        Full environment dict for the child process.
            log_file:   Writable binary file object for stderr capture.
            cwd:        Working directory for the subprocess.

        Returns:
            The newly created ``asyncio.subprocess.Process``.

        Raises:
            ValueError: If *session_id* already has a running process.
        """
        if session_id in self._processes:
            raise ValueError(f"Session {session_id} is already running")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=log_file,
            cwd=str(cwd),
            env=env,
        )
        self._processes[session_id] = process
        self._start_health_monitor(session_id)
        return process

    # ------------------------------------------------------------------
    # Stop
    # ------------------------------------------------------------------

    async def stop(self, session_id: str) -> None:
        """Gracefully stop a running subprocess (SIGTERM → SIGKILL).

        Args:
            session_id: UUID of the session to stop.

        Raises:
            ValueError: If the session is not currently tracked.
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
        self._stop_health_monitor(session_id)
        logger.info("Session %s stopped", session_id)

    # ------------------------------------------------------------------
    # Wait
    # ------------------------------------------------------------------

    async def wait(self, session_id: str) -> int | None:
        """Wait for the process to exit and return its exit code.

        Args:
            session_id: UUID of the session to wait for.

        Returns:
            Exit code of the process, or ``None`` if session not tracked.
        """
        process = self._processes.get(session_id)
        if process is None:
            return None
        await process.wait()
        return process.returncode

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def cleanup(self, session_id: str) -> None:
        """Remove a session from the tracked processes dict.

        Safe to call even if the session is not present.  If a report
        generation is pending for *session_id*, cleanup is deferred until
        :meth:`release_after_report` is called.

        Args:
            session_id: UUID of the session to remove.
        """
        if self._report_pending.get(session_id):
            logger.debug("cleanup deferred: report pending for %s", session_id)
            return
        self._stop_health_monitor(session_id)
        self._processes.pop(session_id, None)

    # ------------------------------------------------------------------
    # Health monitoring
    # ------------------------------------------------------------------

    def _start_health_monitor(self, session_id: str) -> None:
        """Start an asyncio background task that monitors the subprocess health.

        Checks every :data:`_HEALTH_CHECK_INTERVAL_S` seconds that:
        - The process is still alive (``returncode is None``).
        - RSS memory usage is below ``SUBPROCESS_MEMORY_LIMIT_MB``.

        A process that exceeds the memory limit for :data:`_MEMORY_STRIKE_LIMIT`
        consecutive checks is killed via SIGTERM → SIGKILL.

        Args:
            session_id: UUID of the session to monitor.
        """
        if session_id in self._health_monitors:
            return  # Already monitoring

        task = asyncio.create_task(
            self._run_health_check(session_id),
            name=f"health_monitor_{session_id}",
        )
        self._health_monitors[session_id] = task

    def _stop_health_monitor(self, session_id: str) -> None:
        """Cancel the health monitoring task for *session_id*, if any.

        Args:
            session_id: UUID of the session to stop monitoring.
        """
        task = self._health_monitors.pop(session_id, None)
        if task is not None and not task.done():
            task.cancel()
        self._memory_warnings.pop(session_id, None)

    async def _run_health_check(self, session_id: str) -> None:
        """Coroutine body for the health monitor task.

        Runs until the process exits, is stopped externally, or is killed due
        to excessive memory usage.

        Args:
            session_id: UUID of the session being monitored.
        """
        try:
            import psutil  # imported lazily to avoid hard startup dependency
        except ImportError:
            logger.warning(
                "psutil not installed — subprocess memory monitoring disabled for session %s",
                session_id,
            )
            return

        try:
            while True:
                await asyncio.sleep(_HEALTH_CHECK_INTERVAL_S)

                process = self._processes.get(session_id)
                if process is None or process.returncode is not None:
                    # Process already finished or was cleaned up.
                    break

                # --- liveness check ---
                if not self.is_running(session_id):
                    logger.debug(
                        "Health monitor: session %s process has exited", session_id
                    )
                    break

                # --- memory check ---
                try:
                    ps_proc = psutil.Process(process.pid)
                    rss_mb = ps_proc.memory_info().rss / (1024 * 1024)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    logger.debug(
                        "Health monitor: psutil could not inspect PID %d (session %s)",
                        process.pid,
                        session_id,
                    )
                    break

                if rss_mb > _MEMORY_LIMIT_MB:
                    strikes = self._memory_warnings.get(session_id, 0) + 1
                    self._memory_warnings[session_id] = strikes
                    logger.warning(
                        "Health monitor: session %s PID %d using %.1f MB "
                        "(limit %d MB) — strike %d/%d",
                        session_id,
                        process.pid,
                        rss_mb,
                        _MEMORY_LIMIT_MB,
                        strikes,
                        _MEMORY_STRIKE_LIMIT,
                    )

                    if strikes >= _MEMORY_STRIKE_LIMIT:
                        logger.error(
                            "Health monitor: killing session %s PID %d — "
                            "exceeded memory limit (%.1f MB) for %d consecutive checks",
                            session_id,
                            process.pid,
                            rss_mb,
                            strikes,
                        )
                        process.terminate()
                        try:
                            await asyncio.wait_for(process.wait(), timeout=5.0)
                        except asyncio.TimeoutError:
                            logger.warning(
                                "Health monitor: SIGTERM timed out for PID %d, sending SIGKILL",
                                process.pid,
                            )
                            process.kill()
                            await process.wait()
                        self._processes.pop(session_id, None)
                        self._memory_warnings.pop(session_id, None)
                        break
                else:
                    # Reset strike counter on a healthy check.
                    self._memory_warnings.pop(session_id, None)

        except asyncio.CancelledError:
            # Normal cancellation via _stop_health_monitor.
            pass
        except Exception:
            logger.exception(
                "Health monitor unexpected error for session %s", session_id
            )

    # ------------------------------------------------------------------
    # Report keep-alive
    # ------------------------------------------------------------------

    async def keep_alive_for_report(self, session_id: str) -> None:
        """Mark subprocess as awaiting report generation. Prevents cleanup.

        Schedules a 30-minute auto-release to prevent subprocess leaks if
        :meth:`release_after_report` is never called.

        Args:
            session_id: UUID of the session to keep alive.
        """
        self._report_pending[session_id] = True
        logger.info("keep_alive_for_report: %s", session_id)
        task = asyncio.create_task(self._auto_release(session_id, timeout_s=1800))
        self._auto_release_tasks[session_id] = task

    async def _auto_release(self, session_id: str, timeout_s: float) -> None:
        """Auto-release a session after *timeout_s* seconds if still pending.

        Args:
            session_id: UUID of the session to auto-release.
            timeout_s:  Seconds to wait before forcing cleanup.
        """
        await asyncio.sleep(timeout_s)
        if self._report_pending.get(session_id):
            logger.warning(
                "auto_release: timeout expired for %s, cleaning up", session_id
            )
            await self.release_after_report(session_id)

    async def release_after_report(self, session_id: str) -> None:
        """Called when report generation is complete. Clears the pending flag
        and shuts down the subprocess if it is still running.

        Args:
            session_id: UUID of the session to release.
        """
        task = self._auto_release_tasks.pop(session_id, None)
        if task is not None and not task.done():
            task.cancel()
        self._report_pending.pop(session_id, None)
        if self.is_running(session_id):
            await self.stop(session_id)
            await self.cleanup(session_id)
        logger.info("release_after_report: %s cleaned up", session_id)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def is_running(self, session_id: str) -> bool:
        """Return True if a process for *session_id* is tracked and still live.

        A process is considered live when its ``returncode`` is ``None``
        (i.e. it has not yet exited).

        Args:
            session_id: UUID to check.
        """
        process = self._processes.get(session_id)
        return process is not None and process.returncode is None

    def get_process(self, session_id: str) -> asyncio.subprocess.Process | None:
        """Return the raw process object, or None if not tracked.

        Intended for the SimulationRunner finally-block orphan cleanup which
        needs direct access to ``process.pid`` and ``process.kill()``.

        Args:
            session_id: UUID to look up.
        """
        return self._processes.get(session_id)

    # ------------------------------------------------------------------
    # Exit code validation
    # ------------------------------------------------------------------

    def check_exit_code(self, session_id: str) -> None:
        """Raise RuntimeError if the tracked process exited with a non-zero code.

        Args:
            session_id: UUID of the finished session.

        Raises:
            RuntimeError: If the process exited with a non-zero return code.
        """
        process = self._processes.get(session_id)
        if process is None:
            return
        exit_code = process.returncode
        if exit_code is not None and exit_code != 0:
            raise RuntimeError(
                f"OASIS subprocess for session {session_id} exited with code {exit_code}"
            )
