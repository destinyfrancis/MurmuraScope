"""Polymarket prediction market client.

Fetches active contracts from the Gamma API (public, no auth required).
Caches results for 10 minutes to respect rate limits.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from backend.app.utils.logger import get_logger

logger = get_logger("polymarket_client")

_GAMMA_API_BASE = "https://gamma-api.polymarket.com"
_CACHE_TTL_SECONDS = 600  # 10 minutes


@dataclass(frozen=True)
class PolymarketContract:
    """Immutable representation of a Polymarket prediction contract."""
    id: str
    question: str
    description: str
    outcomes: tuple[str, ...]
    outcome_prices: tuple[float, ...]
    volume: float
    liquidity: float
    slug: str
    category: str
    end_date: str
    closed: bool


# Module-level cache shared across all PolymarketClient instances.
# Each entry: (timestamp, value).  Avoids stale-on-every-request when
# callers instantiate a new client per API call.
_MODULE_CACHE: dict[str, tuple[float, Any]] = {}


class PolymarketClient:
    """Fetches and caches Polymarket contract data."""

    def __init__(self) -> None:
        self._cache = _MODULE_CACHE

    async def fetch_active_markets(
        self, category: str | None = None, limit: int = 50,
    ) -> list[PolymarketContract]:
        """Fetch active (non-closed) markets from Gamma API.

        Uses httpx for async HTTP. Falls back gracefully on network errors.
        """
        cache_key = f"markets:{category}:{limit}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        params: dict[str, Any] = {"closed": "false", "limit": limit, "active": "true"}
        if category:
            params["category"] = category

        try:
            import httpx
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(f"{_GAMMA_API_BASE}/markets", params=params)
                resp.raise_for_status()
                raw_markets = resp.json()
        except Exception:
            logger.exception("Failed to fetch Polymarket markets")
            return []

        contracts = [_parse_contract(m) for m in raw_markets if isinstance(m, dict)]
        contracts = [c for c in contracts if c is not None]
        self._set_cached(cache_key, contracts)
        return contracts

    async def fetch_market(self, slug: str) -> PolymarketContract | None:
        """Fetch a single market by slug."""
        cache_key = f"market:{slug}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            import httpx
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(f"{_GAMMA_API_BASE}/markets", params={"slug": slug})
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            logger.exception("Failed to fetch market slug=%s", slug)
            return None

        if isinstance(data, list) and data:
            contract = _parse_contract(data[0])
            if contract:
                self._set_cached(cache_key, contract)
            return contract
        return None

    async def search_markets(self, query: str, limit: int = 20) -> list[PolymarketContract]:
        """Search markets by keyword in question text."""
        # Gamma API doesn't have search — fetch all and filter locally
        all_markets = await self.fetch_active_markets(limit=200)
        query_lower = query.lower()
        matched = [
            c for c in all_markets
            if query_lower in c.question.lower() or query_lower in c.description.lower()
        ]
        return matched[:limit]

    def _get_cached(self, key: str) -> Any | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, value = entry
        if time.monotonic() - ts > _CACHE_TTL_SECONDS:
            del self._cache[key]
            return None
        return value

    def _set_cached(self, key: str, value: Any) -> None:
        self._cache[key] = (time.monotonic(), value)


def _parse_contract(raw: dict[str, Any]) -> PolymarketContract | None:
    """Parse a raw Gamma API market dict into a PolymarketContract."""
    try:
        outcomes_raw = raw.get("outcomes", "")
        if isinstance(outcomes_raw, str):
            import json
            try:
                outcomes_list = json.loads(outcomes_raw)
            except (json.JSONDecodeError, TypeError):
                outcomes_list = [o.strip() for o in outcomes_raw.split(",") if o.strip()]
        elif isinstance(outcomes_raw, list):
            outcomes_list = outcomes_raw
        else:
            outcomes_list = ["Yes", "No"]

        prices_raw = raw.get("outcomePrices", "")
        if isinstance(prices_raw, str):
            import json
            try:
                prices_list = [float(p) for p in json.loads(prices_raw)]
            except (json.JSONDecodeError, TypeError, ValueError):
                prices_list = [0.5, 0.5]
        elif isinstance(prices_raw, list):
            prices_list = [float(p) for p in prices_raw]
        else:
            prices_list = [0.5, 0.5]

        return PolymarketContract(
            id=str(raw.get("id", "")),
            question=raw.get("question", ""),
            description=raw.get("description", "")[:500],
            outcomes=tuple(outcomes_list),
            outcome_prices=tuple(prices_list),
            volume=float(raw.get("volume", 0) or 0),
            liquidity=float(raw.get("liquidity", 0) or 0),
            slug=raw.get("slug", ""),
            category=raw.get("category", ""),
            end_date=raw.get("endDate", ""),
            closed=bool(raw.get("closed", False)),
        )
    except Exception:
        logger.debug("Failed to parse contract: %s", raw.get("id", "unknown"))
        return None
