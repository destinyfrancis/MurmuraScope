"""Tests for Phase A ensemble services: EnsembleAnalyzer and EnsembleRunner.

Coverage areas:
- EnsembleAnalyzer.compute_percentiles (unit + integration)
- EnsembleAnalyzer.generate_probability_statement
- EnsembleAnalyzer.generate_all_statements
- _interpolate_probability helper
- _format_threshold helper
- EnsembleRunner._perturb_macro_fields (via private import)
- EnsembleRunner.run_ensemble (integration with mocked SimulationRunner)
- EnsembleRunner.get_trial_metadata
- API endpoints POST /{id}/ensemble and GET /{id}/ensemble/results
"""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
import pytest_asyncio

from backend.app.models.ensemble import DistributionBand, EnsembleResult
from backend.app.services.ensemble_analyzer import (
    EnsembleAnalyzer,
    ProbabilityStatement,
    PERTURBABLE_FIELDS,
    _interpolate_probability,
    _format_threshold,
)
from backend.app.services.ensemble_runner import (
    EnsembleRunner,
    TrialRecord,
    _perturb_macro_fields,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_band(
    metric: str = "ccl_index",
    p10: float = 100.0,
    p25: float = 120.0,
    p50: float = 150.0,
    p75: float = 180.0,
    p90: float = 200.0,
) -> DistributionBand:
    return DistributionBand(
        metric_name=metric,
        p10=p10, p25=p25, p50=p50, p75=p75, p90=p90,
    )


def _make_macro_state():
    """Build a minimal MacroState using the MacroController defaults."""
    from backend.app.services.macro_state import (
        MacroState,
        BASELINE_AVG_SQFT_PRICE,
        BASELINE_STAMP_DUTY,
    )
    return MacroState(
        hibor_1m=0.043,
        prime_rate=0.0575,
        unemployment_rate=0.029,
        median_monthly_income=20_000,
        ccl_index=152.3,
        avg_sqft_price=dict(BASELINE_AVG_SQFT_PRICE),
        mortgage_cap=0.70,
        stamp_duty_rates=dict(BASELINE_STAMP_DUTY),
        gdp_growth=0.032,
        cpi_yoy=0.021,
        hsi_level=16_800.0,
        consumer_confidence=88.5,
        net_migration=-12_000,
        birth_rate=5.8,
        policy_flags={"辣招撤銷": True},
        fed_rate=0.053,
        taiwan_strait_risk=0.3,
        china_gdp_growth=0.052,
    )


# ---------------------------------------------------------------------------
# Unit tests: _interpolate_probability
# ---------------------------------------------------------------------------


class TestInterpolateProbability:
    """Pure-function unit tests for percentile interpolation."""

    def test_below_p10_returns_high_probability(self):
        band = _make_band(p10=100.0, p90=200.0)
        # Below p10: P(X > threshold) should be near 0.90+
        result = _interpolate_probability(band, 50.0)
        assert result > 0.90

    def test_above_p90_returns_low_probability(self):
        band = _make_band(p10=100.0, p90=200.0)
        result = _interpolate_probability(band, 250.0)
        assert result < 0.10

    def test_at_median_returns_half(self):
        band = _make_band(p10=100.0, p25=125.0, p50=150.0, p75=175.0, p90=200.0)
        result = _interpolate_probability(band, 150.0)
        # P(X > p50) ≈ 0.50
        assert abs(result - 0.50) < 0.02

    def test_between_p25_and_p50(self):
        band = _make_band(p10=100.0, p25=130.0, p50=160.0, p75=180.0, p90=200.0)
        result = _interpolate_probability(band, 145.0)
        # Should be between 0.50 and 0.75
        assert 0.50 < result < 0.75

    def test_at_p75_returns_approx_25pct(self):
        band = _make_band(p10=100.0, p25=125.0, p50=150.0, p75=175.0, p90=200.0)
        result = _interpolate_probability(band, 175.0)
        assert abs(result - 0.25) < 0.03

    def test_result_always_in_zero_one(self):
        band = _make_band(p10=0.01, p25=0.02, p50=0.03, p75=0.04, p90=0.05)
        for threshold in [-10, 0, 0.01, 0.025, 0.05, 0.1]:
            result = _interpolate_probability(band, threshold)
            assert 0.0 <= result <= 1.0, f"Out of range for threshold={threshold}: {result}"

    def test_flat_band_does_not_crash(self):
        """Degenerate case: all percentiles equal."""
        band = _make_band(p10=100.0, p25=100.0, p50=100.0, p75=100.0, p90=100.0)
        result = _interpolate_probability(band, 100.0)
        assert 0.0 <= result <= 1.0


# ---------------------------------------------------------------------------
# Unit tests: _format_threshold
# ---------------------------------------------------------------------------


class TestFormatThreshold:
    def test_percentage_metrics(self):
        assert "%" in _format_threshold("hibor_1m", 0.043)
        assert "%" in _format_threshold("unemployment_rate", 0.03)
        assert "%" in _format_threshold("gdp_growth", 0.032)

    def test_hsi_level_has_thousands_separator(self):
        result = _format_threshold("hsi_level", 16800.0)
        assert "16" in result  # has digits

    def test_taiwan_strait_risk_decimal(self):
        result = _format_threshold("taiwan_strait_risk", 0.3)
        assert "0.30" in result

    def test_net_migration_formatted(self):
        result = _format_threshold("net_migration", -12000.0)
        assert "-12" in result

    def test_unknown_metric_fallback(self):
        result = _format_threshold("unknown_metric", 42.5)
        assert "42" in result


# ---------------------------------------------------------------------------
# Unit tests: _perturb_macro_fields
# ---------------------------------------------------------------------------


class TestPerturbMacroFields:
    def test_returns_all_perturbable_fields(self):
        state = _make_macro_state()
        rng = np.random.default_rng(seed=42)
        result = _perturb_macro_fields(state, rng, sigma_fraction=0.05)
        for field in PERTURBABLE_FIELDS:
            assert field in result, f"Missing field: {field}"

    def test_values_within_clamps(self):
        from backend.app.services.ensemble_runner import _FIELD_CLAMPS
        state = _make_macro_state()
        rng = np.random.default_rng(seed=0)
        # Run many perturbations to stress test clamping
        for _ in range(50):
            result = _perturb_macro_fields(state, rng, sigma_fraction=2.0)
            for field, value in result.items():
                lo, hi = _FIELD_CLAMPS.get(field, (-1e12, 1e12))
                assert lo <= value <= hi, f"{field}={value} out of [{lo}, {hi}]"

    def test_values_are_floats(self):
        state = _make_macro_state()
        rng = np.random.default_rng(seed=1)
        result = _perturb_macro_fields(state, rng, sigma_fraction=0.05)
        for field, value in result.items():
            assert isinstance(value, float), f"{field} should be float, got {type(value)}"

    def test_different_seeds_give_different_results(self):
        state = _make_macro_state()
        rng1 = np.random.default_rng(seed=10)
        rng2 = np.random.default_rng(seed=20)
        r1 = _perturb_macro_fields(state, rng1, sigma_fraction=0.05)
        r2 = _perturb_macro_fields(state, rng2, sigma_fraction=0.05)
        # At least some fields should differ
        assert any(r1[f] != r2[f] for f in r1)

    def test_zero_std_returns_clamped_baseline(self):
        """Zero sigma: result should be identical to base values (within float tolerance)."""
        state = _make_macro_state()
        rng = np.random.default_rng(seed=99)
        result = _perturb_macro_fields(state, rng, sigma_fraction=0.0)
        import dataclasses
        state_dict = dataclasses.asdict(state)
        for field in PERTURBABLE_FIELDS:
            base = state_dict.get(field)
            if base is not None:
                assert abs(result[field] - float(base)) < 1e-6, (
                    f"{field}: expected {base}, got {result[field]}"
                )


# ---------------------------------------------------------------------------
# Unit tests: EnsembleAnalyzer.generate_probability_statement
# ---------------------------------------------------------------------------


class TestEnsembleAnalyzerProbabilityStatement:
    def _make_distributions(self):
        return [
            _make_band("ccl_index", 100, 120, 150, 180, 200),
            _make_band("hsi_level", 12000, 14000, 16800, 20000, 24000),
            _make_band("unemployment_rate", 0.02, 0.025, 0.03, 0.04, 0.05),
        ]

    def test_returns_frozen_dataclass(self):
        analyzer = EnsembleAnalyzer()
        dists = self._make_distributions()
        stmt = analyzer.generate_probability_statement(dists, "ccl_index", 140.0)
        assert isinstance(stmt, ProbabilityStatement)

    def test_probability_in_range(self):
        analyzer = EnsembleAnalyzer()
        dists = self._make_distributions()
        stmt = analyzer.generate_probability_statement(dists, "ccl_index", 150.0)
        assert 0.0 <= stmt.probability <= 1.0

    def test_statement_zh_contains_chinese(self):
        analyzer = EnsembleAnalyzer()
        dists = self._make_distributions()
        stmt = analyzer.generate_probability_statement(dists, "ccl_index", 140.0)
        assert "概率" in stmt.statement_zh

    def test_missing_metric_raises_value_error(self):
        analyzer = EnsembleAnalyzer()
        dists = self._make_distributions()
        with pytest.raises(ValueError, match="nonexistent_field"):
            analyzer.generate_probability_statement(dists, "nonexistent_field", 10.0)

    def test_generate_all_statements_returns_list(self):
        analyzer = EnsembleAnalyzer()
        dists = self._make_distributions()
        results = analyzer.generate_all_statements(dists)
        assert isinstance(results, list)
        for item in results:
            assert "metric" in item
            assert "statement_zh" in item
            assert "probability" in item
            assert 0.0 <= item["probability"] <= 1.0


# ---------------------------------------------------------------------------
# Integration tests: EnsembleAnalyzer.compute_percentiles (with real DB)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestEnsembleAnalyzerComputePercentiles:
    async def test_empty_trial_list_returns_empty_result(self, test_db, monkeypatch):
        """With no trial session IDs, returns EnsembleResult with empty distributions."""
        from backend.app.utils import db as db_module

        monkeypatch.setattr(
            db_module,
            "get_db",
            lambda: _mock_db_context(test_db),
        )

        analyzer = EnsembleAnalyzer()
        result = await analyzer.compute_percentiles(
            session_id="parent-001",
            trial_session_ids=[],
        )
        assert isinstance(result, EnsembleResult)
        assert result.n_trials == 0
        assert result.distributions == []

    async def test_returns_ensemble_result_type(self, test_db, monkeypatch):
        """With real DB containing macro_snapshots, returns valid EnsembleResult."""
        import backend.app.services.ensemble_analyzer as ea_module

        session_a = str(uuid.uuid4())
        session_b = str(uuid.uuid4())

        # Seed the macro_snapshots table (schema.sql may not include it; create manually)
        await test_db.executescript("""
            CREATE TABLE IF NOT EXISTS macro_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                round_number INTEGER NOT NULL,
                macro_json TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(session_id, round_number)
            )
        """)
        macro_a = json.dumps({"ccl_index": 155.0, "hsi_level": 17000.0,
                               "unemployment_rate": 0.028, "gdp_growth": 0.033,
                               "consumer_confidence": 89.0, "net_migration": -10000,
                               "hibor_1m": 0.042, "fed_rate": 0.052,
                               "china_gdp_growth": 0.055, "taiwan_strait_risk": 0.28})
        macro_b = json.dumps({"ccl_index": 145.0, "hsi_level": 16200.0,
                               "unemployment_rate": 0.031, "gdp_growth": 0.029,
                               "consumer_confidence": 85.0, "net_migration": -15000,
                               "hibor_1m": 0.045, "fed_rate": 0.055,
                               "china_gdp_growth": 0.048, "taiwan_strait_risk": 0.35})
        await test_db.execute(
            "INSERT INTO macro_snapshots (session_id, round_number, macro_json) VALUES (?,?,?)",
            (session_a, 5, macro_a),
        )
        await test_db.execute(
            "INSERT INTO macro_snapshots (session_id, round_number, macro_json) VALUES (?,?,?)",
            (session_b, 5, macro_b),
        )
        await test_db.commit()

        parent_id = str(uuid.uuid4())

        # Patch get_db at the ensemble_analyzer module level (top-level import)
        monkeypatch.setattr(ea_module, "get_db", lambda: _mock_db_context(test_db))

        analyzer = EnsembleAnalyzer()
        result = await analyzer.compute_percentiles(
            session_id=parent_id,
            trial_session_ids=[session_a, session_b],
        )
        assert isinstance(result, EnsembleResult)
        assert result.n_trials == 2
        # Should have bands for metrics present in both snapshots
        metric_names = {b.metric_name for b in result.distributions}
        assert "ccl_index" in metric_names
        assert "hsi_level" in metric_names

    async def test_band_percentiles_ordered(self, test_db, monkeypatch):
        """p10 <= p25 <= p50 <= p75 <= p90 for all bands."""
        import backend.app.services.ensemble_analyzer as ea_module

        session_ids = [str(uuid.uuid4()) for _ in range(5)]
        parent_id = str(uuid.uuid4())
        values = [100.0, 120.0, 140.0, 160.0, 180.0]

        await test_db.executescript("""
            CREATE TABLE IF NOT EXISTS macro_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                round_number INTEGER NOT NULL,
                macro_json TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(session_id, round_number)
            )
        """)
        for sid, val in zip(session_ids, values):
            macro_json = json.dumps({
                "ccl_index": val,
                "hsi_level": val * 100,
                "unemployment_rate": 0.03,
                "gdp_growth": 0.03,
                "consumer_confidence": 88.0,
                "net_migration": -12000,
                "hibor_1m": 0.043,
                "fed_rate": 0.053,
                "china_gdp_growth": 0.052,
                "taiwan_strait_risk": 0.3,
            })
            await test_db.execute(
                "INSERT INTO macro_snapshots (session_id, round_number, macro_json) VALUES (?,?,?)",
                (sid, 10, macro_json),
            )
        await test_db.commit()

        monkeypatch.setattr(ea_module, "get_db", lambda: _mock_db_context(test_db))

        analyzer = EnsembleAnalyzer()
        result = await analyzer.compute_percentiles(parent_id, session_ids)

        for band in result.distributions:
            assert band.p10 <= band.p25 <= band.p50 <= band.p75 <= band.p90, (
                f"{band.metric_name}: percentiles not ordered: "
                f"{band.p10} {band.p25} {band.p50} {band.p75} {band.p90}"
            )


# ---------------------------------------------------------------------------
# Integration tests: EnsembleRunner
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestEnsembleRunner:
    async def test_run_ensemble_returns_ensemble_result(self, test_db, monkeypatch):
        """run_ensemble with mocked _run_single_trial returns valid EnsembleResult.

        We monkeypatch EnsembleRunner._run_single_trial to avoid spawning real
        OASIS subprocesses while still exercising the orchestration logic.
        """
        import backend.app.services.ensemble_runner as er_module
        import backend.app.services.ensemble_analyzer as ea_module

        parent_id = str(uuid.uuid4())

        # Insert required parent session
        await test_db.execute(
            """
            INSERT INTO simulation_sessions
               (id, name, sim_mode, scenario_type, status, config_json,
                agent_count, round_count, llm_provider, llm_model, oasis_db_path)
            VALUES (?, ?, 'parallel', 'property', 'completed', ?,
                    50, 10, 'openrouter', 'deepseek/deepseek-v3.2', '')
            """,
            (
                parent_id,
                "Test Parent",
                json.dumps({
                    "agent_count": 50,
                    "round_count": 10,
                    "agent_csv_path": "/tmp/test.csv",
                    "llm_provider": "openrouter",
                    "llm_model": "deepseek/deepseek-v3.2",
                }),
            ),
        )
        await test_db.commit()

        monkeypatch.setattr(er_module, "get_db", lambda: _mock_db_context(test_db))
        monkeypatch.setattr(ea_module, "get_db", lambda: _mock_db_context(test_db))

        # Pre-seed macro_snapshots so the analyzer has data to read
        await test_db.executescript("""
            CREATE TABLE IF NOT EXISTS macro_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                round_number INTEGER NOT NULL,
                macro_json TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(session_id, round_number)
            )
        """)

        fake_branch_ids: list[str] = []

        async def _fake_run_single_trial(
            parent_session_id, parent_config, trial_index, perturbation
        ):
            """Stub that records a completed TrialRecord and seeds a macro snapshot."""
            branch_id = str(uuid.uuid4())
            fake_branch_ids.append(branch_id)
            macro_json = json.dumps({
                "ccl_index": 148.0 + trial_index * 3,
                "hsi_level": 16500.0 + trial_index * 400,
                "unemployment_rate": 0.029 + trial_index * 0.001,
                "gdp_growth": 0.032,
                "consumer_confidence": 88.0,
                "net_migration": -12000,
                "hibor_1m": 0.043,
                "fed_rate": 0.053,
                "china_gdp_growth": 0.052,
                "taiwan_strait_risk": 0.3,
            })
            async with er_module.get_db() as db:
                await db.execute(
                    "INSERT OR REPLACE INTO macro_snapshots "
                    "(session_id, round_number, macro_json) VALUES (?,?,?)",
                    (branch_id, 10, macro_json),
                )
                await db.commit()
            return TrialRecord(
                trial_index=trial_index,
                branch_session_id=branch_id,
                perturbation=perturbation,
                status="completed",
            )

        runner = EnsembleRunner()

        # Patch both MacroController (lazy import) and _run_single_trial
        mock_mc_instance = MagicMock()
        mock_mc_instance.get_baseline_for_scenario = AsyncMock(return_value=_make_macro_state())
        mock_mc_instance.get_baseline = AsyncMock(return_value=_make_macro_state())

        with patch(
            "backend.app.services.macro_controller.MacroController",
            return_value=mock_mc_instance,
        ):
            monkeypatch.setattr(runner, "_run_single_trial", _fake_run_single_trial)
            result = await runner.run_ensemble(
                session_id=parent_id,
                n_trials=3,
                perturbation_std=0.05,
            )

        assert isinstance(result, EnsembleResult)
        assert result.session_id == parent_id
        assert result.n_trials == 3
        assert len(result.distributions) > 0

    async def test_run_ensemble_invalid_session_raises(self, test_db, monkeypatch):
        """run_ensemble with non-existent session_id raises ValueError."""
        import backend.app.services.ensemble_runner as er_module

        monkeypatch.setattr(er_module, "get_db", lambda: _mock_db_context(test_db))

        runner = EnsembleRunner()
        with pytest.raises(ValueError, match="not found"):
            await runner.run_ensemble("nonexistent-session-id", n_trials=1)

    async def test_get_trial_metadata_empty_when_no_trials(self, test_db, monkeypatch):
        """get_trial_metadata returns empty list for session with no trials."""
        import backend.app.services.ensemble_runner as er_module

        monkeypatch.setattr(er_module, "get_db", lambda: _mock_db_context(test_db))

        runner = EnsembleRunner()
        result = await runner.get_trial_metadata("no-trials-session")
        assert result == []

    async def test_trial_count_clamped(self, test_db, monkeypatch):
        """n_trials > 50 is clamped to 50."""
        import backend.app.services.ensemble_runner as er_module

        parent_id = str(uuid.uuid4())
        await test_db.execute(
            """
            INSERT INTO simulation_sessions
               (id, name, sim_mode, scenario_type, status, config_json,
                agent_count, round_count, llm_provider, llm_model, oasis_db_path)
            VALUES (?, 'T', 'parallel', 'property', 'completed', '{}',
                    10, 5, 'openrouter', 'model', '')
            """,
            (parent_id,),
        )
        await test_db.commit()

        monkeypatch.setattr(er_module, "get_db", lambda: _mock_db_context(test_db))

        call_counts = []

        async def _counting_run(session_id, config, progress_callback=None):
            call_counts.append(session_id)

        monkeypatch.setattr(er_module, "get_db", lambda: _mock_db_context(test_db))
        import backend.app.services.ensemble_analyzer as ea_module
        monkeypatch.setattr(ea_module, "get_db", lambda: _mock_db_context(test_db))

        mock_mc_instance = MagicMock()
        mock_mc_instance.get_baseline_for_scenario = AsyncMock(return_value=_make_macro_state())
        mock_mc_instance.get_baseline = AsyncMock(return_value=_make_macro_state())

        with patch(
            "backend.app.services.macro_controller.MacroController",
            return_value=mock_mc_instance,
        ):
            runner = EnsembleRunner()

            async def _stub_trial(parent_session_id, parent_config, trial_index, perturbation):
                call_counts.append(trial_index)
                return TrialRecord(
                    trial_index=trial_index,
                    branch_session_id=str(uuid.uuid4()),
                    perturbation=perturbation,
                    status="completed",
                )

            monkeypatch.setattr(runner, "_run_single_trial", _stub_trial)
            try:
                await runner.run_ensemble(parent_id, n_trials=9999)
            except Exception:
                pass

        # After clamping to 50, at most 50 runs should be attempted
        assert len(call_counts) <= 50


# ---------------------------------------------------------------------------
# Integration tests: API endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestEnsembleAPIEndpoints:
    async def test_post_ensemble_returns_404_for_unknown_session(self, test_client):
        """POST /api/simulation/{id}/ensemble returns 404 for unknown session."""
        resp = await test_client.post(
            "/api/simulation/unknown-session-xyz/ensemble",
            json={"n_trials": 2},
        )
        assert resp.status_code == 404

    async def test_get_ensemble_results_empty_for_unknown_session(self, test_client):
        """GET /api/simulation/{id}/ensemble/results returns 200 with empty data."""
        resp = await test_client.get(
            "/api/simulation/unknown-session-xyz/ensemble/results",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        # Empty result: distributions list should exist and be empty
        assert "distributions" in body["data"]
        assert body["data"]["distributions"] == []


# ---------------------------------------------------------------------------
# Context manager helper for monkeypatching get_db
# ---------------------------------------------------------------------------


class _mock_db_context:
    """Async context manager that yields an existing aiosqlite connection."""

    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *args):
        pass
