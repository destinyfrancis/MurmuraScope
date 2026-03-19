<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { getEmotionalHeatmap } from '@/api/simulation'

const props = defineProps({
  sessionId: { type: String, required: true },
  refreshInterval: { type: Number, default: 30000 },
})

const heatmapData = ref([])
const loading = ref(false)
const error = ref(null)
const selectedDimension = ref('valence')
const hoveredAgent = ref(null)
let _timer = null

const DIMENSIONS = [
  { key: 'valence', label: '效價', range: [-1, 1], desc: '正面/負面情緒' },
  { key: 'arousal', label: '激發度', range: [0, 1], desc: '平靜/激動程度' },
  { key: 'dominance', label: '主導感', range: [0, 1], desc: '控制力/無力感' },
]

async function fetchData() {
  if (!props.sessionId) return
  loading.value = true
  error.value = null
  try {
    const res = await getEmotionalHeatmap(props.sessionId)
    heatmapData.value = res.data?.data || []
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

const activeDim = computed(() =>
  DIMENSIONS.find(d => d.key === selectedDimension.value) || DIMENSIONS[0]
)

function cellColor(agent) {
  const val = agent[selectedDimension.value] ?? 0
  const dim = activeDim.value
  const [min, max] = dim.range
  const normalized = (val - min) / (max - min)

  if (selectedDimension.value === 'valence') {
    // Red (negative) → Gray (neutral) → Green (positive)
    if (val < 0) {
      const intensity = Math.abs(val)
      return `rgba(239, 68, 68, ${0.15 + intensity * 0.7})`
    }
    return `rgba(34, 197, 94, ${0.15 + val * 0.7})`
  }
  if (selectedDimension.value === 'arousal') {
    // Blue (calm) → Red (aroused)
    return `rgba(239, 68, 68, ${0.1 + normalized * 0.7})`
  }
  // Dominance: purple gradient
  return `rgba(147, 51, 234, ${0.1 + normalized * 0.7})`
}

function cellTooltip(agent) {
  const v = agent.valence?.toFixed(2) ?? '—'
  const a = agent.arousal?.toFixed(2) ?? '—'
  const d = agent.dominance?.toFixed(2) ?? '—'
  const name = agent.username || `Agent #${agent.agent_id}`
  return `${name}\n效價: ${v} | 激發度: ${a} | 主導感: ${d}`
}

// Summary stats
const avgVal = computed(() => {
  if (heatmapData.value.length === 0) return 0
  const sum = heatmapData.value.reduce((acc, a) => acc + (a[selectedDimension.value] || 0), 0)
  return sum / heatmapData.value.length
})

const highArousalCount = computed(() =>
  heatmapData.value.filter(a => (a.arousal || 0) > 0.7).length
)

const negativeCount = computed(() =>
  heatmapData.value.filter(a => (a.valence || 0) < -0.3).length
)

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
  <div class="emo-heatmap">
    <div class="emo-header">
      <h3 class="emo-title">情緒地圖</h3>
      <span class="emo-count" v-if="heatmapData.length">
        {{ heatmapData.length }} 個代理人
      </span>
    </div>

    <!-- Dimension selector -->
    <div class="dim-tabs">
      <button
        v-for="dim in DIMENSIONS"
        :key="dim.key"
        class="dim-tab"
        :class="{ active: selectedDimension === dim.key }"
        @click="selectedDimension = dim.key"
      >
        {{ dim.label }}
      </button>
    </div>

    <div v-if="loading && heatmapData.length === 0" class="state-msg">
      <span class="spinner" /> 載入中...
    </div>
    <div v-else-if="error" class="state-msg state-error">{{ error }}</div>
    <div v-else-if="heatmapData.length === 0" class="state-msg">
      尚無情緒狀態數據
    </div>

    <template v-else>
      <!-- Summary stats -->
      <div class="summary-row">
        <div class="summary-stat">
          <span class="summary-label">平均{{ activeDim.label }}</span>
          <span class="summary-value">{{ avgVal.toFixed(2) }}</span>
        </div>
        <div class="summary-stat">
          <span class="summary-label">高激發度</span>
          <span class="summary-value warn">{{ highArousalCount }}</span>
        </div>
        <div class="summary-stat">
          <span class="summary-label">負面情緒</span>
          <span class="summary-value danger">{{ negativeCount }}</span>
        </div>
      </div>

      <!-- Heatmap grid -->
      <div class="heatmap-grid">
        <div
          v-for="agent in heatmapData"
          :key="agent.agent_id"
          class="heatmap-cell"
          :style="{ background: cellColor(agent) }"
          :title="cellTooltip(agent)"
          @mouseenter="hoveredAgent = agent"
          @mouseleave="hoveredAgent = null"
        />
      </div>

      <!-- Legend -->
      <div class="emo-legend">
        <template v-if="selectedDimension === 'valence'">
          <span class="legend-label">負面</span>
          <div class="legend-bar valence-bar" />
          <span class="legend-label">正面</span>
        </template>
        <template v-else-if="selectedDimension === 'arousal'">
          <span class="legend-label">平靜</span>
          <div class="legend-bar arousal-bar" />
          <span class="legend-label">激動</span>
        </template>
        <template v-else>
          <span class="legend-label">低</span>
          <div class="legend-bar dominance-bar" />
          <span class="legend-label">高</span>
        </template>
      </div>

      <!-- Hover detail -->
      <div v-if="hoveredAgent" class="hover-detail">
        <strong>{{ hoveredAgent.username || `Agent #${hoveredAgent.agent_id}` }}</strong>
        <span>效價: {{ (hoveredAgent.valence ?? 0).toFixed(2) }}</span>
        <span>激發: {{ (hoveredAgent.arousal ?? 0).toFixed(2) }}</span>
        <span>主導: {{ (hoveredAgent.dominance ?? 0).toFixed(2) }}</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.emo-heatmap {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 16px;
  box-shadow: var(--shadow-card);
}

.emo-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.emo-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.emo-count {
  font-size: 11px;
  color: var(--text-muted);
  background: var(--bg-secondary);
  padding: 2px 10px;
  border-radius: 12px;
}

.dim-tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 12px;
}

.dim-tab {
  padding: 4px 12px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-primary);
  color: var(--text-muted);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}

