"""Distributed OASIS subprocess sharding for large-scale simulations.

Splits agent population across N subprocess shards so each shard handles a
partition of agents.  A shared JSONL queue merges all shard outputs for the
main simulation runner to consume.
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator

from backend.app.utils.logger import get_logger

logger = get_logger("shard_coordinator")


# ---------------------------------------------------------------------------
# Immutable shard configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ShardConfig:
    """Immutable agent-range assignment for a single subprocess shard."""

    shard_id: int
    agent_start: int
    agent_end: int

    @property
    def agent_count(self) -> int:
        return self.agent_end - self.agent_start


# ---------------------------------------------------------------------------
# Mutable shard runtime state (not frozen — tracks live process handle)
# ---------------------------------------------------------------------------


@dataclass
class ShardState:
    """Mutable runtime state for one running shard subprocess."""

    config: ShardConfig
    process: asyncio.subprocess.Process | None = None
    last_round_synced: int = -1
    failed: bool = False

    # Per-shard queue that feeds the merged stream
    _queue: asyncio.Queue[dict | None] = field(
        default_factory=asyncio.Queue, repr=False
    )


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------


class ShardCoordinator:
    """Launch N OASIS subprocess shards and merge their JSONL output streams.

    Each shard receives env vars ``SHARD_ID``, ``AGENT_START``, ``AGENT_END``
    so the target script can partition its agent population accordingly.

    Usage::

        coord = ShardCoordinator(session_id, python_bin, script_path)
        shards = await coord.launch_shards(10_000, agents_per_shard=2_500)
        async for msg in coord.read_merged_stream():
            process(msg)
        await coord.shutdown_all()
    """

    def __init__(
        self,
        session_id: str,
        python_bin: Path,
        script_path: Path,
    ) -> None:
        self._session_id = session_id
        self._python_bin = python_bin
        self._script_path = script_path
        self._shards: dict[int, ShardState] = {}
        # Shared merge queue; None sentinel signals one shard EOF
        self._merge_queue: asyncio.Queue[dict | None] = asyncio.Queue()
        # Round-sync barrier: shard_id → asyncio.Event
        self._sync_events: dict[int, asyncio.Event] = {}
        # Patch file shared across shards
        self._patch_file: Path = Path(
            tempfile.mktemp(prefix=f"hksim_patch_{session_id}_", suffix=".json")
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def launch_shards(
        self,
        total_agents: int,
        agents_per_shard: int = 2500,
    ) -> list[ShardState]:
        """Launch N subprocess shards partitioned by agent range.

        Returns:
            List of ShardState objects (one per shard launched).
        """
        shard_configs = self._compute_shard_configs(total_agents, agents_per_shard)
        for cfg in shard_configs:
            state = ShardState(config=cfg)
            process = await self._spawn_shard(cfg)
            state.process = process
            self._shards[cfg.shard_id] = state
            self._sync_events[cfg.shard_id] = asyncio.Event()
            # Start background reader for this shard
            asyncio.create_task(
                self._shard_reader(state),
                name=f"shard-reader-{cfg.shard_id}",
            )
            logger.info(
                "Launched shard %d: agents %d–%d (pid=%s)",
                cfg.shard_id,
                cfg.agent_start,
                cfg.agent_end,
                process.pid,
            )
        return list(self._shards.values())

    async def read_merged_stream(self) -> AsyncIterator[dict]:
        """Yield JSONL messages merged from all shard stdouts.

        Terminates when all shards have closed their stdout (or failed).
        """
        active_shards = len(self._shards)
        finished = 0
        while finished < active_shards:
            item = await self._merge_queue.get()
            if item is None:
                finished += 1
                continue
            yield item

    async def sync_round_barrier(self, timeout: float = 60.0) -> None:
        """Wait for all active (non-failed) shards to emit a ``round_sync`` message.

        On timeout, the timed-out shard is marked as failed and execution
        continues with partial quorum.
        """
        active = [
            sid for sid, s in self._shards.items() if not s.failed
        ]
        tasks = []
        for sid in active:
            event = self._sync_events.get(sid)
            if event:
                tasks.append(asyncio.ensure_future(event.wait()))

        if not tasks:
            return

        done, pending = await asyncio.wait(
            tasks, timeout=timeout, return_when=asyncio.ALL_COMPLETED
        )
        if pending:
            timed_out = [
                sid
                for sid, s in self._shards.items()
                if not self._sync_events[sid].is_set() and not s.failed
            ]
            for sid in timed_out:
                self._shards[sid].failed = True
                logger.error(
                    "Shard %d timed out at round barrier — marking failed", sid
                )
            for task in pending:
                task.cancel()

        # Reset events for the next round
        for sid in active:
            if sid in self._sync_events:
                self._sync_events[sid].clear()

    async def broadcast_network_patch(self, patch: dict) -> None:
        """Write a network patch dict to the shared patch file.

        All shards poll this file to pick up cross-shard interactions.
        """
        patch_json = json.dumps(patch, ensure_ascii=False)
        await asyncio.to_thread(self._patch_file.write_text, patch_json, encoding="utf-8")
        logger.debug(
            "broadcast_network_patch: wrote %d bytes to %s",
            len(patch_json),
            self._patch_file,
        )

    async def shutdown_all(self) -> None:
        """Kill all shard subprocesses and clean up the patch file."""
        for shard_id, state in self._shards.items():
            if state.process is not None and state.process.returncode is None:
                try:
                    state.process.kill()
                    try:
                        await asyncio.wait_for(state.process.wait(), timeout=3.0)
                    except asyncio.TimeoutError:
                        logger.warning(
                            "Shard %d did not exit within 3s after kill", shard_id
                        )
                except ProcessLookupError:
                    pass  # Already dead
                logger.info("Shard %d terminated", shard_id)

        if self._patch_file.exists():
            try:
                self._patch_file.unlink()
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_shard_configs(
        total_agents: int,
        agents_per_shard: int,
    ) -> list[ShardConfig]:
        """Compute even partitions of [0, total_agents)."""
        configs: list[ShardConfig] = []
        shard_id = 0
        start = 0
        while start < total_agents:
            end = min(start + agents_per_shard, total_agents)
            configs.append(ShardConfig(shard_id=shard_id, agent_start=start, agent_end=end))
            start = end
            shard_id += 1
        return configs

    async def _spawn_shard(self, cfg: ShardConfig) -> asyncio.subprocess.Process:
        """Spawn a subprocess with shard-specific env vars."""
        env = {**os.environ}
        env["SHARD_ID"] = str(cfg.shard_id)
        env["AGENT_START"] = str(cfg.agent_start)
        env["AGENT_END"] = str(cfg.agent_end)
        env["SESSION_ID"] = self._session_id
        env["SHARD_PATCH_FILE"] = str(self._patch_file)

        process = await asyncio.create_subprocess_exec(
            str(self._python_bin),
            str(self._script_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        return process

    async def _shard_reader(self, state: ShardState) -> None:
        """Read JSONL from shard stdout and push into the merge queue."""
        cfg = state.config
        if state.process is None or state.process.stdout is None:
            await self._merge_queue.put(None)
            return

        try:
            async for raw_line in state.process.stdout:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    # Inject shard metadata
                    msg["_shard_id"] = cfg.shard_id

                    # Signal round-sync barrier
                    if msg.get("type") == "round_sync":
                        event = self._sync_events.get(cfg.shard_id)
                        if event:
                            event.set()

                    await self._merge_queue.put(msg)
                except json.JSONDecodeError:
                    logger.debug("Shard %d non-JSON line: %s", cfg.shard_id, line[:120])
        except Exception as exc:
            logger.error("Shard %d reader error: %s", cfg.shard_id, exc)
            state.failed = True
        finally:
            # Sentinel: this shard's reader is done
            await self._merge_queue.put(None)
            logger.info("Shard %d reader finished", cfg.shard_id)
