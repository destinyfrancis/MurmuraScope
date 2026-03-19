"""Unit tests for auth rate limiter configuration."""

from __future__ import annotations

import pytest


@pytest.mark.unit
def test_rate_limiter_is_configured():
    """Auth router routes exist and limiter is importable."""
    from backend.app.api.auth import _limiter, router

    login_route = next(
        (r for r in router.routes if hasattr(r, "path") and r.path == "/auth/login"),
        None,
    )
    assert login_route is not None, "Login route must exist"
    assert _limiter is not None, "Rate limiter must be configured"


@pytest.mark.unit
def test_register_route_exists():
    """Register route is present on auth router."""
    from backend.app.api.auth import router

    register_route = next(
        (r for r in router.routes if hasattr(r, "path") and r.path == "/auth/register"),
        None,
    )
    assert register_route is not None, "Register route must exist"


@pytest.mark.unit
def test_limiter_uses_remote_address():
    """Rate limiter key function is remote-address based."""
    from slowapi.util import get_remote_address

    from backend.app.api.auth import _limiter

    assert _limiter._key_func is get_remote_address
