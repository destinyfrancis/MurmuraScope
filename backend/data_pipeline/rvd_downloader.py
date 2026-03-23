"""Rating and Valuation Department (RVD) property data downloader.

Downloads HK property price indices and transaction volumes from the RVD
Excel files published on rvd.gov.hk. Uses openpyxl for XLS/XLSX parsing.

Falls back to hardcoded 2024 index data if the download fails.

Raw files saved to data/raw/property/.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import httpx
import openpyxl

from backend.app.utils.logger import get_logger

logger = get_logger("data_pipeline.rvd")

# RVD publishes historical price indices as Excel files
_RVD_EXCEL_URLS: tuple[tuple[str, str], ...] = (
    # (url, description)
    (
        "https://www.rvd.gov.hk/doc/en/statistics/his_data_2.xls",
        "private_domestic_price",
    ),
    (
        "https://www.rvd.gov.hk/doc/en/statistics/his_data_4.xls",
        "private_domestic_rental",
    ),
)

_RAW_DIR = Path("data/raw/property")


# NOTE: All hardcoded fallback data removed.
# If RVD Excel downloads fail, empty results with error messages are returned.


@dataclass(frozen=True)
class RVDRecord:
    """Immutable property data record from RVD."""

    category: str
    metric: str
    value: float
    unit: str
    period: str
    source: str
    source_url: str


@dataclass(frozen=True)
class RVDResult:
    """Immutable result of an RVD download run."""

    source_name: str
    records: tuple[RVDRecord, ...]
    raw_file_path: str
    row_count: int
    error: str | None = None


def _parse_period(cell_value: object) -> str | None:
    """Convert a cell value to a YYYY-MM period string.

    RVD Excel files use various date formats:
    - datetime objects (openpyxl parses numeric dates)
    - strings like "2024-01", "Jan-24", "2024/01"
    """
    if cell_value is None:
        return None

    import datetime  # local import to keep module-level imports minimal

    if isinstance(cell_value, (datetime.datetime, datetime.date)):
        return cell_value.strftime("%Y-%m")

    text = str(cell_value).strip()
    if not text or text in ("-", "N/A", ""):
        return None

    # YYYY-MM or YYYY/MM
    if len(text) == 7 and text[4] in ("-", "/"):
        return text[:4] + "-" + text[5:]

    # Mon-YY or Mon-YYYY
    for fmt in ("%b-%y", "%b-%Y", "%B-%Y", "%Y-%m-%d"):
        try:
            dt = datetime.datetime.strptime(text, fmt)
            return dt.strftime("%Y-%m")
        except ValueError:
            continue

    return None


def _try_float(val: object) -> float | None:
    """Safely convert a cell value to float."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        text = str(val).replace(",", "").strip()
        try:
            return float(text)
        except ValueError:
            return None


def _parse_workbook(
    wb: openpyxl.Workbook,
    description: str,
    source_url: str,
) -> list[RVDRecord]:
    """Extract records from a RVD Excel workbook.

    Scans for rows where column A looks like a period and subsequent
    columns contain numeric index values. Handles merged header rows
    by skipping non-parseable rows gracefully.
    """
    records: list[RVDRecord] = []
    metric_name = "rvd_price_index" if "price" in description else "rvd_rental_index"
    category = "property"
    unit = "index_1999_100"

    for sheet in wb.worksheets:
        rows = list(sheet.iter_rows(values_only=True))
        for row in rows:
            if not row:
                continue
            period = _parse_period(row[0])
            if period is None:
                continue
            # Take first numeric value in the row after period column
            for cell in row[1:]:
                val = _try_float(cell)
                if val is not None and val > 0:
                    records.append(
                        RVDRecord(
                            category=category,
                            metric=metric_name,
                            value=round(val, 2),
                            unit=unit,
                            period=period,
                            source="RVD",
                            source_url=source_url,
                        )
                    )
                    break  # one record per row

    return records


class RVDDownloader:
    """Downloads and parses RVD property data from Excel files."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._own_client = client is None

    async def __aenter__(self) -> RVDDownloader:
        if self._own_client:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(60.0, connect=15.0),
                follow_redirects=True,
            )
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._own_client and self._client is not None:
            await self._client.aclose()

    async def _download_excel(self, url: str, description: str) -> RVDResult:
        """Download one Excel file and parse it into RVDRecords."""
        assert self._client is not None
        filename = url.split("/")[-1]
        dest = _RAW_DIR / filename

        try:
            logger.info("Downloading RVD Excel: %s", url)
            resp = await self._client.get(url, timeout=60.0)
            resp.raise_for_status()

            _RAW_DIR.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)

            wb = openpyxl.load_workbook(io.BytesIO(resp.content), read_only=True, data_only=True)
            records = _parse_workbook(wb, description, url)

            if not records:
                logger.warning("RVD Excel parsed 0 records from %s", url)
                return RVDResult(
                    source_name=description,
                    records=(),
                    raw_file_path=str(dest),
                    row_count=0,
                    error="No records parsed from workbook",
                )

            logger.info("RVD %s: %d records parsed", description, len(records))
            return RVDResult(
                source_name=description,
                records=tuple(records),
                raw_file_path=str(dest),
                row_count=len(records),
            )

        except httpx.HTTPStatusError as exc:
            logger.warning("RVD HTTP %d for %s", exc.response.status_code, url)
            return RVDResult(
                source_name=description,
                records=(),
                raw_file_path=str(dest) if dest.exists() else "",
                row_count=0,
                error=f"HTTP {exc.response.status_code}",
            )
        except Exception as exc:
            logger.warning("RVD download/parse failed for %s: %s", url, exc)
            return RVDResult(
                source_name=description,
                records=(),
                raw_file_path="",
                row_count=0,
                error=str(exc),
            )

    async def download(self) -> list[RVDResult]:
        """Download all RVD Excel files. Returns fallback data if all fail.

        Returns:
            List of RVDResult — one per Excel file, plus a fallback result
            if no live data was obtained.
        """
        results: list[RVDResult] = []

        for url, description in _RVD_EXCEL_URLS:
            result = await self._download_excel(url, description)
            results.append(result)

        total_records = sum(r.row_count for r in results)

        if total_records == 0:
            logger.warning("All RVD downloads failed — no fallback available")

        return results


async def download_all_rvd(client: httpx.AsyncClient | None = None) -> list[RVDResult]:
    """Convenience function: download all RVD data.

    Args:
        client: Optional shared httpx.AsyncClient. Creates one if None.

    Returns:
        List of RVDResult.
    """
    async with RVDDownloader(client) as dl:
        return await dl.download()
