"""HK retail sales and tourism data downloader.

Updated 2026-03: data.gov.hk CKAN API is permanently unavailable (HTTP 404).
Now uses World Bank API:
  - NE.CON.PRVT.KD.ZG — household consumption growth (retail proxy)
  - ST.INT.ARVL        — international tourism arrivals

Data strategy:
  1. Fetch from World Bank API.
  2. Return empty result on failure (no hardcoded fallback).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from backend.app.utils.logger import get_logger

logger = get_logger("data_pipeline.retail_tourism")

_WB_BASE = "https://api.worldbank.org/v2/country/HKG/indicator"

_WB_INDICATORS: dict[str, tuple[str, str, str]] = {
    # key: (indicator_id, metric_name, unit)
    "retail_sales": ("NE.CON.PRVT.KD.ZG", "retail_sales_growth_pct", "percent"),
    "visitor_arrivals": ("ST.INT.ARVL",     "visitor_arrivals_thousands", "thousands"),
}

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetailTourismRecord:
    """Immutable HK retail / tourism data point."""

    metric: str
    value: float
    unit: str
    period: str
    source: str


@dataclass(frozen=True)
class DownloadResult:
    """Immutable result from a retail / tourism download run."""

    category: str
    row_count: int
    records: tuple[RetailTourismRecord, ...]
    error: str | None = None


# ---------------------------------------------------------------------------
# World Bank fetch helper
# ---------------------------------------------------------------------------


async def _fetch_wb_indicator(
    client: httpx.AsyncClient,
    indicator_id: str,
    *,
    mrv: int = 30,
    timeout: float = 20.0,
) -> list[dict]:
    """Fetch annual HK records for a World Bank indicator.

    Returns the records list or [] on failure.
    """
    url = f"{_WB_BASE}/{indicator_id}"
    try:
        resp = await client.get(
            url, params={"format": "json", "per_page": mrv, "mrv": mrv}, timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and len(data) == 2:
            return data[1] or []
        return []
    except Exception as exc:
        logger.debug("World Bank fetch failed for %s: %s", indicator_id, exc)
        return []


# ---------------------------------------------------------------------------
# Public export
# ---------------------------------------------------------------------------


async def download_all_retail_tourism(
    client: httpx.AsyncClient,
) -> list[DownloadResult]:
    """Download HK retail sales and visitor arrival data from World Bank.

    Replaces former CKAN-based downloader (data.gov.hk CKAN is permanently 404).
    Uses World Bank annual indicators; reports as Q4 period labels.

    Args:
        client: Shared httpx.AsyncClient from the pipeline orchestrator.

    Returns:
        List of DownloadResult with RetailTourismRecord tuples.
    """
    all_records: list[RetailTourismRecord] = []

    for key, (indicator_id, metric, unit) in _WB_INDICATORS.items():
        rows = await _fetch_wb_indicator(client, indicator_id)
        for row in rows:
            year = str(row.get("date", "")).strip()
            raw_val = row.get("value")
            if not year or raw_val is None:
                continue
            try:
                val = round(float(raw_val), 4)
            except (TypeError, ValueError):
                continue
            # Visitor arrivals: convert to thousands
            if key == "visitor_arrivals" and val > 10_000:
                val = round(val / 1000.0, 2)
            all_records.append(RetailTourismRecord(
                metric=metric,
                value=val,
                unit=unit,
                period=f"{year}-Q4",
                source="World Bank",
            ))
        logger.info("Retail/tourism WB %s: %d records", key, sum(1 for r in all_records if r.metric == metric))

    error_msg = None if all_records else "World Bank retail/tourism APIs returned no data"
    return [DownloadResult(
        category="retail_tourism",
        row_count=len(all_records),
        records=tuple(all_records),
        error=error_msg,
    )]
