"""Step 1: Graph building — pre-defined HK Property Market knowledge graph.

Stores nodes/edges in kg_nodes / kg_edges (session_id = graph_id),
then serves them back in D3-compatible format for the force graph.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile

from backend.app.models.request import GraphBuildRequest
from backend.app.models.response import APIResponse, GraphBuildResponse
from backend.app.services.implicit_stakeholder_service import ImplicitStakeholderService
from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

router = APIRouter(prefix="/graph", tags=["graph"])
logger = get_logger("api.graph")

# ---------------------------------------------------------------------------
# Pre-defined HK Property Market Knowledge Graph
# ---------------------------------------------------------------------------

_HK_PROPERTY_NODES: list[dict[str, Any]] = [
    # Districts (location)
    {"id": "district_cwb", "type": "location", "label": "中西區", "description": "香港島核心商業及住宅區", "size": 14},
    {"id": "district_kc", "type": "location", "label": "九龍城", "description": "九龍半島傳統住宅區", "size": 12},
    {"id": "district_st", "type": "location", "label": "沙田", "description": "新界東新市鎮，發展成熟", "size": 13},
    {"id": "district_yl", "type": "location", "label": "元朗", "description": "新界西北，北部都會區發展重點", "size": 12},
    {"id": "district_lantau", "type": "location", "label": "大嶼山", "description": "機場島，北大嶼山新發展區", "size": 11},
    # Banks (organization)
    {"id": "bank_hsbc", "type": "organization", "label": "滙豐銀行", "description": "香港最大按揭銀行之一", "size": 13},
    {"id": "bank_hase", "type": "organization", "label": "恒生銀行", "description": "本地最大零售銀行之一", "size": 12},
    {"id": "bank_bochk", "type": "organization", "label": "中銀香港", "description": "主要發鈔銀行，按揭市場份額大", "size": 12},
    {"id": "bank_sc", "type": "organization", "label": "渣打銀行", "description": "國際銀行，提供多元按揭產品", "size": 11},
    # Developers (organization)
    {"id": "dev_shk", "type": "organization", "label": "新鴻基地產", "description": "香港最大地產商之一", "size": 14},
    {"id": "dev_ck", "type": "organization", "label": "長江實業", "description": "李嘉誠家族旗下地產商", "size": 13},
    {"id": "dev_henderson", "type": "organization", "label": "恒基地產", "description": "李兆基家族旗下地產商", "size": 12},
    # Policies (policy)
    {"id": "policy_bsd", "type": "policy", "label": "印花稅措施", "description": "BSD/SSD，2024年全面撤辣", "size": 13},
    {"id": "policy_mip", "type": "policy", "label": "按揭保險計劃", "description": "HKMC按揭保險，提高上車成數", "size": 12},
    {"id": "policy_stress", "type": "policy", "label": "壓力測試", "description": "HKMA按揭壓力測試（+2%利率）", "size": 12},
    {"id": "policy_vacancy", "type": "policy", "label": "空置稅", "description": "針對一手空置單位嘅稅項", "size": 10},
    {"id": "policy_ndd", "type": "policy", "label": "北部都會區", "description": "新界北部發展計劃，30萬新住宅單位", "size": 13},
    # Economic Indicators (economic)
    {"id": "econ_hibor", "type": "economic", "label": "HIBOR利率", "description": "銀行同業拆息，影響按揭利率", "size": 14},
    {"id": "econ_prime", "type": "economic", "label": "最優惠利率", "description": "Prime Rate，按揭定價基準", "size": 13},
    {"id": "econ_ccl", "type": "economic", "label": "中原城市領先指數", "description": "CCL樓價指數，追蹤二手住宅價格", "size": 14},
    {"id": "econ_unemp", "type": "economic", "label": "失業率", "description": "香港整體失業率，影響置業信心", "size": 12},
    {"id": "econ_cpi", "type": "economic", "label": "通脹率", "description": "消費物價指數，影響實際購買力", "size": 11},
    {"id": "econ_gdp", "type": "economic", "label": "GDP增長", "description": "香港本地生產總值增長率", "size": 12},
    # Person types (person)
    {"id": "person_ftb", "type": "person", "label": "首置買家", "description": "首次置業人士，主要受按揭保險及印花稅影響", "size": 14},
    {"id": "person_upgrader", "type": "person", "label": "換樓客", "description": "現有業主換樓，受SSD及印花稅影響", "size": 13},
    {"id": "person_investor", "type": "person", "label": "投資者", "description": "物業投資者，受BSD及租金回報影響", "size": 12},
    {"id": "person_renter", "type": "person", "label": "租客", "description": "無力置業人士，主要關注租金走勢", "size": 12},
    # Social phenomena (social)
    {"id": "social_afford", "type": "social", "label": "上車難問題", "description": "年輕人置業困難，樓價收入比全球最高", "size": 14},
    {"id": "social_emigrate", "type": "social", "label": "移民潮", "description": "香港居民淨移出，影響樓市需求", "size": 13},
    {"id": "social_confidence", "type": "social", "label": "置業信心", "description": "市場對樓市走勢嘅整體信心指標", "size": 13},
    # External — US / Global (economic)
    {"id": "ext_fed", "type": "economic", "label": "美聯儲利率", "description": "聯邦基金利率，透過聯繫匯率直接影響HIBOR及按揭利率", "size": 15},
    {"id": "ext_usd_hkd", "type": "economic", "label": "聯繫匯率", "description": "美元/港元7.75-7.85聯繫匯率制度，港元利率跟隨美元", "size": 13},
    {"id": "ext_us_recession", "type": "economic", "label": "美國衰退風險", "description": "美國經濟衰退機率，影響全球資金風險偏好", "size": 11},
    # External — China economy (economic)
    {"id": "ext_china_gdp", "type": "economic", "label": "中國GDP增長", "description": "中國實際GDP增長率，影響北水流入及內地買家能力", "size": 14},
    {"id": "ext_china_property", "type": "economic", "label": "內房危機", "description": "恒大/碧桂園等內房危機，衝擊內地買家信心及資金", "size": 13},
    {"id": "ext_rmb", "type": "economic", "label": "人民幣匯率", "description": "RMB/HKD匯率，影響內地資金購買香港資產嘅成本", "size": 12},
    {"id": "ext_northbound", "type": "economic", "label": "北水流入", "description": "滬深港通北向資金流入，反映內地資金對港股偏好", "size": 13},
    # External — China politics (policy)
    {"id": "ext_china_policy", "type": "policy", "label": "中國內地政策", "description": "內地政治方向、監管政策、對港政策等", "size": 13},
    {"id": "ext_us_china_trade", "type": "policy", "label": "中美貿易關係", "description": "中美貿易戰/科技戰，影響香港作為國際金融中心地位", "size": 13},
    # External — Geopolitical (social)
    {"id": "ext_taiwan_strait", "type": "social", "label": "台海局勢", "description": "台海緊張程度，地緣政治風險影響國際資金去向及移民潮", "size": 14},
    # External — Shenzhen / GBA (location)
    {"id": "ext_shenzhen", "type": "location", "label": "深圳低成本生活", "description": "深圳生活成本僅香港38%，吸引港人跨境居住返港上班", "size": 14},
    {"id": "ext_gba", "type": "location", "label": "大灣區發展", "description": "粵港澳大灣區整合，30分鐘生活圈，推動北部都會區價值", "size": 13},
    {"id": "ext_crossborder", "type": "social", "label": "跨境生活模式", "description": "港人北上居住、深圳工作，影響香港租務及置業需求", "size": 12},
]

_HK_PROPERTY_EDGES: list[dict[str, Any]] = [
    # Interest rates chain
    {"source": "econ_hibor", "target": "econ_prime", "label": "影響", "weight": 2.0},
    {"source": "econ_prime", "target": "bank_hsbc", "label": "定價基準", "weight": 1.5},
    {"source": "econ_prime", "target": "bank_hase", "label": "定價基準", "weight": 1.5},
    {"source": "econ_prime", "target": "bank_bochk", "label": "定價基準", "weight": 1.5},
    {"source": "econ_prime", "target": "bank_sc", "label": "定價基準", "weight": 1.5},
    # Banks implement policies
    {"source": "bank_hsbc", "target": "policy_stress", "label": "執行", "weight": 1.5},
    {"source": "bank_hase", "target": "policy_stress", "label": "執行", "weight": 1.5},
    {"source": "bank_bochk", "target": "policy_mip", "label": "參與", "weight": 1.2},
    {"source": "bank_hsbc", "target": "policy_mip", "label": "參與", "weight": 1.2},
    # Banks lend to person types
    {"source": "bank_hsbc", "target": "person_ftb", "label": "提供按揭", "weight": 2.0},
    {"source": "bank_hase", "target": "person_ftb", "label": "提供按揭", "weight": 1.8},
    {"source": "bank_bochk", "target": "person_upgrader", "label": "提供按揭", "weight": 1.5},
    {"source": "bank_sc", "target": "person_investor", "label": "提供按揭", "weight": 1.2},
    # Policies → Person types
    {"source": "policy_mip", "target": "person_ftb", "label": "協助置業", "weight": 2.0},
    {"source": "policy_stress", "target": "person_ftb", "label": "限制借貸", "weight": 1.5},
    {"source": "policy_bsd", "target": "person_investor", "label": "增加成本", "weight": 2.0},
    {"source": "policy_bsd", "target": "person_upgrader", "label": "影響換樓", "weight": 1.5},
    {"source": "policy_vacancy", "target": "dev_shk", "label": "規管", "weight": 1.0},
    {"source": "policy_vacancy", "target": "dev_ck", "label": "規管", "weight": 1.0},
    {"source": "policy_ndd", "target": "district_yl", "label": "發展計劃", "weight": 2.0},
    {"source": "policy_ndd", "target": "dev_henderson", "label": "土地機遇", "weight": 1.5},
    {"source": "policy_ndd", "target": "person_ftb", "label": "增加供應", "weight": 1.5},
    # Developers → Districts
    {"source": "dev_shk", "target": "district_cwb", "label": "發展項目", "weight": 1.5},
    {"source": "dev_shk", "target": "district_st", "label": "發展項目", "weight": 1.5},
    {"source": "dev_ck", "target": "district_lantau", "label": "發展項目", "weight": 1.2},
    {"source": "dev_henderson", "target": "district_kc", "label": "發展項目", "weight": 1.2},
    {"source": "dev_henderson", "target": "district_yl", "label": "發展項目", "weight": 1.5},
    # Economic indicators → CCL
    {"source": "econ_hibor", "target": "econ_ccl", "label": "負相關", "weight": 2.0},
    {"source": "econ_unemp", "target": "econ_ccl", "label": "影響樓價", "weight": 1.5},
    {"source": "econ_gdp", "target": "econ_ccl", "label": "正相關", "weight": 1.5},
    {"source": "econ_cpi", "target": "econ_prime", "label": "通脹壓力", "weight": 1.2},
    # CCL → Districts
    {"source": "econ_ccl", "target": "district_cwb", "label": "反映樓價", "weight": 1.5},
    {"source": "econ_ccl", "target": "district_kc", "label": "反映樓價", "weight": 1.2},
    {"source": "econ_ccl", "target": "district_st", "label": "反映樓價", "weight": 1.2},
    {"source": "econ_ccl", "target": "district_yl", "label": "反映樓價", "weight": 1.0},
    # Economic → Social
    {"source": "econ_unemp", "target": "social_confidence", "label": "削弱信心", "weight": 1.5},
    {"source": "econ_hibor", "target": "social_afford", "label": "增加負擔", "weight": 2.0},
    {"source": "econ_ccl", "target": "social_afford", "label": "樓價高企", "weight": 2.0},
    {"source": "social_emigrate", "target": "econ_ccl", "label": "減少需求", "weight": 1.5},
    # Social → Person types
    {"source": "social_afford", "target": "person_ftb", "label": "困境", "weight": 2.0},
    {"source": "social_afford", "target": "person_renter", "label": "被迫租住", "weight": 1.8},
    {"source": "social_emigrate", "target": "person_renter", "label": "加劇趨勢", "weight": 1.2},
    {"source": "social_confidence", "target": "person_investor", "label": "影響決策", "weight": 1.5},
    {"source": "social_confidence", "target": "person_upgrader", "label": "影響決策", "weight": 1.2},
    # Person types → Districts
    {"source": "person_ftb", "target": "district_yl", "label": "首選置業", "weight": 1.5},
    {"source": "person_ftb", "target": "district_st", "label": "首選置業", "weight": 1.2},
    {"source": "person_investor", "target": "district_cwb", "label": "投資核心區", "weight": 1.5},
    {"source": "person_upgrader", "target": "district_kc", "label": "換樓目標", "weight": 1.2},
    {"source": "person_renter", "target": "district_kc", "label": "租住", "weight": 1.0},
    # ---- External factor edges ----
    # US Fed → HK interest rates (via peg)
    {"source": "ext_fed", "target": "ext_usd_hkd", "label": "聯繫匯率傳導", "weight": 2.0},
    {"source": "ext_fed", "target": "econ_hibor", "label": "利率傳導（聯繫匯率）", "weight": 2.5},
    {"source": "ext_fed", "target": "econ_prime", "label": "間接影響", "weight": 2.0},
    {"source": "ext_us_recession", "target": "ext_fed", "label": "觸發減息", "weight": 1.5},
    {"source": "ext_fed", "target": "social_confidence", "label": "加息打壓信心", "weight": 1.5},
    {"source": "ext_fed", "target": "social_afford", "label": "加劇負擔", "weight": 2.0},
    # China economy → HK market
    {"source": "ext_china_gdp", "target": "econ_ccl", "label": "內地買家需求", "weight": 1.8},
    {"source": "ext_china_gdp", "target": "econ_hibor", "label": "資金流向", "weight": 1.2},
    {"source": "ext_china_property", "target": "ext_china_gdp", "label": "拖累增長", "weight": 1.8},
    {"source": "ext_china_property", "target": "person_investor", "label": "內地資金撤退", "weight": 1.5},
    {"source": "ext_rmb", "target": "person_investor", "label": "匯率影響購買力", "weight": 1.5},
    {"source": "ext_northbound", "target": "econ_hibor", "label": "流動性", "weight": 1.0},
    {"source": "ext_northbound", "target": "social_confidence", "label": "帶動信心", "weight": 1.3},
    {"source": "ext_china_policy", "target": "ext_china_gdp", "label": "政策主導", "weight": 1.8},
    {"source": "ext_china_policy", "target": "ext_northbound", "label": "影響資金流向", "weight": 1.5},
    # US-China trade tension
    {"source": "ext_us_china_trade", "target": "ext_china_gdp", "label": "貿易戰衝擊", "weight": 1.8},
    {"source": "ext_us_china_trade", "target": "social_confidence", "label": "不確定性", "weight": 1.5},
    {"source": "ext_us_china_trade", "target": "social_emigrate", "label": "前景憂慮", "weight": 1.3},
    # Taiwan Strait → HK sentiment
    {"source": "ext_taiwan_strait", "target": "social_emigrate", "label": "加速移民", "weight": 2.0},
    {"source": "ext_taiwan_strait", "target": "social_confidence", "label": "打壓信心", "weight": 2.0},
    {"source": "ext_taiwan_strait", "target": "econ_ccl", "label": "資本外流壓樓價", "weight": 1.8},
    {"source": "ext_taiwan_strait", "target": "person_investor", "label": "投資者撤資", "weight": 1.5},
    {"source": "ext_taiwan_strait", "target": "ext_us_china_trade", "label": "地緣政治聯動", "weight": 1.5},
    # Shenzhen / GBA → HK housing demand
    {"source": "ext_shenzhen", "target": "person_renter", "label": "吸引北上居住", "weight": 2.0},
    {"source": "ext_shenzhen", "target": "person_ftb", "label": "替代置業選項", "weight": 1.8},
    {"source": "ext_shenzhen", "target": "social_afford", "label": "紓緩壓力", "weight": 1.5},
    {"source": "ext_shenzhen", "target": "ext_crossborder", "label": "推動跨境生活", "weight": 2.0},
    {"source": "ext_crossborder", "target": "econ_ccl", "label": "減少本地需求", "weight": 1.5},
    {"source": "ext_crossborder", "target": "social_emigrate", "label": "另類移動方式", "weight": 1.2},
    {"source": "ext_crossborder", "target": "district_yl", "label": "元朗口岸效應", "weight": 1.5},
    {"source": "ext_gba", "target": "policy_ndd", "label": "政策配合", "weight": 2.0},
    {"source": "ext_gba", "target": "district_yl", "label": "帶動北區發展", "weight": 1.8},
    {"source": "ext_gba", "target": "ext_crossborder", "label": "促進跨境生活", "weight": 1.8},
    {"source": "ext_gba", "target": "person_ftb", "label": "大灣區置業選項", "weight": 1.3},
    {"source": "ext_china_policy", "target": "ext_gba", "label": "政策推動", "weight": 2.0},
]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _persist_graph(graph_id: str, nodes: list[dict], edges: list[dict]) -> None:
    """Write nodes and edges to kg_nodes / kg_edges (session_id = graph_id).

    Node ids are prefixed with the first 8 chars of graph_id (hex) so each
    graph gets a unique primary key even though node "types" are shared.
    Uses executemany for efficient batch insertion.
    """
    prefix = graph_id.replace("-", "")[:8]

    node_rows = [
        (
            f"{prefix}_{n['id']}",
            graph_id,
            n["type"],
            n["label"],
            n.get("description", ""),
            json.dumps({"size": n.get("size", 10)}),
        )
        for n in nodes
    ]
    edge_rows = [
        (
            graph_id,
            f"{prefix}_{e['source']}",
            f"{prefix}_{e['target']}",
            e["label"],
            e.get("weight", 1.0),
        )
        for e in edges
    ]

    async with get_db() as db:
        await db.execute("DELETE FROM kg_edges WHERE session_id = ?", (graph_id,))
        await db.execute("DELETE FROM kg_nodes WHERE session_id = ?", (graph_id,))
        await db.executemany(
            "INSERT INTO kg_nodes (id, session_id, entity_type, title, description, properties)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            node_rows,
        )
        await db.executemany(
            "INSERT INTO kg_edges (session_id, source_id, target_id, relation_type, weight)"
            " VALUES (?, ?, ?, ?, ?)",
            edge_rows,
        )
        await db.commit()
    logger.info("Persisted graph %s: %d nodes, %d edges", graph_id, len(nodes), len(edges))


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
async def build_graph(req: GraphBuildRequest) -> APIResponse:
    """Build knowledge graph from scenario type and seed text.

    Step 1: Persist the pre-defined HK Property Market base graph.
    Step 2: If seed_text is provided, run TextProcessor + SeedGraphInjector
            to extract entities and inject them ON TOP of the base graph.
    """
    graph_id = str(uuid.uuid4())

    # --- Step 1: base graph ---
    try:
        await _persist_graph(graph_id, _HK_PROPERTY_NODES, _HK_PROPERTY_EDGES)
    except Exception:
        logger.exception("Failed to persist base graph %s", graph_id)
        raise HTTPException(status_code=500, detail="Graph persistence failed")

    base_node_count = len(_HK_PROPERTY_NODES)
    base_edge_count = len(_HK_PROPERTY_EDGES)
    seed_nodes = 0
    seed_edges = 0
    implicit_nodes = 0
    mem_result = None

    # --- Step 2: seed injection (best-effort, never blocks the response) ---
    if req.seed_text and req.seed_text.strip():
        try:
            from backend.app.services.text_processor import TextProcessor  # noqa: PLC0415
            from backend.app.services.seed_graph_injector import SeedGraphInjector  # noqa: PLC0415

            processor = TextProcessor()
            processed = await processor.process(req.seed_text)

            injector = SeedGraphInjector()
            inject_result = await injector.inject(graph_id, processed)
            seed_nodes = inject_result.get("seed_nodes", 0)
            seed_edges = inject_result.get("seed_edges", 0)
            logger.info(
                "Seed injection for graph %s: +%d nodes, +%d edges",
                graph_id, seed_nodes, seed_edges,
            )
        except Exception:
            logger.exception(
                "Seed injection failed for graph %s — continuing with base graph",
                graph_id,
            )

        # --- Implicit stakeholder discovery (best-effort, Option A) ---
        try:
            implicit_svc = ImplicitStakeholderService()
            existing_for_dedup = [
                {"id": str(n.get("id", "")), "label": str(n.get("label") or n.get("title") or ""), "entity_type": str(n.get("type") or n.get("entity_type") or "")}
                for n in (_HK_PROPERTY_NODES or [])
            ]
            discovery = await implicit_svc.discover(graph_id, req.seed_text, existing_for_dedup)
            implicit_nodes = discovery.nodes_added
            logger.info(
                "Implicit stakeholder discovery for graph %s: +%d nodes",
                graph_id, implicit_nodes,
            )
        except Exception:
            logger.exception(
                "Implicit stakeholder discovery failed for graph %s — continuing",
                graph_id,
            )

        # Memory initialization (best-effort, never blocks graph build response)
        mem_result = None
        try:
            from backend.app.services.memory_initialization import MemoryInitializationService  # noqa: PLC0415
            mem_svc = MemoryInitializationService()
            mem_result = await mem_svc.build_from_graph(graph_id, req.seed_text)
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

    total_nodes = base_node_count + seed_nodes
    total_edges = base_edge_count + seed_edges

    result = GraphBuildResponse(
        graph_id=graph_id,
        node_count=total_nodes,
        edge_count=total_edges,
        entity_types=list({n["type"] for n in _HK_PROPERTY_NODES}),
        relation_types=list({e["label"] for e in _HK_PROPERTY_EDGES}),
    )
    return APIResponse(
        success=True,
        data=result.model_dump(),
        meta={
            "scenario_type": req.scenario_type,
            "base_nodes": base_node_count,
            "base_edges": base_edge_count,
            "seed_nodes": seed_nodes,
            "seed_edges": seed_edges,
            "implicit_nodes": implicit_nodes,
            "world_context_count": mem_result.world_context_count if mem_result else 0,
            "persona_template_count": mem_result.persona_template_count if mem_result else 0,
        },
    )


@router.get("/{graph_id}", response_model=APIResponse)
async def get_graph(graph_id: str) -> APIResponse:
    """Get full graph data (nodes + edges) in D3-compatible format."""
    try:
        async with get_db() as db:
            node_rows = await (
                await db.execute(
                    "SELECT id, entity_type, title, description, properties"
                    " FROM kg_nodes WHERE session_id = ?",
                    (graph_id,),
                )
            ).fetchall()
            edge_rows = await (
                await db.execute(
                    "SELECT source_id, target_id, relation_type, weight"
                    " FROM kg_edges WHERE session_id = ?",
                    (graph_id,),
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
            "graph_id": graph_id,
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
                "SELECT id, entity_type, title, description, properties"
                " FROM kg_nodes WHERE session_id = ?",
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
                "SELECT source_id, target_id, relation_type, weight"
                " FROM kg_edges WHERE session_id = ?",
                (graph_id,),
            )
        ).fetchall()

    edges = [_row_to_edge(r) for r in rows]
    return APIResponse(success=True, data=edges, meta={"graph_id": graph_id, "count": len(edges)})


_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
_ALLOWED_CONTENT_TYPES = frozenset({
    "application/pdf",
    "text/plain",
    "text/markdown",
    "application/octet-stream",  # some browsers send this for .md
})
_ALLOWED_EXTENSIONS = frozenset({".pdf", ".txt", ".md", ".markdown"})


@router.post("/upload-seed", response_model=APIResponse)
async def upload_seed_file(file: UploadFile = File(...)) -> APIResponse:
    """Accept a PDF / Markdown / TXT seed file and return its text content.

    Limits:
    - Max size: 10 MB
    - Accepted types: PDF, Markdown (.md), plain text (.txt)
    """
    import io  # noqa: PLC0415

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
async def analyze_seed(req: GraphBuildRequest) -> APIResponse:
    """Analyze seed text and return structured insights without building graph."""
    from backend.app.services.text_processor import TextProcessor  # noqa: PLC0415

    if not req.seed_text or not req.seed_text.strip():
        raise HTTPException(status_code=400, detail="seed_text is required")

    try:
        processor = TextProcessor()
        result = await processor.process(req.seed_text)

        # Also get agent suggestions
        suggestions = await processor.suggest_agents(result)

        return APIResponse(
            success=True,
            data={
                "language": result.language,
                "entities": [
                    {"name": e.name, "type": e.type, "relevance": e.relevance}
                    for e in result.entities
                ],
                "timeline": [
                    {"date_hint": t.date_hint, "event": t.event}
                    for t in result.timeline
                ],
                "stakeholders": [
                    {"group": s.group, "impact": s.impact, "description": s.description}
                    for s in result.stakeholders
                ],
                "sentiment": result.sentiment,
                "key_claims": list(result.key_claims),
                "suggested_scenario": result.suggested_scenario,
                "suggested_districts": list(result.suggested_districts),
                "confidence": result.confidence,
                "agent_suggestions": suggestions,
            },
            meta={"scenario_type": req.scenario_type},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("analyze_seed failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


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
async def get_node_neighborhood(
    graph_id: str, node_id: str, hops: int = 2
) -> APIResponse:
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
            for row in (rows or []):
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
async def get_graph_diff(
    graph_id: str, from_round: int, to_round: int
) -> APIResponse:
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
                changed_edges.append({
                    "edge": e_to,
                    "weight_before": e_from.get("weight"),
                    "weight_after": e_to.get("weight"),
                })

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
            node_row = await (await db.execute(
                "SELECT id, entity_type, title, description FROM kg_nodes WHERE session_id = ? AND id = ?",
                (graph_id, node_id),
            )).fetchone()
            if not node_row:
                raise HTTPException(status_code=404, detail=f"Node {node_id} not found in graph {graph_id}")

            node_label = node_row["title"]

            # Find agent memories mentioning this node's label
            memory_rows = await (await db.execute(
                "SELECT agent_id, memory_text, memory_type, salience_score, round_number, created_at FROM agent_memories WHERE session_id = ? AND memory_text LIKE ? ORDER BY salience_score DESC LIMIT 20",
                (graph_id, f"%{node_label}%"),
            )).fetchall()

            # Find data provenance records
            provenance_rows = []
            try:
                provenance_rows = await (await db.execute(
                    "SELECT category, metric, source_type, source_url, last_updated FROM data_provenance WHERE metric LIKE ? OR category LIKE ? LIMIT 10",
                    (f"%{node_label}%", f"%{node_label}%"),
                )).fetchall()
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
            meta={"graph_id": graph_id, "memory_count": len(memory_rows or []), "provenance_count": len(provenance_rows or [])},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("get_node_evidence failed for graph %s node %s", graph_id, node_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
