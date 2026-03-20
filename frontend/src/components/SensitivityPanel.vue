<script setup>
import { ref, onMounted, computed } from 'vue'
import { getSensitivityAnalysis } from '../api/simulation.js'

const loading = ref(true)
const error = ref(null)
const data = ref(null)

const items = computed(() => {
  const raw = data.value?.top_sensitivities || data.value?.sensitivities || []
  return [...raw].sort((a, b) => Math.abs(b.sensitivity_score) - Math.abs(a.sensitivity_score))
})

const maxScore = computed(() => {
  if (!items.value.length) return 1
  return Math.max(...items.value.map(i => Math.abs(i.sensitivity_score))) || 1
})

const summary = computed(() => data.value?.summary || '')

function barWidth(score) {
  return Math.max((Math.abs(score) / maxScore.value) * 100, 3)
}

function barColor(score) {
  if (score > 0.01) return 'var(--accent-green, #22c55e)'
  if (score < -0.01) return 'var(--accent-red, #ef4444)'
  return 'var(--text-muted, #9ca3af)'
}

function directionLabel(score) {
  if (score > 0.01) return '+'
  if (score < -0.01) return '-'
  return ''
}

onMounted(async () => {
  try {
    const res = await getSensitivityAnalysis()
    data.value = res.data?.data || res.data
  } catch (e) {
    error.value = e.response?.data?.detail || e.message || '載入失敗'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="sensitivity-panel">
    <h3 class="panel-heading">參數敏感度分析</h3>

    <div v-if="loading" class="state-msg">載入中...</div>
    <div v-else-if="error" class="state-msg error">{{ error }}</div>

    <template v-else>
      <div v-if="!items.length" class="state-msg">暫無敏感度數據</div>

      <div v-else class="bar-list">
        <div v-for="(item, i) in items" :key="i" class="bar-row">
          <span class="param-name" :title="item.metric || ''">
            {{ item.parameter || item.param || `P${i + 1}` }}
            <span v-if="item.metric" class="param-metric">{{ item.metric }}</span>
          </span>
          <div class="bar-track">
            <div
              class="bar-fill"
              :style="{ width: barWidth(item.sensitivity_score) + '%', background: barColor(item.sensitivity_score) }"
            />
          </div>
          <span class="score-label" :style="{ color: barColor(item.sensitivity_score) }">
            {{ directionLabel(item.sensitivity_score) }}{{ Math.abs(item.sensitivity_score).toFixed(3) }}
          </span>
        </div>
      </div>

      <p v-if="summary" class="summary-text">{{ summary }}</p>

      <div class="legend">
        <span class="legend-item"><span class="dot" style="background: var(--accent-green, #22c55e)" /> 正向</span>
        <span class="legend-item"><span class="dot" style="background: var(--accent-red, #ef4444)" /> 負向</span>
        <span class="legend-item"><span class="dot" style="background: var(--text-muted, #9ca3af)" /> 中性</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.sensitivity-panel {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 1.25rem;
}
.panel-heading {
  font-size: 1rem;
  font-weight: 600;
  margin: 0 0 1rem;
  color: var(--text-primary);
}
.state-msg {
  text-align: center;
  padding: 2rem;
  color: var(--text-muted);
}
.state-msg.error {
  color: var(--accent-red);
}
.bar-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 1rem;
}
.bar-row {
  display: grid;
  grid-template-columns: 160px 1fr 60px;
  align-items: center;
  gap: 8px;
}
.param-name {
  font-size: 0.82rem;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.param-metric {
  font-size: 0.7rem;
  color: var(--text-muted);
  margin-left: 4px;
}
.bar-track {
  height: 14px;
  background: var(--bg-secondary);
  border-radius: 3px;
  overflow: hidden;
}
.bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s;
}
.score-label {
  font-size: 0.8rem;
  font-weight: 700;
  font-family: var(--font-mono);
  text-align: right;
}
.summary-text {
  font-size: 0.82rem;
  color: var(--text-secondary);
  line-height: 1.6;
  margin: 0 0 0.75rem;
}
.legend {
  display: flex;
  gap: 1rem;
  font-size: 0.78rem;
  color: var(--text-secondary);
}
.legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 2px;
}
</style>
