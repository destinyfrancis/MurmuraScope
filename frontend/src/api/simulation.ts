import axios, { type AxiosResponse } from 'axios'
import type {
  APIResponse,
  AgentMemory,
  AgentProfile,
  BacktestResult,
  BeliefState,
  BranchOptions,
  CommunitySummary,
  ConfidenceScore,
  EchoChamber,
  EmotionalState,
  FactionSnapshot,
  ForecastResult,
  MacroSnapshot,
  MultiRunResult,
  NetworkEvent,
  PolarizationSnapshot,
  QuickStartPayload,
  SessionComparison,
  Shock,
  SimulationAction,
  SimulationSession,
  StartSimulationPayload,
  TippingPoint,
  TripleConflict,
  WorldEvent,
} from './types'

const api = axios.create({ baseURL: '/api' })

/**
 * Create a new simulation session.
 * @param data - Simulation config including optional domain_pack_id (default: 'hk_city')
 */
export function createSimulation(
  data: Partial<StartSimulationPayload> & Record<string, any>,
): Promise<AxiosResponse<APIResponse<SimulationSession>>> {
  const payload = { domain_pack_id: 'hk_city', ...data }
  return api.post('/simulation/create', payload)
}

export function startSimulation(
  data: StartSimulationPayload,
): Promise<AxiosResponse<APIResponse<SimulationSession>>> {
  return api.post('/simulation/start', data)
}

export function getSession(
  sessionId: string,
): Promise<AxiosResponse<APIResponse<SimulationSession>>> {
  return api.get(`/simulation/${sessionId}`)
}

export function getSessionStatus(
  sessionId: string,
): Promise<AxiosResponse<APIResponse<{ status: string; current_round?: number }>>> {
  return api.get(`/simulation/${sessionId}/status`)
}

export function injectShock(
  sessionId: string,
  shock: Shock,
): Promise<AxiosResponse<APIResponse<{ applied: boolean }>>> {
  return api.post(`/simulation/${sessionId}/shock`, shock)
}

export function connectWebSocket(sessionId: string): WebSocket {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  return new WebSocket(`${protocol}//${host}/api/ws/progress/${sessionId}`)
}

export function getSessionAgents(
  sessionId: string,
): Promise<AxiosResponse<APIResponse<AgentProfile[]>>> {
  return api.get(`/simulation/${sessionId}/agents`)
}

export function suggestConfig(
  data: Record<string, any>,
): Promise<AxiosResponse<APIResponse<Record<string, any>>>> {
  return api.post('/simulation/suggest-config', data)
}

export function createBranch(
  sessionId: string,
  options: BranchOptions = {},
): Promise<AxiosResponse<APIResponse<SimulationSession>>> {
  return api.post(`/simulation/${sessionId}/branch`, options)
}

export function listBranches(
  sessionId: string,
): Promise<AxiosResponse<APIResponse<SimulationSession[]>>> {
  return api.get(`/simulation/${sessionId}/branches`)
}

export function compareSessions(
  sessionA: string,
  sessionB: string,
): Promise<AxiosResponse<APIResponse<SessionComparison>>> {
  return api.get(`/simulation/compare/${sessionA}/${sessionB}`)
}

export function getSessionActions(
  sessionId: string,
  params: Record<string, any> = {},
): Promise<AxiosResponse<APIResponse<SimulationAction[]>>> {
  return api.get(`/simulation/${sessionId}/actions`, { params })
}

export function getSentimentSummary(
  sessionId: string,
): Promise<AxiosResponse<APIResponse<Record<string, number>>>> {
  return api.get(`/simulation/${sessionId}/actions/sentiment`)
}

export function getAgentMemories(
  sessionId: string,
  agentId: number,
  params: Record<string, any> = {},
): Promise<AxiosResponse<APIResponse<{ memories: AgentMemory[]; triples?: any[] }>>> {
  return api.get(`/simulation/${sessionId}/agents/${agentId}/memories`, { params })
}

export function searchAgentMemories(
  sessionId: string,
  agentId: number,
  query: string,
  topK: number = 10,
): Promise<AxiosResponse<APIResponse<AgentMemory[]>>> {
  return api.get(`/simulation/${sessionId}/agents/${agentId}/memories/search`, {
    params: { q: query, top_k: topK },
  })
}

export function getAgentTriples(
  sessionId: string,
  agentId: number,
  params: Record<string, any> = {},
): Promise<{ data: { data: any[] } }> {
  return api
    .get(`/simulation/${sessionId}/agents/${agentId}/memories`, { params })
    .then((res) => {
      const data = res.data?.data || {}
      return { data: { data: data.triples || [] } }
    })
}

export function getMacroHistory(
  sessionId: string,
  roundNumber: number | null = null,
): Promise<AxiosResponse<APIResponse<MacroSnapshot[]>>> {
  const params = roundNumber !== null ? { round_number: roundNumber } : {}
  return api.get(`/simulation/${sessionId}/macro-history`, { params })
}

