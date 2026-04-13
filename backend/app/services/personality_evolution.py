"""Personality evolution engine for MurmuraScope.

Tracks Big Five trait drift across simulation rounds. Agents' personalities
are not static — repeated interactions, emotional experiences, and significant
events gradually shift trait scores within realistic bounds.

Algorithm:
  1. Each round, compute a ``drift_delta`` for each trait based on emotional
     state, recent interaction sentiment, and significant events.
  2. Apply delta with a ``plasticity`` damper (0.0 = frozen, 1.0 = fully plastic).
  3. Clamp all traits to [0.0, 1.0].
  4. Log significant drift (>0.05 per trait per round) to ``personality_evolution_log``.

Plasticity model:
  - Younger agents (proxy: low neuroticism) have higher plasticity.
  - Agents in emotional crisis see heightened plasticity for neuroticism.
  - All traits converge toward 0.5 over time (regression to mean) unless driven
    by experiential events.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from backend.app.utils.logger import get_logger

logger = get_logger("personality_evolution")

# Trait names (Big Five)
_TRAITS = ("openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism")

# Maximum per-round drift magnitude for any single trait
_MAX_DRIFT_PER_ROUND = 0.02

# Minimum absolute drift to log (avoid logging noise from tiny shifts)
_LOG_DRIFT_THRESHOLD = 0.005

# Regression-to-mean strength per round (proportion of distance to 0.5)
_REGRESSION_RATE = 0.001


@dataclass
class TraitSnapshot:
    """Immutable snapshot of Big Five traits at a given round."""

    agent_id: str
    round_number: int
    openness: float
    conscientiousness: float
    extraversion: float
    agreeableness: float
    neuroticism: float


@dataclass
class PersonalityEvolutionEngine:
    """Stateless engine — all state lives in the DB and caller-provided dicts.

    Designed to be instantiated once per ``SimulationRunner`` instance.
    """

    # In-memory trait cache: session_id → agent_id → trait dict
    _trait_cache: dict[str, dict[str, dict[str, float]]] = field(
        default_factory=dict, init=False, repr=False
    )

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    async def evolve_round(
        self,
        session_id: str,
        round_num: int,
        agent_profiles: list[dict[str, Any]],
        emotional_states: dict[str, Any],
        events: list[Any],
    ) -> list[TraitSnapshot]:
        """Compute and persist personality drift for all agents in this round.

        Args:
            session_id: The current simulation session.
            round_num: Current round number.
            agent_profiles: List of agent dicts with Big Five trait fields.
            emotional_states: Mapping of agent_id → EmotionalState (or None).
            events: Current-round world events (used for significance scoring).

        Returns:
            List of TraitSnapshot for all agents that experienced significant drift.
        """
        snapshots: list[TraitSnapshot] = []
        event_significance = self._score_event_significance(events)

        log_rows: list[tuple] = []

        for agent in agent_profiles:
            agent_id = str(agent.get("id", ""))
            if not agent_id:
                continue

            current_traits = self._get_traits(session_id, agent_id, agent)
            emotional = emotional_states.get(agent_id)
            valence = getattr(emotional, "valence", 0.0) if emotional else 0.0
            arousal = getattr(emotional, "arousal", 0.3) if emotional else 0.3

            new_traits, drifts = self._compute_drift(
                traits=current_traits,
                valence=valence,
                arousal=arousal,
                event_significance=event_significance,
            )

            # Update in-memory cache
            self._trait_cache.setdefault(session_id, {})[agent_id] = new_traits

            # Only persist and snapshot if any significant drift occurred
            max_drift = max(abs(d) for d in drifts.values()) if drifts else 0.0
            if max_drift >= _LOG_DRIFT_THRESHOLD:
                snap = TraitSnapshot(
                    agent_id=agent_id,
                    round_number=round_num,
                    **{t: new_traits[t] for t in _TRAITS},
                )
                snapshots.append(snap)
                for trait, delta in drifts.items():
                    if abs(delta) >= _LOG_DRIFT_THRESHOLD:
                        log_rows.append(
                            (
                                session_id,
                                agent_id,
                                round_num,
                                trait,
                                current_traits[trait],
                                new_traits[trait],
                                delta,
                            )
                        )

        # Persist log rows in bulk
        if log_rows:
            await self._persist_log(log_rows)

        return snapshots

    def get_traits(self, session_id: str, agent_id: str) -> dict[str, float] | None:
        """Return cached trait dict for an agent (None if not yet loaded)."""
        return self._trait_cache.get(session_id, {}).get(agent_id)

    def clear_session(self, session_id: str) -> None:
        """Remove in-memory cache for a completed session."""
        self._trait_cache.pop(session_id, None)

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _get_traits(
        self,
        session_id: str,
        agent_id: str,
        agent_profile: dict[str, Any],
    ) -> dict[str, float]:
        """Return cached traits or initialise from agent_profile."""
        cached = self._trait_cache.get(session_id, {}).get(agent_id)
        if cached is not None:
            return cached
        traits = {t: float(agent_profile.get(t, 0.5) or 0.5) for t in _TRAITS}
        self._trait_cache.setdefault(session_id, {})[agent_id] = traits
        return traits

    def _compute_drift(
        self,
        traits: dict[str, float],
        valence: float,
        arousal: float,
        event_significance: float,
    ) -> tuple[dict[str, float], dict[str, float]]:
        """Compute per-trait drift and return (new_traits, drifts) pair.

        Drift rules:
          - openness:         slight positive drift under high arousal + positive valence
          - conscientiousness: slight negative drift under high arousal (stress)
          - extraversion:     drift toward valence direction (positive→up, negative→down)
          - agreeableness:    drift toward valence direction (positive events → more agreeable)
          - neuroticism:      amplified by event significance; reduced by consistent positivity
          - all:              regression to mean (0.5) at _REGRESSION_RATE
        """
        plasticity = 0.5 + 0.5 * event_significance  # [0.5, 1.0]

        def clamp(v: float) -> float:
            return max(0.0, min(1.0, v))

        raw_drifts: dict[str, float] = {
            "openness":          0.005 * arousal * valence,
            "conscientiousness": -0.003 * arousal * event_significance,
            "extraversion":      0.004 * valence,
            "agreeableness":     0.003 * valence,
            "neuroticism":       0.006 * event_significance * (1 - valence),
        }

        # Apply plasticity and regression to mean
        drifts: dict[str, float] = {}
        new_traits: dict[str, float] = {}
        for t in _TRAITS:
            base_drift = raw_drifts[t] * plasticity
            # Clamp drift magnitude
            base_drift = max(-_MAX_DRIFT_PER_ROUND, min(_MAX_DRIFT_PER_ROUND, base_drift))
            # Regression to mean
            regression = _REGRESSION_RATE * (0.5 - traits[t])
            total_drift = base_drift + regression
            new_val = clamp(traits[t] + total_drift)
            actual_drift = new_val - traits[t]
            drifts[t] = actual_drift
            new_traits[t] = new_val

        return new_traits, drifts

    @staticmethod
    def _score_event_significance(events: list[Any]) -> float:
        """Return a significance score in [0.0, 1.0] based on current events.

        Falls back to 0.2 (baseline noise) if events cannot be scored.
        """
        if not events:
            return 0.2
        try:
            # Use average severity across events (attribute may vary by event model)
            severities = [
                float(getattr(e, "severity", 0.5))
                for e in events
                if hasattr(e, "severity")
            ]
            if severities:
                return min(1.0, sum(severities) / len(severities))
        except Exception:
            pass
        return 0.3 * min(1.0, len(events) / 5)

    @staticmethod
    async def _persist_log(rows: list[tuple]) -> None:
        """Write drift log rows to personality_evolution_log table (best-effort)."""
        try:
            from backend.app.utils.db import get_db  # noqa: PLC0415

            async with get_db() as db:
                await db.executemany(
                    """INSERT INTO personality_evolution_log
                       (session_id, agent_id, round_number, trait,
                        old_value, new_value, delta)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    rows,
                )
                await db.commit()
        except Exception:
            logger.warning("personality_evolution_log persist failed", exc_info=True)
