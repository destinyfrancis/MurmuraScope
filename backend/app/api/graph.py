"""Step 1: Graph building — LLM-driven knowledge graph from seed text.

Extracts entities and relationships from seed text via TextProcessor +
SeedGraphInjector, then enriches with implicit stakeholder discovery.
All writes go through the aiosqlite graph store (no hard-coded data).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from backend.app.api.auth import _limiter
from backend.app.models.request import GraphBuildRequest
from backend.app.models.response import APIResponse, GraphBuildResponse
from backend.app.services.implicit_stakeholder_service import ImplicitStakeholderService
from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger
from backend.app.utils.prompt_security import sanitize_seed_text

router = APIRouter(prefix="/graph", tags=["graph"])
logger = get_logger("api.graph")


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _row_to_node(row: Any) -> dict[str, Any]:
    props = json.loads(row["properties"] or "{}")
    return {
        "id": row["id"],
        "label": row["title"],
        "type": row["entity_type"],
        "description": row["description"] or "",
        "size": props.get("size", 10),
    }


def _row_to_edge(row: Any) -> dict[str, Any]:
    return {
        "source": row["source_id"],
        "target": row["target_id"],
        "label": row["relation_type"],
        "weight": row["weight"] or 1.0,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/build", response_model=APIResponse)
@_limiter.limit("10/minute")
async def build_graph(request: Request, req: GraphBuildRequest) -> APIResponse:
    """Build knowledge graph from scenario type and seed text.

    Runs LLM-based entity extraction from seed text via TextProcessor +
    SeedGraphInjector, then enriches with implicit stakeholder discovery
    and memory initialization.  All DB writes go through the aiosqlite
    graph store — no hard-coded node/edge data.
    """
    graph_id = str(uuid.uuid4())

    # Detect mode (hk_demographic vs kg_driven) — still used by simulation routing.
    safe_seed = sanitize_seed_text(req.seed_text) if req.seed_text else ""
    if safe_seed.strip():
        from backend.app.services.zero_config import ZeroConfigService  # noqa: PLC0415

        _detected_mode = await ZeroConfigService().detect_mode_async(safe_seed)
        _is_hk = _detected_mode == "hk_demographic"
    else:
        _HK_SCENARIO_TYPES = {"property", "emigration", "fertility", "career", "education", "macro"}
        _is_hk = req.scenario_type in _HK_SCENARIO_TYPES

    seed_nodes = 0
    seed_edges = 0
    implicit_nodes = 0
    mem_result = None

    # --- Unified seed injection: single write path for all modes ---
    if safe_seed.strip():
        try:
            from backend.app.services.seed_graph_injector import SeedGraphInjector  # noqa: PLC0415
            from backend.app.services.text_processor import TextProcessor  # noqa: PLC0415

            processor = TextProcessor()
            processed = await processor.process(safe_seed)

            injector = SeedGraphInjector()
            inject_result = await injector.inject(graph_id, processed)
            seed_nodes = inject_result.get("seed_nodes", 0)
            seed_edges = inject_result.get("seed_edges", 0)
            logger.info(
                "Seed injection for graph %s: +%d nodes, +%d edges",
                graph_id,
                seed_nodes,
                seed_edges,
            )
        except Exception:
            logger.exception(
                "Seed injection failed for graph %s — continuing",
                graph_id,
            )

        # --- Implicit stakeholder discovery (best-effort) ---
        try:
            implicit_svc = ImplicitStakeholderService()
            existing_for_dedup: list[dict[str, str]] = []
            try:
                async with get_db() as db:
                    cursor = await db.execute(
                        "SELECT id, title, entity_type FROM kg_nodes WHERE session_id = ?",
                        (graph_id,),
                    )
                    existing_for_dedup = [
                        {"id": str(r[0]), "label": str(r[1] or ""), "entity_type": str(r[2] or "")}
                        for r in await cursor.fetchall()
                    ]
            except Exception:
                logger.warning("Failed to load existing nodes for dedup graph=%s", graph_id)

            discovery = await implicit_svc.discover(graph_id, safe_seed, existing_for_dedup)
            implicit_nodes = discovery.nodes_added
            logger.info(
                "Implicit stakeholder discovery for graph %s: +%d nodes",
                graph_id,
                implicit_nodes,
            )
        except Exception:
            logger.exception(
                "Implicit stakeholder discovery failed for graph %s — continuing",
                graph_id,
            )

        # --- Memory initialization (best-effort) ---
        try:
            from backend.app.services.memory_initialization import MemoryInitializationService  # noqa: PLC0415

            mem_svc = MemoryInitializationService()
            mem_result = await mem_svc.build_from_graph(graph_id, safe_seed)
            logger.info(
                "Memory init for graph %s: %d world ctx, %d persona templates, %d edges",
                graph_id,
                mem_result.world_context_count,
                mem_result.persona_template_count,
                mem_result.enhanced_edge_count,
            )
        except Exception:
            logger.exception(
                "Memory initialization failed for graph %s — continuing without seed memories",
                graph_id,
            )

    # --- Build entity/relation type lists from DB (uniform for all modes) ---
    try:
        async with get_db() as db:
            et_cursor = await db.execute(
                "SELECT DISTINCT entity_type FROM kg_nodes WHERE session_id = ? AND entity_type IS NOT NULL",
                (graph_id,),
            )
            _entity_types = [r[0] for r in await et_cursor.fetchall()]
            rt_cursor = await db.execute(
                "SELECT DISTINCT relation_type FROM kg_edges WHERE session_id = ? AND relation_type IS NOT NULL",
                (graph_id,),
            )
            _relation_types = [r[0] for r in await rt_cursor.fetchall()]
    except Exception:
        _entity_types = []
        _relation_types = []

    result = GraphBuildResponse(
        graph_id=graph_id,
        node_count=seed_nodes + implicit_nodes,
        edge_count=seed_edges,
        entity_types=_entity_types,
        relation_types=_relation_types,
    )
    return APIResponse(
        success=True,
        data=result.model_dump(),
        meta={
            "scenario_type": req.scenario_type,
            "detected_mode": "hk_demographic" if _is_hk else "kg_driven",
            "base_nodes": 0,
            "base_edges": 0,
            "seed_nodes": seed_nodes,
            "seed_edges": seed_edges,
            "implicit_nodes": implicit_nodes,
            "world_context_count": mem_result.world_context_count if mem_result else 0,
            "persona_template_count": mem_result.persona_template_count if mem_result else 0,
        },
    )


@router.get("/{graph_id}", response_model=APIResponse)
async def get_graph(graph_id: str) -> APIResponse:
    """Get full graph data (nodes + edges) in D3-compatible format.

    Supports both direct graph_id and session_uuid lookups. When the
    provided ID matches a simulation_sessions.id, we resolve the
    associated graph_id and query that instead.
    """
    effective_graph_id = graph_id

    try:
        async with get_db() as db:
            node_rows = await (
                await db.execute(
                    "SELECT id, entity_type, title, description, properties FROM kg_nodes WHERE session_id = ?",
                    (effective_graph_id,),
                )
            ).fetchall()

            # Fallback: try looking up as a session UUID → graph_id
            if not node_rows:
                session_row = await (
                    await db.execute(
                        "SELECT graph_id FROM simulation_sessions WHERE id = ?",
                        (graph_id,),
                    )
                ).fetchone()
                if session_row and session_row["graph_id"]:
                    effective_graph_id = session_row["graph_id"]
                    node_rows = await (
                        await db.execute(
                            "SELECT id, entity_type, title, description, properties FROM kg_nodes WHERE session_id = ?",
                            (effective_graph_id,),
                        )
                    ).fetchall()

            edge_rows = await (
                await db.execute(
                    "SELECT source_id, target_id, relation_type, weight FROM kg_edges WHERE session_id = ?",
                    (effective_graph_id,),
                )
            ).fetchall()
    except Exception:
        logger.exception("Failed to fetch graph %s", graph_id)
        raise HTTPException(status_code=500, detail="Graph fetch failed")

    if not node_rows:
        raise HTTPException(status_code=404, detail=f"Graph {graph_id} not found")

    return APIResponse(
        success=True,
        data={
            "graph_id": effective_graph_id,
            "nodes": [_row_to_node(r) for r in node_rows],
            "edges": [_row_to_edge(r) for r in edge_rows],
        },
    )


@router.get("/{graph_id}/nodes", response_model=APIResponse)
async def list_nodes(graph_id: str) -> APIResponse:
    """List all nodes in a graph."""
    async with get_db() as db:
        rows = await (
            await db.execute(
                "SELECT id, entity_type, title, description, properties FROM kg_nodes WHERE session_id = ?",
                (graph_id,),
            )
        ).fetchall()

    nodes = [_row_to_node(r) for r in rows]
    return APIResponse(success=True, data=nodes, meta={"graph_id": graph_id, "count": len(nodes)})


@router.get("/{graph_id}/edges", response_model=APIResponse)
async def list_edges(graph_id: str) -> APIResponse:
    """List all edges in a graph."""
    async with get_db() as db:
        rows = await (
            await db.execute(
                "SELECT source_id, target_id, relation_type, weight FROM kg_edges WHERE session_id = ?",
                (graph_id,),
            )
        ).fetchall()

    edges = [_row_to_edge(r) for r in rows]
    return APIResponse(success=True, data=edges, meta={"graph_id": graph_id, "count": len(edges)})


_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
_ALLOWED_CONTENT_TYPES = frozenset(
    {
        "application/pdf",
        "text/plain",
        "text/markdown",
        "application/octet-stream",  # some browsers send this for .md
    }
)
_ALLOWED_EXTENSIONS = frozenset({".pdf", ".txt", ".md", ".markdown"})


@router.post("/upload-seed", response_model=APIResponse)
async def upload_seed_file(file: UploadFile = File(...)) -> APIResponse:
    """Accept a PDF / Markdown / TXT seed file and return its text content.

    Limits:
    - Max size: 10 MB
    - Accepted types: PDF, Markdown (.md), plain text (.txt)
    """

    # Validate extension
    filename = file.filename or ""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支援的檔案類型 '{ext}'。請上傳 PDF、TXT 或 Markdown 檔案。",
        )

    # Read with size guard
    raw = await file.read()
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"檔案超過 10 MB 上限（目前 {len(raw) / 1024 / 1024:.1f} MB）",
        )

    extracted = ""
    try:
        if ext == ".pdf":
            extracted = _extract_pdf_text(raw)
        else:
            # TXT / MD: try UTF-8 first, fall back to latin-1
            try:
                extracted = raw.decode("utf-8")
            except UnicodeDecodeError:
                extracted = raw.decode("latin-1", errors="replace")
    except Exception as exc:
        logger.exception("upload_seed_file extraction failed for %s", filename)
        raise HTTPException(status_code=422, detail=f"無法提取文字內容：{exc}") from exc

    if not extracted.strip():
        raise HTTPException(status_code=422, detail="檔案內容為空，無法提取文字。")

    return APIResponse(
        success=True,
        data={
            "text": extracted,
            "filename": filename,
            "size": len(raw),
        },
    )


def _extract_pdf_text(raw: bytes) -> str:
    """Extract text from PDF bytes using pypdf (or PyPDF2 fallback)."""
    import io  # noqa: PLC0415

    try:
        import pypdf  # noqa: PLC0415

        reader = pypdf.PdfReader(io.BytesIO(raw))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages)
    except ImportError:
        pass

    try:
        import PyPDF2  # noqa: PLC0415, N813

        reader = PyPDF2.PdfReader(io.BytesIO(raw))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages)
    except ImportError:
        pass

    raise HTTPException(
        status_code=422,
        detail="伺服器未安裝 PDF 解析庫（pypdf / PyPDF2）。請上傳 TXT 或 Markdown 檔案。",
    )


@router.post("/analyze-seed", response_model=APIResponse)
@_limiter.limit("15/minute")
async def analyze_seed(request: Request, req: GraphBuildRequest) -> APIResponse:
    """Analyze seed text and return structured insights without building graph."""
    from backend.app.services.text_processor import TextProcessor  # noqa: PLC0415

    if not req.seed_text or not req.seed_text.strip():
        raise HTTPException(status_code=400, detail="seed_text is required")

    safe_seed = sanitize_seed_text(req.seed_text)

    try:
        processor = TextProcessor()
        result = await processor.process(safe_seed)

        # Also get agent suggestions
        suggestions = await processor.suggest_agents(result)

        return APIResponse(
            success=True,
            data={
                "language": result.language,
                "entities": [{"name": e.name, "type": e.type, "relevance": e.relevance} for e in result.entities],
                "timeline": [{"date_hint": t.date_hint, "event": t.event} for t in result.timeline],
                "stakeholders": [
                    {"group": s.group, "description": s.description, "impact": s.impact}
                    for s in result.stakeholders
                ],
                "key_claims": result.key_claims,
                "suggested_regions": list(result.suggested_regions),
                "suggested_districts": list(result.suggested_regions),  # backward compat
                "confidence": result.confidence,
                "agent_suggestions": suggestions,
            },
            meta={"scenario_type": req.scenario_type},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Bad request") from exc
    except Exception as exc:
        logger.exception("analyze_seed failed")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{graph_id}/snapshots", response_model=APIResponse)
async def list_graph_snapshots(graph_id: str) -> APIResponse:
    """List all saved KG snapshots for a session (by round)."""
    try:
        async with get_db() as db:
            rows = await (
                await db.execute(
                    "SELECT id, round_number, node_count, edge_count, created_at"
                    " FROM kg_snapshots WHERE session_id = ?"
                    " ORDER BY round_number",
                    (graph_id,),
                )
            ).fetchall()
    except Exception:
        logger.exception("list_graph_snapshots failed for graph %s", graph_id)
        raise HTTPException(status_code=500, detail="Snapshot list failed")

    snapshots = [
        {
            "id": r[0],
            "round_number": r[1],
            "node_count": r[2],
            "edge_count": r[3],
            "created_at": r[4],
        }
        for r in rows
    ]
    return APIResponse(
        success=True,
        data=snapshots,
        meta={"graph_id": graph_id, "count": len(snapshots)},
    )


@router.post("/{graph_id}/personas", response_model=APIResponse)
async def upload_persona_profiles(
    graph_id: str,
    file: UploadFile = File(...),
) -> APIResponse:
    """Upload CSV or JSON persona profiles to pre-seed KG agents.

    Profiles are injected as kg_nodes with source='persona_upload' stored in
    the properties JSON. KGAgentFactory will pick them up during Step 2 agent
    generation as pre-seeded participant data.

    Accepted formats:
    - CSV with headers: name, role, age, occupation, beliefs, goals,
                        political_stance, background
    - JSON array of objects with the same fields

    Limits: 500 profiles per upload, 10 MB file size.
    """
    from backend.app.services.persona_profile_loader import inject_as_kg_nodes, load_profiles  # noqa: PLC0415

    content = await file.read()
    if not content:
        return APIResponse(
            success=False,
            data=None,
            meta={"error": "Empty file"},
        )

    try:
        profiles = load_profiles(content, file.filename or "upload.json")
    except Exception as exc:
        logger.exception("Persona profile parse error for graph %s", graph_id)
        return APIResponse(
            success=False,
            data=None,
            meta={"error": f"Parse error: {exc}"},
        )

    if not profiles:
        return APIResponse(
            success=False,
            data=None,
            meta={"error": "No valid profiles found in file"},
        )

    count = await inject_as_kg_nodes(graph_id, profiles)
    return APIResponse(
        success=True,
        data={"injected": count},
        meta={"graph_id": graph_id, "profiles_parsed": len(profiles)},
    )


@router.get("/{graph_id}/snapshot/{round_number}", response_model=APIResponse)
async def get_graph_snapshot(graph_id: str, round_number: int) -> APIResponse:
    """Get a specific KG snapshot by round number."""
    try:
        async with get_db() as db:
            row = await (
                await db.execute(
                    "SELECT snapshot_json, node_count, edge_count, created_at"
                    " FROM kg_snapshots"
                    " WHERE session_id = ? AND round_number = ?"
                    " ORDER BY id DESC LIMIT 1",
                    (graph_id, round_number),
                )
            ).fetchone()
    except Exception:
        logger.exception("get_graph_snapshot failed for graph %s round %d", graph_id, round_number)
        raise HTTPException(status_code=500, detail="Snapshot fetch failed")

    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"No snapshot for graph {graph_id} at round {round_number}",
        )

    import json as _json  # noqa: PLC0415

    snapshot_data = _json.loads(row[0] or "{}")
    return APIResponse(
        success=True,
        data={
            "graph_id": graph_id,
            "round_number": round_number,
            "node_count": row[1],
            "edge_count": row[2],
            "created_at": row[3],
            **snapshot_data,
        },
    )


# ---------------------------------------------------------------------------
# N-hop Neighborhood & Round Diff (Phase 18)
# ---------------------------------------------------------------------------


@router.get("/{graph_id}/node/{node_id}/neighborhood")
async def get_node_neighborhood(graph_id: str, node_id: str, hops: int = 2) -> APIResponse:
    """Return N-hop subgraph centered on a node."""
    if hops < 1 or hops > 5:
        raise HTTPException(status_code=400, detail="hops must be between 1 and 5")

    visited: set[str] = {node_id}
    frontier: set[str] = {node_id}
    result_edges: list[dict] = []

    async with get_db() as db:
        for _ in range(hops):
            if not frontier:
                break
            placeholders = ",".join("?" for _ in frontier)
            rows = await (
                await db.execute(
                    f"""SELECT source_id, target_id, relation_type, weight
                        FROM kg_edges
                        WHERE session_id = ?
                          AND (source_id IN ({placeholders}) OR target_id IN ({placeholders}))""",
                    (graph_id, *frontier, *frontier),
                )
            ).fetchall()

            next_frontier: set[str] = set()
            for row in rows or []:
                result_edges.append(dict(row))
                for nid in (row["source_id"], row["target_id"]):
                    if nid not in visited:
                        visited.add(nid)
                        next_frontier.add(nid)
            frontier = next_frontier

        # Fetch node details
        if visited:
            placeholders = ",".join("?" for _ in visited)
            node_rows = await (
                await db.execute(
                    f"SELECT id, entity_type, title, description, properties"
                    f" FROM kg_nodes WHERE session_id = ? AND id IN ({placeholders})",
                    (graph_id, *visited),
                )
            ).fetchall()
        else:
            node_rows = []

    return APIResponse(
        success=True,
        data={
            "center_node_id": node_id,
            "hops": hops,
            "nodes": [_row_to_node(r) for r in (node_rows or [])],
            "edges": result_edges,
        },
        meta={"graph_id": graph_id, "node_count": len(node_rows or []), "edge_count": len(result_edges)},
    )


@router.get("/{graph_id}/diff")
async def get_graph_diff(graph_id: str, from_round: int, to_round: int) -> APIResponse:
    """Return added/removed/changed nodes and edges between two KG snapshots."""
    if from_round >= to_round:
        raise HTTPException(status_code=400, detail="from_round must be less than to_round")

    from backend.app.services.graph_builder import GraphBuilder  # noqa: PLC0415

    builder = GraphBuilder()
    snap_from = await builder.get_snapshot(graph_id, from_round)
    snap_to = await builder.get_snapshot(graph_id, to_round)

    if not snap_from or not snap_to:
        missing = []
        if not snap_from:
            missing.append(from_round)
        if not snap_to:
            missing.append(to_round)
        raise HTTPException(
            status_code=404,
            detail=f"Snapshot not found for round(s): {missing}",
        )

    nodes_from = {n.get("id", n.get("name", "")): n for n in snap_from.get("nodes", [])}
    nodes_to = {n.get("id", n.get("name", "")): n for n in snap_to.get("nodes", [])}

    added_nodes = [n for nid, n in nodes_to.items() if nid not in nodes_from]
    removed_nodes = [n for nid, n in nodes_from.items() if nid not in nodes_to]

    def _edge_key(e: dict) -> tuple[str, str, str]:
        return (
            e.get("source_id", e.get("source", "")),
            e.get("target_id", e.get("target", "")),
            e.get("relation", e.get("relation_type", "")),
        )

    edges_from = {_edge_key(e): e for e in snap_from.get("edges", [])}
    edges_to = {_edge_key(e): e for e in snap_to.get("edges", [])}

    added_edges = [e for k, e in edges_to.items() if k not in edges_from]
    removed_edges = [e for k, e in edges_from.items() if k not in edges_to]

    changed_edges = []
    for k, e_to in edges_to.items():
        if k in edges_from:
            e_from = edges_from[k]
            if e_from.get("weight") != e_to.get("weight"):
                changed_edges.append(
                    {
                        "edge": e_to,
                        "weight_before": e_from.get("weight"),
                        "weight_after": e_to.get("weight"),
                    }
                )

    return APIResponse(
        success=True,
        data={
            "from_round": from_round,
            "to_round": to_round,
            "added_nodes": added_nodes,
            "removed_nodes": removed_nodes,
            "added_edges": added_edges,
            "removed_edges": removed_edges,
            "changed_edges": changed_edges,
        },
        meta={
            "graph_id": graph_id,
            "nodes_added": len(added_nodes),
            "nodes_removed": len(removed_nodes),
            "edges_added": len(added_edges),
            "edges_removed": len(removed_edges),
            "edges_changed": len(changed_edges),
        },
    )


@router.get("/{session_id}/relationships")
async def get_relationship_states(session_id: str, round_number: int = -1) -> dict:
    """Get relationship states for visualization.

    Returns directional relationship data for all agent pairs.
    round_number=-1 means latest round.
    """
    try:
        async with get_db() as db:
            if round_number == -1:
                cursor = await db.execute(
                    "SELECT MAX(round_number) FROM relationship_states WHERE session_id = ?",
                    (session_id,),
                )
                row = await cursor.fetchone()
                round_number = row[0] if row and row[0] is not None else 0

            cursor = await db.execute(
                """SELECT agent_a_id, agent_b_id, intimacy, passion, commitment,
                          satisfaction, alternatives, investment, trust,
                          interaction_count, round_number
                   FROM relationship_states
                   WHERE session_id = ? AND round_number = ?
                   ORDER BY intimacy DESC""",
                (session_id, round_number),
            )
            rows = await cursor.fetchall()
    except Exception:
        logger.exception("get_relationship_states failed for session %s", session_id)
        raise HTTPException(status_code=500, detail="Relationship states fetch failed")

    return {
        "session_id": session_id,
        "round_number": round_number,
        "relationships": [
            {
                "agent_a": r[0],
                "agent_b": r[1],
                "intimacy": r[2],
                "passion": r[3],
                "commitment": r[4],
                "satisfaction": r[5],
                "alternatives": r[6],
                "investment": r[7],
                "trust": r[8],
                "interaction_count": r[9],
                "rusbult_commitment": max(0.0, min(1.0, (r[5] or 0.0) - (r[6] or 0.0) + (r[7] or 0.0))),
            }
            for r in rows
        ],
    }


@router.get("/{graph_id}/node/{node_id}/evidence")
async def get_node_evidence(graph_id: str, node_id: str) -> APIResponse:
    """Return evidence for a KG node: matching agent memories + data provenance."""
    try:
        async with get_db() as db:
            # Get node details
            node_row = await (
                await db.execute(
                    "SELECT id, entity_type, title, description FROM kg_nodes WHERE session_id = ? AND id = ?",
                    (graph_id, node_id),
                )
            ).fetchone()
            if not node_row:
                raise HTTPException(status_code=404, detail=f"Node {node_id} not found in graph {graph_id}")

            node_label = node_row["title"]

            # Find agent memories mentioning this node's label
            memory_rows = await (
                await db.execute(
                    "SELECT agent_id, memory_text, memory_type, salience_score, round_number, created_at"
                    " FROM agent_memories WHERE session_id = ? AND memory_text LIKE ?"
                    " ORDER BY salience_score DESC LIMIT 20",
                    (graph_id, f"%{node_label}%"),
                )
            ).fetchall()

            # Find data provenance records
            provenance_rows = []
            try:
                provenance_rows = await (
                    await db.execute(
                        "SELECT category, metric, source_type, source_url, last_updated"
                        " FROM data_provenance WHERE metric LIKE ? OR category LIKE ? LIMIT 10",
                        (f"%{node_label}%", f"%{node_label}%"),
                    )
                ).fetchall()
            except Exception:
                logger.debug("data_provenance query failed (table may not exist)")

        return APIResponse(
            success=True,
            data={
                "node_id": node_id,
                "node_label": node_label,
                "node_type": node_row["entity_type"],
                "memories": [dict(r) for r in (memory_rows or [])],
                "provenance": [dict(r) for r in (provenance_rows or [])],
            },
            meta={
                "graph_id": graph_id,
                "memory_count": len(memory_rows or []),
                "provenance_count": len(provenance_rows or []),
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("get_node_evidence failed for graph %s node %s", graph_id, node_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{graph_id}/temporal")
async def get_graph_at_round(graph_id: str, round: int = 0) -> dict:
    """Return KG edges active at a specific simulation round (temporal query).

    Uses valid_from / valid_until columns — no snapshot table required.
    """
    from backend.app.services.kg_temporal_queries import get_kg_edges_at_round

    # Need session_id: look up most recent session for this graph_id
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id FROM simulation_sessions WHERE graph_id = ? ORDER BY created_at DESC LIMIT 1",
            (graph_id,),
        )
        row = await cursor.fetchone()
    if not row:
        return {"success": True, "data": {"edges": [], "round": round}, "meta": {}}
    session_id = row[0]
    edges = await get_kg_edges_at_round(session_id, round)
    return {"success": True, "data": {"edges": edges, "round": round}, "meta": {"count": len(edges)}}
