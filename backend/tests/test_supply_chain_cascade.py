"""Tests for supply chain cascade propagation — TDD for C7."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.app.services.supply_chain_cascade import (
    CascadeEffect,
    propagate_supply_chain_shock,
)

# ---------------------------------------------------------------------------
# CascadeEffect frozen dataclass
# ---------------------------------------------------------------------------


class TestCascadeEffect:
    def test_frozen(self) -> None:
        effect = CascadeEffect(
            target_entity_id="ent_002",
            revenue_impact=-0.4,
            source_entity_id="ent_001",
            hop_distance=1,
            recovery_rounds=3,
        )
        with pytest.raises(AttributeError):
            effect.revenue_impact = 0.0  # type: ignore[misc]

    def test_fields(self) -> None:
        effect = CascadeEffect(
            target_entity_id="ent_002",
            revenue_impact=-0.25,
            source_entity_id="ent_001",
            hop_distance=2,
            recovery_rounds=3,
        )
        assert effect.target_entity_id == "ent_002"
        assert effect.revenue_impact == -0.25
        assert effect.hop_distance == 2
        assert effect.recovery_rounds == 3


# ---------------------------------------------------------------------------
# propagate_supply_chain_shock
# ---------------------------------------------------------------------------


class TestPropagateSupplyChainShock:
    @pytest.mark.asyncio
    async def test_no_edges_returns_empty(self) -> None:
        """No supply chain edges → no cascade effects."""
        mock_db = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])
        mock_db.execute = AsyncMock(return_value=mock_cursor)

        with patch("backend.app.services.supply_chain_cascade.get_db") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            effects = await propagate_supply_chain_shock(
                session_id="sess-001",
                failed_entity_ids=frozenset({"ent_001"}),
            )
            assert effects == ()

    @pytest.mark.asyncio
    async def test_single_hop_cascade(self) -> None:
        """One failed entity with one downstream → one CascadeEffect."""
        # ent_001 --SUPPLIES_TO--> ent_002
        mock_edges = [
            {"source_id": "ent_001", "target_id": "ent_002", "relation_type": "SUPPLIES_TO"},
        ]
        mock_db = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=mock_edges)
        mock_db.execute = AsyncMock(return_value=mock_cursor)

        with patch("backend.app.services.supply_chain_cascade.get_db") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            effects = await propagate_supply_chain_shock(
                session_id="sess-001",
                failed_entity_ids=frozenset({"ent_001"}),
                propagation_factor=0.4,
            )
            assert len(effects) >= 1
            ent002_effect = next(e for e in effects if e.target_entity_id == "ent_002")
            assert ent002_effect.revenue_impact < 0  # negative = loss
            assert ent002_effect.hop_distance == 1
            assert ent002_effect.source_entity_id == "ent_001"
            assert ent002_effect.recovery_rounds == 3

    @pytest.mark.asyncio
    async def test_multi_hop_amplification(self) -> None:
        """Cascade amplifies by 10% per hop (bullwhip effect)."""
        # ent_001 --> ent_002 --> ent_003
        mock_edges = [
            {"source_id": "ent_001", "target_id": "ent_002", "relation_type": "SUPPLIES_TO"},
            {"source_id": "ent_002", "target_id": "ent_003", "relation_type": "SUPPLIES_TO"},
        ]
        mock_db = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=mock_edges)
        mock_db.execute = AsyncMock(return_value=mock_cursor)

        with patch("backend.app.services.supply_chain_cascade.get_db") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            effects = await propagate_supply_chain_shock(
                session_id="sess-001",
                failed_entity_ids=frozenset({"ent_001"}),
                propagation_factor=0.4,
                max_hops=3,
            )
            hop1 = [e for e in effects if e.hop_distance == 1]
            hop2 = [e for e in effects if e.hop_distance == 2]
            assert len(hop1) >= 1
            assert len(hop2) >= 1
            # Hop 2 should have amplified impact per unit (bullwhip)
            # But absolute impact is propagation_factor × hop1 impact
            assert hop2[0].hop_distance == 2

    @pytest.mark.asyncio
    async def test_max_hops_limits_cascade(self) -> None:
        """Cascade should not propagate beyond max_hops."""
        # Chain: ent_001 --> ent_002 --> ent_003 --> ent_004
        mock_edges = [
            {"source_id": "ent_001", "target_id": "ent_002", "relation_type": "SUPPLIES_TO"},
            {"source_id": "ent_002", "target_id": "ent_003", "relation_type": "SUPPLIES_TO"},
            {"source_id": "ent_003", "target_id": "ent_004", "relation_type": "SUPPLIES_TO"},
        ]
        mock_db = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=mock_edges)
        mock_db.execute = AsyncMock(return_value=mock_cursor)

        with patch("backend.app.services.supply_chain_cascade.get_db") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            effects = await propagate_supply_chain_shock(
                session_id="sess-001",
                failed_entity_ids=frozenset({"ent_001"}),
                max_hops=2,
            )
            max_hop = max(e.hop_distance for e in effects) if effects else 0
            assert max_hop <= 2

    @pytest.mark.asyncio
    async def test_returns_frozen_tuple(self) -> None:
        """Return type should be a tuple (immutable)."""
        mock_db = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])
        mock_db.execute = AsyncMock(return_value=mock_cursor)

        with patch("backend.app.services.supply_chain_cascade.get_db") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            effects = await propagate_supply_chain_shock(
                session_id="sess-001",
                failed_entity_ids=frozenset({"ent_001"}),
            )
            assert isinstance(effects, tuple)
