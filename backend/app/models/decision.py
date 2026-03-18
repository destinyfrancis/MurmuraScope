"""Decision model dataclasses for the Agent Decision Engine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DecisionType(str, Enum):
    """Types of life/financial decisions an agent can make."""

    BUY_PROPERTY = "buy_property"
    EMIGRATE = "emigrate"
    CHANGE_JOB = "change_job"
    INVEST = "invest"
    HAVE_CHILD = "have_child"
    ADJUST_SPENDING = "adjust_spending"  # Phase 4
    EMPLOYMENT_CHANGE = "employment_change"  # Phase 18: O2O Layer 3
    RELOCATE = "relocate"                    # Phase 18: O2O Layer 3


# Valid action strings per decision type (for validation)
DECISION_ACTIONS: dict[str, frozenset[str]] = {
    DecisionType.BUY_PROPERTY: frozenset({"buy", "wait", "rent_more", "sell"}),
    DecisionType.EMIGRATE: frozenset({"emigrate", "stay", "consider_later"}),
    DecisionType.CHANGE_JOB: frozenset({"change_job", "stay", "upskill", "retire_early"}),
    DecisionType.INVEST: frozenset({"invest_stocks", "invest_property", "invest_crypto", "hold_cash", "diversify"}),
    DecisionType.HAVE_CHILD: frozenset({"have_child", "delay", "no_child"}),
    DecisionType.ADJUST_SPENDING: frozenset({"cut_spending", "maintain", "increase_savings", "spend_more"}),
    DecisionType.EMPLOYMENT_CHANGE: frozenset({"quit", "strike", "lie_flat", "seek_employment", "maintain"}),
    DecisionType.RELOCATE: frozenset({"relocate_nt", "relocate_kln", "relocate_hk_island", "relocate_gba", "stay"}),
}


@dataclass(frozen=True)
class AgentDecision:
    """Immutable record of a single agent decision in a simulation round."""

    session_id: str
    agent_id: int
    round_number: int
    decision_type: str   # DecisionType value
    action: str          # e.g. buy / emigrate / stay / invest_stocks
    reasoning: str
    confidence: float    # 0.0–1.0
    topic_tags: tuple[str, ...] = ()
    """Topics this decision touches — persisted as JSON array in DB."""
    emotional_reaction: str = ""
    """Brief emotional state at decision time — persisted as plain string in DB."""

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"confidence must be between 0 and 1, got {self.confidence}"
            )


@dataclass(frozen=True)
class DecisionSummary:
    """Aggregated decision counts for a session/round."""

    session_id: str
    round_number: int | None          # None = across all rounds
    counts_by_type: dict[str, dict[str, int]]  # {decision_type: {action: count}}
    total_decisions: int
