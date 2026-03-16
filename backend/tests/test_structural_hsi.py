"""Tests for Bai-Perron structural break detection and HSI decomposition.

10 tests total:
  - 5 for detect_structural_breaks (Bai-Perron)
  - 5 for HSI decomposition
"""

from __future__ import annotations

import dataclasses
import math
import os
import tempfile

import aiosqlite
import numpy as np
import pytest

from backend.app.services.validation_suite import (
    StructuralBreak,
    detect_structural_breaks,
)


# ---------------------------------------------------------------------------
# Bai-Perron structural break tests
# ---------------------------------------------------------------------------


class TestBaiPerronDetection:
    """Tests for detect_structural_breaks()."""

    def test_detects_known_level_shift(self) -> None:
        """A clear level shift at index 20 should be detected."""
        rng = np.random.RandomState(42)
        left = rng.normal(100, 2, 20).tolist()
        right = rng.normal(130, 2, 20).tolist()
        series = left + right
        periods = [f"T{i}" for i in range(len(series))]

        breaks = detect_structural_breaks(series, periods=periods, min_segment=8)

        assert len(breaks) >= 1
        # The detected break should be near index 20
        detected_indices = [b.break_index for b in breaks]
        assert any(abs(idx - 20) <= 3 for idx in detected_indices), (
            f"Expected break near index 20, got indices {detected_indices}"
        )

    def test_returns_empty_for_stationary_series(self) -> None:
        """A stationary series with no structural change returns no breaks."""
        rng = np.random.RandomState(99)
        series = rng.normal(50, 1, 40).tolist()
        periods = [f"T{i}" for i in range(len(series))]

        breaks = detect_structural_breaks(series, periods=periods, min_segment=8)

        assert breaks == ()

    def test_respects_min_segment(self) -> None:
        """No break should be detected within min_segment from edges."""
        # Level shift at index 5, but min_segment=8 should prevent detection
        series = [10.0] * 5 + [50.0] * 5
        periods = [f"T{i}" for i in range(len(series))]

        breaks = detect_structural_breaks(series, periods=periods, min_segment=8)

        # Series is only 10 long, min_segment=8 means we need 16 points minimum
        assert breaks == ()

    def test_respects_max_breaks(self) -> None:
        """Number of detected breaks should not exceed max_breaks."""
        rng = np.random.RandomState(7)
        # Three clear level shifts
        seg1 = rng.normal(100, 1, 20).tolist()
        seg2 = rng.normal(150, 1, 20).tolist()
        seg3 = rng.normal(80, 1, 20).tolist()
        seg4 = rng.normal(200, 1, 20).tolist()
        series = seg1 + seg2 + seg3 + seg4
        periods = [f"T{i}" for i in range(len(series))]

        breaks = detect_structural_breaks(
            series, periods=periods, max_breaks=2, min_segment=8,
        )

        assert len(breaks) <= 2

    def test_structural_break_is_frozen_dataclass(self) -> None:
        """StructuralBreak should be immutable (frozen dataclass)."""
        brk = StructuralBreak(
            break_point="2020-Q1",
            break_index=10,
            f_statistic=15.3,
            p_value=0.001,
            bic_improvement=5.2,
        )

        assert dataclasses.is_dataclass(brk)

        with pytest.raises(dataclasses.FrozenInstanceError):
            brk.break_index = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# HSI Decomposition tests
# ---------------------------------------------------------------------------


