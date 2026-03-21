"""Shared pytest fixtures for HKSimEngine test suite."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest
import pytest_asyncio

# Ensure project root is in sys.path for imports like 'from backend.app...'
_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Auto-marker: tag tests as "integration" if they use DB fixtures or
# belong to known integration/slow test modules.
# ---------------------------------------------------------------------------

_DB_FIXTURES = frozenset({"test_db", "test_db_path", "test_client"})

# Modules that do inline DB setup (not via shared fixtures)
_INTEGRATION_MODULES = frozenset({
    "test_simulation_integration",
    "test_e2e_dry_run",
    "test_domain_api",
    "test_report",
    "test_data_integrity",
    "test_data_pipeline",
    "test_universal_engine_integration",
    "test_pipeline_verification",
})


@pytest.fixture(autouse=True)
def _disable_rate_limiter():
    """Globally disable slowapi rate limiter for all tests."""
    from backend.app.api.auth import _limiter as _auth_limiter
    prev = _auth_limiter.enabled
    _auth_limiter.enabled = False
    yield
    _auth_limiter.enabled = prev


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Auto-apply 'integration' marker to tests that use DB or are in known modules."""
    integration_marker = pytest.mark.integration
    for item in items:
        module_name = item.module.__name__.rsplit(".", 1)[-1] if item.module else ""
        uses_db = hasattr(item, "fixturenames") and _DB_FIXTURES & set(item.fixturenames)
        if uses_db or module_name in _INTEGRATION_MODULES:
            item.add_marker(integration_marker)


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def test_db_path(tmp_path):
    """Return a path to a temporary test database file."""
    return str(tmp_path / "test.db")


@pytest_asyncio.fixture()
async def test_db(test_db_path) -> AsyncIterator[aiosqlite.Connection]:
    """Initialise a test database with the project schema and yield the connection.

    The connection is closed automatically after the test completes.
    """
    schema_path = os.path.join(
        os.path.dirname(__file__), "..", "database", "schema.sql"
    )

    db = await aiosqlite.connect(test_db_path)
    db.row_factory = aiosqlite.Row

    with open(schema_path, encoding="utf-8") as f:
        await db.executescript(f.read())
    await db.commit()

    yield db

    await db.close()


# ---------------------------------------------------------------------------
# FastAPI test client
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def test_client(tmp_path):
    """Provide an async HTTPX test client bound to the FastAPI app.

    Uses a file-based temporary SQLite database pre-initialised with the
    project schema so that all tables exist (unlike :memory: which is
    per-connection and loses state between the init_db call and the test).
    """
    from httpx import ASGITransport, AsyncClient

    test_db_file = str(tmp_path / "test_api.db")

    # Disable rate limiting for this test to prevent in-memory counter
    # accumulation across test invocations sharing the same _limiter instance.
    from backend.app.api.auth import _limiter as _auth_limiter
    _auth_limiter.enabled = False
    try:
        with patch.dict(os.environ, {"DATABASE_PATH": test_db_file, "DEBUG": "false"}):
            # Force settings to reload with patched env
            import backend.app.config as config_mod

            fresh_settings = config_mod.Settings()
            with patch.object(config_mod, "_settings", fresh_settings):
                # Pre-initialise schema so tables exist when the app starts
                schema_path = os.path.join(
                    os.path.dirname(__file__), "..", "database", "schema.sql"
                )
                async with aiosqlite.connect(test_db_file) as db:
                    with open(schema_path, encoding="utf-8") as f:
                        await db.executescript(f.read())
                    await db.commit()

                from backend.app import create_app

                app = create_app()
                transport = ASGITransport(app=app)

                async with AsyncClient(
                    transport=transport,
                    base_url="http://testserver",
                ) as client:
                    yield client
    finally:
        _auth_limiter.enabled = True


# ---------------------------------------------------------------------------
# LLM mock fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_llm_response():
    """Return a factory that creates mock LLMResponse objects."""
    from backend.app.utils.llm_client import LLMResponse

    def _factory(
        content: str = "Mock LLM response",
        model: str = "test-model",
        prompt_tokens: int = 100,
        completion_tokens: int = 50,
        cost_usd: float = 0.001,
    ) -> LLMResponse:
        return LLMResponse(
            content=content,
            model=model,
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            cost_usd=cost_usd,
        )

    return _factory


@pytest.fixture()
def mock_llm_client(mock_llm_response):
    """Return a mocked LLMClient whose chat() returns a fixed response."""
    from backend.app.utils.llm_client import LLMClient

    client = MagicMock(spec=LLMClient)
    client.chat = AsyncMock(return_value=mock_llm_response())
    client.chat_json = AsyncMock(return_value={"result": "mock"})
    return client


# ---------------------------------------------------------------------------
# HTTPX mock for external API calls
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_httpx_client():
    """Return a mock httpx.AsyncClient for testing HTTP downloaders."""
    client = AsyncMock()
    return client


# ---------------------------------------------------------------------------
# Sample data fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_census_csv():
    """Return sample census CSV content for testing parsers."""
    return (
        "Year,Age Group,Sex,Population\n"
        "2021,0-4,Male,\"123,456\"\n"
        "2021,0-4,Female,\"118,234\"\n"
        "2021,5-9,Male,\"130,000\"\n"
        "2021,5-9,Female,\"125,500\"\n"
        "2021,10-14,Male,\"140,200\"\n"
        "2021,10-14,Female,\"135,800\"\n"
    )


@pytest.fixture()
def sample_hkma_response():
    """Return sample HKMA API response for testing economy downloaders."""
    return {
        "header": {"success": True},
        "result": {
            "datasize": 3,
            "records": [
                {
                    "end_of_month": "2024-01",
                    "ir_overnight": "4.50",
                    "ir_1w": "4.55",
                    "ir_1m": "4.60",
                    "ir_3m": "4.70",
                    "ir_6m": "4.80",
                    "ir_12m": "4.90",
                },
                {
                    "end_of_month": "2024-02",
                    "ir_overnight": "4.45",
                    "ir_1w": "4.50",
                    "ir_1m": "4.55",
                    "ir_3m": "4.65",
                    "ir_6m": "4.75",
                    "ir_12m": "4.85",
                },
                {
                    "end_of_month": "2024-03",
                    "ir_overnight": "4.40",
                    "ir_1w": "4.48",
                    "ir_1m": "4.52",
                    "ir_3m": "4.62",
                    "ir_6m": "4.72",
                    "ir_12m": "4.82",
                },
            ],
        },
    }


@pytest.fixture()
def sample_session_request():
    """Return a sample simulation session creation request."""
    return {
        "graph_id": "test-graph-001",
        "scenario_type": "property",
        "agent_count": 10,
        "round_count": 5,
        "platforms": {"twitter": True, "reddit": False},
        "llm_provider": "deepseek",
        "shocks": [
            {
                "round_number": 3,
                "shock_type": "interest_rate_hike",
                "description": "HKMA raises base rate by 25bps",
                "parameters": {"delta_bps": 25},
            }
        ],
    }
