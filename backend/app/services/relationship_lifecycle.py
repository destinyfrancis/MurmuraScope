"""Relationship lifecycle event detection and emission.

Detects significant relationship transitions and emits them as events to the
existing ``network_events`` table.

Event types (all prefixed with RELATIONSHIP_):
    RELATIONSHIP_FORMED     — first meaningful connection established
    RELATIONSHIP_DEEPENED   — commitment crossed 0.5 threshold
    RELATIONSHIP_CRISIS     — Gottman score > 0.7 (Four Horsemen active)
    RELATIONSHIP_DISSOLVED  — commitment < 0.1 AND trust < -0.3
    RELATIONSHIP_STAGNATED  — intimacy/passion unchanged for 5 rounds

Completely gated: only active in kg_driven mode + emergence_enabled=True.
hk_demographic mode is completely unaffected.
LLM cost: 0.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.models.relationship_state import RelationshipState
from backend.app.services.relationship_engine import RelationshipEngine
from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("relationship_lifecycle")

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

_FORMED_TRUST_MIN = 0.3
_FORMED_INTIMACY_MIN = 0.2

_DEEPENED_COMMITMENT_THRESHOLD = 0.5

_CRISIS_GOTTMAN_THRESHOLD = 0.7
_CRISIS_NEGATIVITY_SIGNAL = -0.5  # valence below this → suspicious for horsemen

_DISSOLVED_COMMITMENT_MAX = 0.1
_DISSOLVED_TRUST_MAX = -0.3

_STAGNATED_ROUNDS = 5      # rounds_since_change >= this → stagnated

# ---------------------------------------------------------------------------
# Event record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RelationshipEvent:
    """Immutable record of a detected relationship lifecycle event."""

    session_id: str
    round_number: int
    agent_a_id: str
    agent_b_id: str
    event_type: str
    payload: str  # JSON-serialisable description


# ---------------------------------------------------------------------------
# RelationshipLifecycleService
# ---------------------------------------------------------------------------


class RelationshipLifecycleService:
    """Detect relationship lifecycle transitions and emit network_events."""

    def __init__(self) -> None:
        self._engine = RelationshipEngine()
        # Track which pairs have already had FORMED / DEEPENED emitted
        # to avoid duplicate events across rounds.
        self._formed_pairs: dict[str, set[tuple[str, str]]] = {}
        self._deepened_pairs: dict[str, set[tuple[str, str]]] = {}

    def detect_events(
        self,
        session_id: str,
        round_number: int,
        rel_states: dict[tuple[str, str], RelationshipState],
        interaction_valences: dict[tuple[str, str], float] | None = None,
    ) -> list[RelationshipEvent]:
        """Scan all relationship states and detect lifecycle events.

        Args:
            session_id: Simulation session UUID.
            round_number: Current round number.
            rel_states: Current relationship states keyed by (a_id, b_id).
            interaction_valences: Optional per-pair interaction valences this
                round, used for Gottman scoring.

        Returns:
            List of detected RelationshipEvent instances.
        """
        events: list[RelationshipEvent] = []
        valences = interaction_valences or {}

        formed = self._formed_pairs.setdefault(session_id, set())
        deepened = self._deepened_pairs.setdefault(session_id, set())

        for (aid, bid), state in rel_states.items():
            pair = (aid, bid)
            valence = valences.get(pair, 0.0)

            # FORMED
            if (
                pair not in formed
                and state.trust >= _FORMED_TRUST_MIN
                and state.intimacy >= _FORMED_INTIMACY_MIN
            ):
                formed.add(pair)
                events.append(RelationshipEvent(
                    session_id=session_id,
                    round_number=round_number,
                    agent_a_id=aid,
                    agent_b_id=bid,
                    event_type="RELATIONSHIP_FORMED",
                    payload=(
                        f"trust={state.trust:.2f} intimacy={state.intimacy:.2f}"
                    ),
                ))

            # DEEPENED
            if (
                pair not in deepened
                and state.commitment >= _DEEPENED_COMMITMENT_THRESHOLD
            ):
                deepened.add(pair)
                events.append(RelationshipEvent(
                    session_id=session_id,
                    round_number=round_number,
                    agent_a_id=aid,
                    agent_b_id=bid,
                    event_type="RELATIONSHIP_DEEPENED",
                    payload=f"commitment={state.commitment:.2f}",
                ))

            # CRISIS — only on negative interactions
            if valence < _CRISIS_NEGATIVITY_SIGNAL:
                gottman = self._engine.compute_gottman_score(
                    interaction_valence=valence,
                    contempt_signal=max(0.0, -valence - 0.3),
                    defensiveness_signal=max(0.0, -valence - 0.2),
                    stonewalling_signal=(
                        0.5 if state.rounds_since_change > 2 else 0.0
                    ),
                )
                agg = sum(gottman.values()) / len(gottman)
                if agg >= _CRISIS_GOTTMAN_THRESHOLD:
                    events.append(RelationshipEvent(
                        session_id=session_id,
                        round_number=round_number,
                        agent_a_id=aid,
                        agent_b_id=bid,
                        event_type="RELATIONSHIP_CRISIS",
                        payload=(
                            f"gottman_avg={agg:.2f} "
                            f"contempt={gottman['contempt']:.2f}"
                        ),
                    ))

            # DISSOLVED
            if (
                state.commitment < _DISSOLVED_COMMITMENT_MAX
                and state.trust < _DISSOLVED_TRUST_MAX
            ):
                events.append(RelationshipEvent(
                    session_id=session_id,
                    round_number=round_number,
                    agent_a_id=aid,
                    agent_b_id=bid,
                    event_type="RELATIONSHIP_DISSOLVED",
                    payload=(
                        f"commitment={state.commitment:.2f} "
                        f"trust={state.trust:.2f}"
                    ),
                ))
                # Reset formed/deepened so relationship can re-form
                formed.discard(pair)
                deepened.discard(pair)

            # STAGNATED — self-expansion theory: no growth → relationship drifts
            if state.rounds_since_change >= _STAGNATED_ROUNDS:
                events.append(RelationshipEvent(
                    session_id=session_id,
                    round_number=round_number,
                    agent_a_id=aid,
                    agent_b_id=bid,
                    event_type="RELATIONSHIP_STAGNATED",
                    payload=(
                        f"rounds_since_change={state.rounds_since_change} "
                        f"intimacy={state.intimacy:.2f}"
                    ),
                ))

        return events

    async def persist_events(
        self,
        events: list[RelationshipEvent],
        db: Any,
    ) -> None:
        """Persist relationship lifecycle events to network_events table.

        Args:
            events: Events detected by detect_events().
            db: Open aiosqlite connection.
        """
        if not events:
            return
        rows = [
            (
                e.session_id,
                e.round_number,
                e.agent_a_id,
                e.agent_b_id,
                e.event_type,
                e.payload,
            )
            for e in events
        ]
        try:
            await db.executemany(
                """
                INSERT INTO network_events
                    (session_id, round_number, agent_a_username, agent_b_username,
                     event_type, details_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            await db.commit()
            logger.debug(
                "Persisted %d relationship events session=%s round=%d",
                len(events), events[0].session_id, events[0].round_number,
            )
        except Exception:
            logger.exception(
                "persist_events failed for %d events", len(events)
            )

    def cleanup_session(self, session_id: str) -> None:
        """Release per-session tracking state."""
        self._formed_pairs.pop(session_id, None)
        self._deepened_pairs.pop(session_id, None)
