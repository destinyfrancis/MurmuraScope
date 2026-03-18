<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { getRelationshipStates } from '../api/graph.js'

const props = defineProps({
  sessionId: { type: String, required: true },
  roundNumber: { type: Number, default: -1 },
})

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const relationships = ref([])
const loading = ref(false)
const error = ref(null)
const currentRound = ref(0)
const selectedMetric = ref('intimacy')
const hoveredCell = ref(null)
const tooltipStyle = ref({ top: '0px', left: '0px' })

// ---------------------------------------------------------------------------
// Metric definitions
// ---------------------------------------------------------------------------

const METRICS = [
  { key: 'intimacy', label: '親密度' },
  { key: 'passion', label: '熱情' },
  { key: 'commitment', label: '承諾' },
  { key: 'trust', label: '信任' },
  { key: 'rusbult_commitment', label: 'Rusbult 承諾' },
]

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function fetchData() {
  if (!props.sessionId) return
  loading.value = true
  error.value = null
  try {
    const res = await getRelationshipStates(props.sessionId, props.roundNumber)
    const data = res.data
    relationships.value = data.relationships || []
    currentRound.value = data.round_number ?? 0
  } catch (err) {
    error.value = `載入失敗：${err.message || '未知錯誤'}`
  } finally {
    loading.value = false
  }
}

onMounted(fetchData)
watch(() => props.sessionId, fetchData)
watch(() => props.roundNumber, fetchData)

// ---------------------------------------------------------------------------
// Top-20 agents by total interaction_count
// ---------------------------------------------------------------------------

const topAgents = computed(() => {
  if (relationships.value.length === 0) return []

  const counts = {}
  for (const r of relationships.value) {
    counts[r.agent_a] = (counts[r.agent_a] || 0) + (r.interaction_count || 0)
    counts[r.agent_b] = (counts[r.agent_b] || 0) + (r.interaction_count || 0)
  }

  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 20)
    .map(([id]) => id)
})

// ---------------------------------------------------------------------------
// Build lookup: { "agentA__agentB": relationship }
// ---------------------------------------------------------------------------

const relLookup = computed(() => {
  const map = {}
  for (const r of relationships.value) {
    map[`${r.agent_a}__${r.agent_b}`] = r
    map[`${r.agent_b}__${r.agent_a}`] = r
  }
  return map
})

// ---------------------------------------------------------------------------
// Cell value & color
// ---------------------------------------------------------------------------

function getCellValue(agentA, agentB) {
  if (agentA === agentB) return null
  const key = `${agentA}__${agentB}`
  const rel = relLookup.value[key]
  if (!rel) return null
  return rel[selectedMetric.value] ?? null
}

function cellColor(value) {
  if (value === null) return 'var(--bg-secondary, #1a1f2e)'
  // 0 → white/grey, 1 → deep warm red
  const v = Math.max(0, Math.min(1, value))
  return `rgba(239, 68, 68, ${0.08 + v * 0.82})`
}

// ---------------------------------------------------------------------------
// Tooltip
// ---------------------------------------------------------------------------

function shortId(id) {
  return id.length > 12 ? id.slice(0, 8) + '…' : id
}

function handleCellEnter(event, agentA, agentB) {
  if (agentA === agentB) return
  const key = `${agentA}__${agentB}`
  const rel = relLookup.value[key]
  hoveredCell.value = rel ? { ...rel } : null
  if (hoveredCell.value) {
    const rect = event.target.getBoundingClientRect()
    tooltipStyle.value = {
      top: `${rect.bottom + window.scrollY + 6}px`,
      left: `${rect.left + window.scrollX}px`,
    }
  }
}

function handleCellLeave() {
  hoveredCell.value = null
}

// ---------------------------------------------------------------------------
// Legend ticks
// ---------------------------------------------------------------------------

const LEGEND_TICKS = [0, 0.25, 0.5, 0.75, 1.0]
</script>

