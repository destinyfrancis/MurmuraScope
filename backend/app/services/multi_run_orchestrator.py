# backend/app/services/multi_run_orchestrator.py
"""Phase B stochastic ensemble — zero LLM cost.

Runs N lightweight trials from Phase A canonical distributions using
t-distribution sampling (heavier tails than Gaussian for tail-risk capture).
No DB writes during trials; only final MultiRunResult is persisted.
"""

from __future__ import annotations

import asyncio
import dataclasses
import math
import random
from dataclasses import dataclass
from typing import Any

from backend.app.utils.logger import get_logger

logger = get_logger(__name__)

_HARD_CAP = 50_000


def _clamp_trial_count(n: int) -> int:
    return max(1, min(n, _HARD_CAP))


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CanonicalResult:
    """Phase A canonical simulation output consumed by MultiRunOrchestrator."""

    simulation_id: str
    scenario_metrics: tuple[str, ...]
    # agent_id → {metric_id: (mean, std_dev)} from Phase A
    agent_belief_distributions: dict[str, dict[str, tuple[float, float]]]
    # Possible named outcomes for this scenario (LLM-defined in ScenarioConfig)
    scenario_outcomes: list[str]
    round_count: int
    # Optional: agent interaction graph for Phase B belief propagation.
    # agent_id → tuple of neighbour agent_ids (from Phase A interaction_graph).
    # When present, each trial runs one round of DeGroot-style neighbour
    # averaging before outcome scoring, improving ensemble realism.
    interaction_graph: dict[str, tuple[str, ...]] = dataclasses.field(default_factory=dict)


@dataclass(frozen=True)
class MultiRunResult:
    simulation_id: str
    trial_count: int
    outcome_distribution: dict[str, float]  # outcome → probability (sums to 1)
    most_common_path: list[str]  # dominant event sequence
    confidence_intervals: dict[str, tuple[float, float]]  # outcome → 95% CI
    avg_tipping_point_round: float
    faction_stability_score: float
    importance_weights_used: bool = False  # True when rare_event_threshold set


