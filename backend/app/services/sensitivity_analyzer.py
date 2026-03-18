# backend/app/services/sensitivity_analyzer.py
"""Parameter sensitivity analysis for HKSimEngine calibration.

Sweeps key delta_per_10 calibration parameters across ±50% of their baseline
values and measures the resulting change in directional accuracy for each
macro metric.  Results identify which parameters the model is most sensitive to,
helping researchers prioritise recalibration effort.

Usage::

    analyzer = SensitivityAnalyzer()
    report = await analyzer.run("2021-Q1", "2023-Q4")
    for row in report["sensitivities"]:
        print(row["parameter"], row["metric"], row["sensitivity_score"])
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from backend.app.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Fractional perturbation applied to each parameter in the sweep.
# e.g. 0.25 means we test baseline × 0.75 and baseline × 1.25.
_PERTURBATION = 0.25

# Grid steps per parameter (odd number so we always include the midpoint).
_N_STEPS = 5

# Minimum absolute baseline to avoid division-by-zero or degenerate sweeps.
_MIN_BASELINE_ABS = 1e-6

# Calibration parameter names that will be swept.
# These map to the coefficient keys used by CalibratedCoefficients.
_SWEEP_PARAMETERS: list[str] = [
    "negative_ratio",
    "positive_ratio",
    "neutral_ratio",
    "thread_count",
    "total_engagement",
]

# Macro metrics that directional accuracy is measured on.
_TARGET_METRICS: list[str] = [
    "ccl_index",
    "unemployment_rate",
    "hsi_level",
    "gdp_growth",
    "consumer_confidence",
]


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SensitivityRow:
    """Sensitivity of one metric to one parameter."""

    parameter: str
    metric: str
    baseline_coefficient: float
    sensitivity_score: float   # normalised change in directional accuracy [0, 1]
    direction: str             # "positive" | "negative" | "flat"


@dataclass(frozen=True)
class SobolResult:
    """Sobol sensitivity indices for all (parameter, metric) pairs.

    Attributes:
        period_start: Validation period start string.
        period_end: Validation period end string.
        parameters: Parameter names swept.
        metrics: Metric names measured.
        first_order: {param__metric: S1 index} — direct effect only.
        total_order: {param__metric: ST index} — direct + interaction effects.
        summary: Human-readable description.
    """
    period_start: str
    period_end: str
    parameters: list[str]
    metrics: list[str]
    first_order: dict[str, float]   # key = "param__metric"
    total_order: dict[str, float]
    summary: str


# ---------------------------------------------------------------------------
# Main service
# ---------------------------------------------------------------------------


class SensitivityAnalyzer:
    """Sweep calibration parameters and measure forecast sensitivity."""

    async def run(
        self,
        period_start: str,
        period_end: str,
        parameters: list[str] | None = None,
        metrics: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run a full sensitivity sweep.

        Args:
            period_start: Validation period start (e.g. '2021-Q1').
            period_end: Validation period end (e.g. '2023-Q4').
            parameters: Override the list of calibration parameters to sweep.
            metrics: Override the list of macro metrics to measure.

        Returns:
            Dict with keys:
              - period_start, period_end
              - parameters_swept: list[str]
              - metrics_measured: list[str]
              - sensitivities: list[dict] — SensitivityRow per (param, metric)
                pair, sorted by sensitivity_score descending
              - top_sensitivities: list[dict] — top 5 rows
              - summary: str
        """
        sweep_params = parameters or _SWEEP_PARAMETERS
        sweep_metrics = metrics or _TARGET_METRICS

        from backend.app.services.calibrated_coefficients import (  # noqa: PLC0415
            CalibratedCoefficients,
        )
        from backend.app.services.retrospective_validator import (  # noqa: PLC0415
            RetrospectiveValidator,
        )

        coefficients = CalibratedCoefficients()
        await coefficients.load()

        validator = RetrospectiveValidator()

        # Load baseline validation results
        try:
            baseline_results = await validator.validate(
                period_start=period_start,
                period_end=period_end,
                metrics=sweep_metrics,
            )
        except Exception as exc:
            logger.warning("SensitivityAnalyzer: baseline validation failed: %s", exc)
            return _empty_report(period_start, period_end)

        baseline_accuracy: dict[str, float] = {
            r.metric: r.directional_accuracy for r in baseline_results
        }

        if not baseline_accuracy:
            return _empty_report(period_start, period_end)

        rows: list[SensitivityRow] = []

        for param in sweep_params:
            # Retrieve all metric→slope mappings for this sentiment parameter
            all_slopes = coefficients.get_all_by_sentiment(param)

            for metric in sweep_metrics:
                baseline_coeff = all_slopes.get(metric, 0.0)
                baseline_dir = baseline_accuracy.get(metric, 0.5)

                # Generate the sweep grid
                grid = _make_grid(baseline_coeff, _N_STEPS, _PERTURBATION)
                if not grid:
                    continue

                # Measure directional accuracy across the grid using
                # the trajectory generator embedded in the validator
                try:
                    dir_accuracies = await _sweep_grid(
                        validator=validator,
                        param=param,
                        metric=metric,
                        grid=grid,
                        coefficients=coefficients,
                        period_start=period_start,
                        period_end=period_end,
                    )
                except Exception as exc:
                    logger.debug(
                        "SensitivityAnalyzer: sweep failed param=%s metric=%s: %s",
                        param, metric, exc,
                    )
                    continue

                if not dir_accuracies:
                    continue

                # Sensitivity score = max deviation from baseline directional accuracy
                deviations = [abs(da - baseline_dir) for da in dir_accuracies]
                sensitivity_score = max(deviations)

                # Direction: does increasing the parameter improve accuracy?
                # Compare accuracy at highest vs lowest grid point.
                if len(dir_accuracies) >= 2:
                    delta = dir_accuracies[-1] - dir_accuracies[0]
                    if abs(delta) < 0.02:
                        direction = "flat"
                    elif delta > 0:
                        direction = "positive"
                    else:
                        direction = "negative"
                else:
                    direction = "flat"

                rows.append(SensitivityRow(
                    parameter=param,
                    metric=metric,
                    baseline_coefficient=round(baseline_coeff, 6),
                    sensitivity_score=round(sensitivity_score, 4),
                    direction=direction,
                ))

        rows.sort(key=lambda r: r.sensitivity_score, reverse=True)

        row_dicts = [
            {
                "parameter": r.parameter,
                "metric": r.metric,
                "baseline_coefficient": r.baseline_coefficient,
                "sensitivity_score": r.sensitivity_score,
                "direction": r.direction,
            }
            for r in rows
        ]

        top5 = row_dicts[:5]
        summary = _make_summary(rows, period_start, period_end)

        logger.info(
            "SensitivityAnalyzer complete: %d rows, top=%s",
            len(rows),
            top5[0]["parameter"] + "/" + top5[0]["metric"] if top5 else "none",
        )

        return {
            "period_start": period_start,
            "period_end": period_end,
            "parameters_swept": sweep_params,
            "metrics_measured": sweep_metrics,
            "sensitivities": row_dicts,
            "top_sensitivities": top5,
            "summary": summary,
        }

    async def run_sobol(
        self,
        period_start: str,
        period_end: str,
        parameters: list[str] | None = None,
        metrics: list[str] | None = None,
        n_samples: int = 64,
    ) -> "SobolResult":
        """Sobol global sensitivity analysis using SALib Saltelli sampling.

        Generates N*(2D+2) parameter combinations via Saltelli sampler,
        evaluates directional accuracy for each, then computes first-order
        (S1) and total-order (ST) Sobol indices.  ST captures parameter
        interaction effects that ±25% grid sweeps miss.

        Args:
            period_start: Validation period start (e.g. '2021-Q1').
            period_end: Validation period end (e.g. '2023-Q4').
            parameters: Override sweep parameters (default: _SWEEP_PARAMETERS).
            metrics: Override target metrics (default: _TARGET_METRICS).
            n_samples: Base sample count N. Total = N*(2D+2). Default 64.

        Returns:
            SobolResult with first_order and total_order index dicts.
        """
        try:
            from SALib.sample import sobol as saltelli  # noqa: PLC0415
            from SALib.analyze import sobol as sobol_analyze  # noqa: PLC0415
            import numpy as np  # noqa: PLC0415
        except ImportError:
            logger.error("SALib not installed — run: pip install SALib")
            return SobolResult(
                period_start=period_start, period_end=period_end,
                parameters=[], metrics=[], first_order={}, total_order={},
                summary="SALib not installed.",
            )

        from backend.app.services.calibrated_coefficients import CalibratedCoefficients  # noqa: PLC0415
        from backend.app.services.retrospective_validator import RetrospectiveValidator  # noqa: PLC0415

        sweep_params = parameters or _SWEEP_PARAMETERS
        sweep_metrics = metrics or _TARGET_METRICS

        coefficients = CalibratedCoefficients()
        await coefficients.load()
        validator = RetrospectiveValidator()

        all_s1: dict[str, float] = {}
        all_st: dict[str, float] = {}

        for metric in sweep_metrics:
            indices = await _run_sobol_for_metric(
                validator=validator,
                coefficients=coefficients,
                metric=metric,
                sweep_params=sweep_params,
                period_start=period_start,
                period_end=period_end,
                n_samples=n_samples,
                saltelli=saltelli,
                sobol_analyze=sobol_analyze,
                np=np,
            )
            for param, (s1, st) in indices.items():
                key = f"{param}__{metric}"
                all_s1[key] = s1
                all_st[key] = st

        if not all_s1:
            return SobolResult(
                period_start=period_start, period_end=period_end,
                parameters=sweep_params, metrics=sweep_metrics,
                first_order={}, total_order={},
                summary=f"Insufficient data for Sobol analysis ({period_start}–{period_end}).",
            )

        top3 = sorted(all_st.items(), key=lambda x: x[1], reverse=True)[:3]
        top_str = ", ".join(f"{k}={v:.3f}" for k, v in top3)
        summary = (
            f"Sobol analysis ({period_start}–{period_end}): "
            f"{len(all_s1)} indices computed. Top ST: {top_str}."
        )
        logger.info("run_sobol complete: %s", summary)

        return SobolResult(
            period_start=period_start,
            period_end=period_end,
            parameters=sweep_params,
            metrics=sweep_metrics,
            first_order=all_s1,
            total_order=all_st,
            summary=summary,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_grid(baseline: float, n_steps: int, perturbation: float) -> list[float]:
    """Generate a symmetric grid of values around baseline.

    If baseline is near zero, use an absolute perturbation of 0.01.
    """
    if abs(baseline) < _MIN_BASELINE_ABS:
        step = 0.01
        lo = -step * (n_steps // 2)
        return [lo + step * i for i in range(n_steps)]

    lo = baseline * (1.0 - perturbation)
    hi = baseline * (1.0 + perturbation)
    step = (hi - lo) / max(n_steps - 1, 1)
    return [lo + step * i for i in range(n_steps)]


async def _sweep_grid(
    validator: Any,
    param: str,
    metric: str,
    grid: list[float],
    coefficients: Any,
    period_start: str,
    period_end: str,
) -> list[float]:
    """For each grid value, compute predicted directional accuracy.

    Temporarily overrides the coefficient for (param, metric), re-runs
    trajectory generation, and measures directional accuracy vs historical
    data already loaded into the validator's internal cache.

    Uses validator._generate_trajectory() + validator._compute_metrics()
    with a patched coefficient object for each grid point.
    """
    # Load historical data once
    historical = await validator._load_historical_series(period_start, period_end)
    series = historical.get(metric)
    if not series or len(series) < 2:
        return []

    actual_values = [v for _, v in series]
    dir_accuracies: list[float] = []

    for coeff_value in grid:
        patched = _PatchedCoefficients(coefficients, param, metric, coeff_value)
        predicted = validator._generate_trajectory(
            metric=metric,
            initial_value=actual_values[0],
            n_steps=len(actual_values),
            coefficients=patched,
        )
        metrics_dict = await validator._compute_metrics(predicted, actual_values)
        dir_accuracies.append(metrics_dict["directional_accuracy"])

    return dir_accuracies


class _PatchedCoefficients:
    """Thin wrapper that overrides one (param, metric) coefficient."""

    def __init__(
        self,
        base: Any,
        param: str,
        metric: str,
        override_value: float,
    ) -> None:
        self._base = base
        self._param = param
        self._metric = metric
        self._override = override_value

    def get_all(self, metric: str) -> dict[str, float]:
        slopes = dict(self._base.get_all(metric))
        if metric == self._metric:
            slopes[self._param] = self._override
        return slopes

    def get_all_by_sentiment(self, param: str) -> dict[str, float]:
        slopes = dict(self._base.get_all_by_sentiment(param))
        if param == self._param:
            slopes[self._metric] = self._override
        return slopes


def _make_summary(rows: list[SensitivityRow], start: str, end: str) -> str:
    if not rows:
        return f"No sensitivity data produced for {start}–{end}."

    top = rows[0]
    high_sens = [r for r in rows if r.sensitivity_score >= 0.10]
    flat = [r for r in rows if r.direction == "flat"]

    parts = [
        f"Sensitivity sweep ({start}–{end}): {len(rows)} (parameter, metric) pairs tested.",
        f"Most sensitive: {top.parameter} → {top.metric} "
        f"(score={top.sensitivity_score:.3f}, direction={top.direction}).",
    ]
    if high_sens:
        parts.append(
            f"{len(high_sens)} pairs show high sensitivity (score ≥ 0.10) — prioritise recalibration."
        )
    if len(flat) == len(rows):
        parts.append("All parameters appear flat — model may be underspecified or data is insufficient.")

    return " ".join(parts)


def _empty_report(period_start: str, period_end: str) -> dict[str, Any]:
    return {
        "period_start": period_start,
        "period_end": period_end,
        "parameters_swept": [],
        "metrics_measured": [],
        "sensitivities": [],
        "top_sensitivities": [],
        "summary": "Insufficient data to run sensitivity analysis.",
    }


class _PatchedCoefficientsMulti:
    """Override all (param → metric) coefficients for one Saltelli sample row."""

    def __init__(
        self,
        base: Any,
        metric: str,
        params: list[str],
        sample: Any,  # numpy array
    ) -> None:
        self._base = base
        self._metric = metric
        self._overrides: dict[str, float] = dict(zip(params, sample))

    def get_all(self, metric: str) -> dict[str, float]:
        slopes = dict(self._base.get_all(metric))
        if metric == self._metric:
            slopes.update(self._overrides)
        return slopes

    def get_all_by_sentiment(self, param: str) -> dict[str, float]:
        slopes = dict(self._base.get_all_by_sentiment(param))
        if param in self._overrides and self._metric:
            slopes[self._metric] = self._overrides[param]
        return slopes


async def _run_sobol_for_metric(
    validator: Any,
    coefficients: Any,
    metric: str,
    sweep_params: list[str],
    period_start: str,
    period_end: str,
    n_samples: int,
    saltelli: Any,
    sobol_analyze: Any,
    np: Any,
) -> dict[str, tuple[float, float]]:
    """Compute Sobol S1+ST indices for one metric. Returns {param: (S1, ST)}."""
    baseline_coeffs: list[float] = []
    for param in sweep_params:
        slopes = coefficients.get_all_by_sentiment(param)
        baseline_coeffs.append(slopes.get(metric, 0.0))

    bounds = []
    for bc in baseline_coeffs:
        if abs(bc) < _MIN_BASELINE_ABS:
            bounds.append([-0.05, 0.05])
        else:
            lo, hi = sorted([bc * 0.5, bc * 1.5])
            bounds.append([lo, hi])

    problem = {"num_vars": len(sweep_params), "names": sweep_params, "bounds": bounds}
    param_values = saltelli.sample(problem, n_samples, calc_second_order=False, seed=42)

    historical = await validator._load_historical_series(period_start, period_end)
    series = historical.get(metric)
    if not series or len(series) < 2:
        return {}

    actual_values = [v for _, v in series]
    Y = np.zeros(len(param_values))
    for i, sample in enumerate(param_values):
        patched = _PatchedCoefficientsMulti(coefficients, metric, sweep_params, sample)
        predicted = validator._generate_trajectory(
            metric=metric,
            initial_value=actual_values[0],
            n_steps=len(actual_values),
            coefficients=patched,
        )
        metrics_dict = await validator._compute_metrics(predicted, actual_values)
        Y[i] = metrics_dict.get("directional_accuracy", 0.5)

    try:
        Si = sobol_analyze.analyze(problem, Y, calc_second_order=False, print_to_console=False)
        return {
            param: (round(float(Si["S1"][j]), 4), round(float(Si["ST"][j]), 4))
            for j, param in enumerate(sweep_params)
        }
    except Exception as exc:
        logger.warning("Sobol analyze failed for metric=%s: %s", metric, exc)
        return {}
