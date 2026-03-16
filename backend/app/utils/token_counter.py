"""Lightweight token counter using tiktoken cl100k_base encoding."""

from __future__ import annotations

import tiktoken


class TokenCounter:
    """Count and truncate tokens using cl100k_base (GPT-4/DeepSeek compatible)."""

    _enc: tiktoken.Encoding | None = None

    @classmethod
    def _get_encoder(cls) -> tiktoken.Encoding:
        if cls._enc is None:
            cls._enc = tiktoken.get_encoding("cl100k_base")
        return cls._enc

    @classmethod
    def count(cls, text: str) -> int:
        """Count tokens in text."""
        if not text:
            return 0
        return len(cls._get_encoder().encode(text))

    @classmethod
    def truncate(cls, text: str, max_tokens: int) -> str:
        """Truncate text to max_tokens, preserving whole tokens."""
        if not text or max_tokens <= 0:
            return ""
        tokens = cls._get_encoder().encode(text)
        if len(tokens) <= max_tokens:
            return text
        return cls._get_encoder().decode(tokens[:max_tokens])
