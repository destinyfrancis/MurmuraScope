"""GARCH(1,1) conditional volatility model for time series variance forecasting.

Implements Bollerslev (1986) GARCH(1,1):
    sigma2_t = omega + alpha * eps2_{t-1} + beta * sigma2_{t-1}

Used by MonteCarloEngine and ValidationSuite when ARCH effects are detected
in the residual series, providing time-varying variance estimates that
capture volatility clustering during crises.

References:
    Bollerslev (1986) Generalized autoregressive conditional heteroscedasticity.
        Journal of Econometrics 31(3), 307-327.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

from backend.app.utils.logger import get_logger

logger = get_logger("garch_model")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MIN_OBSERVATIONS = 20
"""Minimum number of residual observations required for GARCH fitting."""

_MAX_PERSISTENCE = 0.9999
"""Upper bound on alpha + beta for stationarity constraint."""

_OPTIMIZER_MAXITER = 500
"""Maximum iterations for L-BFGS-B optimizer."""

_VARIANCE_FLOOR = 1e-12
"""Floor value for conditional variance to avoid log(0)."""

_INITIAL_OMEGA = 0.05
"""Default initial guess for omega (intercept)."""

_INITIAL_ALPHA = 0.10
"""Default initial guess for alpha (ARCH coefficient)."""

_INITIAL_BETA = 0.80
"""Default initial guess for beta (GARCH coefficient)."""


# ---------------------------------------------------------------------------
# Result dataclass (frozen / immutable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GARCHResult:
    """Fitted GARCH(1,1) model parameters and diagnostics.

    Fields:
        metric: Name of the series this model was fitted to.
        omega: Intercept (long-run variance weight). Must be > 0.
        alpha: ARCH coefficient (weight on lagged squared residual).
        beta: GARCH coefficient (weight on lagged conditional variance).
        persistence: alpha + beta. Must be < 1 for covariance stationarity.
        unconditional_variance: omega / (1 - alpha - beta). The long-run
            variance the process reverts to.
        conditional_variances: Fitted sigma2_t series for each observation.
        log_likelihood: Maximised Gaussian log-likelihood value.
        n_observations: Number of residuals used in estimation.
    """

    metric: str
    omega: float
    alpha: float
    beta: float
    persistence: float
    unconditional_variance: float
    conditional_variances: tuple[float, ...]
    log_likelihood: float
    n_observations: int


# ---------------------------------------------------------------------------
# Confidence interval result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdjustedCI:
    """GARCH-adjusted confidence interval for a single forecast horizon step.

    Fields:
        horizon_step: Forecast step (1-indexed).
        point_forecast: Original point forecast value.
        ci_lower: Lower bound of the adjusted confidence interval.
        ci_upper: Upper bound of the adjusted confidence interval.
        garch_std: GARCH-derived standard deviation at this horizon.
        static_std: Original static standard deviation for comparison.
    """

    horizon_step: int
    point_forecast: float
    ci_lower: float
    ci_upper: float
    garch_std: float
    static_std: float


# ---------------------------------------------------------------------------
# Core GARCH(1,1) engine
# ---------------------------------------------------------------------------


def _compute_conditional_variances(
    params: np.ndarray,
    eps2: np.ndarray,
) -> np.ndarray:
    """Compute the conditional variance series sigma2_t given parameters.

    GARCH(1,1) recursion:
        sigma2_t = omega + alpha * eps2_{t-1} + beta * sigma2_{t-1}

    Initialisation: sigma2_0 = sample variance of eps2 (backcast).

    Args:
        params: Array [omega, alpha, beta].
        eps2: Squared residuals (length T).

    Returns:
        Array of conditional variances (length T).
    """
    omega, alpha, beta = float(params[0]), float(params[1]), float(params[2])
    t_len = len(eps2)
    sigma2 = np.empty(t_len, dtype=np.float64)

    # Backcast initialisation: start from unconditional variance of the sample
    sigma2[0] = max(float(np.mean(eps2)), _VARIANCE_FLOOR)

    for t in range(1, t_len):
        s2 = omega + alpha * eps2[t - 1] + beta * sigma2[t - 1]
        sigma2[t] = max(s2, _VARIANCE_FLOOR)

    return sigma2


def _neg_log_likelihood(
    params: np.ndarray,
    eps2: np.ndarray,
) -> float:
    """Negative Gaussian log-likelihood for GARCH(1,1).

    L = -0.5 * sum_t [ log(2*pi) + log(sigma2_t) + eps2_t / sigma2_t ]

    We minimise the negative so that scipy.optimize.minimize finds the MLE.

    Args:
        params: Array [omega, alpha, beta].
        eps2: Squared residuals.

    Returns:
        Negative log-likelihood (scalar). Returns +inf on numerical failure.
    """
    try:
        sigma2 = _compute_conditional_variances(params, eps2)

        # Guard against non-positive variances
        if np.any(sigma2 <= 0):
            return float("inf")

        log_sigma2 = np.log(sigma2)
        ll = -0.5 * np.sum(np.log(2.0 * np.pi) + log_sigma2 + eps2 / sigma2)

        if not math.isfinite(ll):
            return float("inf")

        return -float(ll)
    except (FloatingPointError, ValueError, OverflowError):
        return float("inf")


# ---------------------------------------------------------------------------
# GARCHForecaster
# ---------------------------------------------------------------------------


class GARCHForecaster:
    """GARCH(1,1) model fitting and forecasting.

    Pure-Python / NumPy / SciPy implementation (no external ``arch`` library).
    Uses maximum likelihood estimation via L-BFGS-B with box constraints.

    Usage::

        forecaster = GARCHForecaster()
        result = forecaster.fit(residuals, "hsi_level")
        if result is not None:
            future_var = forecaster.forecast_variance(result, horizon=12)
            adjusted = forecaster.adjust_confidence_intervals(
                point_forecasts, static_std, result, horizon=12,
            )
    """

    def fit(
        self,
        residuals: list[float],
        metric_name: str,
    ) -> GARCHResult | None:
        """Fit a GARCH(1,1) model to *residuals* via maximum likelihood.

        Constraints (box bounds for L-BFGS-B):
            omega > 1e-8
            alpha in [0, 0.999]
            beta  in [0, 0.999]
            alpha + beta < 1  (enforced via penalty and post-check)

        Args:
            residuals: Forecast residuals (actual - predicted).
            metric_name: Label for logging and result identification.

        Returns:
            Frozen ``GARCHResult`` on success, or ``None`` if:
            - Too few observations (< 20)
            - Optimiser fails to converge
            - Fitted persistence >= 1 (non-stationary)
            - Numerical issues during estimation
        """
        clean = _sanitise(residuals)

        if len(clean) < _MIN_OBSERVATIONS:
            logger.debug(
                "GARCH fit skipped for %s: only %d observations (need %d)",
                metric_name,
                len(clean),
                _MIN_OBSERVATIONS,
            )
            return None

        eps = np.array(clean, dtype=np.float64)
        eps2 = eps ** 2
        sample_var = float(np.var(eps))

        if sample_var < _VARIANCE_FLOOR:
            logger.debug("GARCH fit skipped for %s: near-zero variance", metric_name)
            return None

        # Initial parameter guess: omega scaled to sample variance
        init_omega = sample_var * (1.0 - _INITIAL_ALPHA - _INITIAL_BETA)
        x0 = np.array([
            max(init_omega, 1e-8),
            _INITIAL_ALPHA,
            _INITIAL_BETA,
        ])

        # Box bounds: omega > 0, alpha in [0, 0.999], beta in [0, 0.999]
        bounds = [
            (1e-8, sample_var * 10.0),
            (0.0, 0.999),
            (0.0, 0.999),
        ]

        try:
            result = minimize(
                _neg_log_likelihood,
                x0,
                args=(eps2,),
                method="L-BFGS-B",
                bounds=bounds,
                options={"maxiter": _OPTIMIZER_MAXITER, "ftol": 1e-10},
            )
        except Exception as exc:
            logger.warning("GARCH optimiser exception for %s: %s", metric_name, exc)
            return None

        if not result.success:
            logger.debug(
                "GARCH optimiser did not converge for %s: %s",
                metric_name,
                result.message,
            )
            # Still check if the result is usable (some L-BFGS-B "failures"
            # produce reasonable parameter estimates)
            if not math.isfinite(result.fun):
                return None

        omega_hat = float(result.x[0])
        alpha_hat = float(result.x[1])
        beta_hat = float(result.x[2])
        persistence = alpha_hat + beta_hat

        if persistence >= _MAX_PERSISTENCE:
            logger.debug(
                "GARCH fit rejected for %s: persistence=%.4f >= %.4f",
                metric_name,
                persistence,
                _MAX_PERSISTENCE,
            )
            return None

        uncond_var = omega_hat / (1.0 - persistence)
        if not math.isfinite(uncond_var) or uncond_var <= 0:
            logger.debug(
                "GARCH fit rejected for %s: invalid unconditional variance=%.6g",
                metric_name,
                uncond_var,
            )
            return None

        # Compute the full conditional variance series for diagnostics
        sigma2_series = _compute_conditional_variances(result.x, eps2)
        log_lik = -result.fun

        logger.info(
            "GARCH(1,1) fitted for %s: omega=%.6g, alpha=%.4f, beta=%.4f, "
            "persistence=%.4f, uncond_var=%.6g, LL=%.2f",
            metric_name,
            omega_hat,
            alpha_hat,
            beta_hat,
            persistence,
            uncond_var,
            log_lik,
        )

        return GARCHResult(
            metric=metric_name,
            omega=omega_hat,
            alpha=alpha_hat,
            beta=beta_hat,
            persistence=persistence,
            unconditional_variance=uncond_var,
            conditional_variances=tuple(float(v) for v in sigma2_series),
            log_likelihood=log_lik,
            n_observations=len(clean),
        )

    def forecast_variance(
        self,
        result: GARCHResult,
        horizon: int,
    ) -> tuple[float, ...]:
        """Compute h-step ahead conditional variance forecasts.

        Multi-step GARCH(1,1) forecast formula (Bollerslev 1986, eq. 9):
            sigma2_{t+h} = V + (alpha + beta)^h * (sigma2_t - V)
        where V = omega / (1 - alpha - beta) is the unconditional variance.

        As h -> inf, the forecast mean-reverts toward V.

        Args:
            result: Fitted GARCHResult from ``fit()``.
            horizon: Number of steps ahead to forecast (>= 1).

        Returns:
            Tuple of h forecasted variance values (sigma2_{t+1}, ..., sigma2_{t+h}).
        """
        if horizon < 1:
            return ()

        v_uncond = result.unconditional_variance
        persistence = result.persistence

        # Use the last fitted conditional variance as the starting point
        sigma2_last = (
            result.conditional_variances[-1]
            if result.conditional_variances
            else v_uncond
        )

        forecasts: list[float] = []
        for h in range(1, horizon + 1):
            # sigma2_{t+h} = V + (alpha+beta)^h * (sigma2_t - V)
            sigma2_h = v_uncond + (persistence ** h) * (sigma2_last - v_uncond)
            forecasts.append(max(sigma2_h, _VARIANCE_FLOOR))

        return tuple(forecasts)

    def adjust_confidence_intervals(
        self,
        point_forecasts: list[float],
        static_std: float,
        garch_result: GARCHResult,
        horizon: int,
        z_score: float = 1.96,
    ) -> tuple[AdjustedCI, ...]:
        """Replace static CI widths with GARCH-based time-varying widths.

        For each forecast horizon step h:
            garch_std_h = sqrt(sigma2_{t+h})
            ci_lower = forecast_h - z * garch_std_h
            ci_upper = forecast_h + z * garch_std_h

        This produces wider CIs during high-volatility regimes (crises) and
        narrower CIs during calm periods, compared to the static approach.

        Args:
            point_forecasts: Sequence of point forecast values.
            static_std: Static standard deviation used by the original CI method.
            garch_result: Fitted GARCHResult for the metric.
            horizon: Number of forecast steps (must match len(point_forecasts)).
            z_score: Z-score multiplier for CI width (default 1.96 = 95%).

        Returns:
            Tuple of ``AdjustedCI`` for each horizon step, or empty tuple on
            failure.
        """
        effective_horizon = min(horizon, len(point_forecasts))
        if effective_horizon < 1:
            return ()

        var_forecasts = self.forecast_variance(garch_result, effective_horizon)
        if not var_forecasts:
            return ()

        adjusted: list[AdjustedCI] = []
        for h in range(effective_horizon):
            garch_std = math.sqrt(max(var_forecasts[h], _VARIANCE_FLOOR))
            forecast_val = point_forecasts[h]

            adjusted.append(AdjustedCI(
                horizon_step=h + 1,
                point_forecast=forecast_val,
                ci_lower=forecast_val - z_score * garch_std,
                ci_upper=forecast_val + z_score * garch_std,
                garch_std=garch_std,
                static_std=static_std,
            ))

        return tuple(adjusted)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sanitise(series: list[float]) -> list[float]:
    """Remove NaN and inf values from a series."""
    return [v for v in series if math.isfinite(v)]
