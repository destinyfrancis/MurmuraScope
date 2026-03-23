"""Tests for LLM call latency + token logging in llm_client.py."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.utils.llm_client import LLMClient


def test_openai_compat_logs_latency_and_tokens(caplog):
    """_chat_openai_compat should log latency + tokens at INFO level."""
    fake_resp = MagicMock()
    fake_resp.json.return_value = {
        "choices": [{"message": {"content": "hello"}}],
        "model": "deepseek-v3",
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }
    fake_resp.raise_for_status = MagicMock()

    async def run():
        client = LLMClient()
        with patch.object(client, "_get_http_client") as mock_http:
            mock_http.return_value.post = AsyncMock(return_value=fake_resp)
            with caplog.at_level(logging.INFO, logger="murmuroscope.llm_client"):
                result = await client._chat_openai_compat(
                    [{"role": "user", "content": "hi"}],
                    model="deepseek-v3",
                    temperature=0.7,
                    max_tokens=100,
                    cfg={
                        "base_url": "https://x",
                        "api_key": "k",
                        "cost_per_1k_input": 0.0,
                        "cost_per_1k_output": 0.0,
                    },
                )
        return result

    result = asyncio.get_event_loop().run_until_complete(run())
    assert result.content == "hello"
    assert any("tokens" in r.message.lower() or "latency" in r.message.lower() for r in caplog.records), (
        "Expected latency/token log message"
    )
