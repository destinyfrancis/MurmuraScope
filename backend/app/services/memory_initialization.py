"""MemoryInitializationService — Step 1 seed memory injection.

Converts seed text into:
1. Group memory (seed_world_context table + LanceDB swc_ table)
2. Individual persona templates (seed_persona_templates table)

Called from:
- POST /graph/build → build_from_graph()
- simulation_manager.py → hydrate_session_bulk()
- simulation hooks → get_world_context_for_prompt()
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from backend.app.utils.db import get_db
from backend.app.utils.llm_client import LLMClient
from backend.app.utils.logger import get_logger
from backend.prompts.memory_init_prompts import (
    WORLD_CONTEXT_SYSTEM,
    WORLD_CONTEXT_USER,
    PERSONA_TEMPLATE_SYSTEM,
    PERSONA_TEMPLATE_USER,
)

if TYPE_CHECKING:
    from backend.app.services.vector_store import VectorStore

logger = get_logger("memory_initialization")

_SALIENCE_SEED: float = 0.9
_MEMORY_TYPE_SEED: str = "seed"
_LANCE_TABLE_PREFIX: str = "swc_"
_MAX_WORLD_CONTEXT_ROWS: int = 8


# ---------------------------------------------------------------------------
# Public frozen dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeedInitResult:
    """Result of build_from_graph()."""
    world_context_count: int
    persona_template_count: int
    enhanced_edge_count: int


@dataclass(frozen=True)
class HydrationResult:
    """Result of hydrate_session_bulk()."""
    total_injected: int
    agents_skipped: int
    templates_found: int


@dataclass(frozen=True)
class WorldContextEntry:
    """Single world context item for prompt injection."""
    id: int
    graph_id: str
    context_type: str
    title: str
    content: str
    severity: float
    phase: str


# ---------------------------------------------------------------------------
# Private helpers (module-level so tests can import them)
# ---------------------------------------------------------------------------


def _resolve_key(agent_type: str, available_keys: set[str]) -> str | None:
    """Fuzzy-match agent_type to a template key.

    1. Exact match → return key
    2. Key is substring of agent_type (e.g. "grad_researcher" in "grad_researcher_female") → return key
    3. agent_type is substring of key → return key
    4. No match → return None
    """
    if agent_type in available_keys:
        return agent_type
    for key in available_keys:
        if key in agent_type or agent_type in key:
            return key
    return None


def _agent_id_from_str(agent_str_id: str) -> int:
    """Convert a string agent ID (UniversalAgentProfile.id slug) to a
    deterministic positive integer for agent_memories.agent_id.

    Uses MD5 for stable cross-process determinism (PYTHONHASHSEED does not
    affect MD5). agent_memories.agent_id has no FK constraint so any
    deterministic positive int is safe.
    """
    import hashlib  # noqa: PLC0415
    return int(hashlib.md5(agent_str_id.encode()).hexdigest(), 16) % (2**31)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class MemoryInitializationService:
    """Pre-inject world context and persona templates at Step 1 (graph build).

    Args:
        llm_client: LLMClient instance (or None to create a new one).
        lancedb_path: Path to LanceDB root directory. Defaults to the
            existing VectorStore path "data/vector_store" to co-locate
            swc_ tables with mem_ tables.
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        lancedb_path: str = "data/vector_store",
    ) -> None:
        self._llm = llm_client or LLMClient()
        self._lancedb_path = lancedb_path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def build_from_graph(
        self,
        graph_id: str,
        seed_text: str,
    ) -> SeedInitResult:
        """Run all 3 phases. Each phase is independently try/except.

        Phase 1: Enhanced KG edges (custom relation types)
        Phase 2: World context → seed_world_context + LanceDB
        Phase 3: Persona templates → seed_persona_templates

        Never raises — partial failure logs ERROR and continues.
        Returns SeedInitResult(0, 0, 0) if seed_text is empty.
        """
        if not seed_text or not seed_text.strip():
            return SeedInitResult(0, 0, 0)

        await self._ensure_tables()

        edge_count = 0
        world_count = 0
        persona_count = 0

        # Phase 1: enhanced edges (best-effort, no LLM cost if skipped)
        try:
            edge_count = await self._phase1_enhanced_edges(graph_id, seed_text)
        except Exception:
            logger.exception("Phase 1 (enhanced edges) failed for graph %s", graph_id)

        # Phase 2: world context
        try:
            world_count = await self._phase2_world_context(graph_id, seed_text)
        except Exception:
            logger.exception("Phase 2 (world context) failed for graph %s", graph_id)

        # Phase 3: persona templates
        try:
            persona_count = await self._phase3_persona_templates(graph_id, seed_text)
        except Exception:
            logger.exception("Phase 3 (persona templates) failed for graph %s", graph_id)

        logger.info(
            "build_from_graph %s: %d edges, %d world ctx, %d personas",
            graph_id, edge_count, world_count, persona_count,
        )
        return SeedInitResult(world_count, persona_count, edge_count)

    async def hydrate_session_bulk(
        self,
        session_id: str,
        graph_id: str,
        agents: list[tuple[str, str]],
        vector_store: VectorStore | None = None,
    ) -> HydrationResult:
        """Inject round_number=0 memories for all agents in a session.

        Args:
            session_id: Simulation session ID.
            graph_id: Graph ID (used to look up persona templates).
            agents: List of (agent_str_id, agent_type) tuples.
                agent_str_id = UniversalAgentProfile.id (str slug)
                agent_type   = UniversalAgentProfile.entity_type
            vector_store: Optional VectorStore for dual-write to LanceDB mem_ table.

        Returns:
            HydrationResult with counts of injected/skipped memories.
        """
        templates = await self._load_persona_templates(graph_id)
        if not templates:
            logger.warning(
                "hydrate_session_bulk: no persona templates for graph %s — skipping %d agents",
                graph_id, len(agents),
            )
            return HydrationResult(total_injected=0, agents_skipped=len(agents), templates_found=0)

        template_map: dict[str, dict] = {t["agent_type_key"]: t for t in templates}
        available_keys = set(template_map.keys())

        total_injected = 0
        agents_skipped = 0

        for agent_str_id, agent_type in agents:
            matched_key = _resolve_key(agent_type, available_keys)
            if matched_key is None:
                logger.warning(
                    "No template match for agent %s (type=%s) in graph %s",
                    agent_str_id, agent_type, graph_id,
                )
                agents_skipped += 1
                continue

            template = template_map[matched_key]
            memories: list[str] = template.get("initial_memories", [])
            agent_int_id = _agent_id_from_str(agent_str_id)

            try:
                injected = await self._write_seed_memories(
                    session_id=session_id,
                    agent_id=agent_int_id,
                    memories=memories,
                    vector_store=vector_store,
                )
                total_injected += injected
            except Exception:
                logger.warning(
                    "Failed to inject memories for agent %s session %s",
                    agent_str_id, session_id, exc_info=True,
                )
                agents_skipped += 1

        return HydrationResult(
            total_injected=total_injected,
            agents_skipped=agents_skipped,
            templates_found=len(templates),
        )

    async def get_world_context_for_prompt(
        self,
        graph_id: str,
        query: str | None = None,
        context_types: list[str] | None = None,
    ) -> list[WorldContextEntry]:
        """Retrieve world context entries for prompt injection.

        Dispatch:
        1. query provided → embed + raw LanceDB semantic search on swc_{graph_id[:12]},
           then optional Python post-filter by context_types
        2. query=None, context_types provided → SQL WHERE context_type IN (...)
           ORDER BY severity DESC LIMIT 8
        3. both None → SQL all WHERE graph_id=? ORDER BY severity DESC LIMIT 8
        """
        if query:
            return await self._semantic_search_world_context(graph_id, query, context_types)
        return await self._sql_fetch_world_context(graph_id, context_types)

    # ------------------------------------------------------------------
    # Phase implementations
    # ------------------------------------------------------------------

    async def _phase1_enhanced_edges(self, graph_id: str, seed_text: str) -> int:
        """Phase 1: No LLM call — placeholder for future custom edge extraction.

        Currently returns 0. Custom relation types (FALSELY_ACCUSED, etc.) are
        already handled by SeedGraphInjector. This phase is reserved for future
        domain-specific edge augmentation.
        """
        return 0

    async def _phase2_world_context(self, graph_id: str, seed_text: str) -> int:
        """Phase 2: LLM → world context → SQLite + LanceDB."""
        prompt = WORLD_CONTEXT_USER.format(seed_text=seed_text[:8000])
        raw = await self._llm_call_with_retry(WORLD_CONTEXT_SYSTEM, prompt)
        entries = self._parse_world_context_response(raw)

        if not entries:
            logger.warning("Phase 2: no world context entries parsed for graph %s", graph_id)
            return 0

        written = await self._write_world_context(graph_id, entries)
        await self._embed_world_context(graph_id, written)
        return len(written)

    async def _phase3_persona_templates(self, graph_id: str, seed_text: str) -> int:
        """Phase 3: LLM → persona templates → SQLite."""
        prompt = PERSONA_TEMPLATE_USER.format(seed_text=seed_text[:8000])
        raw = await self._llm_call_with_retry(PERSONA_TEMPLATE_SYSTEM, prompt)
        templates = self._parse_persona_response(raw)

        if not templates:
            logger.warning("Phase 3: no persona templates parsed for graph %s", graph_id)
            return 0

        return await self._write_persona_templates(graph_id, templates)

    # ------------------------------------------------------------------
    # Parse helpers (tested in isolation)
    # ------------------------------------------------------------------

    def _parse_world_context_response(self, raw: str) -> list[dict]:
        """Parse LLM JSON response for world context. Returns [] on any error."""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            logger.error("World context parse failed — invalid JSON: %.200s", raw)
            return []

        if not isinstance(data, list):
            return []

        required = {"context_type", "title", "content"}
        valid = []
        for item in data:
            if not isinstance(item, dict):
                continue
            if not required.issubset(item.keys()):
                continue
            valid.append({
                "context_type": str(item.get("context_type", "social_climate")),
                "title": str(item["title"]),
                "content": str(item["content"]),
                "severity": float(item.get("severity", 0.7)),
                "phase": str(item.get("phase", "crisis")),
            })
        return valid

    def _parse_persona_response(self, raw: str) -> list[dict]:
        """Parse LLM JSON response for persona templates. Returns [] on any error."""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            logger.error("Persona template parse failed — invalid JSON: %.200s", raw)
            return []

        if not isinstance(data, list):
            return []

        valid = []
        for item in data:
            if not isinstance(item, dict):
                continue
            if "agent_type_key" not in item:
                continue
            valid.append({
                "agent_type_key":        str(item["agent_type_key"]),
                "display_name":          str(item.get("display_name", item["agent_type_key"])),
                "age_min":               item.get("age_min"),
                "age_max":               item.get("age_max"),
                "region_hint":           str(item.get("region_hint", "any")),
                "population_ratio":      float(item.get("population_ratio", 0.25)),
                "initial_memories":      list(item.get("initial_memories", [])),
                "personality_hints":     dict(item.get("personality_hints", {})),
            })
        return valid

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    async def _ensure_tables(self) -> None:
        """Create tables if not exist (idempotent — uses CREATE TABLE IF NOT EXISTS)."""
        async with get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS seed_world_context (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    graph_id TEXT NOT NULL,
                    session_id TEXT,
                    context_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    severity REAL NOT NULL DEFAULT 0.7,
                    phase TEXT NOT NULL DEFAULT 'crisis',
                    lance_row_id TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    UNIQUE(graph_id, title) ON CONFLICT IGNORE
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS seed_persona_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    graph_id TEXT NOT NULL,
                    session_id TEXT,
                    agent_type_key TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    age_min INTEGER,
                    age_max INTEGER,
                    region_hint TEXT NOT NULL DEFAULT 'any',
                    population_ratio REAL NOT NULL DEFAULT 0.25,
                    initial_memories_json TEXT NOT NULL,
                    personality_hints_json TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now')),
                    UNIQUE(graph_id, agent_type_key) ON CONFLICT IGNORE
                )
            """)
            await db.commit()

    async def _write_world_context(
        self, graph_id: str, entries: list[dict]
    ) -> list[dict]:
        """Insert world context rows. Returns list of written entries with DB ids."""
        written = []
        async with get_db() as db:
            for entry in entries:
                cursor = await db.execute(
                    """INSERT OR IGNORE INTO seed_world_context
                       (graph_id, context_type, title, content, severity, phase)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (graph_id, entry["context_type"], entry["title"],
                     entry["content"], entry["severity"], entry["phase"]),
                )
                if cursor.lastrowid:
                    written.append({**entry, "db_id": cursor.lastrowid})
            await db.commit()
        return written

    async def _write_persona_templates(
        self, graph_id: str, templates: list[dict]
    ) -> int:
        """Insert persona template rows. Returns count written."""
        count = 0
        async with get_db() as db:
            for t in templates:
                cursor = await db.execute(
                    """INSERT OR IGNORE INTO seed_persona_templates
                       (graph_id, agent_type_key, display_name, age_min, age_max,
                        region_hint, population_ratio, initial_memories_json, personality_hints_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        graph_id,
                        t["agent_type_key"],
                        t["display_name"],
                        t.get("age_min"),
                        t.get("age_max"),
                        t.get("region_hint", "any"),
                        t.get("population_ratio", 0.25),
                        json.dumps(t.get("initial_memories", []), ensure_ascii=False),
                        json.dumps(t.get("personality_hints", {}), ensure_ascii=False),
                    ),
                )
                if cursor.lastrowid:
                    count += 1
            await db.commit()
        return count

    async def _load_persona_templates(self, graph_id: str) -> list[dict]:
        """Load all persona templates for a graph_id."""
        async with get_db() as db:
            rows = await db.execute_fetchall(
                "SELECT graph_id, agent_type_key, initial_memories_json, personality_hints_json "
                "FROM seed_persona_templates WHERE graph_id = ?",
                (graph_id,),
            )
        result = []
        for r in rows:
            try:
                result.append({
                    "agent_type_key": r["agent_type_key"],
                    "initial_memories": json.loads(r["initial_memories_json"]),
                    "personality_hints": json.loads(r["personality_hints_json"]),
                })
            except (json.JSONDecodeError, ValueError, KeyError):
                logger.error(
                    "Corrupt persona template row for graph %s key %s — skipping",
                    r["graph_id"] if "graph_id" in r.keys() else "?",
                    r["agent_type_key"] if "agent_type_key" in r.keys() else "?",
                )
        return result

    async def _write_seed_memories(
        self,
        session_id: str,
        agent_id: int,
        memories: list[str],
        vector_store: VectorStore | None,
    ) -> int:
        """Write round_number=0 seed memories for one agent."""
        valid_memories = [m for m in memories if m.strip()]
        if not valid_memories:
            return 0

        async with get_db() as db:
            for memory_text in valid_memories:
                await db.execute(
                    """INSERT INTO agent_memories
                       (session_id, agent_id, round_number, memory_text, salience_score, memory_type)
                       VALUES (?, ?, 0, ?, ?, ?)""",
                    (session_id, agent_id, memory_text, _SALIENCE_SEED, _MEMORY_TYPE_SEED),
                )
            await db.commit()

        # Dual-write to LanceDB if vector_store provided (best-effort)
        if vector_store:
            try:
                memories_to_add = [
                    {
                        "memory_id": abs(hash(f"seed_{session_id[:8]}_{agent_id}_{i}")) % (2**31),
                        "agent_id": agent_id,
                        "round_number": 0,
                        "memory_text": memory_text,
                        "memory_type": _MEMORY_TYPE_SEED,
                        "salience_score": _SALIENCE_SEED,
                    }
                    for i, memory_text in enumerate(valid_memories)
                ]
                await vector_store.add_memories(session_id=session_id, memories=memories_to_add)
            except Exception:
                logger.warning(
                    "LanceDB dual-write failed for agent %d session %s",
                    agent_id, session_id, exc_info=True,
                )

        return len(valid_memories)

    async def _sql_fetch_world_context(
        self, graph_id: str, context_types: list[str] | None
    ) -> list[WorldContextEntry]:
        """SQL fetch world context, optionally filtered by context_type."""
        async with get_db() as db:
            if context_types:
                placeholders = ", ".join("?" * len(context_types))
                rows = await db.execute_fetchall(
                    f"SELECT id, graph_id, context_type, title, content, severity, phase "
                    f"FROM seed_world_context WHERE graph_id = ? "
                    f"AND context_type IN ({placeholders}) "
                    "ORDER BY severity DESC LIMIT 8",  # LIMIT cannot use ? placeholder in SQLite
                    [graph_id, *context_types],
                )
            else:
                rows = await db.execute_fetchall(
                    "SELECT id, graph_id, context_type, title, content, severity, phase "
                    "FROM seed_world_context WHERE graph_id = ? "
                    "ORDER BY severity DESC LIMIT 8",  # LIMIT cannot use ? placeholder in SQLite
                    (graph_id,),
                )
        return [
            WorldContextEntry(
                id=r["id"], graph_id=r["graph_id"], context_type=r["context_type"],
                title=r["title"], content=r["content"], severity=r["severity"], phase=r["phase"],
            )
            for r in rows
        ]

    async def _semantic_search_world_context(
        self, graph_id: str, query: str, context_types: list[str] | None
    ) -> list[WorldContextEntry]:
        """Semantic search via raw LanceDB on swc_{graph_id[:12]} table."""
        try:
            import lancedb  # noqa: PLC0415
            from backend.app.services.vector_store import EmbeddingProvider  # noqa: PLC0415

            db = lancedb.connect(self._lancedb_path)
            table_name = f"{_LANCE_TABLE_PREFIX}{graph_id[:12]}"

            if table_name not in db.table_names():
                logger.debug("LanceDB table %s not found, falling back to SQL", table_name)
                return await self._sql_fetch_world_context(graph_id, context_types)

            query_vec = EmbeddingProvider.embed_single(query)  # sync — no await
            tbl = db.open_table(table_name)
            results = tbl.search(query_vec).limit(_MAX_WORLD_CONTEXT_ROWS).to_list()

            if context_types:
                results = [r for r in results if r.get("context_type") in context_types]

            # Fetch full rows from SQLite using title as key
            titles = [r["title"] for r in results]
            if not titles:
                return []

            placeholders = ", ".join("?" * len(titles))
            async with get_db() as sqldb:
                rows = await sqldb.execute_fetchall(
                    f"SELECT id, graph_id, context_type, title, content, severity, phase "
                    f"FROM seed_world_context WHERE graph_id = ? AND title IN ({placeholders})",
                    [graph_id, *titles],
                )
            return [
                WorldContextEntry(
                    id=r["id"], graph_id=r["graph_id"], context_type=r["context_type"],
                    title=r["title"], content=r["content"], severity=r["severity"], phase=r["phase"],
                )
                for r in rows
            ]

        except Exception:
            logger.warning(
                "Semantic search failed for graph %s, falling back to SQL", graph_id, exc_info=True
            )
            return await self._sql_fetch_world_context(graph_id, context_types)

    async def _embed_world_context(self, graph_id: str, entries: list[dict]) -> None:
        """Embed world context entries into LanceDB swc_ table (best-effort)."""
        if not entries:
            return
        try:
            import lancedb  # noqa: PLC0415
            import pyarrow as pa  # noqa: PLC0415
            from backend.app.services.vector_store import EmbeddingProvider  # noqa: PLC0415

            db = lancedb.connect(self._lancedb_path)
            table_name = f"{_LANCE_TABLE_PREFIX}{graph_id[:12]}"

            rows = []
            for entry in entries:
                vec = EmbeddingProvider.embed_single(entry["content"])  # sync
                rows.append({
                    "id": f"swc_{graph_id[:8]}_{entry['db_id']}",
                    "graph_id": graph_id,
                    "context_type": entry["context_type"],
                    "title": entry["title"],
                    "content": entry["content"],
                    "severity": entry["severity"],
                    "phase": entry["phase"],
                    "vector": vec,
                })

            if table_name in db.table_names():
                tbl = db.open_table(table_name)
                tbl.add(rows)
            else:
                db.create_table(table_name, data=rows)

            # Backfill lance_row_id in SQLite
            async with get_db() as sqldb:
                for r in rows:
                    await sqldb.execute(
                        "UPDATE seed_world_context SET lance_row_id = ? "
                        "WHERE graph_id = ? AND title = ?",
                        (r["id"], graph_id, r["title"]),
                    )
                await sqldb.commit()

        except Exception:
            logger.warning(
                "LanceDB embed failed for graph %s — world context stored in SQL only",
                graph_id, exc_info=True,
            )

    # ------------------------------------------------------------------
    # LLM helper
    # ------------------------------------------------------------------

    async def _llm_call_with_retry(self, system: str, user: str) -> str:
        """Call LLM returning raw content string.

        Uses LLMClient.chat_json() which appends a JSON-only instruction and
        strips markdown fences. Falls back to raw .chat() on JSONDecodeError,
        appending an explicit JSON constraint to the user message.
        """
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        try:
            result = await self._llm.chat_json(messages)
            return json.dumps(result, ensure_ascii=False)
        except Exception:
            logger.warning("chat_json failed, falling back to raw chat", exc_info=True)
            retry_messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user + "\n\nRespond with a JSON array only, no markdown."},
            ]
            response = await self._llm.chat(retry_messages)
            return response.content
