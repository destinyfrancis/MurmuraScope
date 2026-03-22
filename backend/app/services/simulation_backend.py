"""Simulation backend abstraction layer.

Defines the ``SimulationBackend`` protocol — the interface that any simulation
execution engine must satisfy — together with ``OASISBackend``, the concrete
adapter that wraps :class:`SimulationSubprocessManager` to fulfil that
interface.

Existing code continues to use :class:`SimulationSubprocessManager` directly;
``OASISBackend`` is a parallel implementation that can be swapped in at a
later refactor without breaking anything.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from backend.app.utils.logger import get_logger

logger = get_logger("simulation_backend")


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class SimulationBackend(Protocol):
    """Protocol for simulation execution backends.

    Any class that implements these five methods — regardless of inheritance —
    satisfies the protocol and can be used wherever a ``SimulationBackend`` is
    expected.  ``@runtime_checkable`` enables ``isinstance(obj, SimulationBackend)``
    checks at runtime.
    """

    async def launch(self, session_id: str, config: dict[str, Any]) -> asyncio.subprocess.Process:
        """Start a new simulation subprocess for *session_id*.

        Args:
            session_id: Unique session identifier.
            config:     Simulation configuration dict (cmd, env, log_file, cwd, …).

        Returns:
            The newly created subprocess handle.
        """
        ...

    async def send_event(self, session_id: str, event: dict[str, Any]) -> None:
        """Send a runtime event (e.g. shock) to a running simulation.

        Args:
            session_id: UUID of the target session.
            event:      Event payload to deliver.
        """
        ...

    async def stop(self, session_id: str) -> None:
        """Gracefully stop the running simulation for *session_id*.

        Args:
            session_id: UUID of the session to stop.
        """
        ...

    async def cleanup(self, session_id: str) -> None:
        """Release all resources associated with *session_id*.

        Safe to call even if the session has already been stopped.

        Args:
            session_id: UUID of the session to clean up.
        """
        ...

    def is_running(self, session_id: str) -> bool:
        """Return ``True`` if a simulation is currently active for *session_id*.

        Args:
            session_id: UUID to query.
        """
        ...


# ---------------------------------------------------------------------------
# OASIS backend adapter
# ---------------------------------------------------------------------------


class OASISBackend:
    """Adapter that wraps :class:`SimulationSubprocessManager` as a
    ``SimulationBackend``.

    This class intentionally mirrors ``SimulationSubprocessManager`` behaviour
    rather than inheriting from it, keeping the two decoupled.  The
    ``launch()`` signature accepts a unified *config* dict so callers do not
    need to know about the underlying subprocess argument shape.

    Expected *config* keys for ``launch()``:
        ``cmd``      — ``list[str]`` — command + arguments.
        ``env``      — ``dict[str, str]`` — environment variables.
        ``log_file`` — writable binary file object for stderr capture.
        ``cwd``      — ``str | Path`` — working directory.

    Events delivered via ``send_event()`` are written as newline-delimited
    JSON to the subprocess stdin.  If the process has no stdin (or stdin is
    already closed), the call is a no-op and a warning is logged.
    """

    def __init__(self) -> None:
        from backend.app.services.simulation_subprocess_manager import (
            SimulationSubprocessManager,
        )

        self._mgr: SimulationSubprocessManager = SimulationSubprocessManager()

    # ------------------------------------------------------------------
    # SimulationBackend interface
    # ------------------------------------------------------------------

    async def launch(
        self, session_id: str, config: dict[str, Any]
    ) -> asyncio.subprocess.Process:
        """Start a new OASIS subprocess using *config*.

        Args:
            session_id: Unique session identifier.
            config:     Must contain ``cmd``, ``env``, ``log_file``, ``cwd``.

        Returns:
            The newly created ``asyncio.subprocess.Process``.

        Raises:
            KeyError:   If any required config key is missing.
            ValueError: If *session_id* already has a running process.
        """
        cmd: list[str] = config["cmd"]
        env: dict[str, str] = config["env"]
        log_file: Any = config["log_file"]
        cwd: str | Path = config["cwd"]

        process = await self._mgr.launch(
            session_id=session_id,
            cmd=cmd,
            env=env,
            log_file=log_file,
            cwd=cwd,
        )
        logger.info(
            "OASISBackend: launched session %s PID %d", session_id, process.pid
        )
        return process

    async def send_event(self, session_id: str, event: dict[str, Any]) -> None:
        """Write *event* as newline-delimited JSON to the subprocess stdin.

        If the subprocess does not have an open stdin, the call is a no-op
        and a WARNING is emitted.

        Args:
            session_id: UUID of the target session.
            event:      Arbitrary JSON-serialisable dict.
        """
        import json

        process = self._mgr.get_process(session_id)
        if process is None:
            logger.warning(
                "OASISBackend.send_event: no process for session %s", session_id
            )
            return

        if process.stdin is None or process.stdin.is_closing():
            logger.warning(
                "OASISBackend.send_event: stdin unavailable for session %s", session_id
            )
            return

        try:
            payload = json.dumps(event, ensure_ascii=False) + "\n"
            process.stdin.write(payload.encode())
            await process.stdin.drain()
            logger.debug(
                "OASISBackend.send_event: delivered event type=%s to session %s",
                event.get("type", "unknown"),
                session_id,
            )
        except (BrokenPipeError, ConnectionResetError) as exc:
            logger.warning(
                "OASISBackend.send_event: pipe broken for session %s — %s",
                session_id,
                exc,
            )
        except Exception:
            logger.exception(
                "OASISBackend.send_event: unexpected error for session %s", session_id
            )

    async def stop(self, session_id: str) -> None:
        """Gracefully stop the OASIS subprocess (SIGTERM → SIGKILL).

        Delegates to :meth:`SimulationSubprocessManager.stop`.

        Args:
            session_id: UUID of the session to stop.
        """
        try:
            await self._mgr.stop(session_id)
            logger.info("OASISBackend: session %s stopped", session_id)
        except ValueError:
            logger.debug(
                "OASISBackend.stop: session %s was not running", session_id
            )

    async def cleanup(self, session_id: str) -> None:
        """Release all resources for *session_id*.

        Delegates to :meth:`SimulationSubprocessManager.cleanup`.

        Args:
            session_id: UUID of the session to clean up.
        """
        await self._mgr.cleanup(session_id)
        logger.debug("OASISBackend: session %s cleaned up", session_id)

    def is_running(self, session_id: str) -> bool:
        """Return ``True`` if the OASIS subprocess for *session_id* is live.

        Args:
            session_id: UUID to query.
        """
        return self._mgr.is_running(session_id)

    # ------------------------------------------------------------------
    # Pass-through helpers (not part of the protocol, but useful)
    # ------------------------------------------------------------------

    async def keep_alive_for_report(self, session_id: str) -> None:
        """Forward to :meth:`SimulationSubprocessManager.keep_alive_for_report`.

        Args:
            session_id: UUID of the session to keep alive.
        """
        await self._mgr.keep_alive_for_report(session_id)

    async def release_after_report(self, session_id: str) -> None:
        """Forward to :meth:`SimulationSubprocessManager.release_after_report`.

        Args:
            session_id: UUID of the session to release.
        """
        await self._mgr.release_after_report(session_id)

    def check_exit_code(self, session_id: str) -> None:
        """Forward to :meth:`SimulationSubprocessManager.check_exit_code`.

        Args:
            session_id: UUID of the finished session.

        Raises:
            RuntimeError: If the subprocess exited with a non-zero code.
        """
        self._mgr.check_exit_code(session_id)
