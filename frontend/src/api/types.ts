/** Standard API response envelope */
export interface APIResponse<T = any> {
  success: boolean
  data: T | null
  meta?: {
    total?: number
    page?: number
    limit?: number
  }
  error?: string
}

// ── Graph types ────────────────────────────────────────────────────────────────

export interface KGNode {
  id: string
  title: string
  node_type: string
  session_id: string
  description?: string
  is_stakeholder?: number
  activity_level?: number
  influence_weight?: number
}

export interface KGEdge {
  id: string
  source_id: string
  target_id: string
  relationship: string
  weight?: number
}

export interface GraphData {
  nodes: KGNode[]
  edges: KGEdge[]
  session_id?: string
}

export interface GraphSnapshot {
  round_number: number
  nodes: KGNode[]
  edges: KGEdge[]
}

export interface NodeEvidence {
  node_id: string
  evidence: string[]
}

export interface RelationshipState {
  agent_id: number
  oasis_username: string
  target_id: number
  trust_score: number
  round_number: number
}

export interface BuildGraphPayload {
  seed_text: string
  scenario_type?: string
  session_id?: string
}

export interface SeedAnalysis {
  mode: string
  detected_domain?: string
  implied_actors?: string[]
  summary?: string
}

// ── Simulation types ───────────────────────────────────────────────────────────

export type SimulationMode = 'hk_demographic' | 'kg_driven'
export type SimulationPreset = 'fast' | 'standard' | 'deep' | 'large' | 'massive' | 'custom'
export type SimulationStatus = 'pending' | 'running' | 'completed' | 'failed' | 'stopped'

export interface SimulationSession {
  session_id: string
  name?: string
  status: SimulationStatus
  sim_mode?: SimulationMode
  round_count?: number
  agent_count?: number
  current_round?: number
  created_at?: string
  updated_at?: string
}

export interface AgentProfile {
  agent_id: number
  oasis_username: string
  session_id: string
  is_stakeholder?: number
  activity_level?: number
  influence_weight?: number
  political_stance?: number
  tier?: number
  /** Big Five + attachment personality fields */
  personality?: Record<string, number>
}

export interface SimulationAction {
  action_id?: number
  session_id: string
  agent_id: number
  oasis_username: string
  action_type: string
  content?: string
  round_number: number
  created_at?: string
}

export interface Shock {
  shock_type: string
  description: string
  magnitude?: number
  macro_effects?: Record<string, number>
  target_agents?: number[]
}

export interface StartSimulationPayload {
  session_id: string
  preset?: SimulationPreset
  round_count?: number
  agent_count?: number
  seed_text?: string
  scenario_question?: string
  domain_pack_id?: string
}

export interface MacroSnapshot {
  round_number: number
  gdp_growth?: number
  unemployment_rate?: number
  hsi_level?: number
  ccl_index?: number
  consumer_confidence?: number
  fed_rate?: number
  birth_rate?: number
  policy_flags?: Record<string, boolean>
}

export interface EchoChamber {
  chamber_id: string
  agent_ids: number[]
  cohesion_score: number
  round_number: number
}

export interface PolarizationSnapshot {
  round_number: number
  jsd?: number
  polarization_index?: number
}

export interface FactionSnapshot {
  faction_id: string
  label?: string
  agent_ids: number[]
  belief_centroid?: number
  round_number: number
}

export interface TippingPoint {
  round_number: number
  jsd: number
  trigger?: string
  description?: string
}

export interface WorldEvent {
  event_id: string
  session_id: string
  round_number: number
  description: string
  impact?: Record<string, number>
}

export interface AgentMemory {
  memory_id?: number
  session_id: string
  oasis_username: string
  memory_text: string
  salience_score: number
  round_number?: number
  created_at?: string
}

export interface BeliefState {
  agent_id: number
  topic: string
  stance: number
  confidence?: number
  round_number: number
}

export interface EmotionalState {
  agent_id: number
  valence: number
  arousal: number
  dominant_emotion?: string
  round_number: number
}

export interface NetworkEvent {
  event_type: string
  agent_id?: number
  details?: Record<string, any>
  round_number: number
}

export interface CommunitySummary {
  community_id: string
  summary: string
  member_count: number
  round_number?: number
}

export interface TripleConflict {
  subject: string
  predicate: string
  conflicting_objects: string[]
  agent_count: number
}

export interface MultiRunResult {
  session_id: string
  outcomes: Record<string, number>
  confidence_interval?: [number, number]
  trial_count: number
}

export interface QuickStartPayload {
  seed_text: string
  scenario_question?: string
  preset?: SimulationPreset
}

export interface BranchOptions {
  branch_name?: string
  fork_round?: number
  description?: string
}

export interface SessionComparison {
  session_a: string
  session_b: string
  diff?: Record<string, any>
}

export interface ForecastResult {
  metric: string
  horizon: number
  forecasts: Array<{ period: string; value: number; lower?: number; upper?: number }>
}

export interface BacktestResult {
  metric: string
  train_end: string
  mape?: number
  direction_accuracy?: number
  actuals: number[]
  predictions: number[]
}

export interface ConfidenceScore {
  session_id: string
  score: number
  components?: Record<string, number>
}

// ── Report types ───────────────────────────────────────────────────────────────

export interface Report {
  report_id: string
  session_id: string
  status: 'pending' | 'generating' | 'complete' | 'failed'
  content?: string
  created_at?: string
}

export interface GenerateReportPayload {
  session_id: string
  report_type?: string
  include_xai?: boolean
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface ChatPayload {
  session_id?: string
  report_id?: string
  message: string
  history?: ChatMessage[]
}

export interface AgentInterviewPayload {
  session_id: string
  agent_id: number
  message: string
}

export interface AgentInterviewResponse {
  agent_id: number
  oasis_username?: string
  answer: string
}

export interface XaiToolParams {
  [key: string]: any
}

// ── Prediction market types ────────────────────────────────────────────────────

export interface PredictionContract {
  contract_id: string
  title: string
  category?: string
  yes_price?: number
  no_price?: number
  volume?: number
  end_date?: string
}

export interface TradingSignal {
  contract_id: string
  direction: 'YES' | 'NO' | 'HOLD'
  alpha?: number
  confidence?: number
  reasoning?: string
}

// ── Stock types ────────────────────────────────────────────────────────────────

export type StockGroup = 'hk_stock' | 'hk_index' | 'us_stock' | 'us_index'

export interface StockTicker {
  ticker: string
  name_zh?: string
  name_en?: string
  group: StockGroup
  currency?: string
}

export interface StockForecastPoint {
  period: string
  value: number
  lower?: number
  upper?: number
}

export interface StockForecast {
  ticker: string
  horizon: number
  forecasts: StockForecastPoint[]
  signal_overlay?: Record<string, number>
}

export interface StockBacktest {
  ticker: string
  train_end: string
  mape?: number
  direction_accuracy?: number
  actuals: number[]
  predictions: number[]
}

export interface StockSummaryItem {
  ticker: string
  name_zh?: string
  name_en?: string
  group: StockGroup
  mape?: number
  direction_accuracy?: number
  last_price?: number
  trend?: 'up' | 'down' | 'flat'
}
