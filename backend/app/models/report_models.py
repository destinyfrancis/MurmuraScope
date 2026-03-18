"""Frozen dataclasses for report generation results."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class InsightForgeResult:
    """Result from insight_forge deep query tool."""
    query: str
    sub_queries: tuple[str, ...]
    facts: tuple[str, ...]
    quotable_excerpts: tuple[str, ...]
    source_agents: tuple[str, ...]


@dataclass(frozen=True)
class AgentArc:
    """Cross-round story arc for one representative agent."""
    agent_id: str
    agent_type: str
    name: str
    arc_summary: str
    key_turning_round: int
    stance_shift: str
    sentiment_trajectory: tuple[float, ...]


@dataclass(frozen=True)
class TopicWindow:
    """Topics dominant in one time window of the simulation."""
    rounds: str                          # e.g. "1-5"
    dominant_topics: tuple[str, ...]
    emerging: tuple[str, ...]
    fading: tuple[str, ...]


@dataclass(frozen=True)
class TopicEvolutionResult:
    """Full topic migration analysis across all rounds."""
    windows: tuple[TopicWindow, ...]
    migration_path: str                  # e.g. "個案事實 → 程序正義 → 制度信任"
    inflection_round: int | None
