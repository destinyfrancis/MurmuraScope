"""FRED (Federal Reserve Economic Data) downloader.

Fetches US macroeconomic series used as external factors in the HK simulation:
  - FEDFUNDS: Effective Federal Funds Rate
  - DEXHKUS:  HKD per USD spot exchange rate

Requires the FRED_API_KEY environment variable. If not set, the downloader
falls back to hardcoded 2024-Q4 values so the pipeline always succeeds.

FRED API reference:
  https://fred.stlouisfed.org/docs/api/fred/series_observations.html
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import httpx

from backend.app.utils.logger import get_logger

# Load .env from project root (no-op if dotenv not available or file missing)
try:
    from dotenv import load_dotenv as _load_dotenv

    _load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env", override=False)
except ImportError:
    pass

logger = get_logger("data_pipeline.fred")

_FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# Series to fetch: (series_id, description, unit)
_FRED_SERIES: tuple[tuple[str, str, str], ...] = (
    ("FEDFUNDS", "fed_funds_rate", "%"),
    ("DEXHKUS", "hkd_per_usd", "HKD"),
)


# NOTE: All hardcoded fallback values removed. If FRED API key is not
# configured or API returns no data, empty results are returned.


@dataclass(frozen=True)
class FredRecord:
    """Immutable FRED data observation."""

    series_id: str
    value: float
    date: str
    source: str


@dataclass(frozen=True)
class DownloadResult:
    """Immutable result from a FRED series download."""

    category: str
    row_count: int
    records: tuple[FredRecord, ...]
    error: str | None = None


def _parse_observations(series_id: str, data: dict) -> list[FredRecord]:
    """Parse FRED observations JSON into FredRecord list.

    Skips entries where value is '.' (FRED missing-data sentinel).
    """
    records: list[FredRecord] = []
    observations = data.get("observations", [])
    for obs in observations:
        raw_value = obs.get("value", ".")
        if raw_value == ".":
            continue
        try:
            records.append(
                FredRecord(
                    series_id=series_id,
                    value=round(float(raw_value), 6),
                    date=str(obs.get("date", "")),
                    source="fred",
                )
            )
        except (ValueError, TypeError):
            continue
    return records


async def _fetch_series(
    client: httpx.AsyncClient,
    series_id: str,
    api_key: str,
) -> list[FredRecord]:
    """Fetch up to 24 most-recent observations for one FRED series.

    Returns empty list on any network or API error.
    """
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": "500",
        "observation_start": "1990-01-01",
    }
    try:
        resp = await client.get(_FRED_BASE, params=params, timeout=20.0)
        if resp.status_code != 200:
            logger.debug("FRED API returned HTTP %d for %s", resp.status_code, series_id)
            return []
        data = resp.json()
        records = _parse_observations(series_id, data)
        logger.debug("FRED %s: %d observations", series_id, len(records))
        return records
    except (httpx.RequestError, httpx.TimeoutException, json.JSONDecodeError, ValueError) as exc:
        logger.debug("FRED fetch failed for %s: %s", series_id, exc)
        return []


async def download_series(
    series_ids: list[str],
    observation_start: str = "1990-01-01",
    limit: int = 500,
) -> list[FredRecord]:
    """Download an arbitrary list of FRED series by ID.

    Generic entry point for domain-pack DataSourceSpec dispatching.
    Uses FRED_API_KEY env var.  Returns empty list when key is absent.

    Args:
        series_ids: FRED series identifiers (e.g. ['FEDFUNDS', 'DEXHKUS']).
        observation_start: Earliest observation date (YYYY-MM-DD).
        limit: Max observations to retrieve per series (default 500).

    Returns:
        Flat list of FredRecord objects across all requested series.
    """
    api_key = os.environ.get("FRED_API_KEY", "").strip()
    if not api_key:
        logger.warning("FRED_API_KEY not configured — download_series returning empty")
        return []

    all_records: list[FredRecord] = []

    async with httpx.AsyncClient() as client:
        for series_id in series_ids:
            params = {
                "series_id": series_id,
                "api_key": api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": str(limit),
                "observation_start": observation_start,
            }
            try:
                resp = await client.get(_FRED_BASE, params=params, timeout=20.0)
                if resp.status_code != 200:
                    logger.warning(
                        "download_series: FRED HTTP %d for %s",
                        resp.status_code,
                        series_id,
                    )
                    continue
                records = _parse_observations(series_id, resp.json())
                all_records.extend(records)
                logger.info("download_series: %s — %d records", series_id, len(records))
            except (httpx.RequestError, httpx.TimeoutException, ValueError) as exc:
                logger.warning("download_series: failed for %s: %s", series_id, exc)

    return all_records


async def download_all_fred(
    client: httpx.AsyncClient,
) -> list[DownloadResult]:
    """Download FEDFUNDS and DEXHKUS from FRED.

    Uses FRED_API_KEY env var if set; otherwise falls back to hardcoded 2024-Q4
    values. Each series returns as a separate DownloadResult.

    Args:
        client: Shared httpx.AsyncClient from the pipeline orchestrator.

    Returns:
        List of DownloadResult, one per FRED series.
    """
    api_key = os.environ.get("FRED_API_KEY", "").strip()
    if not api_key:
        logger.warning("FRED_API_KEY not configured — returning empty results")
        return [
            DownloadResult(
                category="fred",
                row_count=0,
                records=(),
                error="FRED_API_KEY not configured",
            )
        ]

    results: list[DownloadResult] = []

    for series_id, description, unit in _FRED_SERIES:
        live_records = await _fetch_series(client, series_id, api_key)

        if live_records:
            results.append(
                DownloadResult(
                    category="fred",
                    row_count=len(live_records),
                    records=tuple(live_records),
                    error=None,
                )
            )
            logger.info("FRED %s: %d records fetched", series_id, len(live_records))
        else:
            results.append(
                DownloadResult(
                    category="fred",
                    row_count=0,
                    records=(),
                    error=f"FRED API returned no data for {series_id}",
                )
            )
            logger.warning("FRED %s: no data returned — no fallback", series_id)

    return results
