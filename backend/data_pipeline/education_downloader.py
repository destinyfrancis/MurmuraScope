"""Download HK education data from UGC and censtatd.

Sources:
- University Grants Committee (UGC) statistics — public reports
- data.gov.hk education datasets

Raw files saved to data/raw/education/.
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

logger = get_logger("data_pipeline.education")

CKAN_BASE = "https://data.gov.hk/en/api/3/action/"

# UGC public statistics — direct download URLs
UGC_BASE = "https://cdcf.ugc.edu.hk/cdcf/searchStatSiteReport.action"
UGC_STATS_URLS: dict[str, str] = {
    # UGC student enrolment by programme level
    "student_enrolment": "https://cdcf.ugc.edu.hk/cdcf/searchStatSiteReport.action",
    # UGC graduate employment statistics
    "graduate_employment": "https://cdcf.ugc.edu.hk/cdcf/searchStatSiteReport.action",
}

# data.gov.hk education datasets
EDUCATION_DATASETS: dict[str, str] = {
    # Student enrolment in educational institutions
    "school_enrolment": "hk-edb-schinfo-enrolment",
    # Number of schools
    "school_count": "hk-edb-schinfo-schools",
}

RAW_DIR = Path("data/raw/education")


@dataclass(frozen=True)
class EducationRecord:
    """Immutable record for a single education data point."""

    category: str
    metric: str
    value: float
    unit: str
    period: str
    source: str
    source_url: str


@dataclass(frozen=True)
class EducationResult:
    """Immutable result of an education download operation."""

    source_name: str
    records: tuple[EducationRecord, ...]
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


async def _download_ckan_dataset(
    client: httpx.AsyncClient,
    dataset_id: str,
    category: str,
    metric_prefix: str,
    unit: str,
    source_name: str,
) -> EducationResult:
    """Download an education dataset from CKAN and parse CSV."""
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

    records: list[EducationRecord] = []
    if len(rows) < 2:
        logger.warning("CSV has fewer than 2 rows for %s", dataset_id)
        return EducationResult(
            source_name=source_name,
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
            if any(kw in key.lower() for kw in ("year", "period", "academic", "school")):
                period = row_dict[key]
                break
        if not period:
            period = list(row_dict.values())[0] if row_dict else ""

        # Extract numeric values
        for key, val in row_dict.items():
            if any(kw in key.lower() for kw in ("year", "period", "academic", "date", "school")):
                continue
            numeric = _try_parse_float(val)
            if numeric is not None:
                metric = f"{metric_prefix}_{key.lower().replace(' ', '_').replace('/', '_')}"
                records.append(EducationRecord(
                    category=category,
                    metric=metric,
                    value=numeric,
                    unit=unit,
                    period=period,
                    source="Education Bureau",
                    source_url=resource_url,
                ))

    logger.info("Parsed %d records from %s", len(records), dataset_id)
    return EducationResult(
        source_name=source_name,
        records=tuple(records),
        raw_file_path=str(dest),
        row_count=len(records),
    )


async def download_school_enrolment(client: httpx.AsyncClient | None = None) -> EducationResult:
    """Download school enrolment data from data.gov.hk."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()

    try:
        return await _download_ckan_dataset(
            client,
            dataset_id=EDUCATION_DATASETS["school_enrolment"],
            category="education",
            metric_prefix="school_enrolment",
            unit="persons",
            source_name="edb_enrolment",
        )
    except Exception:
        logger.exception("Failed to download school enrolment data")
        raise
    finally:
        if own_client:
            await client.aclose()


async def download_school_count(client: httpx.AsyncClient | None = None) -> EducationResult:
    """Download number of schools data from data.gov.hk."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()

    try:
        return await _download_ckan_dataset(
            client,
            dataset_id=EDUCATION_DATASETS["school_count"],
            category="education",
            metric_prefix="school_count",
            unit="schools",
            source_name="edb_schools",
        )
    except Exception:
        logger.exception("Failed to download school count data")
        raise
    finally:
        if own_client:
            await client.aclose()


async def download_ugc_statistics(client: httpx.AsyncClient | None = None) -> EducationResult:
    """Download UGC higher education statistics.

    TODO: UGC CDCF portal requires form-based navigation to download reports.
    This currently attempts a direct fetch; if UGC changes their portal,
    the scraping logic may need to be updated or replaced with manual downloads.
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()

    try:
        RAW_DIR.mkdir(parents=True, exist_ok=True)

        # UGC publishes statistics as HTML tables and PDFs.
        # We try the CDCF statistics search endpoint.
        ugc_url = UGC_STATS_URLS["student_enrolment"]
        logger.info("Attempting to fetch UGC statistics from %s", ugc_url)

        # TODO: UGC CDCF requires POST with specific form parameters.
        # For now, we attempt a GET and save whatever is returned.
        try:
            resp = await client.get(ugc_url, timeout=30.0, follow_redirects=True)
            resp.raise_for_status()
            dest = RAW_DIR / "ugc_statistics.html"
            dest.write_bytes(resp.content)
            logger.warning(
                "UGC data fetched as HTML — manual parsing required. "
                "Consider using data.gov.hk datasets instead."
            )
        except httpx.HTTPError:
            logger.warning(
                "UGC CDCF portal not directly accessible. "
                "UGC statistics need to be downloaded manually from %s",
                ugc_url,
            )
            dest = RAW_DIR / "ugc_statistics_placeholder.txt"
            dest.write_text(
                f"UGC statistics must be downloaded manually from:\n{ugc_url}\n",
                encoding="utf-8",
            )

        return EducationResult(
            source_name="ugc_statistics",
            records=(),
            raw_file_path=str(dest),
            row_count=0,
        )
    except Exception:
        logger.exception("Failed to download UGC statistics")
        raise
    finally:
        if own_client:
            await client.aclose()


async def download_all_education(client: httpx.AsyncClient | None = None) -> list[EducationResult]:
    """Download all education datasets and return parsed results."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()

    try:
        results: list[EducationResult] = []
        downloaders = [
            download_school_enrolment,
            download_school_count,
            download_ugc_statistics,
        ]

        for downloader in downloaders:
            try:
                result = await downloader(client)
                results.append(result)
            except Exception:
                logger.exception("Failed in education downloader: %s", downloader.__name__)

        logger.info(
            "Education download complete: %d/%d datasets succeeded",
            len(results), len(downloaders),
        )
        return results
    finally:
        if own_client:
            await client.aclose()
