# backend/tests/test_sensitivity_sobol.py
"""Tests for Sobol sensitivity analysis extension."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app.services.sensitivity_analyzer import SensitivityAnalyzer, SobolResult


def _mock_coefficients():
    coeff = MagicMock()
    coeff.load = AsyncMock()
    coeff.get_all_by_sentiment.return_value = {"ccl_index": 0.5, "hsi_level": 0.3}
    coeff.get_all.return_value = {"negative_ratio": 0.5}
    return coeff


def _mock_validator(vary_output: bool = False):
    """Create a mock RetrospectiveValidator.

    Args:
        vary_output: If True, _compute_metrics returns varying directional_accuracy
            values so SALib can compute meaningful Sobol indices (avoids the
            'Constant values encountered' edge case that causes analyze to fail).
    """
    v = MagicMock()
    v._load_historical_series = AsyncMock(
        return_value={
            "ccl_index": [("2021-Q1", 160.0), ("2021-Q2", 162.0), ("2021-Q3", 158.0)],
        }
    )
    v._generate_trajectory = MagicMock(return_value=[160.0, 162.0, 159.0])
    if vary_output:
        # Cycle through [0.4, 0.5, 0.6, 0.7, 0.8] to give SALib non-constant Y
        _counter = [0]
        _values = [0.4, 0.5, 0.6, 0.7, 0.8, 0.6, 0.5, 0.4, 0.7, 0.8]

        async def _varying_metrics(*_args):
            val = _values[_counter[0] % len(_values)]
            _counter[0] += 1
            return {"directional_accuracy": val}

        v._compute_metrics = _varying_metrics
    else:
        v._compute_metrics = AsyncMock(return_value={"directional_accuracy": 0.7})
    return v


@pytest.mark.asyncio
async def test_run_sobol_returns_sobol_result():
    """run_sobol() should return a SobolResult with non-empty S1 and ST indices."""
    analyzer = SensitivityAnalyzer()
    coeff = _mock_coefficients()
    # Use vary_output=True so SALib gets non-constant Y values and can compute indices
    validator = _mock_validator(vary_output=True)

    import backend.app.services.calibrated_coefficients as cc_mod
    import backend.app.services.retrospective_validator as rv_mod

    original_cc = cc_mod.CalibratedCoefficients
    original_rv = rv_mod.RetrospectiveValidator
    cc_mod.CalibratedCoefficients = lambda: coeff  # type: ignore[assignment]
    rv_mod.RetrospectiveValidator = lambda: validator  # type: ignore[assignment]
    try:
        result = await analyzer.run_sobol("2021-Q1", "2021-Q3", n_samples=8)
    finally:
        cc_mod.CalibratedCoefficients = original_cc
        rv_mod.RetrospectiveValidator = original_rv

    assert isinstance(result, SobolResult)
    assert len(result.first_order) > 0
    assert len(result.total_order) > 0


@pytest.mark.asyncio
async def test_run_sobol_indices_in_range():
    """S1 and ST indices should be in [-0.5, 1.5] (SALib can return small negatives)."""
    analyzer = SensitivityAnalyzer()
    coeff = _mock_coefficients()
    validator = _mock_validator()

    import backend.app.services.calibrated_coefficients as cc_mod
    import backend.app.services.retrospective_validator as rv_mod

    original_cc = cc_mod.CalibratedCoefficients
    original_rv = rv_mod.RetrospectiveValidator
    cc_mod.CalibratedCoefficients = lambda: coeff  # type: ignore[assignment]
    rv_mod.RetrospectiveValidator = lambda: validator  # type: ignore[assignment]
    try:
        result = await analyzer.run_sobol("2021-Q1", "2021-Q3", n_samples=8)
    finally:
        cc_mod.CalibratedCoefficients = original_cc
        rv_mod.RetrospectiveValidator = original_rv

    for v in result.first_order.values():
        assert -0.5 <= v <= 1.5, f"S1 out of range: {v}"
    for v in result.total_order.values():
        assert -0.5 <= v <= 1.5, f"ST out of range: {v}"


@pytest.mark.asyncio
async def test_run_sobol_empty_on_no_data():
    """run_sobol() should return an empty SobolResult when data insufficient."""
    analyzer = SensitivityAnalyzer()
    coeff = _mock_coefficients()
    validator = MagicMock()
    validator._load_historical_series = AsyncMock(return_value={})
    validator._generate_trajectory = MagicMock(return_value=[])
    validator._compute_metrics = AsyncMock(return_value={"directional_accuracy": 0.5})

    import backend.app.services.calibrated_coefficients as cc_mod
    import backend.app.services.retrospective_validator as rv_mod

    original_cc = cc_mod.CalibratedCoefficients
    original_rv = rv_mod.RetrospectiveValidator
    cc_mod.CalibratedCoefficients = lambda: coeff  # type: ignore[assignment]
    rv_mod.RetrospectiveValidator = lambda: validator  # type: ignore[assignment]
    try:
        result = await analyzer.run_sobol("2021-Q1", "2021-Q3", n_samples=8)
    finally:
        cc_mod.CalibratedCoefficients = original_cc
        rv_mod.RetrospectiveValidator = original_rv

    assert result.first_order == {}
    assert result.total_order == {}
