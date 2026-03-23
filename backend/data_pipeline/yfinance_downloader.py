"""Yahoo Finance downloader for HSI and HK sector indices.

Replaces hardcoded HSI data with real Yahoo Finance historical data.
Aggregates daily OHLCV to quarterly close (last trading day per quarter).
Compatible with both ``hk_data_snapshots`` and ``market_data`` tables.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from backend.app.utils.logger import get_logger

logger = get_logger("data_pipeline.yfinance")

# ---------------------------------------------------------------------------
# Tickers
# ---------------------------------------------------------------------------

_HSI_TICKER = "^HSI"
_SECTOR_TICKERS: dict[str, str] = {
    "^HSFI": "HSI_Financial",
    "^HSNPI": "HSI_Properties",
    "^HSTI": "HSI_Tech",
}

# ---------------------------------------------------------------------------
# Immutable result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class YFinanceRecord:
    """Immutable single Yahoo Finance OHLCV record."""

    date: str  # YYYY-QN for quarterly, YYYY-MM-DD for daily
    ticker: str  # e.g. "HSI", "HSI_Financial"
    open: float | None
    close: float | None
    high: float | None
    low: float | None
    volume: float | None
    source: str  # always "yahoo_finance"


@dataclass(frozen=True)
class DownloadResult:
    """Immutable result of a yfinance download run."""

    category: str  # always "finance"
    row_count: int
    records: tuple[YFinanceRecord, ...]
    error: str | None


# ---------------------------------------------------------------------------
# Quarter helpers
# ---------------------------------------------------------------------------


def _quarter_label(dt: datetime) -> str:
    """Convert a datetime to YYYY-QN format.

    Args:
        dt: A datetime object.

    Returns:
        String like '2024-Q3'.
    """
    quarter = (dt.month - 1) // 3 + 1
    return f"{dt.year}-Q{quarter}"


def _aggregate_quarterly(df: pd.DataFrame, ticker_label: str) -> list[YFinanceRecord]:
    """Aggregate daily OHLCV data to quarterly records using last trading day.

    Args:
        df: DataFrame with columns Open, High, Low, Close, Volume and a
            DatetimeIndex.
        ticker_label: Human-readable ticker name for the record.

    Returns:
        List of quarterly YFinanceRecord objects.
    """
    if df.empty:
        return []

    records: list[YFinanceRecord] = []

    # Group by year-quarter, take last trading day for close/open,
    # quarter high/low, and sum volume.
    quarterly = (
        df.resample("QE")
        .agg(
            {
                "Open": "first",
                "High": "max",
                "Low": "min",
                "Close": "last",
                "Volume": "sum",
            }
        )
        .dropna(subset=["Close"])
    )

    for idx, row in quarterly.iterrows():
        period_end: datetime = idx.to_pydatetime()  # type: ignore[union-attr]
        label = _quarter_label(period_end)

        records.append(
            YFinanceRecord(
                date=label,
                ticker=ticker_label,
                open=round(float(row["Open"]), 2) if pd.notna(row["Open"]) else None,
                close=round(float(row["Close"]), 2),
                high=round(float(row["High"]), 2) if pd.notna(row["High"]) else None,
                low=round(float(row["Low"]), 2) if pd.notna(row["Low"]) else None,
                volume=round(float(row["Volume"]), 0) if pd.notna(row["Volume"]) else None,
                source="yahoo_finance",
            )
        )

    return records


# ---------------------------------------------------------------------------
# Sync download wrappers (yfinance is synchronous)
# ---------------------------------------------------------------------------


def _download_ticker_sync(
    ticker: str,
    start_year: int,
    end_date: str | None = None,
) -> pd.DataFrame:
    """Download daily OHLCV for a single ticker via yfinance (synchronous).

    Args:
        ticker: Yahoo Finance ticker symbol (e.g. '^HSI').
        start_year: Start year for historical data.
        end_date: Optional end date in 'YYYY-MM-DD' format. Defaults to today.

    Returns:
        DataFrame with columns Open, High, Low, Close, Volume.
        Returns empty DataFrame on failure.
    """
    try:
        import yfinance as yf  # noqa: E402
    except ImportError:
        logger.error("yfinance not installed. Run: pip install yfinance>=0.2.36")
        return pd.DataFrame()

    start = f"{start_year}-01-01"
    end = end_date or datetime.now().strftime("%Y-%m-%d")

    try:
        ticker_obj = yf.Ticker(ticker)
        df = ticker_obj.history(start=start, end=end, auto_adjust=True)

        if df.empty:
            logger.warning("No data returned for ticker %s (%s to %s)", ticker, start, end)
            return pd.DataFrame()

        # Ensure expected columns exist
        expected = {"Open", "High", "Low", "Close", "Volume"}
        missing = expected - set(df.columns)
        if missing:
            logger.warning("Missing columns %s for ticker %s", missing, ticker)
            return pd.DataFrame()

        logger.info(
            "Downloaded %d daily records for %s (%s to %s)",
            len(df),
            ticker,
            df.index.min().date(),
            df.index.max().date(),
        )
        return df[list(expected)]

    except Exception as exc:
        logger.warning("Failed to download %s: %s", ticker, exc)
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Async public API
# ---------------------------------------------------------------------------


async def download_tickers(
    tickers: list[str],
    period: str = "5y",
) -> list[YFinanceRecord]:
    """Download daily OHLCV for an arbitrary list of tickers via yfinance.

    Generic entry point for domain-pack DataSourceSpec dispatching.  Runs
    each ticker download concurrently on the default thread pool and returns
    a flat list of daily YFinanceRecord objects (not aggregated to quarterly).

    Args:
        tickers: Yahoo Finance ticker symbols (e.g. ['^HSI', 'AAPL']).
        period: yfinance period string (default '5y').

    Returns:
        Flat list of YFinanceRecord objects across all tickers.
    """
    try:
        import yfinance as yf  # noqa: E402
    except ImportError:
        logger.error("yfinance not installed. Run: pip install yfinance>=0.2.36")
        return []

    all_records: list[YFinanceRecord] = []

    def _fetch_one(ticker: str) -> list[YFinanceRecord]:
        try:
            df = yf.Ticker(ticker).history(period=period, auto_adjust=True)
            if df.empty:
                return []
            records: list[YFinanceRecord] = []
            for idx, row in df.iterrows():
                records.append(
                    YFinanceRecord(
                        date=str(idx.date()),
                        ticker=ticker,
                        open=round(float(row["Open"]), 4) if "Open" in row and pd.notna(row["Open"]) else None,
                        close=round(float(row["Close"]), 4) if "Close" in row and pd.notna(row["Close"]) else None,
                        high=round(float(row["High"]), 4) if "High" in row and pd.notna(row["High"]) else None,
                        low=round(float(row["Low"]), 4) if "Low" in row and pd.notna(row["Low"]) else None,
                        volume=round(float(row["Volume"]), 0) if "Volume" in row and pd.notna(row["Volume"]) else None,
                        source="yahoo_finance",
                    )
                )
            return records
        except Exception as exc:
            logger.warning("download_tickers: failed for %s: %s", ticker, exc)
            return []

    import asyncio

    tasks = [asyncio.to_thread(_fetch_one, t) for t in tickers]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.warning("download_tickers: exception for %s: %s", tickers[i], result)
        else:
            all_records.extend(result)  # type: ignore[arg-type]

    logger.info("download_tickers: %d records across %d tickers", len(all_records), len(tickers))
    return all_records


async def download_hsi_quarterly(
    start_year: int = 1993,
) -> DownloadResult:
    """Download Hang Seng Index daily data and aggregate to quarterly close.

    Uses the last trading day per quarter for the close price, quarter
    high/low, first day open, and summed volume.

    Args:
        start_year: Year to start downloading from (default 1993, HSI inception).

    Returns:
        DownloadResult with quarterly HSI records. Empty on failure.
    """
    try:
        df = await asyncio.to_thread(_download_ticker_sync, _HSI_TICKER, start_year)
    except Exception as exc:
        msg = f"HSI download failed: {exc}"
        logger.warning(msg)
        return DownloadResult(category="finance", row_count=0, records=(), error=msg)

    if df.empty:
        msg = f"No HSI data returned for start_year={start_year}"
        logger.warning(msg)
        return DownloadResult(category="finance", row_count=0, records=(), error=msg)

    records = _aggregate_quarterly(df, "HSI")
    logger.info("HSI quarterly aggregation: %d quarters", len(records))

    return DownloadResult(
        category="finance",
        row_count=len(records),
        records=tuple(records),
        error=None,
    )


async def download_sector_indices(
    start_year: int = 2005,
) -> DownloadResult:
    """Download HK sector indices and aggregate to quarterly close.

    Tickers: ^HSFI (Financial), ^HSNPI (Properties), ^HSTI (Tech).

    Args:
        start_year: Year to start downloading from (default 2005).

    Returns:
        DownloadResult with quarterly sector index records. Empty on failure.
    """
    all_records: list[YFinanceRecord] = []
    errors: list[str] = []

    for ticker, label in _SECTOR_TICKERS.items():
        try:
            df = await asyncio.to_thread(_download_ticker_sync, ticker, start_year)
        except Exception as exc:
            msg = f"{ticker} download failed: {exc}"
            logger.warning(msg)
            errors.append(msg)
            continue

        if df.empty:
            msg = f"No data returned for {ticker}"
            logger.warning(msg)
            errors.append(msg)
            continue

        records = _aggregate_quarterly(df, label)
        all_records.extend(records)
        logger.info("%s quarterly aggregation: %d quarters", label, len(records))

    error_msg = "; ".join(errors) if errors else None
    return DownloadResult(
        category="finance",
        row_count=len(all_records),
        records=tuple(all_records),
        error=error_msg,
    )


async def download_all_yfinance(
    hsi_start_year: int = 1993,
    sector_start_year: int = 2005,
) -> list[DownloadResult]:
    """Download all Yahoo Finance datasets: HSI + sector indices.

    Orchestrates parallel downloads of the Hang Seng Index and three
    sector sub-indices, returning one DownloadResult per dataset.

    Args:
        hsi_start_year: Start year for HSI data (default 1993).
        sector_start_year: Start year for sector indices (default 2005).

    Returns:
        List of DownloadResult objects (one for HSI, one for sectors).
    """
    results = await asyncio.gather(
        download_hsi_quarterly(start_year=hsi_start_year),
        download_sector_indices(start_year=sector_start_year),
        return_exceptions=True,
    )

    output: list[DownloadResult] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            label = "HSI" if i == 0 else "sector_indices"
            logger.error("yfinance download task %s failed: %s", label, result)
            output.append(
                DownloadResult(
                    category="finance",
                    row_count=0,
                    records=(),
                    error=str(result),
                )
            )
        else:
            output.append(result)  # type: ignore[arg-type]

    total = sum(r.row_count for r in output)
    logger.info(
        "yfinance download complete: %d records across %d datasets",
        total,
        len(output),
    )
    return output
