"""Tests for AES-256 encryption utilities."""
from __future__ import annotations

import os
import importlib

import pytest

# A valid 32-byte key encoded as base64url.
# Verify: base64.urlsafe_b64decode(_TEST_KEY) must yield exactly 32 bytes.
_TEST_KEY = "gkNGJWxQNDWqiEgajKGn1cDrE9B_xIlLyvD9d5KOOmU="


def _reload_encryption():
    """Force a fresh import of encryption module to pick up env changes."""
    import backend.app.utils.encryption as enc_mod
    importlib.reload(enc_mod)
    return enc_mod


def test_encrypt_decrypt_roundtrip():
    os.environ["DATA_ENCRYPTION_KEY"] = _TEST_KEY
    enc = _reload_encryption()

    original = "my-secret-api-key-12345"
    encrypted = enc.encrypt_value(original)
    assert encrypted != original
    decrypted = enc.decrypt_value(encrypted)
    assert decrypted == original


def test_encrypt_returns_different_ciphertext():
    """Fernet uses a fresh IV per call — same plaintext yields different ciphertexts."""
    os.environ["DATA_ENCRYPTION_KEY"] = _TEST_KEY
    enc = _reload_encryption()

    a = enc.encrypt_value("secret")
    b = enc.encrypt_value("secret")
    assert a != b


def test_missing_key_raises():
    os.environ.pop("DATA_ENCRYPTION_KEY", None)
    enc = _reload_encryption()

    with pytest.raises(RuntimeError, match="DATA_ENCRYPTION_KEY"):
        enc.encrypt_value("test")


def test_wrong_length_key_raises():
    # Only 16 bytes (128-bit), not 32
    import base64
    short_key = base64.urlsafe_b64encode(b"0123456789abcdef").decode()
    os.environ["DATA_ENCRYPTION_KEY"] = short_key
    enc = _reload_encryption()

    with pytest.raises(RuntimeError, match="32 bytes"):
        enc.encrypt_value("test")


def test_encrypt_unicode():
    os.environ["DATA_ENCRYPTION_KEY"] = _TEST_KEY
    enc = _reload_encryption()

    original = "機密資料：廣東話測試"
    encrypted = enc.encrypt_value(original)
    decrypted = enc.decrypt_value(encrypted)
    assert decrypted == original


def test_decrypt_tampered_token_raises():
    from cryptography.fernet import InvalidToken

    os.environ["DATA_ENCRYPTION_KEY"] = _TEST_KEY
    enc = _reload_encryption()

    with pytest.raises((InvalidToken, Exception)):
        enc.decrypt_value("not-a-valid-fernet-token")
