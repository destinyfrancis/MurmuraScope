"""Download HK Census & Statistics Department population data.

Fetches from data.gov.hk CKAN API:
- hk-censtatd-tablechart-110-01001 (population by age group x sex)
- hk-censtatd-tablechart-110-01002 (population by single year of age)

Raw CSV/XLSX files saved to data/raw/census/.
Returns parsed DataFrames for normalisation.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from backend.app.utils.logger import get_logger

logger = get_logger("data_pipeline.census")

CKAN_BASE = "https://data.gov.hk/en/api/3/action/"

DATASET_IDS: dict[str, str] = {
    "population_age_sex": "hk-censtatd-tablechart-110-01001",
    "population_single_age": "hk-censtatd-tablechart-110-01002",
}

RAW_DIR = Path("data/raw/census")


@dataclass(frozen=True)
class CensusRecord:
    """Immutable record for a single census data point."""

    dataset_id: str
    metric: str
    dimension_1: str
    dimension_2: str | None
    dimension_3: str | None
    value: float
    period: str
    source_url: str


@dataclass(frozen=True)
class CensusResult:
    """Immutable result of a census download operation."""

    dataset_id: str
    records: tuple[CensusRecord, ...]
    raw_file_path: str
    row_count: int


async def _fetch_ckan_package(client: httpx.AsyncClient, dataset_id: str) -> dict[str, Any]:
    """Fetch CKAN package metadata to find downloadable resource URLs."""
    url = f"{CKAN_BASE}package_show"
    params = {"id": dataset_id}
    logger.info("Fetching CKAN package metadata for %s", dataset_id)

    resp = await client.get(url, params=params, timeout=30.0)
    resp.raise_for_status()
    payload = resp.json()

    if not payload.get("success"):
        raise ValueError(f"CKAN API returned success=false for {dataset_id}")

    return payload["result"]


async def _download_resource(client: httpx.AsyncClient, resource_url: str, dest: Path) -> Path:
    """Download a resource file (CSV/XLSX) to the raw directory."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading resource: %s -> %s", resource_url, dest)

    resp = await client.get(resource_url, timeout=60.0, follow_redirects=True)
    resp.raise_for_status()
    dest.write_bytes(resp.content)

    logger.info("Saved %d bytes to %s", len(resp.content), dest)
    return dest


def _pick_csv_resource(resources: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Select the best CSV resource from a CKAN package's resource list."""
    for res in resources:
        fmt = (res.get("format") or "").upper()
        name = (res.get("name") or "").lower()
        url = res.get("url", "")
        if fmt == "CSV" or url.endswith(".csv") or "csv" in name:
            return res
    # Fallback: return first resource if no CSV found
    return resources[0] if resources else None


def _parse_population_csv(csv_text: str, dataset_id: str, source_url: str) -> list[CensusRecord]:
    """Parse a censtatd population CSV into CensusRecord list.

    The CSV format from censtatd typically has:
    - Header rows with metadata
    - Data rows with year/period, dimension columns, and value columns
    """
    records: list[CensusRecord] = []
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)

    if len(rows) < 2:
        logger.warning("CSV has fewer than 2 rows for %s, skipping parse", dataset_id)
        return records

    # Find header row (first row with recognisable column names)
    header_idx = 0
    for i, row in enumerate(rows):
        row_lower = [c.lower().strip() for c in row]
        if any(kw in " ".join(row_lower) for kw in ("year", "age", "sex", "period", "male", "female")):
            header_idx = i
            break

    headers = [h.strip() for h in rows[header_idx]]

    for row in rows[header_idx + 1 :]:
        if not row or all(c.strip() == "" for c in row):
            continue

        # Build a dict from headers -> values
        row_dict: dict[str, str] = {}
        for j, val in enumerate(row):
            if j < len(headers):
                row_dict[headers[j]] = val.strip()

        # Extract period (look for year-like column)
        period = ""
        for key in row_dict:
            key_lower = key.lower()
            if "year" in key_lower or "period" in key_lower or "date" in key_lower:
                period = row_dict[key]
                break

        if not period and row_dict:
            # Use first column as period fallback
            period = list(row_dict.values())[0]

        # Extract dimensions and values based on dataset
        if dataset_id == DATASET_IDS["population_age_sex"]:
            dim1 = row_dict.get("Age Group", row_dict.get("Age group", ""))
            dim2 = row_dict.get("Sex", row_dict.get("sex", ""))
            # Look for count/value column
            value_str = _find_numeric_value(row_dict, exclude_keys={"year", "period", "age", "sex"})
            if value_str is not None:
                records.append(CensusRecord(
                    dataset_id=dataset_id,
                    metric="population_by_age_sex",
                    dimension_1=dim1 or list(row_dict.values())[1] if len(row_dict) > 1 else "",
                    dimension_2=dim2 or None,
                    dimension_3=None,
                    value=value_str,
                    period=period,
                    source_url=source_url,
                ))
        else:
            # Generic: treat columns beyond the first two as metric values
            cols = list(row_dict.items())
            dim1 = cols[1][1] if len(cols) > 1 else ""
            for key, val in cols[2:]:
                numeric = _try_parse_float(val)
                if numeric is not None:
                    records.append(CensusRecord(
                        dataset_id=dataset_id,
                        metric=f"population_{key.lower().replace(' ', '_')}",
                        dimension_1=dim1,
                        dimension_2=key,
                        dimension_3=None,
                        value=numeric,
                        period=period,
                        source_url=source_url,
                    ))

    return records


