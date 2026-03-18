# backend/app/services/external_data_feed.py
"""Live external data feed for Phase 4 universal prediction maturity.

Fetches real-time macro indicators from:
  1. FRED API — US Fed funds rate, USD/HKD exchange rate
  2. World Bank API — GDP growth for HK, US, China
  3. Taiwan Strait risk proxy — derived from RTHK/news keyword frequency in DB

Falls back gracefully to last known DB values when APIs are unavailable.
Results are returned as a flat dict[str, float] compatible with MacroState fields.

Usage::

    feed = ExternalDataFeed()
    data = await feed.fetch()
    # data = {"fed_rate": 0.045, "china_gdp_growth": 0.048, "taiwan_strait_risk": 0.30, ...}
"""
from __future__ import annotations

import os
from typing import Any

from backend.app.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# FRED series → MacroState field mapping
# ---------------------------------------------------------------------------
_FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
_FRED_SERIES: list[tuple[str, str, float]] = [
    # (series_id, macro_field, scale_factor)
    ("FEDFUNDS", "fed_rate", 0.01),   # % → decimal
    ("DEXHKUS",  "usd_hkd", 1.0),
]

# ---------------------------------------------------------------------------
# World Bank API indicators → MacroState field mapping
# ---------------------------------------------------------------------------
_WB_BASE = "https://api.worldbank.org/v2/country/{country}/indicator/{indicator}"
_WB_SERIES: list[tuple[str, str, str, float]] = [
    # (country_code, indicator_id, macro_field, scale_factor)
    ("HKG", "NY.GDP.MKTP.KD.ZG", "gdp_growth", 0.01),         # HK GDP growth %
    ("CHN", "NY.GDP.MKTP.KD.ZG", "china_gdp_growth", 0.01),   # China GDP growth %
    ("USA", "NY.GDP.MKTP.KD.ZG", "us_gdp_growth", 0.01),       # US GDP growth %
]

# Cache TTL: re-fetch at most once every 6 hours to avoid hammering APIs
_CACHE_TTL_SECONDS = 6 * 3600

# ---------------------------------------------------------------------------
# Taiwan Strait risk proxy thresholds (keyword frequency in news headlines)
# ---------------------------------------------------------------------------
_TAIWAN_KEYWORDS = ("Taiwan Strait", "台海", "軍演", "解放軍", "軍事衝突", "航母")
_TAIWAN_RISK_BASE = 0.20
_TAIWAN_RISK_HIGH = 0.65


