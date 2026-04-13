"""Unit tests for GET /presets API endpoint (Phase 4.2).

Covers:
- Endpoint returns 200 with list of presets
- Response structure: {success, data: {presets, total}}
- Each preset has required keys: id, name, description, scenario_type
- total matches len(presets)
- Endpoint is public (no auth required)
"""

from __future__ import annotations

import pytest
import pytest_asyncio


class TestPresetsEndpoint:
    @pytest.mark.asyncio
    async def test_presets_returns_200(self, test_client):
        response = await test_client.get("/api/simulation/presets")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_presets_success_true(self, test_client):
        response = await test_client.get("/api/simulation/presets")
        body = response.json()
        assert body["success"] is True

    @pytest.mark.asyncio
    async def test_presets_data_has_presets_key(self, test_client):
        response = await test_client.get("/api/simulation/presets")
        data = response.json()["data"]
        assert "presets" in data

    @pytest.mark.asyncio
    async def test_presets_data_has_total_key(self, test_client):
        response = await test_client.get("/api/simulation/presets")
        data = response.json()["data"]
        assert "total" in data

    @pytest.mark.asyncio
    async def test_presets_total_matches_list_length(self, test_client):
        response = await test_client.get("/api/simulation/presets")
        data = response.json()["data"]
        assert data["total"] == len(data["presets"])

    @pytest.mark.asyncio
    async def test_presets_is_list(self, test_client):
        response = await test_client.get("/api/simulation/presets")
        data = response.json()["data"]
        assert isinstance(data["presets"], list)

    @pytest.mark.asyncio
    async def test_presets_has_expected_count(self, test_client):
        """3 preset JSON files were shipped with Phase 4.1."""
        response = await test_client.get("/api/simulation/presets")
        data = response.json()["data"]
        assert data["total"] >= 3, \
            f"Expected ≥3 presets, got {data['total']}"

    @pytest.mark.asyncio
    async def test_each_preset_has_required_fields(self, test_client):
        required = {"id", "name", "description", "scenario_type"}
        response = await test_client.get("/api/simulation/presets")
        presets = response.json()["data"]["presets"]
        for preset in presets:
            missing = required - set(preset.keys())
            assert not missing, f"Preset {preset.get('id')} missing fields: {missing}"

    @pytest.mark.asyncio
    async def test_preset_ids_are_unique(self, test_client):
        # Using a fresh call to ensure isolation or consistent state
        response = await test_client.get("/api/simulation/presets")
        presets = response.json()["data"]["presets"]
        ids = [p["id"] for p in presets]
        assert len(ids) == len(set(ids)), "Duplicate preset IDs found"

    @pytest.mark.asyncio
    async def test_no_auth_required(self, test_client):
        """Presets endpoint should be publicly accessible without auth headers."""
        response = await test_client.get(
            "/api/simulation/presets",
            headers={},  # No Authorization header
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_known_preset_hk_housing_present(self, test_client):
        response = await test_client.get("/api/simulation/presets")
        ids = [p["id"] for p in response.json()["data"]["presets"]]
        assert "hong_kong_housing_crisis" in ids

    @pytest.mark.asyncio
    async def test_known_preset_us_election_present(self, test_client):
        response = await test_client.get("/api/simulation/presets")
        ids = [p["id"] for p in response.json()["data"]["presets"]]
        assert "us_election_misinformation" in ids

    @pytest.mark.asyncio
    async def test_known_preset_supply_chain_present(self, test_client):
        response = await test_client.get("/api/simulation/presets")
        ids = [p["id"] for p in response.json()["data"]["presets"]]
        assert "supply_chain_shock" in ids
