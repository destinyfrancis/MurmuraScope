"""Download HK property market data.

Sources:
- Rating and Valuation Department (RVD) property price indices
- data.gov.hk property transaction data

Raw files saved to data/raw/property/.
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

logger = get_logger("data_pipeline.property")

CKAN_BASE = "https://data.gov.hk/en/api/3/action/"

# RVD property price/rental indices — available as CSV on data.gov.hk
# These dataset IDs are for the RVD private domestic price index
RVD_DATASETS: dict[str, str] = {
    "price_index": "hk-rvd-statistic-prn",
    "rental_index": "hk-rvd-statistic-rrn",
}

# Property transaction data from data.gov.hk (Land Registry)
TRANSACTION_DATASETS: dict[str, str] = {
    "agreement_sale_purchase": "hk-landsd-opendata-asp",
}

# Direct RVD statistics page for supplementary data
RVD_DIRECT_URL = "https://www.rvd.gov.hk/doc/en/statistics/his_data_2.xls"

RAW_DIR = Path("data/raw/property")


@dataclass(frozen=True)
class PropertyRecord:
    """Immutable record for a single property market data point."""

    category: str
    metric: str
    value: float
    unit: str
    period: str
    source: str
    source_url: str


@dataclass(frozen=True)
class PropertyResult:
    """Immutable result of a property download operation."""

    source_name: str
    records: tuple[PropertyRecord, ...]
    raw_file_path: str
    row_count: int


def _try_parse_float(val: str) -> float | None:
    """Try to parse a string as float."""
    cleaned = val.replace(",", "").replace(" ", "").strip()
    if not cleaned or cleaned in ("-", "N/A", "n.a.", "..", "N.A."):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


async def _download_ckan_csv(
    client: httpx.AsyncClient,
    dataset_id: str,
) -> tuple[str, str, Path]:
    """Download CSV from CKAN, return (csv_text, resource_url, file_path)."""
    url = f"{CKAN_BASE}package_show"
    resp = await client.get(url, params={"id": dataset_id}, timeout=30.0)
    resp.raise_for_status()
    payload = resp.json()

    if not payload.get("success"):
        raise ValueError(f"CKAN API returned success=false for {dataset_id}")

    resources = payload["result"].get("resources", [])

    # Pick CSV resource
    resource = None
    for res in resources:
        fmt = (res.get("format") or "").upper()
        if fmt == "CSV" or res.get("url", "").endswith(".csv"):
            resource = res
            break
    if resource is None and resources:
        resource = resources[0]
    if resource is None:
        raise ValueError(f"No resource found for {dataset_id}")

    resource_url = resource["url"]
    filename = resource_url.split("/")[-1] or f"{dataset_id}.csv"
    dest = RAW_DIR / filename

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading property data: %s -> %s", resource_url, dest)
    dl_resp = await client.get(resource_url, timeout=60.0, follow_redirects=True)
    dl_resp.raise_for_status()
    dest.write_bytes(dl_resp.content)

    csv_text = dest.read_text(encoding="utf-8", errors="replace")
    return csv_text, resource_url, dest


def _parse_index_csv(
    csv_text: str,
    source_url: str,
    category: str,
    metric_prefix: str,
    unit: str,
) -> list[PropertyRecord]:
    """Parse RVD index CSV into PropertyRecord list."""
    records: list[PropertyRecord] = []
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)

    if len(rows) < 2:
        logger.warning("CSV has fewer than 2 rows, skipping")
        return records

    headers = [h.strip() for h in rows[0]]

    for row in rows[1:]:
        if not row or all(c.strip() == "" for c in row):
            continue

        row_dict = {headers[j]: row[j].strip() for j in range(min(len(headers), len(row)))}

        # Find period column
        period = ""
        for key in row_dict:
            if any(kw in key.lower() for kw in ("year", "period", "month", "quarter", "date")):
                period = row_dict[key]
                break
        if not period:
            period = list(row_dict.values())[0] if row_dict else ""

        # Extract numeric columns
        for key, val in row_dict.items():
            if any(kw in key.lower() for kw in ("year", "period", "month", "quarter", "date")):
                continue
            numeric = _try_parse_float(val)
            if numeric is not None:
                metric = f"{metric_prefix}_{key.lower().replace(' ', '_').replace('/', '_')}"
                records.append(PropertyRecord(
                    category=category,
                    metric=metric,
                    value=numeric,
                    unit=unit,
                    period=period,
                    source="Rating and Valuation Department",
                    source_url=source_url,
                ))

    return records


async def download_price_index(client: httpx.AsyncClient | None = None) -> PropertyResult:
    """Download RVD private domestic property price index."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()

    try:
        csv_text, resource_url, dest = await _download_ckan_csv(
            client, RVD_DATASETS["price_index"]
        )
        records = _parse_index_csv(
            csv_text, resource_url,
            category="property",
            metric_prefix="price_index",
            unit="index",
        )
        logger.info("Parsed %d price index records", len(records))
        return PropertyResult(
            source_name="rvd_price_index",
            records=tuple(records),
            raw_file_path=str(dest),
            row_count=len(records),
        )
    except Exception:
        logger.exception("Failed to download property price index")
        raise
    finally:
        if own_client:
            await client.aclose()