<template>
  <div class="rel-graph">
    <!-- Header -->
    <div class="rel-header">
      <h3 class="rel-title">關係矩陣</h3>
      <span v-if="relationships.length" class="rel-round-badge">
        Round {{ currentRound }}
      </span>
    </div>

    <!-- Metric selector -->
    <div class="metric-tabs">
      <button
        v-for="m in METRICS"
        :key="m.key"
        class="metric-tab"
        :class="{ active: selectedMetric === m.key }"
        @click="selectedMetric = m.key"
      >
        {{ m.label }}
      </button>
    </div>

    <!-- Loading -->
    <div v-if="loading && relationships.length === 0" class="state-msg">
      <span class="spinner" /> 載入中...
    </div>

    <!-- Error -->
    <div v-else-if="error" class="state-msg state-error">{{ error }}</div>

    <!-- Empty -->
    <div v-else-if="relationships.length === 0" class="state-msg">
      尚無關係狀態數據。請在模擬完成後查看。
    </div>

    <!-- Matrix -->
    <template v-else>
      <div class="matrix-wrapper">
        <!-- Corner spacer + column headers -->
        <div class="matrix-col-headers">
          <div class="matrix-corner" />
          <div
            v-for="agentB in topAgents"
            :key="agentB"
            class="matrix-col-label"
            :title="agentB"
          >
            {{ shortId(agentB) }}
          </div>
        </div>

        <!-- Rows -->
        <div
          v-for="agentA in topAgents"
          :key="agentA"
          class="matrix-row"
        >
          <!-- Row label -->
          <div class="matrix-row-label" :title="agentA">
            {{ shortId(agentA) }}
          </div>

          <!-- Cells -->
          <div
            v-for="agentB in topAgents"
            :key="agentB"
            class="matrix-cell"
            :class="{ diagonal: agentA === agentB, 'has-data': getCellValue(agentA, agentB) !== null }"
            :style="{ background: agentA === agentB ? 'var(--bg-secondary, #1a1f2e)' : cellColor(getCellValue(agentA, agentB)) }"
            @mouseenter="handleCellEnter($event, agentA, agentB)"
            @mouseleave="handleCellLeave"
          />
        </div>
      </div>

      <!-- Legend -->
      <div class="rel-legend">
        <span class="legend-label">低</span>
        <div class="legend-bar" />
        <span class="legend-label">高</span>
        <div class="legend-ticks">
          <span v-for="t in LEGEND_TICKS" :key="t" class="legend-tick">
            {{ t.toFixed(2) }}
          </span>
        </div>
      </div>

      <!-- Summary stats -->
      <div class="summary-row" v-if="relationships.length">
        <div class="summary-stat">
          <span class="summary-label">關係對數</span>
          <span class="summary-value">{{ relationships.length }}</span>
        </div>
        <div class="summary-stat">
          <span class="summary-label">頂端代理人</span>
          <span class="summary-value">{{ topAgents.length }}</span>
        </div>
        <div class="summary-stat">
          <span class="summary-label">指標</span>
          <span class="summary-value">{{ METRICS.find(m => m.key === selectedMetric)?.label }}</span>
        </div>
      </div>
    </template>

    <!-- Tooltip (portal-free, absolute) -->
    <div
      v-if="hoveredCell"
      class="cell-tooltip"
      :style="tooltipStyle"
    >
      <div class="tooltip-agents">
        <strong>{{ shortId(hoveredCell.agent_a) }}</strong>
        <span class="tooltip-arrow">↔</span>
        <strong>{{ shortId(hoveredCell.agent_b) }}</strong>
      </div>
      <div class="tooltip-grid">
        <span class="tooltip-key">親密度</span>
        <span class="tooltip-val">{{ (hoveredCell.intimacy ?? 0).toFixed(3) }}</span>
        <span class="tooltip-key">熱情</span>
        <span class="tooltip-val">{{ (hoveredCell.passion ?? 0).toFixed(3) }}</span>
        <span class="tooltip-key">承諾</span>
        <span class="tooltip-val">{{ (hoveredCell.commitment ?? 0).toFixed(3) }}</span>
        <span class="tooltip-key">信任</span>
        <span class="tooltip-val">{{ (hoveredCell.trust ?? 0).toFixed(3) }}</span>
        <span class="tooltip-key">Rusbult</span>
        <span class="tooltip-val">{{ (hoveredCell.rusbult_commitment ?? 0).toFixed(3) }}</span>
        <span class="tooltip-key">互動次數</span>
        <span class="tooltip-val">{{ hoveredCell.interaction_count ?? 0 }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.rel-graph {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 16px;
  box-shadow: var(--shadow-card);
  position: relative;
  overflow: auto;
}

/* Header */
.rel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.rel-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.rel-round-badge {
  font-size: 11px;
  color: var(--text-muted);
  background: var(--bg-secondary);
  padding: 2px 10px;
  border-radius: 12px;
}

/* Metric tabs */
.metric-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 14px;
}

