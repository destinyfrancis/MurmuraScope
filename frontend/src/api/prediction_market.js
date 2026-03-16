import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

/**
 * List active Polymarket contracts, optionally filtered by category.
 * @param {string} [category] - e.g. 'crypto', 'politics', 'economics'
 * @param {number} [limit=20]
 */
export function getContracts(category = null, limit = 20) {
  const params = { limit }
  if (category) params.category = category
  return api.get('/prediction-market/contracts', { params })
}

/**
 * Keyword search across active Polymarket contracts.
 * @param {string} query
 * @param {number} [limit=10]
 */
export function searchContracts(query, limit = 10) {
  return api.get('/prediction-market/contracts/search', { params: { q: query, limit } })
}

/**
 * Match session seed topics to Polymarket contracts.
 * @param {string} sessionId
 * @param {number} [limit=10]
 */
export function getMatchedContracts(sessionId, limit = 10) {
  return api.get('/prediction-market/contracts/matched', { params: { session_id: sessionId, limit } })
}

/**
 * Generate trading signals for a session.
 * Returns array of TradingSignal objects with direction, alpha, confidence, reasoning.
 * @param {string} sessionId
 * @param {number} [limit=10]
 */
export function getTradingSignals(sessionId, limit = 10) {
  return api.get('/prediction-market/signals', { params: { session_id: sessionId, limit } })
}

/**
 * Retrieve persisted trading signal history from DB.
 * @param {string} sessionId
 * @param {number} [limit=20]
 */
export function getSignalHistory(sessionId, limit = 20) {
  return api.get('/prediction-market/signals/history', { params: { session_id: sessionId, limit } })
}
