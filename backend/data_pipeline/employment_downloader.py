"""Download HK employment and wage statistics.

Sources:
- Census and Statistics Department unemployment rate (hk-censtatd-tablechart-210)
- Salary/wage statistics from censtatd

Raw files saved to data/raw/employment/.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path

import httpx

from backend.app.utils.logger import get_logger

logger = get_logger("data_pipeline.employment")

CKAN_BASE = "https://data.gov.hk/en/api/3/action/"

DATASET_IDS: dict[str, str] = {
    "unemployment": "hk-censtatd-tablechart-210",
    # Earnings and hours statistics
    "wages": "hk-censtatd-tablechart-210-60001",
    # Employment by industry
    "employment_by_industry": "hk-censtatd-tablechart-210-50001",
}

RAW_DIR = Path("data/raw/employment")


@dataclass(frozen=True)
class EmploymentRecord:
    """Immutable record for a single employment data point."""

    category: str
    metric: str
    value: float
    unit: str
    period: str
    source: str
    source_url: str


@dataclass(frozen=True)
class EmploymentResult:
    """Immutable result of an employment download operation."""

    source_name: str
    records: tuple[EmploymentRecord, ...]
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


async def _download_and_parse_censtatd(
    client: httpx.AsyncClient,
    dataset_id: str,
    category: str,
    metric_prefix: str,
    unit: str,
) -> EmploymentResult:
    """Download a censtatd employment dataset from CKAN and parse CSV."""
    url = f"{CKAN_BASE}package_show"
    logger.info("Fetching CKAN metadata for %s", dataset_id)

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
    logger.info("Downloading %s: %s", dataset_id, resource_url)
    dl_resp = await client.get(resource_url, timeout=60.0, follow_redirects=True)
    dl_resp.raise_for_status()
    dest.write_bytes(dl_resp.content)

    # Parse CSV
    csv_text = dest.read_text(encoding="utf-8", errors="replace")
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)

    records: list[EmploymentRecord] = []
    if len(rows) < 2:
        logger.warning("CSV has fewer than 2 rows for %s", dataset_id)
        return EmploymentResult(
            source_name=dataset_id,
            records=(),
            raw_file_path=str(dest),
            row_count=0,
        )

    headers = [h.strip() for h in rows[0]]

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

        # Extract numeric values
        for key, val in row_dict.items():
            if any(kw in key.lower() for kw in ("year", "period", "quarter", "month", "date")):
                continue
            numeric = _try_parse_float(val)
            if numeric is not None:
                metric = f"{metric_prefix}_{key.lower().replace(' ', '_').replace('/', '_')}"
                records.append(EmploymentRecord(
                    category=category,
                    metric=metric,
                    value=numeric,
                    unit=unit,
                    period=period,
                    source="Census and Statistics Department",
                    source_url=resource_url,
                ))

    logger.info("Parsed %d records from %s", len(records), dataset_id)
    return EmploymentResult(
        source_name=dataset_id,
        records=tuple(records),
        raw_file_path=str(dest),
        row_count=len(records),
    )


async def download_unemployment(client: httpx.AsyncClient | None = None) -> EmploymentResult:
    """Download unemployment rate data from censtatd."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()

    try:
        return await _download_and_parse_censtatd(
            client,
            dataset_id=DATASET_IDS["unemployment"],
            category="employment",
            metric_prefix="unemployment",
            unit="percent",
        )
    except Exception:
        logger.exception("Failed to download unemployment data")
        raise
    finally:
        if own_client:
            await client.aclose()


async def download_wages(client: httpx.AsyncClient | None = None) -> EmploymentResult:
    """Download wage/salary statistics from censtatd."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()

    try:
        return await _download_and_parse_censtatd(
            client,
            dataset_id=DATASET_IDS["wages"],
            category="wages",
            metric_prefix="wages",
            unit="hkd",
        )
    except Exception:
        logger.exception("Failed to download wage data")
        raise
    finally:
        if own_client:
            await client.aclose()


async def download_employment_by_industry(client: httpx.AsyncClient | None = None) -> EmploymentResult:
    """Download employment by industry data from censtatd."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()

    try:
        return await _download_and_parse_censtatd(
            client,
            dataset_id=DATASET_IDS["employment_by_industry"],
            category="employment",
            metric_prefix="employment_industry",
            unit="thousands",
        )
    except Exception:
        logger.exception("Failed to download employment by industry data")
        raise
    finally:
        if own_client:
            await client.aclose()


async def download_all_employment(client: httpx.AsyncClient | None = None) -> list[EmploymentResult]:
    """Download all employment datasets and return parsed results."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()

    try:
        results: list[EmploymentResult] = []
        downloaders = [
            download_unemployment,
            download_wages,
            download_employment_by_industry,
        ]

        for downloader in downloaders:
            try:
                result = await downloader(client)
                results.append(result)
            except Exception:
                logger.exception("Failed in employment downloader: %s", downloader.__name__)

        logger.info(
            "Employment download complete: %d/%d datasets succeeded",
            len(results), len(downloaders),
        )
        return results
    finally:
        if own_client:
            await client.aclose()
