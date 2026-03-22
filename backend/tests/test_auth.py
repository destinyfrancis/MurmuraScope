"""Tests for the authentication system (Phase 4.8)."""

from __future__ import annotations

import pytest
import pytest_asyncio
from unittest.mock import patch

from backend.app.api.auth import (
    _create_access_token,
    _decode_token,
    _hash_password,
    _verify_password,
)


# ---------------------------------------------------------------------------
# Unit tests: password hashing
# ---------------------------------------------------------------------------


class TestPasswordHashing:
    def test_hash_and_verify(self):
        plain = "securepassword123"
        hashed = _hash_password(plain)
        assert hashed != plain
        assert _verify_password(plain, hashed) is True

    def test_wrong_password_fails(self):
        hashed = _hash_password("correct_password")
        assert _verify_password("wrong_password", hashed) is False

    def test_different_hashes_for_same_password(self):
        h1 = _hash_password("same_password")
        h2 = _hash_password("same_password")
        assert h1 != h2  # bcrypt uses random salt


# ---------------------------------------------------------------------------
# Unit tests: JWT tokens
# ---------------------------------------------------------------------------


class TestJWTTokens:
    def test_create_and_decode_token(self):
        user_id = "abc123"
        token = _create_access_token(user_id)
        decoded = _decode_token(token)
        assert decoded == user_id

    def test_invalid_token_raises(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _decode_token("not.a.valid.token")
        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# Integration tests: API endpoints
# ---------------------------------------------------------------------------


class TestRegisterEndpoint:
    @pytest.mark.asyncio
    async def test_register_success(self, test_client):
        resp = await test_client.post(
            "/api/auth/register",
            json={"email": "test@example.com", "password": "password123"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["email"] == "test@example.com"
        assert "token" in body["data"]
        assert "user_id" in body["data"]

    @pytest.mark.asyncio
    async def test_register_with_display_name(self, test_client):
        resp = await test_client.post(
            "/api/auth/register",
            json={
                "email": "named@example.com",
                "password": "password123",
                "display_name": "Test User",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["display_name"] == "Test User"

    @pytest.mark.asyncio
    async def test_register_duplicate_email(self, test_client):
        payload = {"email": "dupe@example.com", "password": "password123"}
        await test_client.post("/api/auth/register", json=payload)
        resp = await test_client.post("/api/auth/register", json=payload)
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_register_invalid_email(self, test_client):
        resp = await test_client.post(
            "/api/auth/register",
            json={"email": "not-an-email", "password": "password123"},
        )
        assert resp.status_code == 422  # Pydantic validation error

    @pytest.mark.asyncio
    async def test_register_short_password(self, test_client):
        resp = await test_client.post(
            "/api/auth/register",
            json={"email": "short@example.com", "password": "abc"},
        )
        assert resp.status_code == 422


class TestLoginEndpoint:
    @pytest.mark.asyncio
    async def test_login_success(self, test_client):
        # Register first
        await test_client.post(
            "/api/auth/register",
            json={"email": "login@example.com", "password": "password123"},
        )
        # Login
        resp = await test_client.post(
            "/api/auth/login",
            json={"email": "login@example.com", "password": "password123"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "token" in body["data"]

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, test_client):
        await test_client.post(
            "/api/auth/register",
            json={"email": "wrong@example.com", "password": "password123"},
        )
        resp = await test_client.post(
            "/api/auth/login",
            json={"email": "wrong@example.com", "password": "wrongpassword"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self, test_client):
        resp = await test_client.post(
            "/api/auth/login",
            json={"email": "ghost@example.com", "password": "password123"},
        )
        assert resp.status_code == 401


class TestMeEndpoint:
    @pytest.mark.asyncio
    async def test_me_with_valid_token(self, test_client):
        # Register to get a token
        reg_resp = await test_client.post(
            "/api/auth/register",
            json={"email": "me@example.com", "password": "password123"},
        )
        token = reg_resp.json()["data"]["token"]

        resp = await test_client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["email"] == "me@example.com"

    @pytest.mark.asyncio
    async def test_me_without_token(self, test_client):
        resp = await test_client.get("/api/auth/me")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_me_with_invalid_token(self, test_client):
        resp = await test_client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        assert resp.status_code == 401


class TestEmailNormalization:
    @pytest.mark.asyncio
    async def test_email_case_insensitive(self, test_client):
        await test_client.post(
            "/api/auth/register",
            json={"email": "CamelCase@Example.COM", "password": "password123"},
        )
        # Login with different case
        resp = await test_client.post(
            "/api/auth/login",
            json={"email": "camelcase@example.com", "password": "password123"},
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Unit tests: AUTH_SECRET_KEY configuration
# ---------------------------------------------------------------------------


class TestAuthSecretKeyConfiguration:
    @pytest.mark.unit
    def test_auth_secret_key_uses_env_when_set(self, monkeypatch):
        """AUTH_SECRET_KEY must use the env var value when set."""
        test_secret = "test-stable-secret-key-123456789abcdef"
        monkeypatch.setenv("AUTH_SECRET_KEY", test_secret)

        # Reload the auth module to pick up the new env var
        import importlib
        import backend.app.api.auth as auth_module
        importlib.reload(auth_module)

        assert auth_module.AUTH_SECRET_KEY == test_secret

    @pytest.mark.unit
    def test_auth_secret_key_warns_in_debug_mode_when_missing(self, monkeypatch, caplog):
        """In DEBUG mode, a warning is logged when AUTH_SECRET_KEY is missing."""
        monkeypatch.delenv("AUTH_SECRET_KEY", raising=False)
        monkeypatch.setenv("DEBUG", "true")

        import importlib
        import logging
        import backend.app.api.auth as auth_module

        with caplog.at_level(logging.WARNING, logger="api.auth"):
            importlib.reload(auth_module)

        assert any(
            "AUTH_SECRET_KEY env var not set" in record.message
            and "ephemeral secret" in record.message
            for record in caplog.records
        ), f"Expected warning not found in logs: {[r.message for r in caplog.records]}"

    @pytest.mark.unit
    def test_auth_secret_key_raises_in_production_when_missing(self, monkeypatch):
        """In production (DEBUG=false), missing AUTH_SECRET_KEY must raise SystemExit."""
        monkeypatch.delenv("AUTH_SECRET_KEY", raising=False)
        monkeypatch.setenv("DEBUG", "false")

        import importlib
        import backend.app.api.auth as auth_module

        with pytest.raises(SystemExit) as exc_info:
            importlib.reload(auth_module)

        assert "FATAL" in str(exc_info.value)
        assert "AUTH_SECRET_KEY" in str(exc_info.value)
