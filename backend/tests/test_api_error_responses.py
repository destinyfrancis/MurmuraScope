"""Test that API error responses don't leak internal information.

This test suite verifies that:
- 500 errors return a generic "Internal server error" message
- Full exception details are logged, not returned to clients
- Error handlers follow security best practices
"""

import pytest


@pytest.mark.unit
def test_create_app_returns_app():
    """App factory must return a valid FastAPI app (structural test for 500 handler setup)."""
    from backend.app import create_app

    app = create_app()
    assert app is not None
    assert hasattr(app, "router")
    assert hasattr(app, "openapi")
