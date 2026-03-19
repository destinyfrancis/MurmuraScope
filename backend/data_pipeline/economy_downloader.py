"""Download HK economic data: HIBOR, prime rate, CPI, GDP.

Sources:
- HKMA API for interbank rates (HIBOR, prime rate)
- data.gov.hk CKAN for CPI (hk-censtatd-tablechart-520) and GDP (hk-censtatd-tablechart-310)
- Hardcoded fallback data when APIs are unavailable

Raw files saved to data/raw/economy/.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from backend.app.utils.logger import get_logger

logger = get_logger("data_pipeline.economy")

CKAN_BASE = "https://data.gov.hk/en/api/3/action/"

# HKMA API — publicly accessible market data endpoints
HKMA_API_BASE = "https://api.hkma.gov.hk/public/market-data-and-statistics/monthly-statistical-bulletin"

HKMA_ENDPOINTS: dict[str, str] = {
    "hibor": f"{HKMA_API_BASE}/er-ir/hk-interbank-ir-endperiod",
    # "prime_rate" endpoint removed — HKMA best-lending-rate API returns HTTP 400
    # Use World Bank lending rate instead (see download_prime_rate).
    "exchange_rate": f"{HKMA_API_BASE}/er-ir/er-hkd-per-100-foreign-currency-end-period",
}

# HKMA HIBOR requires segment parameter
HKMA_HIBOR_PARAMS: dict[str, str] = {"segment": "hibor.fixing"}

# World Bank API replaces former data.gov.hk CKAN sources (CKAN is permanently 404)
_WB_BASE = "https://api.worldbank.org/v2/country/HKG/indicator"
_WB_CPI_INDICATOR = "FP.CPI.TOTL"           # CPI (2010 = 100)
_WB_GDP_INDICATOR = "NY.GDP.MKTP.KD.ZG"     # GDP growth annual %
_WB_LENDING_RATE = "FR.INR.LEND"            # Lending interest rate %


# NOTE: All hardcoded fallback data has been removed.
# If APIs are unavailable, downloaders return empty results with error messages.

RAW_DIR = Path("data/raw/economy")


@dataclass(frozen=True)
class EconomyRecord:
    """Immutable record for a single economic data point."""

    category: str
    metric: str
    value: float
    unit: str
    period: str
    source: str
    source_url: str


@dataclass(frozen=True)
class EconomyResult:
    """Immutable result of an economy download operation."""

    source_name: str
    records: tuple[EconomyRecord, ...]
    raw_file_path: str
    row_count: int


def _try_parse_float(val: str) -> float | None:
    """Try to parse a string as float, stripping commas."""
    cleaned = val.replace(",", "").replace(" ", "").strip()
    if not cleaned or cleaned in ("-", "N/A", "n.a.", "..", "N.A."):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


async def _fetch_hkma_data(
    client: httpx.AsyncClient,
    endpoint_url: str,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Fetch data from HKMA public API.

    HKMA API returns JSON with structure:
    {
        "header": {...},
        "result": {
            "datasize": N,
            "records": [...]
        }
    }
    """
    default_params = {"pagesize": 500, "offset": 0}
    if params:
        default_params.update(params)

    logger.info("Fetching HKMA data: %s", endpoint_url)
    try:
        resp = await client.get(endpoint_url, params=default_params, timeout=30.0)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "HKMA API returned HTTP %d for %s — endpoint may have changed",
            exc.response.status_code, endpoint_url,
        )
        return []
    payload = resp.json()

    result = payload.get("result", {})
    records = result.get("records", [])
    logger.info("HKMA returned %d records", len(records))
    return records


def _empty_result(source_name: str, error: str) -> EconomyResult:
    """Return an empty result with error message — no fallback."""
    logger.warning("%s: %s", source_name, error)
    return EconomyResult(
        source_name=source_name,
        records=(),
        raw_file_path="",
        row_count=0,
    )


