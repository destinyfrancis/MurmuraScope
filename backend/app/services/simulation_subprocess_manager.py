"""Subprocess lifecycle management for HKSimEngine simulations.

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


class SimulationSubprocessManager:
    """Manages the lifecycle of OASIS simulation subprocesses.

    One instance is owned by SimulationRunner.  The manager holds no
    simulation business logic — it only tracks live processes and
    provides SIGTERM→SIGKILL escalation for clean shutdown.
    """

    def __init__(self) -> None:
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._report_pending: dict[str, bool] = {}

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
        self._processes.pop(session_id, None)

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
        asyncio.create_task(self._auto_release(session_id, timeout_s=1800))

    async def _auto_release(self, session_id: str, timeout_s: int) -> None:
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
