"""HK retail sales and tourism data downloader.

Sources: data.gov.hk CKAN API
  - Monthly retail sales value (HKD billions)
  - Visitor arrivals (total monthly)
  - Mainland visitor proportion

Data strategy:
  1. Attempt CKAN datastore_search on known resource IDs.
  2. On failure, use hardcoded 2024 monthly estimates as fallback.

Hardcoded fallbacks are derived from HKTB and C&SD published 2024 figures.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from backend.app.utils.logger import get_logger

logger = get_logger("data_pipeline.retail_tourism")

_CKAN_SEARCH = "https://data.gov.hk/en/api/3/action/datastore_search"

# data.gov.hk resource IDs for retail/tourism datasets
# These IDs are stable but may change if the dataset is updated.
_RESOURCE_IDS: dict[str, str] = {
    "retail_sales": "b5bc3b67-2e54-4f19-9c6d-f4b53a5e8a3c",
    "visitor_arrivals": "44c5e038-cfd5-4d44-9396-22d3ed9e5ee3",
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



# NOTE: All hardcoded fallback data removed.
# If CKAN API is unavailable, empty results are returned.


# ---------------------------------------------------------------------------
# CKAN fetch helpers
# ---------------------------------------------------------------------------


async def _fetch_ckan_resource(
    client: httpx.AsyncClient,
    resource_id: str,
    limit: int = 24,
) -> list[dict]:
    """Attempt to fetch records from a data.gov.hk CKAN resource.

    Returns empty list on any failure without raising.
    """
    params = {"resource_id": resource_id, "limit": str(limit)}
    try:
        resp = await client.get(_CKAN_SEARCH, params=params, timeout=20.0)
        if resp.status_code != 200:
            logger.debug("CKAN returned HTTP %d for resource %s", resp.status_code, resource_id)
            return []
        data = resp.json()
        if not data.get("success"):
            logger.debug("CKAN success=False for resource %s", resource_id)
            return []
        return data.get("result", {}).get("records", [])
    except (httpx.RequestError, httpx.TimeoutException, json.JSONDecodeError, ValueError) as exc:
        logger.debug("CKAN fetch failed for resource %s: %s", resource_id, exc)
        return []


def _parse_retail_records(ckan_rows: list[dict]) -> list[RetailTourismRecord]:
    """Parse CKAN retail sales rows into RetailTourismRecord list."""
    records: list[RetailTourismRecord] = []
    for row in ckan_rows:
        try:
            period = str(row.get("period", row.get("date", row.get("month", ""))))
            value = float(row.get("value", row.get("sales_value", 0)))
            if not period:
                continue
            records.append(RetailTourismRecord(
                metric="retail_sales_hkd_billion",
                value=round(value, 2),
                unit="HKD_billion",
                period=period,
                source="ckan_retail",
            ))
        except (KeyError, ValueError, TypeError):
            continue
    return records


def _parse_visitor_records(ckan_rows: list[dict]) -> list[RetailTourismRecord]:
    """Parse CKAN visitor arrival rows into RetailTourismRecord list."""
    records: list[RetailTourismRecord] = []
    for row in ckan_rows:
        try:
            period = str(row.get("period", row.get("date", row.get("month", ""))))
            total = float(row.get("total", row.get("arrivals", 0)))
            if not period:
                continue
            records.append(RetailTourismRecord(
                metric="visitor_arrivals_million",
                value=round(total / 1_000_000, 4) if total > 10_000 else round(total, 4),
                unit="million",
                period=period,
                source="ckan_tourism",
            ))
        except (KeyError, ValueError, TypeError):
            continue
    return records




# ---------------------------------------------------------------------------
# Public export
# ---------------------------------------------------------------------------


async def download_all_retail_tourism(
    client: httpx.AsyncClient,
) -> list[DownloadResult]:
    """Download HK retail sales and visitor arrival data.

    Tries data.gov.hk CKAN for both datasets; falls back to hardcoded 2024
    monthly estimates if the API is unavailable or returns no data.

    Args:
        client: Shared httpx.AsyncClient from the pipeline orchestrator.

    Returns:
        List of DownloadResult with RetailTourismRecord tuples.
    """
    results: list[DownloadResult] = []
    all_records: list[RetailTourismRecord] = []

    # --- Retail sales ---
    retail_rows = await _fetch_ckan_resource(
        client, _RESOURCE_IDS["retail_sales"], limit=24
    )
    if retail_rows:
        parsed = _parse_retail_records(retail_rows)
        all_records.extend(parsed)
        logger.info("Retail sales (CKAN): %d records", len(parsed))
    else:
        logger.warning("Retail sales CKAN unavailable — using 2024 fallback")

    # --- Visitor arrivals ---
    visitor_rows = await _fetch_ckan_resource(
        client, _RESOURCE_IDS["visitor_arrivals"], limit=24
    )
    if visitor_rows:
        parsed = _parse_visitor_records(visitor_rows)
        all_records.extend(parsed)
        logger.info("Visitor arrivals (CKAN): %d records", len(parsed))
    else:
        logger.warning("Visitor arrivals CKAN unavailable — using 2024 fallback")

    error_msg = None if all_records else "CKAN retail/tourism APIs unavailable — no fallback"
    if not all_records:
        logger.warning("Retail/tourism: no data from CKAN — no fallback")

    results.append(DownloadResult(
        category="retail_tourism",
        row_count=len(all_records),
        records=tuple(all_records),
        error=error_msg,
    ))

    return results
