"""Structural break detection for time series using CUSUM and Bai-Perron approach.

Detects unknown multiple structural breaks in historical data, allowing the
forecaster to dynamically truncate the training window or add dummy variables
at break points rather than using hardcoded historical dates.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from backend.app.utils.logger import get_logger

logger = get_logger("structural_break_detector")


# ---------------------------------------------------------------------------
# Frozen result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BreakPoint:
    index: int          # position in the series
    confidence: float   # 0.0-1.0 confidence that this is a real break
    direction: str      # 'up', 'down', or 'level_shift'


@dataclass(frozen=True)
class BreakDetectionResult:
    break_points: tuple[BreakPoint, ...]
    n_breaks: int
    recommended_start_index: int   # truncate training before this index
    method: str                    # 'cusum', 'bai_perron', or 'none'
    has_breaks: bool


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _classify_direction(series: np.ndarray, break_idx: int) -> str:
    """Classify break direction: 'up', 'down', or 'level_shift'.

    Compares the mean level before and after the break index.
    Returns 'level_shift' when the absolute change is large relative to
    pre-break volatility (i.e. regime change rather than trend reversal).
    """
    window = max(4, (break_idx) // 3)
    pre_start = max(0, break_idx - window)
    post_end = min(len(series), break_idx + window)

    pre = series[pre_start:break_idx]
    post = series[break_idx:post_end]

    if len(pre) == 0 or len(post) == 0:
        return "level_shift"

    pre_mean = float(np.mean(pre))
    post_mean = float(np.mean(post))
    pre_std = float(np.std(pre)) if len(pre) > 1 else 0.0

    delta = post_mean - pre_mean

    # Large absolute change relative to pre-break std → level shift
    if pre_std > 0 and abs(delta) > 2.0 * pre_std:
        return "level_shift"

    return "up" if delta > 0 else "down"


def _compute_confidence(series: np.ndarray, break_idx: int) -> float:
    """Estimate break confidence as a ratio of inter-regime variance to total.

    Returns a float in [0.0, 1.0]. Higher values mean more confident break.
    """
    n = len(series)
    if break_idx <= 1 or break_idx >= n - 1:
        return 0.5

    pre = series[:break_idx]
    post = series[break_idx:]

    mean_pre = float(np.mean(pre))
    mean_post = float(np.mean(post))
    mean_total = float(np.mean(series))
    var_total = float(np.var(series))

    if var_total < 1e-12:
        return 0.5

    # Between-group variance as fraction of total variance
    n_pre = len(pre)
    n_post = len(post)
    between_var = (
        n_pre * (mean_pre - mean_total) ** 2
        + n_post * (mean_post - mean_total) ** 2
    ) / n

    confidence = min(1.0, between_var / var_total)
    return round(float(confidence), 4)


def _variance_ratio_breaks(
    series: np.ndarray,
    window: int,
    threshold: float = 3.0,
) -> list[int]:
    """Simple variance-ratio structural break detector (fallback method).

    Slides a window across the series; flags positions where the ratio of
    variance on the right vs left exceeds *threshold* (or its inverse).
    Nearby breaks within window//2 are merged into one.

    Args:
        series: 1-D numpy array of values.
        window: Half-window size for variance computation.
        threshold: Minimum variance ratio to flag a break.

    Returns:
        Sorted list of break indices (merged).
    """
    n = len(series)
    raw_breaks: list[int] = []

    for i in range(window, n - window):
        var_left = float(np.var(series[max(0, i - window):i]))
        var_right = float(np.var(series[i:i + window]))

        if var_left <= 0 and var_right <= 0:
            continue

        if var_left <= 0:
            # Right side has variance but left is flat — potential break
            raw_breaks.append(i)
            continue

        ratio = var_right / var_left if var_left > 0 else threshold + 1.0
        if ratio > threshold or ratio < (1.0 / threshold):
            raw_breaks.append(i)

    # Merge nearby breaks (within window // 2 of each other)
    merged: list[int] = []
    for b in raw_breaks:
        if not merged or b - merged[-1] > window // 2:
            merged.append(b)

    return merged


def _cusum_breaks(series: np.ndarray, alpha: float = 0.05) -> list[int]:
    """CUSUM-based structural break detection using statsmodels.

    Uses recursive OLS residuals (CUSUM of squares) to identify structural
    change points. Returns sorted list of approximate break indices.

    Args:
        series: 1-D numpy array.
        alpha: Significance level for CUSUM boundary (default 0.05).

    Returns:
        List of break indices, possibly empty.
    """
    import statsmodels.api as sm  # noqa: PLC0415
    from statsmodels.stats.diagnostic import recursive_olsresiduals  # noqa: PLC0415

    n = len(series)
    if n < 20:
        return []

    # Use a simple trend regressor: [1, t] as X
    X = sm.add_constant(np.arange(n, dtype=np.float64))
    model = sm.OLS(series, X)
    result = model.fit()

    try:
        rresid, rvar, rreg, recursive_coefs, rmse = recursive_olsresiduals(
            result, skip=5, alpha=alpha, order_by=None,
        )
    except Exception as exc:
        logger.debug("recursive_olsresiduals failed: %s", exc)
        return []

    # CUSUM of squares: identify where cumulative squared residuals
    # deviate significantly from the expected linear path
    resid_arr = np.asarray(rresid, dtype=np.float64)
    cusum_sq = np.cumsum(resid_arr ** 2)
    total_sq = float(cusum_sq[-1]) if cusum_sq[-1] != 0 else 1.0

    # Normalise to [0, 1]
    normalised = cusum_sq / total_sq
    m = len(normalised)
    expected = np.linspace(0.0, 1.0, m)

    # Boundary: ±c where c approximates the 5% critical value
    c = 1.36 / np.sqrt(m)  # asymptotic 5% boundary

    deviations = np.abs(normalised - expected)
    exceed = np.where(deviations > c)[0]

    if len(exceed) == 0:
        return []

    # Cluster exceedances and take the centre of each cluster
    break_indices: list[int] = []
    cluster_start = int(exceed[0])
    cluster_end = int(exceed[0])

    for idx in exceed[1:]:
        if idx - cluster_end <= 3:
            cluster_end = int(idx)
        else:
            centre = (cluster_start + cluster_end) // 2
            # Map back to original series index (recursive OLS skips first few)
            original_idx = centre + 5
            if 2 <= original_idx <= n - 2:
                break_indices.append(original_idx)
            cluster_start = int(idx)
            cluster_end = int(idx)

    # Handle last cluster
    centre = (cluster_start + cluster_end) // 2
    original_idx = centre + 5
    if 2 <= original_idx <= n - 2:
        break_indices.append(original_idx)

    # Deduplicate (sort + merge within 4 positions)
    break_indices.sort()
    merged: list[int] = []
    for b in break_indices:
        if not merged or b - merged[-1] > 4:
            merged.append(b)

    return merged


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_structural_breaks(
    series: Sequence[float],
    min_series_length: int = 20,
    confidence_threshold: float = 0.7,
) -> BreakDetectionResult:
    """Detect structural breaks in a time series.

    Attempts statsmodels CUSUM detection first; falls back to a variance-ratio
    method if statsmodels is unavailable or the series is too short for CUSUM.

    Safe to call on any series — returns a no-break result if the series is
    shorter than *min_series_length*.

    Args:
        series: Sequence of float values (chronological order).
        min_series_length: Minimum length to attempt detection (default 20).
        confidence_threshold: Minimum confidence to include a break point
            in the result. Breaks below this threshold are silently dropped.

    Returns:
        BreakDetectionResult (frozen dataclass) with break points and a
        recommended training start index.
    """
    _no_break = BreakDetectionResult(
        break_points=(),
        n_breaks=0,
        recommended_start_index=0,
        method="none",
        has_breaks=False,
    )

    arr = np.asarray(series, dtype=np.float64)
    n = len(arr)

    if n < min_series_length:
        logger.debug(
            "detect_structural_breaks: series too short (n=%d < %d), returning no-break",
            n, min_series_length,
        )
        return _no_break

    raw_indices: list[int] = []
    method_used = "none"

    # --- Strategy 1: CUSUM via statsmodels ---
    try:
        raw_indices = _cusum_breaks(arr)
        if raw_indices:
            method_used = "cusum"
            logger.debug(
                "detect_structural_breaks: CUSUM found %d candidate(s): %s",
                len(raw_indices), raw_indices,
            )
    except Exception as exc:
        logger.debug("detect_structural_breaks: CUSUM error (%s), falling back", exc)
        raw_indices = []

    # --- Strategy 2: Variance-ratio fallback ---
    if not raw_indices:
        window = max(8, n // 5)
        raw_indices = _variance_ratio_breaks(arr, window=window, threshold=3.0)
        if raw_indices:
            method_used = "bai_perron"
            logger.debug(
                "detect_structural_breaks: variance-ratio found %d candidate(s): %s",
                len(raw_indices), raw_indices,
            )

    if not raw_indices:
        return _no_break

    # --- Build BreakPoint objects ---
    break_points: list[BreakPoint] = []
    for idx in raw_indices:
        confidence = _compute_confidence(arr, idx)
        if confidence < confidence_threshold:
            logger.debug(
                "detect_structural_breaks: dropping break at index=%d (confidence=%.3f < %.3f)",
                idx, confidence, confidence_threshold,
            )
            continue
        direction = _classify_direction(arr, idx)
        break_points.append(BreakPoint(
            index=idx,
            confidence=confidence,
            direction=direction,
        ))

    if not break_points:
        return _no_break

    # --- Recommended start index ---
    # Use the most recent break as the start of the most recent regime.
    # This keeps only post-break data for training, discarding outdated regimes.
    last_break = max(bp.index for bp in break_points)
    recommended_start = last_break  # train from this index forward

    logger.info(
        "detect_structural_breaks: %d break(s) detected via '%s'; "
        "recommended_start_index=%d (series length=%d)",
        len(break_points), method_used, recommended_start, n,
    )

    return BreakDetectionResult(
        break_points=tuple(break_points),
        n_breaks=len(break_points),
        recommended_start_index=recommended_start,
        method=method_used,
        has_breaks=True,
    )
