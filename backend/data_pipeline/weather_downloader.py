"""HKO (Hong Kong Observatory) weather data downloader.

Fetches climate data from data.gov.hk CKAN API.
No hardcoded fallback — returns empty results if API unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from backend.app.utils.logger import get_logger

logger = get_logger("data_pipeline.weather")

_HKO_CKAN_SEARCH = "https://data.gov.hk/en/api/3/action/datastore_search"

# Known data.gov.hk resource IDs for HKO climate data
_HKO_MONTHLY_RESOURCE = "da0fa9ef-13c4-4b4e-b6f7-e17cd12a5a03"


@dataclass(frozen=True)
class WeatherRecord:
    """Immutable weather data record."""

    date: str
    category: str
    metric: str
    value: float
    unit: str
    source: str = "hko"


@dataclass(frozen=True)
class WeatherDownloadResult:
    """Immutable result of a weather download run."""

    records: tuple[WeatherRecord, ...]
    row_count: int
    error: str | None


async def _fetch_hko_monthly(
    client: httpx.AsyncClient,
    resource_id: str,
    limit: int = 500,
) -> list[dict]:
    """Fetch HKO monthly climate data from CKAN datastore."""
    try:
        params = {"resource_id": resource_id, "limit": str(limit)}
        resp = await client.get(_HKO_CKAN_SEARCH, params=params, timeout=20.0)
        if resp.status_code != 200:
            logger.warning("HKO CKAN returned HTTP %d", resp.status_code)
            return []
        data = resp.json()
        if not data.get("success"):
            return []
        return data.get("result", {}).get("records", [])
    except Exception as exc:
        logger.warning("HKO CKAN fetch failed: %s", exc)
        return []


def _parse_hko_records(raw_rows: list[dict]) -> list[WeatherRecord]:
    """Parse HKO CKAN rows into WeatherRecord list."""
    records: list[WeatherRecord] = []
    for row in raw_rows:
        # HKO data columns vary; try common field names
        period = str(row.get("date", row.get("month", row.get("period", ""))))
        if not period:
            continue

        # Temperature
        for temp_key in ("mean_temp", "temperature", "mean_temperature"):
            val = row.get(temp_key)
            if val is not None:
                try:
                    records.append(WeatherRecord(
                        date=period,
                        category="weather",
                        metric="monthly_mean_temp_c",
                        value=round(float(val), 1),
                        unit="celsius",
                    ))
                except (ValueError, TypeError):
                    pass
                break

        # Rainfall
        for rain_key in ("rainfall", "total_rainfall", "precipitation"):
            val = row.get(rain_key)
            if val is not None:
                try:
                    records.append(WeatherRecord(
                        date=period,
                        category="weather",
                        metric="monthly_rainfall_mm",
                        value=round(float(val), 1),
                        unit="mm",
                    ))
                except (ValueError, TypeError):
                    pass
                break

    return records


async def download_all_weather(
    client: httpx.AsyncClient,
) -> list[WeatherDownloadResult]:
    """Download HKO climate statistics from data.gov.hk.

    No hardcoded fallback — returns empty result if API unavailable.

    Returns:
        List of WeatherDownloadResult.
    """
    raw_rows = await _fetch_hko_monthly(client, _HKO_MONTHLY_RESOURCE)

    if not raw_rows:
        logger.warning("Weather: no data from HKO CKAN — no fallback")
        return [WeatherDownloadResult(records=(), row_count=0, error="HKO CKAN API unavailable")]

    records = _parse_hko_records(raw_rows)

    if not records:
        logger.warning("Weather: HKO returned data but parsing yielded 0 records")
        return [WeatherDownloadResult(records=(), row_count=0, error="HKO data format unrecognised")]

    logger.info("Weather data: %d records from HKO CKAN", len(records))
    return [WeatherDownloadResult(
        records=tuple(records),
        row_count=len(records),
        error=None,
    )]
