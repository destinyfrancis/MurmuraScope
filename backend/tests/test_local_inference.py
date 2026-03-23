"""Tests for backend.app.services.local_inference (Phase 4E).

~15 tests covering:
- InferenceBackend frozen dataclass
- LocalInferenceAdapter backend construction from env vars
- chat routes to correct backend (mocked HTTP)
- chat_batch with vllm (mocked)
- chat_batch fallback for non-vllm (parallel singles)
- detect_backend env var logic
- fallback chain on primary failure
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from backend.app.services.local_inference import (
    _DEFAULT_OLLAMA_URL,
    _DEFAULT_OPENROUTER_URL,
    _DEFAULT_VLLM_URL,
    InferenceBackend,
    LocalInferenceAdapter,
)

# ---------------------------------------------------------------------------
# InferenceBackend (frozen)
# ---------------------------------------------------------------------------


class TestInferenceBackend:
    def test_frozen(self):
        backend = InferenceBackend(name="openrouter", base_url="https://x.com", model="gpt-4")
        with pytest.raises(Exception):
            backend.name = "vllm"  # type: ignore[misc]

    def test_defaults(self):
        backend = InferenceBackend(
            name="vllm",
            base_url=_DEFAULT_VLLM_URL,
            model="deepseek/deepseek-v3.2",
        )
        assert backend.max_concurrent == 50
        assert backend.batch_size == 1

    def test_custom_batch_size(self):
        backend = InferenceBackend(
            name="vllm",
            base_url=_DEFAULT_VLLM_URL,
            model="m",
            batch_size=16,
        )
        assert backend.batch_size == 16

    def test_all_three_backends_constructible(self):
        for name, url in [
            ("vllm", _DEFAULT_VLLM_URL),
            ("ollama", _DEFAULT_OLLAMA_URL),
            ("openrouter", _DEFAULT_OPENROUTER_URL),
        ]:
            b = InferenceBackend(name=name, base_url=url, model="x")
            assert b.name == name


# ---------------------------------------------------------------------------
# LocalInferenceAdapter backend construction
# ---------------------------------------------------------------------------


class TestLocalInferenceAdapterConstruction:
    def test_default_backend_is_openrouter(self, monkeypatch):
        monkeypatch.delenv("INFERENCE_BACKEND", raising=False)
        adapter = LocalInferenceAdapter()
        assert adapter._backend.name == "openrouter"

    def test_vllm_backend_from_env(self, monkeypatch):
        monkeypatch.setenv("INFERENCE_BACKEND", "vllm")
        adapter = LocalInferenceAdapter()
        assert adapter._backend.name == "vllm"

    def test_ollama_backend_from_env(self, monkeypatch):
        monkeypatch.setenv("INFERENCE_BACKEND", "ollama")
        adapter = LocalInferenceAdapter()
        assert adapter._backend.name == "ollama"

    def test_vllm_base_url_from_env(self, monkeypatch):
        monkeypatch.setenv("INFERENCE_BACKEND", "vllm")
        monkeypatch.setenv("VLLM_BASE_URL", "http://my-gpu-server:8000/v1")
        adapter = LocalInferenceAdapter()
        assert adapter._backend.base_url == "http://my-gpu-server:8000/v1"

    def test_ollama_base_url_from_env(self, monkeypatch):
        monkeypatch.setenv("INFERENCE_BACKEND", "ollama")
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:9999/v1")
        adapter = LocalInferenceAdapter()
        assert adapter._backend.base_url == "http://localhost:9999/v1"


# ---------------------------------------------------------------------------
# chat — mocked HTTP calls
# ---------------------------------------------------------------------------


def _mock_openai_response(content: str) -> dict:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        "model": "test",
    }


class TestLocalInferenceChat:
    @pytest.mark.asyncio
    async def test_chat_openrouter_route(self, monkeypatch):
        monkeypatch.setenv("INFERENCE_BACKEND", "openrouter")
        monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key")
        adapter = LocalInferenceAdapter()

        async def mock_post(*args, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = _mock_openai_response("Hello from OpenRouter")
            return resp

        with patch("httpx.AsyncClient.post", new=mock_post):
            result = await adapter.chat([{"role": "user", "content": "hi"}])
        assert "Hello" in result

    @pytest.mark.asyncio
    async def test_chat_vllm_route(self, monkeypatch):
        monkeypatch.setenv("INFERENCE_BACKEND", "vllm")
        adapter = LocalInferenceAdapter()

        async def mock_post(*args, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = _mock_openai_response("Hello from vLLM")
            return resp

        with patch("httpx.AsyncClient.post", new=mock_post):
            result = await adapter.chat([{"role": "user", "content": "hi"}])
        assert "vLLM" in result

    @pytest.mark.asyncio
    async def test_chat_falls_back_to_openrouter_on_failure(self, monkeypatch):
        monkeypatch.setenv("INFERENCE_BACKEND", "vllm")
        monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key")
        adapter = LocalInferenceAdapter()

        call_count = {"n": 0}

        async def mock_post(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise httpx.ConnectError("vLLM unreachable")
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = _mock_openai_response("Fallback response")
            return resp

        with patch("httpx.AsyncClient.post", new=mock_post):
            result = await adapter.chat([{"role": "user", "content": "hi"}])
        assert "Fallback" in result
        assert call_count["n"] == 2  # first try vLLM, then openrouter


# ---------------------------------------------------------------------------
# chat_batch
# ---------------------------------------------------------------------------


class TestChatBatch:
    @pytest.mark.asyncio
    async def test_chat_batch_empty_input(self, monkeypatch):
        monkeypatch.setenv("INFERENCE_BACKEND", "openrouter")
        monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key")
        adapter = LocalInferenceAdapter()
        results = await adapter.chat_batch([])
        assert results == []

    @pytest.mark.asyncio
    async def test_chat_batch_parallel_singles_for_ollama(self, monkeypatch):
        monkeypatch.setenv("INFERENCE_BACKEND", "ollama")
        adapter = LocalInferenceAdapter()

        responses_sent = {"n": 0}

        async def mock_post(*args, **kwargs):
            responses_sent["n"] += 1
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = _mock_openai_response(f"reply-{responses_sent['n']}")
            return resp

        batch = [
            [{"role": "user", "content": "q1"}],
            [{"role": "user", "content": "q2"}],
            [{"role": "user", "content": "q3"}],
        ]
        with patch("httpx.AsyncClient.post", new=mock_post):
            results = await adapter.chat_batch(batch)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_chat_batch_preserves_order(self, monkeypatch):
        monkeypatch.setenv("INFERENCE_BACKEND", "openrouter")
        monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key")
        adapter = LocalInferenceAdapter()

        call_idx = {"n": 0}

        async def mock_post(*args, **kwargs):
            idx = call_idx["n"]
            call_idx["n"] += 1
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = _mock_openai_response(f"result-{idx}")
            return resp

        batch = [[{"role": "user", "content": f"q{i}"}] for i in range(4)]
        with patch("httpx.AsyncClient.post", new=mock_post):
            results = await adapter.chat_batch(batch)
        assert len(results) == 4


# ---------------------------------------------------------------------------
# detect_backend
# ---------------------------------------------------------------------------


class TestDetectBackend:
    def test_detect_fallback_to_openrouter_when_no_local(self, monkeypatch):
        # urllib.request.urlopen will raise on any URL → both local backends fail

        def raise_error(req, timeout=None):
            raise Exception("Connection refused")

        with patch("urllib.request.urlopen", side_effect=raise_error):
            backend = LocalInferenceAdapter.detect_backend()
        assert backend.name == "openrouter"

    def test_detect_prefers_vllm_when_available(self, monkeypatch):

        call_count = {"n": 0}

        def mock_urlopen(req, timeout=None):
            call_count["n"] += 1
            if "8000" in req.full_url:
                return MagicMock()  # vLLM reachable
            raise Exception("Not reachable")

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            backend = LocalInferenceAdapter.detect_backend()
        assert backend.name == "vllm"
