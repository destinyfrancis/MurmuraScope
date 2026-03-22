import axios, { type AxiosResponse } from 'axios'
import type {
  APIResponse,
  StockBacktest,
  StockForecast,
  StockGroup,
  StockSummaryItem,
  StockTicker,
} from './types'

const api = axios.create({ baseURL: '/api' })

/**
 * List all available stock/index tickers with metadata.
 * Returns [{ ticker, name_zh, name_en, group, currency }]
 */
export function getStockTickers(): Promise<AxiosResponse<APIResponse<StockTicker[]>>> {
  return api.get('/stock/tickers')
}

/**
 * Fetch 12-week (or custom horizon) forecast for a ticker.
 * Optionally overlay social signals from a completed simulation session.
 * @param ticker - e.g. '0005.HK', 'SPY'
 * @param horizon - forecast weeks (default 12)
 * @param sessionId - simulation session_id for signal overlay
 */
export function getStockForecast(
  ticker: string,
  horizon: number = 12,
  sessionId: string | null = null,
): Promise<AxiosResponse<APIResponse<StockForecast>>> {
  const params: Record<string, any> = { ticker, horizon }
  if (sessionId) params.session_id = sessionId
  return api.get('/stock/forecast', { params })
}

/**
 * Walk-forward backtest for a ticker.
 * @param ticker
 * @param trainEnd - ISO week string e.g. '2024-W40'
 * @param horizon - backtest horizon in weeks
 */
export function getStockBacktest(
  ticker: string,
  trainEnd: string = '2024-W40',
  horizon: number = 8,
): Promise<AxiosResponse<APIResponse<StockBacktest>>> {
  return api.get('/stock/forecast/backtest', {
    params: { ticker, train_end: trainEnd, horizon },
  })
}

/**
 * Summary of all tickers — MAPE, direction accuracy, last price, trend.
 * @param group - filter by group: 'hk_stock'|'hk_index'|'us_stock'|'us_index'
 */
export function getStockSummary(
  group: StockGroup | null = null,
): Promise<AxiosResponse<APIResponse<StockSummaryItem[]>>> {
  const params: Record<string, any> = {}
  if (group) params.group = group
  return api.get('/stock/summary', { params })
}

/**
 * Trigger a background refresh of Yahoo Finance price data for all tickers.
 */
export function refreshStockData(): Promise<AxiosResponse<APIResponse<{ refreshed: boolean }>>> {
  return api.post('/stock/refresh')
}
