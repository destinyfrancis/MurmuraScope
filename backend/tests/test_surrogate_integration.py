"""Unit tests for surrogate_integration module."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.app.services.surrogate_integration import auto_train_surrogate
from backend.app.services.surrogate_model import SurrogateModelResult


@pytest.mark.asyncio
async def test_returns_fitted_when_sufficient_data():
    """auto_train_surrogate returns fitted result when training succeeds."""
    fitted = SurrogateModelResult(
        is_fitted=True,
        n_classes=3,
        classes=["a", "b", "c"],
        train_accuracy=0.85,
        metrics_used=["x", "y"],
    )
    mock_model = AsyncMock(return_value=fitted)

    with patch("backend.app.services.surrogate_integration.SurrogateModel") as MockClass:
        MockClass.return_value.train_from_session = mock_model
        result = await auto_train_surrogate("sess1", metrics=["x", "y"])

    assert result.is_fitted is True
    assert result.n_classes == 3
    assert result.train_accuracy == 0.85


@pytest.mark.asyncio
async def test_returns_unfitted_on_empty_data():
    """auto_train_surrogate returns unfitted when no training data."""
    unfitted = SurrogateModelResult(
        is_fitted=False,
        n_classes=0,
        classes=[],
        train_accuracy=0.0,
        metrics_used=["x"],
    )
    mock_model = AsyncMock(return_value=unfitted)

    with patch("backend.app.services.surrogate_integration.SurrogateModel") as MockClass:
        MockClass.return_value.train_from_session = mock_model
        result = await auto_train_surrogate("sess1", metrics=["x"])

    assert result.is_fitted is False


@pytest.mark.asyncio
async def test_returns_unfitted_on_timeout():
    """auto_train_surrogate returns unfitted if training exceeds timeout."""
    import asyncio

    async def slow_train(*_args, **_kwargs):
        await asyncio.sleep(10)
        return SurrogateModelResult(
            is_fitted=True,
            n_classes=2,
            classes=["a", "b"],
            train_accuracy=0.9,
            metrics_used=[],
        )

    with patch("backend.app.services.surrogate_integration.SurrogateModel") as MockClass:
        MockClass.return_value.train_from_session = slow_train
        result = await auto_train_surrogate("sess1", timeout_s=0.01)

    assert result.is_fitted is False


@pytest.mark.asyncio
async def test_returns_unfitted_on_exception():
    """auto_train_surrogate returns unfitted on unexpected errors."""

    async def exploding_train(*_args, **_kwargs):
        raise RuntimeError("sklearn not found")

    with patch("backend.app.services.surrogate_integration.SurrogateModel") as MockClass:
        MockClass.return_value.train_from_session = exploding_train
        result = await auto_train_surrogate("sess1")

    assert result.is_fitted is False


@pytest.mark.asyncio
async def test_metrics_none_passes_through():
    """auto_train_surrogate passes metrics=None to SurrogateModel."""
    unfitted = SurrogateModelResult(
        is_fitted=False,
        n_classes=0,
        classes=[],
        train_accuracy=0.0,
        metrics_used=[],
    )
    mock_model = AsyncMock(return_value=unfitted)

    with patch("backend.app.services.surrogate_integration.SurrogateModel") as MockClass:
        MockClass.return_value.train_from_session = mock_model
        await auto_train_surrogate("sess1", metrics=None)

    mock_model.assert_called_once_with("sess1", metrics=None)
