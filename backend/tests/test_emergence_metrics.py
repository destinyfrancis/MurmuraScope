"""Tests for Time-Delayed Mutual Information (TDMI) emergence measurement.

Covers:
  - tdmi_random_uncorrelated_near_zero: independent signals → TDMI ≈ 0
  - tdmi_correlated_positive: correlated sequence → TDMI > 0
  - tdmi_lag_comparison: higher lag with copied series → lag=0 analogue
  - collect_pairs_basic: pair collection correctness
  - build_summary_empty: empty results produce zero summary
  - build_summary_detection: mean > threshold → emergence_detected=True
"""

from __future__ import annotations

import pytest

from backend.app.services.emergence_metrics import (
    _MIN_SAMPLES,
    EmergenceMetricsSummary,
    TDMIResult,
    _build_summary,
    _collect_pairs,
    _histogram_mi,
)

try:
    import numpy as np

    _NUMPY_AVAILABLE = True
except ImportError:
    _NUMPY_AVAILABLE = False

pytestmark = pytest.mark.unit


# ------------------------------------------------------------------ #
# _histogram_mi tests                                                  #
# ------------------------------------------------------------------ #


@pytest.mark.skipif(not _NUMPY_AVAILABLE, reason="numpy not installed")
def test_tdmi_random_uncorrelated_near_zero() -> None:
    """Completely independent random signals should yield TDMI close to zero."""
    rng = np.random.default_rng(42)
    x = rng.uniform(0.0, 1.0, 200)
    y = rng.uniform(0.0, 1.0, 200)

    mi = _histogram_mi(x, y)

    # Independent uniform variables have MI=0; histogram noise keeps it small
    assert mi >= 0.0, "MI must be non-negative"
    assert mi < 0.1, f"Expected near-zero for independent signals, got {mi:.4f}"


@pytest.mark.skipif(not _NUMPY_AVAILABLE, reason="numpy not installed")
def test_tdmi_correlated_positive() -> None:
    """Strongly correlated sequences (Y = X + noise) should yield TDMI > 0."""
    rng = np.random.default_rng(7)
    x = rng.uniform(0.0, 1.0, 200)
    # Y is close to X — high mutual information
    y = x + rng.normal(0.0, 0.01, 200)
    y = np.clip(y, 0.0, 1.0)

    mi = _histogram_mi(x, y)

    assert mi > 0.05, f"Expected positive MI for correlated sequences, got {mi:.4f}"


@pytest.mark.skipif(not _NUMPY_AVAILABLE, reason="numpy not installed")
def test_tdmi_identical_series_high_mi() -> None:
    """Identical X and Y should yield high MI (near maximum entropy)."""
    rng = np.random.default_rng(99)
    x = rng.uniform(0.0, 1.0, 300)
    y = x.copy()

    mi = _histogram_mi(x, y)

    # For uniform in [0,1], H(X) = ln(bins) / n  — just verify > threshold
    assert mi > 0.1, f"Identical series should have high MI, got {mi:.4f}"


@pytest.mark.skipif(not _NUMPY_AVAILABLE, reason="numpy not installed")
def test_tdmi_returns_float_non_negative() -> None:
    """_histogram_mi always returns a non-negative float."""
    rng = np.random.default_rng(1)
    x = rng.uniform(0.0, 1.0, 50)
    y = rng.uniform(0.0, 1.0, 50)
    result = _histogram_mi(x, y)
    assert isinstance(result, float)
    assert result >= 0.0


# ------------------------------------------------------------------ #
# _collect_pairs tests                                                 #
# ------------------------------------------------------------------ #


def test_collect_pairs_basic() -> None:
    """_collect_pairs should produce paired (t, t+lag) values for each agent."""
    agent_series = {
        "agent_1": [(0, 0.2), (1, 0.3), (2, 0.4), (3, 0.5)],
        "agent_2": [(0, 0.6), (1, 0.7), (2, 0.8)],
    }
    x, y = _collect_pairs(agent_series, lag=1, up_to_round=3)

    # agent_1: rounds 0→1, 1→2, 2→3 = 3 pairs
    # agent_2: rounds 0→1, 1→2 = 2 pairs (round 3 not in series)
    assert len(x) == 5
    assert len(y) == 5


