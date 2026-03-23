"""Tests for Phase B: Parameter Calibration Pipeline.

Covers:
- CalibrationParams frozen dataclass (immutability, defaults, to_dict)
- ParameterCalibrator._compute_rmse (pure function)
- ParameterCalibrator._grid_candidates / _random_candidates
- ParameterCalibrator.calibrate (integration with synthetic data)
- ParameterCalibrator.save_calibration / load_best_calibration (DB round-trip)
- macro_controller.update_from_actions accepts CalibrationParams
"""

from __future__ import annotations

import dataclasses
import json
from unittest.mock import AsyncMock, patch

import pytest

from backend.app.services.calibration_config import (
    DEFAULT_CALIBRATION,
    CalibrationParams,
)
from backend.app.services.parameter_calibrator import (
    HistoricalDataPoint,
    ParameterCalibrator,
)

# ===========================================================================
# CalibrationParams unit tests
# ===========================================================================


class TestCalibrationParams:
    """Unit tests for the CalibrationParams frozen dataclass."""

    def test_default_values_match_original_magic_numbers(self):
        """DEFAULT_CALIBRATION should reproduce the original hard-coded values."""
        p = DEFAULT_CALIBRATION
        assert p.neg_threshold == 0.60
        assert p.pos_threshold == 0.60
        assert p.confidence_delta_neg == 0.3
        assert p.confidence_delta_pos == 0.2
        assert p.gdp_delta_neg == 0.001
        assert p.property_neg_ccl_factor == 0.999
        assert p.employment_neg_unemployment_delta == 0.001
        assert p.emigration_threshold == 0.20
        assert p.emigration_net_migration_delta == 100
        assert p.stock_pos_hsi_factor == 1.002
        assert p.clamp_confidence_min == 20.0
        assert p.clamp_confidence_max == 120.0
        assert p.clamp_gdp_min == -0.15
        assert p.clamp_gdp_max == 0.20
        assert p.clamp_hsi_min == 5_000.0
        assert p.clamp_hsi_max == 60_000.0
        assert p.clamp_ccl_min == 50.0
        assert p.clamp_ccl_max == 300.0
        assert p.clamp_unemployment_min == 0.01
        assert p.clamp_unemployment_max == 0.25
        assert p.clamp_net_migration_min == -200_000
        assert p.clamp_net_migration_max == 100_000

    def test_frozen_prevents_mutation(self):
        """CalibrationParams must be immutable."""
        p = DEFAULT_CALIBRATION
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            p.neg_threshold = 0.99  # type: ignore[misc]

    def test_replace_returns_new_instance(self):
        """dataclasses.replace should return a new object, not modify the original."""
        original = DEFAULT_CALIBRATION
        modified = dataclasses.replace(original, neg_threshold=0.70)
        assert modified.neg_threshold == 0.70
        assert original.neg_threshold == 0.60  # original unchanged
        assert modified is not original

    def test_to_dict_contains_all_fields(self):
        """to_dict() should serialise every field."""
        d = DEFAULT_CALIBRATION.to_dict()
        assert "neg_threshold" in d
        assert "confidence_delta_neg" in d
        assert "clamp_hsi_max" in d
        assert d["neg_threshold"] == 0.60
        # Should be JSON-serialisable
        json.dumps(d)

    def test_to_dict_roundtrip(self):
        """CalibrationParams should reconstruct from its own to_dict() output."""
        original = dataclasses.replace(DEFAULT_CALIBRATION, neg_threshold=0.55, gdp_delta_neg=0.002)
        reconstructed = CalibrationParams(**original.to_dict())
        assert reconstructed == original


# ===========================================================================
# ParameterCalibrator._compute_rmse (pure function)
# ===========================================================================


