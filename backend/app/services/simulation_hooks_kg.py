"""Knowledge graph and initialisation hooks.

Mixin class extracted from SimulationRunner to keep file sizes manageable.
All methods access SimulationRunner state via ``self`` (cooperative MRO).
"""

from __future__ import annotations

from typing import Any

from backend.app.utils.logger import get_logger

logger = get_logger("simulation_hooks.kg")


class KGHooksMixin:
    """KG snapshot and session initialisation hooks."""

    async def _process_kg_evolution(self, session_id: str, round_number: int) -> None:
        """Evolve the KG from agent activities (Zep-style continuous updates)."""
        try:
            from backend.app.services.kg_graph_updater import KGGraphUpdater  # noqa: PLC0415

            updater = KGGraphUpdater()
            stats = await updater.process_round(session_id, round_number)

            logger.debug(
                "KG evolution session=%s round=%d nodes_added=%d edges_added=%d edges_updated=%d",
                session_id,
                round_number,
                stats.nodes_added,
                stats.edges_added,
                stats.edges_updated,
            )
        except Exception:
            logger.exception(
                "_process_kg_evolution failed session=%s round=%d",
                session_id, round_number,
            )

    async def _process_kg_snapshot(self, session_id: str, round_number: int) -> None:
        """Update KG edge weights from actions and take a snapshot."""
        try:
            from backend.app.services.graph_builder import GraphBuilderService  # noqa: PLC0415
            from backend.app.utils.db import get_db  # noqa: PLC0415

            graph_builder = GraphBuilderService()

            async with get_db() as db:
                cursor = await db.execute(
                    "SELECT action_type, oasis_username FROM simulation_actions "
                    "WHERE session_id = ? AND round_number = ?",
                    (session_id, round_number),
                )
                rows = await cursor.fetchall()

            actions = [
                {"action_type": r[0], "oasis_username": r[1]}
                for r in rows
            ]

            updated = await graph_builder.update_weights_from_actions(session_id, actions)
            saved = await graph_builder.take_snapshot(session_id, round_number)

            logger.debug(
                "KG snapshot session=%s round=%d edges_updated=%d saved=%s",
                session_id, round_number, updated, saved,
            )
        except Exception:
            logger.exception(
                "_process_kg_snapshot failed session=%s round=%d",
                session_id, round_number,
            )

    async def _init_b2b_companies(self, session_id: str) -> None:
        """Generate company profiles for *session_id* if none exist yet (idempotent)."""
        try:
            from backend.app.services.company_factory import CompanyFactory  # noqa: PLC0415
            from backend.app.utils.db import get_db  # noqa: PLC0415

            async with get_db() as db:
                await db.execute(
                    """
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
                    )
                    """
                )
                await db.commit()

                cursor = await db.execute(
                    "SELECT COUNT(*) FROM company_profiles WHERE session_id = ?",
                    (session_id,),
                )
                row = await cursor.fetchone()
                existing_count: int = row[0] if row else 0

            if existing_count > 0:
                logger.debug(
                    "B2B init skipped — %d companies already exist for session=%s",
                    existing_count,
                    session_id,
                )
                return

            factory = CompanyFactory()
            companies = await factory.generate_companies(session_id, count=50)
            await factory.store_companies(session_id, companies)

            logger.info(
                "B2B init: generated and stored %d company profiles for session=%s",
                len(companies),
                session_id,
            )
        except Exception:
            logger.exception(
                "_init_b2b_companies failed for session=%s — continuing without B2B data",
                session_id,
            )

    async def _init_social_network(self, session_id: str) -> None:
        """Build the social network for *session_id* if none exists yet (idempotent)."""
        try:
            from backend.app.utils.db import get_db  # noqa: PLC0415

            async with get_db() as db:
                cursor = await db.execute(
                    "SELECT COUNT(*) FROM agent_relationships WHERE session_id = ?",
                    (session_id,),
                )
                row = await cursor.fetchone()
                if row and row[0] > 0:
                    logger.debug(
                        "Social network init skipped — %d relationships already exist for session=%s",
                        row[0], session_id,
                    )
                    return

                cursor = await db.execute(
                    "SELECT id, district, occupation, extraversion FROM agent_profiles WHERE session_id = ?",
                    (session_id,),
                )
                rows = await cursor.fetchall()

            if not rows:
                logger.debug("Social network init skipped — no agent_profiles for session=%s", session_id)
                return

            profiles = [
                {
                    "id": r[0],
                    "district": r[1] or "",
                    "occupation": r[2] or "",
                    "extraversion": float(r[3]) if r[3] is not None else 0.5,
                }
                for r in rows
            ]

            from backend.app.services.social_network import SocialNetworkBuilder  # noqa: PLC0415
            if self._social_network is None:
                self._social_network = SocialNetworkBuilder()

            network = await self._social_network.build_network(session_id, profiles)
            logger.info(
                "Social network init: %d relationships, %d leaders for session=%s",
                network.edge_count, len(network.opinion_leaders), session_id,
            )
        except Exception:
            logger.exception(
                "_init_social_network failed for session=%s — continuing without social network",
                session_id,
            )

    async def _process_supply_chain_cascade(
        self, session_id: str, round_number: int
    ) -> None:
        """Group 3 periodic: propagate supply chain disruption through KG edges.

        Fires every macro_feedback_interval rounds (default 5) for kg_driven
        sessions. Checks for entities with supply_chain_disruption > 0.3 and
        cascades revenue impacts to downstream entities.
        """
        try:
            from backend.app.utils.db import get_db  # noqa: PLC0415
            from backend.app.services.supply_chain_cascade import (  # noqa: PLC0415
                propagate_supply_chain_shock,
            )

            # Find entities currently under disruption (supply_chain_disruption > 0.3)
            async with get_db() as db:
                cursor = await db.execute(
                    """SELECT DISTINCT source_id
                       FROM kg_edges
                       WHERE session_id = ?
                         AND relation_type = 'SUPPLIES_TO'""",
                    (session_id,),
                )
                rows = await cursor.fetchall()

            if not rows:
                return

            # Use macro state to determine if supply chain disruption is active
            macro_state = getattr(self, "_macro_states", {}).get(session_id)
            if macro_state is None or macro_state.supply_chain_disruption < 0.3:
                return

            # Identify failed entities: for now, use entities with highest centrality
            # as proxies for disrupted upstream nodes
            failed_ids = frozenset(row["source_id"] for row in rows[:5])

            effects = await propagate_supply_chain_shock(
                session_id=session_id,
                failed_entity_ids=failed_ids,
            )

            if effects:
                logger.info(
                    "Supply chain cascade: session=%s round=%d effects=%d",
                    session_id[:8],
                    round_number,
                    len(effects),
                )

        except Exception:
            logger.exception(
                "_process_supply_chain_cascade failed session=%s round=%d",
                session_id[:8],
                round_number,
            )
