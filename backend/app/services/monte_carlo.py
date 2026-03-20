"""Monte Carlo Engine for HKSimEngine.

Runs N stochastic trials by perturbing decision confidence values and macro
coefficients using Cholesky-decomposed correlated noise, then computes
percentile distribution bands for key outcome metrics. Results are persisted
in the ``ensemble_results`` table.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats as scipy_stats
from scipy.stats import qmc

from backend.app.models.ensemble import DistributionBand, EnsembleResult
from backend.app.services.calibrated_coefficients import CalibratedCoefficients
from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

_CALIBRATION_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent / "data" / "calibration_coefficients.json"
)

logger = get_logger("monte_carlo")


# ---------------------------------------------------------------------------
# Module-level trial worker — picklable for ProcessPoolExecutor
# ---------------------------------------------------------------------------


def _mc_trial_worker(
    args: tuple,
) -> dict[str, float]:
    """Execute a single Monte Carlo trial and return its outcome dict.

    Module-level function so it can be pickled for ``ProcessPoolExecutor``.

    Args:
        args: Tuple of (trial_idx, base_data, lhs_samples, cov_matrix_diag_sd,
              has_cov, ci_multiplier, coefficients_dict, pair_std_errs).
    """
    (
        trial_idx,
        base_data,
        lhs_samples,
        cov_matrix_diag_sd,  # 1-D array of std-devs for the 4 correlated vars
        has_cov,
        ci_multiplier,
        coefficients_dict,   # plain dict extracted from CalibratedCoefficients
        pair_std_errs,
    ) = args

    # Each trial gets its own RNG seeded deterministically from trial_idx so
    # results are reproducible per-trial while being independent across trials.
    trial_rng = np.random.default_rng(trial_idx)

    correlated_deltas: dict[str, float] = {}
    if has_cov:
        for i, var in enumerate(_CORRELATED_VARS):
            u = np.clip(lhs_samples[trial_idx, i], 1e-8, 1 - 1e-8)
            z = scipy_stats.norm.ppf(u)
            correlated_deltas[var] = float(z * cov_matrix_diag_sd[i] * ci_multiplier)

    # Build a lightweight coefficient proxy that mimics CalibratedCoefficients.get()
    def _get_coef(indicator: str, sentiment_metric: str) -> float | None:
        cal_key = _CALIBRATION_KEY_MAP.get(indicator, indicator)
        val = coefficients_dict.get(cal_key, {}).get(sentiment_metric)
        if val is not None and val != 0.0:
            return float(val)
        return None

    def _coef(indicator: str, metric: str, default: float) -> float:
        v = _get_coef(indicator, metric)
        return v if v is not None else default

    def _pair_se(indicator: str, metric: str) -> float:
        cal_key = _CALIBRATION_KEY_MAP.get(indicator, indicator)
        return float(pair_std_errs.get(cal_key, {}).get(metric, 0.0))

    # -- Perturb confidences --------------------------------------------------
    def perturb_conf(v: float) -> float:
        noisy = v + trial_rng.normal(0, _CONFIDENCE_NOISE_SIGMA * ci_multiplier)
        return float(np.clip(noisy, 0.0, 1.0))

    buy_conf = perturb_conf(base_data.get("buy_property_confidence", 0.5))
    emigrate_conf = perturb_conf(base_data.get("emigrate_confidence", 0.5))

    # -- Perturb macro params -------------------------------------------------
    def perturb_macro(v: float, var_name: str | None = None) -> float:
        if var_name and var_name in correlated_deltas:
            return float(v + correlated_deltas[var_name])
        frac = _MACRO_PERTURBATION_FRACTION * ci_multiplier
        factor = 1.0 + trial_rng.uniform(-frac, frac)
        return float(v * factor)

    gdp_growth = perturb_macro(base_data.get("gdp_growth", 0.02), "gdp_growth")
    unemployment = perturb_macro(base_data.get("unemployment_rate", 0.05), "unemployment_rate")
    ccl_base = perturb_macro(base_data.get("ccl_index", 160.0))  # noqa: F841
    hsi_base = perturb_macro(base_data.get("hsi_level", 18000.0), "hsi_level")
    conf_base = perturb_macro(base_data.get("consumer_confidence", 50.0), "consumer_confidence")  # noqa: F841
    net_mig_base = float(base_data.get("net_migration", -50000.0))  # noqa: F841
    interest = perturb_macro(base_data.get("interest_rate", 0.055))
    geo_risk = perturb_macro(base_data.get("taiwan_strait_risk", 0.3))
    neg_ratio = perturb_macro(base_data.get("negative_ratio", 0.3))
    pos_ratio = perturb_macro(base_data.get("positive_ratio", 0.4))

    def _perturbed_coef(indicator: str, metric: str, default: float) -> float:
        slope = _coef(indicator, metric, default)
        se = _pair_se(indicator, metric)
        if se > 0:
            noise = trial_rng.normal(0, se * ci_multiplier)
            return slope + noise
        return slope

    # -- Derive outcome metrics -----------------------------------------------
    buy_property_rate = float(np.clip(
        buy_conf * 0.6
        - interest * _perturbed_coef("ccl_index", "negative_ratio", 3.0)
        - geo_risk * 0.2,
        0.0, 1.0,
    ))

    emigrate_rate = float(np.clip(
        emigrate_conf * 0.5
        + geo_risk * 0.3,
        0.0, 1.0,
    ))

    ccl_index_change = float(
        buy_property_rate * 5.0
        - interest * 80.0
        + neg_ratio * _perturbed_coef("price_index_all_classes", "negative_ratio", -3.0)
    )

    unemployment_change = float(
        -gdp_growth * 0.8
        + emigrate_rate * 0.02
        + neg_ratio * _perturbed_coef("unemployment_rate", "negative_ratio", 0.01)
    )

    net_migration_change = float(
        -emigrate_rate * 250.0
        - geo_risk * 50.0
        + gdp_growth * 100.0
        + neg_ratio * _perturbed_coef("net_migration", "negative_ratio", -10.0)
    )

    hsi_pos_coef = _perturbed_coef("hsi_level", "positive_ratio", 0.15)
    hsi_neg_coef = abs(_perturbed_coef("hsi_level", "stock_market_positive", 0.10))
    hsi_change = float(
        gdp_growth * 0.6 * hsi_base
        + pos_ratio * hsi_pos_coef * hsi_base
        - neg_ratio * hsi_neg_coef * hsi_base
    )

    cc_neg = _perturbed_coef("consumer_confidence", "negative_ratio", -8.0)
    cc_pos = _perturbed_coef("consumer_confidence", "positive_ratio", 5.0)
    consumer_confidence_change = float(
        gdp_growth * 40.0
        - unemployment * 20.0
        + pos_ratio * cc_pos
        + neg_ratio * cc_neg
    )

    return {
        "buy_property_rate": buy_property_rate,
        "emigrate_rate": emigrate_rate,
        "ccl_index_change": ccl_index_change,
        "unemployment_change": unemployment_change,
        "net_migration_change": net_migration_change,
        "hsi_change": hsi_change,
        "consumer_confidence_change": consumer_confidence_change,
    }

# Correlated macro variables for Cholesky decomposition.
# Order matters — must match row/column order in covariance matrix.
_CORRELATED_VARS = ("gdp_growth", "unemployment_rate", "consumer_confidence", "hsi_level")

# ---------------------------------------------------------------------------
# Table DDL
# ---------------------------------------------------------------------------

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS ensemble_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL,
    n_trials    INTEGER NOT NULL,
    metric_name TEXT    NOT NULL,
    p10         REAL,
    p25         REAL,
    p50         REAL,
    p75         REAL,
    p90         REAL,
    created_at  TEXT    DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ensemble_session ON ensemble_results(session_id);
"""

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_METRICS: list[str] = [
    "ccl_index_change",
    "unemployment_change",
    "net_migration_change",
    "hsi_change",
    "consumer_confidence_change",
    "buy_property_rate",
    "emigrate_rate",
]