class TestComputeRmse:
    """Unit tests for the RMSE computation (no DB, no async)."""

    def _make_point(self, **kwargs) -> HistoricalDataPoint:
        defaults = dict(
            period="2024-Q1",
            neg_ratio=0.65,
            pos_ratio=0.20,
            emigration_freq=0.25,
            property_neg=True,
            employment_neg=False,
            stock_pos=False,
            observed_confidence_delta=-0.3,
            observed_gdp_delta=-0.001,
            observed_hsi_pct_change=0.0,
            observed_ccl_pct_change=-0.001,
            observed_unemployment_delta=0.0,
            observed_net_migration_delta=-100.0,
        )
        defaults.update(kwargs)
        return HistoricalDataPoint(**defaults)

    def test_rmse_returns_float(self):
        data = [self._make_point()]
        rmse = ParameterCalibrator._compute_rmse(DEFAULT_CALIBRATION, data)
        assert isinstance(rmse, float)
        assert rmse >= 0.0

    def test_rmse_lower_for_better_params(self):
        """A near-perfect parameter set should have lower RMSE than random."""
        data = [
            self._make_point(
                neg_ratio=0.65,
                pos_ratio=0.20,
                emigration_freq=0.25,
                property_neg=True,
                employment_neg=False,
                stock_pos=False,
                observed_confidence_delta=-0.3,
                observed_gdp_delta=-0.001,
                observed_hsi_pct_change=0.0,
                observed_ccl_pct_change=-0.001,
                observed_unemployment_delta=0.0,
                observed_net_migration_delta=-100.0,
            )
        ]
        # Params closely matching the observed data
        good_params = dataclasses.replace(
            DEFAULT_CALIBRATION,
            neg_threshold=0.60,
            confidence_delta_neg=0.3,
            gdp_delta_neg=0.001,
            emigration_threshold=0.20,
            emigration_net_migration_delta=100,
        )
        # Very wrong params
        bad_params = dataclasses.replace(
            DEFAULT_CALIBRATION,
            neg_threshold=0.99,
            confidence_delta_neg=5.0,
            gdp_delta_neg=0.1,
        )
        rmse_good = ParameterCalibrator._compute_rmse(good_params, data)
        rmse_bad = ParameterCalibrator._compute_rmse(bad_params, data)
        assert rmse_good <= rmse_bad

    def test_rmse_empty_data_returns_inf(self):
        rmse = ParameterCalibrator._compute_rmse(DEFAULT_CALIBRATION, [])
        assert rmse == float("inf")

    def test_rmse_multiple_points(self):
        """RMSE should remain finite and non-negative for many data points."""
        data = [self._make_point(neg_ratio=0.6 + i * 0.01, period=f"2024-Q{i + 1}") for i in range(5)]
        rmse = ParameterCalibrator._compute_rmse(DEFAULT_CALIBRATION, data)
        assert 0.0 <= rmse < float("inf")


# ===========================================================================
# Candidate generation
# ===========================================================================


class TestCandidateGeneration:
    """Tests for grid / random candidate generation (no DB)."""

    def test_grid_candidates_non_empty(self):
        candidates = ParameterCalibrator._grid_candidates()
        assert len(candidates) > 0

    def test_grid_candidates_all_frozen(self):
        for c in ParameterCalibrator._grid_candidates()[:5]:
            assert isinstance(c, CalibrationParams)
            with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
                c.neg_threshold = 0.0  # type: ignore[misc]

    def test_random_candidates_count(self):
        candidates = ParameterCalibrator._random_candidates(50)
        assert len(candidates) == 50

    def test_random_candidates_deterministic(self):
        """Same seed should produce same candidates each run."""
        c1 = ParameterCalibrator._random_candidates(10)
        c2 = ParameterCalibrator._random_candidates(10)
        assert [p.neg_threshold for p in c1] == [p.neg_threshold for p in c2]

    def test_grid_covers_all_threshold_values(self):
        """Ensure 0.60 default is included in the grid."""
        candidates = ParameterCalibrator._grid_candidates()
        thresholds = {c.neg_threshold for c in candidates}
        assert 0.60 in thresholds


# ===========================================================================
# calibrate() integration (synthetic data, no DB)
# ===========================================================================