.metric-tab {
  padding: 4px 12px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-primary);
  color: var(--text-muted);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}

.metric-tab.active {
  background: var(--accent-blue);
  border-color: var(--accent-blue);
  color: #0d1117;
}

/* State messages */
.state-msg {
  text-align: center;
  padding: 32px;
  color: var(--text-muted);
  font-size: 13px;
}

.state-error {
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
  margin-right: 6px;
  vertical-align: middle;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Matrix layout */
.matrix-wrapper {
  overflow: auto;
  max-height: 60vh;
  margin-bottom: 12px;
}

.matrix-col-headers {
  display: flex;
  align-items: flex-end;
  padding-bottom: 4px;
  position: sticky;
  top: 0;
  background: var(--bg-card);
  z-index: 2;
}

.matrix-corner {
  width: 90px;
  flex-shrink: 0;
}

.matrix-col-label {
  width: 28px;
  flex-shrink: 0;
  font-size: 9px;
  color: var(--text-muted);
  text-align: center;
  writing-mode: vertical-rl;
  transform: rotate(180deg);
  height: 72px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: default;
}

.matrix-row {
  display: flex;
  align-items: center;
}

.matrix-row-label {
  width: 90px;
  flex-shrink: 0;
  font-size: 10px;
  color: var(--text-muted);
  padding-right: 6px;
  text-align: right;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: default;
}

.matrix-cell {
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  border-radius: 3px;
  margin: 1px;
  transition: transform 0.1s, opacity 0.1s;
  cursor: pointer;
}

.matrix-cell.diagonal {
  opacity: 0.25;
  cursor: default;
}

.matrix-cell.has-data:hover {
  transform: scale(1.3);
  z-index: 3;
}

/* Legend */
.rel-legend {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.legend-label {
  white-space: nowrap;
}

.legend-bar {
  width: 120px;
  height: 10px;
  border-radius: 3px;
  background: linear-gradient(
    to right,
    rgba(239, 68, 68, 0.08),
    rgba(239, 68, 68, 0.45),
    rgba(239, 68, 68, 0.9)
  );
}

.legend-ticks {
  display: flex;
  gap: 18px;
  font-size: 10px;
  color: var(--text-muted);
  margin-left: 8px;
}

/* Summary stats */
.summary-row {
  display: flex;
  gap: 12px;
  margin-top: 4px;
}

.summary-stat {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  background: var(--bg-secondary);
  padding: 8px 10px;
  border-radius: 6px;
  text-align: center;
}

.summary-label {
  font-size: 10px;
  color: var(--text-muted);
}

.summary-value {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

/* Tooltip */
.cell-tooltip {
  position: fixed;
  z-index: 9999;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 10px 12px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
  pointer-events: none;
  min-width: 180px;
}

.tooltip-agents {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.tooltip-arrow {
  color: var(--text-muted);
}

.tooltip-grid {
  display: grid;
  grid-template-columns: auto auto;
  gap: 2px 12px;
}

.tooltip-key {
  font-size: 11px;
  color: var(--text-muted);
}

.tooltip-val {
  font-size: 11px;
  color: var(--text-primary);
  font-weight: 600;
  text-align: right;
}
</style>
