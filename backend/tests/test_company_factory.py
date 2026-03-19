"""Tests for CompanyFactory, SupplyChainBuilder, and B2B auto-generation in
create_simulation.

Coverage targets:
  - CompanyFactory.generate_companies: count, sector/size distribution, uniqueness
  - CompanyFactory.store_companies / load_companies: DB round-trip
  - SupplyChainBuilder.build_supply_chain: node/edge creation, immutability
  - create_simulation endpoint: auto-trigger on b2b scenario + explicit company_count
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.models.company import CompanyProfile, CompanyType
from backend.app.services.company_factory import (
    DEFAULT_SECTOR_DIST,
    DEFAULT_SIZE_DIST,
    CompanyFactory,
    _normalise,
)
from backend.app.services.supply_chain_builder import (
    REL_FINANCES,
    REL_SUPPLIES_TO,
    SupplyChainBuilder,
    SupplyChainEdge,
    SupplyChainGraph,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_profile(
    *,
    id: int = 1,
    session_id: str = "test-session",
    company_name: str = "測試公司有限公司",
    company_type: str = CompanyType.TRADER,
    industry_sector: str = "import_export",
    company_size: str = "sme",
    district: str = "中西區",
    supply_chain_position: str = "midstream",
    annual_revenue_hkd: int = 10_000_000,
    employee_count: int = 50,
    china_exposure: float = 0.5,
    export_ratio: float = 0.3,
) -> CompanyProfile:
    """Create a CompanyProfile for testing (no DB interaction)."""
    return CompanyProfile(
        id=id,
        session_id=session_id,
        company_name=company_name,
        company_type=company_type,
        industry_sector=industry_sector,
        company_size=company_size,
        district=district,
        supply_chain_position=supply_chain_position,
        annual_revenue_hkd=annual_revenue_hkd,
        employee_count=employee_count,
        china_exposure=china_exposure,
        export_ratio=export_ratio,
    )


# ---------------------------------------------------------------------------
# _normalise utility
# ---------------------------------------------------------------------------


class TestNormalise:
    def test_already_normalised(self):
        dist = {"a": 0.6, "b": 0.4}
        result = _normalise(dist)
        assert abs(sum(result.values()) - 1.0) < 1e-9
        assert result["a"] == pytest.approx(0.6)

    def test_unnormalised(self):
        dist = {"a": 2.0, "b": 3.0}
        result = _normalise(dist)
        assert abs(sum(result.values()) - 1.0) < 1e-9
        assert result["a"] == pytest.approx(0.4)
        assert result["b"] == pytest.approx(0.6)

    def test_raises_on_zero_total(self):
        with pytest.raises(ValueError, match="positive value"):
            _normalise({"a": 0.0})

    def test_does_not_mutate_input(self):
        dist = {"x": 1.0, "y": 1.0}
        original = dict(dist)
        _normalise(dist)
        assert dist == original


# ---------------------------------------------------------------------------
# CompanyProfile immutability
# ---------------------------------------------------------------------------


class TestCompanyProfileImmutability:
    def test_frozen_raises_on_mutation(self):
        profile = _make_profile()
        with pytest.raises((AttributeError, TypeError)):
            profile.company_name = "修改後的名稱"  # type: ignore[misc]

    def test_replace_creates_new_instance(self):
        profile = _make_profile(company_name="原始公司")
        updated = replace(profile, company_name="更新公司")
        assert updated.company_name == "更新公司"
        assert profile.company_name == "原始公司"
        assert profile is not updated


# ---------------------------------------------------------------------------
# CompanyFactory.generate_companies
# ---------------------------------------------------------------------------


class TestCompanyFactoryGenerate:
    @pytest.mark.asyncio
    async def test_generates_exact_count(self):
        factory = CompanyFactory(rng_seed=42)
        companies = await factory.generate_companies("sess-001", count=15)
        assert len(companies) == 15

    @pytest.mark.asyncio
    async def test_all_profiles_are_frozen(self):
        factory = CompanyFactory(rng_seed=1)
        companies = await factory.generate_companies("sess-002", count=5)
        for c in companies:
            with pytest.raises((AttributeError, TypeError)):
                c.employee_count = 9999  # type: ignore[misc]

    @pytest.mark.asyncio
    async def test_id_is_zero_before_store(self):
        factory = CompanyFactory(rng_seed=2)
        companies = await factory.generate_companies("sess-003", count=3)
        for c in companies:
            assert c.id == 0

    @pytest.mark.asyncio
    async def test_session_id_preserved(self):
        session_id = "unique-session-xyz"
        factory = CompanyFactory(rng_seed=3)
        companies = await factory.generate_companies(session_id, count=5)
        assert all(c.session_id == session_id for c in companies)

    @pytest.mark.asyncio
    async def test_sector_distribution_within_expected_range(self):
        """With 100 companies the sector distribution should loosely match defaults."""
        factory = CompanyFactory(rng_seed=99)
        companies = await factory.generate_companies("sess-004", count=100)
        sectors = [c.industry_sector for c in companies]
        # import_export should be the most common sector (~25%)
        ie_count = sectors.count("import_export")
        assert 10 <= ie_count <= 45  # Allow wide tolerance for random seed

    @pytest.mark.asyncio
    async def test_size_distribution_has_sme_majority(self):
        factory = CompanyFactory(rng_seed=77)
        companies = await factory.generate_companies("sess-005", count=100)
        sme_count = sum(1 for c in companies if c.company_size == "sme")
        # SME default weight = 0.75 → expect majority
        assert sme_count > 50

    @pytest.mark.asyncio
    async def test_china_exposure_clamped_to_unit_interval(self):
        factory = CompanyFactory(rng_seed=55)
        companies = await factory.generate_companies("sess-006", count=50)
        for c in companies:
            assert 0.0 <= c.china_exposure <= 1.0
            assert 0.0 <= c.export_ratio <= 1.0

    @pytest.mark.asyncio
    async def test_revenue_within_size_bounds(self):
        from backend.app.services.company_factory import _REVENUE_BY_SIZE

        factory = CompanyFactory(rng_seed=11)
        companies = await factory.generate_companies("sess-007", count=40)
        for c in companies:
            lo, hi = _REVENUE_BY_SIZE[c.company_size]
            assert lo <= c.annual_revenue_hkd <= hi

    @pytest.mark.asyncio
    async def test_custom_sector_distribution(self):
        """Custom distribution overrides default."""
        factory = CompanyFactory(rng_seed=22)
        custom_dist = {"finance": 1.0}  # All finance
        companies = await factory.generate_companies(
            "sess-008", count=10, sector_distribution=custom_dist
        )
        assert all(c.industry_sector == "finance" for c in companies)

    @pytest.mark.asyncio
    async def test_company_names_are_nonempty(self):
        factory = CompanyFactory(rng_seed=33)
        companies = await factory.generate_companies("sess-009", count=10)
        assert all(c.company_name for c in companies)

    @pytest.mark.asyncio
    async def test_large_generation_is_fast(self):
        """500 companies should generate without timing out (pure CPU)."""
        factory = CompanyFactory(rng_seed=44)
        companies = await factory.generate_companies("sess-010", count=500)
        assert len(companies) == 500


# ---------------------------------------------------------------------------
# CompanyFactory.store_companies + load_companies (real aiosqlite)
# ---------------------------------------------------------------------------


class TestCompanyFactoryDB:
    @pytest.mark.asyncio
    async def test_store_returns_profiles_with_ids(self, test_db, test_db_path):
        session_id = str(uuid.uuid4())
        factory = CompanyFactory(rng_seed=1)

        with patch("backend.app.services.company_factory.get_db") as mock_get_db:
            # Wire the context manager to the test_db fixture
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=test_db)
            cm.__aexit__ = AsyncMock(return_value=None)
            mock_get_db.return_value = cm

            companies = await factory.generate_companies(session_id, count=5)
            stored = await factory.store_companies(session_id, companies)

        assert len(stored) == 5
        for c in stored:
            assert c.id > 0
            assert c.session_id == session_id

    @pytest.mark.asyncio
    async def test_store_preserves_company_fields(self, test_db):
        session_id = str(uuid.uuid4())
        factory = CompanyFactory(rng_seed=7)

        with patch("backend.app.services.company_factory.get_db") as mock_get_db:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=test_db)
            cm.__aexit__ = AsyncMock(return_value=None)
            mock_get_db.return_value = cm

            companies = await factory.generate_companies(session_id, count=3)
            stored = await factory.store_companies(session_id, companies)

        # Verify a specific company's fields survived the round-trip
        original = companies[0]
        matched = next(s for s in stored if s.company_name == original.company_name)
        assert matched.company_type == original.company_type
        assert matched.industry_sector == original.industry_sector
        assert matched.company_size == original.company_size
        assert matched.china_exposure == pytest.approx(original.china_exposure, abs=1e-4)

    @pytest.mark.asyncio
    async def test_load_companies_returns_stored(self, test_db):
        session_id = str(uuid.uuid4())
        factory = CompanyFactory(rng_seed=8)

        def _make_cm():
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=test_db)
            cm.__aexit__ = AsyncMock(return_value=None)
            return cm

        with patch("backend.app.services.company_factory.get_db", side_effect=_make_cm):
            companies = await factory.generate_companies(session_id, count=4)
            await factory.store_companies(session_id, companies)
            loaded = await factory.load_companies(session_id)

        assert len(loaded) == 4
        assert all(c.session_id == session_id for c in loaded)
        assert all(c.id > 0 for c in loaded)

    @pytest.mark.asyncio
    async def test_stored_companies_are_frozen(self, test_db):
        session_id = str(uuid.uuid4())
        factory = CompanyFactory(rng_seed=9)

        with patch("backend.app.services.company_factory.get_db") as mock_get_db:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=test_db)
            cm.__aexit__ = AsyncMock(return_value=None)
            mock_get_db.return_value = cm

            companies = await factory.generate_companies(session_id, count=2)
            stored = await factory.store_companies(session_id, companies)

        for c in stored:
            with pytest.raises((AttributeError, TypeError)):
                c.annual_revenue_hkd = 0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# SupplyChainBuilder
# ---------------------------------------------------------------------------


class TestSupplyChainBuilder:
    def _make_companies(
        self,
        session_id: str,
        positions: list[tuple[int, str, str]],
    ) -> list[CompanyProfile]:
        """positions: list of (id, supply_chain_position, industry_sector)"""
        return [
            _make_profile(
                id=pid,
                session_id=session_id,
                supply_chain_position=pos,
                industry_sector=sector,
            )
            for pid, pos, sector in positions
        ]

    @pytest.mark.asyncio
    async def test_empty_companies_returns_zero_graph(self, test_db):
        session_id = str(uuid.uuid4())
        builder = SupplyChainBuilder(rng_seed=1)

        with patch("backend.app.services.supply_chain_builder.get_db") as mock_get_db:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=test_db)
            cm.__aexit__ = AsyncMock(return_value=None)
            mock_get_db.return_value = cm

            result = await builder.build_supply_chain(session_id, [])

        assert isinstance(result, SupplyChainGraph)
        assert result.node_count == 0
        assert result.edge_count == 0
        assert result.edges == ()

    def _make_mock_db_cm(self):
        """Return a mock async context manager that simulates a DB connection."""
        mock_db = AsyncMock()
        mock_db.executemany = AsyncMock()
        mock_db.commit = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_db)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    @pytest.mark.asyncio
    async def test_supply_chain_graph_is_frozen(self):
        session_id = str(uuid.uuid4())
        builder = SupplyChainBuilder(rng_seed=2)
        companies = self._make_companies(
            session_id,
            [(1, "upstream", "manufacturing"), (2, "downstream", "retail")],
        )

        with patch(
            "backend.app.services.supply_chain_builder.get_db",
            return_value=self._make_mock_db_cm(),
        ):
            result = await builder.build_supply_chain(session_id, companies)

        with pytest.raises((AttributeError, TypeError)):
            result.node_count = 999  # type: ignore[misc]

    @pytest.mark.asyncio
    async def test_supply_chain_edges_are_frozen(self):
        session_id = str(uuid.uuid4())
        builder = SupplyChainBuilder(rng_seed=3)
        companies = self._make_companies(
            session_id,
            [(1, "upstream", "manufacturing"), (2, "midstream", "import_export")],
        )

        with patch(
            "backend.app.services.supply_chain_builder.get_db",
            return_value=self._make_mock_db_cm(),
        ):
            result = await builder.build_supply_chain(session_id, companies)

        for edge in result.edges:
            with pytest.raises((AttributeError, TypeError)):
                edge.weight = 99.9  # type: ignore[misc]

    @pytest.mark.asyncio
    async def test_upstream_to_midstream_supplies_to(self):
        session_id = str(uuid.uuid4())
        builder = SupplyChainBuilder(rng_seed=4)
        companies = self._make_companies(
            session_id,
            [
                (1, "upstream", "manufacturing"),
                (2, "midstream", "import_export"),
                (3, "midstream", "logistics"),
            ],
        )

        with patch(
            "backend.app.services.supply_chain_builder.get_db",
            return_value=self._make_mock_db_cm(),
        ):
            result = await builder.build_supply_chain(session_id, companies)

        supplies_edges = [e for e in result.edges if e.relation_type == REL_SUPPLIES_TO]
        # manufacturer (upstream) should link to midstream companies
        assert len(supplies_edges) > 0

    @pytest.mark.asyncio
    async def test_finance_firms_create_finances_edges(self):
        session_id = str(uuid.uuid4())
        builder = SupplyChainBuilder(rng_seed=5)
        companies = self._make_companies(
            session_id,
            [
                (1, "midstream", "finance"),
                (2, "upstream", "manufacturing"),
                (3, "downstream", "retail"),
            ],
        )

        with patch(
            "backend.app.services.supply_chain_builder.get_db",
            return_value=self._make_mock_db_cm(),
        ):
            result = await builder.build_supply_chain(session_id, companies)

        finance_edges = [e for e in result.edges if e.relation_type == REL_FINANCES]
        assert len(finance_edges) > 0

    @pytest.mark.asyncio
    async def test_node_count_equals_company_count(self):
        session_id = str(uuid.uuid4())
        builder = SupplyChainBuilder(rng_seed=6)
        n_companies = 8
        positions = [
            (i + 1, ["upstream", "midstream", "downstream"][i % 3], "import_export")
            for i in range(n_companies)
        ]
        companies = self._make_companies(session_id, positions)

        with patch(
            "backend.app.services.supply_chain_builder.get_db",
            return_value=self._make_mock_db_cm(),
        ):
            result = await builder.build_supply_chain(session_id, companies)

        assert result.node_count == n_companies

    def test_edge_weight_same_district_bonus(self):
        """Same-district pairs get a weight bonus."""
        builder = SupplyChainBuilder(rng_seed=7)
        a = _make_profile(id=1, district="灣仔", industry_sector="manufacturing", supply_chain_position="upstream")
        b_same = _make_profile(id=2, district="灣仔", industry_sector="retail", supply_chain_position="downstream")
        b_diff = _make_profile(id=3, district="元朗", industry_sector="retail", supply_chain_position="downstream")

        weight_same = builder._calc_edge_weight(a, b_same)
        weight_diff = builder._calc_edge_weight(a, b_diff)
        assert weight_same > weight_diff

    def test_edge_weight_clamped_to_unit_interval(self):
        builder = SupplyChainBuilder(rng_seed=8)
        a = _make_profile(id=1, china_exposure=1.0)
        b = _make_profile(id=2, china_exposure=1.0, district="灣仔")
        weight = builder._calc_edge_weight(a, b)
        assert 0.0 <= weight <= 1.0


# ---------------------------------------------------------------------------
# B2B auto-trigger detection logic
# ---------------------------------------------------------------------------


class TestB2BAutoTriggerDetection:
    """Unit tests for the scenario-keyword B2B auto-trigger logic."""

    @pytest.mark.parametrize(
        "scenario_type,expected_trigger",
        [
            ("b2b", True),
            ("trade", True),
            ("supply_chain", True),
            ("enterprise", True),
            ("B2B_TRADE", True),        # case-insensitive
            ("property", False),
            ("emigration", False),
            ("fertility", False),
            ("macro", False),
            ("", False),
        ],
    )
    def test_b2b_keywords_in_scenario_type(self, scenario_type, expected_trigger):
        from backend.app.models.request import _B2B_SCENARIO_KEYWORDS

        scenario_lower = scenario_type.lower()
        triggered = any(kw in scenario_lower for kw in _B2B_SCENARIO_KEYWORDS)
        assert triggered == expected_trigger

    def test_explicit_company_count_overrides_scenario(self):
        """company_count > 0 should force generation even on non-B2B scenarios."""
        from backend.app.models.request import SimulationCreateRequest

        req = SimulationCreateRequest(
            graph_id="g-1",
            scenario_type="property",
            company_count=20,
        )
        assert req.company_count == 20

    def test_default_company_count_is_zero(self):
        from backend.app.models.request import SimulationCreateRequest

        req = SimulationCreateRequest(graph_id="g-1", scenario_type="property")
        assert req.company_count == 0

    def test_negative_company_count_rejected(self):
        from pydantic import ValidationError

        from backend.app.models.request import SimulationCreateRequest

        with pytest.raises(ValidationError):
            SimulationCreateRequest(
                graph_id="g-1",
                scenario_type="property",
                company_count=-5,
            )


# ---------------------------------------------------------------------------
# create_simulation endpoint — B2B auto-generation integration
# ---------------------------------------------------------------------------


class TestCreateSimulationB2BIntegration:
    """Integration tests for the create_simulation endpoint B2B branch.

    The OASIS subprocess is never started in these tests. We mock all service
    calls that would touch the network or filesystem.
    """

    def _base_request(self, **overrides) -> dict:
        req = {
            "graph_id": "g-test-001",
            "scenario_type": "property",
            "agent_count": 5,
            "round_count": 3,
            "platforms": {"facebook": True, "instagram": False},
            "llm_provider": "openrouter",
            "company_count": 0,
        }
        req.update(overrides)
        return req

    @pytest.mark.asyncio
    async def test_no_b2b_generation_when_count_zero_and_non_b2b_scenario(self):
        """create_simulation with property scenario + company_count=0 should NOT
        trigger CompanyFactory."""
        from backend.app.api.simulation import create_simulation
        from backend.app.models.request import SimulationCreateRequest

        req = SimulationCreateRequest(**self._base_request())

        with (
            patch("backend.app.api.simulation.AgentFactory") as mock_af,
            patch("backend.app.api.simulation.ProfileGenerator") as mock_pg,
            patch("backend.app.api.simulation.MacroController") as mock_mc,
            patch("backend.app.api.simulation.get_simulation_manager") as mock_sm,
            patch("backend.app.api.simulation.store_agent_profiles", new=AsyncMock()),
            patch("backend.app.api.simulation.CompanyFactory") as mock_cf,
            patch("backend.app.api.simulation.SupplyChainBuilder") as mock_scb,
            patch("asyncio.to_thread", new=AsyncMock()),
            patch("backend.app.utils.db.get_db") as mock_get_db,
        ):
            _wire_mocks(mock_af, mock_pg, mock_mc, mock_sm, mock_get_db)
            await create_simulation(req)

        mock_cf.assert_not_called()
        mock_scb.assert_not_called()

    @pytest.mark.asyncio
    async def test_b2b_generated_when_scenario_is_b2b(self):
        """Scenario type 'b2b' should trigger B2B generation with default count."""
        from backend.app.api.simulation import _DEFAULT_B2B_COMPANY_COUNT, create_simulation
        from backend.app.models.request import SimulationCreateRequest

        req = SimulationCreateRequest(**self._base_request(scenario_type="b2b"))

        mock_companies = [_make_profile(id=i + 1, session_id="any") for i in range(_DEFAULT_B2B_COMPANY_COUNT)]

        with (
            patch("backend.app.api.simulation.AgentFactory") as mock_af,
            patch("backend.app.api.simulation.ProfileGenerator") as mock_pg,
            patch("backend.app.api.simulation.MacroController") as mock_mc,
            patch("backend.app.api.simulation.get_simulation_manager") as mock_sm,
            patch("backend.app.api.simulation.store_agent_profiles", new=AsyncMock()),
            patch("backend.app.api.simulation.CompanyFactory") as mock_cf,
            patch("backend.app.api.simulation.SupplyChainBuilder") as mock_scb,
            patch("asyncio.to_thread", new=AsyncMock()),
            patch("backend.app.utils.db.get_db") as mock_get_db,
        ):
            _wire_mocks(mock_af, mock_pg, mock_mc, mock_sm, mock_get_db)
            _wire_b2b_mocks(mock_cf, mock_scb, mock_companies)
            result = await create_simulation(req)

        mock_cf.return_value.generate_companies.assert_awaited_once()
        call_kwargs = mock_cf.return_value.generate_companies.call_args
        assert call_kwargs.kwargs.get("count") == _DEFAULT_B2B_COMPANY_COUNT or (
            len(call_kwargs.args) >= 2 and call_kwargs.args[1] == _DEFAULT_B2B_COMPANY_COUNT
        )
        mock_scb.return_value.build_supply_chain.assert_awaited_once()
        assert result.success is True

    @pytest.mark.asyncio
    async def test_explicit_company_count_triggers_b2b(self):
        """Explicit company_count > 0 triggers B2B even on non-b2b scenario."""
        from backend.app.api.simulation import create_simulation
        from backend.app.models.request import SimulationCreateRequest

        req = SimulationCreateRequest(**self._base_request(
            scenario_type="property",
            company_count=10,
        ))
        mock_companies = [_make_profile(id=i + 1, session_id="any") for i in range(10)]

        with (
            patch("backend.app.api.simulation.AgentFactory") as mock_af,
            patch("backend.app.api.simulation.ProfileGenerator") as mock_pg,
            patch("backend.app.api.simulation.MacroController") as mock_mc,
            patch("backend.app.api.simulation.get_simulation_manager") as mock_sm,
            patch("backend.app.api.simulation.store_agent_profiles", new=AsyncMock()),
            patch("backend.app.api.simulation.CompanyFactory") as mock_cf,
            patch("backend.app.api.simulation.SupplyChainBuilder") as mock_scb,
            patch("asyncio.to_thread", new=AsyncMock()),
            patch("backend.app.utils.db.get_db") as mock_get_db,
        ):
            _wire_mocks(mock_af, mock_pg, mock_mc, mock_sm, mock_get_db)
            _wire_b2b_mocks(mock_cf, mock_scb, mock_companies)
            result = await create_simulation(req)

        mock_cf.return_value.generate_companies.assert_awaited_once()
        # Verify count passed matches request
        call_kwargs = mock_cf.return_value.generate_companies.call_args
        count_arg = call_kwargs.kwargs.get("count") or (
            call_kwargs.args[1] if len(call_kwargs.args) >= 2 else None
        )
        assert count_arg == 10

    @pytest.mark.asyncio
    async def test_b2b_failure_does_not_break_create_simulation(self):
        """If B2B generation fails, create_simulation should still return success."""
        from backend.app.api.simulation import create_simulation
        from backend.app.models.request import SimulationCreateRequest

        req = SimulationCreateRequest(**self._base_request(scenario_type="b2b"))

        with (
            patch("backend.app.api.simulation.AgentFactory") as mock_af,
            patch("backend.app.api.simulation.ProfileGenerator") as mock_pg,
            patch("backend.app.api.simulation.MacroController") as mock_mc,
            patch("backend.app.api.simulation.get_simulation_manager") as mock_sm,
            patch("backend.app.api.simulation.store_agent_profiles", new=AsyncMock()),
            patch("backend.app.api.simulation.CompanyFactory") as mock_cf,
            patch("backend.app.api.simulation.SupplyChainBuilder"),
            patch("asyncio.to_thread", new=AsyncMock()),
            patch("backend.app.utils.db.get_db") as mock_get_db,
        ):
            _wire_mocks(mock_af, mock_pg, mock_mc, mock_sm, mock_get_db)
            # Make generate_companies raise an error
            mock_cf.return_value.generate_companies = AsyncMock(
                side_effect=RuntimeError("DB connection failed")
            )
            result = await create_simulation(req)

        # Should still succeed — B2B generation is non-fatal
        assert result.success is True

    @pytest.mark.asyncio
    async def test_trade_scenario_triggers_b2b(self):
        """'trade' keyword in scenario_type triggers B2B."""
        from backend.app.api.simulation import create_simulation
        from backend.app.models.request import SimulationCreateRequest

        req = SimulationCreateRequest(**self._base_request(scenario_type="hk_trade_war"))
        mock_companies = [_make_profile(id=i + 1, session_id="any") for i in range(5)]

        with (
            patch("backend.app.api.simulation.AgentFactory") as mock_af,
            patch("backend.app.api.simulation.ProfileGenerator") as mock_pg,
            patch("backend.app.api.simulation.MacroController") as mock_mc,
            patch("backend.app.api.simulation.get_simulation_manager") as mock_sm,
            patch("backend.app.api.simulation.store_agent_profiles", new=AsyncMock()),
            patch("backend.app.api.simulation.CompanyFactory") as mock_cf,
            patch("backend.app.api.simulation.SupplyChainBuilder") as mock_scb,
            patch("asyncio.to_thread", new=AsyncMock()),
            patch("backend.app.utils.db.get_db") as mock_get_db,
        ):
            _wire_mocks(mock_af, mock_pg, mock_mc, mock_sm, mock_get_db)
            _wire_b2b_mocks(mock_cf, mock_scb, mock_companies)
            result = await create_simulation(req)

        mock_cf.return_value.generate_companies.assert_awaited_once()
        assert result.success is True

    @pytest.mark.asyncio
    async def test_response_meta_includes_b2b_fields_when_generated(self):
        """Response meta should contain company_count and supply_chain_edges when B2B fires."""
        from backend.app.api.simulation import create_simulation
        from backend.app.models.request import SimulationCreateRequest

        req = SimulationCreateRequest(**self._base_request(
            scenario_type="b2b",
            company_count=5,
        ))
        mock_companies = [_make_profile(id=i + 1, session_id="any") for i in range(5)]

        with (
            patch("backend.app.api.simulation.AgentFactory") as mock_af,
            patch("backend.app.api.simulation.ProfileGenerator") as mock_pg,
            patch("backend.app.api.simulation.MacroController") as mock_mc,
            patch("backend.app.api.simulation.get_simulation_manager") as mock_sm,
            patch("backend.app.api.simulation.store_agent_profiles", new=AsyncMock()),
            patch("backend.app.api.simulation.CompanyFactory") as mock_cf,
            patch("backend.app.api.simulation.SupplyChainBuilder") as mock_scb,
            patch("asyncio.to_thread", new=AsyncMock()),
            patch("backend.app.utils.db.get_db") as mock_get_db,
        ):
            _wire_mocks(mock_af, mock_pg, mock_mc, mock_sm, mock_get_db)
            _wire_b2b_mocks(mock_cf, mock_scb, mock_companies, edge_count=7)
            result = await create_simulation(req)

        assert result.meta is not None
        assert result.meta.get("company_count") == 5
        assert result.meta.get("supply_chain_edges") == 7


# ---------------------------------------------------------------------------
# Private test helpers
# ---------------------------------------------------------------------------


def _wire_mocks(mock_af, mock_pg, mock_mc, mock_sm, mock_get_db):
    """Configure the common service mocks used by create_simulation."""
    from backend.app.models.project import SimMode, SessionStatus

    # AgentFactory
    mock_af.return_value.generate_population.return_value = []
    mock_af.return_value.generate_twin.return_value = MagicMock()
    mock_af.return_value.generate_crm_agents.return_value = []

    # ProfileGenerator
    mock_pg.return_value.to_oasis_csv.return_value = "oasis_user,persona\n"

    # MacroController
    mock_mc.return_value.get_baseline_for_scenario = AsyncMock(return_value=MagicMock())

    # SimulationManager
    session_id = str(uuid.uuid4())
    mock_sm.return_value.create_session = AsyncMock(
        return_value={"session_id": session_id, "status": "created"}
    )
    mock_sm.return_value.get_session = AsyncMock(
        return_value={"session_id": session_id, "status": "created"}
    )

    # DB context manager for config_json update
    import json as _json

    async def _fake_fetchone():
        return {"config_json": _json.dumps({"agent_count": 5})}

    mock_cursor = AsyncMock()
    mock_cursor.fetchone = _fake_fetchone

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_cursor)
    mock_db.commit = AsyncMock()

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    mock_get_db.return_value = mock_cm


def _wire_b2b_mocks(mock_cf, mock_scb, mock_companies, edge_count: int = 3):
    """Configure CompanyFactory + SupplyChainBuilder mocks for B2B tests."""
    mock_cf.return_value.generate_companies = AsyncMock(return_value=mock_companies)
    mock_cf.return_value.store_companies = AsyncMock(return_value=mock_companies)

    mock_graph = SupplyChainGraph(
        session_id="test",
        node_count=len(mock_companies),
        edge_count=edge_count,
        edges=tuple(
            SupplyChainEdge(
                source_company_id=1,
                target_company_id=2,
                relation_type=REL_SUPPLIES_TO,
                weight=0.7,
                session_id="test",
            )
            for _ in range(edge_count)
        ),
    )
    mock_scb.return_value.build_supply_chain = AsyncMock(return_value=mock_graph)