export function getEchoChambers(
  sessionId: string,
  roundNumber: number | null = null,
): Promise<AxiosResponse<APIResponse<EchoChamber[]>>> {
  const params = roundNumber !== null ? { round_number: roundNumber } : {}
  return api.get(`/simulation/${sessionId}/echo-chambers`, { params })
}

export function getContagionData(
  sessionId: string,
): Promise<AxiosResponse<APIResponse<Record<string, any>>>> {
  return api.get(`/simulation/${sessionId}/contagion`)
}

export function getCommunitySummaries(
  sessionId: string,
  roundNumber: number | null = null,
): Promise<AxiosResponse<APIResponse<CommunitySummary[]>>> {
  const params = roundNumber !== null ? { round_number: roundNumber } : {}
  return api.get(`/simulation/${sessionId}/community-summaries`, { params })
}

export function getTripleConflicts(
  sessionId: string,
  minAgents: number = 3,
): Promise<AxiosResponse<APIResponse<TripleConflict[]>>> {
  return api.get(`/simulation/${sessionId}/triple-conflicts`, { params: { min_agents: minAgents } })
}

export function getPolarization(
  sessionId: string,
  roundNumber: number | null = null,
): Promise<AxiosResponse<APIResponse<PolarizationSnapshot[]>>> {
  const params = roundNumber !== null ? { round_number: roundNumber } : {}
  return api.get(`/simulation/${sessionId}/polarization`, { params })
}

export function listSessions(
  limit: number = 20,
  offset: number = 0,
): Promise<AxiosResponse<APIResponse<SimulationSession[]>>> {
  return api.get('/simulation/sessions', { params: { limit, offset } })
}

// ── Network Evolution ──────────────────────────────────────────────────────────

export function getNetworkEvents(
  sessionId: string,
  params: Record<string, any> = {},
): Promise<AxiosResponse<APIResponse<NetworkEvent[]>>> {
  return api.get(`/simulation/${sessionId}/network-events`, { params })
}

// ── Feed & Bubble ──────────────────────────────────────────────────────────────

export function getAgentFeed(
  sessionId: string,
  agentId: number,
): Promise<AxiosResponse<APIResponse<SimulationAction[]>>> {
  return api.get(`/simulation/${sessionId}/feed/${agentId}`)
}

export function getFilterBubble(
  sessionId: string,
): Promise<AxiosResponse<APIResponse<Record<string, any>>>> {
  return api.get(`/simulation/${sessionId}/filter-bubble`)
}

export function getFilterBubbleHistory(
  sessionId: string,
): Promise<AxiosResponse<APIResponse<Record<string, any>[]>>> {
  return api.get(`/simulation/${sessionId}/filter-bubble-history`)
}

export function getViralPosts(
  sessionId: string,
): Promise<AxiosResponse<APIResponse<SimulationAction[]>>> {
  return api.get(`/simulation/${sessionId}/virality`)
}

// ── Emotional State ────────────────────────────────────────────────────────────

export function getEmotionalHeatmap(
  sessionId: string,
): Promise<AxiosResponse<APIResponse<Record<string, any>>>> {
  return api.get(`/simulation/${sessionId}/emotional-heatmap`)
}

export function getAgentEmotionalState(
  sessionId: string,
  agentId: number,
): Promise<AxiosResponse<APIResponse<EmotionalState>>> {
  return api.get(`/simulation/${sessionId}/agents/${agentId}/emotional-state`)
}

export function getAgentBeliefs(
  sessionId: string,
  agentId: number,
): Promise<AxiosResponse<APIResponse<BeliefState[]>>> {
  return api.get(`/simulation/${sessionId}/agents/${agentId}/beliefs`)
}

export function getCognitiveDissonance(
  sessionId: string,
  params: Record<string, any> = {},
): Promise<AxiosResponse<APIResponse<Record<string, any>[]>>> {
  return api.get(`/simulation/${sessionId}/cognitive-dissonance`, { params })
}

export function getEmotionalContagionMap(
  sessionId: string,
): Promise<AxiosResponse<APIResponse<Record<string, any>>>> {
  return api.get(`/simulation/${sessionId}/emotional-contagion-map`)
}

// ── Scale Benchmarks ───────────────────────────────────────────────────────────

export function getBenchmarks(): Promise<AxiosResponse<APIResponse<Record<string, any>[]>>> {
  return api.get('/simulation/admin/benchmarks')
}

export function getBenchmarkResult(
  target: string,
): Promise<AxiosResponse<APIResponse<Record<string, any>>>> {
  return api.get(`/simulation/admin/benchmarks/${target}`)
}

export function runBenchmark(
  target: string,
): Promise<AxiosResponse<APIResponse<Record<string, any>>>> {
  return api.post('/simulation/admin/benchmarks/run', { target })
}

// ── Forecast & Backtest ─────────────────────────────────────────────────────

