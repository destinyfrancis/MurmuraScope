"""Recommendation engine models (Phase 2).

All dataclasses are frozen (immutable) per project coding style.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FeedAlgorithm(str, Enum):
    """Supported feed ranking algorithms."""

    CHRONOLOGICAL = "chronological"
    ENGAGEMENT_FIRST = "engagement_first"
    ECHO_CHAMBER = "echo_chamber"


# Default scoring weights per algorithm.
# Keys: relevance, recency, engagement, social_affinity, controversy.
ALGORITHM_WEIGHTS: dict[FeedAlgorithm, dict[str, float]] = {
    FeedAlgorithm.CHRONOLOGICAL: {
        "relevance": 0.0,
        "recency": 1.0,
        "engagement": 0.0,
        "social_affinity": 0.0,
        "controversy": 0.0,
    },
    FeedAlgorithm.ENGAGEMENT_FIRST: {
        "relevance": 0.10,
        "recency": 0.10,
        "engagement": 0.35,
        "social_affinity": 0.25,
        "controversy": 0.20,
    },
    FeedAlgorithm.ECHO_CHAMBER: {
        "relevance": 0.30,
        "recency": 0.10,
        "engagement": 0.15,
        "social_affinity": 0.45,
        "controversy": 0.00,
    },
}


@dataclass(frozen=True)
class FilterBubbleIndex:
    """Per-agent filter bubble metrics for one round.

    Attributes:
        agent_id: Agent primary key.
        round_number: Simulation round.
        exposure_diversity: Shannon entropy of stance distribution in feed.
            Higher = more diverse viewpoints exposed.
        stance_divergence: Mean |agent_stance - feed_avg_stance|.
            Higher = feed diverges more from agent's own stance.
        source_concentration: Herfindahl index of authors.
            Higher = feed dominated by fewer authors (less source diversity).
        bubble_score: 1 - normalised exposure_diversity.
            0.0 = open information environment, 1.0 = fully trapped in bubble.
    """

    agent_id: int
    round_number: int
    exposure_diversity: float
    stance_divergence: float
    source_concentration: float
    bubble_score: float


@dataclass(frozen=True)
class FilterBubbleReport:
    """Session-level aggregate filter bubble snapshot.

    Attributes:
        session_id: Simulation session UUID.
        round_number: Simulation round.
        avg_bubble_score: Mean bubble_score across all agents.
        median_bubble_score: Median bubble_score.
        pct_in_bubble: Fraction of agents with bubble_score > 0.7.
        algorithm_name: Feed algorithm used (e.g. 'engagement_first').
        gini_coefficient: Gini coefficient of bubble score distribution.
            0 = perfect equality, 1 = maximum inequality.
    """

    session_id: str
    round_number: int
    avg_bubble_score: float
    median_bubble_score: float
    pct_in_bubble: float
    algorithm_name: str
    gini_coefficient: float


@dataclass(frozen=True)
class ViralityScore:
    """Virality metrics for a single post (information cascade root).

    Attributes:
        post_id: Unique post identifier (simulation_actions.id as string).
        session_id: Simulation session UUID.
        cascade_depth: Maximum spread_depth in the cascade tree.
        cascade_breadth: Number of distinct agents that shared/reposted.
        velocity: cascade_breadth / rounds_since_creation.
        reproduction_number: avg reposts per exposed agent (R₀ analogue).
        cross_cluster_reach: Fraction of clusters that received the post.
        virality_index: Composite score = 0.3×velocity_norm
            + 0.3×R₀_norm + 0.4×cross_cluster_reach.
    """

    post_id: str
    session_id: str
    cascade_depth: int
    cascade_breadth: int
    velocity: float
    reproduction_number: float
    cross_cluster_reach: float
    virality_index: float
