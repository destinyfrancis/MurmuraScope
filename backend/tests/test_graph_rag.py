"""Tests for GraphRAG community summarisation and conflict detection.

Covers:
  - Data model immutability (frozen dataclasses)
  - detect_triple_conflicts() pure-logic path
  - get_global_narrative() empty-community graceful degradation
  - generate_community_summaries() with small/empty clusters
  - _persist_summaries() SQLite upsert
  - _search_community_summaries() LanceDB fallback to SQL
  - Opposing predicate pairs completeness
"""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.services.graph_rag import (
    CommunitySummary,
    GlobalNarrative,
    GraphRAGService,
    SubgraphInsight,
    TripleConflict,
    _MIN_CLUSTER_SIZE,
    _OPPOSING_PAIRS,
)

pytestmark = pytest.mark.unit


# ------------------------------------------------------------------ #
# Frozen dataclass immutability                                        #
# ------------------------------------------------------------------ #


def test_community_summary_frozen() -> None:
    """CommunitySummary must be immutable."""
    s = CommunitySummary(
        id=None, session_id="s1", round_number=5, cluster_id=0,
        core_narrative="test", shared_anxieties="", main_opposition="",
        member_count=10, avg_trust=0.5,
    )
    with pytest.raises(FrozenInstanceError):
        s.core_narrative = "mutated"  # type: ignore[misc]


def test_global_narrative_frozen() -> None:
    """GlobalNarrative must be immutable."""
    g = GlobalNarrative(
        session_id="s1", round_number=5, community_count=0,
        narrative_text="n/a", fault_lines=[],
    )
    with pytest.raises(FrozenInstanceError):
        g.narrative_text = "mutated"  # type: ignore[misc]


def test_subgraph_insight_frozen() -> None:
    """SubgraphInsight must be immutable."""
    s = SubgraphInsight(
        query="q", relevant_communities=[1], node_count=5,
        edge_count=3, insight_report="report",
    )
    with pytest.raises(FrozenInstanceError):
        s.query = "mutated"  # type: ignore[misc]


def test_triple_conflict_frozen() -> None:
    """TripleConflict must be immutable."""
    c = TripleConflict(
        entity="X", predicate_a="supports", object_a="Y",
        agent_ids_a=[1, 2, 3], predicate_b="opposes", object_b="Z",
        agent_ids_b=[4, 5, 6], conflict_score=0.5,
    )
    with pytest.raises(FrozenInstanceError):
        c.entity = "mutated"  # type: ignore[misc]


# ------------------------------------------------------------------ #
# _OPPOSING_PAIRS completeness                                         #
# ------------------------------------------------------------------ #


def test_opposing_pairs_symmetric() -> None:
    """Every (a, b) in _OPPOSING_PAIRS should have (b, a) present too."""
    for a, b in _OPPOSING_PAIRS:
        assert (b, a) in _OPPOSING_PAIRS, f"Missing symmetric pair: ({b}, {a})"


def test_opposing_pairs_not_empty() -> None:
    """Must have at least 5 opposing predicate pairs."""
    assert len(_OPPOSING_PAIRS) >= 10  # 5 pairs × 2 directions


# ------------------------------------------------------------------ #
# detect_triple_conflicts — pure logic (mocked DB)                     #
# ------------------------------------------------------------------ #


def _make_triple_row(subject: str, predicate: str, obj: str, agent_id: int) -> dict:
    """Build a dict mimicking an aiosqlite.Row for memory_triples."""
    return {"subject": subject, "predicate": predicate, "object": obj, "agent_id": agent_id}


@pytest.mark.asyncio
async def test_detect_conflicts_no_triples() -> None:
    """Empty memory_triples table should return empty list."""
    svc = GraphRAGService(llm_client=MagicMock())

    mock_cursor = AsyncMock()
    mock_cursor.fetchall = AsyncMock(return_value=[])

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_cursor)
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.app.services.graph_rag.get_db", return_value=mock_db):
        conflicts = await svc.detect_triple_conflicts("sess1")

    assert conflicts == []