.dim-tab.active {
  background: var(--accent-blue);
  border-color: var(--accent-blue);
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

.summary-row {
  display: flex;
  gap: 12px;
  margin-bottom: 12px;
}

.summary-stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  background: var(--bg-secondary);
  padding: 8px 10px;
  border-radius: 6px;
  text-align: center;
}

.summary-label { font-size: 10px; color: var(--text-muted); }
.summary-value { font-size: 16px; font-weight: 700; color: var(--text-primary); }
.summary-value.warn { color: #f59e0b; }
.summary-value.danger { color: #ef4444; }

.heatmap-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
  margin-bottom: 10px;
}

.heatmap-cell {
  width: 14px;
  height: 14px;
  border-radius: 2px;
  cursor: pointer;
  transition: transform 0.1s;
}

.heatmap-cell:hover {
  transform: scale(1.8);
  z-index: 2;
}

.emo-legend {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 8px;
}

.legend-bar {
  height: 8px;
  width: 80px;
  border-radius: 2px;
}

.valence-bar {
  background: linear-gradient(to right, rgba(239, 68, 68, 0.8), rgba(156, 163, 175, 0.3), rgba(34, 197, 94, 0.8));
}

.arousal-bar {
  background: linear-gradient(to right, rgba(239, 68, 68, 0.1), rgba(239, 68, 68, 0.8));
}

.dominance-bar {
  background: linear-gradient(to right, rgba(147, 51, 234, 0.1), rgba(147, 51, 234, 0.8));
}

.hover-detail {
  display: flex;
  gap: 10px;
  align-items: center;
  font-size: 11px;
  color: var(--text-secondary);
  padding: 6px 10px;
  background: var(--bg-secondary);
  border-radius: 6px;
}

.hover-detail strong {
  color: var(--text-primary);
  margin-right: 4px;
}
</style>
