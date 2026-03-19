"""Supply chain graph builder for Phase 5 B2B enterprise simulation.

Builds supply chain relationships as Knowledge Graph nodes and edges,
reflecting the inter-company dependencies present in Hong Kong's economy.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Sequence

from backend.app.models.company import CompanyProfile
from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("supply_chain_builder")

# ---------------------------------------------------------------------------
# Relationship type constants
# ---------------------------------------------------------------------------

REL_SUPPLIES_TO = "SUPPLIES_TO"
REL_BUYS_FROM = "BUYS_FROM"
REL_DEPENDS_ON = "DEPENDS_ON"
REL_FINANCES = "FINANCES"
REL_DISTRIBUTES = "DISTRIBUTES"

# ---------------------------------------------------------------------------
# Thresholds for auto-linking
# ---------------------------------------------------------------------------

_MAX_SUPPLY_LINKS_PER_UPSTREAM = 4   # max buyers per upstream company
_MAX_SUPPLY_LINKS_PER_DOWNSTREAM = 3  # max suppliers per downstream company
_MAX_LOGISTICS_LINKS = 6             # max clients per logistics firm
_MAX_FINANCE_LINKS = 5               # max portfolio companies per finance firm
_SAME_DISTRICT_WEIGHT_BONUS = 0.15   # extra edge weight for same-district pair
_INDUSTRY_PROXIMITY_WEIGHTS: dict[tuple[str, str], float] = {
    ("manufacturing", "import_export"): 0.9,
    ("manufacturing", "logistics"): 0.8,
    ("manufacturing", "retail"): 0.7,
    ("import_export", "retail"): 0.85,
    ("import_export", "logistics"): 0.80,
    ("logistics", "retail"): 0.75,
    ("logistics", "manufacturing"): 0.80,
    ("finance", "real_estate"): 0.70,
    ("finance", "tech"): 0.65,
    ("tech", "retail"): 0.60,
    ("tech", "finance"): 0.65,
}


# ---------------------------------------------------------------------------
# Immutable result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SupplyChainEdge:
    """Immutable supply chain relationship between two company KG nodes."""

    source_company_id: int
    target_company_id: int
    relation_type: str
    weight: float
    session_id: str


@dataclass(frozen=True)
class SupplyChainGraph:
    """Immutable snapshot of a session's supply chain network."""

    session_id: str
    node_count: int
    edge_count: int
    edges: tuple[SupplyChainEdge, ...]


# ---------------------------------------------------------------------------
# SupplyChainBuilder
# ---------------------------------------------------------------------------


