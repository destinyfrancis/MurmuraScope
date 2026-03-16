"""Thread-safe singleton embedding provider using sentence-transformers.

Lazily loads `paraphrase-multilingual-MiniLM-L12-v2` (384-dim) on first call.
Supports batch embedding for efficient bulk operations.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import numpy as np

from backend.app.utils.logger import get_logger

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = get_logger("embedding_provider")

_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
_EMBEDDING_DIM = 384

_lock = threading.Lock()
_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    """Return the singleton model, loading on first call (thread-safe)."""
    global _model  # noqa: PLW0603
    if _model is not None:
        return _model

    with _lock:
        # Double-check after acquiring lock
        if _model is not None:
            return _model

        from sentence_transformers import SentenceTransformer  # noqa: PLC0415

        logger.info("Loading embedding model %s …", _MODEL_NAME)
        _model = SentenceTransformer(_MODEL_NAME)
        logger.info("Embedding model loaded (dim=%d)", _EMBEDDING_DIM)
        return _model


class EmbeddingProvider:
    """Thin wrapper around the singleton sentence-transformers model."""

    model_name: str = _MODEL_NAME
    dim: int = _EMBEDDING_DIM

    def embed(self, texts: list[str]) -> np.ndarray:
        """Encode *texts* into a (N, 384) float32 numpy array.

        Args:
            texts: List of strings to embed.

        Returns:
            2-D numpy array of shape ``(len(texts), 384)``.

        Raises:
            RuntimeError: If the model fails to load.
        """
        if not texts:
            return np.empty((0, _EMBEDDING_DIM), dtype=np.float32)

        model = _get_model()
        embeddings: np.ndarray = model.encode(
            texts,
            batch_size=64,
            show_progress_bar=False,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return embeddings.astype(np.float32)

    def embed_single(self, text: str) -> np.ndarray:
        """Convenience: embed a single string → 1-D array of shape (384,)."""
        return self.embed([text])[0]
