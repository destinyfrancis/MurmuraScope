"""AES-256 encryption for sensitive values at rest.

Uses Fernet symmetric encryption (AES-128-CBC with HMAC-SHA256 authentication).
The key must be exactly 32 bytes, base64url-encoded, stored in the
``DATA_ENCRYPTION_KEY`` environment variable.

Usage::

    from backend.app.utils.encryption import encrypt_value, decrypt_value

    ciphertext = encrypt_value("my-secret")
    plaintext  = decrypt_value(ciphertext)

Security notes:
  - Fernet generates a fresh random IV per call, so identical plaintexts
    produce different ciphertexts (prevents frequency analysis).
  - ``DATA_ENCRYPTION_KEY`` must never be committed to source control.
  - Use ``python -c "import secrets, base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"``
    to generate a valid 32-byte key.
"""

from __future__ import annotations

import base64
import os

from cryptography.fernet import Fernet


def _get_key() -> bytes:
    """Derive the Fernet key from the ``DATA_ENCRYPTION_KEY`` env var.

    Raises:
        RuntimeError: If the env var is missing or not exactly 32 bytes.
    """
    raw = os.environ.get("DATA_ENCRYPTION_KEY", "")
    if not raw:
        raise RuntimeError("DATA_ENCRYPTION_KEY env var is required for data connector")
    try:
        key_bytes = base64.urlsafe_b64decode(raw + "==")  # pad for safety
    except Exception as exc:
        raise RuntimeError("DATA_ENCRYPTION_KEY must be base64url-encoded") from exc
    if len(key_bytes) != 32:
        raise RuntimeError(f"DATA_ENCRYPTION_KEY must decode to exactly 32 bytes (got {len(key_bytes)})")
    # Fernet requires the key to be 32-byte base64url-encoded
    return base64.urlsafe_b64encode(key_bytes)


def encrypt_value(plaintext: str) -> str:
    """Encrypt *plaintext* with AES-256 Fernet.

    Args:
        plaintext: UTF-8 string to encrypt.

    Returns:
        URL-safe base64-encoded ciphertext string.
    """
    f = Fernet(_get_key())
    return f.encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    """Decrypt a Fernet-encrypted ciphertext.

    Args:
        ciphertext: URL-safe base64-encoded ciphertext produced by
            :func:`encrypt_value`.

    Returns:
        Original plaintext string.

    Raises:
        cryptography.fernet.InvalidToken: If the token is tampered or expired.
    """
    f = Fernet(_get_key())
    return f.decrypt(ciphertext.encode()).decode()
