import os
import pytest
from unittest.mock import patch, MagicMock
from backend.app.utils.llm_client import (
    get_default_provider,
    get_agent_provider_model,
    get_agent_model,
    get_report_provider_model,
    _PROVIDERS
)
from backend.app.services import runtime_settings

@pytest.fixture(autouse=True)
def clear_runtime_settings():
    """Ensure runtime settings are clear before each test."""
    runtime_settings._store.clear()
    yield
    runtime_settings._store.clear()

def test_get_default_provider():
    # 1. Default fallback
    with patch.dict(os.environ, {}, clear=True):
        assert get_default_provider() == "openrouter"
    
    # 2. Env var priority
    with patch.dict(os.environ, {"LLM_PROVIDER": "google"}):
        assert get_default_provider() == "google"
    
    # 3. Runtime override priority
    runtime_settings.set_override("llm_provider", "anthropic")
    with patch.dict(os.environ, {"LLM_PROVIDER": "google"}):
        assert get_default_provider() == "anthropic"

def test_get_agent_provider_model():
    # 1. Fallback to default provider
    with patch.dict(os.environ, {"LLM_PROVIDER": "openai"}, clear=True):
        provider, model = get_agent_provider_model()
        assert provider == "openai"
        # Since openai isn't in _PROVIDERS in the same way as openrouter, it falls back to openrouter default in the code logic
        assert model == _PROVIDERS["openrouter"]["default_model"]

    # 2. Specific agent provider env var
    with patch.dict(os.environ, {"AGENT_LLM_PROVIDER": "google"}, clear=True):
        provider, model = get_agent_provider_model()
        assert provider == "google"
        assert model == _PROVIDERS["google"]["default_model"]

    # 3. Model override via runtime settings
    runtime_settings.set_override("agent_llm_model", "gpt-4o")
    runtime_settings.set_override("agent_llm_provider", "openai")
    provider, model = get_agent_provider_model()
    assert provider == "openai"
    assert model == "gpt-4o"

def test_get_agent_model_routing():
    # Configure strong and lite models
    runtime_settings.set_override("agent_llm_provider", "openrouter")
    runtime_settings.set_override("agent_llm_model", "anthropic/claude-3-opus")
    runtime_settings.set_override("agent_llm_model_lite", "anthropic/claude-3-haiku")

    # Stakeholder should get the strong model
    provider, model = get_agent_model(is_stakeholder=True)
    assert provider == "openrouter"
    assert model == "anthropic/claude-3-opus"

    # Background agent should get the lite model
    provider, model = get_agent_model(is_stakeholder=False)
    assert provider == "openrouter"
    assert model == "anthropic/claude-3-haiku"

    # If lite model is NOT set, fallback to main agent model
    runtime_settings.delete_override("agent_llm_model_lite")
    provider, model = get_agent_model(is_stakeholder=False)
    assert provider == "openrouter"
    assert model == "anthropic/claude-3-opus"

def test_get_report_provider_model():
    # 1. Basic report routing
    runtime_settings.set_override("llm_provider", "google")
    runtime_settings.set_override("report_llm_model", "gemini-1.5-pro")
    
    provider, model = get_report_provider_model()
    assert provider == "google"
    assert model == "gemini-1.5-pro"

    # 2. Google-specific env var fallback
    runtime_settings.delete_override("report_llm_model")
    with patch.dict(os.environ, {"GOOGLE_REPORT_MODEL": "gemini-test-env"}):
        provider, model = get_report_provider_model()
        assert provider == "google"
        assert model == "gemini-test-env"
