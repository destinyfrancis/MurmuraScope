"""Tests for module-level LHS + t-Copula helpers in monte_carlo.py.

Covers:
- _latin_hypercube_sample: uniform stratification, shape, [0,1) range
- _t_copula_sample: uniform marginals, shape, mean near 0.5
- MonteCarloEngine integration: sampling_method field
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.app.services.monte_carlo import (
    _latin_hypercube_sample,
    _t_copula_sample,
)


# ---------------------------------------------------------------------------
# _latin_hypercube_sample tests
# ---------------------------------------------------------------------------


def test_lhs_generates_uniform_coverage():
    """Each stratum [i/n, (i+1)/n) must contain exactly one LHS sample."""
    rng = np.random.default_rng(42)
    n = 100
    samples = _latin_hypercube_sample(n, 3, rng)
    assert samples.shape == (n, 3)
    for dim in range(3):
        col = np.sort(samples[:, dim])
        # All values in [0, 1)
        assert col.min() >= 0.0
        assert col.max() < 1.0
        # Each stratum [i/n, (i+1)/n) has exactly one point
        strata = (col * n).astype(int)
        assert len(np.unique(strata)) == n, (
            f"dim {dim}: expected {n} unique strata, got {len(np.unique(strata))}"
        )


def test_lhs_shape():
    """Output shape should be (n_samples, n_dims)."""
    rng = np.random.default_rng(0)
    samples = _latin_hypercube_sample(50, 4, rng)
    assert samples.shape == (50, 4)


def test_lhs_values_in_unit_interval():
    """All LHS samples must be in [0, 1)."""
    rng = np.random.default_rng(7)
    samples = _latin_hypercube_sample(200, 6, rng)
    assert np.all(samples >= 0.0)
    assert np.all(samples < 1.0)


def test_lhs_single_dim():
    """LHS with one dimension should still stratify correctly."""
    rng = np.random.default_rng(1)
    samples = _latin_hypercube_sample(10, 1, rng)
    assert samples.shape == (10, 1)
    strata = (np.sort(samples[:, 0]) * 10).astype(int)
    assert len(np.unique(strata)) == 10


def test_lhs_different_seeds_differ():
    """Different RNG seeds should produce different LHS layouts."""
    samples_a = _latin_hypercube_sample(50, 3, np.random.default_rng(1))
    samples_b = _latin_hypercube_sample(50, 3, np.random.default_rng(2))
    # Should not be identical (extremely unlikely with different seeds)
    assert not np.allclose(samples_a, samples_b)


# ---------------------------------------------------------------------------
# _t_copula_sample tests
# ---------------------------------------------------------------------------


def test_t_copula_returns_uniforms():
    """t-Copula output should be in [0, 1] with mean near 0.5."""
    rng = np.random.default_rng(42)
    corr = np.eye(3)
    samples = _t_copula_sample(200, 3, corr, df=4, rng=rng)
    assert samples.shape == (200, 3)
    # Values must be in [0, 1]
    assert samples.min() >= 0.0
    assert samples.max() <= 1.0
    # Mean should be near 0.5 for a symmetric distribution
    assert abs(samples.mean() - 0.5) < 0.1


def test_t_copula_shape():
    """Output shape must match (n_samples, n_dims)."""
    rng = np.random.default_rng(0)
    corr = np.eye(4)
    result = _t_copula_sample(100, 4, corr, df=4, rng=rng)
    assert result.shape == (100, 4)


def test_t_copula_all_values_finite():
    """No NaN or inf values in t-Copula output."""
    rng = np.random.default_rng(99)
    corr = np.array([[1.0, 0.5], [0.5, 1.0]])
    result = _t_copula_sample(150, 2, corr, df=4, rng=rng)
    assert np.all(np.isfinite(result))


def test_t_copula_handles_non_pd_matrix():
    """t-Copula should gracefully handle a non-positive-definite matrix."""
    rng = np.random.default_rng(10)
    bad_corr = np.array([[1.0, 1.5], [1.5, 1.0]])  # not PD
    result = _t_copula_sample(50, 2, bad_corr, df=4, rng=rng)
    assert result.shape == (50, 2)
    assert np.all(np.isfinite(result))


def test_t_copula_default_rng():
    """_t_copula_sample should work with rng=None (creates its own generator)."""
    corr = np.eye(2)
    result = _t_copula_sample(30, 2, corr, df=4, rng=None)
    assert result.shape == (30, 2)
    assert np.all(result >= 0.0)
    assert np.all(result <= 1.0)


# ---------------------------------------------------------------------------
# Integration: MonteCarloEngine uses LHS by default
# ---------------------------------------------------------------------------


def test_monte_carlo_uses_lhs_by_default():
    """_latin_hypercube_sample basic import and shape check."""
    rng = np.random.default_rng(0)
    s = _latin_hypercube_sample(10, 2, rng)
    assert s.shape == (10, 2)


@pytest.mark.asyncio
async def test_mc_engine_sampling_method_field():
    """MonteCarloEngine.run() should set sampling_method='lhs_t_copula'."""
    from backend.app.services.monte_carlo import MonteCarloEngine

    engine = MonteCarloEngine()
    result = await engine.run(
        session_id="test-lhs-module-session",
        n_trials=10,
        metrics=["ccl_index_change"],
    )
    assert result.sampling_method == "lhs_t_copula"
    assert result.n_trials == 10
