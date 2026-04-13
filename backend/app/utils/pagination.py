"""Pagination utilities for list endpoints.

Provides a standardised ``clamp_limit`` guard to prevent unbounded DB reads
when user-supplied ``limit`` parameters are too large.
"""

from __future__ import annotations


def clamp_limit(limit: int, max_limit: int = 100) -> int:
    """Clamp a user-supplied limit to [1, max_limit].

    Args:
        limit: The raw value from the query parameter.
        max_limit: Upper bound (default 100).

    Returns:
        An integer in the range [1, max_limit].

    Examples::

        clamp_limit(99999)        # → 100
        clamp_limit(50)           # → 50
        clamp_limit(0)            # → 1
        clamp_limit(500, max_limit=200)  # → 200
    """
    return max(1, min(limit, max_limit))
