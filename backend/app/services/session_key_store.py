"""Encrypted per-session API key storage for BYOK (Bring Your Own Key).

Keys are encrypted at rest using Fernet symmetric encryption.
The encryption key is sourced from the SESSION_ENCRYPTION_KEY env var.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("session_key_store")


@dataclass(frozen=True)
class SessionKeyInfo:
    """Immutable container for a session's LLM key configuration."""

    api_key: str
    provider: str
    model: str
    base_url: str


def _get_fernet():
    """Lazy-load Fernet cipher from SESSION_ENCRYPTION_KEY or DATA_ENCRYPTION_KEY env var.

    In production (DEBUG != 'true'), raises RuntimeError when no key is configured
    rather than silently generating an ephemeral key that would lose all BYOK API
    keys on restart.
    """
    from cryptography.fernet import Fernet  # noqa: PLC0415

    key = os.environ.get("SESSION_ENCRYPTION_KEY") or os.environ.get("DATA_ENCRYPTION_KEY")
    if not key:
        debug_mode = os.environ.get("DEBUG", "false").lower() == "true"
        if not debug_mode:
            raise RuntimeError(
                "SESSION_ENCRYPTION_KEY or DATA_ENCRYPTION_KEY must be set in production. "
                "Generate with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
            )
        # Debug mode: ephemeral key with warning
        logger.warning(
            "No encryption key set — using ephemeral key (DEBUG mode). "
            "All BYOK API keys will be lost on restart."
        )
        key = Fernet.generate_key().decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


class SessionKeyStore:
    """Encrypted per-session API key storage."""

    async def store_key(
        self,
        session_id: str,
        api_key: str,
        provider: str,
        model: str = "",
        base_url: str = "",
    ) -> None:
        """Encrypt and store an API key for a session."""
        fernet = _get_fernet()
        encrypted = fernet.encrypt(api_key.encode("utf-8"))

        async with get_db() as db:
            await db.execute(
                """INSERT OR REPLACE INTO session_api_keys
                   (session_id, encrypted_key, provider, model, base_url)
                   VALUES (?, ?, ?, ?, ?)""",
                (session_id, encrypted, provider, model, base_url),
            )
            await db.commit()

        logger.info(
            "Stored BYOK key for session=%s provider=%s model=%s",
            session_id, provider, model,
        )

    async def retrieve_key(self, session_id: str) -> SessionKeyInfo | None:
        """Decrypt and return the API key for a session, or None."""
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT encrypted_key, provider, model, base_url "
                "FROM session_api_keys WHERE session_id = ?",
                (session_id,),
            )
            row = await cursor.fetchone()

        if row is None:
            return None

        fernet = _get_fernet()
        encrypted = row["encrypted_key"]
        if isinstance(encrypted, str):
            encrypted = encrypted.encode("utf-8")
        decrypted = fernet.decrypt(encrypted).decode("utf-8")

        return SessionKeyInfo(
            api_key=decrypted,
            provider=row["provider"],
            model=row["model"] or "",
            base_url=row["base_url"] or "",
        )

    async def delete_key(self, session_id: str) -> None:
        """Remove the stored key for a completed session."""
        async with get_db() as db:
            await db.execute(
                "DELETE FROM session_api_keys WHERE session_id = ?",
                (session_id,),
            )
            await db.commit()
        logger.info("Deleted BYOK key for session=%s", session_id)
