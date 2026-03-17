"""Tests for POST /multi-run and GET /world-events endpoints."""
import pytest
from unittest.mock import AsyncMock, patch
from httpx import ASGITransport, AsyncClient
from backend.app import create_app


@pytest.mark.unit
class TestMultiRunPost:
    async def test_returns_202_when_session_exists(self):
        """POST /multi-run returns 202 Accepted and starts background task."""
        fake_session = {"id": "sess-001", "status": "COMPLETED", "sim_mode": "kg_driven"}
        with patch("backend.app.api.simulation.get_db") as mock_db:
            mock_cursor = AsyncMock()
            mock_cursor.fetchone.return_value = fake_session
            mock_db.return_value.__aenter__.return_value.execute = AsyncMock(return_value=mock_cursor)
            with patch("backend.app.api.simulation.asyncio.create_task"):
                app = create_app()
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                    r = await client.post("/api/simulation/sess-001/multi-run")
        assert r.status_code == 202
        assert r.json()["data"]["status"] == "queued"

    async def test_returns_404_when_session_missing(self):
        """POST /multi-run returns 404 when session not found."""
        with patch("backend.app.api.simulation.get_db") as mock_db:
            mock_cursor = AsyncMock()
            mock_cursor.fetchone.return_value = None
            mock_db.return_value.__aenter__.return_value.execute = AsyncMock(return_value=mock_cursor)
            app = create_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post("/api/simulation/no-such/multi-run")
        assert r.status_code == 404


@pytest.mark.unit
class TestWorldEventsGet:
    async def test_returns_events_list(self):
        """GET /world-events returns list of world events."""
        fake_rows = [
            {"id": "e1", "simulation_id": "sess-001", "round_number": 3,
             "content": "Oil price spike", "event_type": "shock",
             "reach_json": "[]", "impact_vector_json": "{}", "credibility": 0.9,
             "created_at": "2026-03-17T00:00:00"}
        ]
        with patch("backend.app.api.simulation.get_db") as mock_db:
            mock_cursor = AsyncMock()
            mock_cursor.fetchall.return_value = fake_rows
            mock_db.return_value.__aenter__.return_value.execute = AsyncMock(return_value=mock_cursor)
            app = create_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.get("/api/simulation/sess-001/world-events")
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data["events"]) == 1
        assert data["events"][0]["content"] == "Oil price spike"
