"""Scale profiler service (Phase 4A).

Records timing data for each hook group per round and aggregates results
into a BenchmarkResult at the end of a simulation run.  Persists results
to the ``scale_benchmarks`` table so they can be queried by the admin API.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from backend.app.models.scale import BenchmarkResult, HookTiming
from backend.app.utils.logger import get_logger

if TYPE_CHECKING:
    import aiosqlite

logger = get_logger("scale_profiler")


class ScaleProfiler:
    """Collects per-hook timing data for a simulation run.

    Usage::

        profiler = ScaleProfiler()
        t0 = profiler.start_hook("group_1", round_num)
        # ... hook code ...
        timing = profiler.end_hook("group_1", round_num, t0, agent_count=300)

        result = profiler.get_summary("standard", 300, total_s, peak_mb)
        async with get_db() as db:
            await profiler.persist(result, db)
        profiler.clear()
    """

    def __init__(self) -> None:
        self._timings: list[HookTiming] = []

    # ------------------------------------------------------------------
    # Timing helpers
    # ------------------------------------------------------------------

    def start_hook(self, hook_name: str, round_number: int) -> float:
        """Record start timestamp.

        Args:
            hook_name: Human-readable hook identifier (e.g. ``"group_1"``).
            round_number: Current simulation round.

        Returns:
            High-resolution timestamp from ``time.perf_counter()``.
        """
        return time.perf_counter()

    def end_hook(
        self,
        hook_name: str,
        round_number: int,
        start_time: float,
        agent_count: int = 0,
        db_queries: int = 0,
        llm_calls: int = 0,
    ) -> HookTiming:
        """Compute elapsed time, create an immutable HookTiming, and store it.

        Args:
            hook_name: Hook identifier matching the one passed to start_hook.
            round_number: Current simulation round.
            start_time: Value returned by start_hook.
            agent_count: Number of agents processed (optional).
            db_queries: Number of DB queries issued (optional).
            llm_calls: Number of LLM calls issued (optional).

        Returns:
            Newly created HookTiming record.
        """
        duration_ms = (time.perf_counter() - start_time) * 1_000.0
        timing = HookTiming(
            hook_name=hook_name,
            round_number=round_number,
            duration_ms=duration_ms,
            agent_count=agent_count,
            db_queries=db_queries,
            llm_calls=llm_calls,
        )
        self._timings.append(timing)
        logger.debug(
            "hook=%s round=%d duration_ms=%.1f agents=%d",
            hook_name, round_number, duration_ms, agent_count,
        )
        return timing

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def get_summary(
        self,
        preset_name: str,
        agent_count: int,
        total_duration_s: float,
        peak_memory_mb: float,
    ) -> BenchmarkResult:
        """Aggregate all recorded timings into a BenchmarkResult.

        Per-hook durations are averaged across rounds.  The bottleneck hook
        is the one with the highest average duration.

        Args:
            preset_name: Name of the simulation preset (e.g. ``"standard"``).
            agent_count: Total agents in the simulation.
            total_duration_s: Wall-clock seconds for the entire run.
            peak_memory_mb: Peak RSS memory in MB.

        Returns:
            Immutable BenchmarkResult.
        """
        if not self._timings:
            return BenchmarkResult(
                preset_name=preset_name,
                agent_count=agent_count,
                rounds_completed=0,
                total_duration_s=total_duration_s,
                avg_round_duration_s=0.0,
                peak_memory_mb=peak_memory_mb,
            )

        # Compute per-hook average duration (ms)
        hook_duration_sum: dict[str, float] = {}
        hook_duration_count: dict[str, int] = {}
        rounds_seen: set[int] = set()

        db_queries_total = 0
        llm_calls_total = 0

        for t in self._timings:
            hook_duration_sum[t.hook_name] = (
                hook_duration_sum.get(t.hook_name, 0.0) + t.duration_ms
            )
            hook_duration_count[t.hook_name] = (
                hook_duration_count.get(t.hook_name, 0) + 1
            )
            rounds_seen.add(t.round_number)
            db_queries_total += t.db_queries
            llm_calls_total += t.llm_calls

        hook_avg: dict[str, float] = {
            name: hook_duration_sum[name] / hook_duration_count[name]
            for name in hook_duration_sum
        }

        bottleneck = max(hook_avg, key=lambda k: hook_avg[k]) if hook_avg else ""

        rounds_completed = len(rounds_seen)
        avg_round_s = (
            total_duration_s / rounds_completed if rounds_completed > 0 else 0.0
        )
        throughput = (
            agent_count * rounds_completed / total_duration_s
            if total_duration_s > 0
            else 0.0
        )

        return BenchmarkResult(
            preset_name=preset_name,
            agent_count=agent_count,
            rounds_completed=rounds_completed,
            total_duration_s=total_duration_s,
            avg_round_duration_s=avg_round_s,
            peak_memory_mb=peak_memory_mb,
            db_queries_total=db_queries_total,
            db_avg_query_ms=0.0,  # not tracked at this granularity
            llm_calls_total=llm_calls_total,
            llm_avg_latency_ms=0.0,
            hook_durations=hook_avg,
            bottleneck_hook=bottleneck,
            throughput_agents_per_sec=throughput,
            passed=False,  # caller sets this based on ScaleTarget comparison
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def persist(self, result: BenchmarkResult, db: "aiosqlite.Connection") -> None:
        """Persist a BenchmarkResult to the scale_benchmarks table.

        The table must already exist (created by schema.sql).  Errors are
        logged but not raised so a profiling failure never breaks simulation.

        Args:
            result: The BenchmarkResult to persist.
            db: Open aiosqlite connection.
        """
        try:
            await db.execute(
                """
                INSERT INTO scale_benchmarks (
                    target_name, agent_count, rounds_completed,
                    total_duration_s, avg_round_duration_s, peak_memory_mb,
                    db_queries_total, db_avg_query_ms,
                    llm_calls_total, llm_avg_latency_ms,
                    hook_durations_json, bottleneck_hook,
                    throughput, passed
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    result.preset_name,
                    result.agent_count,
                    result.rounds_completed,
                    result.total_duration_s,
                    result.avg_round_duration_s,
                    result.peak_memory_mb,
                    result.db_queries_total,
                    result.db_avg_query_ms,
                    result.llm_calls_total,
                    result.llm_avg_latency_ms,
                    json.dumps(result.hook_durations),
                    result.bottleneck_hook,
                    result.throughput_agents_per_sec,
                    1 if result.passed else 0,
                ),
            )
            await db.commit()
            logger.info(
                "Persisted benchmark: preset=%s agents=%d rounds=%d total_s=%.1f",
                result.preset_name,
                result.agent_count,
                result.rounds_completed,
                result.total_duration_s,
            )
        except Exception:
            logger.exception("ScaleProfiler.persist failed — benchmark result lost")

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Remove all collected timings, ready for the next run."""
        self._timings = []

    @property
    def timing_count(self) -> int:
        """Number of HookTiming records collected so far."""
        return len(self._timings)
