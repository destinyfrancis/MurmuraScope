"""HK trade data downloader for Phase 5 B2B enterprise simulation.

Downloads import/export statistics from data.gov.hk CKAN API and HKSAR
Census and Statistics Department (C&SD) datasets.
Falls back to hardcoded 2024-Q1 estimates if API is unavailable.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

from backend.app.utils.logger import get_logger

logger = get_logger("data_pipeline.trade")

# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

_CKAN_BASE = "https://data.gov.hk/en/api/3/action"
_HKSAR_TRADE_RESOURCE_ID = "29cc1dca-af8c-4a37-a9fd-0e1cb83b58e0"  # HKSAR trade stats

# ---------------------------------------------------------------------------
# Immutable result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TradeRecord:
    """Immutable single trade metric record."""

    date: str  # YYYY-MM or YYYY-QN format
    category: str  # always "trade"
    metric: str  # e.g. "total_exports", "china_trade_pct"
    value: float
    unit: str  # "HKD_million", "pct", etc.
    source: str  # "data.gov.hk" or "fallback"


@dataclass(frozen=True)
class TradeDownloadResult:
    """Immutable result of a trade data download attempt."""

    records: tuple[TradeRecord, ...]
    row_count: int
    error: str | None


# NOTE: All hardcoded fallback data removed.
# If CKAN API is unavailable, empty results with error messages are returned.


# ---------------------------------------------------------------------------
# TradeDownloader
# ---------------------------------------------------------------------------


class TradeDownloader:
    """Download HK trade statistics from data.gov.hk or fall back to hardcoded data."""

    async def download_trade_summary(
        self,
        client: httpx.AsyncClient,
    ) -> TradeDownloadResult:
        """Download quarterly trade totals and partner breakdown.

        Tries the data.gov.hk CKAN API first; falls back to hardcoded 2024 data
        if the API is unreachable or returns an error.

        Args:
            client: Shared httpx async client.

        Returns:
            ``TradeDownloadResult`` with trade summary records.
        """
        try:
            records = await self._fetch_from_api(client)
            if records:
                return TradeDownloadResult(
                    records=tuple(records),
                    row_count=len(records),
                    error=None,
                )
        except Exception as exc:
            logger.warning("Trade API fetch failed: %s — no fallback", exc)

        logger.warning("Trade summary: no data available — no fallback")
        return TradeDownloadResult(
            records=(),
            row_count=0,
            error="Trade API unavailable",
        )

    async def download_import_categories(
        self,
        client: httpx.AsyncClient,
    ) -> TradeDownloadResult:
        """Download import composition by commodity category.

        Currently no live API source — returns empty result.
        """
        logger.info("Import categories: no live API source available")
        return TradeDownloadResult(records=(), row_count=0, error="No live API for import categories")

    async def download_export_categories(
        self,
        client: httpx.AsyncClient,
    ) -> TradeDownloadResult:
        """Download export composition by commodity category.

        Currently no live API source — returns empty result.
        """
        logger.info("Export categories: no live API source available")
        return TradeDownloadResult(records=(), row_count=0, error="No live API for export categories")

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    async def _fetch_from_api(
        self,
        client: httpx.AsyncClient,
    ) -> list[TradeRecord]:
        """Attempt to fetch trade data from data.gov.hk CKAN API."""
        url = f"{_CKAN_BASE}/datastore_search"
        params = {
            "resource_id": _HKSAR_TRADE_RESOURCE_ID,
            "limit": 100,
        }
        response = await client.get(url, params=params, timeout=15.0)
        response.raise_for_status()

        data = response.json()
        if not data.get("success"):
            raise ValueError(f"CKAN API returned success=false: {data.get('error')}")

        api_records = data.get("result", {}).get("records", [])
        if not api_records:
            raise ValueError("CKAN API returned empty records list")

        records: list[TradeRecord] = []
        for row in api_records:
            date_str = str(row.get("period", row.get("date", "2024-Q1")))
            exports_val = _safe_float(row.get("total_exports") or row.get("exports", 0))
            imports_val = _safe_float(row.get("total_imports") or row.get("imports", 0))

            if exports_val:
                records.append(
                    TradeRecord(
                        date=date_str,
                        category="trade",
                        metric="total_exports",
                        value=exports_val,
                        unit="HKD_million",
                        source="data.gov.hk",
                    )
                )
            if imports_val:
                records.append(
                    TradeRecord(
                        date=date_str,
                        category="trade",
                        metric="total_imports",
                        value=imports_val,
                        unit="HKD_million",
                        source="data.gov.hk",
                    )
                )

        logger.info("Fetched %d trade records from data.gov.hk API", len(records))
        return records


# ---------------------------------------------------------------------------
# Module-level convenience function (matches pattern of other downloaders)
# ---------------------------------------------------------------------------


async def download_all_trade(
    client: httpx.AsyncClient,
) -> list[TradeDownloadResult]:
    """Download all HK trade datasets.

    Returns:
        List of TradeDownloadResult (one per dataset: summary, imports, exports).
    """
    downloader = TradeDownloader()
    results = await asyncio.gather(
        downloader.download_trade_summary(client),
        downloader.download_import_categories(client),
        downloader.download_export_categories(client),
        return_exceptions=True,
    )

    output: list[TradeDownloadResult] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error("Trade download task %d failed: %s", i, result)
            output.append(TradeDownloadResult(records=(), row_count=0, error=str(result)))
        else:
            output.append(result)  # type: ignore[arg-type]

    total = sum(r.row_count for r in output)
    logger.info("Trade download complete: %d records across %d datasets", total, len(output))
    return output


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_float(value: object) -> float:
    """Safely convert *value* to float, return 0.0 on failure."""
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
