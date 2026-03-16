"""Zero-config quick-start service for HKSimEngine.

Enables paste-text-and-run: accepts seed text, infers domain,
and returns a ready-to-run simulation configuration.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.utils.logger import get_logger

logger = get_logger("zero_config")

# ---------------------------------------------------------------------------
# Domain inference keywords (static fallback)
# ---------------------------------------------------------------------------

_STATIC_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "hk_city": [
        "香港", "樓市", "property", "移民", "emigration", "生育", "fertility",
        "hk", "hong kong",
    ],
    "us_markets": [
        "美股", "wall street", "nasdaq", "s&p", "fed", "inflation",
        "dow jones", "treasury",
    ],
    "global_macro": [
        "global", "recession", "trade war", "油價", "commodity",
        "world economy", "geopolitical",
    ],
    "public_narrative": [
        "輿論", "narrative", "media", "民意", "protest",
        "public opinion", "social media",
    ],
    "real_estate": [
        "地產", "real estate", "mortgage", "樓價", "ccl",
        "rent", "housing",
    ],
    "company_competitor": [
        "公司", "company", "competitor", "market share", "營銷",
        "enterprise", "corporate",
    ],
    "community_movement": [
        "社區", "community", "movement", "組織",
        "grassroots", "activism",
    ],
}


def _build_domain_keywords() -> dict[str, list[str]]:
    """Build domain keywords dynamically from DomainPackRegistry.

    If a pack has a ``keywords`` field, those keywords are used.
    Falls back to ``_STATIC_DOMAIN_KEYWORDS`` for packs without keywords
    or when the registry is unavailable.
    """
    result = dict(_STATIC_DOMAIN_KEYWORDS)
    try:
        from backend.app.domain.base import DomainPackRegistry  # noqa: PLC0415

        for pack_id in DomainPackRegistry.list_packs():
            pack = DomainPackRegistry.get(pack_id)
            if pack.keywords:
                result[pack_id] = list(pack.keywords)
    except Exception:
        logger.debug("DomainPackRegistry unavailable — using static keywords")
    return result


# Backward compat alias
_DOMAIN_KEYWORDS = _STATIC_DOMAIN_KEYWORDS


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ZeroConfigResult:
    """Result of zero-config inference."""

    domain_pack_id: str
    agent_count: int
    round_count: int
    preset_name: str
    seed_text: str
    detected_entities: list[str]
    estimated_duration_seconds: int


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class ZeroConfigService:
    """Infer domain and configuration from seed text alone."""

    def infer_domain(self, seed_text: str) -> str:
        """Keyword-match seed text to a domain pack ID.

        Dynamically loads keywords from DomainPackRegistry when available,
        falling back to static keyword dict.
        Returns ``"hk_city"`` when nothing matches.
        """
        domain_keywords = _build_domain_keywords()
        text_lower = seed_text.lower()
        scores: dict[str, int] = {}
        for domain, keywords in domain_keywords.items():
            score = sum(1 for kw in keywords if kw.lower() in text_lower)
            if score > 0:
                scores[domain] = score
        if not scores:
            return "hk_city"
        return max(scores, key=scores.get)  # type: ignore[arg-type]

    async def prepare(self, seed_text: str) -> ZeroConfigResult:
        """Analyse seed text and return a zero-config result.

        Uses the existing *TextProcessor* for entity extraction when
        available; falls back gracefully otherwise.

        Raises:
            ValueError: If *seed_text* is empty or whitespace-only.
        """
        if not seed_text or not seed_text.strip():
            raise ValueError("seed_text must not be empty")

        domain = self.infer_domain(seed_text)

        # Try entity extraction via existing TextProcessor -----------------
        entities: list[str] = []
        try:
            from backend.app.services.text_processor import TextProcessor

            tp = TextProcessor()
            analysis = await tp.analyze_seed(seed_text)
            entities = (
                analysis.get("entities", [])
                if isinstance(analysis, dict)
                else []
            )
        except Exception:
            logger.debug("TextProcessor unavailable — skipping entity extraction")

        # PRESET_FAST defaults ---------------------------------------------
        agent_count = 100
        round_count = 10
        estimated_seconds = agent_count * round_count // 50  # rough heuristic

        logger.info(
            "ZeroConfig: domain=%s agents=%d rounds=%d entities=%d",
            domain,
            agent_count,
            round_count,
            len(entities),
        )

        return ZeroConfigResult(
            domain_pack_id=domain,
            agent_count=agent_count,
            round_count=round_count,
            preset_name="fast",
            seed_text=seed_text,
            detected_entities=entities[:10],
            estimated_duration_seconds=estimated_seconds,
        )
