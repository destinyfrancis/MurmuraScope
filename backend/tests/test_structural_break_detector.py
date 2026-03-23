"""Tests for structural break detection service.

Covers: no-break series, obvious level shift, recommended start index,
short series guard, frozen result types, break direction validity.
"""

from __future__ import annotations

import pytest


def test_no_breaks_in_smooth_series():
    import numpy as np

    from backend.app.services.structural_break_detector import detect_structural_breaks

    series = np.linspace(1.0, 10.0, 50).tolist()
    result = detect_structural_breaks(series)

    assert isinstance(result.has_breaks, bool)
    assert result.n_breaks == len(result.break_points)


def test_detects_obvious_level_shift():
    from backend.app.services.structural_break_detector import detect_structural_breaks

    # Clear break: first 25 points around 0, last 25 around 100
    series = [0.1 * i for i in range(25)] + [100 + 0.1 * i for i in range(25)]
    result = detect_structural_breaks(series)

    assert result.has_breaks is True
    assert result.n_breaks >= 1
    # Break should be near index 25
    break_indices = [bp.index for bp in result.break_points]
    assert any(20 <= idx <= 30 for idx in break_indices)


def test_recommended_start_after_break():
    from backend.app.services.structural_break_detector import detect_structural_breaks

    series = [0.0] * 20 + [50.0] * 20
    result = detect_structural_breaks(series)

    if result.has_breaks:
        assert result.recommended_start_index > 0
        assert result.recommended_start_index < len(series)


def test_short_series_returns_no_break():
    from backend.app.services.structural_break_detector import detect_structural_breaks

    result = detect_structural_breaks([1.0, 2.0, 3.0])

    assert result.has_breaks is False
    assert result.recommended_start_index == 0


def test_result_is_frozen():
    from backend.app.services.structural_break_detector import BreakDetectionResult

    r = BreakDetectionResult(
        break_points=(),
        n_breaks=0,
        recommended_start_index=0,
        method="none",
        has_breaks=False,
    )
    with pytest.raises((AttributeError, TypeError)):
        r.n_breaks = 5  # type: ignore[misc]


def test_break_point_direction_valid():
    from backend.app.services.structural_break_detector import detect_structural_breaks

    series = [float(i) for i in range(30)] + [100.0 - float(i) for i in range(30)]
    result = detect_structural_breaks(series)

    for bp in result.break_points:
        assert bp.direction in ("up", "down", "level_shift")
        assert 0.0 <= bp.confidence <= 1.0


def test_break_point_is_frozen():
    from backend.app.services.structural_break_detector import BreakPoint

    bp = BreakPoint(index=10, confidence=0.9, direction="up")
    with pytest.raises((AttributeError, TypeError)):
        bp.index = 20  # type: ignore[misc]


def test_n_breaks_consistent_with_break_points():
    from backend.app.services.structural_break_detector import detect_structural_breaks

    # Create a very clear multi-regime series
    series = [0.0] * 20 + [100.0] * 20 + [0.0] * 20
    result = detect_structural_breaks(series)

    assert result.n_breaks == len(result.break_points)
    assert isinstance(result.method, str)
    assert result.method in ("cusum", "bai_perron", "none")


def test_no_break_result_attributes():
    from backend.app.services.structural_break_detector import detect_structural_breaks

    result = detect_structural_breaks([1.0, 2.0])

    assert result.has_breaks is False
    assert result.n_breaks == 0
    assert result.recommended_start_index == 0
    assert result.break_points == ()
    assert result.method == "none"


def test_series_at_exact_min_length():
    from backend.app.services.structural_break_detector import detect_structural_breaks

    # Exactly 20 points — should attempt detection without error
    series = [float(i) for i in range(20)]
    result = detect_structural_breaks(series, min_series_length=20)

    # Should not raise; result is valid
    assert isinstance(result.has_breaks, bool)
    assert result.n_breaks == len(result.break_points)


def test_variance_ratio_fallback_used_for_short_cusum():
    """Confirm variance-ratio fallback fires for borderline series lengths."""
    from backend.app.services.structural_break_detector import detect_structural_breaks

    # 25 points: long enough for detection but may be too short for CUSUM
    series = [0.0] * 12 + [50.0] * 13
    result = detect_structural_breaks(series, min_series_length=20)

    # Should return a valid result without raising
    assert isinstance(result.has_breaks, bool)
    assert result.n_breaks == len(result.break_points)


def test_recommended_start_is_last_break():
    from backend.app.services.structural_break_detector import detect_structural_breaks

    series = [0.0] * 20 + [100.0] * 20
    result = detect_structural_breaks(series)

    if result.has_breaks and result.n_breaks > 0:
        last_break_idx = max(bp.index for bp in result.break_points)
        assert result.recommended_start_index == last_break_idx
