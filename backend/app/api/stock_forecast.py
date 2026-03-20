"""Stock & Index Forecast API router.

Endpoints (all prefixed /stock when mounted under /api):
  GET  /stock/tickers              — list all 14 registered tickers
  GET  /stock/summary              — MAPE/direction summary for all tickers
  GET  /stock/forecast             — 12-week forecast for one ticker
  GET  /stock/forecast/backtest    — walk-forward backtest for one ticker
  POST /stock/refresh              — re-download yfinance data (background task)

CRITICAL: Static routes declared BEFORE parameterized ones.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Query

from backend.app.models.response import APIResponse
from backend.app.models.stock_forecast import TickerInfo
from backend.app.services.stock_backtester import StockBacktester
from backend.app.services.stock_forecaster import StockForecaster
from backend.app.utils.logger import get_logger
from backend.data_pipeline.stock_downloader import TICKER_REGISTRY

logger = get_logger("api.stock_forecast")

router = APIRouter(prefix="/stock", tags=["stock"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_ticker_info(ticker: str) -> TickerInfo:
    meta = TICKER_REGISTRY[ticker]
    return TickerInfo(
        ticker=ticker,
        name=meta["name"],
        asset_type=meta["asset_type"],
        sector_tag=meta["sector_tag"],
        market=meta["market"],
    )


# ---------------------------------------------------------------------------
# GET /stock/tickers
# ---------------------------------------------------------------------------

@router.get("/tickers", response_model=APIResponse)
async def list_tickers(
    group: str | None = Query(None, description="Filter by asset_type e.g. hk_stock"),
) -> APIResponse:
    """Return all 14 registered tickers with metadata.

    Optional ?group=hk_stock|hk_index|us_stock|us_index filter.
    """
    try:
        infos = [_build_ticker_info(t) for t in TICKER_REGISTRY]
        if group:
            infos = [i for i in infos if i.asset_type == group]
        return APIResponse(
            success=True,
            data={"tickers": [i.to_dict() for i in infos], "count": len(infos)},
        )
    except Exception as exc:
        logger.exception("list_tickers failed")
        return APIResponse(success=False, error="Failed to list tickers")


# ---------------------------------------------------------------------------
# GET /stock/summary
# ---------------------------------------------------------------------------

@router.get("/summary", response_model=APIResponse)
async def get_summary(
    group: str | None = Query(None, description="Filter by asset_type"),
) -> APIResponse:
    """Return MAPE / directional accuracy summary for all tickers.

    Runs backtests concurrently with a semaphore of 4.
    Results include ticker, mape, directional_accuracy for each instrument.
    Failures are reported as null entries (non-fatal).
    """
    backtester = StockBacktester()
    semaphore = asyncio.Semaphore(4)

    tickers = list(TICKER_REGISTRY.keys())
    if group:
        tickers = [t for t in tickers if TICKER_REGISTRY[t]["asset_type"] == group]

    async def _safe_backtest(ticker: str) -> dict[str, Any]:
        async with semaphore:
            try:
                result = await backtester.run(ticker)
                return {
                    "ticker": ticker,
                    "name": TICKER_REGISTRY[ticker]["name"],
                    "asset_type": TICKER_REGISTRY[ticker]["asset_type"],
                    "mape": result.mape,
                    "directional_accuracy": result.directional_accuracy,
                    "rmse": result.rmse,
                    "n_obs": result.n_obs,
                    "error": None,
                }
            except Exception as exc:
                logger.warning("Summary backtest failed for %s: %s", ticker, exc)
                return {
                    "ticker": ticker,
                    "name": TICKER_REGISTRY[ticker]["name"],
                    "asset_type": TICKER_REGISTRY[ticker]["asset_type"],
                    "mape": None,
                    "directional_accuracy": None,
                    "rmse": None,
                    "n_obs": 0,
                    "error": "Backtest failed for ticker",
                }

    rows = await asyncio.gather(*[_safe_backtest(t) for t in tickers])
    return APIResponse(
        success=True,
        data={"summary": list(rows), "count": len(rows)},
    )


# ---------------------------------------------------------------------------
# GET /stock/forecast/backtest  (MUST be before /forecast)
# ---------------------------------------------------------------------------

@router.get("/forecast/backtest", response_model=APIResponse)
async def get_forecast_backtest(
    ticker: str = Query(..., description="Ticker symbol e.g. ^HSI or 0700.HK"),
    train_end: str = Query("2024-W40", description="Last training week YYYY-WNN"),
    horizon: int = Query(8, ge=1, le=52, description="Forecast horizon in weeks"),
) -> APIResponse:
    """Walk-forward backtest: train up to train_end, predict horizon weeks, compare actuals."""
    if ticker not in TICKER_REGISTRY:
        return APIResponse(success=False, error=f"Unknown ticker: {ticker}")

    try:
        backtester = StockBacktester()
        result = await backtester.run(ticker, train_end=train_end, horizon=horizon)
        return APIResponse(success=True, data=result.to_dict())
    except ValueError as exc:
        logger.warning("Backtest validation error for %s: %s", ticker, exc)
        return APIResponse(success=False, error="Backtest validation error")
    except Exception as exc:
        logger.exception("Backtest failed for %s", ticker)
        return APIResponse(success=False, error="Backtest failed")


# ---------------------------------------------------------------------------
# GET /stock/forecast
# ---------------------------------------------------------------------------

@router.get("/forecast", response_model=APIResponse)
async def get_forecast(
    ticker: str = Query(..., description="Ticker symbol e.g. ^HSI or 0700.HK"),
    horizon: int = Query(12, ge=1, le=52, description="Forecast horizon in weeks"),
    session_id: str | None = Query(None, description="Simulation session ID for signal overlay"),
) -> APIResponse:
    """12-week stock/index forecast, optionally adjusted by simulation signals.

    If session_id is provided, SimulationSignalExtractor overlays agent
    sentiment/behavioural signals on the ARIMA baseline.
    """
    if ticker not in TICKER_REGISTRY:
        return APIResponse(success=False, error=f"Unknown ticker: {ticker}")

    try:
        forecaster = StockForecaster()
        result = await forecaster.forecast(ticker, horizon=horizon, session_id=session_id)

        return APIResponse(
            success=True,
            data={
                "ticker": result.ticker,
                "name": result.name,
                "asset_type": result.asset_type,
                "horizon": result.horizon,
                "forecasts": [p.to_dict() for p in result.points],
                "model_used": result.model_used,
                "fit_quality": result.fit_quality,
                "data_quality": result.data_quality,
                "signal_shift": result.signal_shift,
                "signal_breakdown": [s.to_dict() for s in result.signal_breakdown],
                "session_id": result.session_id,
            },
        )
    except ValueError as exc:
        logger.warning("Forecast validation error for %s: %s", ticker, exc)
        return APIResponse(success=False, error="Forecast validation error")
    except Exception as exc:
        logger.exception("Forecast failed for %s", ticker)
        return APIResponse(success=False, error="Forecast failed")


# ---------------------------------------------------------------------------
# POST /stock/refresh  (background task — fire and forget)
# ---------------------------------------------------------------------------

async def _download_task() -> None:
    """Background task: re-download all tickers from yfinance."""
    logger.info("stock/refresh: background download started")
    try:
        from backend.data_pipeline.stock_downloader import download_all_stocks
        results = await download_all_stocks()
        total = sum(results.values())
        logger.info("stock/refresh: complete — %d rows upserted across %d tickers", total, len(results))
    except Exception as exc:
        logger.exception("stock/refresh background task failed: %s", exc)


@router.post("/refresh", response_model=APIResponse)
async def refresh_stock_data(background_tasks: BackgroundTasks) -> APIResponse:
    """Trigger a background re-download of all 14 tickers from yfinance.

    Returns immediately with 202-style accepted response.
    The actual download runs asynchronously.
    """
    try:
        background_tasks.add_task(_download_task)
        return APIResponse(
            success=True,
            data={
                "status": "accepted",
                "message": "Download started in background for all 14 tickers",
                "ticker_count": len(TICKER_REGISTRY),
            },
        )
    except Exception as exc:
        logger.exception("Failed to schedule stock refresh")
        return APIResponse(success=False, error="Failed to schedule stock refresh")
