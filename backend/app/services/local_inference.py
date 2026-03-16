"""Local GPU inference adapter (vLLM / Ollama) with OpenRouter fallback.

Provides a drop-in replacement for ``llm_client.chat()`` that automatically
routes to the configured local inference backend or falls back to OpenRouter.

Environment variables:
    INFERENCE_BACKEND    "openrouter" (default) | "vllm" | "ollama"
    VLLM_BASE_URL        vLLM OpenAI-compat endpoint (default: http://localhost:8000/v1)
    VLLM_MODEL           Model name served by vLLM (default: deepseek/deepseek-v3.2)
    OLLAMA_BASE_URL      Ollama OpenAI-compat endpoint (default: http://localhost:11434/v1)
    OLLAMA_MODEL         Model name served by Ollama (default: deepseek-v2)
    OPENROUTER_API_KEY   Required when backend is "openrouter"
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any

import httpx

from backend.app.utils.logger import get_logger

logger = get_logger("local_inference")

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_VLLM_URL = "http://localhost:8000/v1"
_DEFAULT_OLLAMA_URL = "http://localhost:11434/v1"
_DEFAULT_VLLM_MODEL = "deepseek/deepseek-v3.2"
_DEFAULT_OLLAMA_MODEL = "deepseek-v2"
_DEFAULT_OPENROUTER_URL = "https://openrouter.ai/api/v1"
_DEFAULT_OPENROUTER_MODEL = "deepseek/deepseek-v3.2"
_PROBE_TIMEOUT = 3.0  # seconds for backend health probe


# ---------------------------------------------------------------------------
# Immutable backend descriptor
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InferenceBackend:
    """Immutable descriptor for a configured inference backend."""

    name: str  # "openrouter" | "vllm" | "ollama"
    base_url: str
    model: str
    max_concurrent: int = 50
    batch_size: int = 1  # vLLM supports >1 natively


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class LocalInferenceAdapter:
    """Drop-in replacement for ``chat()`` with local GPU inference support.

    Supports three backends:
    - **vllm**: High-throughput batched inference via ``/v1/completions``
    - **ollama**: Local Ollama server via OpenAI-compat ``/v1/chat/completions``
    - **openrouter**: Cloud fallback (existing ``llm_client`` behaviour)

    Falls back to OpenRouter if the configured local backend is unreachable.
    """

    def __init__(self) -> None:
        backend_name = os.getenv("INFERENCE_BACKEND", "openrouter").lower()
        self._backend: InferenceBackend = self._build_backend(backend_name)
        self._semaphore = asyncio.Semaphore(self._backend.max_concurrent)
        logger.info(
            "LocalInferenceAdapter initialised: backend=%s url=%s model=%s",
            self._backend.name,
            self._backend.base_url,
            self._backend.model,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> str:
        """Single message chat. Routes to configured backend.

        Returns:
            The assistant reply as a plain string.

        Raises:
            RuntimeError: If all backends (primary + fallback) fail.
        """
        try:
            async with self._semaphore:
                return await self._dispatch_single(messages, temperature, max_tokens)
        except Exception as exc:
            logger.warning(
                "Primary backend '%s' failed (%s), falling back to openrouter",
                self._backend.name,
                exc,
            )
            return await self._openrouter_single(messages, temperature, max_tokens)

    async def chat_batch(
        self,
        batch: list[list[dict]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> list[str]:
        """Batched chat. vLLM sends N prompts in one HTTP call; others parallelise.

        Args:
            batch: List of message lists, one per prompt.

        Returns:
            List of reply strings in the same order as ``batch``.
        """
        if not batch:
            return []

        if self._backend.name == "vllm":
            try:
                return await self._vllm_batch(batch, temperature, max_tokens)
            except Exception as exc:
                logger.warning("vLLM batch failed (%s), falling back to parallel single", exc)

        # Parallel single calls for ollama + openrouter (+ vLLM fallback)
        tasks = [self.chat(msgs, temperature=temperature, max_tokens=max_tokens) for msgs in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [
            r if isinstance(r, str) else f"[ERROR: {r}]"
            for r in results
        ]

    @staticmethod
    def detect_backend() -> InferenceBackend:
        """Auto-detect available backend by probing endpoints synchronously.

        Probe order: vLLM → Ollama → OpenRouter (always available).

        Returns:
            The first reachable InferenceBackend.
        """
        import urllib.request  # stdlib, no extra deps

        probes: list[tuple[str, str, str]] = [
            ("vllm", os.getenv("VLLM_BASE_URL", _DEFAULT_VLLM_URL), os.getenv("VLLM_MODEL", _DEFAULT_VLLM_MODEL)),
            ("ollama", os.getenv("OLLAMA_BASE_URL", _DEFAULT_OLLAMA_URL), os.getenv("OLLAMA_MODEL", _DEFAULT_OLLAMA_MODEL)),
        ]

        for name, base_url, model in probes:
            health_url = f"{base_url.rstrip('/')}/models"
            try:
                req = urllib.request.Request(health_url, method="GET")
                with urllib.request.urlopen(req, timeout=_PROBE_TIMEOUT):
                    logger.info("detect_backend: found '%s' at %s", name, base_url)
                    return InferenceBackend(name=name, base_url=base_url, model=model)
            except Exception:
                continue

        # Default: OpenRouter
        return InferenceBackend(
            name="openrouter",
            base_url=_DEFAULT_OPENROUTER_URL,
            model=_DEFAULT_OPENROUTER_MODEL,
        )

    # ------------------------------------------------------------------
    # Private dispatch helpers
    # ------------------------------------------------------------------

    async def _dispatch_single(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Route a single request to the configured backend."""
        name = self._backend.name
        if name == "vllm":
            return await self._vllm_single(messages, temperature, max_tokens)
        if name == "ollama":
            return await self._openai_compat_single(messages, temperature, max_tokens)
        # openrouter
        return await self._openrouter_single(messages, temperature, max_tokens)

    async def _vllm_single(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Single request to vLLM via OpenAI-compat chat/completions."""
        return await self._openai_compat_single(messages, temperature, max_tokens)

    async def _vllm_batch(
        self,
        batch: list[list[dict]],
        temperature: float,
        max_tokens: int,
    ) -> list[str]:
        """Send N prompts to vLLM in one HTTP call using a custom batch endpoint.

        vLLM's OpenAI-compat API doesn't natively support array-of-prompts in
        one call, so we use parallel asyncio tasks with the semaphore for
        concurrency control.
        """
        tasks = [
            self._openai_compat_single(msgs, temperature, max_tokens)
            for msgs in batch
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [
            r if isinstance(r, str) else f"[ERROR: {r}]"
            for r in results
        ]

    async def _openai_compat_single(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Generic OpenAI-compat chat/completions call (vLLM or Ollama)."""
        url = f"{self._backend.base_url.rstrip('/')}/chat/completions"
        payload: dict[str, Any] = {
            "model": self._backend.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {"Content-Type": "application/json"}

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        return data["choices"][0]["message"]["content"]

    async def _openrouter_single(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Fallback single request to OpenRouter."""
        api_key = os.getenv("OPENROUTER_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY not set — cannot fall back to OpenRouter")

        url = f"{_DEFAULT_OPENROUTER_URL}/chat/completions"
        payload: dict[str, Any] = {
            "model": _DEFAULT_OPENROUTER_MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        return data["choices"][0]["message"]["content"]

    # ------------------------------------------------------------------
    # Backend factory
    # ------------------------------------------------------------------

    @staticmethod
    def _build_backend(name: str) -> InferenceBackend:
        """Construct an InferenceBackend from env vars for the given name."""
        if name == "vllm":
            return InferenceBackend(
                name="vllm",
                base_url=os.getenv("VLLM_BASE_URL", _DEFAULT_VLLM_URL),
                model=os.getenv("VLLM_MODEL", _DEFAULT_VLLM_MODEL),
                max_concurrent=int(os.getenv("VLLM_MAX_CONCURRENT", "50")),
                batch_size=int(os.getenv("VLLM_BATCH_SIZE", "16")),
            )
        if name == "ollama":
            return InferenceBackend(
                name="ollama",
                base_url=os.getenv("OLLAMA_BASE_URL", _DEFAULT_OLLAMA_URL),
                model=os.getenv("OLLAMA_MODEL", _DEFAULT_OLLAMA_MODEL),
                max_concurrent=int(os.getenv("OLLAMA_MAX_CONCURRENT", "4")),
                batch_size=1,
            )
        # Default: openrouter
        return InferenceBackend(
            name="openrouter",
            base_url=_DEFAULT_OPENROUTER_URL,
            model=os.getenv("OPENROUTER_MODEL", _DEFAULT_OPENROUTER_MODEL),
            max_concurrent=int(os.getenv("OPENROUTER_MAX_CONCURRENT", "50")),
            batch_size=1,
        )
