"""Surrogate model auto-training integration for Phase B ensemble.

Provides a single entry point that trains a SurrogateModel from Phase A
simulation data with timeout protection and graceful fallback.  Used by
the ``trigger_multi_run`` API to auto-wire data-driven outcome scoring
into MultiRunOrchestrator before Phase B trials begin.
"""
from __future__ import annotations

import asyncio

from backend.app.services.surrogate_model import SurrogateModel, SurrogateModelResult
from backend.app.utils.logger import get_logger

logger = get_logger("surrogate_integration")

_TRAIN_TIMEOUT_S: float = 5.0


async def auto_train_surrogate(
    session_id: str,
    metrics: list[str] | None = None,
    timeout_s: float = _TRAIN_TIMEOUT_S,
) -> SurrogateModelResult:
    """Train a SurrogateModel from Phase A data with timeout protection.

    Never raises — returns an unfitted result on any failure so callers
    can fall back to ad-hoc scoring transparently.

    Args:
        session_id: Completed Phase A simulation session ID.
        metrics: Metric names for feature vector.  If None, inferred
            from belief_snapshot keys in DB.
        timeout_s: Maximum seconds for training (default 5).

    Returns:
        SurrogateModelResult — check ``is_fitted`` before use.
    """
    unfitted = SurrogateModelResult(
        is_fitted=False, n_classes=0, classes=[],
        train_accuracy=0.0, metrics_used=metrics or [],
    )
    try:
        model = SurrogateModel()
        result = await asyncio.wait_for(
            model.train_from_session(session_id, metrics=metrics),
            timeout=timeout_s,
        )
        if result.is_fitted:
            logger.info(
                "Surrogate auto-trained session=%s classes=%d acc=%.3f",
                session_id, result.n_classes, result.train_accuracy,
            )
        else:
            logger.info(
                "Surrogate unfitted session=%s (insufficient data)",
                session_id,
            )
        return result
    except asyncio.TimeoutError:
        logger.warning(
            "Surrogate training timed out (%.1fs) session=%s", timeout_s, session_id
        )
        return unfitted
    except Exception:
        logger.exception("Surrogate training failed session=%s", session_id)
        return unfitted
