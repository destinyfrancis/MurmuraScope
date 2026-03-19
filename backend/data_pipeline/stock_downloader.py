"""Weekly stock & index downloader using yfinance.

Downloads OHLCV data for 14 HK/US tickers, resamples to weekly (W-FRI),
and upserts into the market_data table with granularity='weekly'.
"""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import datetime
from typing import Any

from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("stock_downloader")

# ---------------------------------------------------------------------------
# Ticker registry — 14 tracked instruments
# ---------------------------------------------------------------------------

TICKER_REGISTRY: dict[str, dict[str, str]] = {
    "0700.HK": {"name": "騰訊", "asset_type": "hk_stock", "sector_tag": "tech", "market": "HK"},
    "0005.HK": {"name": "滙豐銀行", "asset_type": "hk_stock", "sector_tag": "banking", "market": "HK"},
    "0941.HK": {"name": "中國移動", "asset_type": "hk_stock", "sector_tag": "telco", "market": "HK"},
    "2318.HK": {"name": "中國平安", "asset_type": "hk_stock", "sector_tag": "insurance", "market": "HK"},
    "1299.HK": {"name": "友邦保險", "asset_type": "hk_stock", "sector_tag": "insurance", "market": "HK"},
    "^HSI": {"name": "恒生指數", "asset_type": "hk_index", "sector_tag": "broad", "market": "HK"},
    "^HSFI": {"name": "恒生金融分類指數", "asset_type": "hk_index", "sector_tag": "financial", "market": "HK"},
    "^HSNPI": {"name": "恒生地產分類指數", "asset_type": "hk_index", "sector_tag": "property", "market": "HK"},
    "^HSTI": {"name": "恒生科技指數", "asset_type": "hk_index", "sector_tag": "tech", "market": "HK"},
    "NVDA": {"name": "英偉達", "asset_type": "us_stock", "sector_tag": "tech", "market": "US"},
    "AAPL": {"name": "蘋果", "asset_type": "us_stock", "sector_tag": "tech", "market": "US"},
    "BABA": {"name": "阿里巴巴", "asset_type": "us_stock", "sector_tag": "china_tech", "market": "US"},
    "^GSPC": {"name": "標普500", "asset_type": "us_index", "sector_tag": "broad", "market": "US"},
    "^IXIC": {"name": "納斯達克", "asset_type": "us_index", "sector_tag": "tech", "market": "US"},
}


@dataclasses.dataclass(frozen=True)
class WeeklyRecord:
    """One weekly OHLCV bar for a ticker."""

    ticker: str
    week_label: str  # "YYYY-WNN"
    open: float
    high: float
    low: float
    close: float
    volume: float


def _week_label_from_date(dt: Any) -> str:
    """Convert a pandas Timestamp / datetime to 'YYYY-WNN' format."""
    if hasattr(dt, "to_pydatetime"):
        dt = dt.to_pydatetime()
    if hasattr(dt, "isocalendar"):
        iso = dt.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    # fallback: parse from string representation
    parsed = datetime.fromisoformat(str(dt)[:10])
    iso = parsed.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _download_weekly_sync(ticker: str, start_year: int) -> list[WeeklyRecord]:
    """Synchronous yfinance download + weekly resample.

    Called via asyncio.to_thread to avoid blocking the event loop.
    """
    try:
        import yfinance as yf  # type: ignore[import]
    except ImportError as exc:
        raise ImportError("yfinance is required for stock_downloader") from exc

    start = f"{start_year}-01-01"
    logger.info("Downloading %s from %s (daily → weekly resample)", ticker, start)

    try:
        # Use Ticker().history() instead of yf.download() to avoid MultiIndex
        # columns introduced in yfinance 2.x when downloading a single ticker.
        ticker_obj = yf.Ticker(ticker)
        raw = ticker_obj.history(start=start, auto_adjust=True, raise_errors=False)
    except Exception as exc:
        logger.warning("yfinance download failed for %s: %s", ticker, exc)
        return []

    if raw is None or raw.empty:
        logger.warning("No data returned by yfinance for %s", ticker)
        return []

    # Normalise column names — Ticker.history() returns flat columns
    # ('Open', 'High', 'Low', 'Close', 'Volume') but may include extras.
    if hasattr(raw.columns, "levels"):
        # Defensive: flatten MultiIndex if somehow returned
        raw.columns = raw.columns.get_level_values(0)

    # Keep only the five OHLCV columns we need
    available = set(raw.columns)
    needed = {"Open", "High", "Low", "Close", "Volume"}
    missing = needed - available
    if missing:
        logger.warning("Missing columns %s for ticker %s — skipping", missing, ticker)
        return []
    raw = raw[list(needed)]

    try:
        weekly = raw.resample("W-FRI").agg(
            {
                "Open": "first",
                "High": "max",
                "Low": "min",
                "Close": "last",
                "Volume": "sum",
            }
        ).dropna(subset=["Close"])
    except Exception as exc:
        logger.warning("Resample failed for %s: %s", ticker, exc)
        return []

    records: list[WeeklyRecord] = []
    for idx, row in weekly.iterrows():
        try:
            wl = _week_label_from_date(idx)
            rec = WeeklyRecord(
                ticker=ticker,
                week_label=wl,
                open=float(row.get("Open", 0.0) or 0.0),
                high=float(row.get("High", 0.0) or 0.0),
                low=float(row.get("Low", 0.0) or 0.0),
                close=float(row.get("Close", 0.0) or 0.0),
                volume=float(row.get("Volume", 0.0) or 0.0),
            )
            if rec.close > 0:
                records.append(rec)
        except Exception as exc:
            logger.debug("Skipping row for %s at %s: %s", ticker, idx, exc)

    logger.info("Downloaded %d weekly bars for %s", len(records), ticker)
    return records


