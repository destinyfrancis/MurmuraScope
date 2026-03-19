import pytest


def test_get_default_client_returns_same_instance():
    from backend.app.utils.llm_client import get_default_client
    c1 = get_default_client()
    c2 = get_default_client()
    assert c1 is c2, "get_default_client() must return the same instance each call"


def test_get_default_client_is_llm_client():
    from backend.app.utils.llm_client import get_default_client, LLMClient
    assert isinstance(get_default_client(), LLMClient)
