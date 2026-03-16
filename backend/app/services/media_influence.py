"""Media influence model for HKSimEngine Phase 6.

Models how major HK media outlets (modelled as special agents) propagate
political opinion shifts to simulation agents each round.

Each media outlet has:
  - political_lean: 0=pro-establishment, 1=pro-democracy
  - influence_radius: max number of agents affected per round
  - credibility: scales receptivity; high credibility → bigger shifts
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.services.political_model import PoliticalModel
from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("media_influence")


# ---------------------------------------------------------------------------
# Frozen dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MediaAgent:
    """Immutable record for a media outlet agent in a simulation session."""

    id: int
    session_id: str
    media_name: str
    political_lean: float    # 0.0–1.0
    influence_radius: int    # max agents affected per round
    credibility: float       # 0.0–1.0


# ---------------------------------------------------------------------------
# Default HK media outlet definitions
# ---------------------------------------------------------------------------

# Credibility and political lean values are informed by HKPORI media
# credibility surveys (2018-2023).  HKPORI measured public trust on a
# 0-10 scale; we normalise to 0-1.  Key findings:
#   - RTHK and SCMP consistently scored highest (7.0-8.0 range)
#   - TVB credibility declined from ~6.5 (2018) to ~5.5 (2023)
#   - 大公報/文匯報 scored lowest (~3.5-4.5)
#   - Independent outlets (inmediahk, 眾新聞) scored ~5.5-6.5
# Political lean is calibrated against HKPORI editorial stance ratings
# and cross-referenced with CUHK journalism school content analysis studies.
# Note: 眾新聞 ceased operations in Jan 2022 but is retained for
# historical simulation scenarios.
DEFAULT_MEDIA_OUTLETS: list[dict[str, Any]] = [
    {
        "media_name": "TVB新聞",
        "political_lean": 0.2,       # HKPORI: perceived pro-establishment
        "influence_radius": 80,       # largest audience share (free-to-air TV)
        "credibility": 0.6,           # HKPORI 2023: ~5.5/10 → 0.55, rounded up
    },
    {
        "media_name": "香港電台RTHK",
        "political_lean": 0.45,       # HKPORI: near-centre, slightly independent
        "influence_radius": 50,
        "credibility": 0.75,          # HKPORI 2018-2020: ~7.5/10 (pre-management change)
    },
    {
        "media_name": "明報",
        "political_lean": 0.55,       # HKPORI: centre-leaning independent
        "influence_radius": 40,
        "credibility": 0.7,           # HKPORI 2023: ~6.8/10
    },
    {
        "media_name": "南華早報",
        "political_lean": 0.5,        # HKPORI: centrist (English-language)
        "influence_radius": 45,
        "credibility": 0.8,           # HKPORI 2023: highest among print (~7.8/10)
    },
    {
        "media_name": "大公報",
        "political_lean": 0.1,        # HKPORI: strongly pro-establishment
        "influence_radius": 30,
        "credibility": 0.4,           # HKPORI 2023: ~3.8/10
    },
    {
        "media_name": "星島日報",
        "political_lean": 0.25,       # HKPORI: pro-establishment
        "influence_radius": 35,
        "credibility": 0.5,           # HKPORI 2023: ~5.0/10
    },
    {
        "media_name": "獨立媒體",
        "political_lean": 0.8,        # HKPORI: pro-democracy
        "influence_radius": 20,       # niche online audience
        "credibility": 0.55,          # HKPORI 2020: ~5.5/10
    },
    {
        "media_name": "眾新聞",
        "political_lean": 0.75,       # HKPORI: pro-democracy (ceased Jan 2022)
        "influence_radius": 15,
        "credibility": 0.6,           # HKPORI 2021: ~6.0/10
    },
]

# Maximum per-round stance shift applied to any single agent (guards against
# runaway drift when many outlets all push in the same direction).
_MAX_SHIFT_PER_ROUND = 0.02

# Receptivity below this threshold → skip the agent (saves DB writes).
_MIN_RECEPTIVITY = 0.05

# Minimum meaningful stance change; smaller deltas are not persisted.
_MIN_STANCE_DELTA = 0.001


# ---------------------------------------------------------------------------
# MediaInfluenceModel
# ---------------------------------------------------------------------------

class MediaInfluenceModel:
    """Models how HK media outlets shift agent political stances over rounds.

    All methods are async.  The ``media_agents`` table is auto-created
    inside ``init_media_agents()`` using CREATE TABLE IF NOT EXISTS.
    """

    # ------------------------------------------------------------------
    # DDL (idempotent)
    # ------------------------------------------------------------------

    async def _ensure_table(self, db: Any) -> None:
        """Create the media_agents table and index if they do not exist."""
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS media_agents (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id       TEXT    NOT NULL,
                media_name       TEXT    NOT NULL,
                political_lean   REAL    NOT NULL DEFAULT 0.5,
                influence_radius INTEGER          DEFAULT 50,
                credibility      REAL             DEFAULT 0.7,
                created_at       TEXT    DEFAULT (datetime('now'))
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_media_session ON media_agents(session_id)"
        )

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    async def init_media_agents(
        self,
        session_id: str,
        outlets: list[dict[str, Any]] | None = None,
    ) -> list[MediaAgent]:
        """Create media agent records for a simulation session.

        If outlets is None, ``DEFAULT_MEDIA_OUTLETS`` is used.  Existing
        records for the session are deleted first so re-init is idempotent.

        Args:
            session_id: UUID of the simulation session.
            outlets: Optional list of outlet definition dicts.  Each must
                     have keys: media_name, political_lean, influence_radius,
                     credibility.

        Returns:
            List of created MediaAgent instances.
        """
        resolved_outlets: list[dict[str, Any]] = outlets or DEFAULT_MEDIA_OUTLETS

        agents: list[MediaAgent] = []
        async with get_db() as db:
            await self._ensure_table(db)

            # Remove any stale records from a previous init for this session.
            await db.execute(
                "DELETE FROM media_agents WHERE session_id = ?",
                (session_id,),
            )

            for outlet in resolved_outlets:
                cursor = await db.execute(
                    """INSERT INTO media_agents
                           (session_id, media_name, political_lean, influence_radius, credibility)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        session_id,
                        outlet["media_name"],
                        float(outlet["political_lean"]),
                        int(outlet["influence_radius"]),
                        float(outlet["credibility"]),
                    ),
                )
                agents.append(
                    MediaAgent(
                        id=cursor.lastrowid,
                        session_id=session_id,
                        media_name=outlet["media_name"],
                        political_lean=float(outlet["political_lean"]),
                        influence_radius=int(outlet["influence_radius"]),
                        credibility=float(outlet["credibility"]),
                    )
                )

            await db.commit()

        logger.info(
            "Initialised %d media agents for session=%s",
            len(agents),
            session_id,
        )
        return agents

    # ------------------------------------------------------------------
    # Data access
    # ------------------------------------------------------------------

    async def get_media_agents(self, session_id: str) -> list[MediaAgent]:
        """Load all media agents for a session from the database.

        Args:
            session_id: UUID of the simulation session.

        Returns:
            List of MediaAgent instances; empty list if session has none.
        """
        async with get_db() as db:
            await self._ensure_table(db)
            rows = await (
                await db.execute(
                    "SELECT * FROM media_agents WHERE session_id = ?",
                    (session_id,),
                )
            ).fetchall()

        return [
            MediaAgent(
                id=int(r["id"]),
                session_id=str(r["session_id"]),
                media_name=str(r["media_name"]),
                political_lean=float(r["political_lean"]),
                influence_radius=int(r["influence_radius"]),
                credibility=float(r["credibility"]),
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Influence propagation
    # ------------------------------------------------------------------

    async def propagate_media_influence(
        self,
        session_id: str,
        round_number: int,
    ) -> dict[str, Any]:
        """Apply media influence to agent political stances for one round.

        Algorithm:
          For each media outlet:
            1. Select the top ``influence_radius`` most-social agents (sorted
               by extraversion DESC) that have a political_stance value.
            2. For each selected agent, compute receptivity:
                  receptivity = max(0, 1 - stance_diff * 1.5) * credibility
               Agents whose stance already aligns with the outlet are most
               receptive; ideologically distant agents are largely unaffected.
            3. Apply a micro-stance shift toward the outlet's lean:
                  shift = (media_lean - current) * receptivity * 0.03
               The shift is clamped to [−_MAX_SHIFT_PER_ROUND, +_MAX_SHIFT_PER_ROUND].
            4. Persist the new stance if |delta| > _MIN_STANCE_DELTA.

        Args:
            session_id: UUID of the simulation session.
            round_number: Current simulation round (used only for logging).

        Returns:
            Dict with keys: influenced_count, media_count, round.
        """
        media_agents = await self.get_media_agents(session_id)
        if not media_agents:
            logger.debug(
                "No media agents for session=%s, skipping propagation", session_id
            )
            return {"influenced_count": 0, "media_count": 0, "round": round_number}

        total_influenced = 0

        async with get_db() as db:
            for media in media_agents:
                # Fetch the most socially active agents (highest extraversion)
                # that already have a political_stance assigned.
                rows = await (
                    await db.execute(
                        """SELECT id, political_stance, extraversion, neuroticism
                           FROM agent_profiles
                           WHERE session_id = ?
                             AND political_stance IS NOT NULL
                           ORDER BY extraversion DESC
                           LIMIT ?""",
                        (session_id, media.influence_radius),
                    )
                ).fetchall()

                for agent_row in rows:
                    agent_id = int(agent_row["id"])
                    current_stance = float(agent_row["political_stance"])

                    stance_diff = abs(current_stance - media.political_lean)

                    # Receptivity: agents ideologically close to outlet are
                    # most affected; the 2.0× multiplier means stances >0.5
                    # apart get zero receptivity (stricter than previous 1.5×).
                    receptivity = (
                        max(0.0, 1.0 - stance_diff * 2.0) * media.credibility
                    )
                    if receptivity < _MIN_RECEPTIVITY:
                        continue

                    # Raw shift — pulls stance toward media's lean.
                    raw_shift = (media.political_lean - current_stance) * receptivity * 0.03

                    # Clamp to prevent large per-round jumps.
                    shift = max(-_MAX_SHIFT_PER_ROUND, min(_MAX_SHIFT_PER_ROUND, raw_shift))

                    new_stance = max(0.0, min(1.0, round(current_stance + shift, 4)))

                    if abs(new_stance - current_stance) < _MIN_STANCE_DELTA:
                        continue

                    await db.execute(
                        """UPDATE agent_profiles
                           SET political_stance = ?
                           WHERE session_id = ? AND id = ?""",
                        (new_stance, session_id, agent_id),
                    )
                    total_influenced += 1

            await db.commit()

            # --- Stance monitoring + depolarization ---
            stance_report = None
            try:
                stance_rows = await (
                    await db.execute(
                        """SELECT political_stance FROM agent_profiles
                           WHERE session_id = ? AND political_stance IS NOT NULL""",
                        (session_id,),
                    )
                ).fetchall()
                if stance_rows:
                    stances = [float(r["political_stance"]) for r in stance_rows]
                    pol_model = PoliticalModel()
                    stance_report = pol_model.monitor_stance_distribution(stances)

                    if stance_report.alert_level != "normal":
                        logger.warning(
                            "POLARIZATION %s session=%s round=%d pi=%.3f extremism=%.3f",
                            stance_report.alert_level.upper(),
                            session_id, round_number,
                            stance_report.polarization_index,
                            stance_report.extremism_ratio,
                        )
                        adjusted = pol_model.apply_depolarization(stances, stance_report.alert_level)
                        # Persist adjusted stances
                        agent_ids = [int(r["id"]) for r in await (
                            await db.execute(
                                """SELECT id FROM agent_profiles
                                   WHERE session_id = ? AND political_stance IS NOT NULL
                                   ORDER BY id""",
                                (session_id,),
                            )
                        ).fetchall()]
                        await db.executemany(
                            "UPDATE agent_profiles SET political_stance = ? WHERE id = ?",
                            list(zip(adjusted, agent_ids)),
                        )
                        await db.commit()
            except Exception:
                logger.exception("Stance monitoring failed session=%s", session_id)

        logger.debug(
            "Media influence propagated session=%s round=%d influenced=%d outlets=%d",
            session_id,
            round_number,
            total_influenced,
            len(media_agents),
        )
        result: dict[str, Any] = {
            "influenced_count": total_influenced,
            "media_count": len(media_agents),
            "round": round_number,
        }
        if stance_report is not None:
            result["stance_report"] = {
                "mean": stance_report.mean,
                "std": stance_report.std,
                "polarization_index": stance_report.polarization_index,
                "extremism_ratio": stance_report.extremism_ratio,
                "alert_level": stance_report.alert_level,
            }
        return result
