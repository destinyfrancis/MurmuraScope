# backend/tests/test_relationship_validator.py
"""Tests for RelationshipValidator — Dunbar + small-world network checks."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.app.services.relationship_validator import (
    RelationshipValidationResult,
    RelationshipValidator,
    _sampled_avg_path_length,
)


def _make_edges(n_agents: int = 20, clique_size: int = 5) -> list[tuple[str, str, int]]:
    """Build a clustered test graph: small cliques connected by bridges."""
    edges = []
    # Within each clique: all-to-all connections (high clustering)
    for clique_start in range(0, n_agents, clique_size):
        clique = list(range(clique_start, min(clique_start + clique_size, n_agents)))
        for i, a in enumerate(clique):
            for b in clique[i + 1 :]:
                edges.append((f"agent_{a}", f"agent_{b}", 5))  # meaningful edges
    # Bridge between cliques (low interaction = not meaningful)
    for clique_start in range(0, n_agents - clique_size, clique_size):
        a = clique_start
        b = clique_start + clique_size
        edges.append((f"agent_{a}", f"agent_{b}", 1))  # NOT meaningful (count < 3)
    return edges


def _patch_db(edges: list[tuple[str, str, int]]):
    """Return a context manager that patches get_db to return given edges."""
    rows = [(a, b, c) for a, b, c in edges]

    def fake_get_db():
        db = AsyncMock()
        db.__aenter__ = AsyncMock(return_value=db)
        db.__aexit__ = AsyncMock(return_value=False)
        cursor = AsyncMock()
        cursor.fetchall = AsyncMock(return_value=rows)
        db.execute = AsyncMock(return_value=cursor)
        return db

    return patch("backend.app.services.relationship_validator.get_db", fake_get_db)


@pytest.mark.asyncio
async def test_validate_returns_result():
    """validate() should return a RelationshipValidationResult."""
    validator = RelationshipValidator()
    edges = _make_edges()
    with _patch_db(edges):
        result = await validator.validate("session_abc")
    assert isinstance(result, RelationshipValidationResult)
    assert result.session_id == "session_abc"


@pytest.mark.asyncio
async def test_dunbar_ok_when_avg_meaningful_degree_low():
    """Small clique graph with high clustering but low avg degree → no violation."""
    validator = RelationshipValidator()
    # 20 agents in 4 cliques of 5 → avg meaningful degree = 4 (within clique)
    edges = _make_edges(n_agents=20, clique_size=5)
    with _patch_db(edges):
        result = await validator.validate("session_dunbar")
    assert result.dunbar_violation is False
    assert result.avg_meaningful_degree <= 15.0


@pytest.mark.asyncio
async def test_dunbar_violation_when_avg_degree_exceeds_limit():
    """Star graph where every agent connects to all others → avg degree = n-1 > 15."""
    validator = RelationshipValidator()
    # Complete graph of 20 agents — avg meaningful degree = 19
    edges = [(f"agent_{i}", f"agent_{j}", 10) for i in range(20) for j in range(i + 1, 20)]
    with _patch_db(edges):
        result = await validator.validate("session_star", dunbar_limit=15.0)
    assert result.dunbar_violation is True
    assert result.avg_meaningful_degree > 15.0


@pytest.mark.asyncio
async def test_clustering_coefficient_positive():
    """Clustered graph should have positive clustering coefficient."""
    validator = RelationshipValidator()
    edges = _make_edges(n_agents=20, clique_size=5)
    with _patch_db(edges):
        result = await validator.validate("session_cc")
    assert result.clustering_coefficient > 0.0


@pytest.mark.asyncio
async def test_empty_graph_returns_graceful_result():
    """Empty edge list → n_agents=0, no crash."""
    validator = RelationshipValidator()
    with _patch_db([]):
        result = await validator.validate("session_empty")
    assert result.n_agents == 0
    assert result.n_edges == 0
    assert result.dunbar_violation is False


@pytest.mark.asyncio
async def test_summary_string_populated():
    """summary field should be a non-empty string."""
    validator = RelationshipValidator()
    edges = _make_edges()
    with _patch_db(edges):
        result = await validator.validate("session_summary")
    assert isinstance(result.summary, str)
    assert len(result.summary) > 0


def test_sampled_avg_path_length_small_graph():
    """_sampled_avg_path_length on a small complete graph should return > 0."""
    import networkx as nx

    G = nx.complete_graph(5)
    apl = _sampled_avg_path_length(G)
    assert apl == pytest.approx(1.0)  # all nodes directly connected
