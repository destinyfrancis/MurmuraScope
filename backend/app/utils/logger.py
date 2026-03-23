"""Centralised logging configuration for Morai."""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path


def setup_logging(
    *,
    level: int | None = None,
    logger_name: str = "murmuroscope",
) -> logging.Logger:
    """Configure and return the application root logger.

    Reads LOG_LEVEL (DEBUG/INFO/WARNING/ERROR) and LOG_FILE (path) from env.
    Adds a RotatingFileHandler when LOG_FILE is set.
    """
    logger = logging.getLogger(logger_name)

    if logger.handlers:
        return logger

    # Resolve level: argument > env > default INFO
    if level is None:
        env_level = os.environ.get("LOG_LEVEL", "INFO").upper()
        level = getattr(logging, env_level, logging.INFO)

    logger.setLevel(level)

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Always log to stdout
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(level)
    stdout_handler.setFormatter(fmt)
    logger.addHandler(stdout_handler)

    # Optional rotating file handler
    log_file = os.environ.get("LOG_FILE")
    if log_file:
        file_path = Path(log_file)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            file_path,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the application namespace."""
    return logging.getLogger(f"murmuroscope.{name}")
