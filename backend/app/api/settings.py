"""Settings API — GET/PUT /api/settings, POST /api/settings/test-key.

Architecture:
  GET  /api/settings         — 返回所有設定（API keys masked）
  PUT  /api/settings         — 更新設定，寫 DB + 更新 RuntimeSettingsStore
  POST /api/settings/test-key — 測試 API key 有效性

API keys 的優先級：
  RuntimeSettingsStore (DB) > .env
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.services.runtime_settings import get_all, get_override, set_override
from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

router = APIRouter(prefix="/settings", tags=["settings"])
logger = get_logger("api.settings")


# ---------------------------------------------------------------------------
# Constants — known API key env var names per provider
# ---------------------------------------------------------------------------

_PROVIDER_ENV_KEYS: dict[str, str] = {
    "openrouter": "OPENROUTER_API_KEY",
    "google": "GOOGLE_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
}

_SETTINGS_KEY_MAP: dict[str, str] = {
    # llm
    "agent_provider": "agent_llm_provider",
    "agent_model": "agent_llm_model",
    "agent_model_lite": "agent_llm_model_lite",
    "report_provider": "llm_provider",
    "report_model": "report_llm_model",
    # api keys
    "openrouter_key": "api_key_openrouter",
    "google_key": "api_key_google",
    "openai_key": "api_key_openai",
    "anthropic_key": "api_key_anthropic",
    "deepseek_key": "api_key_deepseek",
    "fireworks_key": "api_key_fireworks",
    # simulation
    "default_preset": "sim_default_preset",
    "concurrency_limit": "sim_concurrency_limit",
    "default_agent_count": "sim_default_agent_count",
    "default_domain": "sim_default_domain",
    # data
    "fred_api_key": "api_key_fred",
    "external_feed_enabled": "data_external_feed_enabled",
    "feed_refresh_interval": "data_feed_refresh_interval",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mask_key(key: str) -> str:
    """Mask an API key — show only last 4 chars: sk-or-***abc1."""
    if not key:
        return ""
    if len(key) <= 4:
        return "***"
    prefix_part = key[:6] if len(key) > 10 else ""
    suffix = key[-4:]
    if prefix_part:
        return f"{prefix_part}***{suffix}"
    return f"***{suffix}"


def _get_env_key(provider: str) -> str:
    """Return the API key for a provider from RuntimeStore → .env fallback."""
    store_key = f"api_key_{provider}"
    override = get_override(store_key)
    if override:
        return override
    env_var = _PROVIDER_ENV_KEYS.get(provider, "")
    return os.environ.get(env_var, "") if env_var else ""


def _read_setting(key: str, env_fallback_var: str = "", default: str = "") -> str:
    """Read from RuntimeStore first, then env var, then default."""
    override = get_override(key)
    if override is not None:
        return override
    if env_fallback_var:
        return os.environ.get(env_fallback_var, default)
    return default


# ---------------------------------------------------------------------------
# Response shape builder
# ---------------------------------------------------------------------------


def _build_settings_response(mask_keys: bool = True) -> dict[str, Any]:
    """Build the canonical settings response dict."""
    openrouter_key = _get_env_key("openrouter")
    google_key = _get_env_key("google")
    openai_key = _get_env_key("openai")
    anthropic_key = _get_env_key("anthropic")
    deepseek_key = _get_env_key("deepseek")
    fireworks_key = _get_env_key("fireworks")
    fred_key = _read_setting("api_key_fred", "FRED_API_KEY")

    def maybe_mask(k: str) -> str:
        return _mask_key(k) if mask_keys else k

    return {
        "llm": {
            "agent_provider": _read_setting("agent_llm_provider", "AGENT_LLM_PROVIDER", "openrouter"),
            "agent_model": _read_setting("agent_llm_model", "AGENT_LLM_MODEL", ""),
            "agent_model_lite": _read_setting("agent_llm_model_lite", "AGENT_LLM_MODEL_LITE", ""),
            "report_provider": _read_setting("llm_provider", "LLM_PROVIDER", "openrouter"),
            "report_model": _read_setting("report_llm_model", "GOOGLE_REPORT_MODEL", ""),
        },
        "api_keys": {
            "openrouter": maybe_mask(openrouter_key),
            "google": maybe_mask(google_key),
            "openai": maybe_mask(openai_key),
            "anthropic": maybe_mask(anthropic_key),
            "deepseek": maybe_mask(deepseek_key),
            "fireworks": maybe_mask(fireworks_key),
        },
        "simulation": {
            "default_preset": _read_setting("sim_default_preset", "", "standard"),
            "concurrency_limit": int(_read_setting("sim_concurrency_limit", "", "50")),
            "default_agent_count": int(_read_setting("sim_default_agent_count", "", "50")),
            "default_domain": _read_setting("sim_default_domain", "", "hk_city"),
        },
        "data": {
            "fred_api_key": maybe_mask(fred_key),
            "external_feed_enabled": _read_setting("data_external_feed_enabled", "EXTERNAL_FEED_ENABLED", "false") == "true",
            "feed_refresh_interval": int(_read_setting("data_feed_refresh_interval", "", "3600")),
        },
    }


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class SettingsUpdateRequest(BaseModel):
    """Body for PUT /api/settings.

    Any subset of keys may be provided; unspecified keys are untouched.
    """

    # LLM config
    agent_provider: str | None = None
    agent_model: str | None = None
    agent_model_lite: str | None = None
    report_provider: str | None = None
    report_model: str | None = None

    # API keys (plain text; we mask on read)
    openrouter_key: str | None = None
    google_key: str | None = None
    openai_key: str | None = None
    anthropic_key: str | None = None
    deepseek_key: str | None = None
    fireworks_key: str | None = None
    fred_api_key: str | None = None

    # Simulation
    default_preset: str | None = None
    concurrency_limit: int | None = None
    default_agent_count: int | None = None
    default_domain: str | None = None

    # Data feed
    external_feed_enabled: bool | None = None
    feed_refresh_interval: int | None = None


class TestKeyRequest(BaseModel):
    provider: str
    api_key: str


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _persist_to_db(key: str, value: str) -> None:
    """Upsert a single setting into app_settings."""
    async with get_db() as db:
        await db.execute(
            """INSERT INTO app_settings (key, value, updated_at)
               VALUES (?, ?, datetime('now'))
               ON CONFLICT(key) DO UPDATE SET
                   value = excluded.value,
                   updated_at = excluded.updated_at""",
            (key, value),
        )
        await db.commit()


async def _apply_update(field: str, value: Any) -> None:
    """Map a request field → store key, persist to DB and update in-memory store."""
    store_key = _SETTINGS_KEY_MAP.get(field)
    if store_key is None:
        logger.warning("No store key mapping for field '%s'; skipping", field)
        return
    str_value = str(value) if not isinstance(value, bool) else ("true" if value else "false")
    set_override(store_key, str_value)
    await _persist_to_db(store_key, str_value)
    logger.info("Settings: updated %s → %s", store_key, "***" if "key" in store_key else str_value)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("")
async def get_settings() -> dict[str, Any]:
    """Return all current settings with API keys masked."""
    return _build_settings_response(mask_keys=True)


@router.put("")
async def update_settings(req: SettingsUpdateRequest) -> dict[str, Any]:
    """Update one or more settings.  Writes to DB + RuntimeSettingsStore immediately."""
    updated: list[str] = []

    # Iterate over set fields only
    for field, value in req.model_dump(exclude_none=True).items():
        await _apply_update(field, value)
        updated.append(field)

    logger.info("Settings updated: %s", updated)
    return {"success": True, "updated": updated, "settings": _build_settings_response(mask_keys=True)}


@router.post("/test-key")
async def test_api_key(req: TestKeyRequest) -> dict[str, Any]:
    """Test whether an API key is valid by pinging the provider."""
    provider = req.provider.lower()
    api_key = req.api_key.strip()

    if not api_key:
        raise HTTPException(status_code=400, detail="api_key is required")

    try:
        result = await _test_provider_key(provider, api_key)
        return {"success": result["ok"], "provider": provider, "message": result["message"]}
    except Exception as exc:
        logger.warning("test-key failed for %s: %s", provider, exc)
        return {"success": False, "provider": provider, "message": str(exc)}


async def _test_provider_key(provider: str, api_key: str) -> dict[str, Any]:
    """Send a minimal request to validate the API key."""
    timeout = httpx.Timeout(10.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        if provider == "openrouter":
            resp = await client.get(
                "https://openrouter.ai/api/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if resp.status_code == 200:
                return {"ok": True, "message": "OpenRouter key valid ✓"}
            return {"ok": False, "message": f"OpenRouter returned HTTP {resp.status_code}"}

        elif provider == "google":
            resp = await client.get(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
            )
            if resp.status_code == 200:
                return {"ok": True, "message": "Google API key valid ✓"}
            return {"ok": False, "message": f"Google returned HTTP {resp.status_code}"}

        elif provider == "openai":
            resp = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if resp.status_code == 200:
                return {"ok": True, "message": "OpenAI key valid ✓"}
            return {"ok": False, "message": f"OpenAI returned HTTP {resp.status_code}"}

        elif provider == "anthropic":
            # Anthropic requires a POST; use a minimal ping
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5",
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
            # 200 or 400 (bad request but authenticated) both confirm the key works
            if resp.status_code in (200, 400):
                return {"ok": True, "message": "Anthropic key valid ✓"}
            if resp.status_code == 401:
                return {"ok": False, "message": "Anthropic: invalid API key"}
            return {"ok": False, "message": f"Anthropic returned HTTP {resp.status_code}"}

        elif provider == "deepseek":
            resp = await client.get(
                "https://api.deepseek.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if resp.status_code == 200:
                return {"ok": True, "message": "DeepSeek key valid ✓"}
            return {"ok": False, "message": f"DeepSeek returned HTTP {resp.status_code}"}

        elif provider in ("fred", "data"):
            resp = await client.get(
                f"https://api.stlouisfed.org/fred/series?series_id=GNPCA&api_key={api_key}&file_type=json"
            )
            if resp.status_code == 200:
                return {"ok": True, "message": "FRED API key valid ✓"}
            return {"ok": False, "message": f"FRED returned HTTP {resp.status_code}"}

        else:
            return {"ok": False, "message": f"Unknown provider '{provider}' — cannot test"}
