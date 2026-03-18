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
    interaction_graph: dict[str, tuple[str, ...]] = dataclasses.field(
        default_factory=dict
    )


@dataclass(frozen=True)
class MultiRunResult:
    simulation_id: str
    trial_count: int
    outcome_distribution: dict[str, float]             # outcome → probability (sums to 1)
    most_common_path: list[str]                        # dominant event sequence
    confidence_intervals: dict[str, tuple[float, float]]  # outcome → 95% CI
    avg_tipping_point_round: float
    faction_stability_score: float


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
    ) -> MultiRunResult:
        """Execute Phase B ensemble.

        Args:
            canonical: Phase A output with belief distributions.
            trial_count: Number of trials (capped at 50,000).
            concurrency: Concurrent asyncio tasks (all in-memory, no I/O).
            df: Degrees of freedom for t-distribution sampling (default 5).

        Returns:
            MultiRunResult with probability distribution and confidence intervals.
        """
        n = _clamp_trial_count(trial_count)
        logger.info(
            "MultiRunOrchestrator: starting %d trials (concurrency=%d, df=%d)",
            n, concurrency, df,
        )

        # Run trials in batches for asyncio concurrency
        outcome_counts: dict[str, int] = {o: 0 for o in canonical.scenario_outcomes}
        tipping_rounds: list[float] = []

        sem = asyncio.Semaphore(concurrency)

        async def run_trial(_: int) -> str:
            async with sem:
                return _simulate_trial(canonical, df=df)

        tasks = [run_trial(i) for i in range(n)]
        results = await asyncio.gather(*tasks)

        for outcome in results:
            outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1

        total = sum(outcome_counts.values())
        distribution = {o: c / total for o, c in outcome_counts.items()}
        ci = _compute_confidence_intervals(outcome_counts, total)

        logger.info(
            "MultiRunOrchestrator: complete. Distribution: %s",
            {k: f"{v:.2%}" for k, v in distribution.items()},
        )

        return MultiRunResult(
            simulation_id=canonical.simulation_id,
            trial_count=n,
            outcome_distribution=distribution,
            most_common_path=[max(outcome_counts, key=outcome_counts.get)],
            confidence_intervals=ci,
            avg_tipping_point_round=float(sum(tipping_rounds) / len(tipping_rounds)) if tipping_rounds else 0.0,
            faction_stability_score=0.0,  # populated in future enhancement
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


def _simulate_trial(canonical: CanonicalResult, df: int = 5) -> str:
    """Run one in-memory trial. Returns the realised outcome name.

    If ``canonical.interaction_graph`` is provided, runs one round of
    DeGroot-style neighbour averaging (10% pull) after the initial t-sampled
    belief draw.  This captures first-order social influence effects — herding,
    echo chambers, cascade starts — without any LLM cost.

    Args:
        canonical: Phase A canonical result with belief distributions.
        df: Degrees of freedom for t-distribution sampling.
    """
    if not canonical.scenario_outcomes:
        return "unknown"

    # Sample belief states with t-distribution variation
    sampled_beliefs: dict[str, dict[str, float]] = {}
    for agent_id, metric_dists in canonical.agent_belief_distributions.items():
        sampled_beliefs[agent_id] = {
            m: _sample_t(mean, std, df=df)
            for m, (mean, std) in metric_dists.items()
        }

    # Optional: 1-hop DeGroot belief propagation
    if canonical.interaction_graph:
        sampled_beliefs = _propagate_beliefs(sampled_beliefs, canonical.interaction_graph)

    # Aggregate to population-level metric averages
    all_metrics = canonical.scenario_metrics
    agg: dict[str, float] = {}
    for metric in all_metrics:
        vals = [sampled_beliefs[a].get(metric, 0.5) for a in sampled_beliefs]
        agg[metric] = sum(vals) / len(vals) if vals else 0.5

    # Map metric state to outcome using simple scoring
    scores: dict[str, float] = {}
    n_outcomes = len(canonical.scenario_outcomes)
    for i, outcome in enumerate(canonical.scenario_outcomes):
        natural_level = (i + 1) / n_outcomes
        score = sum(
            1.0 - abs(v - natural_level)
            for v in agg.values()
        ) / max(len(agg), 1)
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


def _compute_confidence_intervals(
    counts: dict[str, int],
    total: int,
) -> dict[str, tuple[float, float]]:
    """Compute 95% Wilson score confidence intervals for each outcome."""
    ci = {}
    z = 1.96  # 95% CI
    for outcome, count in counts.items():
        p = count / total if total > 0 else 0.0
        margin = z * math.sqrt(p * (1 - p) / total) if total > 0 else 0.0
        ci[outcome] = (max(0.0, p - margin), min(1.0, p + margin))
    return ci
