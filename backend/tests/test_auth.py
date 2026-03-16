"""Tests for the authentication system (Phase 4.8)."""

from __future__ import annotations

import pytest
import pytest_asyncio

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
