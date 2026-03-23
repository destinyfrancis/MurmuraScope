"""Emotional state, belief system, and cognitive dissonance models (Phase 3)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EmotionalState:
    """Per-agent emotional state at a given simulation round.

    Uses the Valence-Arousal-Dominance (VAD) model.

    Attributes:
        agent_id: Database ID of the agent.
        session_id: Simulation session UUID.
        round_number: Simulation round this state belongs to.
        valence: Emotional positivity — -1 (very negative) to +1 (very positive).
        arousal: Activation level — 0 (calm/sleepy) to 1 (excited/agitated).
        dominance: Control feeling — 0 (submissive/powerless) to 1 (dominant/powerful).
    """

    agent_id: int
    session_id: str
    round_number: int
    valence: float = 0.0  # -1 (negative) to +1 (positive)
    arousal: float = 0.3  # 0 (calm) to 1 (excited)
    dominance: float = 0.4  # 0 (submissive) to 1 (dominant)


@dataclass(frozen=True)
class Belief:
    """An agent's belief on a single topic.

    Attributes:
        topic: One of CORE_BELIEF_TOPICS.
        stance: Position on topic — -1 (strongly against) to +1 (strongly for).
        confidence: Certainty level — 0 (uncertain) to 1 (certain).
        evidence_count: Number of pieces of evidence processed for this topic.
        last_updated: Round number when this belief was last updated.
    """

    topic: str  # one of 6 core topics
    stance: float = 0.0  # -1 to +1
    confidence: float = 0.5  # 0 to 1
    evidence_count: int = 0
    last_updated: int = 0  # round number


@dataclass(frozen=True)
class BeliefState:
    """Transient in-memory view of an agent's belief set.

    NOT directly persisted — the DB stores individual Belief rows.
    Constructed on-demand via SELECT ... WHERE session_id=? AND agent_id=?
    AND round_number=?

    Attributes:
        agent_id: Database ID of the agent.
        session_id: Simulation session UUID.
        beliefs: Tuple of up to 8 active beliefs (max 8 constraint).
    """

    agent_id: int
    session_id: str
    beliefs: tuple[Belief, ...] = ()  # max 8 active beliefs


@dataclass(frozen=True)
class CognitiveDissonance:
    """Detected cognitive dissonance for an agent at a given round.

    Attributes:
        agent_id: Database ID of the agent.
        session_id: Simulation session UUID.
        round_number: Simulation round this record belongs to.
        dissonance_score: Composite score from 0 (consistent) to 1 (severe).
        conflicting_pairs: Pairs of conflicting topic names.
        action_belief_gap: Gap between recent actions and beliefs (0–1).
        resolution_strategy: How the agent resolved the dissonance.
            One of: ``'denial'``, ``'rationalization'``, ``'belief_change'``,
            ``'none'``.
    """

    agent_id: int
    session_id: str
    round_number: int
    dissonance_score: float = 0.0  # 0 to 1
    conflicting_pairs: tuple[tuple[str, str], ...] = ()
    action_belief_gap: float = 0.0
    resolution_strategy: str = "none"  # denial | rationalization | belief_change | none


# ---------------------------------------------------------------------------
# 6 core belief topics for HK society simulation
# ---------------------------------------------------------------------------

CORE_BELIEF_TOPICS: tuple[str, ...] = (
    "property_outlook",
    "economy_outlook",
    "immigration_stance",
    "government_trust",
    "social_stability",
    "ai_impact",
)

# Expected correlation matrix between belief topics.
# Positive value: beliefs should move together.
# Negative value: beliefs tend to move in opposition.
BELIEF_CORRELATIONS: dict[tuple[str, str], float] = {
    ("property_outlook", "economy_outlook"): 0.6,
    ("economy_outlook", "government_trust"): 0.4,
    ("immigration_stance", "social_stability"): -0.3,
    ("government_trust", "social_stability"): 0.5,
}

# Income bracket string → quartile integer mapping (AgentProfile stores string)
INCOME_QUARTILE: dict[str, int] = {
    "低收入": 0,
    "中低收入": 1,
    "中收入": 2,
    "中高收入": 3,
    "高收入": 4,
}
