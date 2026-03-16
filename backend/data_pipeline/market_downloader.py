"""HKEX / HKMA market data downloader (exchange rates only).

HSI data is now provided by yfinance_downloader.py.
Exchange rates are fetched from HKMA API — no hardcoded fallback.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from backend.app.utils.logger import get_logger

logger = get_logger("data_pipeline.market")

_HKMA_BASE = "https://api.hkma.gov.hk/public/market-data-and-statistics"


@dataclass(frozen=True)
class MarketRecord:
    """Immutable market data record."""

    date: str
    asset_type: str
    ticker: str
    open: float | None
    close: float | None
    high: float | None
    low: float | None
    volume: float | None
    source: str


@dataclass(frozen=True)
class MarketDownloadResult:
    """Immutable result of a market data download run."""

    records: tuple[MarketRecord, ...]
    row_count: int
    error: str | None


async def download_exchange_rates(
    client: httpx.AsyncClient,
) -> MarketDownloadResult:
    """Download HKMA USD/HKD exchange rate data.

    Returns empty result with error message if API is unavailable.
    No hardcoded fallback.
    """
    records: list[MarketRecord] = []

    try:
        url = f"{_HKMA_BASE}/foreign-exchange/hkd-usd"
        resp = await client.get(url, timeout=15.0)
        if resp.status_code == 200:
            data = resp.json()
            result_list = data.get("result", {}).get("dataSet", [])
            for item in result_list[:120]:  # Up to 10 years monthly
                records.append(MarketRecord(
                    date=str(item.get("end_of_period", "")),
                    asset_type="fx",
                    ticker="USD/HKD",
                    open=None,
                    close=float(item.get("hkd_usd_spot_rate", 0)),
                    high=None,
                    low=None,
                    volume=None,
                    source="hkma",
                ))
    except Exception:
        logger.warning("HKMA FX API failed — no fallback available")

    if not records:
        logger.warning("No FX data from HKMA API")
        return MarketDownloadResult(records=(), row_count=0, error="HKMA FX API unavailable")

    return MarketDownloadResult(
        records=tuple(records),
        row_count=len(records),
        error=None,
    )


async def download_all_market(
    client: httpx.AsyncClient,
) -> list[MarketDownloadResult]:
    """Download market data: exchange rates from HKMA.

    HSI data is handled by yfinance_downloader separately.

    Returns:
        List of MarketDownloadResult.
    """
    results: list[MarketDownloadResult] = []

    fx_result = await download_exchange_rates(client)
    results.append(fx_result)
    logger.info("FX data: %d records (error=%s)", fx_result.row_count, fx_result.error)

    return results
