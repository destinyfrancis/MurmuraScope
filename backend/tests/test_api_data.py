"""Integration tests for /data/dashboard endpoint.

These tests verify that the dashboard endpoint queries the hk_data_snapshots
table instead of returning hardcoded mock values.
"""

from __future__ import annotations

import os

import aiosqlite
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Shared fixture: client + writable DB connection pointing at the same file
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def client_with_db(tmp_path):
    """Yield (AsyncClient, aiosqlite.Connection) sharing the same DB file.

    The test_client fixture in conftest.py wires DATABASE_PATH to a temp file
    but does not expose the connection.  This fixture replicates that wiring
    and additionally yields the raw connection so tests can seed data.
    """
    test_db_file = str(tmp_path / "test_api_data.db")
    schema_path = os.path.join(os.path.dirname(__file__), "..", "database", "schema.sql")

    # Pre-initialise schema
    async with aiosqlite.connect(test_db_file) as init_db:
        with open(schema_path, encoding="utf-8") as f:
            await init_db.executescript(f.read())
        await init_db.commit()

    with __import__("unittest.mock", fromlist=["patch"]).patch.dict(
        os.environ, {"DATABASE_PATH": test_db_file, "DEBUG": "false"}
    ):
        import backend.app.config as config_mod

        fresh_settings = config_mod.Settings()
        with __import__("unittest.mock", fromlist=["patch"]).patch.object(config_mod, "_settings", fresh_settings):
            from backend.app import create_app

            app = create_app()
            transport = ASGITransport(app=app)

            # Open a persistent connection the test can use to seed data
            seed_db = await aiosqlite.connect(test_db_file)
            seed_db.row_factory = aiosqlite.Row

            async with AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as client:
                yield client, seed_db

            await seed_db.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dashboard_returns_db_values(client_with_db):
    """Dashboard must query DB, not return hardcoded values."""
    client, db = client_with_db

    await db.execute(
        "INSERT INTO hk_data_snapshots (category, metric, value, unit, period, source) VALUES (?, ?, ?, ?, ?, ?)",
        ("economy", "gdp_growth", 3.1, "%", "2026-03-15", "test"),
    )
    await db.execute(
        "INSERT INTO hk_data_snapshots (category, metric, value, unit, period, source) VALUES (?, ?, ?, ?, ?, ?)",
        ("employment", "unemployment_rate", 2.8, "%", "2026-03-15", "test"),
    )
    await db.commit()

    resp = await client.get("/api/data/dashboard")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    # Must reflect DB rows, not hardcoded 2.5 / 3.0
    assert data["economy"]["gdp_growth"] == 3.1
    assert data["employment"]["unemployment_rate"] == 2.8


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dashboard_empty_db_returns_zeros(client_with_db):
    """No data in DB → structured response with 0.0 values, not 500."""
    client, _db = client_with_db

    resp = await client.get("/api/data/dashboard")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    # All metrics should default to 0.0 when there are no DB rows
    assert isinstance(data, dict)
    for category in ("economy", "employment", "property_market"):
        assert category in data
        for _metric, value in data[category].items():
            assert value == 0.0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dashboard_latest_update_reflects_newest_period(client_with_db):
    """latest_update must be the newest period string from hk_data_snapshots."""
    client, db = client_with_db

    await db.execute(
        "INSERT INTO hk_data_snapshots (category, metric, value, unit, period, source) VALUES (?, ?, ?, ?, ?, ?)",
        ("economy", "gdp_growth", 1.0, "%", "2026-01-01", "test"),
    )
    await db.execute(
        "INSERT INTO hk_data_snapshots (category, metric, value, unit, period, source) VALUES (?, ?, ?, ?, ?, ?)",
        ("economy", "inflation_rate", 2.0, "%", "2026-03-01", "test"),
    )
    await db.commit()

    resp = await client.get("/api/data/dashboard")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["latest_update"] == "2026-03-01"


# ---------------------------------------------------------------------------
# Snapshot endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_snapshots_returns_db_rows(client_with_db):
    """Snapshots endpoint must return real DB rows, most-recent first."""
    test_client, test_db = client_with_db
    for date, val in [("2026-03-01", 152.3), ("2026-02-01", 153.1), ("2026-01-01", 154.0)]:
        await test_db.execute(
            "INSERT INTO hk_data_snapshots (category, metric, value, unit, period, source) VALUES (?, ?, ?, ?, ?, ?)",
            ("property_market", "ccl_index", val, "points", date, "test"),
        )
    await test_db.commit()

    resp = await test_client.get("/api/data/snapshots?metric=ccl_index&limit=2")
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["count"] == 2
    assert body["data"][0]["value"] == 152.3  # most recent first


@pytest.mark.integration
@pytest.mark.asyncio
async def test_snapshots_invalid_metric_returns_400(client_with_db):
    """Unknown metric values must be rejected with HTTP 400."""
    test_client, _ = client_with_db
    resp = await test_client.get("/api/data/snapshots?metric=DROP_TABLE")
    assert resp.status_code == 400