class TestCalibrate:
    """Integration tests for the calibrate() method using synthetic data."""

    @pytest.mark.asyncio
    async def test_calibrate_grid_search_returns_params_and_rmse(self):
        calibrator = ParameterCalibrator()
        data = calibrator._synthetic_baseline()
        assert len(data) > 0

        params, rmse = await calibrator.calibrate(data, method="grid_search")

        assert isinstance(params, CalibrationParams)
        assert isinstance(rmse, float)
        assert rmse >= 0.0

    @pytest.mark.asyncio
    async def test_calibrate_random_search_returns_params_and_rmse(self):
        calibrator = ParameterCalibrator()
        data = calibrator._synthetic_baseline()
        params, rmse = await calibrator.calibrate(data, method="random_search")

        assert isinstance(params, CalibrationParams)
        assert rmse >= 0.0

    @pytest.mark.asyncio
    async def test_calibrate_empty_data_returns_defaults(self):
        calibrator = ParameterCalibrator()
        params, rmse = await calibrator.calibrate([], method="grid_search")
        assert params == DEFAULT_CALIBRATION
        assert rmse == 0.0

    @pytest.mark.asyncio
    async def test_calibrate_finds_better_than_random(self):
        """Calibrated RMSE should be no worse than a random bad set."""
        calibrator = ParameterCalibrator()
        data = calibrator._synthetic_baseline()

        _, calibrated_rmse = await calibrator.calibrate(data, method="grid_search")
        bad_params = dataclasses.replace(DEFAULT_CALIBRATION, neg_threshold=0.99)
        bad_rmse = ParameterCalibrator._compute_rmse(bad_params, data)

        assert calibrated_rmse <= bad_rmse


# ===========================================================================
# save_calibration / load_best_calibration (DB round-trip)
# ===========================================================================


class TestSaveLoadCalibration:
    """Tests for DB persistence of calibration results."""

    @pytest.mark.asyncio
    async def test_save_and_load_roundtrip(self, test_db, test_db_path):
        """Save a custom CalibrationParams and load it back as best."""
        custom = dataclasses.replace(
            DEFAULT_CALIBRATION,
            neg_threshold=0.55,
            confidence_delta_neg=0.25,
        )
        calibrator = ParameterCalibrator()

        with patch("backend.app.services.parameter_calibrator.get_db") as mock_get_db:
            # Create a real async context manager backed by the test DB
            mock_get_db.return_value = _AsyncDbContextManager(test_db)
            row_id = await calibrator.save_calibration(custom, label="test_run", rmse=0.042, data_period="2022-2024")
            assert row_id > 0

            loaded = await calibrator.load_best_calibration()

        assert loaded.neg_threshold == 0.55
        assert loaded.confidence_delta_neg == 0.25

    @pytest.mark.asyncio
    async def test_load_best_returns_defaults_when_no_data(self, test_db):
        """load_best_calibration returns DEFAULT_CALIBRATION when table is empty."""
        calibrator = ParameterCalibrator()

        with patch("backend.app.services.parameter_calibrator.get_db") as mock_get_db:
            mock_get_db.return_value = _AsyncDbContextManager(test_db)
            loaded = await calibrator.load_best_calibration()

        assert loaded == DEFAULT_CALIBRATION

    @pytest.mark.asyncio
    async def test_load_selects_lowest_rmse(self, test_db):
        """load_best_calibration should return the entry with the lowest RMSE."""
        calibrator = ParameterCalibrator()
        params_low = dataclasses.replace(DEFAULT_CALIBRATION, neg_threshold=0.55)
        params_high = dataclasses.replace(DEFAULT_CALIBRATION, neg_threshold=0.70)

        with patch("backend.app.services.parameter_calibrator.get_db") as mock_get_db:
            mock_get_db.return_value = _AsyncDbContextManager(test_db)
            await calibrator.save_calibration(params_high, label="high_rmse", rmse=0.9)

        with patch("backend.app.services.parameter_calibrator.get_db") as mock_get_db:
            mock_get_db.return_value = _AsyncDbContextManager(test_db)
            await calibrator.save_calibration(params_low, label="low_rmse", rmse=0.1)

        with patch("backend.app.services.parameter_calibrator.get_db") as mock_get_db:
            mock_get_db.return_value = _AsyncDbContextManager(test_db)
            best = await calibrator.load_best_calibration()

        assert best.neg_threshold == 0.55