# Metrics actually computed by _mc_trial_worker's surrogate formulas.
# Requesting any metric outside this set produces silent zeros — fail-fast instead.
_WORKER_METRICS: frozenset[str] = frozenset(DEFAULT_METRICS)

# Gaussian noise std-dev applied to decision confidence values
_CONFIDENCE_NOISE_SIGMA = 0.1
# Uniform ± fraction applied to macro coefficients
_MACRO_PERTURBATION_FRACTION = 0.10

# Maps Monte Carlo metric names to calibration JSON indicator keys.
# Calibration pipeline uses DB metric names (e.g. "price_index_all_classes")
# while MC uses user-facing names (e.g. "ccl_index").
_CALIBRATION_KEY_MAP: dict[str, str] = {
    "ccl_index": "price_index_all_classes",
    "hsi_level": "hsi_level",
    "consumer_confidence": "consumer_confidence",
    "unemployment_rate": "unemployment_rate",
    "gdp_growth": "gdp_growth_rate",
    "net_migration": "net_migration",
}


# ---------------------------------------------------------------------------
# Module-level LHS + t-Copula sampling helpers
# ---------------------------------------------------------------------------


def _latin_hypercube_sample(
    n_samples: int,
    n_dims: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Generate LHS matrix of shape (n_samples, n_dims) with values in [0, 1].

    Each dimension is divided into n_samples strata; one sample per stratum.

    Args:
        n_samples: Number of sample points.
        n_dims: Number of dimensions.
        rng: NumPy random generator.

    Returns:
        Array of shape (n_samples, n_dims) with uniform LHS samples.
    """
    result = np.zeros((n_samples, n_dims))
    for dim in range(n_dims):
        perm = rng.permutation(n_samples)
        result[:, dim] = (perm + rng.uniform(size=n_samples)) / n_samples
    return result


def _t_copula_sample(
    n_samples: int,
    n_dims: int,
    corr_matrix: np.ndarray,
    df: int = 4,
    rng: np.random.Generator | None = None,
) -> np.ndarray:
    """Sample from a t-copula with given correlation matrix and degrees of freedom.

    Returns uniform marginals in (0, 1) of shape (n_samples, n_dims).
    t-copula captures tail dependence better than Gaussian copula.

    Steps:
    1. Draw chi-squared scaling factor.
    2. Draw multivariate normal with Cholesky correlation.
    3. Scale to get multivariate-t samples.
    4. Convert to uniform marginals via t-CDF.

    Args:
        n_samples: Number of sample points.
        n_dims: Number of dimensions.
        corr_matrix: (n_dims, n_dims) correlation matrix.
        df: Degrees of freedom (default 4 for heavier tails).
        rng: NumPy random generator; created fresh if None.

    Returns:
        Array of shape (n_samples, n_dims) with values in (0, 1).
    """
    if rng is None:
        rng = np.random.default_rng()
    try:
        from scipy import stats  # noqa: PLC0415
        # 1. Chi-squared scaling factor
        chi2 = rng.chisquare(df, size=n_samples)
        # 2. Multivariate normal via Cholesky
        try:
            L = np.linalg.cholesky(corr_matrix)
        except np.linalg.LinAlgError:
            # Fix non-PD matrix via eigenvalue clipping
            eigenvalues, eigenvectors = np.linalg.eigh(corr_matrix)
            clipped = np.maximum(eigenvalues, 1e-10)
            pd_matrix = eigenvectors @ np.diag(clipped) @ eigenvectors.T
            L = np.linalg.cholesky(pd_matrix)
        z = rng.standard_normal((n_samples, n_dims)) @ L.T
        # 3. Scale to multivariate-t
        scale = np.sqrt(df / chi2)[:, np.newaxis]
        t_samples = z * scale
        # 4. Convert to uniform marginals via t-CDF
        return stats.t.cdf(t_samples, df=df)
    except Exception:
        # Graceful fallback to uniform random if scipy unavailable
        return rng.random((n_samples, n_dims))


# ---------------------------------------------------------------------------
# MonteCarloEngine
# ---------------------------------------------------------------------------


class MonteCarloEngine:
    """Run probabilistic ensemble simulations using perturbation Monte Carlo."""

    def __init__(self) -> None:
        self._calibrated: CalibratedCoefficients | None = None

    def _load_calibrated_coefficients(self) -> CalibratedCoefficients:
        """Load OLS-calibrated coefficients, caching the instance.

        Returns:
            CalibratedCoefficients with file-based or default values loaded.
        """
        if self._calibrated is None:
            self._calibrated = CalibratedCoefficients()
            self._calibrated.load_sync()
        return self._calibrated

    async def run(
        self,
        session_id: str,
        n_trials: int = 500,
        metrics: list[str] | None = None,
        domain_pack_id: str = "hk_city",
    ) -> EnsembleResult:
        """Run Monte Carlo ensemble for *session_id*.

        Algorithm:
        1. Load base simulation data from DB (decisions, macro history, sentiment).
        2. For each trial, perturb decision confidences (Gaussian) and macro
           coefficients (uniform ±10%).
        3. Recompute aggregate outcomes for each trial.
        4. Compute percentile bands and persist to ``ensemble_results``.

        Args:
            session_id: Simulation session UUID.
            n_trials: Number of stochastic trials to run (default 500).
            metrics: Subset of metrics to compute (default all DEFAULT_METRICS).
            domain_pack_id: Domain pack for default metrics/correlated vars.

        Returns:
            EnsembleResult with DistributionBand for each metric.
        """
        # Resolve defaults from domain pack
        pack_metrics = DEFAULT_METRICS
        pack_correlated = _CORRELATED_VARS
        try:
            from backend.app.domain.base import DomainPackRegistry  # noqa: PLC0415
            pack = DomainPackRegistry.get(domain_pack_id)
            if pack.mc_default_metrics:
                pack_metrics = list(pack.mc_default_metrics)
            if pack.correlated_vars:
                pack_correlated = pack.correlated_vars
        except (KeyError, ImportError):
            pass

        if metrics is None:
            metrics = pack_metrics

        # Fail-fast: unknown metrics produce silent zeros in the surrogate worker
        unsupported = [m for m in metrics if m not in _WORKER_METRICS]
        if unsupported:
            raise ValueError(
                f"Monte Carlo surrogate does not support metrics: {unsupported}. "
                f"Supported: {sorted(_WORKER_METRICS)}"
            )

        n_trials = max(10, min(n_trials, 2000))

        # Load base data + calibration coefficients
        base_data = await self._load_base_data(session_id)
        calibration = self._load_calibration()
        calibrated_coefs = self._load_calibrated_coefficients()
        data_integrity = self._assess_data_integrity(calibration)

        logger.info(
            "MC run session=%s trials=%d metrics=%s data_integrity=%.2f",
            session_id, n_trials, metrics, data_integrity,
        )

        # Build per-pair OLS std_err lookup for calibration-driven perturbations
        pair_std_errs = self._load_std_errs_from_calibration(calibration)

        # Build covariance matrix for correlated macro perturbations
        cov_matrix = self._build_empirical_covariance(calibration)

        # Run trials with LHS + t-Copula sampling
        rng = np.random.default_rng(seed=None)  # non-deterministic per run
        trial_results: dict[str, list[float]] = {m: [] for m in metrics}

        # Expand CI by 2x if data integrity is low (mostly synthetic)
        ci_multiplier = 2.0 if data_integrity < 0.5 else 1.0

        # Pre-generate all perturbations using LHS + t-Copula
        # Variables: 4 correlated macro vars + 2 confidence + 4 independent macro
        n_correlated = len(pack_correlated)
        n_total_vars = n_correlated + 6  # confidence(2) + ccl, interest, geo_risk, ratios(neg+pos) ~ 6 extras
        lhs_samples = self._generate_lhs_samples(n_trials, n_total_vars, rng)

        # Apply t-copula to correlated macro dimensions only
        if cov_matrix is not None:
            # Build correlation matrix from covariance for the 4 correlated vars
            sd = np.sqrt(np.diag(cov_matrix))
            sd_safe = np.where(sd > 0, sd, 1e-10)
            corr_matrix = cov_matrix / np.outer(sd_safe, sd_safe)
            np.fill_diagonal(corr_matrix, 1.0)

            copula_samples = self._apply_t_copula(
                lhs_samples[:, :n_correlated], corr_matrix, df=5,
            )
            # Replace first n_correlated columns with copula-transformed samples
            lhs_samples = np.column_stack([copula_samples, lhs_samples[:, n_correlated:]])

        # Extract coefficients dict for pickling (avoids passing the full
        # CalibratedCoefficients object which contains a Path and lazy state).
        coef_dict: dict[str, dict[str, float]] = (
            calibrated_coefs.to_dict()
            if calibrated_coefs is not None
            else {}
        )

        # Compute per-variable std-devs once; passed as a plain 1-D ndarray.
        cov_diag_sd = (
            np.sqrt(np.diag(cov_matrix)).tolist()
            if cov_matrix is not None
            else [0.0] * len(_CORRELATED_VARS)
        )

        # Build args list — every element must be picklable.
        args_list = [
            (
                trial_idx,
                base_data,
                lhs_samples,
                cov_diag_sd,
                cov_matrix is not None,
                ci_multiplier,
                coef_dict,
                pair_std_errs,
            )
            for trial_idx in range(n_trials)
        ]

        # Parallelize trials for large runs using ProcessPoolExecutor for true
        # CPU parallelism. _mc_trial_worker is module-level and fully picklable.
        if n_trials >= 30:
            loop = asyncio.get_event_loop()
            with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
                outcomes = await loop.run_in_executor(
                    None,
                    lambda: list(pool.map(_mc_trial_worker, args_list)),
                )
            for outcome in outcomes:
                for metric in metrics:
                    trial_results[metric].append(outcome.get(metric, 0.0))
        else:
            for args in args_list:
                outcome = _mc_trial_worker(args)
                for metric in metrics:
                    trial_results[metric].append(outcome.get(metric, 0.0))

        # Compute distribution bands
        bands: list[DistributionBand] = []
        for metric in metrics:
            values = np.array(trial_results[metric], dtype=float)
            if len(values) == 0:
                continue
            p10, p25, p50, p75, p90 = np.percentile(values, [10, 25, 50, 75, 90])
            bands.append(DistributionBand(
                metric_name=metric,
                p10=float(p10),
                p25=float(p25),
                p50=float(p50),
                p75=float(p75),
                p90=float(p90),
            ))

        # Persist to DB
        await self._persist_results(session_id, n_trials, bands)

        return EnsembleResult(
            session_id=session_id,
            n_trials=n_trials,
            distributions=bands,
            data_integrity_score=data_integrity,
            sampling_method="lhs_t_copula",
        )

    # Mini-ensemble constants
    _MINI_TRIALS = 10
    _MINI_METRICS = [
        "ccl_index_change",
        "unemployment_change",
        "hsi_change",
        "consumer_confidence_change",
    ]

    async def run_mini(
        self,
        session_id: str,
        domain_pack_id: str = "hk_city",
    ) -> EnsembleResult:
        """Run a lightweight 10-trial ensemble for top 4 metrics.

        Called automatically at simulation completion to provide
        median + IQR without the full Monte Carlo cost.

        Args:
            session_id: Simulation session UUID.
            domain_pack_id: Domain pack ID (default hk_city).

        Returns:
            EnsembleResult with 4 DistributionBands.
        """
        return await self.run(
            session_id=session_id,
            n_trials=self._MINI_TRIALS,
            metrics=self._MINI_METRICS,
            domain_pack_id=domain_pack_id,
        )

    async def get_cached_result(self, session_id: str) -> EnsembleResult | None:
        """Return the most recent cached ensemble result for a session, if any.

        Args:
            session_id: Simulation session UUID.

        Returns:
            EnsembleResult or None if not found.
        """
        try:
            async with get_db() as db:
                await db.executescript(_CREATE_TABLE_SQL)
                cursor = await db.execute(
                    """
                    SELECT metric_name, p10, p25, p50, p75, p90, n_trials
                    FROM ensemble_results
                    WHERE session_id = ?
                    ORDER BY created_at DESC
                    """,
                    (session_id,),
                )
                rows = await cursor.fetchall()
        except Exception:
            logger.exception("get_cached_result failed session=%s", session_id)
            return None

        if not rows:
            return None

        bands = [
            DistributionBand(
                metric_name=row["metric_name"],
                p10=row["p10"],
                p25=row["p25"],
                p50=row["p50"],
                p75=row["p75"],
                p90=row["p90"],
            )
            for row in rows
        ]
        n_trials = rows[0]["n_trials"] if rows else 0
        return EnsembleResult(
            session_id=session_id,
            n_trials=n_trials,
            distributions=bands,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_std_errs_from_calibration(
        calibration: dict[str, Any],
    ) -> dict[str, dict[str, float]]:
        """Extract per-pair OLS standard errors from calibration JSON.

        Returns nested dict: {indicator → {sentiment_metric → std_err}}.
        Falls back to empty dict if no std_err data is available.
        """
        result: dict[str, dict[str, float]] = {}
        for key, val in calibration.items():
            if key.startswith("_"):
                continue
            if isinstance(val, dict):
                for sent_metric, entry in val.items():
                    if isinstance(entry, dict) and "std_err" in entry:
                        se = entry["std_err"]
                        if isinstance(se, (int, float)) and se > 0:
                            if key not in result:
                                result[key] = {}
                            result[key][sent_metric] = float(se)
        return result

    @staticmethod
    def _build_empirical_covariance(
        calibration: dict[str, Any],
    ) -> np.ndarray | None:
        """Build empirical covariance matrix for correlated macro variables.

        Uses OLS std_err values from calibration as a proxy for marginal
        variance, with assumed correlations based on economic theory:
        - GDP and unemployment: negative correlation (-0.6, Okun's law)
        - GDP and confidence: positive correlation (0.5)
        - GDP and HSI: positive correlation (0.4)
        - Unemployment and confidence: negative correlation (-0.5)
        - Unemployment and HSI: negative correlation (-0.3)
        - Confidence and HSI: positive correlation (0.6)

        Returns Cholesky-compatible covariance matrix, or None if insufficient data.
        """
        # Extract marginal standard deviations from calibration or use defaults
        std_devs: dict[str, float] = {
            "gdp_growth": 0.005,
            "unemployment_rate": 0.005,
            "consumer_confidence": 3.0,
            "hsi_level": 1500.0,
        }

        # Override with OLS-derived std_err if available
        key_map = {
            "gdp_growth_rate": "gdp_growth",
            "unemployment_rate": "unemployment_rate",
            "consumer_confidence": "consumer_confidence",
        }
        for cal_key, var_name in key_map.items():
            entry = calibration.get(cal_key, {})
            if isinstance(entry, dict):
                for _sent, detail in entry.items():
                    if isinstance(detail, dict) and "std_err" in detail:
                        se = detail["std_err"]
                        if isinstance(se, (int, float)) and se > 0:
                            std_devs[var_name] = float(se)
                            break  # use first available

        # Assumed correlation matrix (economic theory priors)
        corr = np.array([
            # gdp    unemp   conf    hsi
            [1.00,  -0.60,   0.50,   0.40],   # gdp_growth
            [-0.60,  1.00,  -0.50,  -0.30],   # unemployment_rate
            [0.50,  -0.50,   1.00,   0.60],   # consumer_confidence
            [0.40,  -0.30,   0.60,   1.00],   # hsi_level
        ], dtype=np.float64)

        # Build covariance matrix: cov[i,j] = corr[i,j] * std[i] * std[j]
        sd = np.array([std_devs[v] for v in _CORRELATED_VARS], dtype=np.float64)
        cov = corr * np.outer(sd, sd)

        return cov

    @staticmethod
    def _generate_correlated_perturbations(
        cov_matrix: np.ndarray,
        rng: np.random.Generator,
        ci_multiplier: float = 1.0,
    ) -> dict[str, float]:
        """Generate correlated perturbation deltas using Cholesky decomposition.

        Falls back to independent noise if Cholesky fails (matrix not positive
        definite).

        Returns dict mapping variable name to perturbation delta.
        """
        n = len(_CORRELATED_VARS)
        try:
            L = np.linalg.cholesky(cov_matrix * ci_multiplier)
            independent_noise = rng.standard_normal(n)
            correlated_noise = L @ independent_noise
        except np.linalg.LinAlgError:
            # Matrix not positive definite — fall back to independent noise
            logger.debug("Cholesky decomposition failed — using independent perturbations")
            sd = np.sqrt(np.diag(cov_matrix))
            correlated_noise = rng.normal(0, sd * ci_multiplier)

        return {var: float(correlated_noise[i]) for i, var in enumerate(_CORRELATED_VARS)}

    @staticmethod
    def _nearest_pd(A: np.ndarray) -> np.ndarray:
        """Return the nearest positive-definite matrix to *A*.

        Uses eigenvalue clipping: decompose, clip negative eigenvalues to a
        small positive value, then reconstruct.
        """
        eigenvalues, eigenvectors = np.linalg.eigh(A)
        clipped = np.maximum(eigenvalues, 1e-10)
        return eigenvectors @ np.diag(clipped) @ eigenvectors.T

    @staticmethod
    def _generate_lhs_samples(
        n_trials: int,
        n_vars: int,
        rng: np.random.Generator,
    ) -> np.ndarray:
        """Generate Latin Hypercube samples in [0,1]^n_vars.

        Args:
            n_trials: Number of sample points.
            n_vars: Number of dimensions.
            rng: NumPy random generator (used to derive integer seed).

        Returns:
            Array of shape (n_trials, n_vars) with uniform LHS samples.
        """
        seed_int = int(rng.integers(0, 2**31))
        sampler = qmc.LatinHypercube(d=n_vars, seed=seed_int)
        return sampler.random(n=n_trials)

    @staticmethod
    def _apply_t_copula(
        uniform_samples: np.ndarray,
        corr_matrix: np.ndarray,
        df: int = 5,
    ) -> np.ndarray:
        """Transform uniform LHS samples through a t-copula.

        Steps:
        1. Map uniforms to t-distribution quantiles.
        2. Apply Cholesky of correlation matrix to introduce dependence.
        3. Map back to uniforms via t-CDF.

        Args:
            uniform_samples: (n_trials, n_vars) array in [0, 1].
            corr_matrix: (n_vars, n_vars) correlation matrix.
            df: Degrees of freedom for t-distribution (default 5).

        Returns:
            (n_trials, n_vars) array in [0, 1] with t-copula dependence.
        """
        # Clip to avoid infinities at edges
        clipped = np.clip(uniform_samples, 1e-8, 1.0 - 1e-8)

        # Uniform -> t quantiles
        t_samples = scipy_stats.t.ppf(clipped, df)

        # Ensure correlation matrix is positive definite
        try:
            L = np.linalg.cholesky(corr_matrix)
        except np.linalg.LinAlgError:
            L = np.linalg.cholesky(MonteCarloEngine._nearest_pd(corr_matrix))

        # Apply Cholesky to introduce dependence
        correlated = (L @ t_samples.T).T

        # Map back to uniforms via t-CDF
        return scipy_stats.t.cdf(correlated, df)

    async def _load_base_data(self, session_id: str) -> dict[str, Any]:
        """Load base simulation state from the database.

        Loads:
        - Decision confidence summary (avg per type/action)
        - Last macro snapshot
        - Sentiment summary (positive/negative ratios)

        Returns a flat dict of base values for perturbation.
        """
        base: dict[str, Any] = {
            "avg_confidence": 0.5,
            "buy_property_confidence": 0.5,
            "emigrate_confidence": 0.5,
            "invest_confidence": 0.5,
            "gdp_growth": 0.02,
            "unemployment_rate": 0.05,
            "ccl_index": 160.0,
            "hsi_level": 18000.0,
            "consumer_confidence": 50.0,
            "net_migration": -50000.0,
            "positive_ratio": 0.4,
            "negative_ratio": 0.3,
            "interest_rate": 0.055,
            "taiwan_strait_risk": 0.3,
        }

        try:
            async with get_db() as db:
                # Decision confidence
                cursor = await db.execute(
                    """
                    SELECT decision_type, action, AVG(confidence) as avg_conf
                    FROM agent_decisions
                    WHERE session_id = ?
                    GROUP BY decision_type, action
                    """,
                    (session_id,),
                )
                dec_rows = await cursor.fetchall()
                for row in dec_rows:
                    dt = row["decision_type"]
                    action = row["action"]
                    conf = row["avg_conf"] or 0.5
                    if dt == "buy_property" and action == "buy":
                        base["buy_property_confidence"] = conf
                    elif dt == "emigrate" and action == "emigrate":
                        base["emigrate_confidence"] = conf
                    elif dt == "invest":
                        base["invest_confidence"] = conf
                    base["avg_confidence"] = conf  # last one wins as rough proxy

                # Latest macro snapshot
                cursor = await db.execute(
                    """
                    SELECT macro_json FROM macro_snapshots
                    WHERE session_id = ?
                    ORDER BY round_number DESC LIMIT 1
                    """,
                    (session_id,),
                )
                row = await cursor.fetchone()
                if row and row["macro_json"]:
                    try:
                        macro = json.loads(row["macro_json"])
                        for key in (
                            "gdp_growth", "unemployment_rate", "ccl_index",
                            "hsi_level", "consumer_confidence", "net_migration",
                            "interest_rate", "taiwan_strait_risk",
                        ):
                            if key in macro and macro[key] is not None:
                                base[key] = float(macro[key])
                    except (json.JSONDecodeError, TypeError, ValueError):
                        pass

                # Sentiment summary
                cursor = await db.execute(
                    """
                    SELECT
                        CAST(SUM(CASE WHEN sentiment = 'positive' THEN 1 ELSE 0 END) AS REAL) / COUNT(*) AS pos_ratio,
                        CAST(SUM(CASE WHEN sentiment = 'negative' THEN 1 ELSE 0 END) AS REAL) / COUNT(*) AS neg_ratio
                    FROM simulation_actions
                    WHERE session_id = ?
                    """,
                    (session_id,),
                )
                sent_row = await cursor.fetchone()
                if sent_row:
                    if sent_row[0] is not None:
                        base["positive_ratio"] = float(sent_row[0])
                    if sent_row[1] is not None:
                        base["negative_ratio"] = float(sent_row[1])

        except Exception:
            logger.warning(
                "Could not load base data for session=%s, using defaults", session_id
            )

        return base

    @staticmethod
    def _load_calibration() -> dict[str, Any]:
        """Load calibration coefficients from JSON file (if available)."""
        try:
            if _CALIBRATION_PATH.exists():
                return json.loads(_CALIBRATION_PATH.read_text())
        except Exception:
            pass
        return {}

    @staticmethod
    def _assess_data_integrity(calibration: dict[str, Any]) -> float:
        """Score 0.0–1.0 based on how many calibration pairs have real data.

        Checks p_value presence and synthetic_pct in _meta.
        """
        meta = calibration.get("_meta", {})
        synthetic_pct = meta.get("synthetic_pct", 1.0)
        # 0% synthetic → 1.0 integrity, 100% synthetic → 0.0
        return max(0.0, min(1.0, 1.0 - synthetic_pct))

    @staticmethod
    def _run_single_trial(
        base: dict[str, Any],
        rng: np.random.Generator,
        ci_multiplier: float = 1.0,
        calibrated: CalibratedCoefficients | None = None,
        *,
        correlated_deltas: dict[str, float] | None = None,
        pair_std_errs: dict[str, dict[str, float]] | None = None,
    ) -> dict[str, float]:
        """Compute a single perturbed outcome using OLS-calibrated coefficients.

        1. Perturb decision confidence values by Gaussian noise (sigma=0.1).
        2. Apply Cholesky-correlated perturbations for GDP, unemployment,
           confidence, and HSI (if available); fall back to independent uniform.
        3. Perturb remaining macro params by independent uniform noise.
        4. Derive outcome metrics using calibrated slopes where available,
           falling back to hand-tuned defaults.

        Args:
            base: Base simulation data from DB.
            rng: NumPy random generator.
            ci_multiplier: Widen CI for low-integrity data.
            calibrated: OLS-calibrated coefficients (optional).
            correlated_deltas: Pre-computed correlated noise for macro vars.
            pair_std_errs: Per-pair OLS std_err from calibration JSON.
        """
        if correlated_deltas is None:
            correlated_deltas = {}
        if pair_std_errs is None:
            pair_std_errs = {}

        def _coef(indicator: str, metric: str, default: float) -> float:
            """Retrieve calibrated slope, falling back to *default*.

            Translates MC indicator names to calibration JSON keys via
            _CALIBRATION_KEY_MAP before lookup.
            """
            if calibrated is not None:
                cal_key = _CALIBRATION_KEY_MAP.get(indicator, indicator)
                val = calibrated.get(cal_key, metric)
                if val != 0.0:
                    return val
            return default

        def _pair_se(indicator: str, metric: str) -> float:
            """Get OLS std_err for a specific (indicator, metric) pair."""
            cal_key = _CALIBRATION_KEY_MAP.get(indicator, indicator)
            return pair_std_errs.get(cal_key, {}).get(metric, 0.0)

        # -- Perturb confidences -----------------------------------------------
        def perturb_conf(v: float) -> float:
            noisy = v + rng.normal(0, _CONFIDENCE_NOISE_SIGMA * ci_multiplier)
            return float(np.clip(noisy, 0.0, 1.0))

        buy_conf = perturb_conf(base.get("buy_property_confidence", 0.5))
        emigrate_conf = perturb_conf(base.get("emigrate_confidence", 0.5))

        # -- Perturb macro params -----------------------------------------------
        # Use correlated deltas for the 4 correlated variables when available;
        # otherwise fall back to independent uniform perturbation.
        def perturb_macro(v: float, var_name: str | None = None) -> float:
            if var_name and var_name in correlated_deltas:
                return float(v + correlated_deltas[var_name])
            frac = _MACRO_PERTURBATION_FRACTION * ci_multiplier
            factor = 1.0 + rng.uniform(-frac, frac)
            return float(v * factor)

        gdp_growth = perturb_macro(base.get("gdp_growth", 0.02), "gdp_growth")
        unemployment = perturb_macro(base.get("unemployment_rate", 0.05), "unemployment_rate")
        ccl_base = perturb_macro(base.get("ccl_index", 160.0))
        hsi_base = perturb_macro(base.get("hsi_level", 18000.0), "hsi_level")
        conf_base = perturb_macro(base.get("consumer_confidence", 50.0), "consumer_confidence")
        net_mig_base = float(base.get("net_migration", -50000.0))
        interest = perturb_macro(base.get("interest_rate", 0.055))
        geo_risk = perturb_macro(base.get("taiwan_strait_risk", 0.3))
        neg_ratio = perturb_macro(base.get("negative_ratio", 0.3))
        pos_ratio = perturb_macro(base.get("positive_ratio", 0.4))

        # Apply per-pair OLS std_err perturbation to calibrated coefficients.
        # This uses the real estimation uncertainty from OLS rather than arbitrary
        # sensitivity values.
        def _perturbed_coef(indicator: str, metric: str, default: float) -> float:
            """Get calibrated coefficient with std_err-based noise applied."""
            slope = _coef(indicator, metric, default)
            se = _pair_se(indicator, metric)
            if se > 0:
                noise = rng.normal(0, se * ci_multiplier)
                return slope + noise
            return slope

        # -- Derive outcome metrics using calibrated coefficients ----------------
        # buy_property_rate: driven by confidence, penalised by interest + geo risk
        buy_property_rate = float(np.clip(
            buy_conf * 0.6
            - interest * _perturbed_coef("ccl_index", "negative_ratio", 3.0)
            - geo_risk * 0.2,
            0.0, 1.0,
        ))

        # emigrate_rate: driven by emigrate confidence + geo risk
        emigrate_rate = float(np.clip(
            emigrate_conf * 0.5
            + geo_risk * 0.3,
            0.0, 1.0,
        ))

        # ccl_index_change: property demand - rate pressure - sentiment
        ccl_index_change = float(
            buy_property_rate * 5.0
            - interest * 80.0
            + neg_ratio * _perturbed_coef("price_index_all_classes", "negative_ratio", -3.0)
        )

        # unemployment_change: GDP drag + sentiment
        unemployment_change = float(
            -gdp_growth * 0.8
            + emigrate_rate * 0.02
            + neg_ratio * _perturbed_coef("unemployment_rate", "negative_ratio", 0.01)
        )

        # net_migration_change: emigration outflow + GDP pull
        net_migration_change = float(
            -emigrate_rate * 250.0
            - geo_risk * 50.0
            + gdp_growth * 100.0
            + neg_ratio * _perturbed_coef("net_migration", "negative_ratio", -10.0)
        )

        # hsi_change: GDP + sentiment (calibrated positive/negative ratios)
        hsi_pos_coef = _perturbed_coef("hsi_level", "positive_ratio", 0.15)
        hsi_neg_coef = abs(_perturbed_coef("hsi_level", "stock_market_positive", 0.10))
        hsi_change = float(
            gdp_growth * 0.6 * hsi_base
            + pos_ratio * hsi_pos_coef * hsi_base
            - neg_ratio * hsi_neg_coef * hsi_base
        )

        # consumer_confidence_change: calibrated sentiment coefficients
        cc_neg = _perturbed_coef("consumer_confidence", "negative_ratio", -8.0)
        cc_pos = _perturbed_coef("consumer_confidence", "positive_ratio", 5.0)
        consumer_confidence_change = float(
            gdp_growth * 40.0
            - unemployment * 20.0
            + pos_ratio * cc_pos
            + neg_ratio * cc_neg
        )

        return {
            "buy_property_rate": buy_property_rate,
            "emigrate_rate": emigrate_rate,
            "ccl_index_change": ccl_index_change,
            "unemployment_change": unemployment_change,
            "net_migration_change": net_migration_change,
            "hsi_change": hsi_change,
            "consumer_confidence_change": consumer_confidence_change,
        }

    async def _persist_results(
        self,
        session_id: str,
        n_trials: int,
        bands: list[DistributionBand],
    ) -> None:
        """Persist ensemble results to the database.

        Deletes previous results for the session before inserting new ones
        so the table doesn't grow unbounded on re-runs.
        """
        try:
            async with get_db() as db:
                await db.executescript(_CREATE_TABLE_SQL)
                # Remove stale results
                await db.execute(
                    "DELETE FROM ensemble_results WHERE session_id = ?",
                    (session_id,),
                )
                rows_to_insert = [
                    (session_id, n_trials, b.metric_name, b.p10, b.p25, b.p50, b.p75, b.p90)
                    for b in bands
                ]
                await db.executemany(
                    """
                    INSERT INTO ensemble_results
                        (session_id, n_trials, metric_name, p10, p25, p50, p75, p90)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows_to_insert,
                )
                await db.commit()
            logger.debug(
                "Persisted %d distribution bands for session=%s n_trials=%d",
                len(bands), session_id, n_trials,
            )
        except Exception:
            logger.exception("_persist_results failed session=%s", session_id)

    async def run_with_surrogate(
        self,
        session_id: str,
        n_trials: int = 500,
        metrics: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run Monte Carlo using a surrogate model trained from Phase A data.

        When n_trials > 200, trains a logistic regression surrogate from
        Phase A simulation_actions and uses it to approximate outcome
        distributions. Falls back to standard MC run if surrogate training
        fails or produces low accuracy.

        Args:
            session_id: Phase A simulation session ID.
            n_trials: Number of trials to approximate.
            metrics: Metric names (inferred from session if None).

        Returns:
            Dict with surrogate predictions, training accuracy, and
            distribution summary.
        """
        from backend.app.services.surrogate_model import SurrogateModel  # noqa: PLC0415

        surrogate = SurrogateModel()
        result = await surrogate.train_from_session(session_id, metrics=metrics)

        if not result.is_fitted or result.train_accuracy < 0.4:
            logger.info(
                "Surrogate not viable (fitted=%s acc=%.3f) — falling back to standard MC",
                result.is_fitted, result.train_accuracy,
            )
            ensemble = await self.run(session_id, n_trials=min(n_trials, 200), metrics=metrics)
            return {
                "method": "standard_mc_fallback",
                "session_id": session_id,
                "n_trials": ensemble.n_trials,
                "distributions": [
                    {
                        "metric": b.metric_name,
                        "p10": b.p10, "p25": b.p25, "p50": b.p50,
                        "p75": b.p75, "p90": b.p90,
                    }
                    for b in ensemble.distributions
                ],
                "surrogate_accuracy": result.train_accuracy,
            }

        # Generate n_trials synthetic belief vectors via uniform sampling
        rng = np.random.default_rng(seed=42)
        predictions: dict[str, int] = {}
        for _ in range(n_trials):
            belief_vec = {m: float(rng.uniform(0.0, 1.0)) for m in result.metrics_used}
            pred = result.predict(belief_vec)
            predictions[pred] = predictions.get(pred, 0) + 1

        # Compute distribution over outcomes
        total = sum(predictions.values())
        distribution = {
            k: round(v / total, 4) for k, v in sorted(
                predictions.items(), key=lambda x: -x[1]
            )
        }

        logger.info(
            "Surrogate MC completed session=%s trials=%d accuracy=%.3f classes=%d",
            session_id, n_trials, result.train_accuracy, result.n_classes,
        )

        return {
            "method": "surrogate_logistic",
            "session_id": session_id,
            "n_trials": n_trials,
            "surrogate_accuracy": result.train_accuracy,
            "n_classes": result.n_classes,
            "classes": result.classes,
            "outcome_distribution": distribution,
            "metrics_used": result.metrics_used,
        }
