"""Emergence Validation Framework dataclasses (Phase 0).

All dataclasses are frozen (immutable) per project coding style.
These models support bias detection, phase transition alerting,
emergence attribution, and per-simulation scoring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BiasProbeResult:
    """Result of an LLM bias probe on a simulation scenario.

    Replaces the simpler ``BiasProbeResult`` in ``emergence_guards.py``
    with richer diagnostic fields for systematic bias detection.

    Attributes:
        session_id: Simulation session UUID.
        scenario: Description of the scenario being probed.
        sample_size: Number of agents sampled for the probe.
        agreement_rate: Fraction of agents holding the same stance.
            Values above 0.7 indicate a bias concern.
        stance_kurtosis: Distribution peakedness of stance values.
            High kurtosis suggests clustering around a single viewpoint.
        persona_compliance: Fraction of agent responses that match
            persona-expected stances (0.0--1.0).
        diversity_index: Shannon entropy of discretised stance buckets.
            Higher values indicate greater opinion diversity.
        bias_detected: Whether the probe flagged systematic LLM bias.
        details: Flexible dict for extra diagnostic info (e.g. per-bucket
            counts, p-values, raw stance distributions).
    """

    session_id: str
    scenario: str
    sample_size: int
    agreement_rate: float
    stance_kurtosis: float
    persona_compliance: float
    diversity_index: float
    bias_detected: bool
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PhaseTransitionAlert:
    """Alert emitted when a metric jumps discontinuously between rounds.

    Phase transitions (sudden regime changes in modularity, opinion
    variance, etc.) may signal genuine emergence or simulation artifacts.

    Attributes:
        session_id: Simulation session UUID.
        round_number: Round in which the jump was detected.
        metric_name: One of ``'modularity'``, ``'opinion_variance'``,
            ``'sentiment_mean'``, or ``'trust_density'``.
        z_score: Standardised magnitude of the change relative to the
            metric's running mean and standard deviation.
        delta: Absolute change from the previous round's value.
        direction: ``'diverging'`` (increasing spread/polarisation) or
            ``'converging'`` (decreasing spread/homogenisation).
        severity: ``'warning'`` (|z| >= 2) or ``'critical'`` (|z| >= 3).
    """

    session_id: str
    round_number: int
    metric_name: str
    z_score: float
    delta: float
    direction: str
    severity: str


@dataclass(frozen=True)
class EmergenceAttribution:
    """Attribution of an observed metric change to causal components.

    Decomposes a metric's total change into exogenous (shock-driven),
    endogenous (agent-interaction-driven), and artifact (LLM bias)
    components.  The ``emergence_ratio`` captures the fraction of change
    that is genuinely emergent (endogenous / total, clamped to 0--1).

    Attributes:
        session_id: Simulation session UUID.
        metric_name: Name of the decomposed metric.
        total_change: Absolute total change over the round range.
        exogenous_component: Portion attributable to injected shocks.
        endogenous_component: Portion attributable to agent interactions
            (true emergence).
        artifact_component: Portion attributable to LLM systematic bias.
        emergence_ratio: ``endogenous / total``, clamped to [0, 1].
        round_range: ``(start_round, end_round)`` inclusive.
    """

    session_id: str
    metric_name: str
    total_change: float
    exogenous_component: float
    endogenous_component: float
    artifact_component: float
    emergence_ratio: float
    round_range: tuple[int, int]


@dataclass(frozen=True)
class EmergenceScorecard:
    """Per-simulation summary scorecard for emergence quality.

    Aggregates cascade statistics, polarisation trends, opinion
    entropy, bias contamination, and phase transition counts into
    a single letter grade (A--F).

    Attributes:
        session_id: Simulation session UUID.
        max_cascade_depth: Deepest information cascade observed.
        cascade_count: Total number of cascades triggered.
        avg_cascade_breadth: Average number of agents per cascade.
        polarization_delta: Change in polarisation index from first
            to last round (positive = more polarised).
        echo_chamber_count_delta: Change in echo chamber count from
            first to last round.
        opinion_entropy_trend: Trend direction for opinion Shannon
            entropy: ``'increasing'``, ``'stable'``, or ``'decreasing'``.
        stance_bimodality_p: Hartigan dip test p-value.  Low values
            (< 0.05) indicate statistically significant bimodality.
        emergence_ratio: Average ``EmergenceAttribution.emergence_ratio``
            across all tracked metrics.
        bias_contamination: Aggregate bias score from ``BiasProbeResult``
            (0.0 = no bias detected, 1.0 = fully contaminated).
        transition_count: Number of ``'critical'`` phase transition alerts.
        action_diversity_score: Shannon entropy of the action type
            distribution.  Higher values indicate more diverse agent
            behaviour (max ~3.17 for 12 action types).
        grade: Letter grade summarising emergence quality (A/B/C/D/F).
    """

    session_id: str
    max_cascade_depth: int = 0
    cascade_count: int = 0
    avg_cascade_breadth: float = 0.0
    polarization_delta: float = 0.0
    echo_chamber_count_delta: int = 0
    opinion_entropy_trend: str = "stable"
    stance_bimodality_p: float = 1.0
    emergence_ratio: float = 0.0
    bias_contamination: float = 0.0
    transition_count: int = 0
    action_diversity_score: float = 0.0
    # Phase 1C: structural network change intensity
    network_volatility: float = 0.0
    # Phase 2: recommendation engine impact
    filter_bubble_delta: float = 0.0
    information_flow_efficiency: float = 0.0
    # Phase 3: Emotional State + Cognitive Consistency
    emotional_convergence: float = 0.0  # valence variance reduction first→last round
    belief_revision_rate: float = 0.0  # fraction of beliefs with stance change > 0.1 / total / rounds
    dissonance_prevalence: float = 0.0  # avg dissonance_score at last round
    grade: str = "F"


@dataclass(frozen=True)
class MetricSnapshot:
    """Single metric reading for one simulation round.

    Used internally by the phase transition detector to maintain a
    time series of key simulation metrics per round.

    Attributes:
        round_number: Simulation round this snapshot belongs to.
        modularity: Network modularity (Louvain) at this round.
        opinion_variance: Variance of political stance across agents.
        sentiment_mean: Mean sentiment score across agent posts.
        trust_density: Fraction of possible agent-pair trust edges
            that exist with positive weight.
    """

    round_number: int
    modularity: float = 0.0
    opinion_variance: float = 0.0
    sentiment_mean: float = 0.0
    trust_density: float = 0.0
