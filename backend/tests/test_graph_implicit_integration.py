# backend/tests/test_graph_implicit_integration.py
"""Test that build_graph endpoint invokes ImplicitStakeholderService."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_build_graph_calls_implicit_discovery(test_client):
    """build_graph must call ImplicitStakeholderService.discover when seed_text given."""
    from backend.app.services.implicit_stakeholder_service import DiscoveryResult

    mock_result = DiscoveryResult(stakeholders=(), nodes_added=3)

    with patch("backend.app.api.graph.ImplicitStakeholderService") as MockSvc:
        instance = MockSvc.return_value
        instance.discover = AsyncMock(return_value=mock_result)

        resp = await test_client.post(
            "/api/graph/build",
            json={
                "scenario_type": "macro",
                "seed_text": "US-Iran war began Feb 28 2026",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["meta"]["implicit_nodes"] == 3
    instance.discover.assert_called_once()
