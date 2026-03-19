<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { getFilterBubble, getFilterBubbleHistory } from '@/api/simulation'

const props = defineProps({
  sessionId: { type: String, required: true },
  refreshInterval: { type: Number, default: 30000 },
})

const report = ref(null)
const history = ref([])
const loading = ref(false)
const error = ref(null)
const activeView = ref('report')
let _timer = null

async function fetchData() {
  if (!props.sessionId) return
  loading.value = true
  error.value = null
  try {
    const [reportRes, histRes] = await Promise.allSettled([
      getFilterBubble(props.sessionId),
      getFilterBubbleHistory(props.sessionId),
    ])
    if (reportRes.status === 'fulfilled') {
      report.value = reportRes.value.data?.data || null
    }
    if (histRes.status === 'fulfilled') {
      history.value = histRes.value.data?.data || []
    }
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

const bubblePct = computed(() => {
  if (!report.value?.pct_in_bubble) return 0
  return Math.round(report.value.pct_in_bubble * 100)
})

const giniPct = computed(() => {
  if (!report.value?.gini_coefficient) return 0
  return Math.round(report.value.gini_coefficient * 100)
})

function bubbleLevel(score) {
  if (score >= 0.7) return { label: '嚴重', cls: 'level-high' }
  if (score >= 0.4) return { label: '中等', cls: 'level-medium' }
  return { label: '輕微', cls: 'level-low' }
}

// Chart data for history
const chartMax = computed(() => {
  if (history.value.length === 0) return 1
  return Math.max(...history.value.map(h => h.avg_bubble_score || 0), 0.1)
})

function barHeight(val) {
  const pct = (val / chartMax.value) * 80 + 5
  return `${Math.max(4, pct)}%`
}

function barColor(val) {
  if (val >= 0.7) return '#ef4444'
  if (val >= 0.4) return '#f59e0b'
  return '#22c55e'
}

onMounted(() => {
  fetchData()
  startAutoRefresh()
})

watch(() => props.sessionId, () => {
  stopAutoRefresh()
  fetchData()
  startAutoRefresh()
})

onUnmounted(stopAutoRefresh)
</script>

<template>
  <div class="bubble-chart">
    <div class="chart-header">
      <h3 class="chart-title">過濾氣泡分析</h3>
      <div class="view-toggle">
        <button
          class="toggle-btn"
          :class="{ active: activeView === 'report' }"
          @click="activeView = 'report'"
        >
          報告
        </button>
        <button
          class="toggle-btn"
          :class="{ active: activeView === 'history' }"
          @click="activeView = 'history'"
        >
          趨勢
        </button>
      </div>
    </div>

    <div v-if="loading && !report" class="state-msg">
      <span class="spinner" /> 載入中...
    </div>
    <div v-else-if="error" class="state-msg state-error">{{ error }}</div>
    <div v-else-if="!report && history.length === 0" class="state-msg">
      尚無過濾氣泡數據
    </div>

    <!-- Report view -->
    <div v-else-if="activeView === 'report' && report" class="report-body">
      <div class="stat-grid">
        <div class="stat-card">
          <div class="stat-label">平均氣泡分數</div>
          <div class="stat-value" :class="bubbleLevel(report.avg_bubble_score || 0).cls">
            {{ ((report.avg_bubble_score || 0) * 100).toFixed(1) }}%
          </div>
          <div class="stat-sub" :class="bubbleLevel(report.avg_bubble_score || 0).cls">
            {{ bubbleLevel(report.avg_bubble_score || 0).label }}
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-label">中位數</div>
          <div class="stat-value">
            {{ ((report.median_bubble_score || 0) * 100).toFixed(1) }}%
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-label">氣泡中佔比</div>
          <div class="stat-value pct-badge" :class="bubblePct > 50 ? 'level-high' : 'level-low'">
            {{ bubblePct }}%
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-label">基尼係數</div>
          <div class="stat-value">{{ giniPct }}%</div>
          <div class="stat-sub">信息不平等</div>
        </div>
      </div>

      <!-- Diversity gauge -->
      <div v-if="report.avg_exposure_diversity != null" class="gauge-section">
        <div class="gauge-label">曝光多樣性</div>
        <div class="gauge-track">
          <div
            class="gauge-fill"
            :style="{ width: ((report.avg_exposure_diversity || 0) * 100) + '%' }"
          />
        </div>
        <div class="gauge-value">{{ ((report.avg_exposure_diversity || 0) * 100).toFixed(0) }}%</div>
      </div>
    </div>

    <!-- History view -->
    <div v-else-if="activeView === 'history' && history.length > 0" class="history-body">
      <div class="history-chart">
        <div
          v-for="h in history"
          :key="h.round_number"
          class="hist-col"
          :title="`第 ${h.round_number} 輪：${((h.avg_bubble_score || 0) * 100).toFixed(1)}%`"
        >
          <div class="hist-bar-wrap">
            <div
              class="hist-bar"
              :style="{ height: barHeight(h.avg_bubble_score || 0), background: barColor(h.avg_bubble_score || 0) }"
            />
          </div>
          <span class="hist-label">{{ h.round_number }}</span>
        </div>
      </div>
      <div class="history-legend">
        <span class="legend-item"><span class="legend-dot" style="background:#22c55e" /> 低</span>
        <span class="legend-item"><span class="legend-dot" style="background:#f59e0b" /> 中</span>
        <span class="legend-item"><span class="legend-dot" style="background:#ef4444" /> 高</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.bubble-chart {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 16px;
  box-shadow: var(--shadow-card);
}

.chart-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.chart-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.view-toggle {
  display: flex;
  gap: 0;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  overflow: hidden;
}

.toggle-btn {
  padding: 4px 12px;
  border: none;
  background: var(--bg-primary);
  color: var(--text-muted);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s;
}

.toggle-btn.active {
  background: var(--accent-blue);
  color: #0d1117;
}

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

.stat-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-bottom: 14px;
}

.stat-card {
  background: var(--bg-secondary);
  border-radius: 8px;
  padding: 12px;
  text-align: center;
}

.stat-label {
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 4px;
}

.stat-value {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
}

.stat-sub {
  font-size: 10px;
  margin-top: 2px;
}

.level-high { color: #ef4444; }
.level-medium { color: #f59e0b; }
.level-low { color: #22c55e; }

.gauge-section {
  display: flex;
  align-items: center;
  gap: 10px;
}

.gauge-label {
  font-size: 12px;
  color: var(--text-muted);
  min-width: 80px;
}

.gauge-track {
  flex: 1;
  height: 8px;
  background: var(--bg-secondary);
  border-radius: 4px;
  overflow: hidden;
}

.gauge-fill {
  height: 100%;
  background: var(--accent-blue);
  border-radius: 4px;
  transition: width 0.3s;
}

.gauge-value {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  min-width: 36px;
  text-align: right;
}

.history-body { margin-top: 8px; }

.history-chart {
  display: flex;
  align-items: flex-end;
  gap: 4px;
  height: 100px;
  padding-bottom: 20px;
}

.hist-col {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: 1;
  min-width: 20px;
}

.hist-bar-wrap {
  width: 100%;
  height: 80px;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
}

.hist-bar {
  width: 100%;
  border-radius: 3px 3px 0 0;
  transition: height 0.3s;
}

.hist-label {
  font-size: 9px;
  color: var(--text-muted);
  margin-top: 2px;
}

.history-legend {
  display: flex;
  gap: 12px;
  justify-content: center;
  margin-top: 8px;
  font-size: 11px;
  color: var(--text-muted);
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
</style>