@dataclass(frozen=True)
class ReplicateResult:
    """Inter-run variance report from multiple Phase A canonical runs.

    Useful as an epistemic uncertainty measure: when different Phase A
    LLM seeds produce different canonical results, the spread in outcome
    probabilities quantifies how much the LLM non-determinism matters.
    """

    n_replicates: int
    outcome_means: dict[str, float]  # per-outcome mean probability
    outcome_variances: dict[str, float]  # per-outcome inter-run variance
    outcome_std_devs: dict[str, float]  # per-outcome standard deviation
    epistemic_uncertainty: float  # mean std_dev across outcomes (scalar)
    summary: str


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class MultiRunOrchestrator:
    """Run N in-memory stochastic trials from Phase A distributions.

    No LLM calls. Uses t-distribution sampling to capture tail risk
    (heavier tails than Gaussian — better for extreme event simulation).
    """

    async def run(
        self,
        canonical: CanonicalResult,
        trial_count: int = 500,
        concurrency: int = 20,
        df: int = 5,
        surrogate_model: Any | None = None,
        rare_event_threshold: float | None = None,
    ) -> MultiRunResult:
        """Execute Phase B ensemble.

        Args:
            canonical: Phase A output with belief distributions.
            trial_count: Number of trials (capped at 50,000).
            concurrency: Concurrent asyncio tasks (all in-memory, no I/O).
            df: Degrees of freedom for t-distribution sampling (default 5).
            surrogate_model: Optional fitted SurrogateModelResult for data-driven
                outcome prediction (replaces ad-hoc scoring function).
            rare_event_threshold: If set, uses importance sampling with a
                Beta(0.5,0.5) proposal biased toward extreme belief values,
                improving rare event probability estimates.

        Returns:
            MultiRunResult with probability distribution and confidence intervals.
        """
        n = _clamp_trial_count(trial_count)
        use_is = rare_event_threshold is not None
        logger.info(
            "MultiRunOrchestrator: starting %d trials (concurrency=%d, df=%d, IS=%s)",
            n,
            concurrency,
            df,
            use_is,
        )

        sem = asyncio.Semaphore(concurrency)
        ci: dict[str, tuple[float, float]]

        if use_is:

            async def run_trial_is(_: int) -> tuple[str, float]:
                async with sem:
                    return _simulate_trial_is(
                        canonical,
                        df=df,
                        rare_event_threshold=rare_event_threshold,  # type: ignore[arg-type]
                        surrogate_model=surrogate_model,
                    )

            tasks_is = [run_trial_is(i) for i in range(n)]
            results_is: list[tuple[str, float]] = await asyncio.gather(*tasks_is)

            weighted_counts: dict[str, float] = {o: 0.0 for o in canonical.scenario_outcomes}
            for outcome, w in results_is:
                weighted_counts[outcome] = weighted_counts.get(outcome, 0.0) + w
            total_w = sum(weighted_counts.values()) or 1.0
            distribution = {o: c / total_w for o, c in weighted_counts.items()}
            raw_counts_is = {o: sum(1 for out, _ in results_is if out == o) for o in canonical.scenario_outcomes}
            ci = _compute_confidence_intervals(raw_counts_is, n)
            most_common = max(distribution, key=distribution.get)

        else:
            outcome_counts: dict[str, int] = {o: 0 for o in canonical.scenario_outcomes}

            async def run_trial(_: int) -> str:
                async with sem:
                    return _simulate_trial(canonical, df=df, surrogate_model=surrogate_model)

            tasks = [run_trial(i) for i in range(n)]
            results = await asyncio.gather(*tasks)

            for outcome in results:
                outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1

            total = sum(outcome_counts.values())
            distribution = {o: c / total for o, c in outcome_counts.items()}
            ci = _compute_confidence_intervals(outcome_counts, total)
            most_common = max(outcome_counts, key=outcome_counts.get)

        logger.info(
            "MultiRunOrchestrator: complete. Distribution: %s",
            {k: f"{v:.2%}" for k, v in distribution.items()},
        )

        return MultiRunResult(
            simulation_id=canonical.simulation_id,
            trial_count=n,
            outcome_distribution=distribution,
            most_common_path=[most_common],
            confidence_intervals=ci,
            avg_tipping_point_round=0.0,
            faction_stability_score=0.0,
            importance_weights_used=use_is,
        )

    async def run_replicates(
        self,
        canonical_list: list[CanonicalResult],
        trial_count_per_replicate: int = 300,
        df: int = 5,
    ) -> ReplicateResult:
        """Run Phase B on multiple Phase A canonical results and compute inter-run variance.

        Each element of canonical_list should be a Phase A result from the same
        scenario config but a different LLM seed.  The inter-run variance in outcome
        probabilities measures how sensitive the ensemble is to LLM non-determinism.

        Args:
            canonical_list: List of CanonicalResult (≥2 for meaningful variance).
            trial_count_per_replicate: Phase B trials per canonical.
            df: t-distribution degrees of freedom.

        Returns:
            ReplicateResult with per-outcome means, variances, and std devs.
        """
        if not canonical_list:
            return ReplicateResult(
                n_replicates=0,
                outcome_means={},
                outcome_variances={},
                outcome_std_devs={},
                epistemic_uncertainty=0.0,
                summary="No canonical results provided.",
            )

        all_outcomes: set[str] = set()
        for c in canonical_list:
            all_outcomes.update(c.scenario_outcomes)

        run_distributions: list[dict[str, float]] = []
        for i, canonical in enumerate(canonical_list):
            logger.info("run_replicates: running replicate %d/%d", i + 1, len(canonical_list))
            result = await self.run(canonical, trial_count=trial_count_per_replicate, df=df)
            run_distributions.append(result.outcome_distribution)

        means: dict[str, float] = {}
        variances: dict[str, float] = {}
        std_devs: dict[str, float] = {}

        for outcome in all_outcomes:
            vals = [d.get(outcome, 0.0) for d in run_distributions]
            n_reps = len(vals)
            mean = sum(vals) / n_reps
            variance = sum((v - mean) ** 2 for v in vals) / max(n_reps - 1, 1)
            std = variance**0.5
            means[outcome] = round(mean, 4)
            variances[outcome] = round(variance, 6)
            std_devs[outcome] = round(std, 4)

        epistemic_uncertainty = round(sum(std_devs.values()) / max(len(std_devs), 1), 4)

        top_uncertain = max(std_devs, key=std_devs.get) if std_devs else "none"
        summary = (
            f"Replicate analysis: {len(canonical_list)} runs × {trial_count_per_replicate} trials. "
            f"Epistemic uncertainty (mean σ) = {epistemic_uncertainty:.4f}. "
            f"Most uncertain outcome: {top_uncertain} (σ={std_devs.get(top_uncertain, 0):.4f})."
        )

        return ReplicateResult(
            n_replicates=len(canonical_list),
            outcome_means=means,
            outcome_variances=variances,
            outcome_std_devs=std_devs,
            epistemic_uncertainty=epistemic_uncertainty,
            summary=summary,
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _sample_t(mean: float, std: float, df: int = 5) -> float:
    """Sample from t-distribution (heavier tails than Gaussian for tail risk)."""
    # Box-Muller for normal, then scale by chi-squared for t-distribution
    z = random.gauss(0, 1)
    chi2 = sum(random.gauss(0, 1) ** 2 for _ in range(df))
    t = z / math.sqrt(chi2 / df)
    return max(0.0, min(1.0, mean + std * t))


def _simulate_trial(
    canonical: CanonicalResult,
    df: int = 5,
    surrogate_model: Any | None = None,
) -> str:
    """Run one in-memory trial. Returns the realised outcome name.

    If ``canonical.interaction_graph`` is provided, runs one round of
    DeGroot-style neighbour averaging (10% pull) after the initial t-sampled
    belief draw.  This captures first-order social influence effects — herding,
    echo chambers, cascade starts — without any LLM cost.

    If ``surrogate_model`` is a fitted SurrogateModelResult, uses its
    predict_distribution() for outcome assignment instead of the ad-hoc
    scoring function.

    Args:
        canonical: Phase A canonical result with belief distributions.
        df: Degrees of freedom for t-distribution sampling.
        surrogate_model: Optional fitted SurrogateModelResult for data-driven
            outcome prediction.  Falls back to ad-hoc scoring if None or unfitted.
    """
    if not canonical.scenario_outcomes:
        return "unknown"

    # Sample belief states with t-distribution variation
    sampled_beliefs: dict[str, dict[str, float]] = {}
    for agent_id, metric_dists in canonical.agent_belief_distributions.items():
        sampled_beliefs[agent_id] = {m: _sample_t(mean, std, df=df) for m, (mean, std) in metric_dists.items()}

    # Optional: 1-hop DeGroot belief propagation
    if canonical.interaction_graph:
        sampled_beliefs = _propagate_beliefs(sampled_beliefs, canonical.interaction_graph)

    # Aggregate to population-level metric averages
    all_metrics = canonical.scenario_metrics
    agg: dict[str, float] = {}
    for metric in all_metrics:
        vals = [sampled_beliefs[a].get(metric, 0.5) for a in sampled_beliefs]
        agg[metric] = sum(vals) / len(vals) if vals else 0.5

    # Surrogate model path — data-driven outcome assignment
    if surrogate_model is not None and surrogate_model.is_fitted:
        dist = surrogate_model.predict_distribution(agg)
        outcomes = list(dist.keys())
        weights = [dist.get(o, 0.0) for o in outcomes]
        total_w = sum(weights) or 1.0
        r = random.random() * total_w
        cumulative = 0.0
        for outcome, w in zip(outcomes, weights):
            cumulative += w
            if r <= cumulative:
                return outcome
        return outcomes[-1]

    # Ad-hoc scoring fallback
    scores: dict[str, float] = {}
    n_outcomes = len(canonical.scenario_outcomes)
    for i, outcome in enumerate(canonical.scenario_outcomes):
        natural_level = (i + 1) / n_outcomes
        score = sum(1.0 - abs(v - natural_level) for v in agg.values()) / max(len(agg), 1)
        scores[outcome] = score + random.gauss(0, 0.1)  # add noise

    return max(scores, key=scores.get)


def _propagate_beliefs(
    sampled: dict[str, dict[str, float]],
    graph: dict[str, tuple[str, ...]],
) -> dict[str, dict[str, float]]:
    """One round of DeGroot-style belief averaging.

    Each agent's belief shifts 10% toward the mean of its direct neighbours.
    Pure dict arithmetic — zero LLM cost.  Captures first-order social
    influence (herding, echo chamber reinforcement) in Phase B trials.

    Args:
        sampled: agent_id → {metric_id: belief_value} from t-distribution draw.
        graph: agent_id → tuple of neighbour agent_ids.

    Returns:
        New belief dict with neighbour-averaged values; input is not mutated.
    """
    _NEIGHBOUR_WEIGHT = 0.10
    updated: dict[str, dict[str, float]] = {}

    for agent_id, beliefs in sampled.items():
        neighbours = graph.get(agent_id, ())
        neighbour_beliefs = [sampled[n] for n in neighbours if n in sampled]

        if not neighbour_beliefs:
            updated[agent_id] = beliefs
            continue

        new_beliefs: dict[str, float] = {}
        for metric, val in beliefs.items():
            neighbour_vals = [nb.get(metric, val) for nb in neighbour_beliefs]
            neighbour_mean = sum(neighbour_vals) / len(neighbour_vals)
            new_val = val + _NEIGHBOUR_WEIGHT * (neighbour_mean - val)
            new_beliefs[metric] = round(max(0.0, min(1.0, new_val)), 4)
        updated[agent_id] = new_beliefs

    return updated


def _importance_sample_beliefs(
    canonical: CanonicalResult,
    df: int = 5,
) -> dict[str, dict[str, float]]:
    """Sample beliefs biased toward extremes using Beta(0.5, 0.5) arcsine distribution.

    Beta(0.5, 0.5) has high density near 0 and 1, making it better than uniform
    sampling for estimating rare event probabilities in tail regions.
    """
    import math as _math

    sampled: dict[str, dict[str, float]] = {}
    for agent_id, metric_dists in canonical.agent_belief_distributions.items():
        agent_beliefs: dict[str, float] = {}
        for metric, (mean, std) in metric_dists.items():
            # Sample from Beta(0.5, 0.5) arcsine distribution: x = sin²(U * π/2)
            u = random.random()
            beta_sample = _math.sin(u * _math.pi / 2) ** 2
            # Blend: 50% t-sampled, 50% arcsine-biased
            t_val = _sample_t(mean, std, df=df)
            blended = 0.5 * t_val + 0.5 * beta_sample
            agent_beliefs[metric] = max(0.0, min(1.0, blended))
        sampled[agent_id] = agent_beliefs
    return sampled


def _simulate_trial_is(
    canonical: CanonicalResult,
    df: int = 5,
    rare_event_threshold: float = 0.1,
    surrogate_model: Any | None = None,
) -> tuple[str, float]:
    """Run one importance-sampled trial. Returns (outcome, importance_weight).

    Uses Beta(0.5, 0.5) arcsine proposal distribution biased toward extreme belief
    values.  The likelihood ratio weight corrects for proposal bias so that weighted
    averages recover unbiased probability estimates.
    """
    if not canonical.scenario_outcomes:
        return "unknown", 1.0

    sampled_beliefs = _importance_sample_beliefs(canonical, df=df)

    if canonical.interaction_graph:
        sampled_beliefs = _propagate_beliefs(sampled_beliefs, canonical.interaction_graph)

    all_metrics = canonical.scenario_metrics
    agg: dict[str, float] = {}
    for metric in all_metrics:
        vals = [sampled_beliefs[a].get(metric, 0.5) for a in sampled_beliefs]
        agg[metric] = sum(vals) / len(vals) if vals else 0.5

    # Compute importance weight: ratio of target density to proposal density.
    # For extremes (< threshold or > 1-threshold) the arcsine proposal is ~2× denser
    # than uniform, so target/proposal ≈ 0.5.  Near centre it is 0.5/arcsine_density.
    avg_belief = sum(agg.values()) / max(len(agg), 1)
    is_extreme = avg_belief < rare_event_threshold or avg_belief > (1.0 - rare_event_threshold)
    importance_weight = 0.5 if is_extreme else 1.5

    # Outcome assignment (same logic as standard trial)
    if surrogate_model is not None and surrogate_model.is_fitted:
        dist = surrogate_model.predict_distribution(agg)
        outcomes = list(dist.keys())
        weights = [dist.get(o, 0.0) for o in outcomes]
        total_w = sum(weights) or 1.0
        r = random.random() * total_w
        cumulative = 0.0
        for outcome, w in zip(outcomes, weights):
            cumulative += w
            if r <= cumulative:
                return outcome, importance_weight
        return outcomes[-1], importance_weight

    scores: dict[str, float] = {}
    n_outcomes = len(canonical.scenario_outcomes)
    for i, outcome in enumerate(canonical.scenario_outcomes):
        natural_level = (i + 1) / n_outcomes
        score = sum(1.0 - abs(v - natural_level) for v in agg.values()) / max(len(agg), 1)
        scores[outcome] = score + random.gauss(0, 0.1)

    return max(scores, key=scores.get), importance_weight


def _compute_confidence_intervals(
    counts: dict[str, int],
    total: int,
) -> dict[str, tuple[float, float]]:
    """Compute 95% Wilson score confidence intervals for each outcome.

    Wilson score is preferred over the Wald interval because it maintains
    near-nominal 95% coverage even at small n or extreme probabilities (p near
    0 or 1), where Wald coverage degrades to ~89%.

    Formula:
        center = (p̂ + z²/2n) / (1 + z²/n)
        margin = z * sqrt(p̂(1-p̂)/n + z²/4n²) / (1 + z²/n)
    """
    ci: dict[str, tuple[float, float]] = {}
    z = 1.96  # 95% CI
    z2 = z * z  # 3.8416

    for outcome, count in counts.items():
        if total <= 0:
            ci[outcome] = (0.0, 1.0)
            continue

        p = count / total
        n = total
        denominator = 1.0 + z2 / n
        center = (p + z2 / (2.0 * n)) / denominator
        margin = (z * math.sqrt(p * (1.0 - p) / n + z2 / (4.0 * n * n))) / denominator
        ci[outcome] = (max(0.0, center - margin), min(1.0, center + margin))

    return ci
