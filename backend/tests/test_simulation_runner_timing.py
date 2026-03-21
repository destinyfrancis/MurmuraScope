"""Tests for _timed_block context manager in simulation_runner."""
from __future__ import annotations

import logging
import time

from backend.app.services.simulation_runner import _timed_block


def test_timed_block_logs_duration(caplog):
    """_timed_block context manager should log execution time."""
    with caplog.at_level(logging.DEBUG, logger="murmuroscope.simulation_runner"):
        with _timed_block("test_hook", "session_abc", round_num=3):
            time.sleep(0.01)
    assert any(
        "test_hook" in r.message and "ms" in r.message for r in caplog.records
    ), "Expected timing log for test_hook"
