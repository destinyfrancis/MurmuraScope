import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

/**
 * Create a new simulation session.
 * @param {Object} data - Simulation config including optional domain_pack_id (default: 'hk_city')
 */
export function createSimulation(data) {
  const payload = { domain_pack_id: 'hk_city', ...data }
  return api.post('/simulation/create', payload)
}

export function startSimulation(data) {
  return api.post('/simulation/start', data)
}

export function getSession(sessionId) {
  return api.get(`/simulation/${sessionId}`)
}

export function getSessionStatus(sessionId) {
  return api.get(`/simulation/${sessionId}/status`)
}

export function injectShock(sessionId, shock) {
  return api.post(`/simulation/${sessionId}/shock`, shock)
}

export function connectWebSocket(sessionId) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  return new WebSocket(`${protocol}//${host}/api/ws/progress/${sessionId}`)
}

export function getSessionAgents(sessionId) {
  return api.get(`/simulation/${sessionId}/agents`)
}

export function suggestConfig(data) {
  return api.post('/simulation/suggest-config', data)
}

export function createBranch(sessionId, options = {}) {
  return api.post(`/simulation/${sessionId}/branch`, options)
}

export function listBranches(sessionId) {
  return api.get(`/simulation/${sessionId}/branches`)
}

export function compareSessions(sessionA, sessionB) {
  return api.get(`/simulation/compare/${sessionA}/${sessionB}`)
}

export function getSessionActions(sessionId, params = {}) {
  return api.get(`/simulation/${sessionId}/actions`, { params })
}

export function getSentimentSummary(sessionId) {
  return api.get(`/simulation/${sessionId}/actions/sentiment`)
}

export function getAgentMemories(sessionId, agentId, params = {}) {
  return api.get(`/simulation/${sessionId}/agents/${agentId}/memories`, { params })
}

export function searchAgentMemories(sessionId, agentId, query, topK = 10) {
  return api.get(`/simulation/${sessionId}/agents/${agentId}/memories/search`, {
    params: { q: query, top_k: topK },
  })
}

export function getAgentTriples(sessionId, agentId, params = {}) {
  return api.get(`/simulation/${sessionId}/agents/${agentId}/memories`, { params })
    .then(res => {
      const data = res.data?.data || {}
      return { data: { data: data.triples || [] } }
    })
}

export function getMacroHistory(sessionId, roundNumber = null) {
  const params = roundNumber !== null ? { round_number: roundNumber } : {}
  return api.get(`/simulation/${sessionId}/macro-history`, { params })
}

export function getEchoChambers(sessionId, roundNumber = null) {
  const params = roundNumber !== null ? { round_number: roundNumber } : {}
  return api.get(`/simulation/${sessionId}/echo-chambers`, { params })
}

export function getContagionData(sessionId) {
  return api.get(`/simulation/${sessionId}/contagion`)
}

export function getCommunitySummaries(sessionId, roundNumber = null) {
  const params = roundNumber !== null ? { round_number: roundNumber } : {}
  return api.get(`/simulation/${sessionId}/community-summaries`, { params })
}

export function getTripleConflicts(sessionId, minAgents = 3) {
  return api.get(`/simulation/${sessionId}/triple-conflicts`, { params: { min_agents: minAgents } })
}

export function getPolarization(sessionId, roundNumber = null) {
  const params = roundNumber !== null ? { round_number: roundNumber } : {}
  return api.get(`/simulation/${sessionId}/polarization`, { params })
}

export function listSessions(limit = 20, offset = 0) {
  return api.get('/simulation/sessions', { params: { limit, offset } })
}

// ── Network Evolution ──────────────────────────────────────────────────────────

export function getNetworkEvents(sessionId, params = {}) {
  return api.get(`/simulation/${sessionId}/network-events`, { params })
}

// ── Feed & Bubble ──────────────────────────────────────────────────────────────

export function getAgentFeed(sessionId, agentId) {
  return api.get(`/simulation/${sessionId}/feed/${agentId}`)
}

export function getFilterBubble(sessionId) {
  return api.get(`/simulation/${sessionId}/filter-bubble`)
}

export function getFilterBubbleHistory(sessionId) {
  return api.get(`/simulation/${sessionId}/filter-bubble-history`)
}

export function getViralPosts(sessionId) {
  return api.get(`/simulation/${sessionId}/virality`)
}

// ── Emotional State ────────────────────────────────────────────────────────────

export function getEmotionalHeatmap(sessionId) {
  return api.get(`/simulation/${sessionId}/emotional-heatmap`)
}

export function getAgentEmotionalState(sessionId, agentId) {
  return api.get(`/simulation/${sessionId}/agents/${agentId}/emotional-state`)
}

export function getAgentBeliefs(sessionId, agentId) {
  return api.get(`/simulation/${sessionId}/agents/${agentId}/beliefs`)
}

export function getCognitiveDissonance(sessionId, params = {}) {
  return api.get(`/simulation/${sessionId}/cognitive-dissonance`, { params })
}

export function getEmotionalContagionMap(sessionId) {
  return api.get(`/simulation/${sessionId}/emotional-contagion-map`)
}

// ── Scale Benchmarks ───────────────────────────────────────────────────────────

export function getBenchmarks() {
  return api.get('/simulation/admin/benchmarks')
}

export function getBenchmarkResult(target) {
  return api.get(`/simulation/admin/benchmarks/${target}`)
}

export function runBenchmark(target) {
  return api.post('/simulation/admin/benchmarks/run', { target })
}

// ── Forecast & Backtest ─────────────────────────────────────────────────────

export function getForecast(metric, horizon = 12) {
  return api.get(`/simulation/forecast/${metric}`, { params: { horizon } })
}

export function getBacktest(metric, trainEnd = '2022-Q4', horizon = 8) {
  return api.get(`/simulation/forecast/${metric}/backtest`, { params: { train_end: trainEnd, horizon } })
}

export function getRetrospectiveValidation(periodStart = '2020-Q1', periodEnd = '2020-Q4') {
  return api.get('/simulation/validation/retrospective', { params: { period_start: periodStart, period_end: periodEnd } })
}

export function quickStart(seedText) {
  return api.post('/simulation/quick-start', { seed_text: seedText })
}

export function getSessionDecisions(sessionId, params = {}) {
  return api.get(`/simulation/${sessionId}/decisions`, { params })
}

// ── Cognitive Theater (Factions, Tipping Points, World Events) ────────────────────

export function getFactions(sessionId) {
  return api.get(`/simulation/${sessionId}/factions`)
}

export function getTippingPoints(sessionId) {
  return api.get(`/simulation/${sessionId}/tipping-points`)
}

export function getWorldEvents(sessionId) {
  return api.get(`/simulation/${sessionId}/world-events`)
}

export function getMultiRun(sessionId) {
  return api.get(`/simulation/${sessionId}/multi-run`)
}

export function triggerMultiRun(sessionId) {
  return api.post(`/simulation/${sessionId}/multi-run`)
}
