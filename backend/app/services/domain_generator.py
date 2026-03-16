"""Generate domain packs from natural language descriptions via LLM.

The DomainGenerator calls the LLM twice at most:
  1. First attempt with the standard generation prompt.
  2. Retry once with a stricter prompt if the first attempt fails validation.

Raises ValueError if both attempts produce invalid output.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.app.models.domain import DraftDomainPack
from backend.prompts.domain_prompts import (
    DOMAIN_GENERATION_RETRY,
    DOMAIN_GENERATION_SYSTEM,
    DOMAIN_GENERATION_USER,
)

logger = logging.getLogger(__name__)


class DomainGenerator:
    """Generate DraftDomainPack instances from free-text domain descriptions.

    Args:
        llm_client: Any object with an async ``chat_json(messages)`` method.
                    In production this is ``LLMClient`` from llm_client.py.
                    Pass a mock in tests.
    """

    def __init__(self, llm_client: Any = None) -> None:
        self._llm = llm_client

    async def generate(self, description: str) -> DraftDomainPack:
        """Generate a validated DraftDomainPack from a domain description.

        Args:
            description: Free-text description of the simulation domain
                         (e.g. "Japan real estate market in Tokyo").

        Returns:
            A validated, immutable DraftDomainPack with source="generated".

        Raises:
            ValueError: If both LLM attempts fail to produce valid output.
        """
        messages = self._build_messages(DOMAIN_GENERATION_SYSTEM, DOMAIN_GENERATION_USER, description)
        raw = await self._llm.chat_json(messages)

        pack = self._try_parse(raw)
        if pack is not None:
            return pack

        logger.warning("First domain generation attempt failed, retrying")
        retry_messages = self._build_messages(DOMAIN_GENERATION_SYSTEM, DOMAIN_GENERATION_RETRY, description)
        raw = await self._llm.chat_json(retry_messages)

        pack = self._try_parse(raw)
        if pack is not None:
            return pack

        raise ValueError(
            "Failed to generate valid domain pack after 2 attempts. "
            "Please fill in the missing fields manually."
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_messages(system: str, user_template: str, description: str) -> list[dict[str, str]]:
        """Build an OpenAI-style messages list for the LLM call."""
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user_template.format(description=description)},
        ]

    @staticmethod
    def _try_parse(raw: dict[str, Any]) -> DraftDomainPack | None:
        """Attempt to construct a DraftDomainPack from raw LLM output.

        Returns None on any failure so the caller can retry.
        """
        if not raw or "regions" not in raw:
            return None
        try:
            raw.setdefault("source", "generated")
            return DraftDomainPack(**raw)
        except Exception:
            return None
