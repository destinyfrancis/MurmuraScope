"""Tests for Calibration FDR correction and Monte Carlo LHS + t-Copula.

Covers:
- Benjamini-Hochberg FDR correction (C1)
- LHS sampling + t-Copula dependence structure (C2)
- EnsembleResult sampling_method field
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy import stats as scipy_stats

from backend.app.models.ensemble import EnsembleResult, DistributionBand
from backend.app.services.monte_carlo import MonteCarloEngine
from backend.data_pipeline.calibration import _apply_fdr_correction


# ---------------------------------------------------------------------------
# C1: Benjamini-Hochberg FDR Tests
# ---------------------------------------------------------------------------


class TestFDRCorrection:
    """Tests for _apply_fdr_correction()."""

    def test_all_significant_keeps_all(self) -> None:
        """When all p-values are well below threshold, all pairs are kept."""
        pairs = [
            ("pair_a", 0.001),
            ("pair_b", 0.005),
            ("pair_c", 0.010),
        ]
        result = _apply_fdr_correction(pairs, alpha=0.05)
        assert result == {"pair_a", "pair_b", "pair_c"}

    def test_all_nonsignificant_keeps_none(self) -> None:
        """When all p-values are above any BH threshold, none are kept."""
        pairs = [
            ("pair_a", 0.80),
            ("pair_b", 0.90),
            ("pair_c", 0.95),
        ]
        result = _apply_fdr_correction(pairs, alpha=0.05)
        assert result == set()

    def test_fdr_less_conservative_than_bonferroni(self) -> None:
        """BH-FDR should discover more (or equal) pairs than Bonferroni.

        Construct p-values where some pass FDR but not Bonferroni.
        Bonferroni threshold = 0.05 / 6 = 0.00833
        BH threshold for rank 3/6 = 0.025, rank 4/6 = 0.0333
        """
        pairs = [
            ("a", 0.001),
            ("b", 0.005),
            ("c", 0.015),   # passes BH (threshold=0.025) but NOT Bonferroni (0.00833)
            ("d", 0.030),   # passes BH (threshold=0.0333) but NOT Bonferroni
            ("e", 0.200),
            ("f", 0.500),
        ]
        fdr_result = _apply_fdr_correction(pairs, alpha=0.05)

        # Bonferroni: threshold = 0.05/6 = 0.00833
        bonferroni_threshold = 0.05 / len(pairs)
        bonferroni_result = {name for name, p in pairs if p <= bonferroni_threshold}

        assert len(fdr_result) >= len(bonferroni_result)
        assert bonferroni_result.issubset(fdr_result)
        # Specifically, FDR finds more than Bonferroni in this case
        assert len(fdr_result) > len(bonferroni_result)

    def test_empty_input_returns_empty(self) -> None:
        """Empty input list returns empty set."""
        result = _apply_fdr_correction([], alpha=0.05)
        assert result == set()

    def test_boundary_p_value_exactly_at_threshold(self) -> None:
        """P-value exactly at the BH threshold should be included.

        Single test: threshold = (1/1) * 0.05 = 0.05.
        """
        pairs = [("only_pair", 0.05)]
        result = _apply_fdr_correction(pairs, alpha=0.05)
        assert "only_pair" in result

    def test_boundary_multiple_pairs(self) -> None:
        """Verify correct boundary handling with multiple pairs.

        2 pairs: rank 1 threshold = 0.025, rank 2 threshold = 0.05.
        """
        pairs = [("a", 0.025), ("b", 0.05)]
        result = _apply_fdr_correction(pairs, alpha=0.05)
        assert result == {"a", "b"}


# ---------------------------------------------------------------------------
# C2: LHS + t-Copula Tests
# ---------------------------------------------------------------------------


class TestLHSSampling:
    """Tests for _generate_lhs_samples()."""

    def test_samples_in_unit_range(self) -> None:
        """All LHS samples must be in [0, 1]."""
        rng = np.random.default_rng(42)
        samples = MonteCarloEngine._generate_lhs_samples(100, 5, rng)
        assert np.all(samples >= 0.0)
        assert np.all(samples <= 1.0)

    def test_output_shape(self) -> None:
        """Output shape should be (n_trials, n_vars)."""
        rng = np.random.default_rng(42)
        samples = MonteCarloEngine._generate_lhs_samples(200, 7, rng)
        assert samples.shape == (200, 7)

    def test_better_uniformity_than_random(self) -> None:
        """LHS samples should have more uniform bin coverage than pure random.

        Divide [0,1] into 10 bins and check variance of bin counts.
        LHS should have lower variance (more even coverage).
        """
        rng = np.random.default_rng(42)
        n_trials = 1000
        n_vars = 4

        lhs_samples = MonteCarloEngine._generate_lhs_samples(n_trials, n_vars, rng)
        random_samples = rng.random((n_trials, n_vars))

        n_bins = 10
        lhs_variances = []
        random_variances = []
        for dim in range(n_vars):
            lhs_counts, _ = np.histogram(lhs_samples[:, dim], bins=n_bins, range=(0, 1))
            rand_counts, _ = np.histogram(random_samples[:, dim], bins=n_bins, range=(0, 1))
            lhs_variances.append(np.var(lhs_counts))
            random_variances.append(np.var(rand_counts))

        # LHS should have lower average bin-count variance
        assert np.mean(lhs_variances) < np.mean(random_variances)


class TestTCopula:
    """Tests for _apply_t_copula() and _nearest_pd()."""

    def test_output_shape_matches_input(self) -> None:
        """Output shape should match input shape."""
        uniform_samples = np.random.default_rng(42).random((100, 4))
        corr = np.eye(4)
        result = MonteCarloEngine._apply_t_copula(uniform_samples, corr, df=5)
        assert result.shape == (100, 4)

    def test_output_in_unit_range(self) -> None:
        """Copula-transformed samples should be in [0, 1]."""
        uniform_samples = np.random.default_rng(42).random((200, 3))
        corr = np.eye(3)
        result = MonteCarloEngine._apply_t_copula(uniform_samples, corr, df=5)
        assert np.all(result >= 0.0)
        assert np.all(result <= 1.0)

    def test_preserves_rank_correlation_approximately(self) -> None:
        """t-Copula with off-diagonal correlation should induce rank correlation.

        Use a strong positive correlation and check Spearman rho.
        """
        rng = np.random.default_rng(42)
        uniform_samples = rng.random((2000, 2))
        corr = np.array([
            [1.0, 0.8],
            [0.8, 1.0],
        ])
        result = MonteCarloEngine._apply_t_copula(uniform_samples, corr, df=5)
        spearman_rho, _ = scipy_stats.spearmanr(result[:, 0], result[:, 1])
        # Rank correlation should be positive and reasonably close to 0.8
        assert spearman_rho > 0.4, f"Spearman rho={spearman_rho}, expected > 0.4"

    def test_nearest_pd_returns_positive_definite(self) -> None:
        """_nearest_pd should fix a non-PD matrix."""
        # Create a matrix with a negative eigenvalue
        bad_matrix = np.array([
            [1.0, 1.5],
            [1.5, 1.0],
        ])
        # Verify it is not PD
        eigenvalues = np.linalg.eigvalsh(bad_matrix)
        assert np.any(eigenvalues < 0), "Test matrix should have negative eigenvalues"

        fixed = MonteCarloEngine._nearest_pd(bad_matrix)
        fixed_eigenvalues = np.linalg.eigvalsh(fixed)
        assert np.all(fixed_eigenvalues > 0), "Fixed matrix should be positive definite"

    def test_t_copula_handles_non_pd_matrix(self) -> None:
        """t-Copula should handle non-PD correlation matrix via nearest_pd."""
        rng = np.random.default_rng(42)
        uniform_samples = rng.random((50, 2))
        bad_corr = np.array([
            [1.0, 1.5],
            [1.5, 1.0],
        ])
        # Should not raise
        result = MonteCarloEngine._apply_t_copula(uniform_samples, bad_corr, df=5)
        assert result.shape == (50, 2)
        assert np.all(np.isfinite(result))


# ---------------------------------------------------------------------------
# EnsembleResult + Integration Tests
# ---------------------------------------------------------------------------


class TestEnsembleResultSamplingMethod:
    """Tests for sampling_method field on EnsembleResult."""

    def test_has_sampling_method_field(self) -> None:
        """EnsembleResult should have a sampling_method field."""
        result = EnsembleResult(
            session_id="test",
            n_trials=100,
            distributions=[],
        )
        assert hasattr(result, "sampling_method")
        assert result.sampling_method == "lhs_t_copula"

    @pytest.mark.asyncio
    async def test_mc_run_uses_lhs(self) -> None:
        """MonteCarloEngine.run() should set sampling_method='lhs_t_copula'."""
        engine = MonteCarloEngine()
        result = await engine.run(
            session_id="test-lhs-session",
            n_trials=10,
            metrics=["ccl_index_change"],
        )
        assert result.sampling_method == "lhs_t_copula"
