"""Emotional state engine: VAD model updates per simulation round (Phase 3).

Implements the Valence-Arousal-Dominance model with:
- Inertia from previous round
- Social contagion from feed sentiment
- Macro shock signal injection
- Big Five personality modulation
"""

from __future__ import annotations

import random
from dataclasses import replace
from typing import Any

from backend.app.models.emotional_state import (
    INCOME_QUARTILE,
    EmotionalState,
)
from backend.app.utils.logger import get_logger

logger = get_logger("emotional_engine")


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp *value* to [lo, hi]."""
    return max(lo, min(hi, value))


class EmotionalEngine:
    """VAD emotional state updater for simulation agents."""

    # Inertia / influence coefficients
    VALENCE_INERTIA: float = 0.7  # α — how much previous valence persists
    SOCIAL_INFLUENCE: float = 0.15  # β — feed sentiment effect
    MACRO_INFLUENCE: float = 0.10  # γ — macro shock effect
    PERSONAL_INFLUENCE: float = 0.05  # δ — personal event effect

    AROUSAL_DECAY: float = 0.6  # α_a — decay toward baseline
    AROUSAL_CHANGE_SENSITIVITY: float = 0.25  # β_a — arousal driven by valence change
    CONTROVERSY_SENSITIVITY: float = 0.15  # γ_a — arousal from controversy

    DOMINANCE_SOCIAL_VALIDATION: float = 0.1  # social validation coefficient

    def initialize_state(
        self,
        agent_id: int,
        session_id: str,
        profile: Any,
        rng: random.Random | None = None,
    ) -> EmotionalState:
        """Create the initial VAD emotional state for an agent.

        Uses Big Five traits to initialise values:
        - valence = extraversion minus neuroticism effect + noise
        - arousal = extraversion-driven baseline + noise
        - dominance = income-quartile driven + noise

        Args:
            agent_id: Database agent ID.
            session_id: Simulation session UUID.
            profile: AgentProfile with Big Five + income fields.
            rng: Optional RNG for reproducible noise (defaults to module random).

        Returns:
            Freshly initialised :class:`EmotionalState`.
        """
        _rng = rng or random
        noise = lambda sigma: _rng.gauss(0, sigma)  # noqa: E731

        extraversion = getattr(profile, "extraversion", 0.5)
        neuroticism = getattr(profile, "neuroticism", 0.5)
        income_bracket = getattr(profile, "income_bracket", "中收入")

        # Valence: extraverted → positive, neurotic → negative
        raw_valence = 0.1 * (extraversion - neuroticism) + noise(0.1)
        valence = _clamp(raw_valence, -1.0, 1.0)

        # Arousal: extraverted agents are more activated
        raw_arousal = 0.3 + 0.2 * extraversion + noise(0.05)
        arousal = _clamp(raw_arousal, 0.0, 1.0)

        # Dominance: income-proxied sense of control
        income_q = INCOME_QUARTILE.get(income_bracket, 2)
        raw_dominance = 0.4 + 0.1 * (income_q / 4) + noise(0.05)
        dominance = _clamp(raw_dominance, 0.0, 1.0)

        return EmotionalState(
            agent_id=agent_id,
            session_id=session_id,
            round_number=0,
            valence=round(valence, 4),
            arousal=round(arousal, 4),
            dominance=round(dominance, 4),
        )

    def update_state(
        self,
        state: EmotionalState,
        profile: Any,
        feed_sentiment_avg: float,
        macro_shock_valence: float,
        personal_event_valence: float,
        controversy_exposure: float,
        pending_arousal_delta: float = 0.0,
        relationship_crisis: bool = False,
    ) -> EmotionalState:
        """Compute new VAD state from previous state and round inputs.

        Formula:
            v_t = α·v_(t-1) + β·feed_avg + γ·macro + δ·personal + noise
            a_t = α_a·(a_(t-1) - baseline) + β_a·|Δv| + γ_a·controversy
                  + pending_delta + baseline
            d_t ≈ inertia_weighted update from social validation signals

        Big Five modulation:
        - High neuroticism → amplifies negative valence changes
        - High openness → reduces confirmation bias (handled in BeliefSystem)
        - High agreeableness → increases social influence weight
        - High extraversion → faster arousal recovery

        Args:
            state: Current round emotional state.
            profile: AgentProfile with Big Five fields.
            feed_sentiment_avg: Mean valence of feed posts this round (-1..+1).
            macro_shock_valence: Valence signal from macro shocks (-1..+1).
            personal_event_valence: Personal event valence (decision outcomes).
            controversy_exposure: Fraction of feed posts that are controversial.
            pending_arousal_delta: Carried-over arousal boost from dissonance denial.
            relationship_crisis: When True, applies valence penalty (-0.1) and
                arousal boost (+0.15) to model relationship dissolution stress.

        Returns:
            New :class:`EmotionalState` for next round.
        """
        neuroticism = _clamp(getattr(profile, "neuroticism", 0.5), 0.0, 1.0)
        agreeableness = _clamp(getattr(profile, "agreeableness", 0.5), 0.0, 1.0)
        extraversion = _clamp(getattr(profile, "extraversion", 0.5), 0.0, 1.0)

        # Modulate coefficients by personality
        # Agreeableness boosts social influence (more receptive to peers)
        social_coef = self.SOCIAL_INFLUENCE * (1.0 + 0.3 * (agreeableness - 0.5))
        # Neuroticism amplifies macro shock sensitivity
        macro_coef = self.MACRO_INFLUENCE * (1.0 + 0.4 * (neuroticism - 0.5))
        # --- Valence update ---
        # Coefficients (VALENCE_INERTIA + social_coef + macro_coef + PERSONAL_INFLUENCE)
        # are calibrated for the neutral personality (N=A=0.5), where they sum to ≈1.0.
        # At extreme personalities the sum slightly exceeds 1.0; the _clamp() call
        # acts as the natural absorbing boundary and prevents unbounded drift.
        weighted_sum = (
            self.VALENCE_INERTIA * state.valence
            + social_coef * feed_sentiment_avg
            + macro_coef * macro_shock_valence
            + self.PERSONAL_INFLUENCE * personal_event_valence
        )
        # Neurotic agents experience negative valence changes more strongly.
        delta = weighted_sum - state.valence
        if delta < 0:
            delta *= 1.0 + 0.3 * neuroticism
        new_valence = _clamp(state.valence + delta, -1.0, 1.0)

        # --- Arousal update ---
        valence_change = abs(new_valence - state.valence)
        # Baseline arousal around 0.3; extraverted agents return faster
        baseline_arousal = 0.25 + 0.1 * extraversion
        # Extraversion accelerates decay toward baseline
        decay = self.AROUSAL_DECAY * (1.0 + 0.2 * extraversion)
        decay = _clamp(decay, 0.0, 0.95)

        new_arousal = _clamp(
            decay * (state.arousal - baseline_arousal)
            + baseline_arousal
            + self.AROUSAL_CHANGE_SENSITIVITY * valence_change
            + self.CONTROVERSY_SENSITIVITY * controversy_exposure
            + pending_arousal_delta,
            0.0,
            1.0,
        )

        # --- Relationship crisis penalty (Task 10) ---
        if relationship_crisis:
            new_valence = _clamp(new_valence - 0.1, -1.0, 1.0)
            new_arousal = _clamp(new_arousal + 0.15, 0.0, 1.0)

        # --- Dominance update ---
        # Social validation: positive valence + high agreeableness → mild dominance boost
        social_validation = 0.0
        if new_valence > 0.3:
            social_validation = self.DOMINANCE_SOCIAL_VALIDATION * agreeableness * new_valence
        elif new_valence < -0.5:
            # Feeling powerless when mood is very negative
            social_validation = -self.DOMINANCE_SOCIAL_VALIDATION * 0.5

        new_dominance = _clamp(
            0.85 * state.dominance + 0.15 * (0.4 + social_validation),
            0.0,
            1.0,
        )

        return replace(
            state,
            round_number=state.round_number + 1,
            valence=round(new_valence, 4),
            arousal=round(new_arousal, 4),
            dominance=round(new_dominance, 4),
        )

    async def batch_update(
        self,
        session_id: str,
        round_number: int,
        agent_states: dict[int, EmotionalState],
        profiles: dict[int, Any],
        feed_data: dict[int, dict[str, float]],
        macro_valence: float,
        pending_deltas: dict[int, float],
        db: Any,
        crisis_agents: frozenset[int] | None = None,
    ) -> list[EmotionalState]:
        """Update all agents' emotional states for one round.

        Args:
            session_id: Simulation session UUID.
            round_number: Current round number.
            agent_states: Previous-round states keyed by agent_id.
            profiles: AgentProfile objects keyed by agent_id.
            feed_data: Per-agent feed stats: {agent_id: {sentiment_avg, controversy}}.
            macro_valence: Global macro shock valence signal.
            pending_deltas: Arousal deltas from previous dissonance denial.
            db: Open aiosqlite connection (for persist call).
            crisis_agents: Set of agent IDs currently in a relationship crisis.
                When provided, these agents receive a valence penalty and arousal
                boost via ``update_state(relationship_crisis=True)``.

        Returns:
            List of updated :class:`EmotionalState` objects.
        """
        updated: list[EmotionalState] = []
        _crisis_set: frozenset[int] = crisis_agents or frozenset()

        for agent_id, state in agent_states.items():
            profile = profiles.get(agent_id)
            if profile is None:
                updated.append(replace(state, round_number=round_number))
                continue

            feed_info = feed_data.get(agent_id, {})
            feed_sentiment_avg = float(feed_info.get("sentiment_avg", 0.0))
            controversy = float(feed_info.get("controversy", 0.0))
            personal_valence = float(feed_info.get("personal_valence", 0.0))
            pending_delta = float(pending_deltas.get(agent_id, 0.0))

            # Override round_number to be previous (update_state increments)
            state_at_prev = replace(state, round_number=round_number - 1)

            new_state = self.update_state(
                state=state_at_prev,
                profile=profile,
                feed_sentiment_avg=feed_sentiment_avg,
                macro_shock_valence=macro_valence,
                personal_event_valence=personal_valence,
                controversy_exposure=controversy,
                pending_arousal_delta=pending_delta,
                relationship_crisis=agent_id in _crisis_set,
            )
            updated.append(new_state)

        await self.persist_states(updated, db)
        return updated

    async def persist_states(
        self,
        states: list[EmotionalState],
        db: Any,
    ) -> None:
        """Persist a batch of emotional states to ``emotional_states`` table.

        Uses ``INSERT OR REPLACE`` for idempotency.
        """
        if not states:
            return
        rows = [(s.session_id, s.agent_id, s.round_number, s.valence, s.arousal, s.dominance) for s in states]
        await db.executemany(
            """INSERT OR REPLACE INTO emotional_states
               (session_id, agent_id, round_number, valence, arousal, dominance)
               VALUES (?, ?, ?, ?, ?, ?)""",
            rows,
        )
        await db.commit()

    async def load_states(
        self,
        session_id: str,
        round_number: int,
        db: Any,
    ) -> dict[int, EmotionalState]:
        """Load all emotional states for a session/round.

        Returns:
            Dict mapping agent_id → :class:`EmotionalState`.
        """
        cursor = await db.execute(
            """SELECT agent_id, valence, arousal, dominance
               FROM emotional_states
               WHERE session_id = ? AND round_number = ?""",
            (session_id, round_number),
        )
        rows = await cursor.fetchall()
        result: dict[int, EmotionalState] = {}
        for row in rows:
            agent_id = int(row[0])
            result[agent_id] = EmotionalState(
                agent_id=agent_id,
                session_id=session_id,
                round_number=round_number,
                valence=float(row[1]),
                arousal=float(row[2]),
                dominance=float(row[3]),
            )
        return result