class ExternalDataFeed:
    """Fetch live external macro data from FRED + World Bank + local news proxy."""

    def __init__(self) -> None:
        self._cache: dict[str, float] = {}
        self._cache_ts: float = 0.0

    async def fetch(self, force_refresh: bool = False) -> dict[str, float]:
        """Return live macro indicators as a flat dict.

        Args:
            force_refresh: Bypass cache and re-fetch from APIs.

        Returns:
            Dict of field_name → value.  Only includes fields successfully
            fetched; callers should fall back to DB/defaults for missing keys.
        """
        import time  # noqa: PLC0415
        now = time.monotonic()
        if not force_refresh and self._cache and (now - self._cache_ts) < _CACHE_TTL_SECONDS:
            return dict(self._cache)

        result: dict[str, float] = {}

        # Fetch concurrently where possible
        import asyncio  # noqa: PLC0415
        fred_data, wb_data, taiwan_risk = await asyncio.gather(
            self._fetch_fred(),
            self._fetch_world_bank(),
            self._fetch_taiwan_risk_proxy(),
            return_exceptions=True,
        )

        if isinstance(fred_data, dict):
            result.update(fred_data)
        else:
            logger.debug("ExternalDataFeed: FRED fetch failed: %s", fred_data)

        if isinstance(wb_data, dict):
            result.update(wb_data)
        else:
            logger.debug("ExternalDataFeed: World Bank fetch failed: %s", wb_data)

        if isinstance(taiwan_risk, float):
            result["taiwan_strait_risk"] = taiwan_risk
        else:
            logger.debug("ExternalDataFeed: Taiwan risk proxy failed: %s", taiwan_risk)

        self._cache = dict(result)
        self._cache_ts = now

        logger.info(
            "ExternalDataFeed: fetched %d live indicators: %s",
            len(result), sorted(result.keys()),
        )
        return result

    async def fetch_with_db_fallback(self) -> dict[str, float]:
        """Fetch live data, filling missing fields from hk_data_snapshots.

        Returns a combined dict merging live API data over DB snapshot values.
        """
        live = await self.fetch()
        db_values = await self._load_db_fallback()
        # DB fills gaps; live overrides DB
        return {**db_values, **live}

    # ------------------------------------------------------------------
    # Private: FRED
    # ------------------------------------------------------------------

    async def _fetch_fred(self) -> dict[str, float]:
        api_key = os.getenv("FRED_API_KEY", "")
        if not api_key:
            logger.debug("ExternalDataFeed: FRED_API_KEY not set — skipping FRED fetch")
            return {}

        import httpx  # noqa: PLC0415
        result: dict[str, float] = {}
        async with httpx.AsyncClient(timeout=10.0) as client:
            for series_id, field, scale in _FRED_SERIES:
                try:
                    resp = await client.get(
                        _FRED_BASE,
                        params={
                            "series_id": series_id,
                            "api_key": api_key,
                            "file_type": "json",
                            "sort_order": "desc",
                            "limit": "1",
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    observations = data.get("observations", [])
                    if observations:
                        raw_val = observations[0].get("value", ".")
                        if raw_val != ".":
                            result[field] = float(raw_val) * scale
                except Exception as exc:
                    logger.debug("FRED fetch failed series=%s: %s", series_id, exc)
        return result

    # ------------------------------------------------------------------
    # Private: World Bank
    # ------------------------------------------------------------------

    async def _fetch_world_bank(self) -> dict[str, float]:
        import httpx  # noqa: PLC0415
        result: dict[str, float] = {}
        async with httpx.AsyncClient(timeout=15.0) as client:
            for country, indicator, field, scale in _WB_SERIES:
                url = _WB_BASE.format(country=country, indicator=indicator)
                try:
                    resp = await client.get(
                        url,
                        params={"format": "json", "per_page": "3", "mrv": "1"},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    if isinstance(data, list) and len(data) > 1:
                        records = data[1] or []
                        for rec in records:
                            val = rec.get("value")
                            if val is not None:
                                result[field] = float(val) * scale
                                break
                except Exception as exc:
                    logger.debug("WB fetch failed country=%s ind=%s: %s", country, indicator, exc)
        return result

    # ------------------------------------------------------------------
    # Private: Taiwan Strait risk proxy (keyword count in news_headlines DB)
    # ------------------------------------------------------------------

    async def _fetch_taiwan_risk_proxy(self) -> float:
        """Estimate Taiwan Strait risk from recent news_headlines keyword frequency.

        Returns a float in [0, 1].  Falls back to _TAIWAN_RISK_BASE if DB read fails.
        """
        from backend.app.utils.db import get_db  # noqa: PLC0415

        try:
            async with get_db() as db:
                cursor = await db.execute(
                    """
                    SELECT headline FROM news_headlines
                    ORDER BY created_at DESC LIMIT 200
                    """
                )
                rows = await cursor.fetchall()
        except Exception:
            return _TAIWAN_RISK_BASE

        if not rows:
            return _TAIWAN_RISK_BASE

        total = len(rows)
        hit_count = 0
        for row in rows:
            text = (row[0] if isinstance(row, (list, tuple)) else row["headline"]) or ""
            if any(kw.lower() in text.lower() for kw in _TAIWAN_KEYWORDS):
                hit_count += 1

        frequency = hit_count / total
        # Map frequency [0, 0.1+] → risk [0.2, 0.65]
        risk = _TAIWAN_RISK_BASE + frequency * (_TAIWAN_RISK_HIGH - _TAIWAN_RISK_BASE) * 10.0
        return round(min(_TAIWAN_RISK_HIGH, risk), 3)

    # ------------------------------------------------------------------
    # Private: DB fallback
    # ------------------------------------------------------------------

    @staticmethod
    async def _load_db_fallback() -> dict[str, float]:
        """Load the latest hk_data_snapshots values for external fields."""
        from backend.app.utils.db import get_db  # noqa: PLC0415

        _EXTERNAL_DB: list[tuple[str, str, str]] = [
            ("external", "fed_rate", "fed_rate"),
            ("external", "usd_hkd", "usd_hkd"),
            ("external", "china_gdp_growth", "china_gdp_growth"),
            ("external", "taiwan_strait_risk", "taiwan_strait_risk"),
            ("external", "us_china_trade_tension", "us_china_trade_tension"),
        ]
        result: dict[str, float] = {}
        try:
            async with get_db() as db:
                for category, metric, field in _EXTERNAL_DB:
                    cursor = await db.execute(
                        """
                        SELECT value FROM hk_data_snapshots
                        WHERE category=? AND metric=?
                        ORDER BY period DESC, created_at DESC LIMIT 1
                        """,
                        (category, metric),
                    )
                    row = await cursor.fetchone()
                    if row:
                        val = row[0] if isinstance(row, (list, tuple)) else row["value"]
                        if val is not None:
                            result[field] = float(val)
        except Exception:
            logger.debug("ExternalDataFeed: DB fallback read failed")
        return result
