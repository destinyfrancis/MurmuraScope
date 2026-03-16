"""Project and simulation session state models.

Immutable dataclasses representing the core domain objects for simulation
session lifecycle management.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4


class SessionStatus(str, Enum):
    """Simulation session lifecycle states."""

    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SimMode(str, Enum):
    """Supported simulation modes."""

    LIFE_DECISION = "life_decision"
    B2B_CAMPAIGN = "b2b_campaign"
    MACRO_OPINION = "macro_opinion"


class Platform(str, Enum):
    """Supported social media platforms for simulation."""

    TWITTER = "twitter"
    REDDIT = "reddit"
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"


# Maps HKSimEngine platforms to their OASIS backend platform type.
# Facebook uses the Reddit (community/subreddit) backend.
# Instagram uses the Twitter (feed/follower) backend.
PLATFORM_OASIS_MAP: dict[Platform, str] = {
    Platform.TWITTER: "twitter",
    Platform.REDDIT: "reddit",
    Platform.FACEBOOK: "reddit",
    Platform.INSTAGRAM: "twitter",
}


@dataclass(frozen=True)
class AgentProfile:
    """Immutable profile for a single simulated agent."""

    id: int
    agent_type: str
    age: int
    sex: str
    district: str
    occupation: str
    income_bracket: str
    education_level: str
    personality: dict[str, Any]
    backstory: str = ""


@dataclass(frozen=True)
class CostEstimate:
    """Immutable cost estimate for a simulation run."""

    agent_count: int
    round_count: int
    cost_per_call_usd: float
    total_estimated_usd: float
    token_estimate: int

    @staticmethod
    def calculate(
        agent_count: int,
        round_count: int,
        avg_tokens_per_call: int = 500,
        cost_per_1k_tokens: float = 0.00002,
    ) -> CostEstimate:
        """Calculate cost estimate for a Qwen 3.5 9B via OpenRouter simulation."""
        total_calls = agent_count * round_count
        total_tokens = total_calls * avg_tokens_per_call
        cost_per_call = (avg_tokens_per_call / 1000) * cost_per_1k_tokens
        total_cost = total_calls * cost_per_call
        return CostEstimate(
            agent_count=agent_count,
            round_count=round_count,
            cost_per_call_usd=cost_per_call,
            total_estimated_usd=round(total_cost, 4),
            token_estimate=total_tokens,
        )


@dataclass(frozen=True)
class SessionState:
    """Immutable snapshot of a simulation session."""

    id: str
    name: str
    sim_mode: SimMode
    status: SessionStatus
    agent_count: int
    round_count: int
    current_round: int
    graph_id: str
    scenario_type: str
    platforms: dict[str, bool]
    llm_provider: str
    cost_estimate: CostEstimate | None
    created_at: str
    updated_at: str
    error_message: str | None = None

    @staticmethod
    def create(
        name: str,
        sim_mode: SimMode,
        agent_count: int,
        round_count: int,
        graph_id: str,
        scenario_type: str,
        platforms: dict[str, bool] | None = None,
        llm_provider: str = "openrouter",
    ) -> SessionState:
        """Create a new session state with generated ID and timestamps."""
        now = datetime.utcnow().isoformat()
        default_platforms = {"facebook": True, "instagram": True}
        cost = CostEstimate.calculate(agent_count, round_count)
        return SessionState(
            id=str(uuid4()),
            name=name,
            sim_mode=sim_mode,
            status=SessionStatus.CREATED,
            agent_count=agent_count,
            round_count=round_count,
            current_round=0,
            graph_id=graph_id,
            scenario_type=scenario_type,
            platforms=platforms or default_platforms,
            llm_provider=llm_provider,
            cost_estimate=cost,
            created_at=now,
            updated_at=now,
        )

    def with_status(self, status: SessionStatus, **kwargs: Any) -> SessionState:
        """Return a new SessionState with updated status and timestamp."""
        return replace(
            self,
            status=status,
            updated_at=datetime.utcnow().isoformat(),
            **kwargs,
        )

    def with_round(self, current_round: int) -> SessionState:
        """Return a new SessionState with updated current round."""
        return replace(
            self,
            current_round=current_round,
            updated_at=datetime.utcnow().isoformat(),
        )


@dataclass(frozen=True)
class ProgressUpdate:
    """Immutable progress update from a running simulation."""

    session_id: str
    current_round: int
    total_rounds: int
    status: str
    events_count: int
    latest_posts: list[dict[str, Any]]
    graph_updates: list[dict[str, Any]]


@dataclass(frozen=True)
class ReportResult:
    """Immutable result of a generated report."""

    report_id: str
    title: str
    content_markdown: str
    summary: str
    key_findings: list[str]
    charts_data: dict[str, Any] | None = None
