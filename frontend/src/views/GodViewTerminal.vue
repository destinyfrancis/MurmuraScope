<template>
  <div class="god-view">
    <!-- Header Bar -->
    <div class="gv-header">
      <div class="gv-logo">
        <span class="gv-icon">⬡</span>
        <span class="gv-title">GOD VIEW TERMINAL</span>
        <span class="gv-version">v2.0</span>
      </div>
      <div class="gv-controls">
        <select v-model="selectedSessionId" class="gv-select" @change="onSessionChange">
          <option value="">-- Select Session --</option>
          <option v-for="s in sessions" :key="s.id" :value="s.id">
            {{ s.id.slice(0, 8) }} · {{ s.scenario_type || 'hk_city' }} · Round {{ s.current_round || 0 }}
          </option>
        </select>
        <button class="gv-btn" :class="{ active: autoRefresh }" @click="toggleAutoRefresh">
          {{ autoRefresh ? '⟳ AUTO ON' : '⟳ AUTO OFF' }}
        </button>
        <button class="gv-btn primary" :disabled="loading" @click="refresh">
          {{ loading ? 'LOADING...' : 'REFRESH' }}
        </button>
        <span class="gv-clock">{{ currentTime }}</span>
      </div>
    </div>

    <!-- Status Bar -->
    <div class="gv-statusbar">
      <span class="sb-item" :class="signalSummaryClass">
        SIGNALS: {{ signals.length }} active
      </span>
      <span class="sb-item">
        BUY YES: <span class="green">{{ buyYesCount }}</span>
      </span>
      <span class="sb-item">
        BUY NO: <span class="red">{{ buyNoCount }}</span>
      </span>
      <span class="sb-item">
        HOLD: <span class="amber">{{ holdCount }}</span>
      </span>
      <span class="sb-item">
        CONTRACTS: {{ matchedContracts.length }}
      </span>
      <span class="sb-item ml-auto" v-if="lastRefreshed">
        Last: {{ lastRefreshed }}
      </span>
    </div>

    <!-- Tab Bar -->
    <div class="gv-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        class="gv-tab"
        :class="{ active: activeTab === tab.id }"
        @click="activeTab = tab.id"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- Ensemble Tab -->
    <div v-if="activeTab === 'ensemble' && selectedSessionId" class="gv-tab-content">
      <div v-if="ensembleLoading" class="loading-msg">Loading ensemble data...</div>
      <EnsembleChart
        v-else
        :distributions="ensembleDistributions"
        :probability-statements="ensembleProbabilityStatements"
        :trial-metadata="ensembleTrialMetadata"
        :n-trials="ensembleNTrials"
      />
    </div>

    <!-- Scenarios Tab -->
    <div v-if="activeTab === 'scenarios' && selectedSessionId" class="gv-tab-content">
      <ScenarioComparison
        :session-a="selectedSessionId"
        session-b=""
      />
    </div>

    <!-- Sentiment Heatmap Tab -->
    <div v-if="activeTab === 'sentiment' && selectedSessionId" class="gv-tab-content">
      <SentimentHeatmap
        :sentiment-by-round="sentimentByRound"
      />
    </div>

    <!-- Main Grid -->
    <div class="gv-body" v-if="activeTab === 'main' && selectedSessionId">
      <!-- Left: Contracts Panel -->
      <div class="gv-panel contracts-panel">
        <div class="panel-header">
          <span class="panel-title">POLYMARKET CONTRACTS</span>
          <span class="panel-badge">{{ matchedContracts.length }}</span>
        </div>
        <div class="panel-content">
          <div v-if="contractsLoading" class="loading-msg">Fetching contracts...</div>
          <div v-else-if="matchedContracts.length === 0" class="empty-msg">
            No contracts matched for this session.
          </div>
          <div
            v-for="item in matchedContracts"
            :key="item.contract.id"
            class="contract-card"
            :class="{ selected: selectedContractId === item.contract.id }"
            @click="selectContract(item.contract.id)"
          >
            <div class="cc-question">{{ item.contract.question }}</div>
            <div class="cc-meta">
              <span class="cc-price">
                YES: <strong>{{ item.contract.outcome_prices?.length ? formatPrice(item.contract.outcome_prices[0]) : 'N/A' }}</strong>
              </span>
              <span class="cc-sep">|</span>
              <span class="cc-vol">Vol: ${{ formatVolume(item.contract.volume) }}</span>
              <span class="cc-sep">|</span>
              <span class="cc-score">Match: {{ (item.relevance_score * 100).toFixed(0) }}%</span>
            </div>
            <div class="cc-keywords">
              <span v-for="kw in item.matched_keywords.slice(0, 4)" :key="kw" class="kw-tag">
                {{ kw }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- Center: Signals Panel -->
      <div class="gv-panel signals-panel">
        <div class="panel-header">
          <span class="panel-title">TRADING SIGNALS</span>
          <span class="panel-badge" :class="signalBadgeClass">{{ signals.length }}</span>
        </div>
        <div class="panel-content">
          <div v-if="signalsLoading" class="loading-msg">Computing signals from agent consensus...</div>
          <div v-else-if="signals.length === 0" class="empty-msg">
            No signals generated yet. Ensure simulation has completed at least 5 rounds.
          </div>
          <div
            v-for="sig in signals"
            :key="sig.contract_id"
            class="signal-card"
            :class="signalCardClass(sig.direction)"
          >
            <div class="sig-header">
              <span class="sig-direction" :class="directionClass(sig.direction)">
                {{ directionIcon(sig.direction) }} {{ sig.direction }}
              </span>
              <span class="sig-strength" :class="strengthClass(sig.strength)">
                {{ sig.strength.toUpperCase() }}
              </span>
              <span class="sig-alpha" :class="alphaClass(sig.alpha)">
                α {{ sig.alpha >= 0 ? '+' : '' }}{{ (sig.alpha * 100).toFixed(1) }}%
              </span>
            </div>
            <div class="sig-question">{{ sig.contract_question }}</div>
            <div class="sig-prices">
              <span>Market: <strong>{{ (sig.market_price * 100).toFixed(1) }}%</strong></span>
              <span class="sep">→</span>
              <span>Engine: <strong :class="engineProbClass(sig)">{{ (sig.engine_probability * 100).toFixed(1) }}%</strong></span>
            </div>
            <div class="sig-bar">
              <div class="sig-bar-track">
                <div
                  class="sig-bar-market"
                  :style="{ width: (sig.market_price * 100) + '%' }"
                ></div>
              </div>
              <div class="sig-bar-track mt2">
                <div
                  class="sig-bar-engine"
                  :class="engineBarClass(sig)"
                  :style="{ width: (sig.engine_probability * 100) + '%' }"
                ></div>
              </div>
            </div>
            <div class="sig-stats">
              <span>Support: <span class="green">{{ sig.supporting_agents }}</span> agents</span>
              <span>Oppose: <span class="red">{{ sig.opposing_agents }}</span> agents</span>
              <span>Conf: <span :class="confClass(sig.confidence)">{{ (sig.confidence * 100).toFixed(0) }}%</span></span>
            </div>
            <div class="sig-reasoning">{{ sig.reasoning }}</div>
          </div>
        </div>
      </div>

      <!-- Right: Agent Consensus Panel -->
      <div class="gv-panel consensus-panel">
        <div class="panel-header">
          <span class="panel-title">AGENT CONSENSUS</span>
        </div>
        <div class="panel-content">
          <!-- Sentiment Summary -->
          <div class="cons-section">
            <div class="cons-label">SENTIMENT TREND</div>
            <div v-if="sentimentData.length === 0" class="empty-msg small">No data</div>
            <div v-for="row in sentimentData.slice(-6)" :key="row.round" class="cons-row">
              <span class="cons-round">R{{ row.round }}</span>
              <div class="cons-sentiment-bar">
                <div
                  class="csb-fill"
                  :class="sentimentBarClass(row.avg_sentiment)"
                  :style="{ width: Math.abs(row.avg_sentiment) * 100 + '%' }"
                ></div>
              </div>
              <span class="cons-val" :class="sentimentValClass(row.avg_sentiment)">
                {{ row.avg_sentiment >= 0 ? '+' : '' }}{{ row.avg_sentiment.toFixed(2) }}
              </span>
            </div>
          </div>

          <!-- Signal Breakdown by contract -->
          <div class="cons-section" v-if="signals.length > 0">
            <div class="cons-label">SIGNAL BREAKDOWN</div>
            <div v-for="sig in signals.slice(0, 5)" :key="'sb-' + sig.contract_id" class="cons-sig-row">
              <div class="csr-question">{{ sig.contract_question.slice(0, 40) }}...</div>
              <div class="csr-bar-wrap">
                <div class="csr-bar" :style="{ width: (sig.engine_probability * 100) + '%' }" :class="engineBarClass(sig)"></div>
              </div>
              <div class="csr-pct" :class="directionClass(sig.direction)">
                {{ (sig.engine_probability * 100).toFixed(1) }}%
                <span class="csr-dir">{{ directionIcon(sig.direction) }}</span>
              </div>
            </div>
          </div>

          <!-- Top Actions -->
          <div class="cons-section">
            <div class="cons-label">RECENT DECISIONS</div>
            <div v-if="recentDecisions.length === 0" class="empty-msg small">Awaiting agent decisions...</div>
            <div v-for="d in recentDecisions" :key="d.id" class="decision-row">
              <span class="dr-agent">AGT-{{ d.agent_id }}</span>
              <span class="dr-type" :class="decisionClass(d.decision_type)">{{ d.decision_type }}</span>
              <span class="dr-r">R{{ d.round_number }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Empty State -->
    <div v-if="!selectedSessionId" class="gv-empty">
      <div class="ge-icon">⬡</div>
      <div class="ge-msg">Select a simulation session to begin</div>
      <div class="ge-sub">The God View Terminal shows real-time Polymarket trading signals derived from agent consensus</div>
    </div>

    <!-- Bottom: Live Agent Feed (main tab only) -->
    <div class="gv-feed" v-if="selectedSessionId && activeTab === 'main'">
      <div class="feed-header">
        <span class="feed-title">LIVE AGENT FEED</span>
        <span class="feed-count">{{ feedItems.length }} posts</span>
      </div>
      <div class="feed-scroll" ref="feedScrollEl">
        <div v-if="feedItems.length === 0" class="empty-msg">No agent activity yet.</div>
        <div v-for="item in feedItems" :key="item.id" class="feed-item" :class="feedItemClass(item.sentiment_score)">
          <span class="fi-time">{{ relativeTime(item.created_at) }}</span>
          <span class="fi-agent">AGT-{{ item.agent_id }}</span>
          <span class="fi-sep">›</span>
          <span class="fi-content">{{ item.content.slice(0, 120) }}</span>
          <span class="fi-sentiment" :class="sentimentValClass(item.sentiment_score)">
            {{ item.sentiment_score >= 0 ? '+' : '' }}{{ (item.sentiment_score || 0).toFixed(2) }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { listSessions, getSessionActions, getSessionDecisions, getMultiRun } from '../api/simulation.js'
import {
  getMatchedContracts,
  getTradingSignals,
} from '../api/prediction_market.js'
import EnsembleChart from '../components/EnsembleChart.vue'
import ScenarioComparison from '../components/ScenarioComparison.vue'
import SentimentHeatmap from '../components/SentimentHeatmap.vue'

// ── State ───────────────────────────────────────────────────────────────────
const sessions = ref([])
const selectedSessionId = ref('')
const matchedContracts = ref([])
const signals = ref([])
const feedItems = ref([])
const sentimentData = ref([])
const recentDecisions = ref([])
const selectedContractId = ref(null)

const loading = ref(false)
const contractsLoading = ref(false)
const signalsLoading = ref(false)
const autoRefresh = ref(false)
const lastRefreshed = ref('')
const currentTime = ref('')
const feedScrollEl = ref(null)

// ── Tab state ────────────────────────────────────────────────────────────────
const activeTab = ref('main')
const tabs = [
  { id: 'main',     label: '市場訊號' },
  { id: 'ensemble', label: '集成預測' },
  { id: 'scenarios', label: '情景比較' },
  { id: 'sentiment', label: '情緒熱圖' },
]

// ── Ensemble data ────────────────────────────────────────────────────────────
const ensembleDistributions = ref([])
const ensembleProbabilityStatements = ref([])
const ensembleTrialMetadata = ref([])
const ensembleNTrials = ref(0)
const ensembleLoading = ref(false)

let refreshTimer = null
let clockTimer = null

// ── Computed ────────────────────────────────────────────────────────────────
const buyYesCount = computed(() => signals.value.filter(s => s.direction === 'BUY_YES').length)
const buyNoCount = computed(() => signals.value.filter(s => s.direction === 'BUY_NO').length)
const holdCount = computed(() => signals.value.filter(s => s.direction === 'HOLD').length)

const signalSummaryClass = computed(() => {
  if (buyYesCount.value > 0 || buyNoCount.value > 0) return 'active-signal'
  return ''
})

const signalBadgeClass = computed(() => {
  if (buyYesCount.value > buyNoCount.value) return 'badge-green'
  if (buyNoCount.value > buyYesCount.value) return 'badge-red'
  return 'badge-amber'
})

// sentimentByRound for SentimentHeatmap — derived from sentimentData
const sentimentByRound = computed(() => {
  const map = {}
  for (const row of sentimentData.value) {
    const avg = row.avg_sentiment || 0
    map[String(row.round)] = {
      positive: avg > 0 ? Math.round(avg * 100) : 0,
      neutral: Math.round((1 - Math.abs(avg)) * 100),
      negative: avg < 0 ? Math.round(Math.abs(avg) * 100) : 0,
    }
  }
  return map
})

// ── Methods ─────────────────────────────────────────────────────────────────
function formatPrice(p) {
  if (!p) return 'N/A'
  return (parseFloat(p) * 100).toFixed(1) + '%'
}

function formatVolume(v) {
  if (!v) return '0'
  const n = parseFloat(v)
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return n.toFixed(0)
}

function directionIcon(dir) {
  if (dir === 'BUY_YES') return '▲'
  if (dir === 'BUY_NO') return '▼'
  return '─'
}

function directionClass(dir) {
  if (dir === 'BUY_YES') return 'green'
  if (dir === 'BUY_NO') return 'red'
  return 'amber'
}

function strengthClass(s) {
  if (s === 'strong') return 'strength-strong'
  if (s === 'moderate') return 'strength-moderate'
  return 'strength-weak'
}

function alphaClass(a) {
  if (a > 0.1) return 'green'
  if (a < -0.1) return 'red'
  return 'amber'
}

function signalCardClass(dir) {
  if (dir === 'BUY_YES') return 'sc-buy-yes'
  if (dir === 'BUY_NO') return 'sc-buy-no'
  return 'sc-hold'
}

function engineProbClass(sig) {
  return sig.alpha > 0 ? 'green' : sig.alpha < 0 ? 'red' : 'amber'
}

function engineBarClass(sig) {
  return sig.alpha > 0.05 ? 'bar-green' : sig.alpha < -0.05 ? 'bar-red' : 'bar-amber'
}

function confClass(c) {
  if (c >= 0.7) return 'green'
  if (c >= 0.5) return 'amber'
  return 'red'
}

function sentimentBarClass(v) {
  return v >= 0 ? 'sb-pos' : 'sb-neg'
}

function sentimentValClass(v) {
  if (!v) return 'amber'
  return v > 0.1 ? 'green' : v < -0.1 ? 'red' : 'amber'
}

function decisionClass(type) {
  const t = (type || '').toLowerCase()
  const bullish = ['buy_property', 'invest', 'invest_stocks', 'increase_spending', 'spend_more', 'have_child', 'seek_promotion']
  const bearish = ['emigrate', 'reduce_spending', 'cut_spending', 'sell_property', 'hold_cash', 'quit', 'lie_flat', 'strike']
  if (bullish.includes(t)) return 'green'
  if (bearish.includes(t)) return 'red'
  return 'amber'
}

function feedItemClass(score) {
  if (!score) return ''
  if (score > 0.3) return 'fi-pos'
  if (score < -0.3) return 'fi-neg'
  return ''
}

function relativeTime(ts) {
  if (!ts) return ''
  const diff = Math.floor((Date.now() - new Date(ts).getTime()) / 1000)
  if (diff < 60) return `${diff}s`
  if (diff < 3600) return `${Math.floor(diff / 60)}m`
  return `${Math.floor(diff / 3600)}h`
}

function selectContract(id) {
  selectedContractId.value = selectedContractId.value === id ? null : id
}

function updateClock() {
  currentTime.value = new Date().toLocaleTimeString('en-HK', { hour12: false })
}

async function loadSessions() {
  try {
    const res = await listSessions(50, 0)
    sessions.value = (res.data?.sessions || res.data?.data || []).sort(
      (a, b) => new Date(b.created_at) - new Date(a.created_at)
    )
  } catch {
    sessions.value = []
  }
}

async function loadContracts() {
  if (!selectedSessionId.value) return
  contractsLoading.value = true
  try {
    const res = await getMatchedContracts(selectedSessionId.value, 8)
    matchedContracts.value = res.data?.matches || res.data?.data || []
  } catch {
    matchedContracts.value = []
  } finally {
    contractsLoading.value = false
  }
}

async function loadSignals() {
  if (!selectedSessionId.value) return
  signalsLoading.value = true
  try {
    const res = await getTradingSignals(selectedSessionId.value, 10)
    signals.value = res.data?.signals || res.data?.data || []
  } catch {
    signals.value = []
  } finally {
    signalsLoading.value = false
  }
}

async function loadFeed() {
  if (!selectedSessionId.value) return
  try {
    const res = await getSessionActions(selectedSessionId.value, { limit: 50 })
    const actions = res.data?.actions || res.data?.data || []
    feedItems.value = [...actions].sort((a, b) => new Date(b.created_at) - new Date(a.created_at))

    // Build per-round sentiment for consensus panel
    const byRound = {}
    for (const a of actions) {
      const r = a.round_number || 0
      if (!byRound[r]) byRound[r] = { round: r, sum: 0, count: 0 }
      byRound[r].sum += a.sentiment_score || 0
      byRound[r].count++
    }
    sentimentData.value = Object.values(byRound)
      .map(r => ({ round: r.round, avg_sentiment: r.count > 0 ? r.sum / r.count : 0 }))
      .sort((a, b) => a.round - b.round)

    // Scroll feed to top (newest)
    await nextTick()
    if (feedScrollEl.value) feedScrollEl.value.scrollTop = 0
  } catch {
    feedItems.value = []
    sentimentData.value = []
  }
}

async function loadDecisions() {
  if (!selectedSessionId.value) return
  try {
    const res = await getSessionDecisions(selectedSessionId.value, { limit: 20 })
    const decisions = res.data?.data || []
    recentDecisions.value = decisions
      .sort((a, b) => (b.round_number || 0) - (a.round_number || 0))
      .slice(0, 15)
  } catch {
    recentDecisions.value = []
  }
}

async function loadEnsemble() {
  if (!selectedSessionId.value) return
  ensembleLoading.value = true
  try {
    const res = await getMultiRun(selectedSessionId.value)
    const payload = res.data?.data || res.data || {}
    ensembleDistributions.value = payload.distributions || []
    ensembleProbabilityStatements.value = payload.probability_statements || []
    ensembleTrialMetadata.value = payload.trial_metadata || []
    ensembleNTrials.value = payload.n_trials || 0
  } catch {
    ensembleDistributions.value = []
    ensembleProbabilityStatements.value = []
    ensembleTrialMetadata.value = []
    ensembleNTrials.value = 0
  } finally {
    ensembleLoading.value = false
  }
}

async function refresh() {
  if (!selectedSessionId.value || loading.value) return
  loading.value = true
  try {
    await Promise.all([loadContracts(), loadSignals(), loadFeed(), loadDecisions(), loadEnsemble()])
    lastRefreshed.value = new Date().toLocaleTimeString('en-HK', { hour12: false })
  } finally {
    loading.value = false
  }
}

function toggleAutoRefresh() {
  autoRefresh.value = !autoRefresh.value
  if (autoRefresh.value) {
    refreshTimer = setInterval(refresh, 30_000)
    refresh()
  } else {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
}

function onSessionChange() {
  matchedContracts.value = []
  signals.value = []
  feedItems.value = []
  sentimentData.value = []
  selectedContractId.value = null
  ensembleDistributions.value = []
  ensembleProbabilityStatements.value = []
  ensembleTrialMetadata.value = []
  ensembleNTrials.value = 0
  if (selectedSessionId.value) refresh()
}

// ── Lifecycle ────────────────────────────────────────────────────────────────
onMounted(async () => {
  updateClock()
  clockTimer = setInterval(updateClock, 1000)
  await loadSessions()
  // Auto-select most recent session
  if (sessions.value.length > 0) {
    selectedSessionId.value = sessions.value[0].id
    await refresh()
  }
})

onUnmounted(() => {
  clearInterval(refreshTimer)
  clearInterval(clockTimer)
})
</script>

<style scoped>
/* ── Root ─────────────────────────────────────────────────────────────────── */
.god-view {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #0a0c0f;
  color: #c8d6e5;
  font-family: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace;
  font-size: 12px;
  overflow: hidden;
}

/* ── Header ─────────────────────────────────────────────────────────────────── */
.gv-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  background: #0d1117;
  border-bottom: 1px solid #1c2a3a;
  flex-shrink: 0;
}

.gv-logo {
  display: flex;
  align-items: center;
  gap: 8px;
}

.gv-icon {
  font-size: 18px;
  color: #00d4aa;
}

.gv-title {
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 3px;
  color: #00d4aa;
}

.gv-version {
  font-size: 10px;
  color: #4a6080;
  letter-spacing: 1px;
}

.gv-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.gv-select {
  background: #1a2332;
  border: 1px solid #2a3d52;
  color: #c8d6e5;
  padding: 4px 8px;
  font-family: inherit;
  font-size: 11px;
  border-radius: 3px;
  min-width: 220px;
}

.gv-select option {
  background: #1a2332;
}

.gv-btn {
  background: #1a2332;
  border: 1px solid #2a3d52;
  color: #7a9ab8;
  padding: 4px 12px;
  font-family: inherit;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 1px;
  border-radius: 3px;
  cursor: pointer;
  transition: all 0.15s;
}

.gv-btn:hover:not(:disabled) {
  border-color: #00d4aa;
  color: #00d4aa;
}

.gv-btn.active {
  border-color: #00d4aa;
  color: #00d4aa;
  background: #001a14;
}

.gv-btn.primary {
  border-color: #3a8fd4;
  color: #3a8fd4;
}

.gv-btn.primary:hover:not(:disabled) {
  background: #0a1f30;
}

.gv-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.gv-clock {
  color: #4a6080;
  font-size: 11px;
  letter-spacing: 1px;
  min-width: 60px;
  text-align: right;
}

/* ── Status Bar ─────────────────────────────────────────────────────────────── */
.gv-statusbar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 4px 16px;
  background: #0d1117;
  border-bottom: 1px solid #1c2a3a;
  font-size: 11px;
  color: #4a6080;
  flex-shrink: 0;
}

.sb-item.active-signal {
  color: #00d4aa;
}

.sb-item .green { color: #00c97a; }
.sb-item .red { color: #e05050; }
.sb-item .amber { color: #f0a030; }
.ml-auto { margin-left: auto; }

/* ── Body Grid ─────────────────────────────────────────────────────────────── */
.gv-body {
  display: grid;
  grid-template-columns: 280px 1fr 260px;
  gap: 1px;
  flex: 1;
  min-height: 0;
  background: #1c2a3a;
}

/* ── Panels ─────────────────────────────────────────────────────────────────── */
.gv-panel {
  background: #0d1117;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid #1c2a3a;
  background: #111820;
  flex-shrink: 0;
}

.panel-title {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 2px;
  color: #4a8ab0;
}

.panel-badge {
  font-size: 10px;
  background: #1c2a3a;
  color: #7a9ab8;
  padding: 1px 6px;
  border-radius: 10px;
}

.panel-badge.badge-green { background: #001a10; color: #00c97a; }
.panel-badge.badge-red { background: #1a0010; color: #e05050; }
.panel-badge.badge-amber { background: #1a1000; color: #f0a030; }

.panel-content {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
  scrollbar-width: thin;
  scrollbar-color: #2a3d52 transparent;
}

.panel-content::-webkit-scrollbar { width: 4px; }
.panel-content::-webkit-scrollbar-track { background: transparent; }
.panel-content::-webkit-scrollbar-thumb { background: #2a3d52; border-radius: 2px; }

/* ── Contract Cards ─────────────────────────────────────────────────────────── */
.contract-card {
  border: 1px solid #1c2a3a;
  border-radius: 4px;
  padding: 8px 10px;
  margin-bottom: 6px;
  cursor: pointer;
  transition: border-color 0.15s;
}

.contract-card:hover { border-color: #2a4a6a; }
.contract-card.selected { border-color: #00d4aa; background: #001a14; }

.cc-question {
  font-size: 11px;
  color: #c8d6e5;
  margin-bottom: 4px;
  line-height: 1.4;
}

.cc-meta {
  display: flex;
  gap: 6px;
  font-size: 10px;
  color: #4a6080;
  margin-bottom: 4px;
}

.cc-price strong { color: #00d4aa; }
.cc-sep { color: #2a3d52; }

.cc-keywords {
  display: flex;
  flex-wrap: wrap;
  gap: 3px;
}

.kw-tag {
  background: #1c2a3a;
  color: #5a8ab0;
  padding: 1px 5px;
  border-radius: 2px;
  font-size: 9px;
  letter-spacing: 0.5px;
}

/* ── Signal Cards ─────────────────────────────────────────────────────────── */
.signal-card {
  border: 1px solid #1c2a3a;
  border-radius: 4px;
  padding: 10px 12px;
  margin-bottom: 8px;
  transition: border-color 0.15s;
}

.sc-buy-yes { border-left: 3px solid #00c97a; }
.sc-buy-no { border-left: 3px solid #e05050; }
.sc-hold { border-left: 3px solid #f0a030; }

.sig-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.sig-direction {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 1px;
}

.sig-strength {
  font-size: 9px;
  letter-spacing: 1px;
  padding: 1px 5px;
  border-radius: 2px;
}

.strength-strong { background: #001a10; color: #00c97a; }
.strength-moderate { background: #1a1200; color: #f0a030; }
.strength-weak { background: #1a1a1a; color: #5a6a7a; }

.sig-alpha {
  margin-left: auto;
  font-size: 12px;
  font-weight: 700;
}

.sig-question {
  font-size: 11px;
  color: #a0b4c8;
  margin-bottom: 6px;
  line-height: 1.4;
}

.sig-prices {
  display: flex;
  gap: 8px;
  font-size: 11px;
  color: #4a6080;
  margin-bottom: 5px;
  align-items: center;
}

.sig-prices .sep { color: #2a3d52; }
.sig-prices strong { color: #c8d6e5; }

.sig-bar { margin-bottom: 6px; }

.sig-bar-track {
  height: 4px;
  background: #1c2a3a;
  border-radius: 2px;
  overflow: hidden;
  position: relative;
}

.mt2 { margin-top: 2px; }

.sig-bar-market { height: 100%; background: #3a5a7a; border-radius: 2px; transition: width 0.5s; }
.sig-bar-engine { height: 100%; border-radius: 2px; transition: width 0.5s; }
.bar-green { background: #00c97a; }
.bar-red { background: #e05050; }
.bar-amber { background: #f0a030; }

.sig-stats {
  display: flex;
  gap: 12px;
  font-size: 10px;
  color: #4a6080;
  margin-bottom: 6px;
}

.sig-reasoning {
  font-size: 10px;
  color: #4a7090;
  font-style: italic;
  border-top: 1px solid #1c2a3a;
  padding-top: 5px;
  line-height: 1.4;
}

/* ── Consensus Panel ─────────────────────────────────────────────────────────── */
.cons-section {
  margin-bottom: 16px;
}

.cons-label {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 2px;
  color: #3a5a7a;
  margin-bottom: 6px;
  border-bottom: 1px solid #1c2a3a;
  padding-bottom: 3px;
}

.cons-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 3px;
  font-size: 10px;
}

.cons-round { color: #3a5a7a; width: 24px; flex-shrink: 0; }
.cons-val { width: 36px; text-align: right; flex-shrink: 0; }

.cons-sentiment-bar {
  flex: 1;
  height: 6px;
  background: #1c2a3a;
  border-radius: 3px;
  position: relative;
  overflow: hidden;
}

.csb-fill {
  position: absolute;
  height: 100%;
  border-radius: 3px;
  max-width: 50%;
}

.sb-pos { background: #00c97a; left: 50%; right: auto; }
.sb-neg { background: #e05050; right: 50%; left: auto; }

/* Signal breakdown rows */
.cons-sig-row {
  margin-bottom: 6px;
}

.csr-question {
  font-size: 10px;
  color: #5a7a9a;
  margin-bottom: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.csr-bar-wrap {
  height: 4px;
  background: #1c2a3a;
  border-radius: 2px;
  overflow: hidden;
  margin-bottom: 2px;
}

.csr-bar { height: 100%; border-radius: 2px; transition: width 0.5s; }

.csr-pct {
  font-size: 10px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 4px;
}

.csr-dir { font-size: 11px; }

/* Decision rows */
.decision-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 2px 0;
  font-size: 10px;
  border-bottom: 1px solid #0f1820;
}

.dr-agent { color: #3a5a7a; width: 50px; flex-shrink: 0; }
.dr-type { flex: 1; font-weight: 600; letter-spacing: 0.5px; }
.dr-r { color: #2a3d52; }

/* ── Empty State ─────────────────────────────────────────────────────────────── */
.gv-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: #2a3d52;
}

.ge-icon {
  font-size: 48px;
  color: #1c2a3a;
}

.ge-msg {
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 2px;
  color: #3a5a7a;
}

.ge-sub {
  font-size: 11px;
  color: #2a3d52;
  max-width: 400px;
  text-align: center;
  line-height: 1.6;
}

/* ── Loading / Empty ─────────────────────────────────────────────────────────── */
.loading-msg {
  color: #3a5a7a;
  font-size: 11px;
  padding: 16px 0;
  text-align: center;
  letter-spacing: 1px;
}

.empty-msg {
  color: #2a3d52;
  font-size: 11px;
  padding: 16px 0;
  text-align: center;
}

.empty-msg.small { padding: 8px 0; }

/* ── Feed ─────────────────────────────────────────────────────────────────── */
.gv-feed {
  border-top: 1px solid #1c2a3a;
  background: #0a0c0f;
  flex-shrink: 0;
  height: 120px;
  display: flex;
  flex-direction: column;
}

.feed-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 4px 16px;
  border-bottom: 1px solid #1c2a3a;
  background: #0d1117;
}

.feed-title {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 2px;
  color: #3a5a7a;
}

.feed-count {
  font-size: 10px;
  color: #2a3d52;
}

.feed-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 4px 16px;
  scrollbar-width: thin;
  scrollbar-color: #1c2a3a transparent;
}

.feed-scroll::-webkit-scrollbar { width: 3px; }
.feed-scroll::-webkit-scrollbar-thumb { background: #1c2a3a; }

.feed-item {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 2px 0;
  border-bottom: 1px solid #0f1820;
  font-size: 10px;
  color: #4a6080;
  overflow: hidden;
}

.feed-item.fi-pos .fi-content { color: #3a8a5a; }
.feed-item.fi-neg .fi-content { color: #8a3a3a; }

.fi-time { color: #2a3d52; width: 24px; flex-shrink: 0; }
.fi-agent { color: #3a6a8a; width: 52px; flex-shrink: 0; font-weight: 600; }
.fi-sep { color: #2a3d52; }
.fi-content { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fi-sentiment { flex-shrink: 0; font-weight: 600; width: 36px; text-align: right; }

/* ── Color Utilities ─────────────────────────────────────────────────────────── */
.green { color: #00c97a; }
.red { color: #e05050; }
.amber { color: #f0a030; }

/* ── Tabs ─────────────────────────────────────────────────────────────────── */
.gv-tabs {
  display: flex;
  align-items: center;
  gap: 1px;
  padding: 0 16px;
  background: #0d1117;
  border-bottom: 1px solid #1c2a3a;
  flex-shrink: 0;
}

.gv-tab {
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: #4a6080;
  padding: 6px 14px;
  font-family: inherit;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 1px;
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
  margin-bottom: -1px;
}

.gv-tab:hover {
  color: #7a9ab8;
}

.gv-tab.active {
  color: #00d4aa;
  border-bottom-color: #00d4aa;
}

/* ── Tab content wrapper ─────────────────────────────────────────────────── */
.gv-tab-content {
  flex: 1;
  min-height: 0;
  overflow: auto;
  background: #0d1117;
}
</style>
