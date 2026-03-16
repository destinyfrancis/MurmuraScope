import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

/**
 * List all available stock/index tickers with metadata.
 * Returns [{ ticker, name_zh, name_en, group, currency }]
 */
export function getStockTickers() {
  return api.get('/stock/tickers')
}

/**
 * Fetch 12-week (or custom horizon) forecast for a ticker.
 * Optionally overlay social signals from a completed simulation session.
 * @param {string} ticker - e.g. '0005.HK', 'SPY'
 * @param {number} horizon - forecast weeks (default 12)
 * @param {string|null} sessionId - simulation session_id for signal overlay
 */
export function getStockForecast(ticker, horizon = 12, sessionId = null) {
  const params = { ticker, horizon }
  if (sessionId) params.session_id = sessionId
  return api.get('/stock/forecast', { params })
}

/**
 * Walk-forward backtest for a ticker.
 * @param {string} ticker
 * @param {string} trainEnd - ISO week string e.g. '2024-W40'
 * @param {number} horizon - backtest horizon in weeks
 */
export function getStockBacktest(ticker, trainEnd = '2024-W40', horizon = 8) {
  return api.get('/stock/forecast/backtest', {
    params: { ticker, train_end: trainEnd, horizon },
  })
}

/**
 * Summary of all tickers — MAPE, direction accuracy, last price, trend.
 * @param {string|null} group - filter by group: 'hk_stock'|'hk_index'|'us_stock'|'us_index'
 */
export function getStockSummary(group = null) {
  const params = {}
  if (group) params.group = group
  return api.get('/stock/summary', { params })
}

/**
 * Trigger a background refresh of Yahoo Finance price data for all tickers.
 */
export function refreshStockData() {
  return api.post('/stock/refresh')
}
