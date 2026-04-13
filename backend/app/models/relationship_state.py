"""Multi-dimensional relationship state models.

Implements:
- Sternberg's Triangular Theory (intimacy, passion, commitment)
- Rusbult's Investment Model (satisfaction, alternatives, investment)
- Directional trust (backward-compatible with agent_relationships.trust_score)
- AttachmentStyle (secure / anxious / avoidant / disorganized)

All dataclasses are frozen to enforce immutability.  Use dataclasses.replace()
to create updated states.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# RelationshipState
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RelationshipState:
    """Directional, multi-dimensional relationship state: A's perception of A→B.

    Sternberg dimensions:
        intimacy   — closeness, connectedness, bondedness (0..1)
        passion    — romance / physical / excitement (0..1, decays fast)
        commitment — long-term intention to maintain relationship (0..1)

    Rusbult Investment Model:
        satisfaction  — overall positive appraisal (0..1)
        alternatives  — quality of perceived alternatives (0..1)
        investment    — accumulated resources tied to relationship (0..1)
        rusbult_commitment (property) = clamp(satisfaction - alternatives + investment)

    Trust (asymmetric — Phase 2.2):
        trust              — A's trust toward B  (-1..+1)
        trust_b_perspective — B's trust toward A (-1..+1)
        deception_a_to_b   — A's active deception toward B (0..1)
        deception_b_to_a   — B's active deception toward A (0..1)

    Counters:
        interaction_count — total logged interactions (used for staleness detection)
        rounds_since_change — rounds without significant change (stagnation detection)
    """

    agent_a_id: str
    agent_b_id: str

    # Sternberg triangle
    intimacy: float = 0.1
    passion: float = 0.1
    commitment: float = 0.1

    # Rusbult investment model
    satisfaction: float = 0.1
    alternatives: float = 0.3
    investment: float = 0.05

    # Trust — A's perspective (backward-compatible with agent_relationships.trust_score)
    trust: float = 0.0

    # Asymmetric trust and deception (Phase 2.2)
    trust_b_perspective: float = 0.0   # B's trust toward A
    deception_a_to_b: float = 0.0      # A's active deception of B (0 = honest, 1 = fully deceptive)
    deception_b_to_a: float = 0.0      # B's active deception of A

    # Counters
    interaction_count: int = 0
    rounds_since_change: int = 0

    # ------------------------------------------------------------------
    # Computed properties
    # ------------------------------------------------------------------

    @property
    def rusbult_commitment(self) -> float:
        """Rusbult commitment = satisfaction − alternatives + investment.

        Clamped to [0, 1].
        """
        raw = self.satisfaction - self.alternatives + self.investment
        return max(0.0, min(1.0, raw))

    @property
    def trust_asymmetry(self) -> float:
        """Signed trust gap between perspectives: trust − trust_b_perspective.

        Large positive values indicate A trusts B more than B trusts A.
        """
        return self.trust - self.trust_b_perspective

    @property
    def net_deception(self) -> float:
        """Net deception imbalance: deception_a_to_b − deception_b_to_a.

        Positive = A is more deceptive; negative = B is more deceptive.
        """
        return self.deception_a_to_b - self.deception_b_to_a


# ---------------------------------------------------------------------------
# AttachmentStyle
# ---------------------------------------------------------------------------

_VALID_STYLES = frozenset({"secure", "anxious", "avoidant", "disorganized"})


@dataclass(frozen=True)
class AttachmentStyle:
    """Agent's attachment style, inferred from Big Five traits.

    Dimensions mirror Bartholomew & Horowitz (1991):
        anxiety  — fear of abandonment / rejection sensitivity (0..1)
        avoidance — discomfort with closeness / self-reliance (0..1)

    Derived style:
        secure       — low anxiety, low avoidance
        anxious      — high anxiety, low avoidance
        avoidant     — low anxiety, high avoidance
        disorganized — high anxiety, high avoidance
    """

    agent_id: str
    style: str = "secure"
    anxiety: float = 0.2
    avoidance: float = 0.2

    def __post_init__(self) -> None:
        if self.style not in _VALID_STYLES:
            raise ValueError(f"Invalid attachment style '{self.style}'. Must be one of {sorted(_VALID_STYLES)}")
