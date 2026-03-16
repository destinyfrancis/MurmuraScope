"""Tests for DataConnector and its file-ingestion pipeline."""
from __future__ import annotations

import json
import os
from unittest.mock import patch

import aiosqlite
import pytest

from backend.app.services.data_connector import DataConnector, IngestResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CSV = b"date,price,volume\n2025-01,100,50\n2025-02,110,55\n2025-03,105,48"

_JSON = json.dumps(
    [
        {"date": "2025-01", "rate": 5.0},
        {"date": "2025-02", "rate": 5.25},
    ]
).encode()


# ---------------------------------------------------------------------------
# Basic ingestion — no DB required
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_csv():
    connector = DataConnector()
    result = await connector.ingest_file(
        file_content=_CSV,
        filename="test.csv",
        session_id="sess_001",
    )
    assert result.row_count == 3
    assert len(result.detected_fields) == 3


@pytest.mark.asyncio
async def test_ingest_csv_detects_types():
    connector = DataConnector()
    result = await connector.ingest_file(
        file_content=_CSV,
        filename="test.csv",
        session_id="sess_001",
    )
    field_map = {f.source_field: f.detected_type for f in result.detected_fields}
    assert field_map["price"] == "numeric"
    assert field_map["volume"] == "numeric"
    assert field_map["date"] == "date"


@pytest.mark.asyncio
async def test_ingest_json():
    connector = DataConnector()
    result = await connector.ingest_file(
        file_content=_JSON,
        filename="rates.json",
        session_id="sess_002",
    )
    assert result.row_count == 2
    assert len(result.detected_fields) == 2


@pytest.mark.asyncio
async def test_unsupported_extension_raises():
    connector = DataConnector()
    with pytest.raises(ValueError, match="Unsupported"):
        await connector.ingest_file(
            file_content=b"data",
            filename="data.parquet",
            session_id="sess_003",
        )


@pytest.mark.asyncio
async def test_no_mappings_returns_zero_mapped():
    connector = DataConnector()
    result = await connector.ingest_file(
        file_content=_CSV,
        filename="test.csv",
        session_id="sess_001",
    )
    assert result.mapped_count == 0


@pytest.mark.asyncio
async def test_ingest_result_is_frozen():
    result = IngestResult(row_count=3, detected_fields=[], mapped_count=0)
    with pytest.raises((AttributeError, TypeError)):
        result.row_count = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Mapping + DB persistence
# ---------------------------------------------------------------------------


async def _make_test_db(tmp_path) -> str:
    """Create a temp SQLite DB with user_data_points table, return its path."""
    db_path = str(tmp_path / "test_connector.db")
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "CREATE TABLE user_data_points ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  session_id TEXT NOT NULL,"
            "  metric TEXT NOT NULL,"
            "  value REAL NOT NULL,"
            "  timestamp TEXT NOT NULL,"
            "  source_type TEXT NOT NULL DEFAULT 'user_file',"
            "  created_at TEXT DEFAULT (datetime('now'))"
            ")"
        )
        await db.commit()
    return db_path


def _patched_settings(db_path: str):
    """Return a fresh Settings instance pointing at *db_path*."""
    import backend.app.config as config_mod
    return patch.object(
        config_mod,
        "_settings",
        config_mod.Settings(DATABASE_PATH=db_path),
    )


@pytest.mark.asyncio
async def test_ingest_with_mappings_stores_rows(tmp_path):
    db_path = await _make_test_db(tmp_path)
    with _patched_settings(db_path):
        connector = DataConnector()
        result = await connector.ingest_file(
            file_content=_CSV,
            filename="test.csv",
            session_id="sess_map_01",
            field_mappings=[{"source_field": "price", "target_metric": "hsi_level"}],
        )

    assert result.mapped_count == 3

    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM user_data_points WHERE session_id='sess_map_01'"
        ) as cur:
            row = await cur.fetchone()
    assert row[0] == 3


@pytest.mark.asyncio
async def test_ingest_with_missing_source_field_is_skipped(tmp_path):
    db_path = await _make_test_db(tmp_path)
    with _patched_settings(db_path):
        connector = DataConnector()
        result = await connector.ingest_file(
            file_content=_CSV,
            filename="test.csv",
            session_id="sess_skip_01",
            field_mappings=[{"source_field": "nonexistent_col", "target_metric": "gdp"}],
        )

    assert result.mapped_count == 0


@pytest.mark.asyncio
async def test_ingest_multiple_mappings(tmp_path):
    db_path = await _make_test_db(tmp_path)
    with _patched_settings(db_path):
        connector = DataConnector()
        result = await connector.ingest_file(
            file_content=_CSV,
            filename="test.csv",
            session_id="sess_multi_01",
            field_mappings=[
                {"source_field": "price", "target_metric": "price_index"},
                {"source_field": "volume", "target_metric": "trade_volume"},
            ],
        )

    # 3 rows × 2 mappings = 6 rows stored
    assert result.mapped_count == 6

    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM user_data_points WHERE session_id='sess_multi_01'"
        ) as cur:
            row = await cur.fetchone()
    assert row[0] == 6
