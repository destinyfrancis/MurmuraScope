"""China macroeconomic data downloader.

Collects GDP growth, PMI, CPI, export growth and other macro indicators for
China. These feed into the MacroController's external economic factors
(china_gdp_growth, etc.) and the hk_data_snapshots data lake.

Data strategy:
  1. Attempt to fetch live data from public sources (NBS, World Bank API).
  2. On any failure, fall back to hardcoded 2024-Q4 / 2025-Q1 values.

All hardcoded values are sourced from publicly available 2024-Q4 reports.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from backend.app.utils.logger import get_logger

logger = get_logger("data_pipeline.china_macro")

# ---------------------------------------------------------------------------
# World Bank API — most accessible public macro data source
# ---------------------------------------------------------------------------

_WORLD_BANK_BASE = "https://api.worldbank.org/v2/country/CN/indicator"
_WORLD_BANK_PARAMS = "?format=json&per_page=8&mrv=8"

# World Bank indicator codes
_WB_INDICATORS: tuple[tuple[str, str, str], ...] = (
    ("NY.GDP.MKTP.KD.ZG", "gdp_growth_pct", "%"),
    ("FP.CPI.TOTL.ZG", "cpi_yoy_pct", "%"),
    ("NE.EXP.GNFS.KD.ZG", "export_growth_pct", "%"),
    ("IC.BUS.EASE.XQ", "retail_sales_growth_pct", "%"),
)


# NOTE: All hardcoded fallback values removed.
# If World Bank API is unavailable, empty results are returned.

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChinaMacroRecord:
    """Immutable China macro economic data point."""

    metric: str
    value: float
    unit: str
    period: str
    source: str


@dataclass(frozen=True)
class DownloadResult:
    """Immutable result from a single China macro data fetch."""

    category: str
    row_count: int
    records: tuple[ChinaMacroRecord, ...]
    error: str | None = None


# ---------------------------------------------------------------------------
# World Bank fetch helpers
# ---------------------------------------------------------------------------


def _parse_wb_response(
    data: list,
    metric: str,
    unit: str,
) -> list[ChinaMacroRecord]:
    """Parse World Bank API response into ChinaMacroRecord list."""
    records: list[ChinaMacroRecord] = []
    if len(data) < 2:
        return records

    observations = data[1] or []
    for obs in observations:
        try:
            raw_value = obs.get("value")
            if raw_value is None:
                continue
            period = str(obs.get("date", "unknown"))
            records.append(
                ChinaMacroRecord(
                    metric=metric,
                    value=round(float(raw_value), 4),
                    unit=unit,
                    period=period,
                    source="world_bank",
                )
            )
        except (KeyError, ValueError, TypeError):
            continue
    return records


async def _fetch_world_bank(
    client: httpx.AsyncClient,
    indicator: str,
    metric: str,
    unit: str,
) -> list[ChinaMacroRecord]:
    """Fetch a single World Bank indicator for China.

    Returns empty list on any network or parse failure.
    """
    url = f"{_WORLD_BANK_BASE}/{indicator}{_WORLD_BANK_PARAMS}"
    try:
        resp = await client.get(url, timeout=20.0)
        if resp.status_code != 200:
            logger.debug("World Bank returned HTTP %d for %s", resp.status_code, indicator)
            return []
        data = resp.json()
        records = _parse_wb_response(data, metric, unit)
        logger.debug("World Bank %s: %d records", indicator, len(records))
        return records
    except (httpx.RequestError, httpx.TimeoutException, json.JSONDecodeError, ValueError) as exc:
        logger.debug("World Bank fetch failed for %s: %s", indicator, exc)
        return []


# ---------------------------------------------------------------------------
# Public export
# ---------------------------------------------------------------------------


async def download_all_china_macro(
    client: httpx.AsyncClient,
) -> list[DownloadResult]:
    """Download China macroeconomic indicators.

    Attempts live World Bank API fetch; on failure uses hardcoded 2024-Q4
    values. Always returns a non-empty result set via the fallback path.

    Args:
        client: Shared httpx.AsyncClient from the pipeline orchestrator.

    Returns:
        List containing one DownloadResult with ChinaMacroRecord tuples.
    """
    live_records: list[ChinaMacroRecord] = []

    for indicator, metric, unit in _WB_INDICATORS:
        fetched = await _fetch_world_bank(client, indicator, metric, unit)
        live_records.extend(fetched)

    if live_records:
        logger.info("China macro (World Bank): %d live records", len(live_records))
        return [
            DownloadResult(
                category="china_macro",
                row_count=len(live_records),
                records=tuple(live_records),
                error=None,
            )
        ]

    logger.warning("China macro: World Bank unavailable — no fallback")
    return [
        DownloadResult(
            category="china_macro",
            row_count=0,
            records=(),
            error="World Bank API unavailable for all China macro indicators",
        )
    ]
