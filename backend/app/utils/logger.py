"""Centralised logging configuration for HKSimEngine."""

from __future__ import annotations

import logging
import sys


def setup_logging(*, level: int = logging.INFO) -> logging.Logger:
    """Configure and return the application root logger.

    Args:
        level: Logging level (default INFO).

    Returns:
        The configured root logger for the application.
    """
    logger = logging.getLogger("hksimengine")

    if logger.handlers:
        return logger

    logger.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the application namespace.

    Args:
        name: Logger name (will be prefixed with 'hksimengine.').

    Returns:
        A child logger instance.
    """
    return logging.getLogger(f"hksimengine.{name}")
