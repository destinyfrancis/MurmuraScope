"""Hong Kong public transport statistics downloader.

Fetches transport data from data.gov.hk CKAN API.
No hardcoded fallback — returns empty results if API unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from backend.app.utils.logger import get_logger

logger = get_logger("data_pipeline.transport")

_CKAN_SEARCH = "https://data.gov.hk/en/api/3/action/datastore_search"

# Known data.gov.hk resource IDs for transport datasets
_MTR_RESOURCE_ID = "4be0eca4-858e-4ef0-8c7b-0c8e8f6c0f79"
_CROSS_BOUNDARY_RESOURCE_ID = "f3e18e2f-7f45-4f0c-9a3f-31b4c2c7b6d2"


@dataclass(frozen=True)
class TransportRecord:
    """Immutable transport data record."""

    date: str
    category: str
    metric: str
    value: float
    unit: str
    source: str = "datagov_hk"


@dataclass(frozen=True)
class TransportDownloadResult:
    """Immutable result of a transport download run."""

    records: tuple[TransportRecord, ...]
    row_count: int
    error: str | None


async def _fetch_ckan_resource(
    client: httpx.AsyncClient,
    resource_id: str,
    limit: int = 500,
) -> list[dict]:
    """Fetch records from a data.gov.hk CKAN resource."""
    try:
        params = {"resource_id": resource_id, "limit": str(limit)}
        resp = await client.get(_CKAN_SEARCH, params=params, timeout=20.0)
        if resp.status_code != 200:
            logger.debug("CKAN transport returned HTTP %d for %s", resp.status_code, resource_id)
            return []
        data = resp.json()
        if not data.get("success"):
            return []
        return data.get("result", {}).get("records", [])
    except Exception as exc:
        logger.debug("CKAN transport fetch failed for %s: %s", resource_id, exc)
        return []


def _parse_transport_records(raw_rows: list[dict], metric_name: str, unit: str) -> list[TransportRecord]:
    """Parse CKAN transport rows into TransportRecord list."""
    records: list[TransportRecord] = []
    for row in raw_rows:
        period = str(row.get("date", row.get("month", row.get("period", ""))))
        if not period:
            continue
        # Try common value column names
        for val_key in ("value", "total", "passengers", "journeys", "count"):
            val = row.get(val_key)
            if val is not None:
                try:
                    records.append(
                        TransportRecord(
                            date=period,
                            category="transport",
                            metric=metric_name,
                            value=round(float(val), 2),
                            unit=unit,
                        )
                    )
                except (ValueError, TypeError):
                    pass
                break
    return records


async def download_all_transport(
    client: httpx.AsyncClient,
) -> list[TransportDownloadResult]:
    """Download HK transport usage statistics from data.gov.hk.

    No hardcoded fallback — returns empty result if API unavailable.

    Returns:
        List of TransportDownloadResult.
    """
    all_records: list[TransportRecord] = []
    errors: list[str] = []

    # MTR passenger journeys
    mtr_rows = await _fetch_ckan_resource(client, _MTR_RESOURCE_ID)
    if mtr_rows:
        parsed = _parse_transport_records(mtr_rows, "mtr_passenger_journeys_millions", "millions")
        all_records.extend(parsed)
        logger.info("MTR data: %d records", len(parsed))
    else:
        errors.append("MTR CKAN unavailable")

    # Cross-boundary passengers
    cb_rows = await _fetch_ckan_resource(client, _CROSS_BOUNDARY_RESOURCE_ID)
    if cb_rows:
        parsed = _parse_transport_records(cb_rows, "cross_boundary_passengers_millions", "millions")
        all_records.extend(parsed)
        logger.info("Cross-boundary data: %d records", len(parsed))
    else:
        errors.append("Cross-boundary CKAN unavailable")

    if not all_records:
        error_msg = "; ".join(errors) if errors else "Transport CKAN APIs unavailable"
        logger.warning("Transport: no data — no fallback. %s", error_msg)
        return [TransportDownloadResult(records=(), row_count=0, error=error_msg)]

    logger.info("Transport data: %d total records", len(all_records))
    return [
        TransportDownloadResult(
            records=tuple(all_records),
            row_count=len(all_records),
            error=None,
        )
    ]
