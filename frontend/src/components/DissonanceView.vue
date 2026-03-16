<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { getCognitiveDissonance } from '@/api/simulation'

const props = defineProps({
  sessionId: { type: String, required: true },
  refreshInterval: { type: Number, default: 30000 },
})

const agents = ref([])
const loading = ref(false)
const error = ref(null)
const minScore = ref(0.5)
let _timer = null

const STRATEGY_LABELS = {
  denial: '否認',
  rationalization: '合理化',
  belief_change: '信念改變',
  none: '未解決',
}

const STRATEGY_CLASSES = {
  denial: 'strat-denial',
  rationalization: 'strat-rational',
  belief_change: 'strat-change',
  none: 'strat-none',
}

async function fetchData() {
  if (!props.sessionId) return
  loading.value = true
  error.value = null
  try {
    const res = await getCognitiveDissonance(props.sessionId, { min_score: minScore.value })
    agents.value = res.data?.data || []
  } catch (err) {
    error.value = `載入失敗：${err.message || '未知錯誤'}`
  } finally {
    loading.value = false
  }
}

function startAutoRefresh() {
  stopAutoRefresh()
  if (props.refreshInterval > 0) {
    _timer = setInterval(fetchData, props.refreshInterval)
  }
}

function stopAutoRefresh() {
  if (_timer) { clearInterval(_timer); _timer = null }
}

function scoreColor(score) {
  if (score >= 0.7) return '#ef4444'
  if (score >= 0.5) return '#f59e0b'
  return '#6b7280'
}

function formatPairs(pairs) {
  if (!pairs) return '—'
  if (typeof pairs === 'string') {
    try { pairs = JSON.parse(pairs) } catch { return pairs }
  }
  if (Array.isArray(pairs)) {
    return pairs.map(p => {
      if (Array.isArray(p)) return p.join(' vs ')
      return String(p)
    }).join('、')
  }
  return String(pairs)
}

const sortedAgents = computed(() =>
  [...agents.value].sort((a, b) => (b.dissonance_score || 0) - (a.dissonance_score || 0))
)

const avgScore = computed(() => {
  if (agents.value.length === 0) return 0
  const sum = agents.value.reduce((acc, a) => acc + (a.dissonance_score || 0), 0)
  return sum / agents.value.length
})

function handleMinScoreChange(e) {
  minScore.value = parseFloat(e.target.value)
  fetchData()
}

onMounted(() => {
  fetchData()
  startAutoRefresh()
})

watch(() => props.sessionId, () => {
  fetchData()
  startAutoRefresh()
})
</script>

<template>
  <div class="dissonance-view">
    <div class="dv-header">
      <h3 class="dv-title">認知失調監測</h3>
      <div class="dv-controls">
        <label class="min-score-label">
          最低分數:
          <input
            type="range"
            :value="minScore"
            min="0"
            max="1"
            step="0.1"
            class="min-score-slider"
            @change="handleMinScoreChange"
          />
          <span class="min-score-value">{{ minScore.toFixed(1) }}</span>
        </label>
      </div>
    </div>

    <!-- Summary -->
    <div v-if="agents.length > 0" class="summary-bar">
      <span class="summary-item">
        {{ agents.length }} 個代理人出現認知失調
      </span>
      <span class="summary-item">
        平均分數: <strong>{{ avgScore.toFixed(2) }}</strong>
      </span>
    </div>

    <div v-if="loading && agents.length === 0" class="state-msg">
      <span class="spinner" /> 載入中...
    </div>
    <div v-else-if="error" class="state-msg state-error">{{ error }}</div>
    <div v-else-if="sortedAgents.length === 0" class="state-msg">
      目前無顯著認知失調
    </div>

    <div v-else class="agent-list">
      <div
        v-for="agent in sortedAgents"
        :key="agent.agent_id"
        class="agent-card"
      >
        <div class="agent-top">
          <div class="agent-name">{{ agent.username || `Agent #${agent.agent_id}` }}</div>
          <div
            class="score-badge"
            :style="{ background: scoreColor(agent.dissonance_score || 0) }"
          >
            {{ ((agent.dissonance_score || 0) * 100).toFixed(0) }}%
          </div>
        </div>

        <div v-if="agent.conflicting_pairs" class="conflict-section">
          <span class="conflict-label">衝突信念:</span>
          <span class="conflict-pairs">{{ formatPairs(agent.conflicting_pairs) }}</span>
        </div>

        <div v-if="agent.action_belief_gap" class="gap-section">
          <span class="gap-label">行為-信念差距:</span>
          <span class="gap-value">{{ ((agent.action_belief_gap || 0) * 100).toFixed(0) }}%</span>
        </div>

        <div class="strategy-section">
          <span class="strategy-label">解決策略:</span>
          <span
            class="strategy-badge"
            :class="STRATEGY_CLASSES[agent.resolution_strategy] || 'strat-none'"
          >
            {{ STRATEGY_LABELS[agent.resolution_strategy] || agent.resolution_strategy || '未知' }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dissonance-view {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 16px;
  box-shadow: var(--shadow-card);
}

.dv-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  flex-wrap: wrap;
  gap: 8px;
}

.dv-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.min-score-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-muted);
}

.min-score-slider {
  width: 80px;
  cursor: pointer;
}

.min-score-value {
  font-weight: 600;
  color: var(--text-primary);
  min-width: 24px;
}

.summary-bar {
  display: flex;
  gap: 16px;
  padding: 8px 12px;
  background: var(--bg-secondary);
  border-radius: 6px;
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 12px;
}

.summary-item strong { color: var(--text-primary); }

.state-msg {
  text-align: center;
  padding: 24px;
  color: var(--text-muted);
  font-size: 13px;
}

.state-error { color: var(--accent-red); }

.spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid var(--accent-blue);
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
  margin-right: 6px;
  vertical-align: middle;
}

@keyframes spin { to { transform: rotate(360deg); } }

.agent-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 400px;
  overflow-y: auto;
}

.agent-card {
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 10px 12px;
  transition: border-color 0.15s;
}

.agent-card:hover { border-color: var(--accent-blue); }

.agent-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}

.agent-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.score-badge {
  font-size: 12px;
  font-weight: 700;
  color: #0d1117;
  padding: 2px 8px;
  border-radius: 4px;
}

.conflict-section,
.gap-section,
.strategy-section {
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 4px;
}

.conflict-label,
.gap-label,
.strategy-label {
  color: var(--text-muted);
  margin-right: 4px;
}

.conflict-pairs { font-weight: 500; }

.gap-value { font-weight: 600; color: var(--accent-orange); }

.strategy-badge {
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 10px;
}

.strat-denial { background: rgba(255, 68, 68, 0.15); color: var(--accent-red); }
.strat-rational { background: rgba(255, 159, 67, 0.15); color: var(--accent-orange); }
.strat-change { background: rgba(0, 217, 101, 0.15); color: var(--accent-green); }
.strat-none { background: var(--bg-secondary); color: var(--text-muted); }
</style>
