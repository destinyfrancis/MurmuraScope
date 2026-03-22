import axios, { type AxiosResponse } from 'axios'
import type { APIResponse, PredictionContract, TradingSignal } from './types'

const api = axios.create({ baseURL: '/api' })

/**
 * List active Polymarket contracts, optionally filtered by category.
 * @param category - e.g. 'crypto', 'politics', 'economics'
 * @param limit
 */
export function getContracts(
  category: string | null = null,
  limit: number = 20,
): Promise<AxiosResponse<APIResponse<PredictionContract[]>>> {
  const params: Record<string, any> = { limit }
  if (category) params.category = category
  return api.get('/prediction-market/contracts', { params })
}

/**
 * Keyword search across active Polymarket contracts.
 * @param query
 * @param limit
 */
export function searchContracts(
  query: string,
  limit: number = 10,
): Promise<AxiosResponse<APIResponse<PredictionContract[]>>> {
  return api.get('/prediction-market/contracts/search', { params: { q: query, limit } })
}

/**
 * Match session seed topics to Polymarket contracts.
 * @param sessionId
 * @param limit
 */
export function getMatchedContracts(
  sessionId: string,
  limit: number = 10,
): Promise<AxiosResponse<APIResponse<PredictionContract[]>>> {
  return api.get('/prediction-market/contracts/matched', {
    params: { session_id: sessionId, limit },
  })
}

/**
 * Generate trading signals for a session.
 * Returns array of TradingSignal objects with direction, alpha, confidence, reasoning.
 * @param sessionId
 * @param limit
 */
export function getTradingSignals(
  sessionId: string,
  limit: number = 10,
): Promise<AxiosResponse<APIResponse<TradingSignal[]>>> {
  return api.get('/prediction-market/signals', { params: { session_id: sessionId, limit } })
}

/**
 * Retrieve persisted trading signal history from DB.
 * @param sessionId
 * @param limit
 */
export function getSignalHistory(
  sessionId: string,
  limit: number = 20,
): Promise<AxiosResponse<APIResponse<TradingSignal[]>>> {
  return api.get('/prediction-market/signals/history', {
    params: { session_id: sessionId, limit },
  })
}
