"""Scale testing models (Phase 4A).

Defines immutable dataclasses for performance profiling, scale targets, and
benchmark results used by ScaleProfiler and the admin benchmark API.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class HookTiming:
    """Immutable timing record for a single hook execution."""

    hook_name: str
    round_number: int
    duration_ms: float
    agent_count: int = 0
    db_queries: int = 0
    llm_calls: int = 0


@dataclass(frozen=True)
class ScaleTarget:
    """Immutable performance target for a given scale tier."""

    name: str  # "1k" | "3k" | "10k"
    agent_count: int
    rounds: int
    max_round_duration_s: float
    max_memory_mb: float
    max_total_duration_s: float


@dataclass(frozen=True)
class BenchmarkResult:
    """Immutable result from a full benchmark run."""

    preset_name: str
    agent_count: int
    rounds_completed: int
    total_duration_s: float
    avg_round_duration_s: float
    peak_memory_mb: float
    db_queries_total: int = 0
    db_avg_query_ms: float = 0.0
    llm_calls_total: int = 0
    llm_avg_latency_ms: float = 0.0
    hook_durations: dict[str, float] = field(default_factory=dict)
    bottleneck_hook: str = ""
    throughput_agents_per_sec: float = 0.0
    passed: bool = False


# ---------------------------------------------------------------------------
# Pre-defined scale targets
# ---------------------------------------------------------------------------

SCALE_1K = ScaleTarget(
    name="1k",
    agent_count=1_000,
    rounds=10,
    max_round_duration_s=30.0,
    max_memory_mb=4_096.0,
    max_total_duration_s=300.0,
)

SCALE_3K = ScaleTarget(
    name="3k",
    agent_count=3_000,
    rounds=10,
    max_round_duration_s=90.0,
    max_memory_mb=8_192.0,
    max_total_duration_s=900.0,
)

SCALE_10K = ScaleTarget(
    name="10k",
    agent_count=10_000,
    rounds=5,
    max_round_duration_s=300.0,
    max_memory_mb=16_384.0,
    max_total_duration_s=1_500.0,
)
