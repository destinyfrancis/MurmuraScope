"""Entity extraction from seed text and HK data.

Extracts concrete entities (nodes) and relationships (edges) using an LLM,
guided by the ontology's entity types and relation types.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

# ---------------------------------------------------------------------------
# Alias map for entity deduplication
# ---------------------------------------------------------------------------
# Maps canonical entity name → frozenset of known aliases.
# When an extracted node title matches an alias, it is remapped to the
# canonical name and its ID is unified with any existing canonical node.
_ALIAS_MAP: dict[str, frozenset[str]] = {
    "嗶哩嗶哩": frozenset({"B站", "bilibili", "哔哩哔哩", "b站", "Bilibili", "B站(嗶哩嗶哩)"}),
    "微博": frozenset({"Weibo", "weibo", "新浪微博", "Sina Weibo"}),
    "微信": frozenset({"WeChat", "wechat", "Wechat", "微信公眾號", "微信公众号"}),
    "抖音": frozenset({"TikTok", "Douyin", "douyin", "tiktok", "TikTok(抖音)"}),
    "小紅書": frozenset({"小红书", "RedNote", "RED", "Xiaohongshu", "rednote"}),
    "知乎": frozenset({"Zhihu", "zhihu"}),
    "百度": frozenset({"Baidu", "baidu", "百度搜索"}),
    "騰訊": frozenset({"腾讯", "Tencent", "tencent"}),
    "阿里巴巴": frozenset({"阿里", "Alibaba", "alibaba", "BABA", "阿里集團", "阿里集团"}),
    "字節跳動": frozenset({"字节跳动", "ByteDance", "bytedance", "Bytedance"}),
    "京東": frozenset({"京东", "JD.com", "JD", "jd"}),
    "拼多多": frozenset({"Pinduoduo", "pinduoduo", "PDD"}),
    "美團": frozenset({"美团", "Meituan", "meituan"}),
    "滴滴": frozenset({"Didi", "didi", "滴滴出行"}),
    "華為": frozenset({"华为", "Huawei", "huawei", "HUAWEI"}),
    "小米": frozenset({"Xiaomi", "xiaomi", "XIAOMI", "MI"}),
    "中央電視台": frozenset({"CCTV", "cctv", "央視", "央视", "中央电视台"}),
    "人民日報": frozenset({"人民日报", "People's Daily", "peoples daily"}),
    "新華社": frozenset({"新华社", "Xinhua", "xinhua", "新华通讯社"}),
    "港交所": frozenset({"HKEX", "hkex", "香港交易所", "香港证券交易所", "香港證券交易所"}),
}

from backend.app.utils.llm_client import LLMClient, get_agent_provider_model
from backend.app.utils.logger import get_logger
from backend.app.utils.prompt_security import sanitize_seed_text
from backend.prompts.ontology_prompts import (
    ENTITY_EXTRACTION_SYSTEM,
    ENTITY_EXTRACTION_USER,
    RELATIONSHIP_DETECTION_SYSTEM,
    RELATIONSHIP_DETECTION_USER,
)

logger = get_logger("entity_extractor")

# ---------------------------------------------------------------------------
# Dynamic alias support (Phase 3.3)
# ---------------------------------------------------------------------------

# In-session alias extensions: populated by enrich_aliases() and
# generate_dynamic_aliases(). Keyed by canonical title → set of lowercase aliases.
_dynamic_aliases: dict[str, set[str]] = {}


def _build_reverse_alias_lookup(extra: dict[str, set[str]] | None = None) -> dict[str, str]:
    """Build a unified alias → canonical reverse lookup.

    Merges the static ``_ALIAS_MAP`` with any ``extra`` dynamic aliases
    collected during the current session.

    Args:
        extra: Optional dict of canonical_title → set of lowercase aliases
               to merge on top of _ALIAS_MAP.

    Returns:
        Dict mapping each alias (lowercase) to its canonical title.
    """
    lookup: dict[str, str] = {}
    for canonical, aliases in _ALIAS_MAP.items():
        for alias in aliases:
            lookup[alias.lower()] = canonical
        lookup[canonical.lower()] = canonical
    if extra:
        for canonical, aliases in extra.items():
            for alias in aliases:
                lookup[alias.lower()] = canonical
    return lookup


def generate_dynamic_aliases(
    entities: list[dict],
    *,
    max_per_entity: int = 4,
) -> dict[str, set[str]]:
    """Infer additional aliases for extracted entities using rule-based heuristics.

    Rules applied (all case-insensitive):
      1. Strip common legal suffixes (Ltd., Inc., Corp., Group, 集團, 公司 ...)
      2. Generate English acronyms from multi-word titles (e.g. "Goldman Sachs" → "gs")
      3. Add SC ↔ TC character-set variants for common pairs
      4. Strip leading "The " / "the " prefix

    This function is the fast/cheap path — no LLM calls.
    For LLM-assisted alias suggestion, use ``EntityExtractor.enrich_aliases()``.

    Args:
        entities: List of node dicts with at least a ``title`` key.
        max_per_entity: Maximum number of generated aliases per entity.

    Returns:
        Dict of canonical_title (original case) → set of lowercased aliases.
    """
    import re  # noqa: PLC0415

    _STRIP_SUFFIX_RE = re.compile(
        r"\s+(ltd\.?|inc\.?|corp\.?|co\.?|plc|group|holdings?|limited|holding)\s*$",
        re.IGNORECASE,
    )
    _STRIP_CJK_SUFFIX_RE = re.compile(r"[集局社行]$")
    _STRIP_PREFIX_RE = re.compile(r"^the\s+", re.IGNORECASE)

    # Known TC→SC mapping pairs (single char substitutions only)
    _TC_SC: dict[str, str] = {
        "訊": "讯", "騰": "腾", "號": "号", "創": "创", "領": "领",
        "灣": "湾", "億": "亿", "幣": "币", "實": "实", "場": "场",
    }
    _SC_TC: dict[str, str] = {v: k for k, v in _TC_SC.items()}

    result: dict[str, set[str]] = {}

    for entity in entities:
        title: str = entity.get("title", "").strip()
        if not title:
            continue

        aliases: set[str] = set()

        # Rule 1a: strip English legal suffixes
        stripped = _STRIP_SUFFIX_RE.sub("", title).strip()
        # Rule 1b: strip CJK company suffixes
        stripped = _STRIP_CJK_SUFFIX_RE.sub("", stripped).strip()
        # Rule 1c: strip "The " prefix
        stripped = _STRIP_PREFIX_RE.sub("", stripped).strip()
        if stripped and stripped.lower() != title.lower():
            aliases.add(stripped.lower())

        # Rule 2: English acronym from capitalised words
        words = re.findall(r"[A-Z][a-z]+|[A-Z]{2,}", title)
        if len(words) >= 2:
            acronym = "".join(w[0].upper() for w in words if len(w) >= 2)
            if len(acronym) >= 2:
                aliases.add(acronym.lower())

        # Rule 3: TC ↔ SC transliteration (single-char substitution)
        sc_variant = title
        for tc, sc in _TC_SC.items():
            sc_variant = sc_variant.replace(tc, sc)
        if sc_variant.lower() != title.lower():
            aliases.add(sc_variant.lower())

        tc_variant = title
        for sc, tc in _SC_TC.items():
            tc_variant = tc_variant.replace(sc, tc)
        if tc_variant.lower() != title.lower():
            aliases.add(tc_variant.lower())

        aliases.discard(title.lower())  # never alias to self
        if aliases:
            result[title] = set(list(aliases)[:max_per_entity])

    return result



class EntityExtractor:
    """Extract entities and relationships from text and structured HK data.

    Uses an LLM to perform named entity recognition and relation extraction
    within the ontology defined by the provided type lists.
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        provider: str | None = None,
    ) -> None:
        self._llm = llm_client or LLMClient()
        self._provider = provider or get_agent_provider_model()[0]

    async def extract(
        self,
        seed_text: str,
        hk_data: dict[str, Any],
        entity_types: list[str],
        relation_types: list[str],
        *,
        enrich_aliases: bool = True,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Extract nodes and edges from seed text and HK data.

        Args:
            seed_text: Scenario narrative text.
            hk_data: Supplementary structured HK data.
            entity_types: Allowed entity types from the ontology.
            relation_types: Allowed relation types from the ontology.
            enrich_aliases: If True (default), auto-generate dynamic aliases for
                            extracted entities and apply them to deduplication.

        Returns:
            A tuple of (nodes, edges) where each node is a dict with keys
            ``{id, entity_type, title, description, properties}`` and each
            edge is ``{source_id, target_id, relation_type, description, weight}``.
        """
        messages = [
            {"role": "system", "content": ENTITY_EXTRACTION_SYSTEM},
            {
                "role": "user",
                "content": ENTITY_EXTRACTION_USER.format(
                    entity_types=", ".join(entity_types),
                    relation_types=", ".join(relation_types),
                    seed_text=sanitize_seed_text(seed_text),
                    hk_data_json=json.dumps(hk_data, ensure_ascii=False, indent=2),
                ),
            },
        ]

        try:
            result = await self._llm.chat_json(
                messages,
                provider=self._provider,
                temperature=0.3,
                max_tokens=8192,
            )
            raw_nodes = result.get("nodes", [])
            raw_edges = result.get("edges", [])

            nodes = _validate_nodes(raw_nodes, entity_types)

            # Phase 3.3: generate dynamic aliases before deduplication
            if enrich_aliases and nodes:
                dynamic = generate_dynamic_aliases(nodes)
                _dynamic_aliases.update(dynamic)
                logger.debug(
                    "Dynamic aliases generated for %d entities (%d total entries)",
                    len(dynamic),
                    sum(len(v) for v in dynamic.values()),
                )

            edges = _validate_edges(raw_edges, nodes, relation_types)
            nodes, edges = _deduplicate_nodes(nodes, edges)

            logger.info("Extracted %d nodes and %d edges", len(nodes), len(edges))
            return nodes, edges

        except Exception:
            logger.exception("Entity extraction failed")
            return [], []

    async def enrich_aliases(
        self,
        nodes: list[dict[str, Any]],
        *,
        provider: str | None = None,
        model: str | None = None,
        max_suggestions: int = 5,
    ) -> dict[str, list[str]]:
        """Use LLM to suggest additional aliases for extracted entities.

        This is the *expensive* alias path (one LLM call per batch of nodes).
        Call this after initial ``extract()`` when higher deduplication quality
        is needed.  Results are merged into ``_dynamic_aliases`` for use in
        subsequent deduplication calls.

        Args:
            nodes: Extracted entity nodes.
            provider: LLM provider (defaults to instance provider).
            model: LLM model override.
            max_suggestions: Max aliases per entity to accept.

        Returns:
            Dict of canonical_title → list of suggested alias strings.
        """
        if not nodes:
            return {}

        _provider = provider or self._provider
        entity_list = [{"title": n["title"], "type": n["entity_type"]} for n in nodes[:30]]
        messages = [
            {
                "role": "system",
                "content": (
                    "You are an entity alias specialist. For each entity, return a JSON object mapping "
                    "entity title → list of alternative names (abbreviations, translations, nicknames, "
                    "ticker symbols). Max "
                    + str(max_suggestions)
                    + " aliases per entity. Only include widely-recognised aliases. "
                    "Return ONLY valid JSON, no explanation."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Generate aliases for these entities:\n"
                    + json.dumps(entity_list, ensure_ascii=False)
                ),
            },
        ]
        try:
            raw = await self._llm.chat_json(
                messages,
                provider=_provider,
                model=model,
                temperature=0.1,
                max_tokens=1024,
            )
            # raw should be {title: [alias, ...]}
            enriched: dict[str, list[str]] = {}
            for title, aliases in raw.items():
                if isinstance(aliases, list):
                    clean = [str(a).strip() for a in aliases if isinstance(a, str) and a.strip()]
                    if clean:
                        enriched[title] = clean[:max_suggestions]
                        _dynamic_aliases.setdefault(title, set()).update(
                            a.lower() for a in clean
                        )
            logger.info(
                "enrich_aliases: LLM suggested aliases for %d/%d entities",
                len(enriched),
                len(nodes),
            )
            return enriched
        except Exception:
            logger.warning("enrich_aliases LLM call failed", exc_info=True)
            return {}

    async def extract_from_round(
        self,
        existing_nodes: list[dict[str, Any]],
        relation_types: list[str],
        round_context: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Extract new/updated edges from a simulation round.

        Args:
            existing_nodes: Current graph nodes.
            relation_types: Allowed relation types.
            round_context: Text describing what happened in this round.

        Returns:
            A tuple of (new_edges, updated_edges).
        """
        entities_summary = [
            {"id": n["id"], "title": n["title"], "entity_type": n["entity_type"]} for n in existing_nodes
        ]

        messages = [
            {"role": "system", "content": RELATIONSHIP_DETECTION_SYSTEM},
            {
                "role": "user",
                "content": RELATIONSHIP_DETECTION_USER.format(
                    entities_json=json.dumps(entities_summary, ensure_ascii=False, indent=2),
                    relation_types=", ".join(relation_types),
                    round_context=round_context,
                ),
            },
        ]

        try:
            result = await self._llm.chat_json(
                messages,
                provider=self._provider,
                temperature=0.3,
                max_tokens=2048,
            )
            new_edges = result.get("new_edges", [])
            updated_edges = result.get("updated_edges", [])

            node_ids = {n["id"] for n in existing_nodes}
            new_edges = [e for e in new_edges if e.get("source_id") in node_ids and e.get("target_id") in node_ids]

            logger.info(
                "Round extraction: %d new edges, %d updated edges",
                len(new_edges),
                len(updated_edges),
            )
            return new_edges, updated_edges

        except Exception:
            logger.exception("Round entity extraction failed")
            return [], []


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_nodes(
    raw_nodes: list[dict[str, Any]],
    entity_types: list[str],
) -> list[dict[str, Any]]:
    """Validate and normalise extracted nodes."""
    valid_types = set(entity_types)
    validated: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for node in raw_nodes:
        node_id = node.get("id", "")
        if not node_id or not node.get("title"):
            continue
        if node.get("entity_type") not in valid_types:
            continue
        if node_id in seen_ids:
            node_id = f"{node_id}_{uuid.uuid4().hex[:6]}"

        seen_ids.add(node_id)
        validated.append(
            {
                "id": node_id,
                "entity_type": node["entity_type"],
                "title": node["title"],
                "description": node.get("description", ""),
                "properties": node.get("properties", {}),
            }
        )

    return validated


def _validate_edges(
    raw_edges: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
    relation_types: list[str],
) -> list[dict[str, Any]]:
    """Validate edges: ensure source/target exist and relation type is valid."""
    node_ids = {n["id"] for n in nodes}
    valid_rels = set(relation_types)
    validated: list[dict[str, Any]] = []

    for edge in raw_edges:
        src = edge.get("source_id", "")
        tgt = edge.get("target_id", "")
        rel = edge.get("relation_type", "")

        if src not in node_ids or tgt not in node_ids:
            continue
        if rel not in valid_rels:
            continue

        weight = edge.get("weight", 1.0)
        if not isinstance(weight, (int, float)):
            weight = 1.0
        weight = max(0.1, min(1.0, float(weight)))

        validated.append(
            {
                "source_id": src,
                "target_id": tgt,
                "relation_type": rel,
                "description": edge.get("description", ""),
                "weight": weight,
            }
        )

    return validated


# ---------------------------------------------------------------------------
# Entity deduplication
# ---------------------------------------------------------------------------


def _deduplicate_nodes(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Merge duplicate nodes using alias lookup.

    Performs alias-based deduplication: if a node's title matches a known
    alias in ``_ALIAS_MAP``, its ID is remapped to the canonical form and
    duplicate nodes are merged (the first-seen canonical node is kept).

    All edge ``source_id``/``target_id`` references are updated to reflect
    the canonical IDs after merging.

    Returns:
        A tuple of (deduplicated_nodes, remapped_edges).
    """
    # Build reverse lookup: static _ALIAS_MAP + dynamic aliases accumulated this session
    alias_to_canonical: dict[str, str] = _build_reverse_alias_lookup(_dynamic_aliases or None)

    # First pass: build ID remap table and collect canonical nodes
    id_remap: dict[str, str] = {}  # old_id → canonical_id
    seen_canonical_title: dict[str, str] = {}  # canonical_title → first_seen_id
    deduped: list[dict[str, Any]] = []

    for node in nodes:
        title: str = node["title"]
        canonical_title = alias_to_canonical.get(title.lower(), title)
        canonical_id = canonical_title.lower().replace(" ", "_").replace("/", "_")

        original_id: str = node["id"]

        if canonical_id in seen_canonical_title:
            # This node is a duplicate — remap its ID to the first-seen canonical node
            id_remap[original_id] = seen_canonical_title[canonical_id]
        else:
            seen_canonical_title[canonical_id] = original_id
            id_remap[original_id] = original_id
            # Store node with canonical title (preserve original ID for DB compatibility)
            deduped.append({**node, "title": canonical_title})

    # Second pass: remap all edge endpoints
    remapped_edges: list[dict[str, Any]] = []
    for edge in edges:
        new_src = id_remap.get(edge["source_id"], edge["source_id"])
        new_tgt = id_remap.get(edge["target_id"], edge["target_id"])
        if new_src == new_tgt:
            continue  # Drop self-loops created by merging
        remapped_edges.append({**edge, "source_id": new_src, "target_id": new_tgt})

    merged_count = len(nodes) - len(deduped)
    if merged_count:
        logger.info("Entity dedup: merged %d duplicate nodes", merged_count)

    return deduped, remapped_edges
