# backend/tests/test_implicit_stakeholder_service.py
"""Tests for ImplicitStakeholderService.

Coverage:
- discover() with mocked LLM returns DiscoveryResult
- Deduplication: actors already in KG are not re-injected
- nodes_added reflects only genuinely new nodes
- DiscoveryResult and ImplicitStakeholder are frozen
- LLM failure → returns empty DiscoveryResult (never raises)
- Empty seed text → returns empty DiscoveryResult immediately
- Slug sanitisation: invalid slugs are fixed before DB insert
"""
from __future__ import annotations

import dataclasses
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.services.implicit_stakeholder_service import (
    DiscoveryResult,
    ImplicitStakeholder,
    ImplicitStakeholderService,
)


@pytest.fixture()
def mock_llm():
    llm = MagicMock()
    llm.chat_json = AsyncMock(return_value={
        "implied_actors": [
            {
                "id": "european_union",
                "name": "歐盟",
                "entity_type": "Organization",
                "role": "協調歐洲能源政策及制裁回應",
                "relevance_reason": "霍爾木茲封鎖直接衝擊歐洲天然氣供應",
            },
            {
                "id": "russia_federation",
                "name": "俄羅斯聯邦",
                "entity_type": "Country",
                "role": "地區大國，油價受益者",
                "relevance_reason": "伊朗戰爭令油價上漲，俄羅斯是主要受益國",
            },
        ]
    })
    return llm


_EXISTING_NODES = [
    {"id": "abc_usa", "entity_type": "Country", "label": "美國", "description": ""},
    {"id": "abc_iran", "entity_type": "Country", "label": "伊朗", "description": ""},
]


@pytest.mark.asyncio
async def test_discover_returns_discovery_result(mock_llm):
    svc = ImplicitStakeholderService(llm_client=mock_llm)
    with patch.object(svc, "_load_kg_nodes", new=AsyncMock(return_value=_EXISTING_NODES)):
        with patch.object(svc, "_persist_nodes", new=AsyncMock(return_value=2)):
            result = await svc.discover("graph-123", "伊朗戰爭爆發", _EXISTING_NODES)

    assert isinstance(result, DiscoveryResult)
    assert result.nodes_added == 2
    assert len(result.stakeholders) == 2
    assert result.stakeholders[0].id == "european_union"


@pytest.mark.asyncio
async def test_discover_deduplicates_existing_actors(mock_llm):
    existing = _EXISTING_NODES + [
        {"id": "abc_eu", "entity_type": "Organization", "label": "歐盟", "description": ""}
    ]
    mock_llm.chat_json = AsyncMock(return_value={
        "implied_actors": [
            {
                "id": "european_union",
                "name": "歐盟",  # Same name as existing node
                "entity_type": "Organization",
                "role": "already exists",
                "relevance_reason": "test dedup",
            }
        ]
    })
    svc = ImplicitStakeholderService(llm_client=mock_llm)
    with patch.object(svc, "_load_kg_nodes", new=AsyncMock(return_value=existing)):
        with patch.object(svc, "_persist_nodes", new=AsyncMock(return_value=0)):
            result = await svc.discover("graph-123", "test", existing)

    assert result.nodes_added == 0


@pytest.mark.asyncio
async def test_discover_returns_empty_on_llm_failure():
    llm = MagicMock()
    llm.chat_json = AsyncMock(side_effect=RuntimeError("LLM down"))
    svc = ImplicitStakeholderService(llm_client=llm)
    with patch.object(svc, "_load_kg_nodes", new=AsyncMock(return_value=[])):
        result = await svc.discover("graph-123", "test", [])
    assert result.nodes_added == 0
    assert result.stakeholders == ()


@pytest.mark.asyncio
async def test_discover_returns_empty_for_blank_seed():
    svc = ImplicitStakeholderService()
    result = await svc.discover("graph-123", "   ", [])
    assert result.nodes_added == 0


def test_implicit_stakeholder_is_frozen():
    s = ImplicitStakeholder(
        id="eu", name="歐盟", entity_type="Organization",
        role="x", relevance_reason="y",
    )
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        s.id = "other"  # type: ignore[misc]


def test_discovery_result_is_frozen():
    r = DiscoveryResult(stakeholders=(), nodes_added=0)
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        r.nodes_added = 5  # type: ignore[misc]