def _find_numeric_value(row_dict: dict[str, str], exclude_keys: set[str]) -> float | None:
    """Find the first numeric value in a row dict, excluding certain keys."""
    for key, val in row_dict.items():
        if key.lower() in exclude_keys:
            continue
        result = _try_parse_float(val)
        if result is not None:
            return result
    return None


def _try_parse_float(val: str) -> float | None:
    """Try to parse a string as float, stripping commas and whitespace."""
    cleaned = val.replace(",", "").replace(" ", "").strip()
    if not cleaned or cleaned in ("-", "N/A", "n.a.", ".."):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


async def download_population_age_sex(client: httpx.AsyncClient | None = None) -> CensusResult:
    """Download population by age group x sex dataset."""
    dataset_id = DATASET_IDS["population_age_sex"]
    own_client = client is None

    if own_client:
        client = httpx.AsyncClient()

    try:
        package = await _fetch_ckan_package(client, dataset_id)
        resources = package.get("resources", [])

        resource = _pick_csv_resource(resources)
        if resource is None:
            raise ValueError(f"No downloadable resource found for {dataset_id}")

        resource_url = resource["url"]
        filename = resource_url.split("/")[-1] or f"{dataset_id}.csv"
        dest = RAW_DIR / filename

        await _download_resource(client, resource_url, dest)

        csv_text = dest.read_text(encoding="utf-8", errors="replace")
        records = _parse_population_csv(csv_text, dataset_id, resource_url)

        logger.info("Parsed %d records from %s", len(records), dataset_id)
        return CensusResult(
            dataset_id=dataset_id,
            records=tuple(records),
            raw_file_path=str(dest),
            row_count=len(records),
        )
    except Exception:
        logger.exception("Failed to download %s", dataset_id)
        raise
    finally:
        if own_client:
            await client.aclose()


async def download_population_single_age(client: httpx.AsyncClient | None = None) -> CensusResult:
    """Download population by single year of age dataset."""
    dataset_id = DATASET_IDS["population_single_age"]
    own_client = client is None

    if own_client:
        client = httpx.AsyncClient()

    try:
        package = await _fetch_ckan_package(client, dataset_id)
        resources = package.get("resources", [])

        resource = _pick_csv_resource(resources)
        if resource is None:
            raise ValueError(f"No downloadable resource found for {dataset_id}")

        resource_url = resource["url"]
        filename = resource_url.split("/")[-1] or f"{dataset_id}.csv"
        dest = RAW_DIR / filename

        await _download_resource(client, resource_url, dest)

        csv_text = dest.read_text(encoding="utf-8", errors="replace")
        records = _parse_population_csv(csv_text, dataset_id, resource_url)

        logger.info("Parsed %d records from %s", len(records), dataset_id)
        return CensusResult(
            dataset_id=dataset_id,
            records=tuple(records),
            raw_file_path=str(dest),
            row_count=len(records),
        )
    except Exception:
        logger.exception("Failed to download %s", dataset_id)
        raise
    finally:
        if own_client:
            await client.aclose()


async def download_all_census(client: httpx.AsyncClient | None = None) -> list[CensusResult]:
    """Download all census datasets and return parsed results."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()

    try:
        results = [
            await download_population_age_sex(client),
            await download_population_single_age(client),
        ]
        logger.info("Census download complete: %d datasets", len(results))
        return results
    finally:
        if own_client:
            await client.aclose()
