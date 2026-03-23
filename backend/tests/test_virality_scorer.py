"""Tests for Phase 2: ViralityScorer.

Covers ViralityScore model, cascade computation, virality index formula,
and persistence with ON CONFLICT upsert.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.app.models.recommendation import ViralityScore
from backend.app.services.virality_scorer import ViralityScorer

# ---------------------------------------------------------------------------
# ViralityScore model tests
# ---------------------------------------------------------------------------


class TestViralityScoreModel:
    def test_creation(self):
        vs = ViralityScore(
            post_id="100",
            session_id="sess-1",
            cascade_depth=3,
            cascade_breadth=15,
            velocity=2.5,
            reproduction_number=0.15,
            cross_cluster_reach=0.6,
            virality_index=0.45,
        )
        assert vs.post_id == "100"
        assert vs.cascade_depth == 3
        assert vs.virality_index == 0.45

    def test_frozen(self):
        vs = ViralityScore(
            post_id="1",
            session_id="s",
            cascade_depth=0,
            cascade_breadth=1,
            velocity=0.0,
            reproduction_number=0.0,
            cross_cluster_reach=0.0,
            virality_index=0.0,
        )
        with pytest.raises(Exception):
            vs.virality_index = 1.0  # type: ignore[misc]

    def test_zero_defaults(self):
        vs = ViralityScore(
            post_id="42",
            session_id="sess",
            cascade_depth=0,
            cascade_breadth=0,
            velocity=0.0,
            reproduction_number=0.0,
            cross_cluster_reach=0.0,
            virality_index=0.0,
        )
        assert vs.cascade_depth == 0
        assert vs.virality_index == 0.0


# ---------------------------------------------------------------------------
# ViralityScorer.score_posts tests
# ---------------------------------------------------------------------------


def _make_db_with_rows(root_rows, all_rows, cluster_row=None, total_agents_row=None):
    """Create a mock db with preset cursor results."""
    mock_db = AsyncMock()

    call_count = 0

    async def mock_execute(sql, params=None):
        nonlocal call_count
        call_count += 1
        mock_cursor = AsyncMock()

        if call_count == 1:
            # First call: root posts
            mock_cursor.fetchall = AsyncMock(return_value=root_rows)
        elif call_count == 2:
            # Second call: all cascade data
            mock_cursor.fetchall = AsyncMock(return_value=all_rows)
        elif call_count == 3:
            # Third call: echo chamber cluster
            mock_cursor.fetchone = AsyncMock(return_value=cluster_row or (None,))
        elif call_count >= 4:
            # Remaining calls: total agent count per root post
            mock_cursor.fetchone = AsyncMock(return_value=total_agents_row or (100,))
        return mock_cursor

    mock_db.execute = AsyncMock(side_effect=mock_execute)
    return mock_db


class TestViralityScorerScorePosts:
    @pytest.mark.asyncio
    async def test_empty_session_returns_empty(self):
        """Session with no root posts returns empty list."""
        scorer = ViralityScorer()
        mock_db = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])
        mock_db.execute = AsyncMock(return_value=mock_cursor)

        result = await scorer.score_posts("s", 5, mock_db)
        assert result == []

    @pytest.mark.asyncio
    async def test_single_post_no_cascade(self):
        """Single root post with no children: depth=0, breadth=0."""
        scorer = ViralityScorer()

        # root_rows: (id, agent_id, round_number)
        root_rows = [(1, 10, 3)]
        # all_rows: (id, agent_id, round_number, parent_id, depth)
        all_rows = [(1, 10, 3, 0, 0)]

        call_count = 0

        async def mock_execute(sql, params=None):
            nonlocal call_count
            call_count += 1
            mock_cursor = AsyncMock()
            if call_count == 1:
                mock_cursor.fetchall = AsyncMock(return_value=root_rows)
            elif call_count == 2:
                mock_cursor.fetchall = AsyncMock(return_value=all_rows)
            elif call_count == 3:
                # cluster query
                mock_cursor.fetchone = AsyncMock(return_value=(None,))
            else:
                mock_cursor.fetchone = AsyncMock(return_value=(100,))
            return mock_cursor

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=mock_execute)

        result = await scorer.score_posts("s", 5, mock_db)
        assert len(result) == 1
        score = result[0]
        assert score.post_id == "1"
        assert score.cascade_depth == 0
        assert score.cascade_breadth == 0

    @pytest.mark.asyncio
    async def test_cascade_depth_computed(self):
        """Post with 2-hop cascade has depth=2."""
        scorer = ViralityScorer()

        root_rows = [(1, 10, 1)]
        all_rows = [
            (1, 10, 1, 0, 0),  # root
            (2, 11, 2, 1, 1),  # depth 1
            (3, 12, 3, 2, 2),  # depth 2
        ]

        call_count = 0

        async def mock_execute(sql, params=None):
            nonlocal call_count
            call_count += 1
            mock_cursor = AsyncMock()
            if call_count == 1:
                mock_cursor.fetchall = AsyncMock(return_value=root_rows)
            elif call_count == 2:
                mock_cursor.fetchall = AsyncMock(return_value=all_rows)
            elif call_count == 3:
                mock_cursor.fetchone = AsyncMock(return_value=(None,))
            else:
                mock_cursor.fetchone = AsyncMock(return_value=(100,))
            return mock_cursor

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=mock_execute)

        result = await scorer.score_posts("s", 5, mock_db)
        assert result[0].cascade_depth == 2

    @pytest.mark.asyncio
    async def test_cascade_breadth_counts_unique_agents(self):
        """Breadth = number of distinct agents that received the post."""
        scorer = ViralityScorer()

        root_rows = [(1, 10, 1)]
        # 3 unique agents (11, 12, 13) re-shared
        all_rows = [
            (1, 10, 1, 0, 0),
            (2, 11, 2, 1, 1),
            (3, 12, 2, 1, 1),
            (4, 13, 3, 2, 2),
        ]

        call_count = 0

        async def mock_execute(sql, params=None):
            nonlocal call_count
            call_count += 1
            mock_cursor = AsyncMock()
            if call_count == 1:
                mock_cursor.fetchall = AsyncMock(return_value=root_rows)
            elif call_count == 2:
                mock_cursor.fetchall = AsyncMock(return_value=all_rows)
            elif call_count == 3:
                mock_cursor.fetchone = AsyncMock(return_value=(None,))
            else:
                mock_cursor.fetchone = AsyncMock(return_value=(100,))
            return mock_cursor

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=mock_execute)

        result = await scorer.score_posts("s", 5, mock_db)
        # 3 additional agents (11, 12, 13), not counting root (10)
        assert result[0].cascade_breadth == 3

    @pytest.mark.asyncio
    async def test_velocity_is_breadth_over_rounds(self):
        """velocity = breadth / rounds_elapsed."""
        scorer = ViralityScorer()

        root_rows = [(1, 10, 1)]
        all_rows = [
            (1, 10, 1, 0, 0),
            (2, 11, 2, 1, 1),  # +1 agent
        ]

        call_count = 0

        async def mock_execute(sql, params=None):
            nonlocal call_count
            call_count += 1
            mock_cursor = AsyncMock()
            if call_count == 1:
                mock_cursor.fetchall = AsyncMock(return_value=root_rows)
            elif call_count == 2:
                mock_cursor.fetchall = AsyncMock(return_value=all_rows)
            elif call_count == 3:
                mock_cursor.fetchone = AsyncMock(return_value=(None,))
            else:
                mock_cursor.fetchone = AsyncMock(return_value=(10,))
            return mock_cursor

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=mock_execute)

        result = await scorer.score_posts("s", 5, mock_db)
        # breadth=1, rounds_elapsed=5-1=4 → velocity=0.25
        assert abs(result[0].velocity - 0.25) < 0.01

    @pytest.mark.asyncio
    async def test_virality_index_in_range(self):
        """virality_index is in [0, 1]."""
        scorer = ViralityScorer()

        root_rows = [(1, 10, 1)]
        all_rows = [
            (1, 10, 1, 0, 0),
            (2, 11, 2, 1, 1),
        ]

        call_count = 0

        async def mock_execute(sql, params=None):
            nonlocal call_count
            call_count += 1
            mock_cursor = AsyncMock()
            if call_count == 1:
                mock_cursor.fetchall = AsyncMock(return_value=root_rows)
            elif call_count == 2:
                mock_cursor.fetchall = AsyncMock(return_value=all_rows)
            elif call_count == 3:
                mock_cursor.fetchone = AsyncMock(return_value=(None,))
            else:
                mock_cursor.fetchone = AsyncMock(return_value=(100,))
            return mock_cursor

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=mock_execute)

        result = await scorer.score_posts("s", 5, mock_db)
        vi = result[0].virality_index
        assert 0.0 <= vi <= 1.0

    @pytest.mark.asyncio
    async def test_cross_cluster_reach_with_clusters(self):
        """cross_cluster_reach = distinct clusters reached / total clusters."""
        scorer = ViralityScorer()

        # Mock _load_clusters to return cluster mapping
        with patch.object(
            scorer,
            "_load_clusters",
            new=AsyncMock(
                return_value={
                    "10": 0,
                    "11": 1,
                    "12": 2,
                }
            ),
        ):
            root_rows = [(1, 10, 1)]
            all_rows = [
                (1, 10, 1, 0, 0),
                (2, 11, 2, 1, 1),  # cluster 1
                (3, 12, 3, 2, 2),  # cluster 2
            ]

            call_count = 0

            async def mock_execute(sql, params=None):
                nonlocal call_count
                call_count += 1
                mock_cursor = AsyncMock()
                if call_count == 1:
                    mock_cursor.fetchall = AsyncMock(return_value=root_rows)
                elif call_count == 2:
                    mock_cursor.fetchall = AsyncMock(return_value=all_rows)
                else:
                    mock_cursor.fetchone = AsyncMock(return_value=(100,))
                return mock_cursor

            mock_db = AsyncMock()
            mock_db.execute = AsyncMock(side_effect=mock_execute)

            result = await scorer.score_posts("s", 5, mock_db)
            # 3 clusters total (0, 1, 2), 3 reached → cross_cluster_reach = 1.0
            assert result[0].cross_cluster_reach >= 0.9


# ---------------------------------------------------------------------------
# ViralityScorer.persist_scores tests
# ---------------------------------------------------------------------------


class TestPersistScores:
    @pytest.mark.asyncio
    async def test_persist_empty_no_db_call(self):
        scorer = ViralityScorer()
        mock_db = AsyncMock()
        await scorer.persist_scores("s", [], mock_db)
        mock_db.executemany.assert_not_called()

    @pytest.mark.asyncio
    async def test_persist_uses_upsert(self):
        scorer = ViralityScorer()
        mock_db = AsyncMock()
        scores = [
            ViralityScore(
                post_id="100",
                session_id="s",
                cascade_depth=2,
                cascade_breadth=5,
                velocity=1.0,
                reproduction_number=0.05,
                cross_cluster_reach=0.5,
                virality_index=0.3,
            ),
        ]
        await scorer.persist_scores("s", scores, mock_db)
        mock_db.executemany.assert_called_once()
        # Check ON CONFLICT present in SQL
        sql = mock_db.executemany.call_args[0][0]
        assert "ON CONFLICT" in sql
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_persist_multiple_scores(self):
        scorer = ViralityScorer()
        mock_db = AsyncMock()
        scores = [
            ViralityScore(
                post_id=str(i),
                session_id="s",
                cascade_depth=i,
                cascade_breadth=i * 2,
                velocity=float(i),
                reproduction_number=0.1,
                cross_cluster_reach=0.4,
                virality_index=0.3,
            )
            for i in range(1, 6)
        ]
        await scorer.persist_scores("s", scores, mock_db)
        # Verify 5 rows were passed to executemany
        rows = mock_db.executemany.call_args[0][1]
        assert len(rows) == 5


# ---------------------------------------------------------------------------
# _load_clusters helper
# ---------------------------------------------------------------------------


class TestLoadClusters:
    @pytest.mark.asyncio
    async def test_load_clusters_empty_when_no_data(self):
        scorer = ViralityScorer()
        mock_db = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=None)
        mock_db.execute = AsyncMock(return_value=mock_cursor)

        result = await scorer._load_clusters("s", mock_db)
        assert result == {}

    @pytest.mark.asyncio
    async def test_load_clusters_parses_json(self):
        scorer = ViralityScorer()
        mock_db = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=('{"10": 0, "11": 1, "12": 2}',))
        mock_db.execute = AsyncMock(return_value=mock_cursor)

        result = await scorer._load_clusters("s", mock_db)
        assert result == {"10": 0, "11": 1, "12": 2}
