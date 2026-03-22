"""Tests for API response models — immutability compliance."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.models.response import APIResponse


class TestAPIResponseFrozen:
    """M12: APIResponse must be frozen for immutability compliance."""

    def test_api_response_frozen(self) -> None:
        resp = APIResponse(success=True, data={"key": "value"})
        with pytest.raises(ValidationError):
            resp.success = False  # type: ignore[misc]

    def test_api_response_error_field_frozen(self) -> None:
        resp = APIResponse(success=False, error="something broke")
        with pytest.raises(ValidationError):
            resp.error = "changed"  # type: ignore[misc]

    def test_api_response_construction(self) -> None:
        resp = APIResponse(success=True, data={"x": 1}, meta={"page": 1})
        assert resp.success is True
        assert resp.data == {"x": 1}
        assert resp.meta == {"page": 1}
