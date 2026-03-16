<template>
  <div class="macro-timeline">
    <div class="timeline-header">
      <h3 class="timeline-title">宏觀經濟走勢</h3>
      <span class="round-badge" v-if="history.length">
        已記錄 {{ history.length }} 個輪次
      </span>
    </div>

    <div v-if="loading" class="timeline-loading">
      <span class="spinner"></span>
      <span>載入中…</span>
    </div>

    <div v-else-if="error" class="timeline-error">
      {{ error }}
    </div>

    <div v-else-if="history.length === 0" class="timeline-empty">
      尚無宏觀快照。模擬進行 5 輪後將自動生成。
    </div>

    <div v-else class="timeline-body">
      <!-- Metric selector tabs -->
      <div class="metric-tabs">
        <button
          v-for="m in metrics"
          :key="m.key"
          class="metric-tab"
          :class="{ active: activeMetric === m.key }"
          @click="activeMetric = m.key"
        >
          {{ m.label }}
        </button>
      </div>

      <!-- Bar chart for selected metric -->
      <div class="chart-area" v-if="chartData.length">
        <div class="chart-y-labels">
          <span class="y-max">{{ formatValue(chartMax, activeMetric) }}</span>
          <span class="y-mid">{{ formatValue((chartMax + chartMin) / 2, activeMetric) }}</span>
          <span class="y-min">{{ formatValue(chartMin, activeMetric) }}</span>
        </div>
        <div class="chart-bars">
          <div
            v-for="item in chartData"
            :key="item.round"
            class="bar-col"
            @mouseenter="hoveredRound = item.round"
            @mouseleave="hoveredRound = null"
          >
            <div class="bar-wrapper">
              <div
                class="bar"
                :style="barStyle(item)"
                :class="barClass(item)"
              ></div>
              <div class="bar-tooltip" v-if="hoveredRound === item.round">
                <strong>第 {{ item.round }} 輪</strong><br />
                {{ activeMetricLabel }}: {{ formatValue(item.value, activeMetric) }}
              </div>
            </div>
            <span class="bar-label">{{ item.round }}</span>
          </div>
        </div>
      </div>

      <!-- Summary table -->
      <div class="summary-table-wrap">
        <table class="summary-table">
          <thead>
            <tr>
              <th>輪次</th>
              <th v-for="m in metrics" :key="m.key">{{ m.label }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in history" :key="row.round_number">
              <td class="round-cell">{{ row.round_number }}</td>
              <td v-for="m in metrics" :key="m.key" :class="trendClass(row, m.key)">
                {{ formatValue(row[m.key], m.key) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { getMacroHistory } from '@/api/simulation'

// ── Props ────────────────────────────────────────────────────────────────────
const props = defineProps({
  sessionId: {
    type: String,
    required: true,
  },
  /** Auto-refresh interval in milliseconds. 0 = no auto-refresh. */
  refreshInterval: {
    type: Number,
    default: 30_000,
  },
})

// ── State ────────────────────────────────────────────────────────────────────
const history = ref([])
const loading = ref(false)
const error = ref(null)
const hoveredRound = ref(null)
const activeMetric = ref('consumer_confidence')
let _timer = null

// ── Metrics config ───────────────────────────────────────────────────────────
const metrics = [
  { key: 'consumer_confidence', label: '消費信心' },
  { key: 'hsi_level',           label: '恒生指數' },
  { key: 'unemployment_rate',   label: '失業率' },
  { key: 'ccl_index',           label: 'CCL指數' },
  { key: 'gdp_growth',          label: 'GDP增長' },
  { key: 'net_migration',       label: '淨遷移' },
]

const activeMetricLabel = computed(
  () => metrics.find(m => m.key === activeMetric.value)?.label ?? activeMetric.value
)

// ── Chart derived data ───────────────────────────────────────────────────────
const chartData = computed(() =>
  history.value.map(row => ({
    round: row.round_number,
    value: row[activeMetric.value] ?? 0,
  }))
)

const chartMax = computed(() => {
  const vals = chartData.value.map(d => d.value)
  return vals.length ? Math.max(...vals) : 1
})

const chartMin = computed(() => {
  const vals = chartData.value.map(d => d.value)
  return vals.length ? Math.min(...vals) : 0
})

function barStyle(item) {
  const range = chartMax.value - chartMin.value || 1
  const pct = ((item.value - chartMin.value) / range) * 80 + 5
  return { height: `${Math.max(4, pct)}%` }
}

function barClass(item) {
  if (activeMetric.value === 'unemployment_rate') {
    // Higher unemployment = bad (red)
    return item.value > chartData.value[0]?.value ? 'bar-bad' : 'bar-good'
  }
  if (activeMetric.value === 'net_migration') {
    return item.value < 0 ? 'bar-bad' : 'bar-good'
  }
  // For most metrics, higher = good
  return item.value >= (chartData.value[0]?.value ?? item.value) ? 'bar-good' : 'bar-bad'
}

// ── Trend cell colouring ─────────────────────────────────────────────────────
function trendClass(row, key) {
  const idx = history.value.indexOf(row)
  if (idx === 0) return ''
  const prev = history.value[idx - 1][key]
  const curr = row[key]
  if (prev == null || curr == null) return ''
  // For unemployment/negative metrics: increase = bad
  const isNegativeMetric = key === 'unemployment_rate' || key === 'net_migration'
  if (curr > prev) return isNegativeMetric ? 'cell-bad' : 'cell-good'
  if (curr < prev) return isNegativeMetric ? 'cell-good' : 'cell-bad'
  return ''
}

// ── Formatting ───────────────────────────────────────────────────────────────
function formatValue(val, key) {
  if (val == null) return '—'
  switch (key) {
    case 'unemployment_rate':
    case 'gdp_growth':
      return `${(val * 100).toFixed(2)}%`
    case 'hsi_level':
      return val.toLocaleString('zh-HK', { maximumFractionDigits: 0 })
    case 'ccl_index':
      return val.toFixed(1)
    case 'consumer_confidence':
      return val.toFixed(1)
    case 'net_migration':
      return val.toLocaleString('zh-HK', { signDisplay: 'always' })
    default:
      return String(val)
  }
}

// ── Data fetching ─────────────────────────────────────────────────────────────
async function fetchHistory() {
  if (!props.sessionId) return
  loading.value = true
  error.value = null
  try {
    const resp = await getMacroHistory(props.sessionId)
    history.value = resp.data?.data ?? []
  } catch (err) {
    error.value = `載入失敗：${err.message ?? '未知錯誤'}`
  } finally {
    loading.value = false
  }
}

function startAutoRefresh() {
  stopAutoRefresh()
  if (props.refreshInterval > 0) {
    _timer = setInterval(fetchHistory, props.refreshInterval)
  }
}

function stopAutoRefresh() {
  if (_timer) {
    clearInterval(_timer)
    _timer = null
  }
}

// ── Lifecycle ────────────────────────────────────────────────────────────────
onMounted(() => {
  fetchHistory()
  startAutoRefresh()
})

watch(() => props.sessionId, () => {
  fetchHistory()
  startAutoRefresh()
})
</script>

<style scoped>
.macro-timeline {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 16px;
  color: var(--text-secondary);
  font-size: 13px;
  box-shadow: var(--shadow-card);
}

.timeline-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.timeline-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.round-badge {
  background: var(--bg-secondary);
  border-radius: 12px;
  padding: 2px 10px;
  font-size: 11px;
  color: var(--text-muted);
}

.timeline-loading,
.timeline-error,
.timeline-empty {
  padding: 24px;
  text-align: center;
  color: var(--text-muted);
}

.timeline-error {
  color: var(--accent-red);
}

.spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid var(--accent-blue);
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
  margin-right: 8px;
  vertical-align: middle;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ── Metric tabs ── */
.metric-tabs {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.metric-tab {
  padding: 4px 10px;
  border-radius: 6px;
  border: 1px solid var(--border-color);
  background: var(--bg-primary);
  color: var(--text-muted);
  cursor: pointer;
  font-size: 12px;
  transition: background 0.15s, color 0.15s;
}

.metric-tab:hover {
  background: var(--bg-secondary);
  color: var(--text-secondary);
}

.metric-tab.active {
  background: var(--accent-blue);
  border-color: var(--accent-blue);
  color: #0d1117;
}

/* ── Chart ── */
.chart-area {
  display: flex;
  height: 120px;
  margin-bottom: 16px;
  gap: 8px;
}

.chart-y-labels {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  font-size: 10px;
  color: var(--text-muted);
  width: 48px;
  text-align: right;
  padding-bottom: 20px;
}

.chart-bars {
  display: flex;
  align-items: flex-end;
  gap: 4px;
  flex: 1;
  overflow-x: auto;
  padding-bottom: 20px;
  position: relative;
}

.bar-col {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 28px;
  flex: 1;
  position: relative;
}

.bar-wrapper {
  width: 100%;
  height: 100px;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  position: relative;
}

.bar {
  width: 100%;
  border-radius: 3px 3px 0 0;
  transition: height 0.3s ease;
  cursor: pointer;
}

.bar-good {
  background: #22c55e;
}

.bar-bad {
  background: #ef4444;
}

.bar:hover {
  filter: brightness(1.2);
}

.bar-tooltip {
  position: absolute;
  bottom: 110%;
  left: 50%;
  transform: translateX(-50%);
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 11px;
  white-space: nowrap;
  z-index: 10;
  pointer-events: none;
  color: var(--text-primary);
  box-shadow: var(--shadow-md);
}

.bar-label {
  font-size: 10px;
  color: var(--text-muted);
  margin-top: 2px;
}

/* ── Summary table ── */
.summary-table-wrap {
  overflow-x: auto;
}

.summary-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.summary-table th {
  background: var(--bg-secondary);
  color: var(--text-muted);
  padding: 6px 10px;
  text-align: right;
  border-bottom: 1px solid var(--border-color);
  white-space: nowrap;
}

.summary-table th:first-child,
.summary-table td:first-child {
  text-align: center;
}

.summary-table td {
  padding: 5px 10px;
  text-align: right;
  border-bottom: 1px solid var(--border-color);
  color: var(--text-secondary);
}

.round-cell {
  color: var(--text-muted);
  font-size: 11px;
}

.cell-good {
  color: var(--accent-green);
}

.cell-bad {
  color: var(--accent-red);
}
</style>
