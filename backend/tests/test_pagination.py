"""Unit tests for pagination utility (Phase 0.6).

Covers:
- Default max_limit enforcement
- Custom max_limit
- Values at boundary (0, 1, max, max+1)
- Negative input clamped to 1
"""

from __future__ import annotations

import pytest

from backend.app.utils.pagination import clamp_limit


class TestClampLimit:
    def test_within_bounds_unchanged(self):
        assert clamp_limit(50) == 50

    def test_zero_clamped_to_one(self):
        assert clamp_limit(0) == 1

    def test_negative_clamped_to_one(self):
        assert clamp_limit(-10) == 1

    def test_exactly_max_limit_allowed(self):
        assert clamp_limit(100) == 100

    def test_exceeds_max_limit_clamped(self):
        assert clamp_limit(500) == 100

    def test_custom_max_limit(self):
        assert clamp_limit(200, max_limit=500) == 200

    def test_custom_max_limit_clamped(self):
        assert clamp_limit(600, max_limit=250) == 250

    def test_one_is_minimum(self):
        assert clamp_limit(1) == 1

    def test_returns_int(self):
        result = clamp_limit(50)
        assert isinstance(result, int)

    def test_large_negative_clamped(self):
        assert clamp_limit(-9999) == 1

    @pytest.mark.parametrize("limit,expected", [
        (10, 10),
        (100, 100),
        (101, 100),
        (1, 1),
        (0, 1),
    ])
    def test_parametrize_default_max(self, limit, expected):
        assert clamp_limit(limit) == expected
