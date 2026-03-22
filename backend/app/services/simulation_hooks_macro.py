"""Macro-economic simulation hooks: feedback loops, credit cycle, news, B2B.

Mixin class extracted from SimulationRunner to keep file sizes manageable.
All methods access SimulationRunner state via ``self`` (cooperative MRO).
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
from typing import Any

from backend.app.utils.logger import get_logger

logger = get_logger("simulation_hooks.macro")

# Per-session cache for ExternalDataFeed results (one fetch per session lifetime).
# Keyed by session_id; value is the merged dict[str, float] returned by
# ExternalDataFeed.fetch_with_db_fallback().
_external_feed_cache: dict[str, dict[str, float]] = {}


class MacroHooksMixin:
    """Periodic hooks for macro-economic phenomena."""

    async def _fetch_external_feed(
        self, session_id: str, *, force_refresh: bool = False,
    ) -> dict[str, float]:
        """Fetch external macro data with per-session caching.

        Returns an empty dict on any error so callers can safely ignore failures.
        The result is cached in the module-level ``_external_feed_cache`` dict
        keyed by *session_id*.  Pass *force_refresh=True* to bypass the cache
        and re-fetch from live APIs (used for periodic refresh every N rounds).
        """
        if not force_refresh and session_id in _external_feed_cache:
            logger.debug(
                "ExternalDataFeed: using cached data for session=%s (%d fields)",
                session_id,
                len(_external_feed_cache[session_id]),
            )
            return _external_feed_cache[session_id]

        try:
            from backend.app.services.external_data_feed import ExternalDataFeed  # noqa: PLC0415
            feed = ExternalDataFeed()
            data = await feed.fetch_with_db_fallback()

            # Detect significant changes since last fetch (for logging)
            prev = _external_feed_cache.get(session_id, {})
            if prev and data:
                from backend.app.services.external_data_feed import detect_significant_changes  # noqa: PLC0415
                changes = detect_significant_changes(prev, data)
                if changes:
                    logger.warning(
                        "ExternalDataFeed: significant changes detected session=%s: %s",
                        session_id,
                        [(f, f"{o:.4f}→{n:.4f}") for f, o, n in changes],
                    )

            _external_feed_cache[session_id] = data
            logger.debug(
                "ExternalDataFeed: fetched and cached %d fields for session=%s: %s",
                len(data),
                session_id,
                sorted(data.keys()),
            )
            return data
        except Exception:
            logger.warning(
                "ExternalDataFeed fetch failed for session=%s — skipping external merge",
                session_id,
                exc_info=True,
            )
            return {}

    async def _process_macro_feedback(
        self,
        session_id: str,
        round_number: int,
    ) -> None:
        """Update MacroState from agent sentiment/topics and persist a snapshot."""
        try:
            if self._kg_mode.get(session_id):
                await self._process_generic_macro_feedback(session_id, round_number)
                return

            from backend.app.services.macro_controller import MacroController  # noqa: PLC0415
            from backend.app.services.macro_history import MacroHistoryService  # noqa: PLC0415

            if self._macro_controller is None:
                self._macro_controller = MacroController()
            if self._macro_history is None:
                self._macro_history = MacroHistoryService()

            if session_id not in self._macro_locks:
                self._macro_locks[session_id] = asyncio.Lock()
            async with self._macro_locks[session_id]:
                if session_id not in self._macro_state:
                    self._macro_state[session_id] = await self._macro_controller.get_baseline()

                current_state = self._macro_state[session_id]

                updated_state = await self._macro_controller.update_from_actions(
                    current_state=current_state,
                    session_id=session_id,
                    round_number=round_number,
                )

                updated_state = self._clamp_macro_state(updated_state)

                # Optionally merge live external macro data into MacroState.
                # Gated behind EXTERNAL_FEED_ENABLED env var (default "false").
                # Refreshes every EXTERNAL_FEED_REFRESH_ROUNDS rounds (default 10).
                # Failures are non-fatal and never crash the simulation.
                if os.environ.get("EXTERNAL_FEED_ENABLED", "false").lower() == "true":
                    refresh_interval = int(os.environ.get("EXTERNAL_FEED_REFRESH_ROUNDS", "10"))
                    should_refresh = (
                        round_number % refresh_interval == 0
                    ) or session_id not in _external_feed_cache
                    external_data = await self._fetch_external_feed(
                        session_id, force_refresh=should_refresh,
                    )
                    if external_data:
                        import dataclasses as _dc  # noqa: PLC0415
                        valid_fields = {f.name for f in _dc.fields(updated_state)}
                        overrides: dict[str, Any] = {}
                        for field_name, value in external_data.items():
                            if field_name in valid_fields and isinstance(value, (int, float)):
                                overrides[field_name] = type(
                                    getattr(updated_state, field_name)
                                )(value)
                        if overrides:
                            updated_state = self._clamp_macro_state(
                                dataclasses.replace(updated_state, **overrides)
                            )
                            logger.debug(
                                "ExternalDataFeed merged into MacroState session=%s "
                                "round=%d fields=%s",
                                session_id,
                                round_number,
                                sorted(overrides.keys()),
                            )

                self._macro_state[session_id] = updated_state

            await self._persist_macro_state(session_id, round_number, updated_state)

            logger.info(
                "Macro feedback applied session=%s round=%d "
                "confidence=%.1f hsi=%.0f unemployment=%.3f ccl=%.1f",
                session_id,
                round_number,
                updated_state.consumer_confidence,
                updated_state.hsi_level,
                updated_state.unemployment_rate,
                updated_state.ccl_index,
            )
        except Exception:
            logger.exception(
                "_process_macro_feedback failed session=%s round=%d",
                session_id,
                round_number,
            )

    async def _process_generic_macro_feedback(
        self,
        session_id: str,
        round_number: int,
    ) -> None:
        """GenericMacroState feedback loop for kg_driven (non-HK) mode.

        Reads agent sentiment from simulation_actions and adjusts each metric
        in the GenericMacroState proportionally to net sentiment polarity.
        """
        from backend.app.services.generic_macro import GenericMacroState  # noqa: PLC0415
        from backend.app.utils.db import get_db  # noqa: PLC0415

        kg_state = self._kg_sessions.get(session_id)
        if kg_state is None:
            return

        if session_id not in self._macro_locks:
            self._macro_locks[session_id] = asyncio.Lock()
        async with self._macro_locks[session_id]:
            # Initialize GenericMacroState from active_metrics if not yet cached
            if session_id not in self._macro_state:
                fields = {k: float(v) for k, v in kg_state.active_metrics.items()}
                self._macro_state[session_id] = GenericMacroState(
                    fields=fields, round_number=round_number,
                )

            current_state = self._macro_state[session_id]
            if not isinstance(current_state, GenericMacroState):
                return

            # Read recent sentiment from simulation_actions
            lookback = max(0, round_number - 4)
            try:
                async with get_db() as db:
                    cursor = await db.execute(
                        """
                        SELECT sentiment FROM simulation_actions
                        WHERE session_id = ? AND round_number BETWEEN ? AND ?
                        """,
                        (session_id, lookback, round_number),
                    )
                    rows = await cursor.fetchall()
            except Exception:
                logger.debug(
                    "_process_generic_macro_feedback: DB read failed session=%s",
                    session_id,
                )
                return

            if not rows:
                return

            # Compute net sentiment polarity (-1 to +1)
            sentiment_map = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}
            total = sum(sentiment_map.get(str(r[0] or "neutral"), 0.0) for r in rows)
            net_polarity = total / len(rows) if rows else 0.0

            # Apply small adjustments to each field based on sentiment
            _FEEDBACK_RATE = 0.02
            updates = {
                k: v + net_polarity * _FEEDBACK_RATE * max(abs(v), 0.01)
                for k, v in current_state.fields.items()
            }
            updated_state = GenericMacroState(
                fields=updates, round_number=round_number,
            )
            self._macro_state[session_id] = updated_state

        # Persist as macro snapshot (best-effort)
        try:
            from backend.app.services.macro_history import MacroHistoryService  # noqa: PLC0415
            if self._macro_history is None:
                self._macro_history = MacroHistoryService()
            await self._macro_history.save_snapshot(
                session_id, round_number, updated_state.to_dict(),
            )
        except Exception:
            logger.debug(
                "_process_generic_macro_feedback: persist failed session=%s round=%d",
                session_id, round_number,
            )

        logger.info(
            "Generic macro feedback applied session=%s round=%d "
            "net_polarity=%.3f fields=%d",
            session_id, round_number, net_polarity, len(updates),
        )

    async def _persist_macro_state(
        self,
        session_id: str,
        round_number: int,
        macro_state: object,
    ) -> None:
        """Persist current macro state to macro_snapshots for restart recovery."""
        try:
            from backend.app.services.macro_history import MacroHistoryService  # noqa: PLC0415
            if self._macro_history is None:
                self._macro_history = MacroHistoryService()
            await self._macro_history.save_snapshot(session_id, round_number, macro_state)
        except Exception:
            logger.exception(
                "_persist_macro_state failed session=%s round=%d",
                session_id, round_number,
            )

    async def _restore_macro_state(self, session_id: str) -> Any:
        """Restore MacroState from the latest macro_snapshot if available."""
        try:
            from backend.app.services.macro_history import MacroHistoryService  # noqa: PLC0415
            from backend.app.services.macro_state import MacroState  # noqa: PLC0415

            if self._macro_history is None:
                self._macro_history = MacroHistoryService()

            history = await self._macro_history.get_history(session_id)
            if not history:
                return None

            last_round = history[-1]["round_number"]
            snapshot = await self._macro_history.get_snapshot(session_id, last_round)
            if not snapshot:
                return None

            from backend.app.services.macro_controller import MacroController  # noqa: PLC0415
            mc = MacroController()
            baseline = await mc.get_baseline()

            valid_fields = {f.name for f in dataclasses.fields(baseline)}
            overrides: dict[str, Any] = {}
            for key, value in snapshot.items():
                if key in valid_fields and value is not None:
                    overrides[key] = value

            if overrides:
                restored = dataclasses.replace(baseline, **overrides)
                logger.info(
                    "Restored macro state session=%s from round=%d (%d fields)",
                    session_id, last_round, len(overrides),
                )
                return restored
            return None
        except Exception:
            logger.exception("_restore_macro_state failed session=%s", session_id)
            return None

    @staticmethod
    def _clamp_macro_state(macro_state: Any) -> Any:
        """Clamp macro state values to realistic ranges."""
        clamp_ranges: dict[str, tuple[float, float]] = {
            "unemployment_rate": (0.0, 0.30),
            "gdp_growth": (-0.20, 0.20),
            "hsi_level": (5000.0, 50000.0),
            "consumer_confidence": (0.0, 100.0),
            "ccl_index": (20.0, 500.0),
            "net_migration": (-500000, 500000),
            "cpi_yoy": (-0.10, 0.30),
            "taiwan_strait_risk": (0.0, 1.0),
            "supply_chain_disruption": (0.0, 1.0),
            "import_tariff_rate": (0.0, 1.0),
            "credit_growth_yoy": (-0.15, 0.20),
            "interbank_spread": (0.001, 0.10),
            "mortgage_delinquency": (0.005, 0.20),
            "bank_ltv_cap": (0.40, 0.70),
            "bank_reserve_ratio": (0.04, 0.20),
        }
        updates: dict[str, Any] = {}
        for field, (lo, hi) in clamp_ranges.items():
            val = getattr(macro_state, field, None)
            if val is not None and isinstance(val, (int, float)):
                clamped = max(lo, min(hi, float(val)))
                if clamped != float(val):
                    updates[field] = type(val)(clamped)
        if updates:
            return dataclasses.replace(macro_state, **updates)
        return macro_state

    async def _process_credit_cycle(
        self,
        session_id: str,
        round_number: int,
    ) -> None:
        """Update banking credit cycle and apply macro feedback."""
        try:
            if self._kg_mode.get(session_id):
                return  # kg_driven: HK macro metrics not applicable

            from backend.app.services.bank_agent import BankAgent, BankState  # noqa: PLC0415

            if self._bank_agent is None:
                self._bank_agent = BankAgent()

            lock = self._macro_locks.get(session_id)
            if lock:
                async with lock:
                    macro_state = self._macro_state.get(session_id)
            else:
                macro_state = self._macro_state.get(session_id)
            if macro_state is None:
                from backend.app.services.macro_controller import MacroController  # noqa: PLC0415
                mc = MacroController()
                macro_state = await mc.get_baseline()

            new_bank_state = self._bank_agent.update_credit_cycle(macro_state)
            adjustments = self._bank_agent.compute_macro_feedback(
                new_bank_state, macro_state
            )

            if adjustments and session_id in self._macro_state:
                if session_id not in self._macro_locks:
                    self._macro_locks[session_id] = asyncio.Lock()
                async with self._macro_locks[session_id]:
                    current = self._macro_state[session_id]
                    updates: dict[str, Any] = {}
                    for field, delta in adjustments.items():
                        current_val = getattr(current, field, None)
                        if current_val is not None and isinstance(current_val, (int, float)):
                            updates[field] = type(current_val)(current_val + delta)
                    if updates:
                        new_state = self._clamp_macro_state(
                            dataclasses.replace(current, **updates)
                        )
                        self._macro_state[session_id] = new_state
                    await self._persist_macro_state(
                        session_id, round_number, new_state
                    )
                    logger.info(
                        "Credit cycle applied session=%s round=%d "
                        "npl=%.3f credit_growth=%.3f impulse=%.4f fields=%s",
                        session_id,
                        round_number,
                        new_bank_state.npl_ratio,
                        new_bank_state.credit_growth_yoy,
                        new_bank_state.credit_impulse,
                        list(updates.keys()),
                    )
        except Exception:
            logger.exception(
                "_process_credit_cycle failed session=%s round=%d",
                session_id,
                round_number,
            )

    async def _process_news_shock(
        self,
        session_id: str,
        round_number: int,
    ) -> None:
        """Fetch the latest real-world headline and inject as structured shock."""
        try:
            import aiosqlite as _aiosqlite  # noqa: PLC0415
            from backend.app.utils.db import get_db  # noqa: PLC0415
            from backend.app.services.triple_extractor import TripleExtractor  # noqa: PLC0415

            # 1. Fetch latest unprocessed headline
            async with get_db() as db:
                db.row_factory = _aiosqlite.Row
                cursor = await db.execute(
                    """
                    SELECT id, title, source, category, sentiment
                    FROM news_headlines
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                )
                row = await cursor.fetchone()

            if row is None:
                logger.debug(
                    "No news_headlines available for shock injection session=%s round=%d",
                    session_id, round_number,
                )
                return

            headline = dict(row)
            title = headline["title"]
            source = headline.get("source", "RTHK")
            category = headline.get("category", "general")

            # 2. Extract structured triples from headline
            extractor = TripleExtractor()
            triples = extractor.extract_triples(title, "observation", f"[{source}]")

            triple_summary = ""
            if triples:
                triple_lines = [f"  {t.subject} → {t.predicate} → {t.object}" for t in triples]
                triple_summary = "\n" + "\n".join(triple_lines)

            shock_content = (
                f"【突發新聞 BREAKING NEWS】({source} | {category})\n"
                f"{title}"
                f"{triple_summary}"
            )

            # 3. Store as simulation_action
            async with get_db() as db:
                await db.execute(
                    """
                    INSERT INTO simulation_actions
                        (session_id, round_number, agent_id, oasis_username,
                         action_type, platform, content, sentiment, topics)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        round_number,
                        0,
                        f"[NEWS:{source}]",
                        "CREATE_POST",
                        "news_injection",
                        shock_content,
                        headline.get("sentiment", "neutral"),
                        category,
                    ),
                )
                await db.commit()

            # 4. Inject triples into memory_triples for each agent
            agent_ids: dict[str, int] = {}
            async with get_db() as db:
                db.row_factory = _aiosqlite.Row
                cursor = await db.execute(
                    "SELECT id, oasis_username FROM agent_profiles WHERE session_id = ?",
                    (session_id,),
                )
                rows = await cursor.fetchall()
                agent_ids = {r["oasis_username"]: r["id"] for r in rows if r["oasis_username"]}

            if triples and agent_ids:
                triple_rows = []
                for agent_id in agent_ids.values():
                    for t in triples:
                        triple_rows.append((
                            None,
                            session_id,
                            agent_id,
                            round_number,
                            t.subject,
                            t.predicate,
                            t.object,
                            t.confidence * 0.9,
                        ))
                if triple_rows:
                    async with get_db() as db:
                        await db.executemany(
                            """
                            INSERT OR IGNORE INTO memory_triples
                                (memory_id, session_id, agent_id, round_number,
                                 subject, predicate, object, confidence)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            triple_rows,
                        )
                        await db.commit()

            # 5. Push to WebSocket
            try:
                from backend.app.api.ws import push_progress  # noqa: PLC0415
                await push_progress(session_id, {
                    "type": "news_shock",
                    "data": {
                        "round": round_number,
                        "headline": title,
                        "source": source,
                        "category": category,
                        "triples": [
                            {"subject": t.subject, "predicate": t.predicate, "object": t.object}
                            for t in triples
                        ],
                        "agents_injected": len(agent_ids),
                    },
                })
            except Exception:
                logger.debug("WebSocket push for news_shock failed (best-effort)")

            logger.info(
                "News shock injected session=%s round=%d headline='%.60s' "
                "triples=%d agents=%d",
                session_id,
                round_number,
                title,
                len(triples),
                len(agent_ids),
            )
        except Exception:
            logger.exception(
                "_process_news_shock failed session=%s round=%d",
                session_id,
                round_number,
            )

    async def _process_round_company_decisions(
        self,
        session_id: str,
        round_number: int,
    ) -> None:
        """Run B2B company decision processing for a completed simulation round."""
        try:
            from collections import Counter  # noqa: PLC0415

            from backend.app.models.company import (  # noqa: PLC0415
                CompanyDecision,
                CompanyDecisionType,
                CompanyProfile,
            )
            from backend.app.services.b2b_decision_rules import (  # noqa: PLC0415
                filter_eligible_companies,
            )
            from backend.app.utils.db import get_db  # noqa: PLC0415

            async with get_db() as db:
                await db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS company_decisions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        company_id INTEGER NOT NULL,
                        round_number INTEGER NOT NULL,
                        decision_type TEXT NOT NULL,
                        action TEXT NOT NULL,
                        reasoning TEXT,
                        confidence REAL NOT NULL DEFAULT 0.5,
                        impact_employees INTEGER NOT NULL DEFAULT 0,
                        impact_revenue_pct REAL NOT NULL DEFAULT 0.0,
                        created_at TEXT DEFAULT (datetime('now'))
                    )
                    """
                )
                await db.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_company_decisions_session
                    ON company_decisions(session_id, round_number)
                    """
                )
                await db.commit()

                cursor = await db.execute(
                    "SELECT * FROM company_profiles WHERE session_id = ?",
                    (session_id,),
                )
                rows = await cursor.fetchall()

            if not rows:
                return

            companies: list[CompanyProfile] = [
                CompanyProfile(
                    id=r["id"],
                    session_id=r["session_id"],
                    company_name=r["company_name"],
                    company_type=r["company_type"],
                    industry_sector=r["industry_sector"],
                    company_size=r["company_size"],
                    district=r["district"] or "",
                    supply_chain_position=r["supply_chain_position"] or "",
                    annual_revenue_hkd=r["annual_revenue_hkd"] or 0,
                    employee_count=r["employee_count"] or 0,
                    china_exposure=r["china_exposure"] if r["china_exposure"] is not None else 0.5,
                    export_ratio=r["export_ratio"] if r["export_ratio"] is not None else 0.3,
                )
                for r in rows
            ]

            macro_state = self._macro_state.get(session_id)
            if macro_state is None:
                from backend.app.services.macro_controller import MacroController  # noqa: PLC0415
                mc = MacroController()
                macro_state = await mc.get_baseline()

            all_decisions: list[CompanyDecision] = []
            for dt in CompanyDecisionType:
                eligible = filter_eligible_companies(companies, macro_state, dt.value)
                for company in eligible:
                    all_decisions.append(
                        CompanyDecision(
                            session_id=session_id,
                            company_id=company.id,
                            round_number=round_number,
                            decision_type=dt.value,
                            action=dt.value,
                            reasoning=(
                                f"Macro conditions triggered {dt.value} "
                                f"for {company.company_name}"
                            ),
                            confidence=0.7,
                            impact_employees=0,
                            impact_revenue_pct=0.0,
                        )
                    )

            if all_decisions:
                async with get_db() as db:
                    await db.executemany(
                        """
                        INSERT INTO company_decisions
                            (session_id, company_id, round_number, decision_type,
                             action, reasoning, confidence,
                             impact_employees, impact_revenue_pct)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                d.session_id,
                                d.company_id,
                                d.round_number,
                                d.decision_type,
                                d.action,
                                d.reasoning,
                                d.confidence,
                                d.impact_employees,
                                d.impact_revenue_pct,
                            )
                            for d in all_decisions
                        ],
                    )
                    await db.commit()

            logger.info(
                "B2B decisions: session=%s round=%d total=%d",
                session_id,
                round_number,
                len(all_decisions),
            )

            # B2B → macro feedback
            type_counts: Counter[str] = Counter(d.decision_type for d in all_decisions)
            macro_adjustments: dict[str, float] = {}

            layoff_count = type_counts.get(CompanyDecisionType.LAYOFF.value, 0)
            if layoff_count >= 3:
                macro_adjustments["unemployment_rate"] = round(layoff_count * 0.001, 4)

            hire_count = type_counts.get(CompanyDecisionType.HIRE.value, 0)
            if hire_count >= 3:
                macro_adjustments["unemployment_rate"] = (
                    macro_adjustments.get("unemployment_rate", 0.0)
                    - round(hire_count * 0.0008, 4)
                )

            expand_count = type_counts.get(CompanyDecisionType.EXPAND.value, 0)
            if expand_count >= 2:
                macro_adjustments["gdp_growth"] = round(expand_count * 0.001, 4)

            contract_count = (
                type_counts.get(CompanyDecisionType.CONTRACT.value, 0)
                + type_counts.get(CompanyDecisionType.EXIT_MARKET.value, 0)
            )
            if contract_count >= 2:
                macro_adjustments["gdp_growth"] = (
                    macro_adjustments.get("gdp_growth", 0.0)
                    - round(contract_count * 0.0015, 4)
                )

            relocate_count = type_counts.get(CompanyDecisionType.RELOCATE.value, 0)
            if relocate_count >= 2:
                macro_adjustments["hsi_level"] = -round(relocate_count * 30.0, 2)

            if macro_adjustments and session_id in self._macro_state:
                if session_id not in self._macro_locks:
                    self._macro_locks[session_id] = asyncio.Lock()
                async with self._macro_locks[session_id]:
                    current = self._macro_state[session_id]
                    updates: dict[str, Any] = {}
                    for field, delta in macro_adjustments.items():
                        current_val = getattr(current, field, None)
                        if current_val is not None and isinstance(current_val, (int, float)):
                            updates[field] = type(current_val)(current_val + delta)
                    if updates:
                        new_state = self._clamp_macro_state(
                            dataclasses.replace(current, **updates)
                        )
                        self._macro_state[session_id] = new_state
                        await self._persist_macro_state(session_id, round_number, new_state)
                        logger.info(
                            "B2B macro adjustments applied session=%s round=%d fields=%s",
                            session_id,
                            round_number,
                            list(updates.keys()),
                        )

        except Exception:
            logger.exception(
                "_process_round_company_decisions failed session=%s round=%d",
                session_id,
                round_number,
            )
