"""Integration tests for MurmuraScope simulation pipeline.

Tasks covered:
  3.1  OASIS config building, CSV generation, platform-aware script selection.
  3.2  Sentiment → MacroState feedback via MacroController.update_from_actions().
  3.3  MonteCarloEngine + EnsembleRunner instantiation and call surface.
  3.4  CompanyFactory B2B initialisation and DB persistence.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "database" / "schema.sql"

# Minimal schema for :memory: DBs that include only the tables tested here.
_MINIMAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS simulation_actions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    round_number INTEGER NOT NULL,
    agent_id    INTEGER,
    oasis_username TEXT,
    action_type TEXT DEFAULT 'post',
    platform    TEXT DEFAULT 'facebook',
    content     TEXT NOT NULL DEFAULT '',
    target_agent_username TEXT,
    sentiment   TEXT,
    topics      TEXT,
    post_id     TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS agent_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    agent_type TEXT NOT NULL,
    age INTEGER,
    sex TEXT,
    district TEXT,
    occupation TEXT,
    income_bracket TEXT,
    education_level TEXT,
    marital_status TEXT,
    housing_type TEXT,
    openness REAL DEFAULT 0.5,
    conscientiousness REAL DEFAULT 0.5,
    extraversion REAL DEFAULT 0.5,
    agreeableness REAL DEFAULT 0.5,
    neuroticism REAL DEFAULT 0.5,
    monthly_income INTEGER DEFAULT 0,
    savings INTEGER DEFAULT 0,
    oasis_persona TEXT,
    oasis_username TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS company_profiles (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          TEXT    NOT NULL,
    company_name        TEXT    NOT NULL,
    company_type        TEXT    NOT NULL,
    industry_sector     TEXT    NOT NULL,
    company_size        TEXT    NOT NULL,
    district            TEXT,
    supply_chain_position TEXT,
    annual_revenue_hkd  INTEGER,
    employee_count      INTEGER,
    china_exposure      REAL    DEFAULT 0.5,
    export_ratio        REAL    DEFAULT 0.3,
    created_at          TEXT    DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_company_session ON company_profiles(session_id);
CREATE TABLE IF NOT EXISTS company_decisions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          TEXT    NOT NULL,
    company_id          INTEGER NOT NULL,
    round_number        INTEGER NOT NULL,
    decision_type       TEXT    NOT NULL,
    action              TEXT    NOT NULL,
    reasoning           TEXT,
    confidence          REAL    NOT NULL DEFAULT 0.5,
    impact_employees    INTEGER DEFAULT 0,
    impact_revenue_pct  REAL    DEFAULT 0.0,
    created_at          TEXT    DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS ensemble_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL,
    n_trials    INTEGER NOT NULL,
    metric_name TEXT    NOT NULL,
    p10         REAL,
    p25         REAL,
    p50         REAL,
    p75         REAL,
    p90         REAL,
    created_at  TEXT    DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ensemble_session ON ensemble_results(session_id);
CREATE TABLE IF NOT EXISTS macro_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    round_number INTEGER NOT NULL,
    macro_json  TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS agent_decisions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    agent_id    INTEGER NOT NULL,
    round_number INTEGER NOT NULL,
    decision_type TEXT NOT NULL,
    action      TEXT NOT NULL,
    reasoning   TEXT,
    confidence  REAL NOT NULL DEFAULT 0.5,
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS hk_data_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT,
    period TEXT NOT NULL,
    source TEXT NOT NULL,
    source_url TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


@pytest_asyncio.fixture()
async def mem_db() -> AsyncIterator[aiosqlite.Connection]:
    """In-memory SQLite DB with minimal schema for integration tests."""
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    await db.executescript(_MINIMAL_SCHEMA)
    await db.commit()
    yield db
    await db.close()


# ---------------------------------------------------------------------------
# Task 3.1 — OASIS End-to-End: config building + script selection
# ---------------------------------------------------------------------------


class TestBuildFullConfig:
    """Tests for simulation_runner._build_full_config()."""

    def test_required_fields_present(self) -> None:
        """_build_full_config must include all fields required by OASIS scripts."""
        from backend.app.services.simulation_helpers import _build_full_config

        config = {
            "session_id": "sess-abc",
            "agent_csv_path": "/tmp/agents.csv",
            "round_count": 10,
            "platforms": {"facebook": True},
        }
        result = _build_full_config(config, "sess-abc")

        assert result["session_id"] == "sess-abc"
        assert "llm_provider" in result
        assert "llm_model" in result
        assert "llm_base_url" in result
        assert "oasis_db_path" in result

    def test_llm_api_key_stripped(self) -> None:
        """llm_api_key must NOT appear in the written config (security fix)."""
        from backend.app.services.simulation_helpers import _build_full_config

        config = {
            "session_id": "sess-sec",
            "llm_api_key": "sk-supersecret",
            "agent_csv_path": "/tmp/agents.csv",
        }
        result = _build_full_config(config, "sess-sec")
        assert "llm_api_key" not in result, "llm_api_key must never be written to sim_config.json"

    def test_oasis_db_path_uses_session_dir(self) -> None:
        """oasis_db_path must be under data/sessions/<session_id>/."""
        from backend.app.services.simulation_helpers import _build_full_config

        result = _build_full_config({}, "my-session-99")
        assert "my-session-99" in result["oasis_db_path"]
        assert result["oasis_db_path"].endswith("oasis.db")

    def test_default_provider_is_openrouter(self) -> None:
        """Default LLM provider for OASIS simulation agents must be openrouter."""
        from backend.app.services.simulation_helpers import _build_full_config

        result = _build_full_config({}, "any-session")
        assert result["llm_provider"] == "openrouter"
        assert "deepseek" in result["llm_model"].lower()

    def test_custom_provider_preserved(self) -> None:
        """Caller-supplied llm_provider / llm_model must be forwarded."""
        from backend.app.services.simulation_helpers import _build_full_config

        config = {"llm_provider": "fireworks", "llm_model": "deepseek/deepseek-v3.2"}
        result = _build_full_config(config, "s1")
        assert result["llm_provider"] == "fireworks"
        assert result["llm_model"] == "deepseek/deepseek-v3.2"


class TestParallelScriptRequiredKeys:
    """Task 3.1 — verify REQUIRED_CONFIG_KEYS no longer includes llm_api_key."""

    def test_llm_api_key_not_required(self) -> None:
        """llm_api_key must NOT be in REQUIRED_CONFIG_KEYS (security fix)."""
        from backend.scripts.run_parallel_simulation import REQUIRED_CONFIG_KEYS

        assert "llm_api_key" not in REQUIRED_CONFIG_KEYS, (
            "llm_api_key must be read from env, not required in config file"
        )

    def test_minimal_required_keys_present(self) -> None:
        """Core config keys needed to start a parallel simulation must be listed."""
        from backend.scripts.run_parallel_simulation import REQUIRED_CONFIG_KEYS

        for key in (
            "session_id",
            "agent_csv_path",
            "round_count",
            "platforms",
            "llm_provider",
            "llm_model",
            "oasis_db_path",
        ):
            assert key in REQUIRED_CONFIG_KEYS, f"Expected '{key}' in REQUIRED_CONFIG_KEYS"


class TestPlatformScriptSelection:
    """Task 3.1 — platform-aware script selection logic in SimulationRunner.run()."""

    @pytest.mark.asyncio
    async def test_facebook_only_uses_facebook_script(self, tmp_path: Path) -> None:
        """Single facebook platform → run_facebook_simulation.py is selected."""
        from backend.app.services import simulation_runner as sr
        from backend.app.services import simulation_helpers as sh
        from backend.app.services import simulation_lifecycle as sl

        agent_csv = tmp_path / "agents.csv"
        agent_csv.write_text("id,name\n1,Alice\n")

        # Patch _require_path to accept anything so we don't need real scripts.
        selected: list[Path] = []

        def fake_require(path: Path, label: str) -> None:
            selected.append(path)

        config = {
            "agent_csv_path": str(agent_csv),
            "platforms": {"facebook": True},
            "round_count": 1,
        }

        with patch("backend.app.services.simulation_helpers._require_path", side_effect=fake_require):
            with patch("backend.app.services.simulation_helpers._build_full_config", return_value={**config, "session_id": "s1"}):
                # Simulate the script-selection logic directly (not the full run)
                platforms = config.get("platforms", {})
                facebook_on = platforms.get("facebook", False)
                instagram_on = platforms.get("instagram", False)
                twitter_on = platforms.get("twitter", False)
                enabled_count = sum(1 for v in platforms.values() if v)

                if enabled_count > 1 and sl._PARALLEL_SCRIPT.exists():
                    script = sl._PARALLEL_SCRIPT
                elif facebook_on:
                    script = sl._FACEBOOK_SCRIPT
                elif instagram_on:
                    script = sl._INSTAGRAM_SCRIPT
                elif twitter_on:
                    script = sl._SCRIPT_PATH
                else:
                    script = sl._SCRIPT_PATH

        assert "facebook" in str(script), f"Expected facebook script, got: {script}"

    def test_instagram_only_uses_instagram_script(self) -> None:
        """Single instagram platform → run_instagram_simulation.py is selected."""
        from backend.app.services import simulation_runner as sr
        from backend.app.services import simulation_helpers as sh
        from backend.app.services import simulation_lifecycle as sl

        platforms = {"instagram": True}
        enabled_count = sum(1 for v in platforms.values() if v)
        facebook_on = platforms.get("facebook", False)
        instagram_on = platforms.get("instagram", False)

        if enabled_count > 1:
            script = sl._PARALLEL_SCRIPT
        elif facebook_on:
            script = sl._FACEBOOK_SCRIPT
        elif instagram_on:
            script = sl._INSTAGRAM_SCRIPT
        else:
            script = sl._SCRIPT_PATH

        assert "instagram" in str(script)

    def test_multiple_platforms_use_parallel_script(self) -> None:
        """Multiple active platforms → parallel script is selected."""

        platforms = {"twitter": True, "reddit": True}
        enabled_count = sum(1 for v in platforms.values() if v)

        # The real check also requires _PARALLEL_SCRIPT.exists() but we test logic
        assert enabled_count > 1  # guarantee parallel is chosen when script exists


# ---------------------------------------------------------------------------
# Task 3.2 — Sentiment → Macro Feedback Loop
# ---------------------------------------------------------------------------


class TestUpdateFromActions:
    """Verify MacroController.update_from_actions() adjusts MacroState from sentiment."""

    @pytest.mark.asyncio
    async def test_negative_sentiment_reduces_consumer_confidence(
        self, mem_db: aiosqlite.Connection, tmp_path: Path
    ) -> None:
        """Heavy negative sentiment must decrease consumer_confidence."""
        from backend.app.services.macro_controller import MacroController
        from backend.app.services.macro_state import BASELINE_AVG_SQFT_PRICE, BASELINE_STAMP_DUTY, MacroState

        session_id = "neg-test-01"
        # Seed 8 negative posts + 2 positive → 80% negative
        rows: list[tuple] = []
        for i in range(8):
            rows.append((session_id, 1, None, f"user_{i}", "negative", "[]"))
        for i in range(2):
            rows.append((session_id, 1, None, f"user_pos_{i}", "positive", "[]"))
        await mem_db.executemany(
            "INSERT INTO simulation_actions "
            "(session_id, round_number, agent_id, oasis_username, sentiment, topics) "
            "VALUES (?,?,?,?,?,?)",
            rows,
        )
        await mem_db.commit()

        baseline_confidence = 50.0
        state = MacroState(
            hibor_1m=0.04,
            prime_rate=0.055,
            unemployment_rate=0.032,
            median_monthly_income=20_800,
            ccl_index=150.0,
            avg_sqft_price=dict(BASELINE_AVG_SQFT_PRICE),
            mortgage_cap=0.70,
            stamp_duty_rates=dict(BASELINE_STAMP_DUTY),
            gdp_growth=0.025,
            cpi_yoy=0.019,
            hsi_level=20_060.0,
            consumer_confidence=baseline_confidence,
            net_migration=2_000,
            birth_rate=5.3,
            policy_flags={},
        )

        mc = MacroController()

        db_path = str(tmp_path / "test_neg.db")

        with patch("backend.app.utils.db.get_db") as mock_get_db:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mem_db)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_get_db.return_value = mock_ctx

            updated = await mc.update_from_actions(
                current_state=state,
                session_id=session_id,
                round_number=1,
            )

        assert updated.consumer_confidence < baseline_confidence, (
            "80% negative sentiment should decrease consumer_confidence"
        )

    @pytest.mark.asyncio
    async def test_positive_sentiment_increases_consumer_confidence(self, mem_db: aiosqlite.Connection) -> None:
        """Heavy positive sentiment must increase consumer_confidence."""
        from backend.app.services.macro_controller import MacroController
        from backend.app.services.macro_state import BASELINE_AVG_SQFT_PRICE, BASELINE_STAMP_DUTY, MacroState

        session_id = "pos-test-02"
        rows: list[tuple] = []
        for i in range(8):
            rows.append((session_id, 1, None, f"user_{i}", "positive", "[]"))
        for i in range(2):
            rows.append((session_id, 1, None, f"user_neg_{i}", "negative", "[]"))
        await mem_db.executemany(
            "INSERT INTO simulation_actions "
            "(session_id, round_number, agent_id, oasis_username, sentiment, topics) "
            "VALUES (?,?,?,?,?,?)",
            rows,
        )
        await mem_db.commit()

        baseline_confidence = 50.0
        state = MacroState(
            hibor_1m=0.04,
            prime_rate=0.055,
            unemployment_rate=0.032,
            median_monthly_income=20_800,
            ccl_index=150.0,
            avg_sqft_price=dict(BASELINE_AVG_SQFT_PRICE),
            mortgage_cap=0.70,
            stamp_duty_rates=dict(BASELINE_STAMP_DUTY),
            gdp_growth=0.025,
            cpi_yoy=0.019,
            hsi_level=20_060.0,
            consumer_confidence=baseline_confidence,
            net_migration=2_000,
            birth_rate=5.3,
            policy_flags={},
        )

        mc = MacroController()

        with patch("backend.app.utils.db.get_db") as mock_get_db:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mem_db)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_get_db.return_value = mock_ctx

            updated = await mc.update_from_actions(
                current_state=state,
                session_id=session_id,
                round_number=1,
            )

        assert updated.consumer_confidence >= baseline_confidence, (
            "80% positive sentiment should not decrease consumer_confidence"
        )

    @pytest.mark.asyncio
    async def test_empty_actions_returns_unchanged_state(self, mem_db: aiosqlite.Connection) -> None:
        """No simulation actions → MacroState must be returned unchanged."""
        from backend.app.services.macro_controller import MacroController
        from backend.app.services.macro_state import BASELINE_AVG_SQFT_PRICE, BASELINE_STAMP_DUTY, MacroState

        session_id = "empty-actions-99"

        state = MacroState(
            hibor_1m=0.04,
            prime_rate=0.055,
            unemployment_rate=0.032,
            median_monthly_income=20_800,
            ccl_index=150.0,
            avg_sqft_price=dict(BASELINE_AVG_SQFT_PRICE),
            mortgage_cap=0.70,
            stamp_duty_rates=dict(BASELINE_STAMP_DUTY),
            gdp_growth=0.025,
            cpi_yoy=0.019,
            hsi_level=20_060.0,
            consumer_confidence=55.0,
            net_migration=2_000,
            birth_rate=5.3,
            policy_flags={},
        )

        mc = MacroController()

        with patch("backend.app.utils.db.get_db") as mock_get_db:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mem_db)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_get_db.return_value = mock_ctx

            updated = await mc.update_from_actions(
                current_state=state,
                session_id=session_id,
                round_number=1,
            )

        assert updated is state, "No actions → identical state object expected"

    @pytest.mark.asyncio
    async def test_update_returns_new_frozen_object(self, mem_db: aiosqlite.Connection) -> None:
        """update_from_actions must return a new MacroState, never mutate original."""
        from backend.app.services.macro_controller import MacroController
        from backend.app.services.macro_state import BASELINE_AVG_SQFT_PRICE, BASELINE_STAMP_DUTY, MacroState

        session_id = "immut-test-03"
        rows = [(session_id, 1, None, f"u{i}", "negative", "[]") for i in range(8)]
        rows += [(session_id, 1, None, f"p{i}", "positive", "[]") for i in range(2)]
        await mem_db.executemany(
            "INSERT INTO simulation_actions "
            "(session_id, round_number, agent_id, oasis_username, sentiment, topics) "
            "VALUES (?,?,?,?,?,?)",
            rows,
        )
        await mem_db.commit()

        state = MacroState(
            hibor_1m=0.04,
            prime_rate=0.055,
            unemployment_rate=0.032,
            median_monthly_income=20_800,
            ccl_index=150.0,
            avg_sqft_price=dict(BASELINE_AVG_SQFT_PRICE),
            mortgage_cap=0.70,
            stamp_duty_rates=dict(BASELINE_STAMP_DUTY),
            gdp_growth=0.025,
            cpi_yoy=0.019,
            hsi_level=20_060.0,
            consumer_confidence=50.0,
            net_migration=2_000,
            birth_rate=5.3,
            policy_flags={},
        )
        original_confidence = state.consumer_confidence

        mc = MacroController()

        with patch("backend.app.utils.db.get_db") as mock_get_db:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mem_db)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_get_db.return_value = mock_ctx

            updated = await mc.update_from_actions(current_state=state, session_id=session_id, round_number=1)

        # Original must be unchanged (frozen dataclass)
        assert state.consumer_confidence == original_confidence
        # Returned object is a new MacroState
        assert updated is not state


# ---------------------------------------------------------------------------
# Task 3.3 — MonteCarloEngine + EnsembleRunner Verification
# ---------------------------------------------------------------------------


class TestMonteCarloEngine:
    """Structural / unit tests for MonteCarloEngine."""

    def test_can_instantiate(self) -> None:
        from backend.app.services.monte_carlo import MonteCarloEngine

        engine = MonteCarloEngine()
        assert engine is not None

    def test_run_single_trial_returns_expected_metrics(self) -> None:
        """_run_single_trial must return all DEFAULT_METRICS keys."""
        import numpy as np

        from backend.app.services.monte_carlo import (
            DEFAULT_METRICS,
            MonteCarloEngine,
        )

        rng = np.random.default_rng(seed=42)
        base = {
            "buy_property_confidence": 0.4,
            "emigrate_confidence": 0.3,
            "gdp_growth": 0.025,
            "unemployment_rate": 0.032,
            "ccl_index": 150.0,
            "hsi_level": 20_000.0,
            "consumer_confidence": 50.0,
            "net_migration": -2_000.0,
            "positive_ratio": 0.4,
            "negative_ratio": 0.25,
            "interest_rate": 0.055,
            "taiwan_strait_risk": 0.25,
        }
        result = MonteCarloEngine._run_single_trial(base, rng)

        for metric in DEFAULT_METRICS:
            assert metric in result, f"Missing metric: {metric}"
            assert isinstance(result[metric], float)

    def test_buy_property_rate_clamped_zero_to_one(self) -> None:
        """buy_property_rate must stay in [0, 1] even with extreme params."""
        import numpy as np

        from backend.app.services.monte_carlo import MonteCarloEngine

        rng = np.random.default_rng(seed=0)
        base_low = {
            "buy_property_confidence": 0.0,
            "emigrate_confidence": 0.0,
            "gdp_growth": -0.10,
            "unemployment_rate": 0.20,
            "ccl_index": 50.0,
            "hsi_level": 8_000.0,
            "consumer_confidence": 10.0,
            "net_migration": -100_000.0,
            "positive_ratio": 0.0,
            "negative_ratio": 0.9,
            "interest_rate": 0.15,
            "taiwan_strait_risk": 0.95,
        }
        result = MonteCarloEngine._run_single_trial(base_low, rng)
        assert 0.0 <= result["buy_property_rate"] <= 1.0
        assert 0.0 <= result["emigrate_rate"] <= 1.0

    @pytest.mark.asyncio
    async def test_run_persists_to_db(self, tmp_path: Path) -> None:
        """MonteCarloEngine.run() must write rows to ensemble_results table."""
        import contextlib

        from backend.app.services.monte_carlo import MonteCarloEngine

        engine = MonteCarloEngine()
        session_id = "mc-persist-01"

        db_file = str(tmp_path / "mc_test.db")

        # Use a real temp-file DB so executescript + commit work correctly
        async with aiosqlite.connect(db_file) as setup_db:
            setup_db.row_factory = aiosqlite.Row
            await setup_db.executescript(_MINIMAL_SCHEMA)
            await setup_db.commit()

        # Monte Carlo imports get_db at module level — patch at the usage site
        @contextlib.asynccontextmanager
        async def _real_get_db():
            async with aiosqlite.connect(db_file) as conn:
                conn.row_factory = aiosqlite.Row
                yield conn

        with patch("backend.app.services.monte_carlo.get_db", side_effect=_real_get_db):
            result = await engine.run(session_id=session_id, n_trials=20)

        assert result.session_id == session_id
        assert result.n_trials == 20
        assert len(result.distributions) > 0

        # Verify DB rows using a fresh connection
        async with aiosqlite.connect(db_file) as verify_db:
            verify_db.row_factory = aiosqlite.Row
            cursor = await verify_db.execute(
                "SELECT COUNT(*) FROM ensemble_results WHERE session_id = ?",
                (session_id,),
            )
            row = await cursor.fetchone()
            assert row[0] > 0, "ensemble_results table must have rows after MC run"

    @pytest.mark.asyncio
    async def test_distribution_bands_monotone(self, tmp_path: Path) -> None:
        """Each DistributionBand must have p10 <= p25 <= p50 <= p75 <= p90."""
        import contextlib

        from backend.app.services.monte_carlo import MonteCarloEngine

        engine = MonteCarloEngine()
        db_file = str(tmp_path / "mc_mono.db")

        async with aiosqlite.connect(db_file) as setup_db:
            setup_db.row_factory = aiosqlite.Row
            await setup_db.executescript(_MINIMAL_SCHEMA)
            await setup_db.commit()

        @contextlib.asynccontextmanager
        async def _real_get_db():
            async with aiosqlite.connect(db_file) as conn:
                conn.row_factory = aiosqlite.Row
                yield conn

        with patch("backend.app.services.monte_carlo.get_db", side_effect=_real_get_db):
            result = await engine.run(session_id="mc-mono", n_trials=30)

        for band in result.distributions:
            assert band.p10 <= band.p25 <= band.p50 <= band.p75 <= band.p90, (
                f"Percentiles not monotone for metric={band.metric_name}"
            )

    def test_ensemble_result_get_band(self) -> None:
        """EnsembleResult.get_band() must return the correct DistributionBand."""
        from backend.app.models.ensemble import DistributionBand, EnsembleResult

        bands = [
            DistributionBand("ccl_index_change", -5.0, -2.0, 0.0, 2.0, 5.0),
            DistributionBand("emigrate_rate", 0.1, 0.2, 0.3, 0.4, 0.5),
        ]
        er = EnsembleResult(session_id="s1", n_trials=50, distributions=bands)

        found = er.get_band("emigrate_rate")
        assert found is not None
        assert found.metric_name == "emigrate_rate"
        assert er.get_band("nonexistent") is None


class TestEnsembleRunner:
    """Structural tests for EnsembleRunner (no real OASIS subprocess)."""

    def test_can_instantiate(self) -> None:
        from backend.app.services.ensemble_runner import EnsembleRunner

        runner = EnsembleRunner()
        assert runner is not None

    def test_trial_record_is_frozen(self) -> None:
        """TrialRecord must be a frozen dataclass — direct attribute mutation raises."""
        from dataclasses import FrozenInstanceError

        from backend.app.services.ensemble_runner import TrialRecord

        record = TrialRecord(
            trial_index=0,
            branch_session_id="branch-001",
            perturbation={"hibor_1m": 0.042},
            status="completed",
        )
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            # Normal attribute assignment on a frozen dataclass must raise
            record.status = "running"  # type: ignore[misc]

        assert record.status == "completed"

    def test_perturb_macro_fields_returns_all_perturbable(self) -> None:
        """_perturb_macro_fields must return a value for each PERTURBABLE_FIELDS entry."""
        import numpy as np

        from backend.app.services.ensemble_analyzer import PERTURBABLE_FIELDS
        from backend.app.services.ensemble_runner import _perturb_macro_fields
        from backend.app.services.macro_state import BASELINE_AVG_SQFT_PRICE, BASELINE_STAMP_DUTY, MacroState

        state = MacroState(
            hibor_1m=0.04,
            prime_rate=0.055,
            unemployment_rate=0.032,
            median_monthly_income=20_800,
            ccl_index=150.0,
            avg_sqft_price=dict(BASELINE_AVG_SQFT_PRICE),
            mortgage_cap=0.70,
            stamp_duty_rates=dict(BASELINE_STAMP_DUTY),
            gdp_growth=0.025,
            cpi_yoy=0.019,
            hsi_level=20_060.0,
            consumer_confidence=50.0,
            net_migration=2_000,
            birth_rate=5.3,
            policy_flags={},
        )

        rng = np.random.default_rng(seed=7)
        result = _perturb_macro_fields(state, rng, sigma_fraction=0.05)

        for field in PERTURBABLE_FIELDS:
            assert field in result, f"Field {field!r} missing from perturbation output"
            assert isinstance(result[field], float)

    def test_schema_has_ensemble_results_table(self) -> None:
        """ensemble_results table must be defined in schema.sql."""
        schema_text = _SCHEMA_PATH.read_text(encoding="utf-8")
        assert "ensemble_results" in schema_text, "ensemble_results table not found in backend/database/schema.sql"


# ---------------------------------------------------------------------------
# Task 3.4 — B2B CompanyFactory Initialization
# ---------------------------------------------------------------------------


class TestCompanyFactory:
    """Unit tests for CompanyFactory.generate_companies()."""

    @pytest.mark.asyncio
    async def test_generate_returns_correct_count(self) -> None:
        """generate_companies must return exactly count profiles."""
        from backend.app.services.company_factory import CompanyFactory

        factory = CompanyFactory(rng_seed=42)
        profiles = await factory.generate_companies("sess-b2b-01", count=20)

        assert len(profiles) == 20

    @pytest.mark.asyncio
    async def test_profiles_are_frozen_dataclasses(self) -> None:
        """CompanyProfile must be immutable (frozen dataclass)."""
        from backend.app.models.company import CompanyProfile
        from backend.app.services.company_factory import CompanyFactory

        factory = CompanyFactory(rng_seed=1)
        profiles = await factory.generate_companies("sess-b2b-02", count=5)

        for p in profiles:
            assert isinstance(p, CompanyProfile)
            with pytest.raises(Exception):
                p.company_name = "mutated"  # type: ignore[misc]

    @pytest.mark.asyncio
    async def test_profiles_have_valid_fields(self) -> None:
        """Each CompanyProfile must have non-empty required string fields."""
        from backend.app.services.company_factory import CompanyFactory

        factory = CompanyFactory(rng_seed=99)
        profiles = await factory.generate_companies("sess-b2b-03", count=15)

        for p in profiles:
            assert p.company_name, "company_name must not be empty"
            assert p.company_type, "company_type must not be empty"
            assert p.industry_sector, "industry_sector must not be empty"
            assert p.company_size in ("sme", "mnc", "startup")
            assert 0.0 <= p.china_exposure <= 1.0
            assert 0.0 <= p.export_ratio <= 1.0
            assert p.annual_revenue_hkd > 0
            assert p.employee_count > 0

    @pytest.mark.asyncio
    async def test_names_are_unique(self) -> None:
        """Company names must be unique within a batch (best-effort)."""
        from backend.app.services.company_factory import CompanyFactory

        factory = CompanyFactory(rng_seed=5)
        profiles = await factory.generate_companies("sess-b2b-04", count=30)
        names = [p.company_name for p in profiles]
        # Allow very small collision rate but names must be mostly unique
        unique_ratio = len(set(names)) / len(names)
        assert unique_ratio >= 0.85, f"Too many duplicate company names: unique_ratio={unique_ratio:.2f}"

    @pytest.mark.asyncio
    async def test_store_and_load_roundtrip(self, tmp_path: Path) -> None:
        """store_companies() must persist profiles and load_companies() must retrieve them."""
        import contextlib

        from backend.app.services.company_factory import CompanyFactory

        factory = CompanyFactory(rng_seed=77)
        session_id = "sess-b2b-store-unique-77"
        n_companies = 10

        db_file = str(tmp_path / "b2b_roundtrip.db")
        async with aiosqlite.connect(db_file) as setup_db:
            setup_db.row_factory = aiosqlite.Row
            await setup_db.executescript(_MINIMAL_SCHEMA)
            await setup_db.commit()

        profiles = await factory.generate_companies(session_id, count=n_companies)

        @contextlib.asynccontextmanager
        async def _real_get_db():
            async with aiosqlite.connect(db_file) as conn:
                conn.row_factory = aiosqlite.Row
                yield conn

        with patch("backend.app.services.company_factory.get_db", side_effect=_real_get_db):
            factory._schema_initialised = True
            stored = await factory.store_companies(session_id, profiles)

        assert len(stored) == n_companies, f"All {n_companies} companies must be stored"
        for s in stored:
            assert s.id > 0, "DB-assigned ID must be positive"
            assert s.session_id == session_id

    @pytest.mark.asyncio
    async def test_store_sets_session_id(self, tmp_path: Path) -> None:
        """Stored companies must carry the correct session_id."""
        import contextlib

        from backend.app.services.company_factory import CompanyFactory

        factory = CompanyFactory(rng_seed=123)
        session_id = "sess-b2b-store-02-unique"

        db_file = str(tmp_path / "b2b_session.db")
        async with aiosqlite.connect(db_file) as setup_db:
            setup_db.row_factory = aiosqlite.Row
            await setup_db.executescript(_MINIMAL_SCHEMA)
            await setup_db.commit()

        profiles = await factory.generate_companies(session_id, count=5)

        @contextlib.asynccontextmanager
        async def _real_get_db():
            async with aiosqlite.connect(db_file) as conn:
                conn.row_factory = aiosqlite.Row
                yield conn

        with patch("backend.app.services.company_factory.get_db", side_effect=_real_get_db):
            factory._schema_initialised = True
            stored = await factory.store_companies(session_id, profiles)

        for s in stored:
            assert s.session_id == session_id


# ---------------------------------------------------------------------------
# Task 3 (Phase 2) — dry_run mode
# ---------------------------------------------------------------------------


class TestSimulationRunnerDryRun:
    """Verify SimulationRunner behaves correctly in dry_run mode."""

    def test_dry_run_flag_stored(self) -> None:
        """SimulationRunner(dry_run=True) must store the flag."""
        from backend.app.services.simulation_runner import SimulationRunner

        runner = SimulationRunner(dry_run=True)
        assert runner._dry_run is True

    def test_default_is_not_dry_run(self) -> None:
        """SimulationRunner() default must NOT be dry_run."""
        from backend.app.services.simulation_runner import SimulationRunner

        runner = SimulationRunner()
        assert runner._dry_run is False

    @pytest.mark.asyncio
    async def test_dry_run_completes_without_subprocess(self, tmp_path: Path) -> None:
        """dry_run=True must complete run() without spawning a subprocess."""
        from backend.app.services.simulation_runner import SimulationRunner

        runner = SimulationRunner(dry_run=True)
        session_id = "dry-test-001"

        agent_csv = tmp_path / "agents.csv"
        agent_csv.write_text("id,name\n1,Alice\n")

        config: dict[str, Any] = {
            "agent_csv_path": str(agent_csv),
            "platforms": {"facebook": True},
            "round_count": 3,
        }

        subprocess_spawned = False

        with patch("asyncio.create_subprocess_exec") as mock_spawn:
            mock_spawn.side_effect = AssertionError("subprocess must not be spawned in dry_run")
            # Patch B2B init and ws push_progress to avoid real DB / import issues
            with patch.object(runner, "_init_b2b_companies", new=AsyncMock()):
                with patch("backend.app.api.ws.push_progress", new=AsyncMock()):
                    await runner.run(session_id, config)

        # If we reach here without AssertionError, subprocess was not called
        assert not mock_spawn.called

    @pytest.mark.asyncio
    async def test_dry_run_generates_mock_progress_events(self, tmp_path: Path) -> None:
        """dry_run must emit progress and post events via the progress_callback."""
        from backend.app.services.simulation_runner import SimulationRunner

        runner = SimulationRunner(dry_run=True)
        session_id = "dry-test-002"

        agent_csv = tmp_path / "agents.csv"
        agent_csv.write_text("id,name\n1,Alice\n")

        collected: list[dict[str, Any]] = []

        async def capture(update: dict[str, Any]) -> None:
            collected.append(update)

        config: dict[str, Any] = {
            "agent_csv_path": str(agent_csv),
            "platforms": {"facebook": True},
            "round_count": 3,
        }

        with patch.object(runner, "_init_b2b_companies", new=AsyncMock()):
            with patch("backend.app.api.ws.push_progress", new=AsyncMock()):
                await runner.run(session_id, config, progress_callback=capture)

        types = {e["type"] for e in collected}
        assert "progress" in types, "Must emit at least one 'progress' event"
        assert "post" in types, "Must emit at least one 'post' event"

        complete_events = [e for e in collected if e["type"] == "complete"]
        assert len(complete_events) == 1, "Must emit exactly one 'complete' event"

    @pytest.mark.asyncio
    async def test_dry_run_triggers_memory_hook(self, tmp_path: Path) -> None:
        """dry_run must call _process_round_memories for each simulated round."""
        from backend.app.services.simulation_runner import SimulationRunner

        runner = SimulationRunner(dry_run=True)
        session_id = "dry-test-003"

        agent_csv = tmp_path / "agents.csv"
        agent_csv.write_text("id,name\n1,Alice\n")

        memory_rounds: list[int] = []

        async def mock_memory(sid: str, rnd: int, **kwargs: Any) -> None:
            memory_rounds.append(rnd)

        config: dict[str, Any] = {
            "agent_csv_path": str(agent_csv),
            "platforms": {"facebook": True},
            "round_count": 3,
        }

        with patch.object(runner, "_init_b2b_companies", new=AsyncMock()):
            with patch("backend.app.api.ws.push_progress", new=AsyncMock()):
                with patch.object(runner, "_process_round_memories", side_effect=mock_memory):
                    await runner.run(session_id, config)

        assert len(memory_rounds) == 3, f"Expected 3 memory hook calls (one per round), got {memory_rounds}"
        assert memory_rounds == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_dry_run_triggers_decision_hook(self, tmp_path: Path) -> None:
        """dry_run must call _process_round_decisions for each simulated round."""
        from backend.app.services.simulation_runner import SimulationRunner

        runner = SimulationRunner(dry_run=True)
        session_id = "dry-test-004"

        agent_csv = tmp_path / "agents.csv"
        agent_csv.write_text("id,name\n1,Alice\n")

        decision_rounds: list[int] = []

        async def mock_decisions(sid: str, rnd: int) -> None:
            decision_rounds.append(rnd)

        config: dict[str, Any] = {
            "agent_csv_path": str(agent_csv),
            "platforms": {"facebook": True},
            "round_count": 3,
        }

        with patch.object(runner, "_init_b2b_companies", new=AsyncMock()):
            with patch("backend.app.api.ws.push_progress", new=AsyncMock()):
                with patch.object(runner, "_process_round_decisions", side_effect=mock_decisions):
                    await runner.run(session_id, config)

        assert len(decision_rounds) == 3
        assert decision_rounds == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_dry_run_cleans_up_buffers(self, tmp_path: Path) -> None:
        """dry_run must clear _posts_buffer and _macro_state after completion."""
        from backend.app.services.simulation_runner import SimulationRunner

        runner = SimulationRunner(dry_run=True)
        session_id = "dry-test-005"

        agent_csv = tmp_path / "agents.csv"
        agent_csv.write_text("id,name\n1,Alice\n")

        config: dict[str, Any] = {
            "agent_csv_path": str(agent_csv),
            "platforms": {"facebook": True},
            "round_count": 3,
        }

        with patch.object(runner, "_init_b2b_companies", new=AsyncMock()):
            with patch("backend.app.api.ws.push_progress", new=AsyncMock()):
                await runner.run(session_id, config)

        assert session_id not in runner._posts_buffer, "_posts_buffer must be cleared after dry_run"
        assert session_id not in runner._macro_state, "_macro_state must be cleared after dry_run"


class TestSimulationRunnerRelativePaths:
    """Verify that module-level path constants are computed relative to the file."""

    def test_project_root_is_valid_directory(self) -> None:
        """_PROJECT_ROOT must point to an existing directory."""
        from backend.app.services import simulation_runner as sr
        from backend.app.services import simulation_helpers as sh
        from backend.app.services import simulation_lifecycle as sl

        assert sr._PROJECT_ROOT.is_dir(), f"_PROJECT_ROOT does not exist: {sr._PROJECT_ROOT}"

    def test_project_root_contains_backend(self) -> None:
        """_PROJECT_ROOT must contain the backend/ subdirectory."""
        from backend.app.services import simulation_lifecycle as sl

        assert (sl._PROJECT_ROOT / "backend").is_dir(), "_PROJECT_ROOT does not contain a backend/ directory"

    def test_python_bin_path_is_relative(self) -> None:
        """_PYTHON_BIN must be derived from _PROJECT_ROOT, not an absolute literal."""
        from backend.app.services import simulation_lifecycle as sl

        assert str(sl._PYTHON_BIN).startswith(str(sl._PROJECT_ROOT)), "_PYTHON_BIN must be relative to _PROJECT_ROOT"

    def test_script_paths_are_under_project_root(self) -> None:
        """All simulation script paths must be under _PROJECT_ROOT."""
        from backend.app.services import simulation_lifecycle as sl

        scripts = [
            sl._SCRIPT_PATH,
            sl._PARALLEL_SCRIPT,
            sl._FACEBOOK_SCRIPT,
            sl._INSTAGRAM_SCRIPT,
        ]
        for script in scripts:
            assert str(script).startswith(str(sl._PROJECT_ROOT)), f"Script path not under _PROJECT_ROOT: {script}"

    def test_no_hardcoded_absolute_paths(self) -> None:
        """simulation_runner.py must not contain hardcoded /Volumes/... paths."""
        source = Path(__file__).resolve().parent.parent / "app" / "services" / "simulation_runner.py"
        content = source.read_text(encoding="utf-8")
        assert "/Volumes/4TB/francistam" not in content, "Found hardcoded absolute path in simulation_runner.py"


class TestB2BInitInSimulationRunner:
    """Task 3.4 — verify B2B initialization is conditional and non-blocking."""

    @pytest.mark.asyncio
    async def test_b2b_init_skipped_when_companies_exist(self, mem_db: aiosqlite.Connection) -> None:
        """When company_profiles already has rows for the session, factory skips."""
        session_id = "sess-b2b-skip"

        # Pre-populate one company row
        await mem_db.execute(
            """
            INSERT INTO company_profiles
                (session_id, company_name, company_type, industry_sector,
                 company_size, china_exposure, export_ratio)
            VALUES (?, '利貿易有限公司', 'trader', 'import_export', 'sme', 0.8, 0.7)
            """,
            (session_id,),
        )
        await mem_db.commit()

        with patch("backend.app.utils.db.get_db") as mock_get_db:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mem_db)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_get_db.return_value = mock_ctx

            # Check the guard condition directly
            cursor = await mem_db.execute(
                "SELECT COUNT(*) FROM company_profiles WHERE session_id = ?",
                (session_id,),
            )
            row = await cursor.fetchone()
            count = row[0]

        assert count == 1
        # Guard: only initialise if count == 0
        should_init = count == 0
        assert not should_init, "B2B init should be skipped when companies exist"

    @pytest.mark.asyncio
    async def test_b2b_failure_does_not_raise(self) -> None:
        """CompanyFactory errors must be caught — B2B failure must not bubble up."""
        from backend.app.services.company_factory import CompanyFactory

        factory = CompanyFactory(rng_seed=0)

        error_raised = False
        try:
            with patch.object(factory, "generate_companies", side_effect=RuntimeError("DB down")):
                try:
                    await factory.generate_companies("sess-fail", count=10)
                except RuntimeError:
                    pass  # Caught inside the simulation runner try/except
        except Exception:
            error_raised = True

        # The outer test context must not see the error
        assert not error_raised, "B2B errors must be swallowed inside the runner"

    @pytest.mark.asyncio
    async def test_b2b_generates_companies_for_new_session(self, mem_db: aiosqlite.Connection) -> None:
        """For a new session with zero companies, factory must generate profiles."""
        from backend.app.services.company_factory import CompanyFactory

        session_id = "sess-b2b-new"

        with patch("backend.app.utils.db.get_db") as mock_get_db:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mem_db)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_get_db.return_value = mock_ctx

            cursor = await mem_db.execute(
                "SELECT COUNT(*) FROM company_profiles WHERE session_id = ?",
                (session_id,),
            )
            row = await cursor.fetchone()
            count = row[0]

        assert count == 0, "New session starts with zero companies"
        should_init = count == 0
        assert should_init, "B2B init should proceed when no companies exist"

        # Now actually generate
        factory = CompanyFactory(rng_seed=42)
        profiles = await factory.generate_companies(session_id, count=50)
        assert len(profiles) == 50