class TestHSIDecomposition:
    """Tests for HSIDecomposer."""

    @pytest.fixture
    def db_path(self, tmp_path) -> str:
        """Create a temporary SQLite DB with test data."""
        db_file = str(tmp_path / "test_hsi.db")
        return db_file

    @pytest.fixture
    def populated_db_path(self, db_path) -> str:
        """Create a DB populated with aligned HSI, GDP, HIBOR data."""
        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS market_data ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  date TEXT, asset_type TEXT, ticker TEXT,"
            "  open REAL, close REAL, high REAL, low REAL,"
            "  volume REAL, source TEXT, created_at TEXT"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS hk_data_snapshots ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  category TEXT, metric TEXT, period TEXT,"
            "  value REAL, source TEXT, source_url TEXT,"
            "  created_at TEXT"
            ")"
        )

        rng = np.random.RandomState(42)

        # Generate 12 quarters of aligned data
        for i in range(12):
            year = 2022 + i // 4
            q = (i % 4) + 1
            period = f"{year}-Q{q}"
            date_str = f"{year}-{q * 3:02d}-28"

            hsi_close = 20000 + rng.normal(0, 500)
            gdp_growth = 2.0 + rng.normal(0, 0.5)
            hibor = 3.0 + rng.normal(0, 0.3)

            conn.execute(
                "INSERT INTO market_data (date, ticker, close) VALUES (?, 'HSI', ?)",
                (date_str, hsi_close),
            )
            conn.execute(
                "INSERT INTO hk_data_snapshots (category, metric, period, value, source) "
                "VALUES ('gdp', 'gdp_growth_rate', ?, ?, 'test')",
                (period, gdp_growth),
            )
            conn.execute(
                "INSERT INTO hk_data_snapshots (category, metric, period, value, source) "
                "VALUES ('interest_rate', 'hibor_1m', ?, ?, 'test')",
                (period, hibor),
            )

        conn.commit()
        conn.close()
        return db_path

    @pytest.mark.asyncio
    async def test_components_sum_to_total(self, populated_db_path: str) -> None:
        """fundamental + sentiment should equal total_return for each period."""
        from backend.app.services.hsi_decomposer import HSIDecomposer

        decomposer = HSIDecomposer(db_path=populated_db_path)
        result = await decomposer.decompose(n_quarters=20)

        assert len(result.decompositions) > 0

        for d in result.decompositions:
            reconstructed = d.fundamental_component + d.sentiment_component
            assert abs(reconstructed - d.total_return) < 1e-4, (
                f"Period {d.period}: fundamental({d.fundamental_component}) + "
                f"sentiment({d.sentiment_component}) = {reconstructed} != "
                f"total_return({d.total_return})"
            )

    @pytest.mark.asyncio
    async def test_decomposition_result_is_frozen(self, populated_db_path: str) -> None:
        """DecompositionResult and HSIDecomposition should be frozen."""
        from backend.app.services.hsi_decomposer import (
            DecompositionResult,
            HSIDecomposition,
        )

        assert dataclasses.is_dataclass(DecompositionResult)
        assert dataclasses.is_dataclass(HSIDecomposition)

        decomposer = __import__(
            "backend.app.services.hsi_decomposer", fromlist=["HSIDecomposer"]
        ).HSIDecomposer(db_path=populated_db_path)
        result = await decomposer.decompose(n_quarters=20)

        with pytest.raises(dataclasses.FrozenInstanceError):
            result.beta_gdp = 999.0  # type: ignore[misc]

        if result.decompositions:
            with pytest.raises(dataclasses.FrozenInstanceError):
                result.decompositions[0].total_return = 999.0  # type: ignore[misc]

    @pytest.mark.asyncio
    async def test_empty_result_when_insufficient_data(self, db_path: str) -> None:
        """Empty DB should return empty decompositions with diagnostic info."""
        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS market_data ("
            "  id INTEGER PRIMARY KEY, date TEXT, ticker TEXT, close REAL"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS hk_data_snapshots ("
            "  id INTEGER PRIMARY KEY, category TEXT, metric TEXT,"
            "  period TEXT, value REAL, source TEXT"
            ")"
        )
        conn.commit()
        conn.close()

        from backend.app.services.hsi_decomposer import HSIDecomposer

        decomposer = HSIDecomposer(db_path=db_path)
        result = await decomposer.decompose(n_quarters=20)

        assert result.decompositions == ()
        assert result.diagnostics["status"] == "insufficient_data"
        assert result.r_squared == 0.0

    @pytest.mark.asyncio
    async def test_beta_signs(self, populated_db_path: str) -> None:
        """GDP beta should be finite and HIBOR beta should be finite.

        We cannot guarantee signs with random test data, but both should be
        finite real numbers (not NaN/inf).
        """
        from backend.app.services.hsi_decomposer import HSIDecomposer

        decomposer = HSIDecomposer(db_path=populated_db_path)
        result = await decomposer.decompose(n_quarters=20)

        assert math.isfinite(result.beta_gdp)
        assert math.isfinite(result.beta_hibor)
        assert 0.0 <= result.r_squared <= 1.0

    @pytest.mark.asyncio
    async def test_to_dict_serializes_correctly(self, populated_db_path: str) -> None:
        """to_dict() should produce a JSON-serializable structure."""
        import json

        from backend.app.services.hsi_decomposer import HSIDecomposer

        decomposer = HSIDecomposer(db_path=populated_db_path)
        result = await decomposer.decompose(n_quarters=20)

        d = result.to_dict()

        assert isinstance(d, dict)
        assert "decompositions" in d
        assert "beta_gdp" in d
        assert "beta_hibor" in d
        assert "r_squared" in d
        assert "diagnostics" in d

        # Verify JSON serializable
        json_str = json.dumps(d)
        assert len(json_str) > 0

        # Verify decomposition entries have expected keys
        if d["decompositions"]:
            entry = d["decompositions"][0]
            assert "period" in entry
            assert "total_return" in entry
            assert "fundamental_component" in entry
            assert "sentiment_component" in entry
            assert "interest_rate_component" in entry

    # -----------------------------------------------------------------------
    # New tests for macro risk factors and lifecycle MPC
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_to_dict_includes_macro_factor_fields(self, populated_db_path: str) -> None:
        """to_dict() must expose the new macro risk factor fields."""
        from backend.app.services.hsi_decomposer import HSIDecomposer

        decomposer = HSIDecomposer(db_path=populated_db_path)
        result = await decomposer.decompose(n_quarters=20)
        d = result.to_dict()

        assert "rate_spread_coef" in d, "Expected rate_spread_coef in to_dict output"
        assert "cny_coef" in d, "Expected cny_coef in to_dict output"
        assert "macro_r2_contribution" in d, "Expected macro_r2_contribution in to_dict output"

        assert isinstance(d["rate_spread_coef"], float)
        assert isinstance(d["cny_coef"], float)
        assert 0.0 <= d["macro_r2_contribution"] <= 1.0

    @pytest.mark.asyncio
    async def test_decomposition_result_has_macro_fields(self, populated_db_path: str) -> None:
        """DecompositionResult dataclass must carry rate_spread_coef, cny_coef, macro_r2_contribution."""
        from backend.app.services.hsi_decomposer import DecompositionResult, HSIDecomposer

        # Check field presence via dataclass fields
        field_names = {f.name for f in dataclasses.fields(DecompositionResult)}
        assert "rate_spread_coef" in field_names
        assert "cny_coef" in field_names
        assert "macro_r2_contribution" in field_names

        # Check values on a real decomposition
        decomposer = HSIDecomposer(db_path=populated_db_path)
        result = await decomposer.decompose(n_quarters=20)

        assert math.isfinite(result.rate_spread_coef)
        assert math.isfinite(result.cny_coef)
        assert 0.0 <= result.macro_r2_contribution <= 1.0

    @pytest.mark.asyncio
    async def test_macro_factors_fallback_on_missing_data(self, db_path: str) -> None:
        """When macro factor data is absent, decompose returns zeroed macro coefficients."""
        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS market_data ("
            "  id INTEGER PRIMARY KEY, date TEXT, ticker TEXT, close REAL"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS hk_data_snapshots ("
            "  id INTEGER PRIMARY KEY, category TEXT, metric TEXT,"
            "  period TEXT, value REAL, source TEXT"
            ")"
        )
        conn.commit()
        conn.close()

        from backend.app.services.hsi_decomposer import HSIDecomposer

        decomposer = HSIDecomposer(db_path=db_path)
        result = await decomposer.decompose(n_quarters=20)

        # Empty DB → insufficient_data path → zeroed macro fields
        assert result.rate_spread_coef == 0.0
        assert result.cny_coef == 0.0
        assert result.macro_r2_contribution == 0.0


# ---------------------------------------------------------------------------
# Lifecycle MPC and wealth effect tests (consumer_model.py)
# ---------------------------------------------------------------------------


class TestLifecycleMPC:
    """Tests for _lifecycle_mpc and compute_spending in consumer_model."""

    def test_lifecycle_mpc_young(self) -> None:
        """Young agents (age < 30) should have MPC > 1 (dissaving)."""
        from backend.app.services.consumer_model import _lifecycle_mpc

        assert _lifecycle_mpc(25) > 1.0, "Young agents should have MPC > 1"
        assert _lifecycle_mpc(20) > 1.0

    def test_lifecycle_mpc_elderly(self) -> None:
        """Elderly agents should have higher MPC than middle-aged (asset drawdown)."""
        from backend.app.services.consumer_model import _lifecycle_mpc

        mpc_elderly = _lifecycle_mpc(65)
        mpc_middle = _lifecycle_mpc(50)
        assert mpc_elderly > mpc_middle, (
            f"Elderly MPC {mpc_elderly} should exceed middle-age MPC {mpc_middle}"
        )

    def test_lifecycle_mpc_age_bands(self) -> None:
        """Verify all four age bands return expected values."""
        from backend.app.services.consumer_model import _lifecycle_mpc

        assert _lifecycle_mpc(25) == pytest.approx(1.05)   # < 30
        assert _lifecycle_mpc(35) == pytest.approx(0.88)   # 30-44
        assert _lifecycle_mpc(50) == pytest.approx(0.78)   # 45-59
        assert _lifecycle_mpc(70) == pytest.approx(0.92)   # 60+

    def test_lifecycle_mpc_boundary(self) -> None:
        """Boundary ages should map to the correct band."""
        from backend.app.services.consumer_model import _lifecycle_mpc

        assert _lifecycle_mpc(30) == pytest.approx(0.88)   # age 30 → band [30, 45)
        assert _lifecycle_mpc(45) == pytest.approx(0.78)   # age 45 → band [45, 60)
        assert _lifecycle_mpc(60) == pytest.approx(0.92)   # age 60 → elderly band

    def test_wealth_effect_positive_ccl(self) -> None:
        """Rising property prices (positive ccl_change) should boost total consumption."""
        from backend.app.services.consumer_model import SpendingProfile, compute_spending

        sp = SpendingProfile(
            food=0.28,
            housing=0.30,
            transport=0.10,
            entertainment=0.08,
            education=0.04,
            healthcare=0.04,
            savings_rate=0.16,
        )
        monthly_income = 30_000
        baseline = compute_spending(sp, monthly_income, age=40, ccl_change=0.0)
        boosted = compute_spending(sp, monthly_income, age=40, ccl_change=10.0)

        assert boosted["total_consumption"] > baseline["total_consumption"], (
            "Positive CCL change should increase total consumption via wealth effect"
        )

    def test_wealth_effect_negative_ccl(self) -> None:
        """Falling property prices (negative ccl_change) should reduce consumption."""
        from backend.app.services.consumer_model import SpendingProfile, compute_spending

        sp = SpendingProfile(
            food=0.28,
            housing=0.30,
            transport=0.10,
            entertainment=0.08,
            education=0.04,
            healthcare=0.04,
            savings_rate=0.16,
        )
        monthly_income = 30_000
        baseline = compute_spending(sp, monthly_income, age=40, ccl_change=0.0)
        reduced = compute_spending(sp, monthly_income, age=40, ccl_change=-10.0)

        assert reduced["total_consumption"] < baseline["total_consumption"], (
            "Negative CCL change should reduce total consumption"
        )

    def test_compute_spending_backward_compat(self) -> None:
        """compute_spending with default args (age=40, ccl_change=0) should behave predictably."""
        from backend.app.services.consumer_model import SpendingProfile, compute_spending

        sp = SpendingProfile(
            food=0.28,
            housing=0.30,
            transport=0.10,
            entertainment=0.08,
            education=0.04,
            healthcare=0.04,
            savings_rate=0.16,
        )
        result = compute_spending(sp, 30_000)
        assert "total_consumption" in result
        assert "lifecycle_mpc" in result
        assert "wealth_multiplier" in result
        assert result["wealth_multiplier"] == pytest.approx(1.0)
        assert result["total_consumption"] > 0

    def test_compute_spending_young_vs_middle(self) -> None:
        """Young agents should consume more than middle-aged given same income and profile."""
        from backend.app.services.consumer_model import SpendingProfile, compute_spending

        sp = SpendingProfile(
            food=0.28,
            housing=0.30,
            transport=0.10,
            entertainment=0.08,
            education=0.04,
            healthcare=0.04,
            savings_rate=0.16,
        )
        young = compute_spending(sp, 30_000, age=25)
        middle = compute_spending(sp, 30_000, age=50)

        assert young["total_consumption"] > middle["total_consumption"], (
            "Young agents (MPC>1) should out-consume middle-aged agents"
        )