async def download_stock_weekly(ticker: str, start_year: int = 2019) -> list[WeeklyRecord]:
    """Async wrapper: downloads weekly OHLCV for one ticker via yfinance.

    Uses asyncio.to_thread because yfinance is synchronous.
    """
    return await asyncio.to_thread(_download_weekly_sync, ticker, start_year)


async def upsert_weekly_records(records: list[WeeklyRecord]) -> int:
    """INSERT OR REPLACE weekly records into market_data with granularity='weekly'.

    Returns number of rows inserted/replaced.
    """
    if not records:
        return 0

    inserted = 0
    async with get_db() as db:
        # Ensure the granularity column exists (may have been added by migration)
        try:
            await db.execute(
                "ALTER TABLE market_data ADD COLUMN granularity TEXT DEFAULT 'daily'"
            )
            await db.commit()
        except Exception:
            pass  # Column already exists

        for rec in records:
            try:
                meta = TICKER_REGISTRY.get(rec.ticker, {})
                asset_type = meta.get("asset_type", "hk_stock")
                cursor = await db.execute(
                    """INSERT OR REPLACE INTO market_data
                       (date, asset_type, ticker, open, close, high, low, volume, source, granularity)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        rec.week_label,
                        asset_type,
                        rec.ticker,
                        rec.open,
                        rec.close,
                        rec.high,
                        rec.low,
                        rec.volume,
                        "yfinance_weekly",
                        "weekly",
                    ),
                )
                if cursor.rowcount > 0:
                    inserted += 1
            except Exception as exc:
                logger.warning(
                    "Failed to upsert weekly record %s/%s: %s",
                    rec.ticker,
                    rec.week_label,
                    exc,
                )
        await db.commit()

    logger.info("upsert_weekly_records: %d rows inserted/replaced", inserted)
    return inserted


async def download_all_stocks() -> dict[str, int]:
    """Download all 14 tickers concurrently (max 3 simultaneous) and upsert.

    Returns a mapping of ticker → rows upserted.
    """
    semaphore = asyncio.Semaphore(3)
    results: dict[str, int] = {}

    async def _fetch_and_upsert(ticker: str) -> tuple[str, int]:
        async with semaphore:
            try:
                records = await download_stock_weekly(ticker)
                count = await upsert_weekly_records(records)
                return ticker, count
            except Exception as exc:
                logger.warning("download_all_stocks: %s failed: %s", ticker, exc)
                return ticker, 0

    tasks = [_fetch_and_upsert(t) for t in TICKER_REGISTRY]
    done = await asyncio.gather(*tasks, return_exceptions=False)
    for ticker, count in done:
        results[ticker] = count

    total = sum(results.values())
    logger.info(
        "download_all_stocks complete: %d tickers, %d total rows", len(results), total
    )
    return results
