"""Tests for SimulationRunner and its task tracking mechanisms."""
from __future__ import annotations

import asyncio
import logging

import pytest

from backend.app.services.simulation_runner import SimulationRunner


@pytest.mark.unit
async def test_tracked_task_logs_at_error_level(caplog):
    """Exceptions in fire-and-forget tasks must be logged at ERROR level.

    _create_tracked_task signature: (self, session_id: str, coro: Any, timeout_s: float = 60.0)
    The 3rd arg is timeout_s (float), NOT a string name.
    """
    runner = SimulationRunner()

    async def failing_coro():
        raise ValueError("test failure in tracked task")

    # Capture both DEBUG and ERROR to see what level is actually logged
    with caplog.at_level(logging.DEBUG, logger="murmuroscope.simulation_runner"):
        runner._create_tracked_task("test-session", failing_coro())
        await asyncio.sleep(0.2)  # let the task run and fail

    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]

    if not error_records:
        pytest.fail(
            f"Task failure should be logged at ERROR, not DEBUG. "
            f"Got {len(debug_records)} DEBUG records: {[r.message for r in debug_records]}"
        )


@pytest.mark.unit
async def test_tracked_task_does_not_raise(caplog):
    """Fire-and-forget tasks should not raise—they should be logged and captured."""
    runner = SimulationRunner()

    async def failing_coro():
        raise ValueError("expected test failure")

    # Should not raise
    task = runner._create_tracked_task("test-session", failing_coro())
    await asyncio.sleep(0.2)
    assert task.done()


@pytest.mark.unit
async def test_tracked_task_handles_cancellation(caplog):
    """CancelledError should not be logged at ERROR level (it's expected on shutdown)."""
    runner = SimulationRunner()

    async def slow_coro():
        await asyncio.sleep(10)

    task = runner._create_tracked_task("test-session", slow_coro())
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.sleep(0.1)

    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(error_records) == 0, (
        "CancelledError should not be logged at ERROR level. "
        f"Got {len(error_records)} ERROR records"
    )
