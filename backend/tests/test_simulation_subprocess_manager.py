"""Unit tests for SimulationSubprocessManager.

Tests use unittest.mock to avoid spawning real subprocesses.
All tests are pure-logic (no DB, no HTTP) and will be auto-classified
as *unit* tests by conftest.py.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.services.simulation_subprocess_manager import (
    SimulationSubprocessManager,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_process(returncode: int | None = None, pid: int = 12345):
    """Return a MagicMock that approximates asyncio.subprocess.Process."""
    proc = MagicMock()
    proc.pid = pid
    proc.returncode = returncode
    proc.stdout = AsyncMock()
    proc.wait = AsyncMock(return_value=returncode)
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    return proc


# ---------------------------------------------------------------------------
# launch()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_launch_stores_process_in_processes():
    """launch() should register the process under session_id."""
    mgr = SimulationSubprocessManager()
    mock_proc = _make_mock_process(returncode=None)

    with patch(
        "asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
        return_value=mock_proc,
    ):
        result = await mgr.launch(
            "sess-001",
            ["python", "script.py"],
            {"KEY": "val"},
            MagicMock(),  # log_file
            "/tmp",
        )

    assert result is mock_proc
    assert mgr.get_process("sess-001") is mock_proc


@pytest.mark.asyncio
async def test_launch_raises_if_session_already_running():
    """launch() should raise ValueError when the session is already tracked."""
    mgr = SimulationSubprocessManager()
    mock_proc = _make_mock_process(returncode=None)

    with patch(
        "asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
        return_value=mock_proc,
    ):
        await mgr.launch("sess-dup", ["python", "s.py"], {}, MagicMock(), "/tmp")

    with pytest.raises(ValueError, match="already running"):
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_proc,
        ):
            await mgr.launch("sess-dup", ["python", "s.py"], {}, MagicMock(), "/tmp")


# ---------------------------------------------------------------------------
# stop()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stop_sends_sigterm():
    """stop() should call terminate() on the process."""
    mgr = SimulationSubprocessManager()
    mock_proc = _make_mock_process(returncode=None)
    # simulate graceful exit after terminate
    mock_proc.wait = AsyncMock(return_value=0)

    with patch(
        "asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
        return_value=mock_proc,
    ):
        await mgr.launch("sess-stop", ["python", "s.py"], {}, MagicMock(), "/tmp")

    await mgr.stop("sess-stop")

    mock_proc.terminate.assert_called_once()
    # process should be removed from internal dict after stop
    assert mgr.get_process("sess-stop") is None


@pytest.mark.asyncio
async def test_stop_escalates_to_sigkill_on_timeout():
    """stop() should send SIGKILL when SIGTERM times out."""
    mgr = SimulationSubprocessManager()
    mock_proc = _make_mock_process(returncode=None)

    call_count = 0

    async def _wait_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        # First wait_for (after terminate) → timeout; second wait (after kill) → ok
        if call_count == 1:
            raise asyncio.TimeoutError
        return 0

    # asyncio.wait_for wraps process.wait; patch it at the module level
    with patch(
        "asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
        return_value=mock_proc,
    ):
        await mgr.launch("sess-kill", ["python", "s.py"], {}, MagicMock(), "/tmp")

    with patch("asyncio.wait_for", side_effect=_wait_side_effect):
        await mgr.stop("sess-kill")

    mock_proc.terminate.assert_called_once()
    mock_proc.kill.assert_called_once()


@pytest.mark.asyncio
async def test_stop_raises_if_session_not_found():
    """stop() should raise ValueError when session is not tracked."""
    mgr = SimulationSubprocessManager()
    with pytest.raises(ValueError, match="No running process"):
        await mgr.stop("nonexistent-session")


# ---------------------------------------------------------------------------
# is_running()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_is_running_returns_true_for_live_process():
    """is_running() should return True when process.returncode is None."""
    mgr = SimulationSubprocessManager()
    mock_proc = _make_mock_process(returncode=None)

    with patch(
        "asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
        return_value=mock_proc,
    ):
        await mgr.launch("sess-live", ["python", "s.py"], {}, MagicMock(), "/tmp")

    assert mgr.is_running("sess-live") is True


@pytest.mark.asyncio
async def test_is_running_returns_false_after_exit():
    """is_running() should return False when process.returncode is set."""
    mgr = SimulationSubprocessManager()
    mock_proc = _make_mock_process(returncode=0)

    with patch(
        "asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
        return_value=mock_proc,
    ):
        await mgr.launch("sess-done", ["python", "s.py"], {}, MagicMock(), "/tmp")

    assert mgr.is_running("sess-done") is False


def test_is_running_returns_false_for_unknown_session():
    """is_running() should return False for a session that was never started."""
    mgr = SimulationSubprocessManager()
    assert mgr.is_running("ghost-session") is False


# ---------------------------------------------------------------------------
# cleanup()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cleanup_removes_session():
    """cleanup() should remove the session entry from internal dict."""
    mgr = SimulationSubprocessManager()
    mock_proc = _make_mock_process(returncode=0)

    with patch(
        "asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
        return_value=mock_proc,
    ):
        await mgr.launch("sess-clean", ["python", "s.py"], {}, MagicMock(), "/tmp")

    await mgr.cleanup("sess-clean")
    assert mgr.get_process("sess-clean") is None


@pytest.mark.asyncio
async def test_cleanup_is_safe_for_unknown_session():
    """cleanup() should not raise for sessions that were never started."""
    mgr = SimulationSubprocessManager()
    await mgr.cleanup("never-existed")  # must not raise


# ---------------------------------------------------------------------------
# check_exit_code()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_exit_code_raises_on_nonzero():
    """check_exit_code() should raise RuntimeError for non-zero exit codes."""
    mgr = SimulationSubprocessManager()
    mock_proc = _make_mock_process(returncode=1)

    with patch(
        "asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
        return_value=mock_proc,
    ):
        await mgr.launch("sess-fail", ["python", "s.py"], {}, MagicMock(), "/tmp")

    with pytest.raises(RuntimeError, match="exited with code 1"):
        mgr.check_exit_code("sess-fail")


@pytest.mark.asyncio
async def test_check_exit_code_passes_on_zero():
    """check_exit_code() should not raise for zero exit codes."""
    mgr = SimulationSubprocessManager()
    mock_proc = _make_mock_process(returncode=0)

    with patch(
        "asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
        return_value=mock_proc,
    ):
        await mgr.launch("sess-ok", ["python", "s.py"], {}, MagicMock(), "/tmp")

    mgr.check_exit_code("sess-ok")  # must not raise


def test_check_exit_code_silent_for_unknown_session():
    """check_exit_code() should not raise when session is not tracked."""
    mgr = SimulationSubprocessManager()
    mgr.check_exit_code("not-tracked")  # must not raise


# ---------------------------------------------------------------------------
# keep_alive_for_report() / release_after_report() / cleanup guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_keep_alive_sets_pending_flag():
    """keep_alive_for_report() should set _report_pending[session_id] = True."""
    mgr = SimulationSubprocessManager()
    await mgr.keep_alive_for_report("sess1")
    assert mgr._report_pending.get("sess1") is True


@pytest.mark.asyncio
async def test_release_after_report_clears_flag():
    """release_after_report() should remove session from _report_pending."""
    mgr = SimulationSubprocessManager()
    mgr._report_pending["sess1"] = True
    with patch.object(mgr, "stop", new_callable=AsyncMock), \
         patch.object(mgr, "cleanup", new_callable=AsyncMock):
        await mgr.release_after_report("sess1")
    assert "sess1" not in mgr._report_pending


@pytest.mark.asyncio
async def test_cleanup_skipped_when_report_pending():
    """cleanup() should return early (no-op) when report is pending for session."""
    mgr = SimulationSubprocessManager()
    mgr._report_pending["sess1"] = True
    # cleanup should return early, not touch _processes
    await mgr.cleanup("sess1")
    # sess1 still in _report_pending (not cleared by cleanup)
    assert mgr._report_pending.get("sess1") is True
