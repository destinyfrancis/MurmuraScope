"""Tests for backend.app.utils.db connection manager."""

import pytest


@pytest.mark.integration
async def test_get_db_sets_busy_timeout(tmp_path, monkeypatch):
    """Confirm get_db() sets busy_timeout >= 5000ms."""
    db_file = str(tmp_path / "test.db")

    # Patch get_settings in the db module to return a settings-like object
    # pointing at a temp path so we don't touch the real DB.
    from unittest.mock import MagicMock

    mock_settings = MagicMock()
    mock_settings.DATABASE_PATH = db_file

    import backend.app.utils.db as db_module

    monkeypatch.setattr(db_module, "get_settings", lambda: mock_settings)

    from backend.app.utils.db import get_db

    async with get_db() as db:
        result = await db.execute("PRAGMA busy_timeout")
        row = await result.fetchone()
        timeout_ms = row[0]
        assert timeout_ms >= 5000, f"busy_timeout should be >=5000ms, got {timeout_ms}"
