"""Tests for CalibrationTracker — prediction accuracy tracking."""
from __future__ import annotations

import os
import pytest
import pytest_asyncio
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Fixtures: patch DATABASE_PATH so CalibrationTracker writes to a temp file
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def tracker(tmp_path):
    """Yield a CalibrationTracker bound to a temporary database."""
    db_file = str(tmp_path / "calibration_test.db")
    with patch.dict(os.environ, {"DATABASE_PATH": db_file}):
        import backend.app.config as config_mod
        fresh = config_mod.Settings()
        with patch.object(config_mod, "_settings", fresh):
            from backend.app.services.calibration_tracker import CalibrationTracker
            t = CalibrationTracker()
            await t._ensure_schema()
            yield t


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_prediction(tracker):
    await tracker.record(
        session_id="sess_001",
        metric="property_index",
        predicted_direction="down",
        predicted_magnitude=-5.0,
        target_date="2026-09-14",
    )
    pending = await tracker.get_pending()
    assert len(pending) >= 1
    assert pending[0]["metric"] == "property_index"
    assert pending[0]["predicted_direction"] == "down"
    assert pending[0]["session_id"] == "sess_001"


@pytest.mark.asyncio
async def test_verify_prediction(tracker):
    await tracker.record(
        session_id="sess_001",
        metric="hsi",
        predicted_direction="up",
        predicted_magnitude=3.0,
        target_date="2026-06-01",
    )
    await tracker.verify(
        session_id="sess_001",
        metric="hsi",
        actual_direction="up",
        actual_value=28000,
    )
    stats = await tracker.get_accuracy()
    assert stats["total"] >= 1
    assert stats["hits"] >= 1
    assert stats["hit_rate"] > 0.0


@pytest.mark.asyncio
async def test_verify_miss(tracker):
    await tracker.record(
        session_id="sess_002",
        metric="ccl_index",
        predicted_direction="up",
        predicted_magnitude=2.0,
        target_date="2026-06-01",
    )
    await tracker.verify(
        session_id="sess_002",
        metric="ccl_index",
        actual_direction="down",
        actual_value=150.0,
    )
    stats = await tracker.get_accuracy()
    # hit should be 0 for this one
    assert stats["total"] >= 1
    assert stats["hit_rate"] == 0.0


@pytest.mark.asyncio
async def test_get_pending_empty(tracker):
    pending = await tracker.get_pending()
    assert pending == []


@pytest.mark.asyncio
async def test_multiple_predictions_accuracy(tracker):
    records = [
        ("sess_m", "hsi", "up", 5.0, "2026-06-01"),
        ("sess_m", "ccl_index", "down", -3.0, "2026-06-01"),
        ("sess_m", "unemployment_rate", "stable", 0.0, "2026-06-01"),
    ]
    for sid, metric, direction, mag, tdate in records:
        await tracker.record(sid, metric, direction, mag, tdate)

    # Verify: 2 correct, 1 wrong
    await tracker.verify("sess_m", "hsi", "up", 28000)
    await tracker.verify("sess_m", "ccl_index", "up", 155.0)  # wrong direction
    await tracker.verify("sess_m", "unemployment_rate", "stable", 3.2)

    stats = await tracker.get_accuracy()
    assert stats["total"] == 3
    assert stats["hits"] == 2
    assert stats["hit_rate"] == pytest.approx(0.6667, abs=1e-3)


@pytest.mark.asyncio
async def test_accuracy_zero_when_no_verifications(tracker):
    await tracker.record("sess_x", "hsi", "up", 1.0, "2026-12-01")
    stats = await tracker.get_accuracy()
    assert stats["total"] == 0
    assert stats["hit_rate"] == 0.0


@pytest.mark.asyncio
async def test_pending_cleared_after_verify(tracker):
    await tracker.record("sess_p", "gdp", "up", 2.0, "2026-12-01")
    pending_before = await tracker.get_pending()
    assert len(pending_before) == 1

    await tracker.verify("sess_p", "gdp", "up", 3.5)
    pending_after = await tracker.get_pending()
    assert len(pending_after) == 0


@pytest.mark.asyncio
async def test_accuracy_by_metric(tracker):
    await tracker.record("sess_bm", "hsi", "up", 3.0, "2026-06-01")
    await tracker.record("sess_bm", "hsi", "down", -1.0, "2026-09-01")
    await tracker.record("sess_bm", "ccl_index", "down", -2.0, "2026-06-01")

    await tracker.verify("sess_bm", "hsi", "up", 28000)
    await tracker.verify("sess_bm", "hsi", "up", 29000)   # second record: "down" vs "up" = miss
    await tracker.verify("sess_bm", "ccl_index", "down", 140.0)

    by_metric = await tracker.get_accuracy_by_metric()
    assert "hsi" in by_metric
    assert "ccl_index" in by_metric
    assert by_metric["ccl_index"]["hits"] == 1
    assert by_metric["ccl_index"]["hit_rate"] == 1.0
