"""Unified async LLM client wrapper for DeepSeek, Claude (Anthropic), Qwen, and Google.

Supports OpenAI-compatible APIs via httpx, the Anthropic SDK, and Google Generative AI REST.
All API keys are loaded from environment variables.

Provider selection env vars:
  LLM_PROVIDER           — report/default provider (default: openrouter)
  AGENT_LLM_PROVIDER     — agent-decision provider (falls back to LLM_PROVIDER)
  AGENT_LLM_MODEL        — agent-decision model override (e.g. google/gemini-3.1-flash-lite-preview)

Google provider env vars:
  GOOGLE_API_KEY         — required for provider="google"
  GOOGLE_AGENT_MODEL     — model for agent decisions when AGENT_LLM_PROVIDER=google
  GOOGLE_REPORT_MODEL    — model for report generation (default: gemini-3.1-pro-preview)
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

from backend.app.utils.logger import get_logger
from backend.app.utils.telemetry import get_tracer

logger = get_logger("llm_client")
_llm_tracer = get_tracer("llm_client")

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

# ---------------------------------------------------------------------------
# Retry / backoff constants
# ---------------------------------------------------------------------------

_MAX_RETRIES = 3
_RETRY_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503, 504})
_RETRY_BASE_DELAY_S = 1.0

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
    "google": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "default_model": "gemini-3-flash-preview",  # override with GOOGLE_AGENT_MODEL
        "cost_per_1k_input": 0.0,  # preview pricing TBD
        "cost_per_1k_output": 0.0,
        "env_key": "GOOGLE_API_KEY",
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
    # Auto-detecting local inference with OpenRouter fallback
    "local": {
        "base_url": "",  # Determined by LocalInferenceAdapter
        "default_model": "",  # Determined by LocalInferenceAdapter
        "cost_per_1k_input": 0.0,
        "cost_per_1k_output": 0.0,
        "env_key": "",  # No key needed for local; adapter handles fallback
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
# Public helpers — read env vars so callers don't need to import os
# ---------------------------------------------------------------------------


def get_default_provider() -> str:
    """Return the active LLM provider from LLM_PROVIDER env var (default: openrouter)."""
    return os.environ.get("LLM_PROVIDER", "openrouter")


def get_agent_provider_model() -> tuple[str, str]:
    """Return (provider, model) for agent decision tasks.

    Reads AGENT_LLM_PROVIDER (falls back to LLM_PROVIDER) and AGENT_LLM_MODEL.
    When provider is google, also checks GOOGLE_AGENT_MODEL for the model.
    """
    provider = os.environ.get("AGENT_LLM_PROVIDER") or get_default_provider()
    if os.environ.get("AGENT_LLM_MODEL"):
        model = os.environ["AGENT_LLM_MODEL"]
    elif provider == "google":
        model = os.environ.get("GOOGLE_AGENT_MODEL", _PROVIDERS["google"]["default_model"])
    else:
        model = _PROVIDERS.get(provider, _PROVIDERS["openrouter"])["default_model"]
    return provider, model


def get_agent_model(is_stakeholder: bool = True) -> tuple[str, str]:
    """Return (provider, model) with model routing based on stakeholder status.

    Stakeholders use AGENT_LLM_MODEL (stronger model).
    Background agents use AGENT_LLM_MODEL_LITE (cheaper model).
    Falls back to AGENT_LLM_MODEL if LITE not set.
    """
    if is_stakeholder:
        return get_agent_provider_model()
    provider = os.environ.get("AGENT_LLM_PROVIDER") or get_default_provider()
    lite_model = os.environ.get("AGENT_LLM_MODEL_LITE")
    if lite_model:
        return provider, lite_model
    return get_agent_provider_model()


def get_report_provider_model() -> tuple[str, str]:
    """Return (provider, model) for report generation tasks.

    When LLM_PROVIDER=google, uses GOOGLE_REPORT_MODEL env var.
    Otherwise returns the provider's default model.
    """
    provider = get_default_provider()
    if provider == "google":
        model = os.environ.get("GOOGLE_REPORT_MODEL", "gemini-3.1-pro-preview")
    else:
        model = _PROVIDERS.get(provider, _PROVIDERS["openrouter"])["default_model"]
    return provider, model


# ---------------------------------------------------------------------------
# LLMClient
# ---------------------------------------------------------------------------


class LLMClient:
    """Unified LLM client supporting DeepSeek, Claude, and Qwen.

    Uses httpx for OpenAI-compatible endpoints (DeepSeek, Qwen) and the
    ``anthropic`` SDK for Claude.

    Connection pools are reused across calls to avoid per-call TCP/TLS overhead.
    Call ``await client.close()`` when done (e.g. on app shutdown).
    """

    PROVIDERS: dict[str, dict[str, Any]] = _PROVIDERS

    def __init__(self, timeout: float = 120.0) -> None:
        self._timeout = timeout
        # Persistent HTTP client — reused across all OpenAI-compat calls
        self._http_client: httpx.AsyncClient | None = None
        # Cached Anthropic client — recreated only when api_key changes
        self._anthropic_client: Any | None = None
        self._anthropic_api_key: str | None = None
        # Lazy-init local inference adapter (vLLM/Ollama with OpenRouter fallback)
        self._local_adapter: Any | None = None

    def _get_http_client(self) -> httpx.AsyncClient:
        """Return the shared httpx client, creating it lazily if needed."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=self._timeout,
                limits=httpx.Limits(
                    max_connections=50,
                    max_keepalive_connections=20,
                    keepalive_expiry=30.0,
                ),
            )
        return self._http_client

    def _get_anthropic_client(self, api_key: str) -> Any:
        """Return a cached Anthropic client, recreating if the key changed."""
        import anthropic  # noqa: WPS433

        if self._anthropic_client is None or self._anthropic_api_key != api_key:
            self._anthropic_client = anthropic.AsyncAnthropic(api_key=api_key)
            self._anthropic_api_key = api_key
        return self._anthropic_client

    async def close(self) -> None:
        """Release pooled connections. Call on application shutdown."""
        if self._http_client is not None and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None
        if self._anthropic_client is not None:
            try:
                await self._anthropic_client.close()
            except Exception:
                pass
            self._anthropic_client = None
            self._anthropic_api_key = None

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
        session_id: str | None = None,
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

        if provider == "local":
            response = await self._chat_local(messages, temperature, max_tokens)
        elif provider == "anthropic":
            response = await self._chat_anthropic(messages, resolved_model, temperature, max_tokens, cfg)
        elif provider == "google":
            response = await self._chat_google(messages, resolved_model, temperature, max_tokens, cfg)
        else:
            response = await self._chat_openai_compat(messages, resolved_model, temperature, max_tokens, cfg)

        if session_id and response.cost_usd > 0:
            from backend.app.services.cost_tracker import record_cost  # noqa: PLC0415

            await record_cost(session_id, response.cost_usd)

        return response

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
                "content": ("IMPORTANT: Respond ONLY with valid JSON. No markdown, no code fences, no extra text."),
            },
        ]
        response = await self.chat(augmented_messages, provider=provider, **kwargs)
        cleaned = response.content.strip()

        # Strip markdown code fences if present
        if cleaned.startswith("```"):
            first_newline = cleaned.index("\n")
            cleaned = cleaned[first_newline + 1 :]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]

        return json.loads(cleaned.strip())

    # ------------------------------------------------------------------
    # Local inference (vLLM / Ollama with OpenRouter fallback)
    # ------------------------------------------------------------------

    def _get_local_adapter(self) -> Any:
        """Return the lazily-initialised LocalInferenceAdapter singleton."""
        if self._local_adapter is None:
            from backend.app.services.local_inference import LocalInferenceAdapter  # noqa: PLC0415

            self._local_adapter = LocalInferenceAdapter()
        return self._local_adapter

    async def _chat_local(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        """Route chat through LocalInferenceAdapter with auto-fallback.

        The adapter returns a plain string; we wrap it in an LLMResponse with
        zero cost (local GPU) and estimated token counts.
        """
        adapter = self._get_local_adapter()
        _t0 = time.monotonic()
        content = await adapter.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        _latency_ms = round((time.monotonic() - _t0) * 1000)

        # Rough token estimates (no usage data from local endpoints)
        prompt_chars = sum(len(m.get("content", "")) for m in messages)
        est_prompt_tokens = max(1, prompt_chars // 4)
        est_completion_tokens = max(1, len(content) // 4)
        usage = {
            "prompt_tokens": est_prompt_tokens,
            "completion_tokens": est_completion_tokens,
            "total_tokens": est_prompt_tokens + est_completion_tokens,
        }

        backend_name = adapter._backend.name
        model_name = adapter._backend.model
        logger.info(
            "LLM local/%s/%s | ~%d tokens | $0.00 | %dms",
            backend_name,
            model_name,
            est_prompt_tokens + est_completion_tokens,
            _latency_ms,
        )
        with _llm_tracer.start_as_current_span("llm.chat") as _span:
            _span.set_attribute("llm.provider", f"local/{backend_name}")
            _span.set_attribute("llm.model", str(model_name))
            _span.set_attribute("llm.tokens.total", int(est_prompt_tokens + est_completion_tokens))
            _span.set_attribute("llm.cost_usd", 0.0)
            _span.set_attribute("llm.latency_ms", float(_latency_ms))

        return LLMResponse(
            content=content,
            model=f"local/{model_name}",
            usage=usage,
            cost_usd=0.0,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_provider_config(self, provider: str) -> dict[str, Any]:
        if provider not in _PROVIDERS:
            raise ValueError(f"Unknown provider '{provider}'. Choose from: {', '.join(_PROVIDERS)}")
        cfg = _PROVIDERS[provider]
        env_key = cfg.get("env_key", "")
        if env_key:
            api_key = os.environ.get(env_key, "")
            if not api_key:
                raise ValueError(f"API key env var '{env_key}' is not set for provider '{provider}'")
        else:
            # Local providers (vllm, ollama) — allow custom base_url via env var
            api_key = ""
            if provider == "vllm":
                cfg = {**cfg, "base_url": os.environ.get("VLLM_BASE_URL", cfg["base_url"])}
            elif provider == "ollama":
                cfg = {**cfg, "base_url": os.environ.get("OLLAMA_BASE_URL", cfg["base_url"])}
        # Google: allow GOOGLE_AGENT_MODEL to override default_model for agent decisions
        if provider == "google":
            agent_model = os.environ.get("GOOGLE_AGENT_MODEL", cfg["default_model"])
            cfg = {**cfg, "default_model": agent_model}
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

        client = self._get_http_client()
        _t0 = time.monotonic()
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                break  # success — exit retry loop
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                status = exc.response.status_code if exc.response is not None else 0
                if status in _RETRY_STATUSES and attempt < _MAX_RETRIES - 1:
                    delay = _RETRY_BASE_DELAY_S * (2**attempt)
                    logger.warning(
                        "LLM %s HTTP %d — retrying in %.1fs (attempt %d/%d)",
                        model,
                        status,
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    delay = _RETRY_BASE_DELAY_S * (2**attempt)
                    logger.warning(
                        "LLM %s connection error — retrying in %.1fs (attempt %d/%d): %s",
                        model,
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                        exc,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise
        else:
            # Loop exhausted without break — all retries failed
            if last_exc is not None:
                raise last_exc
        _latency_ms = round((time.monotonic() - _t0) * 1000)
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

        cost = _calculate_cost(cfg, prompt_tokens, completion_tokens)
        logger.info(
            "LLM %s | %d tokens (in=%d out=%d) | $%.6f | %dms",
            model,
            prompt_tokens + completion_tokens,
            prompt_tokens,
            completion_tokens,
            cost,
            _latency_ms,
        )
        with _llm_tracer.start_as_current_span("llm.chat") as _span:
            _span.set_attribute("llm.provider", str(cfg.get("base_url", "")))
            _span.set_attribute("llm.model", str(model))
            _span.set_attribute("llm.tokens.total", int(prompt_tokens + completion_tokens))
            _span.set_attribute("llm.cost_usd", float(cost))
            _span.set_attribute("llm.latency_ms", float(_latency_ms))

        return LLMResponse(
            content=choice["message"]["content"],
            model=data.get("model", model),
            usage=usage,
            cost_usd=cost,
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
        client = self._get_anthropic_client(cfg["api_key"])

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

        _t0 = time.monotonic()
        response = await client.messages.create(**kwargs)
        _latency_ms = round((time.monotonic() - _t0) * 1000)

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

        cost = _calculate_cost(cfg, prompt_tokens, completion_tokens)
        logger.info(
            "LLM %s | %d tokens (in=%d out=%d) | $%.6f | %dms",
            model,
            prompt_tokens + completion_tokens,
            prompt_tokens,
            completion_tokens,
            cost,
            _latency_ms,
        )
        with _llm_tracer.start_as_current_span("llm.chat") as _span:
            _span.set_attribute("llm.provider", "anthropic")
            _span.set_attribute("llm.model", str(model))
            _span.set_attribute("llm.tokens.total", int(prompt_tokens + completion_tokens))
            _span.set_attribute("llm.cost_usd", float(cost))
            _span.set_attribute("llm.latency_ms", float(_latency_ms))

        return LLMResponse(
            content=content_text,
            model=response.model,
            usage=usage,
            cost_usd=cost,
        )

    async def _chat_google(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        cfg: dict[str, Any],
    ) -> LLMResponse:
        """Call Google Generative AI REST API (generateContent)."""
        api_key = cfg["api_key"]
        base_url = cfg["base_url"]
        url = f"{base_url}/models/{model}:generateContent?key={api_key}"

        # Separate system message; convert "assistant" role → "model" for Google
        system_text = ""
        contents: list[dict[str, Any]] = []
        for msg in messages:
            role = msg["role"]
            text = msg["content"]
            if role == "system":
                system_text = text
            else:
                google_role = "model" if role == "assistant" else "user"
                contents.append({"role": google_role, "parts": [{"text": text}]})

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_text:
            payload["system_instruction"] = {"parts": [{"text": system_text}]}

        client = self._get_http_client()
        _t0 = time.monotonic()
        resp = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
        _latency_ms = round((time.monotonic() - _t0) * 1000)
        resp.raise_for_status()
        data = resp.json()

        candidates = data.get("candidates", [])
        content_text = ""
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            content_text = "".join(p.get("text", "") for p in parts)

        usage_meta = data.get("usageMetadata", {})
        prompt_tokens = usage_meta.get("promptTokenCount", 0)
        completion_tokens = usage_meta.get("candidatesTokenCount", 0)
        usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }

        cost = _calculate_cost(cfg, prompt_tokens, completion_tokens)
        logger.info(
            "LLM %s | %d tokens (in=%d out=%d) | $%.6f | %dms",
            model,
            prompt_tokens + completion_tokens,
            prompt_tokens,
            completion_tokens,
            cost,
            _latency_ms,
        )
        with _llm_tracer.start_as_current_span("llm.chat") as _span:
            _span.set_attribute("llm.provider", "google")
            _span.set_attribute("llm.model", str(model))
            _span.set_attribute("llm.tokens.total", int(prompt_tokens + completion_tokens))
            _span.set_attribute("llm.cost_usd", float(cost))
            _span.set_attribute("llm.latency_ms", float(_latency_ms))

        return LLMResponse(
            content=content_text,
            model=model,
            usage=usage,
            cost_usd=cost,
        )


# Module-level singleton for service code (not report_agent which has its own)
_default_client: LLMClient | None = None


def get_default_client() -> LLMClient:
    """Return the shared module-level LLMClient singleton.
    Use this in service code instead of LLMClient() per call."""
    global _default_client
    if _default_client is None:
        _default_client = LLMClient()
    return _default_client
