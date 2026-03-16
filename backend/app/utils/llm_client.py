"""Unified async LLM client wrapper for DeepSeek, Claude (Anthropic), and Qwen.

Supports OpenAI-compatible APIs via httpx and the Anthropic SDK.
All API keys are loaded from environment variables.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any

import httpx

from backend.app.utils.logger import get_logger

logger = get_logger("llm_client")

# ---------------------------------------------------------------------------
# Immutable response container
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LLMResponse:
    """Immutable container for an LLM completion result."""

    content: str
    model: str
    usage: dict[str, int]  # prompt_tokens, completion_tokens, total_tokens
    cost_usd: float


# ---------------------------------------------------------------------------
# Provider configuration (immutable dict of dicts)
# ---------------------------------------------------------------------------

_PROVIDERS: dict[str, dict[str, Any]] = {
    "fireworks": {
        "base_url": "https://api.fireworks.ai/inference/v1",
        "default_model": "accounts/fireworks/models/deepseek/deepseek-v3.2",
        "cost_per_1k_input": 0.00009,
        "cost_per_1k_output": 0.00027,
        "env_key": "FIREWORKS_API_KEY",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "cost_per_1k_input": 0.00014,
        "cost_per_1k_output": 0.00028,
        "env_key": "DEEPSEEK_API_KEY",
    },
    "anthropic": {
        "base_url": None,  # Uses anthropic SDK directly
        "default_model": "claude-sonnet-4-6",
        "cost_per_1k_input": 0.003,
        "cost_per_1k_output": 0.015,
        "env_key": "ANTHROPIC_API_KEY",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
        "cost_per_1k_input": 0.0008,
        "cost_per_1k_output": 0.002,
        "env_key": "OPENAI_API_KEY",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "deepseek/deepseek-v3.2",
        "cost_per_1k_input": 0.00027,
        "cost_per_1k_output": 0.00110,
        "env_key": "OPENROUTER_API_KEY",
    },
    # Local inference providers — no API key required
    "vllm": {
        "base_url": "http://localhost:8000/v1",
        "default_model": "deepseek/deepseek-v3.2",
        "cost_per_1k_input": 0.0,
        "cost_per_1k_output": 0.0,
        "env_key": "",  # No key needed
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "default_model": "deepseek-v2",
        "cost_per_1k_input": 0.0,
        "cost_per_1k_output": 0.0,
        "env_key": "",  # No key needed
    },
}


# ---------------------------------------------------------------------------
# Helper: calculate cost
# ---------------------------------------------------------------------------


def _calculate_cost(
    provider_cfg: dict[str, Any],
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    input_cost = (prompt_tokens / 1000) * provider_cfg["cost_per_1k_input"]
    output_cost = (completion_tokens / 1000) * provider_cfg["cost_per_1k_output"]
    return round(input_cost + output_cost, 8)


# ---------------------------------------------------------------------------
# LLMClient
# ---------------------------------------------------------------------------


class LLMClient:
    """Unified LLM client supporting DeepSeek, Claude, and Qwen.

    Uses httpx for OpenAI-compatible endpoints (DeepSeek, Qwen) and the
    ``anthropic`` SDK for Claude.
    """

    PROVIDERS: dict[str, dict[str, Any]] = _PROVIDERS

    def __init__(self, timeout: float = 120.0) -> None:
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        provider: str = "openrouter",
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> LLMResponse:
        """Send a chat completion request and return an ``LLMResponse``.

        Args:
            messages: OpenAI-style message list (role/content dicts).
            provider: One of ``deepseek``, ``anthropic``, ``qwen``.
            model: Override the provider's default model.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens in the response.

        Returns:
            An immutable ``LLMResponse``.

        Raises:
            ValueError: If the provider is unknown or its API key is missing.
            httpx.HTTPStatusError: On non-2xx responses from OpenAI-compat APIs.
        """
        cfg = self._get_provider_config(provider)
        resolved_model = model or cfg["default_model"]

        # BYOK override: user-provided API key and/or base URL
        if api_key:
            cfg = {**cfg, "api_key": api_key}
        if base_url:
            cfg = {**cfg, "base_url": base_url}

        if provider == "anthropic":
            return await self._chat_anthropic(
                messages, resolved_model, temperature, max_tokens, cfg
            )

        return await self._chat_openai_compat(
            messages, resolved_model, temperature, max_tokens, cfg
        )

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        provider: str = "openrouter",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Chat and parse the response as JSON.

        Appends an instruction asking the LLM to reply with valid JSON.
        Returns the parsed dict.

        Raises:
            json.JSONDecodeError: If the response cannot be parsed as JSON.
        """
        augmented_messages = [
            *messages,
            {
                "role": "user",
                "content": (
                    "IMPORTANT: Respond ONLY with valid JSON. "
                    "No markdown, no code fences, no extra text."
                ),
            },
        ]
        response = await self.chat(augmented_messages, provider=provider, **kwargs)
        cleaned = response.content.strip()

        # Strip markdown code fences if present
        if cleaned.startswith("```"):
            first_newline = cleaned.index("\n")
            cleaned = cleaned[first_newline + 1 :]
        if cleaned.endswith("```"):
            cleaned = cleaned[: -3]

        return json.loads(cleaned.strip())

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_provider_config(self, provider: str) -> dict[str, Any]:
        if provider not in _PROVIDERS:
            raise ValueError(
                f"Unknown provider '{provider}'. "
                f"Choose from: {', '.join(_PROVIDERS)}"
            )
        cfg = _PROVIDERS[provider]
        env_key = cfg.get("env_key", "")
        if env_key:
            api_key = os.environ.get(env_key, "")
            if not api_key:
                raise ValueError(
                    f"API key env var '{env_key}' is not set for provider '{provider}'"
                )
        else:
            # Local providers (vllm, ollama) — allow custom base_url via env var
            api_key = ""
            if provider == "vllm":
                cfg = {**cfg, "base_url": os.environ.get("VLLM_BASE_URL", cfg["base_url"])}
            elif provider == "ollama":
                cfg = {**cfg, "base_url": os.environ.get("OLLAMA_BASE_URL", cfg["base_url"])}
        return {**cfg, "api_key": api_key}

    async def chat_batch(
        self,
        messages_batch: list[list[dict[str, str]]],
        *,
        provider: str = "openrouter",
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> list[str]:
        """Send a batch of message lists and return a list of reply strings.

        For all providers this uses ``asyncio.gather`` over parallel ``chat()``
        calls.  A vLLM-specific native batch path can be added here later.

        Fallback chain: if a single call fails it returns ``"[ERROR: ...]"``
        rather than raising, so the caller receives partial results.

        Args:
            messages_batch: List of OpenAI-style message lists.
            provider: LLM provider (same options as ``chat()``).
            model: Override the provider's default model.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens per response.

        Returns:
            List of reply strings in the same order as ``messages_batch``.
        """
        if not messages_batch:
            return []

        async def _safe_chat(msgs: list[dict[str, str]]) -> str:
            try:
                resp = await self.chat(
                    msgs,
                    provider=provider,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    api_key=api_key,
                    base_url=base_url,
                )
                return resp.content
            except Exception as exc:
                logger.warning("chat_batch single call failed: %s", exc)
                return f"[ERROR: {exc}]"

        results = await asyncio.gather(*[_safe_chat(msgs) for msgs in messages_batch])
        return list(results)

    async def _chat_openai_compat(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        cfg: dict[str, Any],
    ) -> LLMResponse:
        """Call an OpenAI-compatible chat endpoint (DeepSeek / Qwen / vLLM / Ollama)."""
        url = f"{cfg['base_url']}/chat/completions"
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if cfg.get("api_key"):
            headers["Authorization"] = f"Bearer {cfg['api_key']}"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0]
        usage_raw = data.get("usage", {})
        prompt_tokens = usage_raw.get("prompt_tokens", 0)
        completion_tokens = usage_raw.get("completion_tokens", 0)

        usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }

        return LLMResponse(
            content=choice["message"]["content"],
            model=data.get("model", model),
            usage=usage,
            cost_usd=_calculate_cost(cfg, prompt_tokens, completion_tokens),
        )

    async def _chat_anthropic(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        cfg: dict[str, Any],
    ) -> LLMResponse:
        """Call Anthropic's Claude API via the ``anthropic`` SDK."""
        import anthropic  # noqa: WPS433 — lazy import to avoid hard dep

        client = anthropic.AsyncAnthropic(api_key=cfg["api_key"])

        # Separate system message from conversation
        system_text = ""
        conversation: list[dict[str, str]] = []
        for msg in messages:
            if msg["role"] == "system":
                system_text = msg["content"]
            else:
                conversation.append({"role": msg["role"], "content": msg["content"]})

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": conversation,
        }
        if system_text:
            kwargs["system"] = system_text

        response = await client.messages.create(**kwargs)

        content_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                content_text += block.text

        prompt_tokens = response.usage.input_tokens
        completion_tokens = response.usage.output_tokens

        usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }

        return LLMResponse(
            content=content_text,
            model=response.model,
            usage=usage,
            cost_usd=_calculate_cost(cfg, prompt_tokens, completion_tokens),
        )
