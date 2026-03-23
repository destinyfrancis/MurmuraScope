# backend/tests/test_async_embeddings.py
"""Verify that sync embedding calls inside async functions are properly
offloaded to a thread pool via asyncio.to_thread().

These tests use unittest.mock to confirm asyncio.to_thread is invoked in the
relevant async methods so the event loop is never blocked.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# MemoryInitializationService._semantic_search_world_context
# ---------------------------------------------------------------------------


class TestSemanticSearchWorldContextUsesThread:
    """_semantic_search_world_context must wrap embed_single in asyncio.to_thread."""

    @pytest.mark.asyncio
    async def test_embed_single_offloaded_to_thread(self):
        """asyncio.to_thread must be called for the embed_single embedding step."""
        from backend.app.services.memory_initialization import MemoryInitializationService

        _GRAPH_ID = "test_graph_id_0123456789ab"
        # Table name = "swc_" + graph_id[:12] = "swc_test_graph_i"
        _TABLE_NAME = f"swc_{_GRAPH_ID[:12]}"

        svc = MemoryInitializationService.__new__(MemoryInitializationService)
        svc._lancedb_path = "/nonexistent/path"

        fake_vec = np.zeros(384, dtype=np.float32)

        # Patch lancedb so the table lookup path actually reaches asyncio.to_thread
        mock_tbl = MagicMock()
        mock_tbl.search.return_value.limit.return_value.to_list.return_value = []
        mock_db = MagicMock()
        mock_db.table_names.return_value = [_TABLE_NAME]
        mock_db.open_table.return_value = mock_tbl

        mock_provider_instance = MagicMock()
        mock_provider_instance.embed_single.return_value = fake_vec
        mock_provider_cls = MagicMock(return_value=mock_provider_instance)

        to_thread_calls: list = []

        async def _capture_to_thread(func, *args, **kwargs):
            to_thread_calls.append((func, args))
            return func(*args, **kwargs)

        with (
            patch("lancedb.connect", return_value=mock_db),
            patch(
                "backend.app.services.memory_initialization.asyncio.to_thread",
                side_effect=_capture_to_thread,
            ),
            patch(
                "backend.app.services.memory_initialization.EmbeddingProvider",
                mock_provider_cls,
                create=True,
            ),
        ):
            # Also patch the lazy import inside the function
            import sys
            import types

            fake_vs_module = types.ModuleType("backend.app.services.vector_store")
            fake_vs_module.EmbeddingProvider = mock_provider_cls  # type: ignore[attr-defined]
            with patch.dict(sys.modules, {"backend.app.services.vector_store": fake_vs_module}):
                result = await svc._semantic_search_world_context(_GRAPH_ID, "test query", None)

        assert len(to_thread_calls) >= 1, "asyncio.to_thread must be called at least once for embedding"
        # Verify the function passed to to_thread is embed_single.
        # When a MagicMock method is passed, its repr/name contains "embed_single".
        called_funcs = [call[0] for call in to_thread_calls]
        assert any("embed_single" in (getattr(f, "__name__", "") or repr(f)) for f in called_funcs), (
            f"embed_single not found among to_thread calls: {called_funcs}"
        )


# ---------------------------------------------------------------------------
# MemoryInitializationService._embed_world_context
# ---------------------------------------------------------------------------


class TestEmbedWorldContextUsesThread:
    """_embed_world_context must wrap embed (batch) in asyncio.to_thread."""

    @pytest.mark.asyncio
    async def test_batch_embed_offloaded_to_thread(self):
        """asyncio.to_thread must be called for the batch embed step."""
        import sys
        import types

        from backend.app.services.memory_initialization import MemoryInitializationService

        _GRAPH_ID = "test_graph_id_0123456789ab"

        svc = MemoryInitializationService.__new__(MemoryInitializationService)
        svc._lancedb_path = "/nonexistent/path"

        entries = [
            {
                "db_id": 1,
                "content": "World context entry one.",
                "context_type": "background",
                "title": "Entry 1",
                "severity": "low",
                "phase": "initial",
            },
            {
                "db_id": 2,
                "content": "World context entry two.",
                "context_type": "background",
                "title": "Entry 2",
                "severity": "medium",
                "phase": "initial",
            },
        ]

        fake_vectors = np.zeros((len(entries), 384), dtype=np.float32)

        mock_provider_instance = MagicMock()
        mock_provider_instance.embed.return_value = fake_vectors
        mock_provider_cls = MagicMock(return_value=mock_provider_instance)

        mock_db = MagicMock()
        mock_db.table_names.return_value = []
        mock_db.create_table = MagicMock()

        # Stub out lancedb and pyarrow at the module level to avoid real I/O
        fake_lancedb = types.ModuleType("lancedb")
        fake_lancedb.connect = MagicMock(return_value=mock_db)  # type: ignore[attr-defined]

        fake_pa = types.ModuleType("pyarrow")

        fake_vs_module = types.ModuleType("backend.app.services.vector_store")
        fake_vs_module.EmbeddingProvider = mock_provider_cls  # type: ignore[attr-defined]

        to_thread_calls: list = []

        async def _capture_to_thread(func, *args, **kwargs):
            to_thread_calls.append((func, args))
            return func(*args, **kwargs)

        with (
            patch.dict(
                sys.modules,
                {
                    "lancedb": fake_lancedb,
                    "pyarrow": fake_pa,
                    "backend.app.services.vector_store": fake_vs_module,
                },
            ),
            patch(
                "backend.app.services.memory_initialization.asyncio.to_thread",
                side_effect=_capture_to_thread,
            ),
        ):
            await svc._embed_world_context(_GRAPH_ID, entries)

        assert len(to_thread_calls) >= 1, "asyncio.to_thread must be called at least once for batch embedding"
        # Verify the function passed to to_thread is the batch embed method.
        # When a MagicMock method is passed, its repr contains "embed".
        called_funcs = [call[0] for call in to_thread_calls]
        assert any("embed" in (getattr(f, "__name__", "") or repr(f)) for f in called_funcs), (
            f"embed not found among to_thread calls: {called_funcs}"
        )

    @pytest.mark.asyncio
    async def test_empty_entries_skips_embedding(self):
        """Empty entry list must return early without calling embed at all."""
        from backend.app.services.memory_initialization import MemoryInitializationService

        svc = MemoryInitializationService.__new__(MemoryInitializationService)
        svc._lancedb_path = "/nonexistent/path"

        to_thread_calls: list = []

        async def _capture_to_thread(func, *args, **kwargs):
            to_thread_calls.append((func, args))
            return func(*args, **kwargs)

        with patch(
            "backend.app.services.memory_initialization.asyncio.to_thread",
            side_effect=_capture_to_thread,
        ):
            await svc._embed_world_context("test_graph_id_0123456789ab", [])

        assert len(to_thread_calls) == 0, "No embedding calls expected for empty entry list"


# ---------------------------------------------------------------------------
# EmbeddingProvider.embed_single — unit-level sanity check
# ---------------------------------------------------------------------------


class TestEmbeddingProviderInterface:
    """EmbeddingProvider.embed_single must remain synchronous (called via to_thread)."""

    def test_embed_single_is_not_a_coroutine(self):
        """embed_single must be a plain sync function, not async."""
        from backend.app.services.embedding_provider import EmbeddingProvider

        provider = EmbeddingProvider.__new__(EmbeddingProvider)
        assert not asyncio.iscoroutinefunction(provider.embed_single), (
            "embed_single must remain synchronous — it is called via asyncio.to_thread"
        )

    def test_embed_is_not_a_coroutine(self):
        """embed (batch) must be a plain sync function, not async."""
        from backend.app.services.embedding_provider import EmbeddingProvider

        provider = EmbeddingProvider.__new__(EmbeddingProvider)
        assert not asyncio.iscoroutinefunction(provider.embed), (
            "embed must remain synchronous — it is called via asyncio.to_thread"
        )