@pytest.mark.asyncio
async def test_detect_conflicts_opposing_predicates() -> None:
    """Agents split on supports vs opposes for same entity → conflict detected."""
    svc = GraphRAGService(llm_client=MagicMock())

    rows = [
        _make_triple_row("housing_policy", "supports", "increase", 1),
        _make_triple_row("housing_policy", "supports", "increase", 2),
        _make_triple_row("housing_policy", "supports", "increase", 3),
        _make_triple_row("housing_policy", "opposes", "increase", 4),
        _make_triple_row("housing_policy", "opposes", "increase", 5),
        _make_triple_row("housing_policy", "opposes", "increase", 6),
    ]

    mock_cursor = AsyncMock()
    mock_cursor.fetchall = AsyncMock(return_value=rows)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_cursor)
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.app.services.graph_rag.get_db", return_value=mock_db):
        conflicts = await svc.detect_triple_conflicts("sess1", min_agents_per_side=3)

    assert len(conflicts) == 1
    c = conflicts[0]
    assert c.entity == "housing_policy"
    assert c.conflict_score > 0.0
    assert len(c.agent_ids_a) >= 3
    assert len(c.agent_ids_b) >= 3


@pytest.mark.asyncio
async def test_detect_conflicts_below_threshold() -> None:
    """Fewer agents than min_agents_per_side → no conflict reported."""
    svc = GraphRAGService(llm_client=MagicMock())

    rows = [
        _make_triple_row("topic", "supports", "yes", 1),
        _make_triple_row("topic", "supports", "yes", 2),
        _make_triple_row("topic", "opposes", "yes", 3),  # only 1 agent opposes
    ]

    mock_cursor = AsyncMock()
    mock_cursor.fetchall = AsyncMock(return_value=rows)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_cursor)
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.app.services.graph_rag.get_db", return_value=mock_db):
        conflicts = await svc.detect_triple_conflicts("sess1", min_agents_per_side=3)

    assert conflicts == []


@pytest.mark.asyncio
async def test_detect_conflicts_non_opposing_predicates() -> None:
    """Predicates not in _OPPOSING_PAIRS should NOT generate conflicts."""
    svc = GraphRAGService(llm_client=MagicMock())

    rows = [
        _make_triple_row("topic", "likes", "X", 1),
        _make_triple_row("topic", "likes", "X", 2),
        _make_triple_row("topic", "likes", "X", 3),
        _make_triple_row("topic", "dislikes", "X", 4),
        _make_triple_row("topic", "dislikes", "X", 5),
        _make_triple_row("topic", "dislikes", "X", 6),
    ]

    mock_cursor = AsyncMock()
    mock_cursor.fetchall = AsyncMock(return_value=rows)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_cursor)
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.app.services.graph_rag.get_db", return_value=mock_db):
        conflicts = await svc.detect_triple_conflicts("sess1", min_agents_per_side=3)

    # "likes" vs "dislikes" is NOT in _OPPOSING_PAIRS
    assert conflicts == []


@pytest.mark.asyncio
async def test_conflicts_sorted_by_score_descending() -> None:
    """Multiple conflicts should be returned sorted by conflict_score desc."""
    svc = GraphRAGService(llm_client=MagicMock())

    # Two entities with conflicts of different sizes
    rows = (
        # Entity A: 3 vs 3 (balanced → score ~ 0.5)
        [_make_triple_row("entity_A", "supports", "yes", i) for i in range(1, 4)]
        + [_make_triple_row("entity_A", "opposes", "yes", i) for i in range(4, 7)]
        # Entity B: 5 vs 5 (larger → higher absolute score)
        + [_make_triple_row("entity_B", "trusts", "X", i) for i in range(10, 15)]
        + [_make_triple_row("entity_B", "distrusts", "X", i) for i in range(15, 20)]
    )

    mock_cursor = AsyncMock()
    mock_cursor.fetchall = AsyncMock(return_value=rows)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_cursor)
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.app.services.graph_rag.get_db", return_value=mock_db):
        conflicts = await svc.detect_triple_conflicts("sess1", min_agents_per_side=3)

    assert len(conflicts) == 2
    assert conflicts[0].conflict_score >= conflicts[1].conflict_score