async def download_hibor(client: httpx.AsyncClient | None = None) -> EconomyResult:
    """Download HIBOR (Hong Kong Interbank Offered Rate) from HKMA.

    Falls back to hardcoded 2024-Q4 data if the API is unavailable.
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()

    try:
        raw_records = await _fetch_hkma_data(
            client, HKMA_ENDPOINTS["hibor"], params=HKMA_HIBOR_PARAMS,
        )

        if not raw_records:
            return _empty_result("hkma_hibor", "HKMA HIBOR API returned no data")

        # Save raw JSON
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        raw_path = RAW_DIR / "hkma_hibor.json"
        raw_path.write_text(json.dumps(raw_records, indent=2, ensure_ascii=False), encoding="utf-8")

        records: list[EconomyRecord] = []
        for entry in raw_records:
            # HKMA HIBOR records typically have: end_of_month, overnight, 1w, 1m, 3m, 6m, 12m
            period = entry.get("end_of_month", entry.get("year_month", ""))

            for tenor_key in ("ir_overnight", "ir_1w", "ir_1m", "ir_2m", "ir_3m", "ir_6m", "ir_9m", "ir_12m"):
                val = _try_parse_float(str(entry.get(tenor_key, "")))
                if val is not None:
                    records.append(EconomyRecord(
                        category="interest_rate",
                        metric=f"hibor_{tenor_key.replace('ir_', '')}",
                        value=val,
                        unit="percent",
                        period=str(period),
                        source="HKMA",
                        source_url=HKMA_ENDPOINTS["hibor"],
                    ))

        if not records:
            return _empty_result("hkma_hibor", "HKMA HIBOR API returned no data")

        logger.info("Parsed %d HIBOR records", len(records))
        return EconomyResult(
            source_name="hkma_hibor",
            records=tuple(records),
            raw_file_path=str(raw_path),
            row_count=len(records),
        )
    except Exception:
        logger.warning("Failed to download HIBOR data — using fallback", exc_info=True)
        return _empty_result("hkma_hibor", "HKMA HIBOR API returned no data")
    finally:
        if own_client:
            await client.aclose()


async def download_prime_rate(client: httpx.AsyncClient | None = None) -> EconomyResult:
    """Download lending interest rate for HK from World Bank.

    The HKMA best-lending-rate API endpoint now returns HTTP 400 (removed).
    Falls back to World Bank FR.INR.LEND (lending interest rate %) for HK.
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()

    try:
        url = f"{_WB_BASE}/{_WB_LENDING_RATE}"
        resp = await client.get(url, params={"format": "json", "per_page": 60, "mrv": 60}, timeout=30.0)
        resp.raise_for_status()
        data = resp.json()

        if not isinstance(data, list) or len(data) < 2 or not data[1]:
            return _empty_result("wb_lending_rate", "World Bank lending rate returned no data for HK")

        raw_records = data[1]
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        raw_path = RAW_DIR / "wb_lending_rate.json"
        raw_path.write_text(json.dumps(raw_records, indent=2, ensure_ascii=False), encoding="utf-8")

        records: list[EconomyRecord] = []
        for entry in raw_records:
            year = str(entry.get("date", "")).strip()
            val = _try_parse_float(str(entry.get("value", "")))
            if not year or val is None:
                continue
            period = f"{year}-Q4"
            records.append(EconomyRecord(
                category="interest_rate",
                metric="prime_rate",
                value=val,
                unit="percent",
                period=period,
                source="World Bank",
                source_url=url,
            ))

        if not records:
            return _empty_result("wb_lending_rate", "World Bank lending rate: no valid records")

        logger.info("Parsed %d lending rate records from World Bank", len(records))
        return EconomyResult(
            source_name="wb_lending_rate",
            records=tuple(records),
            raw_file_path=str(raw_path),
            row_count=len(records),
        )
    except Exception:
        logger.warning("Failed to download lending rate from World Bank", exc_info=True)
        return _empty_result("wb_lending_rate", "World Bank lending rate fetch failed")
    finally:
        if own_client:
            await client.aclose()




def _parse_csv_records(
    csv_text: str,
    category: str,
    metric_prefix: str,
    unit: str,
    source_url: str,
    dest_path: str,
) -> EconomyResult:
    """Parse a CSV string into EconomyResult."""
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)

    if len(rows) < 2:
        return EconomyResult(source_name=metric_prefix, records=(), raw_file_path=dest_path, row_count=0)

    headers = [h.strip() for h in rows[0]]
    records: list[EconomyRecord] = []

    for row in rows[1:]:
        if not row or all(c.strip() == "" for c in row):
            continue

        row_dict = {headers[j]: row[j].strip() for j in range(min(len(headers), len(row)))}

        # Find period column
        period = ""
        for key in row_dict:
            if any(kw in key.lower() for kw in ("year", "period", "quarter", "month")):
                period = row_dict[key]
                break
        if not period:
            period = list(row_dict.values())[0] if row_dict else ""

        for key, val in row_dict.items():
            if any(kw in key.lower() for kw in ("year", "period", "quarter", "month", "date")):
                continue
            numeric = _try_parse_float(val)
            if numeric is not None:
                metric_name = f"{metric_prefix}_{key.lower().replace(' ', '_').replace('/', '_')}"
                records.append(EconomyRecord(
                    category=category,
                    metric=metric_name,
                    value=numeric,
                    unit=unit,
                    period=period,
                    source="Census and Statistics Department",
                    source_url=source_url,
                ))

    return EconomyResult(
        source_name=metric_prefix,
        records=tuple(records),
        raw_file_path=dest_path,
        row_count=len(records),
    )