# ===========================================================================
# macro_controller.update_from_actions accepts CalibrationParams
# ===========================================================================


class TestMacroControllerAcceptsCalibration:
    """Verify that update_from_actions uses CalibrationParams correctly."""

    @pytest.mark.asyncio
    async def test_uses_custom_neg_threshold(self):
        """A higher neg_threshold should prevent confidence reduction at 65% neg."""
        from backend.app.services.macro_controller import MacroController
        from backend.app.services.macro_state import MacroState

        state = MacroState(
            hibor_1m=0.04,
            prime_rate=0.0575,
            unemployment_rate=0.029,
            median_monthly_income=20_000,
            ccl_index=152.3,
            avg_sqft_price={},
            mortgage_cap=0.70,
            stamp_duty_rates={},
            gdp_growth=0.032,
            cpi_yoy=0.021,
            hsi_level=16_800.0,
            consumer_confidence=88.5,
            net_migration=-12_000,
            birth_rate=5.8,
            policy_flags={},
        )

        # 65% negative posts → with default threshold (0.60) triggers reduction
        # With tight threshold (0.70) it should NOT trigger
        tight_params = dataclasses.replace(DEFAULT_CALIBRATION, neg_threshold=0.70)

        mc = MacroController()

        # Simulate 65% negative sentiment in action logs
        mock_rows = [("negative", "[]")] * 65 + [("positive", "[]")] * 35

        with patch("backend.app.utils.db.get_db") as mock_get_db:
            mock_cursor = AsyncMock()
            mock_cursor.fetchall = AsyncMock(return_value=mock_rows)
            mock_db = AsyncMock()
            mock_db.execute = AsyncMock(return_value=mock_cursor)
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            # Default params: 65% neg > 60% threshold → confidence should drop
            updated_default = await mc.update_from_actions(state, "sess1", 5, calibration=DEFAULT_CALIBRATION)

        with patch("backend.app.utils.db.get_db") as mock_get_db:
            mock_cursor = AsyncMock()
            mock_cursor.fetchall = AsyncMock(return_value=mock_rows)
            mock_db = AsyncMock()
            mock_db.execute = AsyncMock(return_value=mock_cursor)
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            # Tight params: 65% neg < 70% threshold → no change
            updated_tight = await mc.update_from_actions(state, "sess1", 5, calibration=tight_params)

        assert updated_default.consumer_confidence < state.consumer_confidence
        assert updated_tight.consumer_confidence == state.consumer_confidence

    @pytest.mark.asyncio
    async def test_clamp_applied_from_params(self):
        """Custom clamp max should cap consumer_confidence."""
        from backend.app.services.macro_controller import MacroController
        from backend.app.services.macro_state import MacroState

        state = MacroState(
            hibor_1m=0.04,
            prime_rate=0.0575,
            unemployment_rate=0.029,
            median_monthly_income=20_000,
            ccl_index=152.3,
            avg_sqft_price={},
            mortgage_cap=0.70,
            stamp_duty_rates={},
            gdp_growth=0.032,
            cpi_yoy=0.021,
            hsi_level=16_800.0,
            consumer_confidence=119.8,
            net_migration=-12_000,
            birth_rate=5.8,
            policy_flags={},
        )

        # Very low cap: max confidence = 100
        capped_params = dataclasses.replace(DEFAULT_CALIBRATION, clamp_confidence_max=100.0)

        # 80% positive → should try to raise confidence
        mock_rows = [("positive", "[]")] * 80 + [("neutral", "[]")] * 20

        mc = MacroController()

        with patch("backend.app.utils.db.get_db") as mock_get_db:
            mock_cursor = AsyncMock()
            mock_cursor.fetchall = AsyncMock(return_value=mock_rows)
            mock_db = AsyncMock()
            mock_db.execute = AsyncMock(return_value=mock_cursor)
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            updated = await mc.update_from_actions(state, "sess1", 5, calibration=capped_params)

        assert updated.consumer_confidence <= 100.0


# ===========================================================================
# Helpers
# ===========================================================================


class _AsyncDbContextManager:
    """Wraps an aiosqlite.Connection as an async context manager for patching."""

    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *args):
        pass