async def download_rental_index(client: httpx.AsyncClient | None = None) -> PropertyResult:
    """Download RVD private domestic rental index."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()

    try:
        csv_text, resource_url, dest = await _download_ckan_csv(
            client, RVD_DATASETS["rental_index"]
        )
        records = _parse_index_csv(
            csv_text, resource_url,
            category="property",
            metric_prefix="rental_index",
            unit="index",
        )
        logger.info("Parsed %d rental index records", len(records))
        return PropertyResult(
            source_name="rvd_rental_index",
            records=tuple(records),
            raw_file_path=str(dest),
            row_count=len(records),
        )
    except Exception:
        logger.exception("Failed to download property rental index")
        raise
    finally:
        if own_client:
            await client.aclose()


async def download_transactions(client: httpx.AsyncClient | None = None) -> PropertyResult:
    """Download property transaction data from Land Registry via data.gov.hk."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()

    try:
        csv_text, resource_url, dest = await _download_ckan_csv(
            client, TRANSACTION_DATASETS["agreement_sale_purchase"]
        )

        # Transaction CSVs typically have: date, district, class, consideration, etc.
        records: list[PropertyRecord] = []
        reader = csv.reader(io.StringIO(csv_text))
        rows = list(reader)

        if len(rows) >= 2:
            headers = [h.strip() for h in rows[0]]
            for row in rows[1:]:
                if not row or all(c.strip() == "" for c in row):
                    continue
                row_dict = {headers[j]: row[j].strip() for j in range(min(len(headers), len(row)))}

                period = ""
                for key in row_dict:
                    if any(kw in key.lower() for kw in ("date", "year", "month", "period")):
                        period = row_dict[key]
                        break

                # Look for consideration/price column
                for key, val in row_dict.items():
                    if any(kw in key.lower() for kw in ("consideration", "price", "amount")):
                        numeric = _try_parse_float(val)
                        if numeric is not None:
                            district = row_dict.get("District", row_dict.get("district", "unknown"))
                            records.append(PropertyRecord(
                                category="property_transaction",
                                metric=f"transaction_{district.lower().replace(' ', '_')}",
                                value=numeric,
                                unit="hkd",
                                period=period,
                                source="Land Registry",
                                source_url=resource_url,
                            ))

        logger.info("Parsed %d transaction records", len(records))
        return PropertyResult(
            source_name="land_registry_transactions",
            records=tuple(records),
            raw_file_path=str(dest),
            row_count=len(records),
        )
    except Exception:
        logger.exception("Failed to download property transactions")
        raise
    finally:
        if own_client:
            await client.aclose()


async def download_rvd_historical(client: httpx.AsyncClient | None = None) -> PropertyResult:
    """Download RVD historical property data (XLS direct download).

    TODO: Parse XLS format — requires openpyxl or xlrd.
    Currently downloads raw file only.
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()

    try:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        dest = RAW_DIR / "rvd_historical_data.xls"

        logger.info("Downloading RVD historical data: %s", RVD_DIRECT_URL)
        resp = await client.get(RVD_DIRECT_URL, timeout=60.0, follow_redirects=True)
        resp.raise_for_status()
        dest.write_bytes(resp.content)

        logger.warning("RVD XLS downloaded but parsing not yet implemented — raw file saved")
        # TODO: Add openpyxl/xlrd parsing for XLS format
        return PropertyResult(
            source_name="rvd_historical",
            records=(),
            raw_file_path=str(dest),
            row_count=0,
        )
    except Exception:
        logger.exception("Failed to download RVD historical data")
        raise
    finally:
        if own_client:
            await client.aclose()


async def download_all_property(client: httpx.AsyncClient | None = None) -> list[PropertyResult]:
    """Download all property datasets and return parsed results."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()

    try:
        results: list[PropertyResult] = []
        downloaders = [
            download_price_index,
            download_rental_index,
            download_transactions,
            download_rvd_historical,
        ]

        for downloader in downloaders:
            try:
                result = await downloader(client)
                results.append(result)
            except Exception:
                logger.exception("Failed in property downloader: %s", downloader.__name__)

        logger.info(
            "Property download complete: %d/%d datasets succeeded",
            len(results), len(downloaders),
        )
        return results
    finally:
        if own_client:
            await client.aclose()