async def _download_censtatd_dataset(
    client: httpx.AsyncClient,
    dataset_id: str,
    category: str,
    metric_prefix: str,
    unit: str,
) -> EconomyResult:
    """Download a censtatd dataset from CKAN and parse CSV.

    Falls back to direct CSV URL if CKAN package_show fails.
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    # --- Attempt 1: CKAN package_show ---
    resource_url: str | None = None
    try:
        url = f"{CKAN_BASE}package_show"
        resp = await client.get(url, params={"id": dataset_id}, timeout=30.0)
        resp.raise_for_status()
        payload = resp.json()

        if payload.get("success"):
            resources = payload["result"].get("resources", [])
            for res in resources:
                fmt = (res.get("format") or "").upper()
                if fmt == "CSV" or res.get("url", "").endswith(".csv"):
                    resource_url = res["url"]
                    break
            if resource_url is None and resources:
                resource_url = resources[0].get("url")
    except Exception as exc:
        logger.warning("CKAN package_show failed for %s: %s", dataset_id, exc)

    # --- Attempt 2: direct CSV download from resolved URL ---
    if resource_url:
        try:
            filename = resource_url.split("/")[-1] or f"{dataset_id}.csv"
            dest = RAW_DIR / filename
            logger.info("Downloading censtatd %s: %s", dataset_id, resource_url)
            dl_resp = await client.get(resource_url, timeout=60.0, follow_redirects=True)
            dl_resp.raise_for_status()
            dest.write_bytes(dl_resp.content)
            csv_text = dest.read_text(encoding="utf-8", errors="replace")
            result = _parse_csv_records(csv_text, category, metric_prefix, unit, resource_url, str(dest))
            if result.row_count > 0:
                logger.info("Parsed %d records from %s (CKAN)", result.row_count, dataset_id)
                return result
        except Exception as exc:
            logger.warning("Direct CSV download failed for %s: %s", dataset_id, exc)

    logger.warning("All CKAN/CSV attempts failed for %s — using hardcoded fallback", dataset_id)
    return EconomyResult(source_name=dataset_id, records=(), raw_file_path="", row_count=0)


async def _download_wb_economy(
    client: httpx.AsyncClient,
    indicator_id: str,
    category: str,
    metric: str,
    unit: str,
    source_name: str,
) -> EconomyResult:
    """Generic World Bank economy data fetcher (annual → Q4 records)."""
    url = f"{_WB_BASE}/{indicator_id}"
    try:
        resp = await client.get(url, params={"format": "json", "per_page": 60, "mrv": 60}, timeout=30.0)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list) or len(data) < 2 or not data[1]:
            return _empty_result(source_name, f"World Bank {indicator_id}: no data")
        raw_records = data[1]
    except Exception:
        logger.warning("World Bank fetch failed for %s", indicator_id, exc_info=True)
        return _empty_result(source_name, f"World Bank {indicator_id} fetch failed")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_DIR / f"wb_{source_name}.json"
    raw_path.write_text(json.dumps(raw_records, indent=2, ensure_ascii=False), encoding="utf-8")

    records: list[EconomyRecord] = []
    for entry in raw_records:
        year = str(entry.get("date", "")).strip()
        val = _try_parse_float(str(entry.get("value", "")))
        if not year or val is None:
            continue
        records.append(EconomyRecord(
            category=category,
            metric=metric,
            value=round(val, 4),
            unit=unit,
            period=f"{year}-Q4",
            source="World Bank",
            source_url=url,
        ))

    logger.info("World Bank %s: %d records", source_name, len(records))
    return EconomyResult(
        source_name=source_name,
        records=tuple(records),
        raw_file_path=str(raw_path),
        row_count=len(records),
    )


async def download_cpi(client: httpx.AsyncClient | None = None) -> EconomyResult:
    """Download CPI (2010=100) for HK from World Bank (replaces CKAN which is 404)."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()
    try:
        return await _download_wb_economy(
            client, _WB_CPI_INDICATOR, "price_index", "cpi_composite", "index", "cpi",
        )
    finally:
        if own_client:
            await client.aclose()


async def download_gdp(client: httpx.AsyncClient | None = None) -> EconomyResult:
    """Download GDP growth rate for HK from World Bank (replaces CKAN which is 404)."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()
    try:
        return await _download_wb_economy(
            client, _WB_GDP_INDICATOR, "gdp", "gdp_growth_rate", "percent", "gdp",
        )
    finally:
        if own_client:
            await client.aclose()


async def download_all_economy(client: httpx.AsyncClient | None = None) -> list[EconomyResult]:
    """Download all economy datasets and return parsed results."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()

    try:
        results: list[EconomyResult] = []

        for downloader in (download_hibor, download_prime_rate, download_cpi, download_gdp):
            try:
                result = await downloader(client)
                results.append(result)
            except Exception:
                logger.exception("Failed in economy downloader: %s", downloader.__name__)

        logger.info("Economy download complete: %d/%d datasets succeeded", len(results), 4)
        return results
    finally:
        if own_client:
            await client.aclose()