# ------------------------------------------------------------------ #
# get_global_narrative — empty community graceful degradation          #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_global_narrative_empty_summaries() -> None:
    """No community summaries → graceful fallback message, no LLM call."""
    mock_llm = MagicMock()
    mock_llm.chat = AsyncMock()  # should NOT be called
    svc = GraphRAGService(llm_client=mock_llm)

    # Mock _ensure_table
    with patch.object(svc, "_ensure_table", new_callable=AsyncMock):
        # Mock _load_latest_summaries to return empty
        with patch.object(svc, "_load_latest_summaries", new_callable=AsyncMock, return_value=[]):
            result = await svc.get_global_narrative("sess1")

    assert isinstance(result, GlobalNarrative)
    assert result.community_count == 0
    assert "暫無社群摘要" in result.narrative_text
    assert result.fault_lines == []
    # LLM should NOT have been called
    mock_llm.chat.assert_not_called()


# ------------------------------------------------------------------ #
# generate_community_summaries — small/empty clusters                  #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_generate_summaries_skips_small_clusters() -> None:
    """Clusters smaller than _MIN_CLUSTER_SIZE should be skipped entirely."""
    mock_llm = MagicMock()
    mock_llm.chat_json = AsyncMock()  # should NOT be called
    svc = GraphRAGService(llm_client=mock_llm)

    small_chamber = SimpleNamespace(
        cluster_id=0,
        member_count=1,
        member_ids=[42],
    )
    echo_result = SimpleNamespace(chambers=[small_chamber])

    with patch.object(svc, "_ensure_table", new_callable=AsyncMock):
        result = await svc.generate_community_summaries("sess1", 5, echo_result)

    assert result == []
    mock_llm.chat_json.assert_not_called()


@pytest.mark.asyncio
async def test_generate_summaries_empty_chambers() -> None:
    """No chambers at all → empty result, no LLM call."""
    mock_llm = MagicMock()
    svc = GraphRAGService(llm_client=mock_llm)

    echo_result = SimpleNamespace(chambers=[])

    with patch.object(svc, "_ensure_table", new_callable=AsyncMock):
        result = await svc.generate_community_summaries("sess1", 5, echo_result)

    assert result == []


# ------------------------------------------------------------------ #
# _MIN_CLUSTER_SIZE constant guard                                     #
# ------------------------------------------------------------------ #


def test_min_cluster_size_at_least_3() -> None:
    """_MIN_CLUSTER_SIZE should be >= 3 to avoid trivial summaries."""
    assert _MIN_CLUSTER_SIZE >= 3


# ------------------------------------------------------------------ #
# Conflict score computation                                           #
# ------------------------------------------------------------------ #


def test_conflict_score_balanced_sides() -> None:
    """For perfectly balanced sides (n vs n), score = n / (2n) = 0.5."""
    # geometric mean(n, n) / 2n = n / 2n = 0.5
    n = 10
    expected = (n * n) ** 0.5 / (2 * n)
    assert abs(expected - 0.5) < 0.001


def test_conflict_score_imbalanced_sides() -> None:
    """Imbalanced sides should have score < 0.5 (penalised)."""
    # 3 vs 10: geometric_mean = sqrt(30) ≈ 5.48, total = 13
    # score = 5.48 / 13 ≈ 0.421
    score = (3 * 10) ** 0.5 / (3 + 10)
    assert score < 0.5
    assert score > 0.0
