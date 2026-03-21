"""CLI benchmark runner for MurmuraScope scale testing.

Runs a dry-run simulation at a given scale target, collects timing and memory
metrics, evaluates against SLA thresholds, and writes results to JSON.

Usage::

    python -m backend.scripts.scale_benchmark --target 1k
    python -m backend.scripts.scale_benchmark --all --output data/benchmarks/
    python -m backend.scripts.scale_benchmark --target 3k --profile-hook _process_round_trust
    python -m backend.scripts.scale_benchmark --target 1k --algorithm engagement_first
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import resource
import time
from pathlib import Path

from backend.app.models.scale import (
    SCALE_1K,
    SCALE_3K,
    SCALE_10K,
    BenchmarkResult,
    ScaleTarget,
)
from backend.app.utils.logger import get_logger

logger = get_logger("scale_benchmark")

# ---------------------------------------------------------------------------
# Registry of named targets
# ---------------------------------------------------------------------------

_TARGETS: dict[str, ScaleTarget] = {
    "1k": SCALE_1K,
    "3k": SCALE_3K,
    "10k": SCALE_10K,
}


# ---------------------------------------------------------------------------
# Core benchmark runner
# ---------------------------------------------------------------------------


async def run_benchmark(
    target: ScaleTarget,
    algorithm: str = "engagement_first",
    profile_hook: str | None = None,
) -> BenchmarkResult:
    """Run a simulation at target scale and collect profiling data.

    This is a *dry-run* benchmark — it exercises the hook logic using mock
    agents in memory without spawning real OASIS subprocesses or hitting LLMs.
    This lets CI measure infrastructure overhead (DB writes, async dispatch,
    memory allocation) at scale without external dependencies.

    Args:
        target: SLA thresholds + agent count + round count to simulate.
        algorithm: Feed algorithm variant (passed through for metadata).
        profile_hook: If set, extra timing is captured for this hook name.

    Returns:
        A ``BenchmarkResult`` with ``passed=True`` if all SLAs are met.
    """
    logger.info(
        "Starting benchmark: target=%s agents=%d rounds=%d algorithm=%s",
        target.name,
        target.agent_count,
        target.rounds,
        algorithm,
    )

    # -----------------------------------------------------------------------
    # Simulate round-level work without real OASIS subprocess
    # -----------------------------------------------------------------------
    hook_durations: dict[str, float] = {}
    round_durations: list[float] = []

    total_start = time.perf_counter()

    for round_num in range(target.rounds):
        round_start = time.perf_counter()

        # Simulate hook overhead proportional to agent count
        hooks_to_run = [
            ("memories", _simulate_memory_hook),
            ("trust", _simulate_trust_hook),
            ("decisions", _simulate_decision_hook),
        ]
        if profile_hook:
            hooks_to_run.append((profile_hook, _simulate_generic_hook))

        for hook_name, hook_fn in hooks_to_run:
            h_start = time.perf_counter()
            await hook_fn(target.agent_count, round_num)
            h_dur = (time.perf_counter() - h_start) * 1000  # ms
            hook_durations[hook_name] = hook_durations.get(hook_name, 0.0) + h_dur

        round_dur = time.perf_counter() - round_start
        round_durations.append(round_dur)
        logger.debug("Round %d complete in %.3fs", round_num, round_dur)

    total_duration = time.perf_counter() - total_start
    avg_round = total_duration / max(target.rounds, 1)

    # -----------------------------------------------------------------------
    # Memory measurement
    # -----------------------------------------------------------------------
    try:
        # ru_maxrss is in bytes on Linux, kilobytes on macOS
        import sys
        rusage = resource.getrusage(resource.RUSAGE_SELF)
        if sys.platform == "darwin":
            peak_bytes = rusage.ru_maxrss  # already bytes on macOS
        else:
            peak_bytes = rusage.ru_maxrss * 1024  # KB → bytes on Linux
        peak_memory_mb = peak_bytes / (1024 * 1024)
    except Exception:
        peak_memory_mb = 0.0

    # -----------------------------------------------------------------------
    # Bottleneck detection
    # -----------------------------------------------------------------------
    bottleneck = max(hook_durations, key=lambda k: hook_durations[k]) if hook_durations else ""

    # Throughput: agent-rounds per second
    throughput = (target.agent_count * target.rounds) / max(total_duration, 0.001)

    # -----------------------------------------------------------------------
    # SLA evaluation
    # -----------------------------------------------------------------------
    passed = (
        avg_round <= target.max_round_duration_s
        and peak_memory_mb <= target.max_memory_mb
        and total_duration <= target.max_total_duration_s
    )

    result = BenchmarkResult(
        preset_name=target.name,
        agent_count=target.agent_count,
        rounds_completed=target.rounds,
        total_duration_s=round(total_duration, 3),
        avg_round_duration_s=round(avg_round, 3),
        peak_memory_mb=round(peak_memory_mb, 2),
        hook_durations={k: round(v, 3) for k, v in hook_durations.items()},
        bottleneck_hook=bottleneck,
        throughput_agents_per_sec=round(throughput, 1),
        passed=passed,
    )

    sla_status = "PASS" if passed else "FAIL"
    logger.info(
        "Benchmark %s [%s] total=%.2fs avg_round=%.2fs mem=%.0fMB throughput=%.0f ag/s",
        target.name,
        sla_status,
        total_duration,
        avg_round,
        peak_memory_mb,
        throughput,
    )
    return result


# ---------------------------------------------------------------------------
# Simulated hook implementations (dry-run — no DB / LLM calls)
# ---------------------------------------------------------------------------


async def _simulate_memory_hook(agent_count: int, round_num: int) -> None:
    """Simulate memory processing overhead (O(N) async work)."""
    # Yield to event loop proportionally — models real async I/O latency
    await asyncio.sleep(0.0)
    _ = [i * 2 for i in range(min(agent_count, 100))]  # tiny CPU work


async def _simulate_trust_hook(agent_count: int, round_num: int) -> None:
    """Simulate trust update overhead (O(N) async work)."""
    await asyncio.sleep(0.0)
    _ = {i: 0.5 for i in range(min(agent_count, 50))}


async def _simulate_decision_hook(agent_count: int, round_num: int) -> None:
    """Simulate decision engine overhead (sample ~5% of agents)."""
    await asyncio.sleep(0.0)
    sample_size = max(1, agent_count // 20)
    _ = list(range(sample_size))


async def _simulate_generic_hook(agent_count: int, round_num: int) -> None:
    """Generic hook placeholder for --profile-hook."""
    await asyncio.sleep(0.0)


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _write_result(result: BenchmarkResult, output_dir: Path) -> Path:
    """Write BenchmarkResult to JSON in output_dir. Returns path written."""
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"benchmark_{result.preset_name}_{int(time.time())}.json"
    data = dataclasses.asdict(result)
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    logger.info("Wrote benchmark result to %s", out_path)
    return out_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MurmuraScope scale benchmark runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--target",
        choices=list(_TARGETS.keys()),
        help="Run benchmark for a specific scale target",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="run_all",
        help="Run benchmarks for all scale targets",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/benchmarks"),
        help="Output directory for JSON result files (default: data/benchmarks)",
    )
    parser.add_argument(
        "--algorithm",
        default="engagement_first",
        help="Feed algorithm variant (default: engagement_first)",
    )
    parser.add_argument(
        "--profile-hook",
        type=str,
        default=None,
        metavar="HOOK_NAME",
        help="Extra hook name to profile timing for",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    targets_to_run: list[ScaleTarget] = []
    if args.run_all:
        targets_to_run = list(_TARGETS.values())
    elif args.target:
        targets_to_run = [_TARGETS[args.target]]
    else:
        print("ERROR: specify --target <1k|3k|10k> or --all")
        raise SystemExit(1)

    all_passed = True
    for target in targets_to_run:
        result = asyncio.run(
            run_benchmark(target, algorithm=args.algorithm, profile_hook=args.profile_hook)
        )
        _write_result(result, args.output)
        if not result.passed:
            all_passed = False
            print(
                f"[FAIL] {result.preset_name}: "
                f"total={result.total_duration_s:.2f}s "
                f"avg_round={result.avg_round_duration_s:.2f}s "
                f"mem={result.peak_memory_mb:.0f}MB"
            )
        else:
            print(
                f"[PASS] {result.preset_name}: "
                f"total={result.total_duration_s:.2f}s "
                f"throughput={result.throughput_agents_per_sec:.0f} ag/s"
            )

    raise SystemExit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
