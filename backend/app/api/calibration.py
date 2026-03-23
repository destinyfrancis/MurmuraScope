"""Calibration accuracy API."""

from __future__ import annotations

from fastapi import APIRouter

from backend.app.services.calibration_tracker import CalibrationTracker

router = APIRouter(prefix="/calibration", tags=["calibration"])


@router.get("/accuracy")
async def get_accuracy() -> dict:
    """Return calibration accuracy statistics."""
    tracker = CalibrationTracker()
    return await tracker.get_accuracy()


@router.get("/pending")
async def get_pending() -> dict:
    """Return pending (unverified) predictions."""
    tracker = CalibrationTracker()
    return await tracker.get_pending()
