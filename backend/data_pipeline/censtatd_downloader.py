"""Download real historical economic data from data.gov.hk CKAN API.

Replaces synthetic seed data with actual C&SD (Census and Statistics Department)
published statistics for: unemployment, CPI, GDP, retail sales, visitor arrivals,
net migration, and a derived consumer confidence proxy.

Data strategy:
  1. Try CKAN package_show with known dataset ID.
  2. Fall back to package_search with keyword.
  3. Return empty + error if nothing works (NO hardcoded fallback data).

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

_CKAN_BASE = "https://data.gov.hk/en/api/3/action"
_RAW_DIR = Path("data/raw/censtatd")
_MAX_RETRIES = 3
_BACKOFF_BASE_S = 1.0

_KNOWN_DATASETS: dict[str, str] = {
    "unemployment": "hk-censtatd-tablechart-006",
    "cpi": "hk-censtatd-tablechart-520",
    "gdp": "hk-censtatd-tablechart-310",
    "retail_sales": "hk-censtatd-tablechart-133",
    "visitor_arrivals": "hk-censtatd-tablechart-1300",
    "population": "hk-censtatd-tablechart-002",
}

_SEARCH_KEYWORDS: dict[str, str] = {
    "unemployment": "unemployment rate hong kong",
    "cpi": "consumer price index composite hong kong",
    "gdp": "gross domestic product hong kong",
    "retail_sales": "retail sales value index hong kong",
    "visitor_arrivals": "visitor arrivals hong kong",
    "population": "mid-year population estimates hong kong",
}

_QUARTER_FOR_MONTH: dict[int, str] = {
    1: "Q1", 2: "Q1", 3: "Q1", 4: "Q2", 5: "Q2", 6: "Q2",
    7: "Q3", 8: "Q3", 9: "Q3", 10: "Q4", 11: "Q4", 12: "Q4",
}

_MONTH_ABBR: dict[str, str] = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
    "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12",
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


def _normalize_period(raw: str) -> str:
    """Normalize period strings to YYYY-QN or YYYY-MM format."""
    raw = raw.strip()
    if len(raw) == 7 and raw[4] == "-" and raw[5] == "Q":
        return raw
    # "2024 Q1" / "2024-Q1" / "2024/Q1"
    for sep in (" ", "-", "/"):
        if sep + "Q" in raw.upper():
            parts = raw.upper().replace(sep, " ").split()
            for i, p in enumerate(parts):
                if p.startswith("Q") and len(p) == 2 and p[1].isdigit():
                    return f"{parts[i - 1] if i > 0 else parts[0]}-{p}"
    if len(raw) == 6 and raw[4].upper() == "Q" and raw[5].isdigit():
        return f"{raw[:4]}-Q{raw[5]}"
    if len(raw) == 7 and raw[4] == "-" and raw[5:7].isdigit():
        return raw
    if len(raw) == 7 and raw[2] == "/" and raw[3:7].isdigit():
        return f"{raw[3:7]}-{raw[0:2]}"
    lower = raw.lower()
    for abbr, num in _MONTH_ABBR.items():
        if lower.startswith(abbr):
            digits = "".join(c for c in raw if c.isdigit())
            if len(digits) >= 4:
                return f"{digits[-4:]}-{num}"
    if len(raw) == 4 and raw.isdigit():
        return f"{raw}-Q4"
    return raw


def _is_monthly(period: str) -> bool:
    return len(period) == 7 and period[4] == "-" and period[5:7].isdigit()


def _monthly_to_quarterly(records: list[CenstatdRecord]) -> list[CenstatdRecord]:
    """Average monthly records into quarterly buckets."""
    buckets: dict[tuple[str, str], list[CenstatdRecord]] = {}
    for rec in records:
        if _is_monthly(rec.period):
            month = int(rec.period[5:7])
            q = _QUARTER_FOR_MONTH.get(month)
            key = (rec.metric, f"{rec.period[:4]}-{q}") if q else (rec.metric, rec.period)
        else:
            key = (rec.metric, rec.period)
        buckets.setdefault(key, []).append(rec)

    result: list[CenstatdRecord] = []
    for (metric, q_period), recs in sorted(buckets.items()):
        avg_val = sum(r.value for r in recs) / len(recs)
        t = recs[0]
        result.append(CenstatdRecord(q_period, metric, round(avg_val, 4), t.unit, t.source, t.source_url))
    return result


async def _fetch_with_retry(
    client: httpx.AsyncClient, url: str, params: dict[str, Any], *, timeout: float = 30.0,
) -> dict[str, Any] | None:
    """GET with 3 retries and exponential backoff (1s, 2s, 4s)."""
    for attempt in range(_MAX_RETRIES):
        try:
            resp = await client.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            if data.get("success"):
                return data
        except (httpx.HTTPStatusError, httpx.RequestError, httpx.TimeoutException) as exc:
            logger.debug("Attempt %d failed for %s: %s", attempt + 1, url, exc)
        except (json.JSONDecodeError, ValueError):
            return None
        if attempt < _MAX_RETRIES - 1:
            await asyncio.sleep(_BACKOFF_BASE_S * (2 ** attempt))
    return None


def _pick_best_resource(resources: list[dict[str, Any]]) -> str | None:
    """Pick datastore-active > CSV > first resource."""
    for res in resources:
        if res.get("datastore_active") is True:
            return res.get("id")
    for res in resources:
        if (res.get("format") or "").upper() == "CSV":
            return res.get("id")
    return next((res.get("id") for res in resources if res.get("id")), None)


async def _find_resource_id(client: httpx.AsyncClient, key: str) -> str | None:
    """Discover CKAN resource ID: package_show first, then package_search."""
    known_id = _KNOWN_DATASETS.get(key)
    if known_id:
        data = await _fetch_with_retry(client, f"{_CKAN_BASE}/package_show", {"id": known_id})
        if data:
            rid = _pick_best_resource(data.get("result", {}).get("resources", []))
            if rid:
                return rid

    kw = _SEARCH_KEYWORDS.get(key, key)
    data = await _fetch_with_retry(client, f"{_CKAN_BASE}/package_search", {"q": kw, "rows": 3})
    if data:
        for pkg in data.get("result", {}).get("results", []):
            rid = _pick_best_resource(pkg.get("resources", []))
            if rid:
                return rid

    logger.warning("Could not find CKAN resource for %s", key)
    return None


async def _datastore_search(client: httpx.AsyncClient, resource_id: str, limit: int = 500) -> list[dict]:
    """Fetch records from CKAN datastore_search with retry."""
    data = await _fetch_with_retry(
        client, f"{_CKAN_BASE}/datastore_search",
        {"resource_id": resource_id, "limit": str(limit)},
    )
    if data is None:
        return []
    recs = data.get("result", {}).get("records", [])
    logger.info("datastore_search: %d records for %s", len(recs), resource_id)
    return recs


def _save_raw(filename: str, data: Any) -> None:
    _RAW_DIR.mkdir(parents=True, exist_ok=True)
    (_RAW_DIR / filename).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _src_url(resource_id: str) -> str:
    return f"https://data.gov.hk/en/api/3/action/datastore_search?resource_id={resource_id}"


def _extract_period(row: dict) -> str:
    """Extract and normalize period from a CKAN row."""
    raw = str(row.get("period", row.get("Period", row.get("date",
              row.get("month", row.get("quarter", row.get("Year", "")))))))
    return _normalize_period(raw)


def _extract_value(row: dict, columns: tuple[str, ...]) -> float | None:
    """Try columns in order, return first valid float."""
    for col in columns:
        val = _safe_float(row.get(col))
        if val is not None:
            return val
    return None


async def _download_simple(
    client: httpx.AsyncClient,
    dataset_key: str,
    category: str,
    metric: str,
    unit: str,
    columns: tuple[str, ...],
    *,
    normalize_fn: Any = None,
) -> DownloadResult:
    """Generic downloader for single-metric datasets.

    Handles resource discovery, datastore fetch, parsing, and monthly->quarterly.
    """
    resource_id = await _find_resource_id(client, dataset_key)
    if resource_id is None:
        return DownloadResult(category=category, row_count=0, records=(),
                              error=f"Could not locate {dataset_key} dataset on data.gov.hk")

    raw_rows = await _datastore_search(client, resource_id)
    if not raw_rows:
        return DownloadResult(category=category, row_count=0, records=(),
                              error=f"No records from datastore_search (resource={resource_id})")

    _save_raw(f"{dataset_key}_raw.json", raw_rows)
    source_url = _src_url(resource_id)

    records: list[CenstatdRecord] = []
    for row in raw_rows:
        period = _extract_period(row)
        if not period:
            continue
        val = _extract_value(row, columns)
        if val is None:
            continue
        if normalize_fn:
            val = normalize_fn(val)
        records.append(CenstatdRecord(period, metric, val, unit,
                                       "Census and Statistics Department", source_url))

    if any(_is_monthly(r.period) for r in records):
        records = _monthly_to_quarterly(records)

    logger.info("%s: parsed %d records", dataset_key, len(records))
    return DownloadResult(category=category, row_count=len(records), records=tuple(records))


# ---------------------------------------------------------------------------
# Individual downloaders
# ---------------------------------------------------------------------------

_UNEMP_COLS = ("unemployment_rate", "Unemployment rate", "unemployment",
               "seasonally_adjusted", "rate", "value", "Value")

_CPI_COLS = ("composite", "Composite", "cpi_composite", "CPI(A)",
             "index", "Index", "value", "Value")

_RETAIL_COLS = ("value_index", "retail_sales_index", "index", "Index",
                "value", "Value", "total")

_VISITOR_COLS = ("total", "Total", "arrivals", "visitor_arrivals",
                 "value", "Value", "number")


def _normalize_visitor_count(val: float) -> float:
    """Convert raw visitor count to thousands if needed."""
    return round(val / 1000.0, 2) if val > 100_000 else round(val, 2)


async def download_unemployment_historical(client: httpx.AsyncClient) -> DownloadResult:
    """Download unemployment rate from C&SD. Returns quarterly percent values."""
    return await _download_simple(client, "unemployment", "unemployment",
                                   "unemployment_rate", "percent", _UNEMP_COLS)


async def download_cpi_historical(client: httpx.AsyncClient) -> DownloadResult:
    """Download CPI-A Composite index from C&SD. Returns quarterly index values."""
    return await _download_simple(client, "cpi", "price_index",
                                   "cpi_composite", "index", _CPI_COLS)


async def download_retail_sales_historical(client: httpx.AsyncClient) -> DownloadResult:
    """Download retail sales value index from C&SD. Returns quarterly index values."""
    return await _download_simple(client, "retail_sales", "retail_tourism",
                                   "retail_sales_index", "index", _RETAIL_COLS)


async def download_visitor_arrivals_historical(client: httpx.AsyncClient) -> DownloadResult:
    """Download visitor arrivals from C&SD/HKTB. Returns quarterly thousands."""
    return await _download_simple(client, "visitor_arrivals", "retail_tourism",
                                   "tourist_arrivals", "thousands", _VISITOR_COLS,
                                   normalize_fn=_normalize_visitor_count)


async def download_gdp_historical(client: httpx.AsyncClient) -> DownloadResult:
    """Download GDP at constant prices + compute YoY growth. Returns quarterly records."""
    resource_id = await _find_resource_id(client, "gdp")
    if resource_id is None:
        return DownloadResult("gdp", 0, (), "Could not locate GDP dataset on data.gov.hk")

    raw_rows = await _datastore_search(client, resource_id)
    if not raw_rows:
        return DownloadResult("gdp", 0, (), f"No GDP records (resource={resource_id})")

    _save_raw("gdp_raw.json", raw_rows)
    source_url = _src_url(resource_id)
    src = "Census and Statistics Department"

    gdp_cols = ("gdp", "GDP", "gdp_constant", "real_gdp", "value", "Value", "amount")
    growth_cols = ("yoy_growth", "growth_rate", "YoY", "change_pct")

    records: list[CenstatdRecord] = []
    for row in raw_rows:
        period = _extract_period(row)
        if not period:
            continue
        val = _extract_value(row, gdp_cols)
        if val is not None:
            records.append(CenstatdRecord(period, "gdp_constant_prices", val, "hkd_million", src, source_url))
        g = _extract_value(row, growth_cols)
        if g is not None:
            records.append(CenstatdRecord(period, "gdp_growth_rate", g, "percent", src, source_url))

    # Compute YoY growth from levels where not already present
    existing_growth = {r.period for r in records if r.metric == "gdp_growth_rate"}
    levels = {r.period: r.value for r in records if r.metric == "gdp_constant_prices"}

    for period, val in sorted(levels.items()):
        if period in existing_growth or "-Q" not in period:
            continue
        prev = f"{int(period[:4]) - 1}-{period[5:]}"
        prev_val = levels.get(prev)
        if prev_val and prev_val > 0:
            yoy = round(((val - prev_val) / prev_val) * 100.0, 2)
            records.append(CenstatdRecord(period, "gdp_growth_rate", yoy, "percent", src, source_url))

    logger.info("GDP: parsed %d records", len(records))
    return DownloadResult("gdp", len(records), tuple(records))


async def download_net_migration(client: httpx.AsyncClient) -> DownloadResult:
    """Download net migration from mid-year population estimates.

    Derives net_migration = population_change - natural_increase, then
    interpolates annual values to quarterly (divide by 4).
    """
    resource_id = await _find_resource_id(client, "population")
    if resource_id is None:
        return DownloadResult("migration", 0, (), "Could not locate population dataset on data.gov.hk")

    raw_rows = await _datastore_search(client, resource_id)
    if not raw_rows:
        return DownloadResult("migration", 0, (), f"No population records (resource={resource_id})")

    _save_raw("population_raw.json", raw_rows)
    source_url = _src_url(resource_id)

    pop_cols = ("population", "Population", "mid_year_population", "total", "Total", "value", "Value")
    nat_cols = ("natural_increase", "Natural increase", "births_minus_deaths", "net_natural")

    pop_by_year: dict[str, float] = {}
    nat_by_year: dict[str, float] = {}
    for row in raw_rows:
        yr_raw = str(row.get("year", row.get("Year", row.get("period", row.get("Period", "")))))
        digits = "".join(c for c in yr_raw if c.isdigit())
        if len(digits) < 4:
            continue
        year = digits[:4]
        val = _extract_value(row, pop_cols)
        if val is not None:
            pop_by_year[year] = val
        nat = _extract_value(row, nat_cols)
        if nat is not None:
            nat_by_year[year] = nat

    records: list[CenstatdRecord] = []
    years = sorted(pop_by_year.keys())
    for i in range(1, len(years)):
        yr, prev_yr = years[i], years[i - 1]
        net_mig = (pop_by_year[yr] - pop_by_year[prev_yr]) - nat_by_year.get(yr, 0.0)
        if abs(net_mig) > 10_000:
            net_mig /= 1000.0
        quarterly = round(net_mig / 4.0, 2)
        for q in ("Q1", "Q2", "Q3", "Q4"):
            records.append(CenstatdRecord(
                f"{yr}-{q}", "net_migration", quarterly, "thousands",
                "Census and Statistics Department", source_url,
            ))

    logger.info("Net migration: %d quarterly records from %d annual observations",
                len(records), max(len(years) - 1, 0))
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