class SupplyChainBuilder:
    """Build and store supply chain KG nodes and edges for a session."""

    def __init__(self, rng_seed: int | None = None) -> None:
        self._rng = random.Random(rng_seed)

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    async def build_supply_chain(
        self,
        session_id: str,
        companies: list[CompanyProfile],
        graph_id: str | None = None,
    ) -> SupplyChainGraph:
        """Generate and store KG nodes/edges for the supply chain.

        Steps:
        1. Insert one KG node per company.
        2. Link upstream manufacturers → midstream distributors/importers.
        3. Link midstream → downstream retailers.
        4. Link logistics firms to all other companies.
        5. Link finance firms to selected companies.
        6. Store all edges in kg_edges.

        Args:
            session_id: Simulation session UUID.
            companies: List of ``CompanyProfile`` instances (must have id set).
            graph_id: Optional graph_id prefix for KG nodes. If None, uses
                session_id[:8].

        Returns:
            ``SupplyChainGraph`` with node_count, edge_count, and edges.
        """
        if not companies:
            logger.warning("build_supply_chain called with empty company list")
            return SupplyChainGraph(
                session_id=session_id,
                node_count=0,
                edge_count=0,
                edges=(),
            )

        graph_prefix = (graph_id or session_id)[:8]

        # Partition companies by position
        upstream = [c for c in companies if c.supply_chain_position == "upstream"]
        midstream = [c for c in companies if c.supply_chain_position == "midstream"]
        downstream = [c for c in companies if c.supply_chain_position == "downstream"]
        logistics_firms = [c for c in companies if c.industry_sector == "logistics"]
        finance_firms = [c for c in companies if c.industry_sector == "finance"]
        non_logistics = [c for c in companies if c.industry_sector != "logistics"]

        # ---- Insert KG nodes ----
        await self._insert_company_nodes(session_id, graph_prefix, companies)

        # ---- Build edges ----
        edges: list[SupplyChainEdge] = []

        # upstream → midstream (SUPPLIES_TO)
        edges.extend(
            self._link_tiers(
                session_id,
                suppliers=upstream,
                buyers=midstream,
                relation=REL_SUPPLIES_TO,
                max_links=_MAX_SUPPLY_LINKS_PER_UPSTREAM,
            )
        )

        # midstream → downstream (SUPPLIES_TO)
        edges.extend(
            self._link_tiers(
                session_id,
                suppliers=midstream,
                buyers=downstream,
                relation=REL_SUPPLIES_TO,
                max_links=_MAX_SUPPLY_LINKS_PER_DOWNSTREAM,
            )
        )

        # downstream → upstream (BUYS_FROM) — reverse reference for major retailers
        edges.extend(
            self._link_tiers(
                session_id,
                suppliers=downstream,
                buyers=upstream,
                relation=REL_BUYS_FROM,
                max_links=2,
                bidirectional=False,
            )
        )

        # logistics → everyone (DEPENDS_ON)
        edges.extend(
            self._link_logistics(session_id, logistics_firms, non_logistics)
        )

        # finance → companies (FINANCES)
        edges.extend(
            self._link_finance(session_id, finance_firms, companies)
        )

        # Store edges in DB
        await self._insert_edges(session_id, graph_prefix, edges)

        logger.info(
            "Built supply chain for session=%s: %d nodes, %d edges",
            session_id,
            len(companies),
            len(edges),
        )

        return SupplyChainGraph(
            session_id=session_id,
            node_count=len(companies),
            edge_count=len(edges),
            edges=tuple(edges),
        )

    async def get_supply_chain(
        self,
        session_id: str,
        graph_id: str | None = None,
    ) -> list[dict]:
        """Retrieve supply chain edges from kg_edges for a session.

        Args:
            session_id: Simulation session UUID.
            graph_id: Optional graph_id to filter by.

        Returns:
            List of edge dicts with source_id, target_id, relation_type, weight.
        """
        async with get_db() as db:
            if graph_id:
                cursor = await db.execute(
                    """
                    SELECT source_id, target_id, relation_type, weight
                    FROM kg_edges
                    WHERE graph_id = ?
                      AND relation_type IN (?, ?, ?, ?, ?)
                    ORDER BY weight DESC
                    """,
                    (
                        graph_id,
                        REL_SUPPLIES_TO,
                        REL_BUYS_FROM,
                        REL_DEPENDS_ON,
                        REL_FINANCES,
                        REL_DISTRIBUTES,
                    ),
                )
            else:
                cursor = await db.execute(
                    """
                    SELECT e.source_id, e.target_id, e.relation_type, e.weight
                    FROM kg_edges e
                    JOIN kg_nodes n ON n.id = e.source_id
                    WHERE n.properties LIKE ?
                      AND e.relation_type IN (?, ?, ?, ?, ?)
                    ORDER BY e.weight DESC
                    """,
                    (
                        f'%"session_id": "{session_id}"%',
                        REL_SUPPLIES_TO,
                        REL_BUYS_FROM,
                        REL_DEPENDS_ON,
                        REL_FINANCES,
                        REL_DISTRIBUTES,
                    ),
                )
            rows = await cursor.fetchall()

        return [dict(row) for row in rows]

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _calc_edge_weight(
        self,
        company_a: CompanyProfile,
        company_b: CompanyProfile,
    ) -> float:
        """Compute edge weight based on industry proximity + district bonus."""
        # Industry proximity lookup (symmetric)
        pair_fwd = (company_a.industry_sector, company_b.industry_sector)
        pair_rev = (company_b.industry_sector, company_a.industry_sector)
        base_weight = (
            _INDUSTRY_PROXIMITY_WEIGHTS.get(pair_fwd)
            or _INDUSTRY_PROXIMITY_WEIGHTS.get(pair_rev)
            or 0.5
        )

        # District bonus
        bonus = _SAME_DISTRICT_WEIGHT_BONUS if company_a.district == company_b.district else 0.0

        # China exposure similarity (closer = stronger relationship for trade)
        exposure_similarity = 1.0 - abs(company_a.china_exposure - company_b.china_exposure)
        exposure_factor = 0.1 * exposure_similarity

        raw = base_weight + bonus + exposure_factor
        return round(min(1.0, raw), 3)

    def _link_tiers(
        self,
        session_id: str,
        suppliers: list[CompanyProfile],
        buyers: list[CompanyProfile],
        relation: str,
        max_links: int,
        bidirectional: bool = False,
    ) -> list[SupplyChainEdge]:
        """Create edges from each supplier to up to *max_links* buyers."""
        if not suppliers or not buyers:
            return []

        edges: list[SupplyChainEdge] = []
        seen: set[tuple[int, int, str]] = set()

        for supplier in suppliers:
            # Sort buyers by descending edge weight, then sample
            buyer_pool = sorted(
                buyers,
                key=lambda b: self._calc_edge_weight(supplier, b),
                reverse=True,
            )
            k = min(max_links, len(buyer_pool))
            chosen = buyer_pool[:k]

            for buyer in chosen:
                key_fwd = (supplier.id, buyer.id, relation)
                if key_fwd not in seen:
                    seen.add(key_fwd)
                    edges.append(
                        SupplyChainEdge(
                            source_company_id=supplier.id,
                            target_company_id=buyer.id,
                            relation_type=relation,
                            weight=self._calc_edge_weight(supplier, buyer),
                            session_id=session_id,
                        )
                    )

        return edges

    def _link_logistics(
        self,
        session_id: str,
        logistics_firms: list[CompanyProfile],
        clients: list[CompanyProfile],
    ) -> list[SupplyChainEdge]:
        """Link each logistics firm to up to *_MAX_LOGISTICS_LINKS* clients."""
        if not logistics_firms or not clients:
            return []

        edges: list[SupplyChainEdge] = []
        seen: set[tuple[int, int]] = set()

        for logistics in logistics_firms:
            sample_size = min(_MAX_LOGISTICS_LINKS, len(clients))
            chosen = self._rng.sample(clients, sample_size)

            for client in chosen:
                key = (logistics.id, client.id)
                if key not in seen:
                    seen.add(key)
                    edges.append(
                        SupplyChainEdge(
                            source_company_id=client.id,
                            target_company_id=logistics.id,
                            relation_type=REL_DEPENDS_ON,
                            weight=self._calc_edge_weight(client, logistics),
                            session_id=session_id,
                        )
                    )

        return edges

    def _link_finance(
        self,
        session_id: str,
        finance_firms: list[CompanyProfile],
        companies: list[CompanyProfile],
    ) -> list[SupplyChainEdge]:
        """Link each finance firm to selected companies it finances."""
        if not finance_firms:
            return []

        non_finance = [c for c in companies if c.industry_sector != "finance"]
        if not non_finance:
            return []

        edges: list[SupplyChainEdge] = []
        seen: set[tuple[int, int]] = set()

        for fin in finance_firms:
            sample_size = min(_MAX_FINANCE_LINKS, len(non_finance))
            chosen = self._rng.sample(non_finance, sample_size)

            for client in chosen:
                key = (fin.id, client.id)
                if key not in seen:
                    seen.add(key)
                    edges.append(
                        SupplyChainEdge(
                            source_company_id=fin.id,
                            target_company_id=client.id,
                            relation_type=REL_FINANCES,
                            weight=round(
                                0.5 + 0.3 * client.china_exposure, 3
                            ),
                            session_id=session_id,
                        )
                    )

        return edges

    async def _insert_company_nodes(
        self,
        session_id: str,
        graph_prefix: str,
        companies: list[CompanyProfile],
    ) -> None:
        """Insert KG nodes for each company into kg_nodes."""
        import json

        rows = []
        for company in companies:
            node_id = f"{graph_prefix}_company_{company.id}"
            title = company.company_name
            props = json.dumps(
                {
                    "company_id": company.id,
                    "session_id": session_id,
                    "company_type": company.company_type,
                    "industry_sector": company.industry_sector,
                    "company_size": company.company_size,
                    "district": company.district,
                    "supply_chain_position": company.supply_chain_position,
                    "annual_revenue_hkd": company.annual_revenue_hkd,
                    "employee_count": company.employee_count,
                    "china_exposure": company.china_exposure,
                    "export_ratio": company.export_ratio,
                },
                ensure_ascii=False,
            )
            rows.append((node_id, session_id, "Company", title, props))

        async with get_db() as db:
            await db.executemany(
                """
                INSERT OR IGNORE INTO kg_nodes
                    (id, session_id, entity_type, title, properties)
                VALUES (?, ?, ?, ?, ?)
                """,
                rows,
            )
            await db.commit()

        logger.debug("Inserted %d company KG nodes", len(rows))

    async def _insert_edges(
        self,
        session_id: str,
        graph_prefix: str,
        edges: list[SupplyChainEdge],
    ) -> None:
        """Batch insert supply chain edges into kg_edges."""
        rows = [
            (
                f"{graph_prefix}_company_{e.source_company_id}",
                f"{graph_prefix}_company_{e.target_company_id}",
                session_id,
                e.relation_type,
                e.weight,
            )
            for e in edges
        ]

        async with get_db() as db:
            await db.executemany(
                """
                INSERT OR IGNORE INTO kg_edges
                    (source_id, target_id, session_id, relation_type, weight)
                VALUES (?, ?, ?, ?, ?)
                """,
                rows,
            )
            await db.commit()

        logger.debug("Inserted %d supply chain edges into kg_edges", len(rows))
