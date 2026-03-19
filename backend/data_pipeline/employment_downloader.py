"""Download HK employment and wage statistics.

Sources (updated 2026-03):
- World Bank API for unemployment rate (SL.UEM.TOTL.ZS) and wages proxy
  — replaced former data.gov.hk CKAN downloader which is permanently 404.

Raw files saved to data/raw/employment/.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import httpx

from backend.app.utils.logger import get_logger

logger = get_logger("data_pipeline.employment")

_WB_BASE = "https://api.worldbank.org/v2/country/HKG/indicator"

# World Bank indicators for HK employment
_WB_INDICATORS: dict[str, str] = {
    "unemployment": "SL.UEM.TOTL.ZS",       # Unemployment rate (%)
    "wages_growth": "SL.EMP.VULN.ZS",        # Vulnerable employment (proxy; wages N/A on WB for HK)
    "labour_force": "SL.TLF.TOTL.IN",        # Labour force total
}

RAW_DIR = Path("data/raw/employment")


@dataclass(frozen=True)
class EmploymentRecord:
    """Immutable record for a single employment data point."""

    category: str
    metric: str
    value: float
    unit: str
    period: str
    source: str
    source_url: str


@dataclass(frozen=True)
class EmploymentResult:
    """Immutable result of an employment download operation."""

    source_name: str
    records: tuple[EmploymentRecord, ...]
    raw_file_path: str
    row_count: int


def _try_parse_float(val: str) -> float | None:
    """Try to parse a string as float."""
    cleaned = val.replace(",", "").replace(" ", "").strip()
    if not cleaned or cleaned in ("-", "N/A", "n.a.", "..", "N.A."):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


async def _download_wb_employment(
    client: httpx.AsyncClient,
    indicator_key: str,
    category: str,
    metric: str,
    unit: str,
) -> EmploymentResult:
    """Download a World Bank employment indicator for HK (annual → Q4 records)."""
    indicator_id = _WB_INDICATORS.get(indicator_key)
    if not indicator_id:
        logger.warning("No World Bank indicator for %s", indicator_key)
        return EmploymentResult(source_name=indicator_key, records=(), raw_file_path="", row_count=0)

    url = f"{_WB_BASE}/{indicator_id}"
    try:
        resp = await client.get(
            url, params={"format": "json", "per_page": 60, "mrv": 60}, timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list) or len(data) < 2 or not data[1]:
            logger.warning("World Bank %s: no data for HK", indicator_id)
            return EmploymentResult(source_name=indicator_key, records=(), raw_file_path="", row_count=0)
        raw_records = data[1]
    except Exception:
        logger.warning("World Bank fetch failed for %s", indicator_id, exc_info=True)
        return EmploymentResult(source_name=indicator_key, records=(), raw_file_path="", row_count=0)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_DIR / f"wb_{indicator_key}.json"
    raw_path.write_text(json.dumps(raw_records, indent=2, ensure_ascii=False), encoding="utf-8")

    records: list[EmploymentRecord] = []
    for entry in raw_records:
        year = str(entry.get("date", "")).strip()
        val = _try_parse_float(str(entry.get("value", "")))
        if not year or val is None:
            continue
        records.append(EmploymentRecord(
            category=category,
            metric=metric,
            value=round(val, 4),
            unit=unit,
            period=f"{year}-Q4",
            source="World Bank",
            source_url=url,
        ))

    logger.info("World Bank %s: %d records", indicator_key, len(records))
    return EmploymentResult(
        source_name=indicator_key,
        records=tuple(records),
        raw_file_path=str(raw_path),
        row_count=len(records),
    )


async def download_unemployment(client: httpx.AsyncClient | None = None) -> EmploymentResult:
    """Download HK unemployment rate from World Bank (replaces CKAN which is 404)."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()
    try:
        return await _download_wb_employment(
            client, "unemployment", "employment", "unemployment_rate", "percent",
        )
    finally:
        if own_client:
            await client.aclose()


async def download_wages(client: httpx.AsyncClient | None = None) -> EmploymentResult:
    """Download HK labour force size from World Bank as wages/employment proxy."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()
    try:
        return await _download_wb_employment(
            client, "labour_force", "wages", "labour_force_total", "persons",
        )
    finally:
        if own_client:
            await client.aclose()


async def download_employment_by_industry(client: httpx.AsyncClient | None = None) -> EmploymentResult:
    """Download HK vulnerable employment % from World Bank as industry proxy."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()
    try:
        return await _download_wb_employment(
            client, "wages_growth", "employment", "employment_industry_vulnerable_pct", "percent",
        )
    finally:
        if own_client:
            await client.aclose()


async def download_all_employment(client: httpx.AsyncClient | None = None) -> list[EmploymentResult]:
    """Download all employment datasets from World Bank and return parsed results."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()

    try:
        results: list[EmploymentResult] = []
        downloaders = [
            download_unemployment,
            download_wages,
            download_employment_by_industry,
        ]

        for downloader in downloaders:
            try:
                result = await downloader(client)
                results.append(result)
            except Exception:
                logger.exception("Failed in employment downloader: %s", downloader.__name__)

        logger.info(
            "Employment download complete: %d/%d datasets succeeded",
            len(results), len(downloaders),
        )
        return results
    finally:
        if own_client:
            await client.aclose()
