"""Download HK property market data.

Sources (updated 2026-03):
- World Bank API: house price index proxy (CPI, FDI) — replaces CKAN (404)
- RVD Excel: rvd_downloader.py now handles direct XLS downloads from rvd.gov.hk
  (this module's CKAN-based RVD download is replaced by World Bank fallback)

Raw files saved to data/raw/property/.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import httpx

from backend.app.utils.logger import get_logger

logger = get_logger("data_pipeline.property")

_WB_BASE = "https://api.worldbank.org/v2/country/HKG/indicator"

# World Bank property/housing proxies for HK (CKAN data.gov.hk is permanently 404)
_WB_INDICATORS: dict[str, tuple[str, str, str]] = {
    # key: (indicator_id, metric_name, unit)
    "price_inflation": ("FP.CPI.TOTL.ZG", "property_price_inflation", "percent"),
    "fdi_pct_gdp": ("BX.KLT.DINV.WD.GD.ZS", "fdi_pct_gdp", "percent"),
    "gdp_per_capita": ("NY.GDP.PCAP.CD", "gdp_per_capita_usd", "usd"),
}

RAW_DIR = Path("data/raw/property")


@dataclass(frozen=True)
class PropertyRecord:
    """Immutable record for a single property market data point."""

    category: str
    metric: str
    value: float
    unit: str
    period: str
    source: str
    source_url: str


@dataclass(frozen=True)
class PropertyResult:
    """Immutable result of a property download operation."""

    source_name: str
    records: tuple[PropertyRecord, ...]
    raw_file_path: str
    row_count: int


async def _download_wb_property(
    client: httpx.AsyncClient,
    indicator_key: str,
) -> PropertyResult:
    """Download a World Bank indicator as property market proxy for HK."""
    spec = _WB_INDICATORS.get(indicator_key)
    if not spec:
        return PropertyResult(source_name=indicator_key, records=(), raw_file_path="", row_count=0)

    indicator_id, metric, unit = spec
    url = f"{_WB_BASE}/{indicator_id}"
    try:
        resp = await client.get(
            url,
            params={"format": "json", "per_page": 60, "mrv": 60},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list) or len(data) < 2 or not data[1]:
            logger.warning("World Bank %s: no data for HK", indicator_id)
            return PropertyResult(source_name=indicator_key, records=(), raw_file_path="", row_count=0)
        raw_records = data[1]
    except Exception:
        logger.warning("World Bank fetch failed for %s", indicator_id, exc_info=True)
        return PropertyResult(source_name=indicator_key, records=(), raw_file_path="", row_count=0)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_DIR / f"wb_{indicator_key}.json"
    raw_path.write_text(json.dumps(raw_records, indent=2, ensure_ascii=False), encoding="utf-8")

    records: list[PropertyRecord] = []
    for entry in raw_records:
        year = str(entry.get("date", "")).strip()
        raw_val = entry.get("value")
        if not year or raw_val is None:
            continue
        try:
            val = round(float(raw_val), 4)
        except (TypeError, ValueError):
            continue
        records.append(
            PropertyRecord(
                category="property",
                metric=metric,
                value=val,
                unit=unit,
                period=f"{year}-Q4",
                source="World Bank",
                source_url=url,
            )
        )

    logger.info("World Bank %s (%s): %d records", indicator_key, indicator_id, len(records))
    return PropertyResult(
        source_name=indicator_key,
        records=tuple(records),
        raw_file_path=str(raw_path),
        row_count=len(records),
    )


async def download_price_index(client: httpx.AsyncClient | None = None) -> PropertyResult:
    """Download HK property price inflation proxy from World Bank (CKAN is 404)."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()
    try:
        return await _download_wb_property(client, "price_inflation")
    finally:
        if own_client:
            await client.aclose()


async def download_rental_index(client: httpx.AsyncClient | None = None) -> PropertyResult:
    """Download HK FDI % of GDP from World Bank as rental market proxy."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()
    try:
        return await _download_wb_property(client, "fdi_pct_gdp")
    finally:
        if own_client:
            await client.aclose()


async def download_transactions(client: httpx.AsyncClient | None = None) -> PropertyResult:
    """Download HK GDP per capita from World Bank as transaction volume proxy."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()
    try:
        return await _download_wb_property(client, "gdp_per_capita")
    finally:
        if own_client:
            await client.aclose()


async def download_all_property(client: httpx.AsyncClient | None = None) -> list[PropertyResult]:
    """Download all property proxy datasets from World Bank.

    Note: Direct RVD XLS download is handled by rvd_downloader.py.
    This module now provides World Bank economic proxies for property market signals.
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()

    try:
        results: list[PropertyResult] = []
        downloaders = [
            download_price_index,
            download_rental_index,
            download_transactions,
        ]

        for downloader in downloaders:
            try:
                result = await downloader(client)
                results.append(result)
            except Exception:
                logger.exception("Failed in property downloader: %s", downloader.__name__)

        logger.info(
            "Property download complete: %d/%d datasets succeeded",
            len(results),
            len(downloaders),
        )
        return results
    finally:
        if own_client:
            await client.aclose()
