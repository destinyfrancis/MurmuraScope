"""Unit tests for LLMClient retry/backoff logic in _chat_openai_compat."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.app.utils.llm_client import LLMClient


# ---------------------------------------------------------------------------
# Helper: build a mock httpx.Response
# ---------------------------------------------------------------------------


def _make_error_response(status_code: int) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        f"{status_code}",
        request=MagicMock(),
        response=resp,
    )
    return resp


def _make_ok_response() -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.raise_for_status = MagicMock()  # no-op
    resp.json.return_value = {
        "choices": [{"message": {"content": "ok"}}],
        "model": "test-model",
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    return resp


# ---------------------------------------------------------------------------
# Shared cfg fixture (matches _chat_openai_compat expectations)
# ---------------------------------------------------------------------------

_CFG = {
    "base_url": "https://example.com/v1",
    "api_key": "test-key",
    "cost_per_1k_input": 0.0,
    "cost_per_1k_output": 0.0,
}

_MESSAGES = [{"role": "user", "content": "test"}]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_chat_retries_on_429_and_succeeds():
    """_chat_openai_compat must retry on 429 and return result when third attempt succeeds."""
    client = LLMClient()
    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return _make_error_response(429)
        return _make_ok_response()

    http_mock = MagicMock()
    http_mock.post = mock_post

    with patch.object(client, "_get_http_client", return_value=http_mock):
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await client._chat_openai_compat(
                messages=_MESSAGES,
                model="test-model",
                temperature=0.7,
                max_tokens=100,
                cfg=_CFG,
            )

    assert call_count == 3, f"Expected 3 attempts (2 retries), got {call_count}"
    assert result.content == "ok"
    assert mock_sleep.call_count == 2, "Should sleep between each retry"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_chat_retries_on_503():
    """_chat_openai_compat must retry on 503 (server error) and eventually succeed."""
    client = LLMClient()
    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _make_error_response(503)
        return _make_ok_response()

    http_mock = MagicMock()
    http_mock.post = mock_post

    with patch.object(client, "_get_http_client", return_value=http_mock):
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await client._chat_openai_compat(
                messages=_MESSAGES,
                model="test-model",
                temperature=0.7,
                max_tokens=100,
                cfg=_CFG,
            )

    assert call_count == 2
    assert result.content == "ok"
    assert mock_sleep.call_count == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_chat_raises_after_max_retries():
    """_chat_openai_compat must raise HTTPStatusError after exhausting all retries."""
    client = LLMClient()
    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return _make_error_response(429)

    http_mock = MagicMock()
    http_mock.post = mock_post

    with patch.object(client, "_get_http_client", return_value=http_mock):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(httpx.HTTPStatusError):
                await client._chat_openai_compat(
                    messages=_MESSAGES,
                    model="test-model",
                    temperature=0.7,
                    max_tokens=100,
                    cfg=_CFG,
                )

    # _MAX_RETRIES = 3 → 3 total attempts
    assert call_count == 3, f"Expected exactly 3 attempts, got {call_count}"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_chat_no_retry_on_404():
    """_chat_openai_compat must NOT retry on non-retryable status codes like 404."""
    client = LLMClient()
    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return _make_error_response(404)

    http_mock = MagicMock()
    http_mock.post = mock_post

    with patch.object(client, "_get_http_client", return_value=http_mock):
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(httpx.HTTPStatusError):
                await client._chat_openai_compat(
                    messages=_MESSAGES,
                    model="test-model",
                    temperature=0.7,
                    max_tokens=100,
                    cfg=_CFG,
                )

    assert call_count == 1, "Should not retry on 404"
    assert not mock_sleep.called, "Should not sleep for non-retryable errors"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_chat_retries_on_connect_error():
    """_chat_openai_compat must retry on httpx.ConnectError."""
    client = LLMClient()
    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise httpx.ConnectError("connection refused")
        return _make_ok_response()

    http_mock = MagicMock()
    http_mock.post = mock_post

    with patch.object(client, "_get_http_client", return_value=http_mock):
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await client._chat_openai_compat(
                messages=_MESSAGES,
                model="test-model",
                temperature=0.7,
                max_tokens=100,
                cfg=_CFG,
            )

    assert call_count == 2
    assert result.content == "ok"
    assert mock_sleep.call_count == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_chat_exponential_backoff_delays():
    """Sleep durations must follow exponential backoff: 1s, 2s for attempts 0, 1."""
    client = LLMClient()
    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return _make_error_response(429)
        return _make_ok_response()

    http_mock = MagicMock()
    http_mock.post = mock_post

    with patch.object(client, "_get_http_client", return_value=http_mock):
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await client._chat_openai_compat(
                messages=_MESSAGES,
                model="test-model",
                temperature=0.7,
                max_tokens=100,
                cfg=_CFG,
            )

    sleep_calls = [call.args[0] for call in mock_sleep.call_args_list]
    assert len(sleep_calls) == 2
    assert sleep_calls[0] == pytest.approx(1.0), f"First backoff should be 1.0s, got {sleep_calls[0]}"
    assert sleep_calls[1] == pytest.approx(2.0), f"Second backoff should be 2.0s, got {sleep_calls[1]}"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_chat_succeeds_first_attempt_no_sleep():
    """When first attempt succeeds, asyncio.sleep must not be called."""
    client = LLMClient()

    async def mock_post(*args, **kwargs):
        return _make_ok_response()

    http_mock = MagicMock()
    http_mock.post = mock_post

    with patch.object(client, "_get_http_client", return_value=http_mock):
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await client._chat_openai_compat(
                messages=_MESSAGES,
                model="test-model",
                temperature=0.7,
                max_tokens=100,
                cfg=_CFG,
            )

    assert result.content == "ok"
    assert not mock_sleep.called, "Should not sleep when first attempt succeeds"
