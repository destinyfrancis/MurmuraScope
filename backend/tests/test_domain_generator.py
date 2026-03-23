"""Tests for DomainGenerator service (Task 9)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app.models.domain import DraftDomainPack
from backend.app.services.domain_generator import DomainGenerator

# ---------------------------------------------------------------------------
# Fixtures / shared constants
# ---------------------------------------------------------------------------

MOCK_LLM_RESPONSE = {
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

INCOMPLETE_LLM_RESPONSE: dict = {}  # Missing "regions" key — triggers retry


def _make_llm(responses: list[dict]) -> MagicMock:
    """Build a mock LLM client that returns responses in sequence."""
    mock = MagicMock()
    mock.chat_json = AsyncMock(side_effect=responses)
    return mock


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_domain_pack_success():
    llm = _make_llm([MOCK_LLM_RESPONSE])
    gen = DomainGenerator(llm_client=llm)

    result = await gen.generate("日本東京房地產市場")

    assert isinstance(result, DraftDomainPack)
    assert result.name == "Japan Real Estate"
    assert result.id == "jp_real_estate"
    assert result.source == "generated"
    assert result.locale == "ja-JP"


@pytest.mark.asyncio
async def test_generate_sets_source_generated():
    """source='generated' must be set even if LLM omits it."""
    response_without_source = {k: v for k, v in MOCK_LLM_RESPONSE.items() if k != "source"}
    llm = _make_llm([response_without_source])
    gen = DomainGenerator(llm_client=llm)

    result = await gen.generate("test")
    assert result.source == "generated"


@pytest.mark.asyncio
async def test_generate_regions_count():
    llm = _make_llm([MOCK_LLM_RESPONSE])
    gen = DomainGenerator(llm_client=llm)
    result = await gen.generate("test")
    assert len(result.regions) >= 3


@pytest.mark.asyncio
async def test_generate_shocks_count():
    llm = _make_llm([MOCK_LLM_RESPONSE])
    gen = DomainGenerator(llm_client=llm)
    result = await gen.generate("test")
    assert len(result.shocks) >= 4


@pytest.mark.asyncio
async def test_generate_sentiment_keywords_count():
    llm = _make_llm([MOCK_LLM_RESPONSE])
    gen = DomainGenerator(llm_client=llm)
    result = await gen.generate("test")
    assert len(result.sentiment_keywords) >= 20


@pytest.mark.asyncio
async def test_generate_result_is_frozen():
    llm = _make_llm([MOCK_LLM_RESPONSE])
    gen = DomainGenerator(llm_client=llm)
    result = await gen.generate("test")
    with pytest.raises(Exception):
        result.name = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_retries_on_bad_json():
    """Empty first response triggers retry; second response succeeds."""
    llm = _make_llm([INCOMPLETE_LLM_RESPONSE, MOCK_LLM_RESPONSE])
    gen = DomainGenerator(llm_client=llm)

    result = await gen.generate("test domain")

    assert llm.chat_json.call_count == 2
    assert isinstance(result, DraftDomainPack)


@pytest.mark.asyncio
async def test_generate_retries_on_missing_regions_key():
    """Response with no 'regions' key triggers retry."""
    bad_response = {"id": "bad", "name": "Bad Pack"}  # missing regions
    llm = _make_llm([bad_response, MOCK_LLM_RESPONSE])
    gen = DomainGenerator(llm_client=llm)

    result = await gen.generate("test domain")

    assert llm.chat_json.call_count == 2
    assert result.name == "Japan Real Estate"


@pytest.mark.asyncio
async def test_generate_raises_after_two_failures():
    """Both attempts fail → ValueError is raised."""
    llm = _make_llm([INCOMPLETE_LLM_RESPONSE, INCOMPLETE_LLM_RESPONSE])
    gen = DomainGenerator(llm_client=llm)

    with pytest.raises(ValueError, match="Failed to generate valid domain pack"):
        await gen.generate("impossible domain")

    assert llm.chat_json.call_count == 2


@pytest.mark.asyncio
async def test_generate_no_retry_needed_on_first_success():
    """When first attempt succeeds, LLM is only called once."""
    llm = _make_llm([MOCK_LLM_RESPONSE])
    gen = DomainGenerator(llm_client=llm)

    await gen.generate("test")

    assert llm.chat_json.call_count == 1


@pytest.mark.asyncio
async def test_generate_retry_uses_different_prompt():
    """Verify that the retry call uses a different user message (RETRY template)."""
    llm = _make_llm([INCOMPLETE_LLM_RESPONSE, MOCK_LLM_RESPONSE])
    gen = DomainGenerator(llm_client=llm)

    await gen.generate("my description")

    first_call_user = llm.chat_json.call_args_list[0][0][0][-1]["content"]
    second_call_user = llm.chat_json.call_args_list[1][0][0][-1]["content"]
    assert first_call_user != second_call_user


# ---------------------------------------------------------------------------
# _try_parse unit tests
# ---------------------------------------------------------------------------


def test_try_parse_valid():
    result = DomainGenerator._try_parse(MOCK_LLM_RESPONSE.copy())
    assert result is not None
    assert isinstance(result, DraftDomainPack)


def test_try_parse_empty_dict():
    assert DomainGenerator._try_parse({}) is None


def test_try_parse_missing_regions_key():
    data = {k: v for k, v in MOCK_LLM_RESPONSE.items() if k != "regions"}
    assert DomainGenerator._try_parse(data) is None


def test_try_parse_validation_failure_returns_none():
    """Too few regions triggers pydantic ValidationError → returns None."""
    data = {**MOCK_LLM_RESPONSE, "regions": ["Only One"]}
    assert DomainGenerator._try_parse(data) is None


def test_try_parse_adds_generated_source():
    data = {k: v for k, v in MOCK_LLM_RESPONSE.items() if k != "source"}
    result = DomainGenerator._try_parse(data)
    assert result is not None
    assert result.source == "generated"
