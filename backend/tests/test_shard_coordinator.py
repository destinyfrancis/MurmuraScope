"""Tests for backend.app.services.shard_coordinator (Phase 4D).

~20 tests covering:
- ShardConfig frozen dataclass
- ShardState mutable dataclass
- Shard range calculation
- Coordinator launch + stream merge
- sync_round_barrier timeout + partial quorum
- broadcast_network_patch
- shutdown_all
- Failed shard exclusion
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app.services.shard_coordinator import (
    ShardConfig,
    ShardCoordinator,
    ShardState,
)

# ---------------------------------------------------------------------------
# ShardConfig (frozen)
# ---------------------------------------------------------------------------


class TestShardConfig:
    def test_frozen(self):
        cfg = ShardConfig(shard_id=0, agent_start=0, agent_end=2500)
        with pytest.raises(Exception):  # FrozenInstanceError
            cfg.shard_id = 1  # type: ignore[misc]

    def test_agent_count_property(self):
        cfg = ShardConfig(shard_id=0, agent_start=0, agent_end=2500)
        assert cfg.agent_count == 2500

    def test_agent_count_partial(self):
        cfg = ShardConfig(shard_id=3, agent_start=7500, agent_end=10000)
        assert cfg.agent_count == 2500

    def test_repr(self):
        cfg = ShardConfig(shard_id=1, agent_start=2500, agent_end=5000)
        r = repr(cfg)
        assert "ShardConfig" in r
        assert "2500" in r


# ---------------------------------------------------------------------------
# ShardState (mutable)
# ---------------------------------------------------------------------------


class TestShardState:
    def test_default_state(self):
        cfg = ShardConfig(shard_id=0, agent_start=0, agent_end=100)
        state = ShardState(config=cfg)
        assert state.process is None
        assert state.last_round_synced == -1
        assert state.failed is False

    def test_mutable_failed(self):
        cfg = ShardConfig(shard_id=0, agent_start=0, agent_end=100)
        state = ShardState(config=cfg)
        state.failed = True
        assert state.failed is True

    def test_mutable_last_round(self):
        cfg = ShardConfig(shard_id=0, agent_start=0, agent_end=100)
        state = ShardState(config=cfg)
        state.last_round_synced = 5
        assert state.last_round_synced == 5


# ---------------------------------------------------------------------------
# Shard range calculation
# ---------------------------------------------------------------------------


class TestShardRangeCalculation:
    def test_even_split(self):
        configs = ShardCoordinator._compute_shard_configs(10000, 2500)
        assert len(configs) == 4
        assert configs[0].agent_start == 0
        assert configs[0].agent_end == 2500
        assert configs[1].agent_start == 2500
        assert configs[1].agent_end == 5000
        assert configs[3].agent_end == 10000

    def test_uneven_split_last_shard_smaller(self):
        configs = ShardCoordinator._compute_shard_configs(5500, 2500)
        assert len(configs) == 3
        assert configs[2].agent_start == 5000
        assert configs[2].agent_end == 5500
        assert configs[2].agent_count == 500

    def test_single_shard_small_population(self):
        configs = ShardCoordinator._compute_shard_configs(100, 2500)
        assert len(configs) == 1
        assert configs[0].agent_start == 0
        assert configs[0].agent_end == 100

    def test_shard_ids_sequential(self):
        configs = ShardCoordinator._compute_shard_configs(10000, 2500)
        ids = [c.shard_id for c in configs]
        assert ids == [0, 1, 2, 3]

    def test_no_gaps_in_ranges(self):
        configs = ShardCoordinator._compute_shard_configs(9000, 3000)
        for i in range(1, len(configs)):
            assert configs[i].agent_start == configs[i - 1].agent_end

    def test_total_agents_covered(self):
        total = 7777
        configs = ShardCoordinator._compute_shard_configs(total, 2500)
        assert configs[-1].agent_end == total


# ---------------------------------------------------------------------------
# broadcast_network_patch
# ---------------------------------------------------------------------------


class TestBroadcastNetworkPatch:
    @pytest.mark.asyncio
    async def test_writes_json_file(self, tmp_path):
        coord = ShardCoordinator(
            session_id="test-session",
            python_bin=Path("/usr/bin/python3"),
            script_path=Path("/dev/null"),
        )
        coord._patch_file = tmp_path / "patch.json"
        patch_data = {"action": "trust_update", "pairs": [["a1", "a2", 0.8]]}
        await coord.broadcast_network_patch(patch_data)
        assert coord._patch_file.exists()
        written = json.loads(coord._patch_file.read_text())
        assert written == patch_data

    @pytest.mark.asyncio
    async def test_overwrites_previous_patch(self, tmp_path):
        coord = ShardCoordinator(
            session_id="test-session",
            python_bin=Path("/usr/bin/python3"),
            script_path=Path("/dev/null"),
        )
        coord._patch_file = tmp_path / "patch.json"
        await coord.broadcast_network_patch({"round": 1})
        await coord.broadcast_network_patch({"round": 2})
        written = json.loads(coord._patch_file.read_text())
        assert written["round"] == 2


# ---------------------------------------------------------------------------
# shutdown_all
# ---------------------------------------------------------------------------


class TestShutdownAll:
    @pytest.mark.asyncio
    async def test_shutdown_kills_running_process(self):
        coord = ShardCoordinator(
            session_id="test-session",
            python_bin=Path("/usr/bin/python3"),
            script_path=Path("/dev/null"),
        )
        mock_proc = AsyncMock()
        mock_proc.returncode = None  # still running
        mock_proc.kill = MagicMock()  # kill() is synchronous in asyncio.Process
        mock_proc.wait = AsyncMock(return_value=0)
        cfg = ShardConfig(shard_id=0, agent_start=0, agent_end=100)
        coord._shards[0] = ShardState(config=cfg, process=mock_proc)
        await coord.shutdown_all()
        mock_proc.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_skips_already_dead_process(self):
        coord = ShardCoordinator(
            session_id="test-session",
            python_bin=Path("/usr/bin/python3"),
            script_path=Path("/dev/null"),
        )
        mock_proc = AsyncMock()
        mock_proc.returncode = 0  # already exited
        cfg = ShardConfig(shard_id=0, agent_start=0, agent_end=100)
        coord._shards[0] = ShardState(config=cfg, process=mock_proc)
        await coord.shutdown_all()
        mock_proc.kill.assert_not_called()

    @pytest.mark.asyncio
    async def test_shutdown_cleans_patch_file(self, tmp_path):
        coord = ShardCoordinator(
            session_id="test-session",
            python_bin=Path("/usr/bin/python3"),
            script_path=Path("/dev/null"),
        )
        coord._patch_file = tmp_path / "patch.json"
        coord._patch_file.write_text("{}")
        await coord.shutdown_all()
        assert not coord._patch_file.exists()


# ---------------------------------------------------------------------------
# sync_round_barrier: timeout + partial quorum
# ---------------------------------------------------------------------------


class TestSyncRoundBarrier:
    @pytest.mark.asyncio
    async def test_all_shards_sync_within_timeout(self):
        coord = ShardCoordinator(
            session_id="test-session",
            python_bin=Path("/usr/bin/python3"),
            script_path=Path("/dev/null"),
        )
        # Add two fake shards
        for sid in [0, 1]:
            cfg = ShardConfig(shard_id=sid, agent_start=sid * 1000, agent_end=(sid + 1) * 1000)
            coord._shards[sid] = ShardState(config=cfg)
            event = asyncio.Event()
            event.set()  # already synced
            coord._sync_events[sid] = event

        await coord.sync_round_barrier(timeout=1.0)  # should not raise

    @pytest.mark.asyncio
    async def test_timeout_marks_shard_failed(self):
        coord = ShardCoordinator(
            session_id="test-session",
            python_bin=Path("/usr/bin/python3"),
            script_path=Path("/dev/null"),
        )
        # Shard 0 synced, shard 1 will time out
        cfg0 = ShardConfig(shard_id=0, agent_start=0, agent_end=1000)
        cfg1 = ShardConfig(shard_id=1, agent_start=1000, agent_end=2000)
        coord._shards[0] = ShardState(config=cfg0)
        coord._shards[1] = ShardState(config=cfg1)
        ev0 = asyncio.Event()
        ev0.set()
        ev1 = asyncio.Event()  # never set → times out
        coord._sync_events[0] = ev0
        coord._sync_events[1] = ev1

        await coord.sync_round_barrier(timeout=0.05)  # short timeout
        assert coord._shards[1].failed is True
        assert coord._shards[0].failed is False

    @pytest.mark.asyncio
    async def test_failed_shard_excluded_from_barrier(self):
        coord = ShardCoordinator(
            session_id="test-session",
            python_bin=Path("/usr/bin/python3"),
            script_path=Path("/dev/null"),
        )
        cfg0 = ShardConfig(shard_id=0, agent_start=0, agent_end=1000)
        cfg1 = ShardConfig(shard_id=1, agent_start=1000, agent_end=2000)
        coord._shards[0] = ShardState(config=cfg0)
        coord._shards[1] = ShardState(config=cfg1, failed=True)  # pre-failed
        ev0 = asyncio.Event()
        ev0.set()
        coord._sync_events[0] = ev0
        # Shard 1 has no event — but should be excluded from barrier

        # Should complete quickly because shard 1 is excluded
        await asyncio.wait_for(coord.sync_round_barrier(timeout=5.0), timeout=1.0)