export function getForecast(
  metric: string,
  horizon: number = 12,
): Promise<AxiosResponse<APIResponse<ForecastResult>>> {
  return api.get(`/simulation/forecast/${metric}`, { params: { horizon } })
}

export function getBacktest(
  metric: string,
  trainEnd: string = '2022-Q4',
  horizon: number = 8,
): Promise<AxiosResponse<APIResponse<BacktestResult>>> {
  return api.get(`/simulation/forecast/${metric}/backtest`, {
    params: { train_end: trainEnd, horizon },
  })
}

export function getRetrospectiveValidation(
  periodStart: string = '2020-Q1',
  periodEnd: string = '2020-Q4',
): Promise<AxiosResponse<APIResponse<Record<string, any>>>> {
  return api.get('/simulation/validation/retrospective', {
    params: { period_start: periodStart, period_end: periodEnd },
  })
}

export function quickStart(
  seedText: string,
  scenarioQuestion: string = '',
  preset: string = 'fast',
): Promise<AxiosResponse<APIResponse<SimulationSession>>> {
  return api.post('/simulation/quick-start', {
    seed_text: seedText,
    scenario_question: scenarioQuestion,
    preset,
  })
}

export function quickStartWithFile(
  file: File,
  scenarioQuestion: string = '',
  preset: string = 'fast',
): Promise<AxiosResponse<APIResponse<SimulationSession>>> {
  const form = new FormData()
  form.append('file', file)
  form.append('scenario_question', scenarioQuestion)
  form.append('preset', preset)
  return api.post('/simulation/quick-start/upload', form)
}

export function getSessionDecisions(
  sessionId: string,
  params: Record<string, any> = {},
): Promise<AxiosResponse<APIResponse<Record<string, any>[]>>> {
  return api.get(`/simulation/${sessionId}/decisions`, { params })
}

// ── Cognitive Theater (Factions, Tipping Points, World Events) ─────────────────

export function getFactions(
  sessionId: string,
): Promise<AxiosResponse<APIResponse<FactionSnapshot[]>>> {
  return api.get(`/simulation/${sessionId}/factions`)
}

export function getTippingPoints(
  sessionId: string,
): Promise<AxiosResponse<APIResponse<TippingPoint[]>>> {
  return api.get(`/simulation/${sessionId}/tipping-points`)
}

export function getWorldEvents(
  sessionId: string,
): Promise<AxiosResponse<APIResponse<WorldEvent[]>>> {
  return api.get(`/simulation/${sessionId}/world-events`)
}

export function getMultiRun(
  sessionId: string,
): Promise<AxiosResponse<APIResponse<MultiRunResult>>> {
  return api.get(`/simulation/${sessionId}/multi-run`)
}

export function triggerMultiRun(
  sessionId: string,
): Promise<AxiosResponse<APIResponse<MultiRunResult>>> {
  return api.post(`/simulation/${sessionId}/multi-run`)
}

export function stopSimulation(
  sessionId: string,
): Promise<AxiosResponse<APIResponse<{ stopped: boolean }>>> {
  return api.post(`/simulation/${sessionId}/stop`)
}

/**
 * Release all in-memory resources for a session (subprocess, caches, WS buffers).
 * Safe to call for any session state. Frontend should call this on navigation away.
 */
export function cleanupSession(
  sessionId: string,
): Promise<AxiosResponse<APIResponse<{ cleaned: boolean }>>> {
  return api.post(`/simulation/${sessionId}/cleanup`)
}

// ── HSI Decomposition & Validation ────────────────────────────────────────────

export function getHSIDecomposition(
  nQuarters: number = 20,
): Promise<AxiosResponse<APIResponse<Record<string, any>>>> {
  return api.get('/simulation/forecast/hsi-decomposition', { params: { n_quarters: nQuarters } })
}

export function getSensitivityAnalysis(
  periodStart: string = '2021-Q1',
  periodEnd: string = '2023-Q4',
): Promise<AxiosResponse<APIResponse<Record<string, any>>>> {
  return api.post('/simulation/sensitivity-analysis', {
    period_start: periodStart,
    period_end: periodEnd,
  })
}

export function getCrossDomainValidation(
  periodStart: string = '2021-Q1',
  periodEnd: string = '2023-Q4',
): Promise<AxiosResponse<APIResponse<Record<string, any>>>> {
  return api.get('/simulation/validation/cross-domain', {
    params: { period_start: periodStart, period_end: periodEnd },
  })
}

export function getExternalFeed(
  forceRefresh: boolean = false,
): Promise<AxiosResponse<APIResponse<Record<string, any>[]>>> {
  return api.get('/simulation/data/external-feed', { params: { force_refresh: forceRefresh } })
}

export function getConfidenceScore(
  sessionId: string,
): Promise<AxiosResponse<APIResponse<ConfidenceScore>>> {
  return api.get(`/simulation/${sessionId}/confidence-score`)
}
