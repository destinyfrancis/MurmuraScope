"""Download HK population data.

Updated 2026-03: data.gov.hk CKAN API is permanently unavailable (HTTP 404).
Now uses World Bank API for total population and age distribution proxies:
- SP.POP.TOTL  — total population
- SP.POP.65UP.TO.ZS — population 65+ (% of total)
- SP.POP.0014.TO.ZS — population 0-14 (% of total)

Raw JSON files saved to data/raw/census/.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from backend.app.utils.logger import get_logger

logger = get_logger("data_pipeline.census")

_WB_BASE = "https://api.worldbank.org/v2/country/HKG/indicator"

# World Bank population indicators
_WB_POP_INDICATORS: dict[str, tuple[str, str]] = {
    "total":    ("SP.POP.TOTL",        "population_total"),
    "elderly":  ("SP.POP.65UP.TO.ZS",  "population_pct_65plus"),
    "youth":    ("SP.POP.0014.TO.ZS",  "population_pct_0to14"),
}

RAW_DIR = Path("data/raw/census")


@dataclass(frozen=True)
class CensusRecord:
    """Immutable record for a single census data point."""

    dataset_id: str
    metric: str
    dimension_1: str
    dimension_2: str | None
    dimension_3: str | None
    value: float
    period: str
    source_url: str
    source: str = "World Bank"      # normalizer requires this field
    category: str = "population"    # normalizer requires non-empty category


@dataclass(frozen=True)
class CensusResult:
    """Immutable result of a census download operation."""

    dataset_id: str
    records: tuple[CensusRecord, ...]
    raw_file_path: str
    row_count: int


async def _fetch_wb_population(
    client: httpx.AsyncClient,
    indicator_key: str,
) -> CensusResult:
    """Download a World Bank population indicator for HK."""
    spec = _WB_POP_INDICATORS.get(indicator_key)
    if not spec:
        return CensusResult(dataset_id=indicator_key, records=(), raw_file_path="", row_count=0)

    indicator_id, metric = spec
    url = f"{_WB_BASE}/{indicator_id}"
    dataset_id = f"wb_{indicator_key}"

    try:
        resp = await client.get(
            url, params={"format": "json", "per_page": 60, "mrv": 60}, timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list) or len(data) < 2 or not data[1]:
            logger.warning("World Bank %s: no data for HK", indicator_id)
            return CensusResult(dataset_id=dataset_id, records=(), raw_file_path="", row_count=0)
        raw_records = data[1]
    except Exception:
        logger.warning("World Bank fetch failed for census %s", indicator_id, exc_info=True)
        return CensusResult(dataset_id=dataset_id, records=(), raw_file_path="", row_count=0)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_DIR / f"wb_{indicator_key}.json"
    raw_path.write_text(json.dumps(raw_records, indent=2, ensure_ascii=False), encoding="utf-8")

    records: list[CensusRecord] = []
    for entry in raw_records:
        year = str(entry.get("date", "")).strip()
        raw_val = entry.get("value")
        if not year or raw_val is None:
            continue
        try:
            val = round(float(raw_val), 4)
        except (TypeError, ValueError):
            continue
        records.append(CensusRecord(
            dataset_id=dataset_id,
            metric=metric,
            dimension_1="total",
            dimension_2=None,
            dimension_3=None,
            value=val,
            period=f"{year}-Q4",
            source_url=url,
        ))

    logger.info("Census WB %s: %d records", indicator_key, len(records))
    return CensusResult(
        dataset_id=dataset_id,
        records=tuple(records),
        raw_file_path=str(raw_path),
        row_count=len(records),
    )


async def download_population_age_sex(client: httpx.AsyncClient | None = None) -> CensusResult:
    """Download HK total population from World Bank (replaces CKAN which is 404)."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()
    try:
        return await _fetch_wb_population(client, "total")
    finally:
        if own_client:
            await client.aclose()


async def download_population_single_age(client: httpx.AsyncClient | None = None) -> CensusResult:
    """Download HK population age distribution proxies from World Bank."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()
    try:
        # Fetch elderly and youth percentages, combine into one result
        r_elderly = await _fetch_wb_population(client, "elderly")
        r_youth = await _fetch_wb_population(client, "youth")
        combined = list(r_elderly.records) + list(r_youth.records)
        return CensusResult(
            dataset_id="wb_age_distribution",
            records=tuple(combined),
            raw_file_path=r_elderly.raw_file_path,
            row_count=len(combined),
        )
    finally:
        if own_client:
            await client.aclose()


async def download_all_census(client: httpx.AsyncClient | None = None) -> list[CensusResult]:
    """Download all census datasets from World Bank and return parsed results."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()

    try:
        results = [
            await download_population_age_sex(client),
            await download_population_single_age(client),
        ]
        logger.info("Census download complete: %d datasets", len(results))
        return results
    finally:
        if own_client:
            await client.aclose()
