"""Relationship dynamics engine for multi-dimensional relationship simulation.

Implements:
- initialize_relationship() — from KG edge description
- update_from_interaction() — per-round update (immutable, dataclasses.replace)
- compute_gottman_score()   — Four Horsemen scoring
- batch_update()            — batch update pattern (mirrors EmotionalEngine)
- infer_attachment_style()  — Big Five → AttachmentStyle (pure function, no LLM)

All state transitions use dataclasses.replace() — never mutate in-place.
LLM cost: 0 (all rule-based).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from backend.app.models.relationship_state import AttachmentStyle, RelationshipState
from backend.app.utils.logger import get_logger

logger = get_logger("relationship_engine")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Round duration in days — calibration anchor for decay rate scaling.
# Set ROUND_DURATION_DAYS to match your scenario's time granularity:
#   7  → 1 round = 1 week  (default, matches base rates below)
#  30  → 1 round = 1 month
#   1  → 1 round = 1 day
ROUND_DURATION_DAYS: int = 7

# Base decay rates calibrated per week (ROUND_DURATION_DAYS = 7).
#
# Literature grounding (Sprecher & Regan 1998; Sternberg 1986):
#   Passionate love   half-life ≈ 18 months = 78 weeks  → 0.5^(1/78)  ≈ 0.991
#   Intimacy          half-life ≈  5 years  = 260 weeks → 0.5^(1/260) ≈ 0.997
#   Trust             half-life ≈  2 years  = 104 weeks → 0.5^(1/104) ≈ 0.993
#   Commitment        half-life ≈ 10 years  = 520 weeks → 0.5^(1/520) ≈ 0.9987
#
# Previous values (0.97 / 0.93 / 0.99 / 0.95) produced a half-life of ~2-10 weeks —
# roughly 10× too fast relative to empirical data.
# Phase 2 correction: 0.999/week gives t½ ≈ 13.3 years, not 10 years.
# 0.9987/week: ln(0.5)/ln(0.9987) = 533 weeks = 10.25 years ✓
_BASE_INTIMACY_DECAY_PER_WEEK: float = 0.997
_BASE_PASSION_DECAY_PER_WEEK: float = 0.991
_BASE_COMMITMENT_DECAY_PER_WEEK: float = 0.9987
_BASE_TRUST_DECAY_PER_WEEK: float = 0.993

# Legacy aliases — kept for backward compatibility (tests / external imports)
_INTIMACY_DECAY = _BASE_INTIMACY_DECAY_PER_WEEK
_PASSION_DECAY = _BASE_PASSION_DECAY_PER_WEEK
_COMMITMENT_DECAY = _BASE_COMMITMENT_DECAY_PER_WEEK
_TRUST_DECAY = _BASE_TRUST_DECAY_PER_WEEK


def _decay_rate(base_weekly: float, round_days: int) -> float:
    """Scale a weekly decay rate to the actual round duration.

    Args:
        base_weekly: Decay multiplier calibrated per 7-day week (e.g. 0.97).
        round_days: Duration of one simulation round in days.

    Returns:
        Decay multiplier appropriate for one round of ``round_days`` length.
    """
    weeks = round_days / 7.0
    return base_weekly**weeks


# Sensitivity coefficients for interaction updates
_INTIMACY_SENSITIVITY = 0.04
_PASSION_SENSITIVITY = 0.06
_TRUST_SENSITIVITY = 0.08
_SATISFACTION_SENSITIVITY = 0.05
_INVESTMENT_INCREMENT = 0.01  # small accumulation per positive interaction

# Gottman horsemen scaling — calibrated to Gottman & Levenson (1994, 2000)
# Predictive ordering per divorce prediction research:
#   contempt (1.5×) — unique strongest predictor; only horseman that predicts
#                      illness too; effect size d ≈ 1.3 vs. 0.6–0.8 for others
#                      (Gottman & Levenson 2000, "Timing of Divorce")
#   stonewalling (0.9×) — physiological flooding; strongest predictor of
#                          *late-stage* dissolution (7+ year marriages)
#   criticism (0.8×) — common, moderate predictor; triggers early deterioration
#   defensiveness (0.5×) — mostly reactive to the above three; least
#                            independently predictive when occurring alone
# Previous: contempt 1.2 / criticism 0.8 / defensiveness 0.7 / stonewalling 0.6
# Error: stonewalling was incorrectly ranked lower than defensiveness
_HORSEMAN_CONTEMPT_SCALE = 1.5
_HORSEMAN_CRIT_SCALE = 0.8
_HORSEMAN_DEF_SCALE = 0.5
_HORSEMAN_STONE_SCALE = 0.9

# Edge description → relationship seed keywords
_ROMANTIC_KEYWORDS = frozenset(
    {
        "romantic",
        "partner",
        "lover",
        "spouse",
        "husband",
        "wife",
        "girlfriend",
        "boyfriend",
        "fiance",
        "married",
        "dating",
        "戀人",
        "夫妻",
        "情侶",
        "配偶",
    }
)
_FRIENDSHIP_KEYWORDS = frozenset(
    {
        "friend",
        "ally",
        "colleague",
        "associate",
        "朋友",
        "盟友",
    }
)
_CONFLICT_KEYWORDS = frozenset(
    {
        "enemy",
        "rival",
        "opponent",
        "hostile",
        "antagonist",
        "敵人",
        "對手",
        "衝突",
    }
)
_FAMILY_KEYWORDS = frozenset(
    {
        "family",
        "sibling",
        "parent",
        "child",
        "brother",
        "sister",
        "father",
        "mother",
        "家人",
        "兄弟",
        "姊妹",
    }
)


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# Public pure function: infer_attachment_style
# ---------------------------------------------------------------------------


def infer_attachment_style(
    agent_id: str,
    neuroticism: float,
    agreeableness: float,
    openness: float,
) -> AttachmentStyle:
    """Derive attachment style from Big Five traits (pure function, no LLM).

    Mapping (Bartholomew & Horowitz quadrant model):
        high N + high A  → anxious
        low A + low O    → avoidant
        high N + low A   → disorganized
        otherwise        → secure

    Thresholds chosen to reproduce empirical prevalence (~55% secure).

    Args:
        agent_id: Agent identifier for the returned AttachmentStyle.
        neuroticism: Big Five N score (0..1).
        agreeableness: Big Five A score (0..1).
        openness: Big Five O score (0..1).

    Returns:
        An immutable AttachmentStyle.
    """
    high_n = neuroticism > 0.7
    low_n = neuroticism < 0.4
    high_a = agreeableness > 0.65
    low_a = agreeableness < 0.35
    low_o = openness < 0.35

    # Anxiety ∝ neuroticism; avoidance ∝ (1 - agreeableness)
    anxiety = _clamp(0.1 + 0.8 * neuroticism)
    avoidance = _clamp(0.1 + 0.7 * (1.0 - agreeableness) + 0.2 * (1.0 - openness))

    if high_n and low_a:
        style = "disorganized"
    elif high_n and high_a:
        style = "anxious"
    elif low_a and low_o and not high_n:
        style = "avoidant"
    elif low_n or (not high_n and not low_a):
        style = "secure"
    else:
        style = "secure"

    return AttachmentStyle(
        agent_id=agent_id,
        style=style,
        anxiety=round(anxiety, 4),
        avoidance=round(avoidance, 4),
    )


# ---------------------------------------------------------------------------
# RelationshipEngine
# ---------------------------------------------------------------------------


class RelationshipEngine:
    """Stateless service for relationship state transitions.

    All methods return new RelationshipState instances via dataclasses.replace().
    """

    # ------------------------------------------------------------------
    # initialize_relationship
    # ------------------------------------------------------------------

    def initialize_relationship(
        self,
        agent_a_id: str,
        agent_b_id: str,
        edge_description: str = "",
        initial_trust: float = 0.0,
    ) -> RelationshipState:
        """Create a new RelationshipState seeded from a KG edge description.

        Parses edge_description keywords to set appropriate starting values.

        Args:
            agent_a_id: Source agent ID.
            agent_b_id: Target agent ID.
            edge_description: KG edge label/description (e.g., "romantic partner").
            initial_trust: Optional trust seed from trust_dynamics.

        Returns:
            A fresh immutable RelationshipState.
        """
        desc = edge_description.lower()
        tokens = set(desc.replace(",", " ").replace("_", " ").split())

        is_romantic = bool(tokens & _ROMANTIC_KEYWORDS)
        is_friendship = bool(tokens & _FRIENDSHIP_KEYWORDS)
        is_conflict = bool(tokens & _CONFLICT_KEYWORDS)
        is_family = bool(tokens & _FAMILY_KEYWORDS)

        if is_romantic:
            return RelationshipState(
                agent_a_id=agent_a_id,
                agent_b_id=agent_b_id,
                intimacy=0.55,
                passion=0.65,
                commitment=0.40,
                satisfaction=0.60,
                alternatives=0.20,
                investment=0.35,
                trust=max(initial_trust, 0.3),
            )
        if is_family:
            return RelationshipState(
                agent_a_id=agent_a_id,
                agent_b_id=agent_b_id,
                intimacy=0.50,
                passion=0.10,
                commitment=0.70,
                satisfaction=0.55,
                alternatives=0.15,
                investment=0.60,
                trust=max(initial_trust, 0.2),
            )
        if is_friendship:
            return RelationshipState(
                agent_a_id=agent_a_id,
                agent_b_id=agent_b_id,
                intimacy=0.35,
                passion=0.10,
                commitment=0.30,
                satisfaction=0.45,
                alternatives=0.30,
                investment=0.20,
                trust=max(initial_trust, 0.15),
            )
        if is_conflict:
            return RelationshipState(
                agent_a_id=agent_a_id,
                agent_b_id=agent_b_id,
                intimacy=0.05,
                passion=0.10,
                commitment=0.05,
                satisfaction=0.10,
                alternatives=0.80,
                investment=0.05,
                trust=min(initial_trust, -0.3),
            )

        # Unknown edge type — neutral baseline
        return RelationshipState(
            agent_a_id=agent_a_id,
            agent_b_id=agent_b_id,
            trust=initial_trust,
        )

    # ------------------------------------------------------------------
    # update_from_interaction
    # ------------------------------------------------------------------

    def update_from_interaction(
        self,
        state: RelationshipState,
        interaction_valence: float,
        profile_a: dict[str, Any],
        attachment_style_a: AttachmentStyle | None,
    ) -> RelationshipState:
        """Compute updated RelationshipState for one round.

        Algorithm:
        1. Apply decay (intimacy×0.997, passion×0.991, trust×0.993 toward 0)
        2. Apply interaction effect (Big Five modulated)
        3. Attachment style modulation (anxious → amplifies negative, avoidant → dampens)
        4. Accumulate investment on positive interactions
        5. Increment interaction_count; reset rounds_since_change if significant change

        Args:
            state: Current relationship state.
            interaction_valence: Signed valence of interaction this round (-1..+1).
                                 0.0 = no direct interaction (decay only).
            profile_a: Agent A's personality dict (agreeableness, neuroticism).
            attachment_style_a: Agent A's attachment style (optional).

        Returns:
            New RelationshipState (immutable).
        """
        agreeableness = _clamp(float(profile_a.get("agreeableness", 0.5)))
        neuroticism = _clamp(float(profile_a.get("neuroticism", 0.5)))

        # Attachment modulation multiplier
        att_multiplier = 1.0
        if attachment_style_a is not None:
            if attachment_style_a.style == "anxious":
                # Anxious: amplify both positive and negative (especially negative)
                if interaction_valence < 0:
                    att_multiplier = 1.0 + 0.5 * attachment_style_a.anxiety
                else:
                    att_multiplier = 1.0 + 0.2 * attachment_style_a.anxiety
            elif attachment_style_a.style == "avoidant":
                # Avoidant: dampen all emotional impact
                att_multiplier = max(0.3, 1.0 - 0.4 * attachment_style_a.avoidance)

        # Personality modulation: agreeableness boosts positive, neuroticism amplifies negative
        if interaction_valence >= 0:
            effective_valence = interaction_valence * (1.0 + 0.2 * (agreeableness - 0.5))
        else:
            effective_valence = interaction_valence * (1.0 + 0.3 * (neuroticism - 0.5))

        effective_valence = _clamp(effective_valence * att_multiplier, -1.0, 1.0)

        # 1. Decay — rates scale with ROUND_DURATION_DAYS
        new_intimacy = state.intimacy * _decay_rate(_BASE_INTIMACY_DECAY_PER_WEEK, ROUND_DURATION_DAYS)
        new_passion = state.passion * _decay_rate(_BASE_PASSION_DECAY_PER_WEEK, ROUND_DURATION_DAYS)
        new_trust = state.trust * _decay_rate(_BASE_TRUST_DECAY_PER_WEEK, ROUND_DURATION_DAYS)

        # 2. Interaction effect
        new_intimacy = _clamp(new_intimacy + _INTIMACY_SENSITIVITY * effective_valence)
        new_passion = _clamp(new_passion + _PASSION_SENSITIVITY * effective_valence)
        new_trust = _clamp(new_trust + _TRUST_SENSITIVITY * effective_valence, -1.0, 1.0)
        new_satisfaction = _clamp(state.satisfaction + _SATISFACTION_SENSITIVITY * effective_valence)

        # 3. Investment accumulates slowly on positive interactions
        new_investment = state.investment
        if effective_valence > 0.1:
            new_investment = _clamp(state.investment + _INVESTMENT_INCREMENT * effective_valence)

        # 4. Commitment: decay slightly unless satisfaction is high
        commitment_decay = _decay_rate(_BASE_COMMITMENT_DECAY_PER_WEEK, ROUND_DURATION_DAYS)
        if new_satisfaction > 0.6:
            new_commitment = _clamp(state.commitment * commitment_decay + 0.005)
        else:
            new_commitment = _clamp(state.commitment * commitment_decay)

        # 5. Stagnation detection
        total_change = abs(new_intimacy - state.intimacy) + abs(new_trust - state.trust)
        new_rounds_since_change = 0 if total_change > 0.01 else state.rounds_since_change + 1

        has_interaction = abs(interaction_valence) > 0.05
        new_count = state.interaction_count + (1 if has_interaction else 0)

        return replace(
            state,
            intimacy=round(new_intimacy, 4),
            passion=round(new_passion, 4),
            commitment=round(new_commitment, 4),
            satisfaction=round(new_satisfaction, 4),
            investment=round(new_investment, 4),
            trust=round(new_trust, 4),
            interaction_count=new_count,
            rounds_since_change=new_rounds_since_change,
        )

    # ------------------------------------------------------------------
    # compute_gottman_score
    # ------------------------------------------------------------------

    def compute_gottman_score(
        self,
        interaction_valence: float,
        contempt_signal: float = 0.0,
        defensiveness_signal: float = 0.0,
        stonewalling_signal: float = 0.0,
    ) -> dict[str, float]:
        """Score the Four Horsemen of relationship apocalypse (Gottman 1994).

        Args:
            interaction_valence: Round interaction valence (-1..+1).
            contempt_signal: 0..1 contempt signal (eye-roll, mockery proxy).
            defensiveness_signal: 0..1 defensiveness signal.
            stonewalling_signal: 0..1 stonewalling/withdrawal signal.

        Returns:
            Dict with keys: criticism, contempt, defensiveness, stonewalling.
            Each value is 0..1 (higher = more present).
        """
        # Criticism proxy: strong negative valence without contempt
        criticism = _clamp(_HORSEMAN_CRIT_SCALE * max(0.0, -interaction_valence))
        contempt = _clamp(_HORSEMAN_CONTEMPT_SCALE * contempt_signal)
        defensiveness = _clamp(_HORSEMAN_DEF_SCALE * defensiveness_signal)
        stonewalling = _clamp(_HORSEMAN_STONE_SCALE * stonewalling_signal)
        return {
            "criticism": round(criticism, 4),
            "contempt": round(contempt, 4),
            "defensiveness": round(defensiveness, 4),
            "stonewalling": round(stonewalling, 4),
        }

    # ------------------------------------------------------------------
    # batch_update
    # ------------------------------------------------------------------

    def batch_update(
        self,
        states: dict[tuple[str, str], RelationshipState],
        interactions: dict[tuple[str, str], float],
        profiles: dict[str, Any],
        attachment_styles: dict[str, AttachmentStyle],
    ) -> list[RelationshipState]:
        """Update all relationship states for one round.

        Follows the same pattern as EmotionalEngine.batch_update():
        pure in-memory computation, no DB I/O (caller persists results).

        Args:
            states: Current relationship states keyed by (agent_a_id, agent_b_id).
            interactions: Valence per pair this round (may be empty for pairs
                          with no direct interaction — decay-only update).
            profiles: Agent personality dicts keyed by agent_id.
            attachment_styles: Attachment styles keyed by agent_id.

        Returns:
            List of updated RelationshipState objects.
        """
        updated: list[RelationshipState] = []
        for (aid, bid), state in states.items():
            valence = float(interactions.get((aid, bid), 0.0))
            profile = profiles.get(aid, {})
            attachment = attachment_styles.get(aid)
            new_state = self.update_from_interaction(
                state=state,
                interaction_valence=valence,
                profile_a=profile,
                attachment_style_a=attachment,
            )
            updated.append(new_state)
        return updated

    # ------------------------------------------------------------------
    # update_asymmetric_trust (Phase 2.2)
    # ------------------------------------------------------------------

    def update_asymmetric_trust(
        self,
        state: RelationshipState,
        *,
        perspective: str = "a",
        trust_delta: float = 0.0,
        deception_delta: float = 0.0,
    ) -> RelationshipState:
        """Update trust or deception from a specific perspective.

        Args:
            state: Current relationship state.
            perspective: ``"a"`` to update A's perspective (trust, deception_a_to_b),
                         ``"b"`` to update B's perspective (trust_b_perspective,
                         deception_b_to_a).
            trust_delta: Signed change in trust (-1..+1 range, clamped).
            deception_delta: Signed change in deception level (0..1, clamped).

        Returns:
            New RelationshipState with updated asymmetric fields.

        Example::

            # Agent A discovers Agent B is lying — B's deception rises:
            state = engine.update_asymmetric_trust(
                state,
                perspective="b",
                deception_delta=0.2,
                trust_delta=-0.15,
            )
        """
        if perspective == "a":
            new_trust = _clamp(state.trust + trust_delta, -1.0, 1.0)
            new_deception_a = _clamp(state.deception_a_to_b + deception_delta)
            return replace(
                state,
                trust=round(new_trust, 4),
                deception_a_to_b=round(new_deception_a, 4),
            )
        else:
            new_trust_b = _clamp(state.trust_b_perspective + trust_delta, -1.0, 1.0)
            new_deception_b = _clamp(state.deception_b_to_a + deception_delta)
            return replace(
                state,
                trust_b_perspective=round(new_trust_b, 4),
                deception_b_to_a=round(new_deception_b, 4),
            )
