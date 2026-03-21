"""Statistical validation framework for the MurmuraScope prediction engine.

Provides stationarity testing (ADF), Granger causality analysis,
forecast accuracy metrics (MAPE, RMSE, Theil's U), and a full
validation report aggregating results from DB-sourced macro + sentiment data.

Design notes:
  - All result types are frozen dataclasses (immutable per project style).
  - ``run_full_validation`` is async (DB access via ``get_db``).
  - Edge cases (short series, all zeros, NaN/inf) are handled gracefully.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from statsmodels.tsa.stattools import adfuller, grangercausalitytests

from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("validation_suite")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MIN_SERIES_LENGTH = 8
_GRANGER_SIGNIFICANCE = 0.10
_ADF_SIGNIFICANCE = 0.05

# Macro indicators loaded from hk_data_snapshots (category, metric) pairs.
_MACRO_INDICATORS: tuple[tuple[str, str, str], ...] = (
    ("ccl_index", "property", "ccl_index"),
    ("unemployment_rate", "employment", "unemployment_rate"),
    ("gdp_growth", "gdp", "gdp_growth_rate"),
    ("cpi_yoy", "price_index", "cpi_yoy"),
    ("consumer_confidence", "sentiment", "consumer_confidence"),
    ("hsi_level", "finance", "hsi_level"),
    ("hibor_1m", "interest_rate", "hibor_1m"),
    ("prime_rate", "interest_rate", "prime_rate"),
    ("net_migration", "migration", "net_migration"),
    ("retail_sales_index", "retail", "retail_sales_index"),
    ("tourist_arrivals", "tourism", "tourist_arrivals"),
)

# Sentiment columns from social_sentiment (used as Granger "cause").
_SENTIMENT_COLUMNS: tuple[str, ...] = (
    "positive_ratio",
    "negative_ratio",
    "neutral_ratio",
)


# ---------------------------------------------------------------------------
# Result dataclasses (frozen / immutable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StationarityResult:
    """ADF stationarity test result for a single indicator series."""

    metric: str
    adf_statistic: float
    p_value: float
    is_stationary: bool
    lags_used: int
    differencing_applied: bool


@dataclass(frozen=True)
class GrangerResult:
    """Granger causality test result for a cause -> effect pair."""

    cause_metric: str
    effect_metric: str
    max_lag: int
    best_lag: int
    p_value: float
    is_significant: bool


@dataclass(frozen=True)
class ForecastAccuracy:
    """Forecast accuracy metrics for a single indicator."""

    metric: str
    mape: float  # MAPE percentage [0-100] for backtest reports (differs from ForecastResult.fit_quality which is [0-1])
    rmse: float
    theils_u: float
    n_observations: int
    data_quality: str


@dataclass(frozen=True)
class ARCHTestResult:
    """ARCH (Autoregressive Conditional Heteroscedasticity) LM test result.

    Tests whether residuals exhibit time-varying volatility (ARCH effects).
    Uses Engle's LM test: regress squared residuals on their own lags,
    LM = n * R^2 ~ chi-squared(p).
    """

    metric: str
    lm_statistic: float
    p_value: float
    has_arch_effects: bool
    lags_tested: int


@dataclass(frozen=True)
class ValidationReport:
    """Aggregated validation report across all indicators."""

    stationarity_results: tuple[StationarityResult, ...]
    granger_results: tuple[GrangerResult, ...]
    forecast_accuracy: tuple[ForecastAccuracy, ...]
    arch_results: tuple[ARCHTestResult, ...]
    overall_score: float
    warnings: tuple[str, ...]
    data_sources_used: dict[str, Any]


# ---------------------------------------------------------------------------
# Pure helper: sanitise a numeric series
# ---------------------------------------------------------------------------


def _sanitise(series: list[float]) -> list[float]:
    """Remove NaN and inf values from a series."""
    return [v for v in series if math.isfinite(v)]


def _benjamini_hochberg(p_values: list[float], alpha: float = 0.05) -> list[bool]:
    """Benjamini-Hochberg FDR correction. Returns list of reject booleans.

    More powerful than Bonferroni (which uses alpha/m threshold) because it
    controls False Discovery Rate rather than Family-Wise Error Rate.

    Algorithm:
      1. Sort p-values ascending: p_(1) <= p_(2) <= ... <= p_(m)
      2. Find largest k where p_(k) <= (k/m) * alpha
      3. Reject all H_0 for i <= k

    Args:
        p_values: List of p-values to correct.
        alpha: Desired FDR level (default 0.05).

    Returns:
        List of booleans (True = reject null hypothesis).
    """
    m = len(p_values)
    if m == 0:
        return []
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    reject = [False] * m
    last_reject = -1
    for rank, (orig_idx, p) in enumerate(indexed, 1):
        if p <= (rank / m) * alpha:
            last_reject = rank
    for rank, (orig_idx, p) in enumerate(indexed, 1):
        if rank <= last_reject:
            reject[orig_idx] = True
    return reject


def _is_constant(series: list[float]) -> bool:
    """Return True if the series has zero variance (all identical values)."""
    if not series:
        return True
    return all(v == series[0] for v in series)


# ---------------------------------------------------------------------------
# 1. Stationarity validation (ADF)
# ---------------------------------------------------------------------------


def validate_stationarity(
    series: list[float],
    metric_name: str,
) -> StationarityResult:
    """Run the Augmented Dickey-Fuller test on *series*.

    If the raw series is non-stationary (p > 0.05), a first-differenced
    version is tested and the result reflects the differenced series with
    ``differencing_applied=True``.

    Returns a frozen ``StationarityResult``.
    """
    clean = _sanitise(series)

    if len(clean) < _MIN_SERIES_LENGTH or _is_constant(clean):
        return StationarityResult(
            metric=metric_name,
            adf_statistic=0.0,
            p_value=1.0,
            is_stationary=False,
            lags_used=0,
            differencing_applied=False,
        )

    arr = np.array(clean, dtype=np.float64)
    result = adfuller(arr, autolag="AIC")
    adf_stat: float = float(result[0])
    p_val: float = float(result[1])
    lags: int = int(result[2])

    if p_val <= _ADF_SIGNIFICANCE:
        return StationarityResult(
            metric=metric_name,
            adf_statistic=adf_stat,
            p_value=p_val,
            is_stationary=True,
            lags_used=lags,
            differencing_applied=False,
        )

    # Try first differencing
    diffed = np.diff(arr)
    if len(diffed) < _MIN_SERIES_LENGTH or np.std(diffed) == 0.0:
        return StationarityResult(
            metric=metric_name,
            adf_statistic=adf_stat,
            p_value=p_val,
            is_stationary=False,
            lags_used=lags,
            differencing_applied=False,
        )

    diff_result = adfuller(diffed, autolag="AIC")
    return StationarityResult(
        metric=metric_name,
        adf_statistic=float(diff_result[0]),
        p_value=float(diff_result[1]),
        is_stationary=float(diff_result[1]) <= _ADF_SIGNIFICANCE,
        lags_used=int(diff_result[2]),
        differencing_applied=True,
    )


# ---------------------------------------------------------------------------
# 2. Granger causality validation
# ---------------------------------------------------------------------------


def validate_granger_causality(
    cause: list[float],
    effect: list[float],
    cause_name: str,
    effect_name: str,
    max_lag: int = 4,
    cause_periods: list[str] | None = None,
    effect_periods: list[str] | None = None,
) -> GrangerResult:
    """Test whether *cause* Granger-causes *effect* up to *max_lag* lags.

    Uses the minimum p-value across all tested lags (ssr_ftest).
    Significant if best p < 0.10.

    Phase 6B: when *cause_periods* and *effect_periods* are provided, only
    periods present in BOTH series are used (temporal alignment).
    """
    clean_cause = _sanitise(cause)
    clean_effect = _sanitise(effect)

    # Phase 6B: temporal alignment — only use periods present in BOTH series.
    if (
        cause_periods is not None
        and effect_periods is not None
        and len(cause_periods) == len(clean_cause)
        and len(effect_periods) == len(clean_effect)
    ):
        # Build lookup for effect series by period label
        effect_lookup: dict[str, float] = dict(zip(effect_periods, clean_effect))
        aligned_cause: list[float] = []
        aligned_effect: list[float] = []
        for period, val in zip(cause_periods, clean_cause):
            if period in effect_lookup:
                aligned_cause.append(val)
                aligned_effect.append(effect_lookup[period])
        clean_cause = aligned_cause
        clean_effect = aligned_effect

    min_len = min(len(clean_cause), len(clean_effect))

    if min_len < _MIN_SERIES_LENGTH:
        return GrangerResult(
            cause_metric=cause_name,
            effect_metric=effect_name,
            max_lag=max_lag,
            best_lag=0,
            p_value=1.0,
            is_significant=False,
        )

    # Truncate to equal length
    c = clean_cause[:min_len]
    e = clean_effect[:min_len]

    if _is_constant(c) or _is_constant(e):
        return GrangerResult(
            cause_metric=cause_name,
            effect_metric=effect_name,
            max_lag=max_lag,
            best_lag=0,
            p_value=1.0,
            is_significant=False,
        )

    # grangercausalitytests expects a 2D array: columns [effect, cause]
    data = np.column_stack([e, c])

    # Clamp max_lag to avoid exceeding data length (need >= 3*max_lag observations)
    effective_max_lag = min(max_lag, max(1, min_len // 3))

    try:
        results = grangercausalitytests(data, maxlag=effective_max_lag, verbose=False)
    except Exception as exc:
        logger.warning(
            "Granger test failed for %s -> %s: %s", cause_name, effect_name, exc
        )
        return GrangerResult(
            cause_metric=cause_name,
            effect_metric=effect_name,
            max_lag=max_lag,
            best_lag=0,
            p_value=1.0,
            is_significant=False,
        )

    # Find the lag with the lowest p-value (ssr_ftest)
    best_lag = 1
    best_p = 1.0
    for lag, test_dict in results.items():
        p = float(test_dict[0]["ssr_ftest"][1])
        if p < best_p:
            best_p = p
            best_lag = int(lag)

    return GrangerResult(
        cause_metric=cause_name,
        effect_metric=effect_name,
        max_lag=max_lag,
        best_lag=best_lag,
        p_value=best_p,
        is_significant=best_p < _GRANGER_SIGNIFICANCE,
    )


# ---------------------------------------------------------------------------
# 3. Forecast accuracy validation
# ---------------------------------------------------------------------------


def validate_forecast_accuracy(
    actuals: list[float],
    predictions: list[float],
    metric_name: str,
) -> ForecastAccuracy:
    """Compute MAPE, RMSE, and Theil's U for *actuals* vs *predictions*.

    Theil's U compares the forecast to a naive random-walk baseline.
    Values < 1.0 indicate the model outperforms naive.
    """
    n = min(len(actuals), len(predictions))

    if n == 0:
        return ForecastAccuracy(
            metric=metric_name,
            mape=float("inf"),
            rmse=float("inf"),
            theils_u=float("inf"),
            n_observations=0,
            data_quality="insufficient",
        )

    a = np.array(actuals[:n], dtype=np.float64)
    p = np.array(predictions[:n], dtype=np.float64)

    # NOTE: ForecastAccuracy.mape is intentionally kept in 0-100 percentage scale
    # for backtest report display. This differs from ForecastResult.fit_quality["mape"]
    # which is 0-1 fraction (used internally by TimeSeriesForecaster).
    # MAPE — skip zeros in actuals to avoid division by zero
    nonzero_mask = a != 0.0
    if nonzero_mask.any():
        mape = float(np.mean(np.abs((a[nonzero_mask] - p[nonzero_mask]) / a[nonzero_mask])) * 100.0)
    else:
        mape = float("inf")

    # RMSE
    rmse = float(np.sqrt(np.mean((a - p) ** 2)))

    # Theil's U: forecast error / naive error (random walk = previous actual)
    if n >= 2:
        forecast_errors = a[1:] - p[1:]
        naive_errors = a[1:] - a[:-1]
        fe_rms = float(np.sqrt(np.mean(forecast_errors**2)))
        ne_rms = float(np.sqrt(np.mean(naive_errors**2)))
        theils_u = fe_rms / ne_rms if ne_rms > 1e-12 else float("inf")
    else:
        theils_u = float("inf")

    # Data quality assessment
    if n < _MIN_SERIES_LENGTH:
        quality = "insufficient"
    elif n < 20:
        quality = "limited"
    else:
        quality = "adequate"

    return ForecastAccuracy(
        metric=metric_name,
        mape=mape,
        rmse=rmse,
        theils_u=theils_u,
        n_observations=n,
        data_quality=quality,
    )


# ---------------------------------------------------------------------------
# 3b. Structural break detection (Bai-Perron sequential Chow test)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StructuralBreak:
    """A detected structural break point with test statistics."""

    break_point: str
    break_index: int
    f_statistic: float
    p_value: float
    bic_improvement: float


def _ols_rss(y: np.ndarray) -> float:
    """Fit OLS trend (intercept + linear trend) and return RSS."""
    n = len(y)
    if n < 2:
        return 0.0
    x_mat = np.column_stack([np.ones(n), np.arange(n, dtype=np.float64)])
    betas, _, _, _ = np.linalg.lstsq(x_mat, y, rcond=None)
    residuals = y - x_mat @ betas
    return float(np.sum(residuals ** 2))


def _bic(rss: float, n: int, k: int) -> float:
    """Compute Bayesian Information Criterion.

    BIC = n * ln(RSS / n) + k * ln(n).
    Returns +inf when RSS is near zero (perfect fit edge case).
    """
    if n <= 0 or rss <= 1e-15:
        return float("-inf")
    return n * math.log(rss / n) + k * math.log(n)


def detect_structural_breaks(
    series: list[float],
    periods: list[str] | None = None,
    max_breaks: int = 5,
    min_segment: int = 8,
) -> tuple[StructuralBreak, ...]:
    """Sequential Chow test with BIC penalty (Bai-Perron style).

    Algorithm:
      1. Fit OLS on full sample, compute BIC_full.
      2. For each candidate split point (min_segment from edges):
         - Fit OLS on left + right subsegments.
         - Compute Chow F-statistic.
         - Compute BIC_split = BIC_left + BIC_right.
      3. Pick split with highest F-stat where BIC_split < BIC_full.
      4. If found, record break and recurse on each subsegment.
      5. Stop when max_breaks reached or no improving split found.

    Args:
        series: Numeric time series values.
        periods: Period labels aligned with *series* (e.g. ``"2019-Q3"``).
        max_breaks: Maximum number of breaks to detect (default 5).
        min_segment: Minimum observations per segment (default 8).

    Returns:
        Tuple of frozen :class:`StructuralBreak` instances sorted by index.
    """
    from scipy import stats as scipy_stats  # noqa: PLC0415

    clean = _sanitise(series)
    if len(clean) < 2 * min_segment:
        return ()

    y_full = np.array(clean, dtype=np.float64)

    def _find_best_break(
        y: np.ndarray,
        offset: int,
    ) -> StructuralBreak | None:
        """Find the single best break within segment *y* starting at *offset*."""
        n = len(y)
        if n < 2 * min_segment:
            return None

        k = 2  # parameters per sub-model (intercept + trend)
        rss_full = _ols_rss(y)
        bic_full = _bic(rss_full, n, k)

        best: StructuralBreak | None = None
        best_f = 0.0

        for idx in range(min_segment, n - min_segment + 1):
            y_left = y[:idx]
            y_right = y[idx:]

            rss_left = _ols_rss(y_left)
            rss_right = _ols_rss(y_right)
            rss_split = rss_left + rss_right

            bic_left = _bic(rss_left, len(y_left), k)
            bic_right = _bic(rss_right, len(y_right), k)
            bic_split = bic_left + bic_right
            bic_improvement = bic_full - bic_split

            if bic_improvement <= 0:
                continue

            denominator = rss_split / (n - 2 * k)
            if denominator < 1e-15:
                continue

            f_stat = ((rss_full - rss_split) / k) / denominator
            p_value = 1.0 - float(scipy_stats.f.cdf(f_stat, k, n - 2 * k))

            if f_stat > best_f and p_value < 0.05:
                global_idx = offset + idx
                period_label = (
                    periods[global_idx]
                    if periods is not None and global_idx < len(periods)
                    else str(global_idx)
                )
                best = StructuralBreak(
                    break_point=period_label,
                    break_index=global_idx,
                    f_statistic=round(f_stat, 4),
                    p_value=round(p_value, 6),
                    bic_improvement=round(bic_improvement, 4),
                )
                best_f = f_stat

        return best

    # Recursive detection
    breaks: list[StructuralBreak] = []

    def _recurse(y: np.ndarray, offset: int) -> None:
        if len(breaks) >= max_breaks:
            return
        brk = _find_best_break(y, offset)
        if brk is None:
            return
        breaks.append(brk)

        # Recurse on left subsegment
        local_idx = brk.break_index - offset
        if local_idx >= 2 * min_segment and len(breaks) < max_breaks:
            _recurse(y[:local_idx], offset)

        # Recurse on right subsegment
        right_len = len(y) - local_idx
        if right_len >= 2 * min_segment and len(breaks) < max_breaks:
            _recurse(y[local_idx:], offset + local_idx)

    _recurse(y_full, 0)

    return tuple(sorted(breaks, key=lambda b: b.break_index))


def validate_structural_breaks(
    series: list[float],
    periods: list[str] | None = None,
    candidates: list[str] | None = None,
    max_breaks: int = 5,
    min_segment: int = 8,
) -> list[dict]:
    """Backward-compatible wrapper around :func:`detect_structural_breaks`.

    If *candidates* is provided, results are filtered to only include breaks
    whose period label matches one of the candidates.

    Returns:
        List of dicts with keys ``break_point``, ``f_statistic``, ``p_value``.
    """
    breaks = detect_structural_breaks(
        series=series,
        periods=periods,
        max_breaks=max_breaks,
        min_segment=min_segment,
    )

    if candidates is not None:
        breaks = tuple(b for b in breaks if b.break_point in candidates)

    return [
        {
            "break_point": b.break_point,
            "f_statistic": b.f_statistic,
            "p_value": b.p_value,
        }
        for b in breaks
    ]


# ---------------------------------------------------------------------------
# 3c. ARCH / GARCH residual heteroscedasticity test
# ---------------------------------------------------------------------------


def validate_arch_effects(
    residuals: list[float],
    metric_name: str,
    lags: int = 4,
) -> ARCHTestResult:
    """Run Engle's ARCH LM test on *residuals* to detect heteroscedasticity.

    Manual implementation:
      1. Compute squared residuals e^2.
      2. Regress e^2_t on (1, e^2_{t-1}, ..., e^2_{t-p}).
      3. LM = n * R^2 ~ chi-squared(p).
      4. ARCH effects present if p-value < 0.05.

    Args:
        residuals: Forecast residuals (actual - predicted).
        metric_name: Label for the series.
        lags: Number of lags to test (default 4).

    Returns:
        Frozen ``ARCHTestResult``.
    """
    from scipy.stats import chi2  # noqa: PLC0415

    clean = _sanitise(residuals)
    lags = max(1, lags)

    if len(clean) < lags + _MIN_SERIES_LENGTH:
        return ARCHTestResult(
            metric=metric_name,
            lm_statistic=0.0,
            p_value=1.0,
            has_arch_effects=False,
            lags_tested=lags,
        )

    e = np.array(clean, dtype=np.float64)
    e2 = e ** 2
    n = len(e2)

    # Build lagged regressor matrix [1, e2_{t-1}, ..., e2_{t-p}]
    y = e2[lags:]
    n_obs = len(y)
    x_cols = [np.ones(n_obs)]
    for lag in range(1, lags + 1):
        x_cols.append(e2[lags - lag: n - lag])
    x_mat = np.column_stack(x_cols)

    # OLS: beta = (X'X)^{-1} X'y
    try:
        from numpy.linalg import lstsq  # noqa: PLC0415

        beta = lstsq(x_mat, y, rcond=None)[0]
        y_hat = x_mat @ beta
        ss_res = float(np.sum((y - y_hat) ** 2))
        ss_tot = float(np.sum((y - np.mean(y)) ** 2))
        r_squared = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
        r_squared = max(0.0, min(r_squared, 1.0))
    except Exception:
        return ARCHTestResult(
            metric=metric_name,
            lm_statistic=0.0,
            p_value=1.0,
            has_arch_effects=False,
            lags_tested=lags,
        )

    lm_stat = float(n_obs) * r_squared
    p_value = 1.0 - float(chi2.cdf(lm_stat, lags))

    return ARCHTestResult(
        metric=metric_name,
        lm_statistic=round(lm_stat, 6),
        p_value=round(p_value, 6),
        has_arch_effects=p_value < _ADF_SIGNIFICANCE,
        lags_tested=lags,
    )


# ---------------------------------------------------------------------------
# 4. Full validation pipeline (async, DB access)
# ---------------------------------------------------------------------------


async def _load_macro_series(db: Any) -> dict[str, list[float]]:
    """Load macro indicator time series from hk_data_snapshots."""
    series: dict[str, list[float]] = {}

    for label, category, metric in _MACRO_INDICATORS:
        try:
            cursor = await db.execute(
                "SELECT value FROM hk_data_snapshots "
                "WHERE category = ? AND metric = ? "
                "ORDER BY period ASC",
                (category, metric),
            )
            rows = await cursor.fetchall()
            values = [float(r[0]) for r in rows if r[0] is not None]
            if values:
                series[label] = values
        except Exception as exc:
            logger.warning("Failed to load macro series %s: %s", label, exc)

    return series


async def _load_sentiment_series(db: Any) -> dict[str, list[float]]:
    """Load sentiment ratio time series from social_sentiment."""
    series: dict[str, list[float]] = {}
    try:
        cursor = await db.execute(
            "SELECT positive_ratio, negative_ratio, neutral_ratio "
            "FROM social_sentiment "
            "ORDER BY period ASC"
        )
        rows = await cursor.fetchall()
        for col_idx, col_name in enumerate(_SENTIMENT_COLUMNS):
            values = [float(r[col_idx]) for r in rows if r[col_idx] is not None]
            if values:
                series[col_name] = values
    except Exception as exc:
        logger.warning("Failed to load sentiment series: %s", exc)

    return series


async def run_full_validation(db: Any) -> ValidationReport:
    """Run the complete statistical validation suite against the DB.

    Loads macro + sentiment series, then:
      1. Stationarity (ADF) on all macro indicators.
      2. Granger causality: each sentiment column -> each macro indicator.
      3. Forecast accuracy: basic in-sample fit check per indicator.
      4. Overall score: weighted combination of results.
    """
    warnings: list[str] = []

    macro = await _load_macro_series(db)
    sentiment = await _load_sentiment_series(db)

    data_sources: dict[str, Any] = {
        "macro_indicators_loaded": len(macro),
        "sentiment_columns_loaded": len(sentiment),
        "macro_keys": sorted(macro.keys()),
        "sentiment_keys": sorted(sentiment.keys()),
    }

    # --- 1. Stationarity ---
    stationarity: list[StationarityResult] = []
    for label in macro:
        s = macro[label]
        if len(s) < _MIN_SERIES_LENGTH:
            warnings.append(f"Stationarity skipped for {label}: only {len(s)} points (<{_MIN_SERIES_LENGTH})")
            continue
        if _is_constant(s):
            warnings.append(f"Stationarity skipped for {label}: constant series (all zeros or identical)")
            continue
        stationarity.append(validate_stationarity(s, label))

    # --- 2. Granger causality ---
    granger: list[GrangerResult] = []
    for sent_col in sentiment:
        for macro_label in macro:
            cause_series = sentiment[sent_col]
            effect_series = macro[macro_label]
            min_len = min(len(cause_series), len(effect_series))
            if min_len < _MIN_SERIES_LENGTH:
                warnings.append(
                    f"Granger skipped for {sent_col} -> {macro_label}: "
                    f"only {min_len} aligned points (<{_MIN_SERIES_LENGTH})"
                )
                continue
            granger.append(
                validate_granger_causality(
                    cause_series, effect_series, sent_col, macro_label
                )
            )

    # --- 3. Forecast accuracy (in-sample split: last 25% as holdout) ---
    accuracy: list[ForecastAccuracy] = []
    for label, s in macro.items():
        if len(s) < _MIN_SERIES_LENGTH:
            warnings.append(f"Accuracy skipped for {label}: only {len(s)} points")
            continue
        holdout_size = max(2, len(s) // 4)
        train = s[:-holdout_size]
        holdout = s[-holdout_size:]
        # Naive forecast = last training value repeated
        naive_pred = [train[-1]] * holdout_size
        accuracy.append(validate_forecast_accuracy(holdout, naive_pred, label))

    # --- 3b. ARCH test on naive forecast residuals ---
    arch: list[ARCHTestResult] = []
    for label, s in macro.items():
        if len(s) < _MIN_SERIES_LENGTH + 4:
            warnings.append(f"ARCH skipped for {label}: only {len(s)} points")
            continue
        # Naive residuals: actual[t] - actual[t-1]
        residuals = [s[i] - s[i - 1] for i in range(1, len(s))]
        arch.append(validate_arch_effects(residuals, label))

    # --- 4. Overall score ---
    score = _compute_overall_score(stationarity, granger, accuracy)

    return ValidationReport(
        stationarity_results=tuple(stationarity),
        granger_results=tuple(granger),
        forecast_accuracy=tuple(accuracy),
        arch_results=tuple(arch),
        overall_score=score,
        warnings=tuple(warnings),
        data_sources_used=data_sources,
    )


def _compute_overall_score(
    stationarity: list[StationarityResult],
    granger: list[GrangerResult],
    accuracy: list[ForecastAccuracy],
) -> float:
    """Compute a 0-1 overall validation score.

    Weights:
      - 30%: fraction of indicators that are stationary (or become so after differencing)
      - 30%: fraction of Granger tests that are significant
      - 40%: data adequacy ratio (adequate=1.0, limited=0.5, insufficient=0.0)
    """
    # Stationarity component
    if stationarity:
        stat_frac = sum(1 for r in stationarity if r.is_stationary) / len(stationarity)
    else:
        stat_frac = 0.0

    # Granger component
    if granger:
        granger_frac = sum(1 for r in granger if r.is_significant) / len(granger)
    else:
        granger_frac = 0.0

    # Data adequacy component
    quality_map = {"adequate": 1.0, "limited": 0.5, "insufficient": 0.0}
    if accuracy:
        adequacy = sum(quality_map.get(r.data_quality, 0.0) for r in accuracy) / len(accuracy)
    else:
        adequacy = 0.0

    return round(0.30 * stat_frac + 0.30 * granger_frac + 0.40 * adequacy, 4)


# ---------------------------------------------------------------------------
# 5. Confidence synthesis — multi-signal confidence score
# ---------------------------------------------------------------------------

from backend.app.models.validation import ConfidenceResult  # noqa: E402


def synthesize_confidence(
    theils_u: float,
    mc_p25: float,
    mc_p75: float,
    mc_median: float,
    agent_consensus: float,
    sensitivity: float = 0.5,
) -> ConfidenceResult:
    """Synthesise a multi-signal confidence score for a forecast.

    Args:
        theils_u: Theil's U statistic from backtest (< 1 means model beats naive).
        mc_p25: 25th-percentile Monte Carlo outcome.
        mc_p75: 75th-percentile Monte Carlo outcome.
        mc_median: Median Monte Carlo outcome (used to normalise band width).
        agent_consensus: Fraction of agents arriving at the same directional conclusion.
        sensitivity: Normalised sensitivity score (0 = insensitive, 1 = very sensitive).

    Returns:
        Frozen :class:`ConfidenceResult` with composite score and explanation.
    """
    backtest_vs_naive = 1.0 - theils_u
    mc_band_width = (mc_p75 - mc_p25) / mc_median if mc_median != 0 else 1.0

    score = 0.0
    score += 0.35 * max(0, min(1, backtest_vs_naive / 0.3))
    score += 0.30 * max(0, min(1, agent_consensus))
    score += 0.20 * max(0, min(1, 1.0 - mc_band_width))
    score += 0.15 * max(0, min(1, 1.0 - sensitivity))

    if score >= 0.7:
        level = "high"
    elif score >= 0.4:
        level = "medium"
    else:
        level = "low"

    return ConfidenceResult(
        backtest_vs_naive=round(backtest_vs_naive, 4),
        mc_band_width=round(mc_band_width, 4),
        agent_consensus=round(agent_consensus, 4),
        sensitivity_score=round(sensitivity, 4),
        confidence_level=level,
        confidence_score=round(score, 4),
        explanation_zh=_generate_explanation(level, backtest_vs_naive, agent_consensus, mc_band_width),
    )


def _generate_explanation(
    level: str,
    backtest: float,
    consensus: float,
    band: float,
) -> str:
    """Generate a Cantonese explanation string for a confidence result."""
    parts = []
    if backtest > 0:
        parts.append(f"回測驗證顯示本模型比趨勢外推準確 {abs(backtest) * 100:.0f}%")
    else:
        parts.append("回測顯示模型表現未及簡單趨勢外推")
    parts.append(f"{consensus * 100:.0f}% 嘅模擬市民獨立得出相似結論")
    if band < 0.3:
        parts.append("蒙特卡羅模擬嘅預測範圍相對集中")
    else:
        parts.append("蒙特卡羅模擬嘅預測範圍較闊，結果存在較大不確定性")
    return "。".join(parts) + "。"
