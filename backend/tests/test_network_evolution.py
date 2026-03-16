"""Tests for Phase 1C: Dynamic Network Evolution.

Covers NetworkEvent/NetworkEvolutionStats models and NetworkEvolutionEngine
detection logic, persistence, and scorecard integration.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.models.network_evolution import NetworkEvent, NetworkEvolutionStats
from backend.app.services.network_evolution import NetworkEvolutionEngine


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestNetworkEventModel:
    def test_creation_defaults(self):
        e = NetworkEvent(
            session_id="sess-1",
            round_number=3,
            event_type="TIE_FORMED",
            agent_a_username="agent_1",
        )
        assert e.session_id == "sess-1"
        assert e.round_number == 3
        assert e.event_type == "TIE_FORMED"
        assert e.agent_a_username == "agent_1"
        assert e.agent_b_username == ""
        assert e.trust_delta == 0.0
        assert e.details == {}

    def test_frozen(self):
        e = NetworkEvent(
            session_id="sess-1",
            round_number=1,
            event_type="TIE_FORMED",
            agent_a_username="agent_1",
        )
        with pytest.raises(Exception):
            e.round_number = 99  # type: ignore[misc]

    def test_with_details(self):
        e = NetworkEvent(
            session_id="sess-1",
            round_number=2,
            event_type="BRIDGE_DETECTED",
            agent_a_username="bridge_agent",
            details={"clusters_bridged": [0, 1]},
        )
        assert e.details["clusters_bridged"] == [0, 1]

    def test_all_event_types_valid(self):
        """Confirm all 5 event types can be stored in the model."""
        for et in ("TIE_FORMED", "TIE_DISSOLVED", "BRIDGE_DETECTED", "TRIADIC_CLOSURE", "CLUSTER_SHIFT"):
            e = NetworkEvent(
                session_id="s", round_number=1, event_type=et, agent_a_username="a"
            )
            assert e.event_type == et


class TestNetworkEvolutionStatsModel:
    def test_defaults(self):
        s = NetworkEvolutionStats(session_id="s", round_number=1)
        assert s.ties_formed == 0
        assert s.ties_dissolved == 0
        assert s.bridges_detected == 0
        assert s.triadic_closures == 0
        assert s.cluster_shifts == 0
        assert s.density == 0.0
        assert s.avg_trust == 0.0

    def test_frozen(self):
        s = NetworkEvolutionStats(session_id="s", round_number=1)
        with pytest.raises(Exception):
            s.ties_formed = 10  # type: ignore[misc]

    def test_with_values(self):
        s = NetworkEvolutionStats(
            session_id="s",
            round_number=5,
            ties_formed=3,
            ties_dissolved=1,
            bridges_detected=2,
            triadic_closures=4,
            cluster_shifts=1,
            density=0.25,
            avg_trust=0.45,
        )
        assert s.ties_formed == 3
        assert s.density == 0.25
        assert s.avg_trust == 0.45


# ---------------------------------------------------------------------------
# Engine detection tests
# ---------------------------------------------------------------------------


class TestNetworkEvolutionEngineDetection:
    """Test detect_events() using in-memory trust dicts (no DB needed)."""

    @pytest.fixture
    def engine(self):
        return NetworkEvolutionEngine()

    @pytest.mark.asyncio
    async def test_tie_formed_detection(self, engine):
        """Trust crossing 0.3 triggers TIE_FORMED."""
        prev = {(1, 2): 0.1}
        curr = {(1, 2): 0.4}
        cluster = {"1": 0, "2": 0}

        with patch.object(engine, "_detect_triadic_closures", new=AsyncMock(return_value=[])):
            with patch.object(engine, "_load_stances", new=AsyncMock(return_value={})):
                events, stats = await engine.detect_events("s", 3, prev, curr, cluster)

        formed = [e for e in events if e.event_type == "TIE_FORMED"]
        assert len(formed) == 1
        assert formed[0].agent_a_username == "1"
        assert formed[0].agent_b_username == "2"
        assert stats.ties_formed == 1

    @pytest.mark.asyncio
    async def test_tie_dissolved_detection(self, engine):
        """Trust dropping below -0.1 triggers TIE_DISSOLVED."""
        prev = {(1, 2): 0.0}
        curr = {(1, 2): -0.2}
        cluster = {}

        with patch.object(engine, "_detect_triadic_closures", new=AsyncMock(return_value=[])):
            events, stats = await engine.detect_events("s", 2, prev, curr, cluster)

        dissolved = [e for e in events if e.event_type == "TIE_DISSOLVED"]
        assert len(dissolved) == 1
        assert stats.ties_dissolved == 1

    @pytest.mark.asyncio
    async def test_no_event_when_trust_stable(self, engine):
        """No event when trust stays within thresholds."""
        prev = {(1, 2): 0.5}
        curr = {(1, 2): 0.55}
        cluster = {}

        with patch.object(engine, "_detect_triadic_closures", new=AsyncMock(return_value=[])):
            events, stats = await engine.detect_events("s", 5, prev, curr, cluster)

        assert all(e.event_type not in ("TIE_FORMED", "TIE_DISSOLVED") for e in events)

    @pytest.mark.asyncio
    async def test_bridge_detected(self, engine):
        """Agent connecting 2+ clusters is detected as BRIDGE_DETECTED."""
        curr = {
            (1, 2): 0.5,  # 1 connected to 2 (cluster 0)
            (1, 3): 0.6,  # 1 connected to 3 (cluster 1)
        }
        prev: dict = {}
        cluster = {"1": 0, "2": 0, "3": 1}

        with patch.object(engine, "_detect_triadic_closures", new=AsyncMock(return_value=[])):
            events, stats = await engine.detect_events("s", 4, prev, curr, cluster)

        bridges = [e for e in events if e.event_type == "BRIDGE_DETECTED"]
        assert len(bridges) >= 1
        bridge_agents = {b.agent_a_username for b in bridges}
        assert "1" in bridge_agents
        assert stats.bridges_detected >= 1

    @pytest.mark.asyncio
    async def test_cluster_shift(self, engine):
        """Agent moving to different cluster triggers CLUSTER_SHIFT."""
        # Set previous cluster state
        engine._prev_clusters["s"] = {"agent_1": 0}
        curr = {(1, 2): 0.4}
        prev: dict = {}
        cluster_new = {"agent_1": 1}  # moved from cluster 0 to 1

        with patch.object(engine, "_detect_triadic_closures", new=AsyncMock(return_value=[])):
            events, stats = await engine.detect_events("s", 6, prev, curr, cluster_new)

        shifts = [e for e in events if e.event_type == "CLUSTER_SHIFT"]
        assert len(shifts) == 1
        assert shifts[0].agent_a_username == "agent_1"
        assert shifts[0].details["from_cluster"] == 0
        assert shifts[0].details["to_cluster"] == 1
        assert stats.cluster_shifts == 1

    @pytest.mark.asyncio
    async def test_empty_trust_dict(self, engine):
        """Empty trust dicts produce no events and zero stats."""
        with patch.object(engine, "_detect_triadic_closures", new=AsyncMock(return_value=[])):
            events, stats = await engine.detect_events("s", 1, {}, {}, {})

        assert events == []
        assert stats.ties_formed == 0

    @pytest.mark.asyncio
    async def test_single_agent_stable_trust_no_events(self, engine):
        """Agent with stable trust (already above threshold) produces no tie events."""
        prev = {(1, 2): 0.8}  # already above threshold
        curr = {(1, 2): 0.85}  # stayed above threshold — no TIE_FORMED
        cluster = {}

        with patch.object(engine, "_detect_triadic_closures", new=AsyncMock(return_value=[])):
            events, _ = await engine.detect_events("s", 2, prev, curr, cluster)

        tie_events = [e for e in events if e.event_type in ("TIE_FORMED", "TIE_DISSOLVED")]
        assert len(tie_events) == 0

    @pytest.mark.asyncio
    async def test_no_bridge_with_single_cluster(self, engine):
        """Agents all in same cluster → no bridge detected."""
        curr = {
            (1, 2): 0.5,
            (1, 3): 0.6,
        }
        cluster = {"1": 0, "2": 0, "3": 0}

        with patch.object(engine, "_detect_triadic_closures", new=AsyncMock(return_value=[])):
            events, stats = await engine.detect_events("s", 3, {}, curr, cluster)

        bridges = [e for e in events if e.event_type == "BRIDGE_DETECTED"]
        assert len(bridges) == 0
        assert stats.bridges_detected == 0

    @pytest.mark.asyncio
    async def test_stats_density_computed(self, engine):
        """Stats include computed density > 0 when edges exist."""
        curr = {(1, 2): 0.4, (2, 3): 0.5, (1, 3): 0.3}
        cluster = {}
        with patch.object(engine, "_detect_triadic_closures", new=AsyncMock(return_value=[])):
            _, stats = await engine.detect_events("s", 2, {}, curr, cluster)

        assert stats.density > 0.0

    @pytest.mark.asyncio
    async def test_stats_avg_trust(self, engine):
        """Stats include correct avg trust."""
        curr = {(1, 2): 0.4, (2, 3): 0.6}
        cluster = {}
        with patch.object(engine, "_detect_triadic_closures", new=AsyncMock(return_value=[])):
            _, stats = await engine.detect_events("s", 2, {}, curr, cluster)

        assert abs(stats.avg_trust - 0.5) < 0.01


# ---------------------------------------------------------------------------
# Triadic closure tests
# ---------------------------------------------------------------------------


class TestTriadicClosure:
    @pytest.mark.asyncio
    async def test_triadic_closure_with_similar_stances(self):
        """A→B + B→C where A and C have similar stances generates TRIADIC_CLOSURE."""
        engine = NetworkEvolutionEngine()
        # Build strong edges: A→B and B→C
        curr_trusts = {(1, 2): 0.6, (2, 3): 0.7}
        # A and C have similar stances
        stances = {"1": 0.8, "2": 0.5, "3": 0.75}
        cluster = {}

        with patch.object(engine, "_load_stances", new=AsyncMock(return_value=stances)):
            events = await engine._detect_triadic_closures("s", 5, curr_trusts, cluster)

        triadic = [e for e in events if e.event_type == "TRIADIC_CLOSURE"]
        assert len(triadic) >= 1
        # Should suggest closing A→C
        assert any(
            e.agent_a_username == "1" and e.details.get("suggested_followee") == "3"
            for e in triadic
        )

    @pytest.mark.asyncio
    async def test_no_triadic_closure_dissimilar_stances(self):
        """Dissimilar stances below threshold → no triadic closure suggested."""
        engine = NetworkEvolutionEngine()
        curr_trusts = {(1, 2): 0.6, (2, 3): 0.7}
        stances = {"1": -0.9, "2": 0.0, "3": 0.9}  # very different stances

        with patch.object(engine, "_load_stances", new=AsyncMock(return_value=stances)):
            events = await engine._detect_triadic_closures("s", 2, curr_trusts, {})

        assert all(e.event_type != "TRIADIC_CLOSURE" for e in events)


# ---------------------------------------------------------------------------
# Persistence tests
# ---------------------------------------------------------------------------


class TestNetworkEvolutionPersistence:
    @pytest.mark.asyncio
    async def test_persist_events_empty(self):
        """Persisting empty list is a no-op (no DB error)."""
        engine = NetworkEvolutionEngine()
        mock_db = AsyncMock()
        with patch("backend.app.services.network_evolution.get_db") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)
            await engine.persist_events("s", [])
        mock_db.executemany.assert_not_called()

    @pytest.mark.asyncio
    async def test_persist_events_calls_executemany(self):
        """Non-empty event list triggers executemany."""
        engine = NetworkEvolutionEngine()
        events = [
            NetworkEvent(session_id="s", round_number=1, event_type="TIE_FORMED",
                         agent_a_username="1", agent_b_username="2", trust_delta=0.2),
        ]
        mock_db = AsyncMock()
        with patch("backend.app.services.network_evolution.get_db") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)
            await engine.persist_events("s", events)

        mock_db.executemany.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_write_network_patch_creates_file(self, tmp_path, monkeypatch):
        """write_network_patch creates the JSON file in the session dir."""
        engine = NetworkEvolutionEngine()
        session_id = "test-sess-001"
        monkeypatch.setattr(
            "backend.app.services.network_evolution._PROJECT_ROOT", tmp_path
        )

        events = [
            NetworkEvent(
                session_id=session_id,
                round_number=3,
                event_type="TRIADIC_CLOSURE",
                agent_a_username="100",
                agent_b_username="200",
                trust_delta=0.0,
                details={"suggested_followee": "300"},
            ),
        ]
        await engine.write_network_patch(session_id, events)

        patch_path = tmp_path / "data" / "sessions" / session_id / "network_patch.json"
        assert patch_path.is_file()
        data = json.loads(patch_path.read_text())
        assert len(data["suggested_follows"]) == 1
        assert data["suggested_follows"][0]["follower"] == "100"
        assert data["suggested_follows"][0]["followee"] == "300"

    @pytest.mark.asyncio
    async def test_write_network_patch_empty_no_file(self, tmp_path, monkeypatch):
        """Empty triadic closures → no patch file created."""
        engine = NetworkEvolutionEngine()
        monkeypatch.setattr(
            "backend.app.services.network_evolution._PROJECT_ROOT", tmp_path
        )
        await engine.write_network_patch("sess-none", [])
        patch_path = tmp_path / "data" / "sessions" / "sess-none" / "network_patch.json"
        assert not patch_path.is_file()


# ---------------------------------------------------------------------------
# get_events filter tests
# ---------------------------------------------------------------------------


class TestGetEventsFilters:
    @pytest.mark.asyncio
    async def test_get_events_no_filters(self):
        """get_events with no filters returns all rows."""
        engine = NetworkEvolutionEngine()
        mock_row = ("s", 1, "TIE_FORMED", "1", "2", 0.3, '{"prev": 0.1}')
        mock_db = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[mock_row])
        mock_db.execute = AsyncMock(return_value=mock_cursor)

        with patch("backend.app.services.network_evolution.get_db") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)
            events = await engine.get_events("s")

        assert len(events) == 1
        assert events[0].event_type == "TIE_FORMED"
        assert events[0].details == {"prev": 0.1}

    @pytest.mark.asyncio
    async def test_get_events_with_round_filter(self):
        """get_events includes round_number param in SQL query."""
        engine = NetworkEvolutionEngine()
        mock_db = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])
        mock_db.execute = AsyncMock(return_value=mock_cursor)

        with patch("backend.app.services.network_evolution.get_db") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)
            events = await engine.get_events("s", round_number=5)

        # Verify the query was called with round_number param
        call_args = mock_db.execute.call_args
        params = call_args[0][1]
        assert 5 in params

    @pytest.mark.asyncio
    async def test_get_events_with_type_filter(self):
        """get_events includes event_type param in SQL query."""
        engine = NetworkEvolutionEngine()
        mock_db = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])
        mock_db.execute = AsyncMock(return_value=mock_cursor)

        with patch("backend.app.services.network_evolution.get_db") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)
            events = await engine.get_events("s", event_type="BRIDGE_DETECTED")

        call_args = mock_db.execute.call_args
        params = call_args[0][1]
        assert "BRIDGE_DETECTED" in params


# ---------------------------------------------------------------------------
# Scorecard: network_volatility
# ---------------------------------------------------------------------------


class TestNetworkVolatility:
    @pytest.mark.asyncio
    async def test_network_volatility_zero_with_no_data(self):
        """Returns 0.0 when no network_events rows exist."""
        from backend.app.services.emergence_scorecard import EmergenceScorecardGenerator

        gen = EmergenceScorecardGenerator()
        mock_db = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])
        mock_a_cursor = AsyncMock()
        mock_a_cursor.fetchone = AsyncMock(return_value=[100])
        mock_db.execute = AsyncMock(side_effect=[mock_cursor, mock_a_cursor])

        with patch("backend.app.services.emergence_scorecard.get_db") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await gen._network_volatility("s")

        assert result == 0.0

    @pytest.mark.asyncio
    async def test_network_volatility_positive_with_events(self):
        """Returns a positive float when events exist."""
        from backend.app.services.emergence_scorecard import EmergenceScorecardGenerator

        gen = EmergenceScorecardGenerator()
        mock_db = AsyncMock()
        mock_cursor = AsyncMock()
        # 2 rounds, 10 and 6 events each
        mock_cursor.fetchall = AsyncMock(return_value=[(1, 10), (2, 6)])
        mock_a_cursor = AsyncMock()
        mock_a_cursor.fetchone = AsyncMock(return_value=[100])

        call_count = 0

        async def side_effect(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_cursor
            return mock_a_cursor

        mock_db.execute = AsyncMock(side_effect=side_effect)

        with patch("backend.app.services.emergence_scorecard.get_db") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await gen._network_volatility("s")

        # avg events per round = 8, agents = 100 → 0.08
        assert result > 0.0
        assert abs(result - 0.08) < 0.001

    @pytest.mark.asyncio
    async def test_network_volatility_above_threshold_grade_not_f(self):
        """Grade improves with network_volatility > 0.05 (not F or D)."""
        from backend.app.services.emergence_scorecard import _compute_grade

        grade = _compute_grade(
            emergence_ratio=0.8,
            bias_contamination=0.1,
            max_cascade_depth=5,
            action_diversity=2.5,
            network_volatility=0.1,
            belief_revision_rate=0.1,  # Phase 3 also required for Grade A
        )
        assert grade == "A"

    @pytest.mark.asyncio
    async def test_network_volatility_below_threshold_no_grade_a(self):
        """Grade A NOT awarded when network_volatility <= 0.05."""
        from backend.app.services.emergence_scorecard import _compute_grade

        grade = _compute_grade(
            emergence_ratio=0.8,
            bias_contamination=0.1,
            max_cascade_depth=5,
            action_diversity=2.5,
            network_volatility=0.01,  # below threshold
            belief_revision_rate=0.1,
        )
        assert grade != "A"
