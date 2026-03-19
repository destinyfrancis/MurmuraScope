"""Download real historical economic data for HK from the World Bank API.

Replaces the former data.gov.hk CKAN-based downloader which became permanently
unavailable (all CKAN endpoints return HTTP 404).  The World Bank Data API is
free, requires no authentication, and covers all required indicators.

World Bank endpoint pattern:
  https://api.worldbank.org/v2/country/HKG/indicator/<ID>?format=json&per_page=100&mrv=60

Data strategy:
  1. Fetch from World Bank API with retry.
  2. Return empty + error if the API is unavailable.

Raw JSON saved to data/raw/censtatd/.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from backend.app.utils.logger import get_logger

logger = get_logger("data_pipeline.censtatd")

_WB_BASE = "https://api.worldbank.org/v2/country/HKG/indicator"
_RAW_DIR = Path("data/raw/censtatd")
_MAX_RETRIES = 3
_BACKOFF_BASE_S = 1.0

# World Bank indicator IDs for Hong Kong
_WB_INDICATORS: dict[str, str] = {
    "unemployment": "SL.UEM.TOTL.ZS",          # Unemployment rate (%)
    "cpi": "FP.CPI.TOTL",                       # CPI (2010 = 100)
    "gdp": "NY.GDP.MKTP.KD.ZG",                 # GDP growth (annual %)
    "gdp_current": "NY.GDP.MKTP.CD",            # GDP current USD
    "retail_sales": "NE.CON.PRVT.KD.ZG",        # Household consumption growth (proxy for retail)
    "visitor_arrivals": "ST.INT.ARVL",           # International tourism arrivals
    "population": "SP.POP.TOTL",                 # Total population
    "net_migration": "SM.POP.NETM",              # Net migration
}

_QUARTER_FOR_MONTH: dict[int, str] = {
    1: "Q1", 2: "Q1", 3: "Q1", 4: "Q2", 5: "Q2", 6: "Q2",
    7: "Q3", 8: "Q3", 9: "Q3", 10: "Q4", 11: "Q4", 12: "Q4",
}

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CenstatdRecord:
    """Immutable record for a single C&SD data point."""
    period: str       # "YYYY-QN" or "YYYY-MM"
    metric: str
    value: float
    unit: str
    source: str
    source_url: str


@dataclass(frozen=True)
class DownloadResult:
    """Immutable result of a censtatd download operation."""
    category: str
    row_count: int
    records: tuple[CenstatdRecord, ...]
    error: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_float(value: object) -> float | None:
    """Parse value to float, stripping commas. None on failure."""
    if value is None:
        return None
    cleaned = str(value).replace(",", "").replace(" ", "").strip()
    if not cleaned or cleaned in ("-", "N/A", "n.a.", "..", "N.A.", "...", "\u2014"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _year_to_q4(year: str) -> str:
    """Convert a year string to YYYY-Q4 period (World Bank reports annual data)."""
    return f"{year}-Q4"


def _save_raw(filename: str, data: Any) -> None:
    _RAW_DIR.mkdir(parents=True, exist_ok=True)
    (_RAW_DIR / filename).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


async def _fetch_wb_indicator(
    client: httpx.AsyncClient,
    indicator_id: str,
    *,
    per_page: int = 100,
    mrv: int = 60,
    timeout: float = 30.0,
) -> list[dict[str, Any]]:
    """Fetch annual HK data for a World Bank indicator.

    Returns the records list from the World Bank JSON response, or [] on failure.
    The World Bank API returns a two-element list: [metadata, records].
    """
    url = f"{_WB_BASE}/{indicator_id}"
    params: dict[str, Any] = {"format": "json", "per_page": per_page, "mrv": mrv}

    for attempt in range(_MAX_RETRIES):
        try:
            resp = await client.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list) and len(data) == 2:
                records = data[1] or []
                logger.info("World Bank %s: %d records", indicator_id, len(records))
                return records
            logger.warning("Unexpected World Bank response format for %s", indicator_id)
            return []
        except (httpx.HTTPStatusError, httpx.RequestError, httpx.TimeoutException) as exc:
            logger.debug("WB attempt %d failed for %s: %s", attempt + 1, indicator_id, exc)
        except (json.JSONDecodeError, ValueError):
            return []
        if attempt < _MAX_RETRIES - 1:
            await asyncio.sleep(_BACKOFF_BASE_S * (2 ** attempt))
    return []


def _parse_wb_records(
    raw_rows: list[dict[str, Any]],
    category: str,
    metric: str,
    unit: str,
    source_url: str,
    *,
    normalize_fn: Any = None,
) -> list[CenstatdRecord]:
    """Convert World Bank API rows into CenstatdRecord list.

    World Bank rows have structure: {date: "2024", value: 2.79, ...}
    We emit one Q4 record per year (annual data reported as year-end).
    """
    records: list[CenstatdRecord] = []
    for row in raw_rows:
        year = str(row.get("date", "")).strip()
        val = _safe_float(row.get("value"))
        if not year or val is None:
            continue
        period = _year_to_q4(year)
        if normalize_fn:
            val = normalize_fn(val)
        records.append(CenstatdRecord(
            period, metric, round(val, 4), unit, "World Bank", source_url,
        ))
    return records


async def _download_wb_simple(
    client: httpx.AsyncClient,
    indicator_key: str,
    category: str,
    metric: str,
    unit: str,
    *,
    normalize_fn: Any = None,
) -> DownloadResult:
    """Generic World Bank downloader for a single indicator."""
    indicator_id = _WB_INDICATORS.get(indicator_key)
    if not indicator_id:
        return DownloadResult(category=category, row_count=0, records=(),
                              error=f"No World Bank indicator ID for {indicator_key}")

    source_url = f"{_WB_BASE}/{indicator_id}"
    raw_rows = await _fetch_wb_indicator(client, indicator_id)
    if not raw_rows:
        return DownloadResult(category=category, row_count=0, records=(),
                              error=f"No data from World Bank for {indicator_id}")

    _save_raw(f"{indicator_key}_raw.json", raw_rows)
    records = _parse_wb_records(raw_rows, category, metric, unit, source_url,
                                 normalize_fn=normalize_fn)

    logger.info("%s: parsed %d records from World Bank", indicator_key, len(records))
    return DownloadResult(category=category, row_count=len(records), records=tuple(records))


# ---------------------------------------------------------------------------
# Individual downloaders — now backed by World Bank API
# ---------------------------------------------------------------------------


async def download_unemployment_historical(client: httpx.AsyncClient) -> DownloadResult:
    """Download unemployment rate for HK from World Bank. Returns annual Q4 records."""
    return await _download_wb_simple(
        client, "unemployment", "unemployment", "unemployment_rate", "percent",
    )


async def download_cpi_historical(client: httpx.AsyncClient) -> DownloadResult:
    """Download CPI index (2010=100) for HK from World Bank. Returns annual Q4 records."""
    return await _download_wb_simple(
        client, "cpi", "price_index", "cpi_composite", "index",
    )


async def download_retail_sales_historical(client: httpx.AsyncClient) -> DownloadResult:
    """Download household final consumption growth (retail proxy) from World Bank."""
    return await _download_wb_simple(
        client, "retail_sales", "retail_tourism", "retail_sales_index", "percent_change",
    )


async def download_visitor_arrivals_historical(client: httpx.AsyncClient) -> DownloadResult:
    """Download international tourism arrivals for HK from World Bank."""
    def _to_thousands(val: float) -> float:
        return round(val / 1000.0, 2) if val > 10_000 else round(val, 2)

    return await _download_wb_simple(
        client, "visitor_arrivals", "retail_tourism", "tourist_arrivals", "thousands",
        normalize_fn=_to_thousands,
    )


async def download_gdp_historical(client: httpx.AsyncClient) -> DownloadResult:
    """Download GDP growth rate for HK from World Bank. Returns annual Q4 records."""
    indicator_id = _WB_INDICATORS["gdp"]
    source_url = f"{_WB_BASE}/{indicator_id}"
    raw_rows = await _fetch_wb_indicator(client, indicator_id)
    if not raw_rows:
        return DownloadResult("gdp", 0, (), f"No data from World Bank for {indicator_id}")

    _save_raw("gdp_raw.json", raw_rows)

    records: list[CenstatdRecord] = []
    for row in raw_rows:
        year = str(row.get("date", "")).strip()
        val = _safe_float(row.get("value"))
        if not year or val is None:
            continue
        period = _year_to_q4(year)
        records.append(CenstatdRecord(period, "gdp_growth_rate", round(val, 4),
                                       "percent", "World Bank", source_url))

    logger.info("GDP: parsed %d records", len(records))
    return DownloadResult("gdp", len(records), tuple(records))


async def download_net_migration(client: httpx.AsyncClient) -> DownloadResult:
    """Download net migration for HK from World Bank.

    Uses the SM.POP.NETM indicator (annual net migration).
    Interpolates annual values to quarterly (divide by 4).
    """
    indicator_id = _WB_INDICATORS["net_migration"]
    source_url = f"{_WB_BASE}/{indicator_id}"
    raw_rows = await _fetch_wb_indicator(client, indicator_id)
    if not raw_rows:
        return DownloadResult("migration", 0, (), f"No data from World Bank for {indicator_id}")

    _save_raw("migration_raw.json", raw_rows)

    records: list[CenstatdRecord] = []
    for row in raw_rows:
        year = str(row.get("date", "")).strip()
        val = _safe_float(row.get("value"))
        if not year or val is None:
            continue
        # Convert to thousands and split quarterly
        quarterly = round(val / 4_000.0, 2) if abs(val) > 1000 else round(val / 4.0, 2)
        for q in ("Q1", "Q2", "Q3", "Q4"):
            records.append(CenstatdRecord(
                f"{year}-{q}", "net_migration", quarterly, "thousands",
                "World Bank", source_url,
            ))

    logger.info("Net migration: %d quarterly records", len(records))
    return DownloadResult("migration", len(records), tuple(records))


# ---------------------------------------------------------------------------
# Derived: Consumer confidence proxy
# ---------------------------------------------------------------------------


def compute_consumer_confidence_proxy(
    retail_records: tuple[CenstatdRecord, ...],
    unemp_records: tuple[CenstatdRecord, ...],
    hsi_records: tuple[CenstatdRecord, ...],
) -> DownloadResult:
    """Compute consumer confidence proxy from three real data sources.

    Formula:
        0.4 * retail_sales_yoy + 0.3 * (1 - unemp_normalized) * 100 + 0.3 * hsi_qoq_return

    Only computes for periods where ALL three components have data.
    All records tagged source="derived_proxy", source_url="composite: retail+employment+hsi".
    """
    retail_by_q = {r.period: r.value for r in retail_records if r.metric == "retail_sales_index"}
    unemp_by_q = {r.period: r.value for r in unemp_records if r.metric == "unemployment_rate"}
    hsi_by_q = {r.period: r.value for r in hsi_records
                if "hsi" in r.metric.lower() or r.metric in ("hsi_level", "hang_seng_index")}

    # Retail YoY change
    retail_yoy: dict[str, float] = {}
    for period, val in sorted(retail_by_q.items()):
        if "-Q" not in period:
            continue
        prev = f"{int(period[:4]) - 1}-{period[5:]}"
        prev_val = retail_by_q.get(prev)
        if prev_val and prev_val > 0:
            retail_yoy[period] = ((val - prev_val) / prev_val) * 100.0

    # Unemployment normalized to [0, 1] (0-10% range)
    unemp_norm = {p: min(max(v / 10.0, 0.0), 1.0) for p, v in unemp_by_q.items()}

    # HSI quarterly return
    hsi_return: dict[str, float] = {}
    sorted_hsi = sorted(hsi_by_q.items())
    for i in range(1, len(sorted_hsi)):
        period, val = sorted_hsi[i]
        _, prev_val = sorted_hsi[i - 1]
        if prev_val > 0:
            hsi_return[period] = ((val - prev_val) / prev_val) * 100.0

    overlap = set(retail_yoy) & set(unemp_norm) & set(hsi_return)
    records: list[CenstatdRecord] = []
    for period in sorted(overlap):
        confidence = (0.4 * retail_yoy[period]
                      + 0.3 * (1.0 - unemp_norm[period]) * 100.0
                      + 0.3 * hsi_return[period])
        records.append(CenstatdRecord(
            period, "consumer_confidence_proxy", round(confidence, 2),
            "index", "derived_proxy", "composite: retail+employment+hsi",
        ))

    logger.info("Consumer confidence proxy: %d records", len(records))
    return DownloadResult("consumer_confidence", len(records), tuple(records))


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def download_all_censtatd(client: httpx.AsyncClient | None = None) -> list[DownloadResult]:
    """Download all C&SD historical datasets concurrently.

    Returns one DownloadResult per dataset. Consumer confidence proxy is NOT
    auto-computed here (requires external HSI data); call
    compute_consumer_confidence_proxy() separately with real HSI records.
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()

    try:
        tasks = [
            download_unemployment_historical(client),
            download_cpi_historical(client),
            download_gdp_historical(client),
            download_retail_sales_historical(client),
            download_visitor_arrivals_historical(client),
            download_net_migration(client),
        ]
        names = ["unemployment", "cpi", "gdp", "retail_sales", "visitor_arrivals", "net_migration"]

        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        output: list[DownloadResult] = []
        for i, result in enumerate(raw_results):
            if isinstance(result, Exception):
                logger.error("Censtatd %s failed: %s", names[i], result)
                output.append(DownloadResult(names[i], 0, (), str(result)))
            else:
                output.append(result)

        total = sum(r.row_count for r in output)
        errors = sum(1 for r in output if r.error is not None)
        logger.info("Censtatd complete: %d records, %d datasets, %d errors", total, len(output), errors)
        return output
    finally:
        if own_client:
            await client.aclose()
