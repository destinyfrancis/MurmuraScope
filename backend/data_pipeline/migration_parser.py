"""Parse HK migration statistics.

Sources:
- Immigration Department statistics (data.gov.hk)
- Census population movement data

Migration data includes:
- One-way permit holders (mainland to HK)
- Net migration estimates
- Visitor arrivals/departures

Raw files saved to data/raw/migration/.
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

logger = get_logger("data_pipeline.migration")

CKAN_BASE = "https://data.gov.hk/en/api/3/action/"

# Immigration Department datasets on data.gov.hk
MIGRATION_DATASETS: dict[str, str] = {
    # Passenger traffic statistics
    "passenger_traffic": "hk-immd-passenger-traffic-statistics",
    # Residents movement — departures/arrivals
    "residents_movement": "hk-immd-set4-passenger_arrival_departure",
}

# Direct URL for Immigration Department monthly statistics
IMMD_STATS_URL = "https://www.immd.gov.hk/eng/stat_info.html"

RAW_DIR = Path("data/raw/migration")


@dataclass(frozen=True)
class MigrationRecord:
    """Immutable record for a single migration data point."""

    category: str
    metric: str
    value: float
    unit: str
    period: str
    source: str
    source_url: str


@dataclass(frozen=True)
class MigrationResult:
    """Immutable result of a migration download/parse operation."""

    source_name: str
    records: tuple[MigrationRecord, ...]
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


def parse_migration_csv(csv_text: str, source_url: str) -> list[MigrationRecord]:
    """Parse a migration statistics CSV into MigrationRecord list.

    Expected CSV format varies by dataset, but typically includes:
    - Period/Date column
    - Category columns (arrivals, departures, by control point, etc.)
    - Numeric value columns
    """
    records: list[MigrationRecord] = []
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)

    if len(rows) < 2:
        logger.warning("Migration CSV has fewer than 2 rows")
        return records

    headers = [h.strip() for h in rows[0]]

    for row in rows[1:]:
        if not row or all(c.strip() == "" for c in row):
            continue

        row_dict = {headers[j]: row[j].strip() for j in range(min(len(headers), len(row)))}

        # Find period column
        period = ""
        for key in row_dict:
            if any(kw in key.lower() for kw in ("year", "period", "month", "date", "quarter")):
                period = row_dict[key]
                break
        if not period:
            period = list(row_dict.values())[0] if row_dict else ""

        # Determine category from column names
        for key, val in row_dict.items():
            key_lower = key.lower()
            if any(kw in key_lower for kw in ("year", "period", "month", "date", "quarter")):
                continue

            numeric = _try_parse_float(val)
            if numeric is None:
                continue

            # Classify the metric
            if any(kw in key_lower for kw in ("arrival", "incoming", "入境")):
                category = "migration_arrival"
            elif any(kw in key_lower for kw in ("departure", "outgoing", "出境")):
                category = "migration_departure"
            elif any(kw in key_lower for kw in ("one-way", "one way", "single", "單程")):
                category = "migration_one_way_permit"
            elif any(kw in key_lower for kw in ("net", "淨")):
                category = "migration_net"
            else:
                category = "migration"

            metric = key_lower.replace(" ", "_").replace("/", "_").replace("-", "_")
            records.append(MigrationRecord(
                category=category,
                metric=metric,
                value=numeric,
                unit="persons",
                period=period,
                source="Immigration Department",
                source_url=source_url,
            ))

    return records


async def _download_ckan_migration(
    client: httpx.AsyncClient,
    dataset_id: str,
) -> MigrationResult:
    """Download a migration dataset from CKAN."""
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
    logger.info("Downloading migration data: %s", resource_url)
    dl_resp = await client.get(resource_url, timeout=60.0, follow_redirects=True)
    dl_resp.raise_for_status()
    dest.write_bytes(dl_resp.content)

    csv_text = dest.read_text(encoding="utf-8", errors="replace")
    records = parse_migration_csv(csv_text, resource_url)

    logger.info("Parsed %d records from %s", len(records), dataset_id)
    return MigrationResult(
        source_name=dataset_id,
        records=tuple(records),
        raw_file_path=str(dest),
        row_count=len(records),
    )


async def download_passenger_traffic(client: httpx.AsyncClient | None = None) -> MigrationResult:
    """Download passenger traffic statistics from Immigration Department."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()

    try:
        return await _download_ckan_migration(client, MIGRATION_DATASETS["passenger_traffic"])
    except Exception:
        logger.exception("Failed to download passenger traffic data")
        raise
    finally:
        if own_client:
            await client.aclose()


async def download_residents_movement(client: httpx.AsyncClient | None = None) -> MigrationResult:
    """Download residents arrival/departure statistics."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()

    try:
        return await _download_ckan_migration(client, MIGRATION_DATASETS["residents_movement"])
    except Exception:
        logger.exception("Failed to download residents movement data")
        raise
    finally:
        if own_client:
            await client.aclose()


def parse_migration_file(file_path: str | Path) -> MigrationResult:
    """Parse a previously downloaded migration statistics file.

    Useful for re-processing raw files without re-downloading.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Migration file not found: {path}")

    csv_text = path.read_text(encoding="utf-8", errors="replace")
    records = parse_migration_csv(csv_text, source_url=f"file://{path}")

    return MigrationResult(
        source_name=path.stem,
        records=tuple(records),
        raw_file_path=str(path),
        row_count=len(records),
    )


async def download_all_migration(client: httpx.AsyncClient | None = None) -> list[MigrationResult]:
    """Download all migration datasets and return parsed results."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()

    try:
        results: list[MigrationResult] = []
        downloaders = [
            download_passenger_traffic,
            download_residents_movement,
        ]

        for downloader in downloaders:
            try:
                result = await downloader(client)
                results.append(result)
            except Exception:
                logger.exception("Failed in migration downloader: %s", downloader.__name__)

        logger.info(
            "Migration download complete: %d/%d datasets succeeded",
            len(results), len(downloaders),
        )
        return results
    finally:
        if own_client:
            await client.aclose()
