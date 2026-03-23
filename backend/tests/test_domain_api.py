"""Tests for domain pack API endpoints (Task 10).

Covers:
- GET /api/domain-packs       -- list builtin packs
- GET /api/domain-packs/{id}  -- get a specific builtin pack
- POST /api/domain-packs/generate -- LLM-based generation (mocked)
- POST /api/domain-packs/save     -- persist custom pack to DB
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

VALID_PACK_PAYLOAD = {
    "id": "test_custom_pack",
    "name": "Test Custom Pack",
    "description": "A test custom domain pack",
    "regions": ["Region A", "Region B", "Region C"],
    "occupations": ["Engineer", "Teacher", "Doctor", "Lawyer", "Chef"],
    "income_brackets": ["low", "middle", "high"],
    "shocks": ["shock1", "shock2", "shock3", "shock4"],
    "metrics": ["metric1", "metric2", "metric3"],
    "persona_template": "You are a {occupation} in {region}.",
    "sentiment_keywords": ["good"] * 20,
    "locale": "en-US",
    "source": "user_edited",
}

MOCK_LLM_PACK = {
    "id": "jp_real_estate",
    "name": "Japan Real Estate",
    "regions": ["Shinjuku", "Shibuya", "Minato"],
    "occupations": ["Engineer", "Finance", "Service", "Education", "Healthcare"],
    "income_brackets": ["low", "middle", "high"],
    "shocks": ["BOJ rate hike", "Earthquake", "Population decline", "Foreign investment surge"],
    "metrics": ["land_price_index", "vacancy_rate", "transaction_volume"],
    "persona_template": "You are a {occupation} living in {region}, Tokyo.",
    "sentiment_keywords": [
        "good",
        "bad",
        "expensive",
        "cheap",
        "rising",
        "falling",
        "bullish",
        "bearish",
        "stable",
        "volatile",
        "demand",
        "supply",
        "mortgage",
        "rent",
        "buy",
        "sell",
        "invest",
        "wait",
        "opportunity",
        "risk",
    ],
    "locale": "ja-JP",
}


def _make_mock_llm_client(response: dict) -> MagicMock:
    mock = MagicMock()
    mock.chat_json = AsyncMock(return_value=response)
    return mock


def _unwrap(resp_json: dict) -> dict | list:
    """Unwrap APIResponse envelope, returning the data payload."""
    assert resp_json["success"] is True
    return resp_json["data"]


# ---------------------------------------------------------------------------
# GET /api/domain-packs -- list packs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_domain_packs_returns_builtin(test_client):
    """The list endpoint must return at least the 7 builtin packs."""
    resp = await test_client.get("/api/domain-packs")
    assert resp.status_code == 200
    data = _unwrap(resp.json())
    assert "packs" in data
    assert len(data["packs"]) >= 7


@pytest.mark.asyncio
async def test_list_domain_packs_structure(test_client):
    """Each pack in the list must have the required keys."""
    resp = await test_client.get("/api/domain-packs")
    assert resp.status_code == 200
    packs = _unwrap(resp.json())["packs"]
    for pack in packs:
        assert "id" in pack
        assert "locale" in pack
        assert "shock_count" in pack
        assert "metric_count" in pack


@pytest.mark.asyncio
async def test_list_domain_packs_includes_hk_city(test_client):
    resp = await test_client.get("/api/domain-packs")
    ids = {p["id"] for p in _unwrap(resp.json())["packs"]}
    assert "hk_city" in ids


@pytest.mark.asyncio
async def test_list_domain_packs_includes_us_markets(test_client):
    resp = await test_client.get("/api/domain-packs")
    ids = {p["id"] for p in _unwrap(resp.json())["packs"]}
    assert "us_markets" in ids


# ---------------------------------------------------------------------------
# GET /api/domain-packs/{pack_id} -- get specific builtin pack
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_hk_city_pack(test_client):
    resp = await test_client.get("/api/domain-packs/hk_city")
    assert resp.status_code == 200
    data = _unwrap(resp.json())
    assert data["id"] == "hk_city"
    assert "shock_types" in data
    assert "metrics" in data
    assert len(data["shock_types"]) > 0


@pytest.mark.asyncio
async def test_get_builtin_pack_has_macro_fields(test_client):
    resp = await test_client.get("/api/domain-packs/hk_city")
    assert resp.status_code == 200
    assert "macro_fields" in _unwrap(resp.json())


@pytest.mark.asyncio
async def test_get_nonexistent_pack_returns_404(test_client):
    resp = await test_client.get("/api/domain-packs/nonexistent_pack_xyz")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_us_markets_pack(test_client):
    resp = await test_client.get("/api/domain-packs/us_markets")
    assert resp.status_code == 200
    assert _unwrap(resp.json())["id"] == "us_markets"


# ---------------------------------------------------------------------------
# POST /api/domain-packs/generate -- LLM generation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_domain_pack_success(test_client):
    """POST /generate with a valid description returns a DraftDomainPack."""
    with patch("backend.app.api.domain_packs.LLMClient") as MockLLM:
        instance = MockLLM.return_value
        instance.chat_json = AsyncMock(return_value=MOCK_LLM_PACK)

        resp = await test_client.post(
            "/api/domain-packs/generate",
            json={"description": "Japan real estate market in Tokyo"},
        )

    assert resp.status_code == 200
    data = _unwrap(resp.json())
    assert "pack" in data
    pack = data["pack"]
    assert pack["name"] == "Japan Real Estate"
    assert pack["source"] == "generated"
    assert len(pack["regions"]) >= 3
    assert len(pack["shocks"]) >= 4
    assert len(pack["sentiment_keywords"]) >= 20


@pytest.mark.asyncio
async def test_generate_returns_pack_fields(test_client):
    with patch("backend.app.api.domain_packs.LLMClient") as MockLLM:
        instance = MockLLM.return_value
        instance.chat_json = AsyncMock(return_value=MOCK_LLM_PACK)

        resp = await test_client.post(
            "/api/domain-packs/generate",
            json={"description": "test domain"},
        )

    pack = _unwrap(resp.json())["pack"]
    for field in (
        "id",
        "name",
        "regions",
        "occupations",
        "shocks",
        "metrics",
        "persona_template",
        "sentiment_keywords",
        "locale",
        "source",
    ):
        assert field in pack, f"Missing field: {field}"


@pytest.mark.asyncio
async def test_generate_empty_description_returns_422(test_client):
    resp = await test_client.post(
        "/api/domain-packs/generate",
        json={"description": "   "},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_generate_llm_failure_returns_422(test_client):
    """When LLM produces invalid output twice, endpoint returns 422."""
    with patch("backend.app.api.domain_packs.LLMClient") as MockLLM:
        instance = MockLLM.return_value
        # Both attempts return empty dict -- triggers ValueError in DomainGenerator
        instance.chat_json = AsyncMock(return_value={})

        resp = await test_client.post(
            "/api/domain-packs/generate",
            json={"description": "impossible domain"},
        )

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/domain-packs/save -- persist custom pack
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_custom_pack_success(test_client):
    resp = await test_client.post("/api/domain-packs/save", json=VALID_PACK_PAYLOAD)
    assert resp.status_code == 200
    data = _unwrap(resp.json())
    assert data["saved"] is True
    assert data["id"] == "test_custom_pack"


@pytest.mark.asyncio
async def test_save_pack_then_list_includes_it(test_client):
    await test_client.post("/api/domain-packs/save", json=VALID_PACK_PAYLOAD)
    resp = await test_client.get("/api/domain-packs")
    ids = {p["id"] for p in _unwrap(resp.json())["packs"]}
    assert "test_custom_pack" in ids


@pytest.mark.asyncio
async def test_save_pack_then_get_by_id(test_client):
    await test_client.post("/api/domain-packs/save", json=VALID_PACK_PAYLOAD)
    resp = await test_client.get("/api/domain-packs/test_custom_pack")
    assert resp.status_code == 200
    data = _unwrap(resp.json())
    assert data["id"] == "test_custom_pack"
    assert data["name"] == "Test Custom Pack"
    assert data["locale"] == "en-US"


@pytest.mark.asyncio
async def test_save_pack_upsert(test_client):
    """Saving a pack with the same id twice should update (not fail)."""
    await test_client.post("/api/domain-packs/save", json=VALID_PACK_PAYLOAD)

    updated = {**VALID_PACK_PAYLOAD, "name": "Updated Pack Name"}
    resp = await test_client.post("/api/domain-packs/save", json=updated)
    assert resp.status_code == 200

    resp2 = await test_client.get("/api/domain-packs/test_custom_pack")
    assert _unwrap(resp2.json())["name"] == "Updated Pack Name"


@pytest.mark.asyncio
async def test_save_pack_invalid_too_few_regions(test_client):
    bad = {**VALID_PACK_PAYLOAD, "regions": ["only_one"]}
    resp = await test_client.post("/api/domain-packs/save", json=bad)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_save_pack_invalid_too_few_shocks(test_client):
    bad = {**VALID_PACK_PAYLOAD, "shocks": ["s1", "s2"]}
    resp = await test_client.post("/api/domain-packs/save", json=bad)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_save_pack_invalid_too_few_sentiment_keywords(test_client):
    bad = {**VALID_PACK_PAYLOAD, "sentiment_keywords": ["good"] * 5}
    resp = await test_client.post("/api/domain-packs/save", json=bad)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_save_pack_with_zh_hk_locale(test_client):
    pack = {**VALID_PACK_PAYLOAD, "id": "zh_custom", "locale": "zh-HK"}
    resp = await test_client.post("/api/domain-packs/save", json=pack)
    assert resp.status_code == 200

    resp2 = await test_client.get("/api/domain-packs/zh_custom")
    assert _unwrap(resp2.json())["locale"] == "zh-HK"


@pytest.mark.asyncio
async def test_save_pack_preserves_shocks(test_client):
    resp = await test_client.post("/api/domain-packs/save", json=VALID_PACK_PAYLOAD)
    assert resp.status_code == 200

    resp2 = await test_client.get("/api/domain-packs/test_custom_pack")
    shocks = _unwrap(resp2.json())["shocks"]
    assert shocks == ["shock1", "shock2", "shock3", "shock4"]


@pytest.mark.asyncio
async def test_save_pack_preserves_metrics(test_client):
    resp = await test_client.post("/api/domain-packs/save", json=VALID_PACK_PAYLOAD)
    assert resp.status_code == 200

    resp2 = await test_client.get("/api/domain-packs/test_custom_pack")
    metrics = _unwrap(resp2.json())["metrics"]
    assert metrics == ["metric1", "metric2", "metric3"]


# ---------------------------------------------------------------------------
# Integration: generate -> save -> list workflow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_save_list_workflow(test_client):
    """Full workflow: generate a pack then immediately save it."""
    with patch("backend.app.api.domain_packs.LLMClient") as MockLLM:
        instance = MockLLM.return_value
        instance.chat_json = AsyncMock(return_value=MOCK_LLM_PACK)

        gen_resp = await test_client.post(
            "/api/domain-packs/generate",
            json={"description": "Japan real estate"},
        )
    assert gen_resp.status_code == 200
    generated_pack = _unwrap(gen_resp.json())["pack"]

    # Save the generated pack
    save_payload = {
        "id": generated_pack["id"],
        "name": generated_pack["name"],
        "description": generated_pack.get("description", ""),
        "regions": generated_pack["regions"],
        "occupations": generated_pack["occupations"],
        "income_brackets": generated_pack["income_brackets"],
        "shocks": generated_pack["shocks"],
        "metrics": generated_pack["metrics"],
        "persona_template": generated_pack["persona_template"],
        "sentiment_keywords": generated_pack["sentiment_keywords"],
        "locale": generated_pack["locale"],
        "source": "generated",
    }
    save_resp = await test_client.post("/api/domain-packs/save", json=save_payload)
    assert save_resp.status_code == 200
    assert _unwrap(save_resp.json())["saved"] is True

    # Verify it appears in the list
    list_resp = await test_client.get("/api/domain-packs")
    ids = {p["id"] for p in _unwrap(list_resp.json())["packs"]}
    assert generated_pack["id"] in ids