def test_collect_pairs_respects_up_to_round() -> None:
    """Pairs with base round > up_to_round should be excluded."""
    agent_series = {
        "a": [(0, 0.1), (1, 0.2), (5, 0.3), (6, 0.4)],
    }
    x, y = _collect_pairs(agent_series, lag=1, up_to_round=2)
    # Only rounds 0 and 1 are within up_to_round=2; lag-1 pair: (0,0.1)→(1,0.2)
    assert len(x) == 1
    assert x[0] == pytest.approx(0.1)
    assert y[0] == pytest.approx(0.2)


def test_collect_pairs_no_overlap_returns_empty() -> None:
    """When no lagged pair is available (too few rounds), return empty lists."""
    agent_series = {
        "a": [(0, 0.5)],
    }
    x, y = _collect_pairs(agent_series, lag=3, up_to_round=2)
    assert x == []
    assert y == []


# ------------------------------------------------------------------ #
# _build_summary tests                                                 #
# ------------------------------------------------------------------ #


def test_build_summary_empty_results() -> None:
    """Empty results should produce a zero EmergenceMetricsSummary."""
    summary = _build_summary("sess_abc", 10, [], threshold=0.01)

    assert isinstance(summary, EmergenceMetricsSummary)
    assert summary.mean_tdmi == 0.0
    assert summary.max_tdmi == 0.0
    assert summary.n_topics == 0
    assert summary.emergence_detected is False
    assert summary.per_topic == ()


def test_build_summary_detection_above_threshold() -> None:
    """mean_tdmi > threshold should set emergence_detected=True."""
    results = [
        TDMIResult("s", 5, "topic_A", 1, 0.05, 100),
        TDMIResult("s", 5, "topic_A", 3, 0.04, 80),
        TDMIResult("s", 5, "topic_B", 1, 0.06, 90),
    ]
    summary = _build_summary("s", 5, results, threshold=0.01)

    assert summary.emergence_detected is True
    assert summary.mean_tdmi > 0.01
    assert summary.n_topics == 2
    assert summary.max_tdmi == pytest.approx(0.06)


def test_build_summary_detection_below_threshold() -> None:
    """mean_tdmi <= threshold should leave emergence_detected=False."""
    results = [
        TDMIResult("s", 5, "topic_A", 1, 0.005, 50),
    ]
    summary = _build_summary("s", 5, results, threshold=0.01)

    assert summary.emergence_detected is False
    assert summary.mean_tdmi == pytest.approx(0.005)


def test_min_samples_threshold_is_30() -> None:
    """TDMI must require ≥30 paired samples per Kraskov et al. (2004).

    KNN MI estimator (k=5) on n=10 samples is below the reliability threshold.
    """
    assert _MIN_SAMPLES == 30, f"_MIN_SAMPLES should be 30 (KNN MI reliable at n≥30), got {_MIN_SAMPLES}"


def test_build_summary_per_topic_structure() -> None:
    """per_topic should contain one dict per distinct topic."""
    results = [
        TDMIResult("s", 5, "topic_X", 1, 0.02, 100),
        TDMIResult("s", 5, "topic_X", 3, 0.03, 90),
        TDMIResult("s", 5, "topic_Y", 1, 0.01, 80),
    ]
    summary = _build_summary("s", 5, results, threshold=0.01)

    assert len(summary.per_topic) == 2
    topic_names = {t["topic"] for t in summary.per_topic}
    assert topic_names == {"topic_X", "topic_Y"}
    # topic_X has 2 lag entries
    topic_x = next(t for t in summary.per_topic if t["topic"] == "topic_X")
    assert len(topic_x["lags"]) == 2
    assert topic_x["lags"][0]["lag"] == 1
    assert topic_x["lags"][1]["lag"] == 3
