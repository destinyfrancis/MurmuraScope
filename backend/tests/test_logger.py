"""Tests for backend/app/utils/logger.py — setup_logging + get_logger."""
from __future__ import annotations

import logging
import os

from unittest.mock import patch


def test_setup_logging_creates_file_handler(tmp_path):
    """setup_logging() with LOG_FILE should add a RotatingFileHandler."""
    log_path = tmp_path / "app.log"
    import backend.app.utils.logger as lg

    # Force re-init by using a unique logger name
    root = logging.getLogger("hksimengine_test")
    root.handlers.clear()
    with patch.dict(os.environ, {"LOG_FILE": str(log_path), "LOG_LEVEL": "DEBUG"}):
        result = lg.setup_logging(logger_name="hksimengine_test")
    file_handlers = [
        h for h in result.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert len(file_handlers) == 1
    assert result.level == logging.DEBUG


def test_setup_logging_default_level_info():
    """Default log level is INFO when LOG_LEVEL not set."""
    import backend.app.utils.logger as lg

    root = logging.getLogger("hksimengine_default")
    root.handlers.clear()
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("LOG_LEVEL", None)
        result = lg.setup_logging(logger_name="hksimengine_default")
    assert result.level == logging.INFO
