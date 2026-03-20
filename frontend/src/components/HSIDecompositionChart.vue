<script setup>
import { ref, onMounted, computed } from 'vue'
import { getHSIDecomposition } from '../api/simulation.js'

const loading = ref(true)
const error = ref(null)
const data = ref(null)

const bars = computed(() => data.value?.decomposition || [])
const stats = computed(() => data.value?.stats || {})

const maxAbsReturn = computed(() => {
  if (!bars.value.length) return 1
  return Math.max(
    ...bars.value.map(b => Math.abs(b.total_return || (b.fundamental + b.sentiment)))
  ) || 1
})

function barHeight(val) {
  const pct = (Math.abs(val) / maxAbsReturn.value) * 100
  return Math.max(pct, 2)
}

onMounted(async () => {
  try {
    const res = await getHSIDecomposition(20)
    data.value = res.data?.data || res.data
  } catch (e) {
    error.value = e.response?.data?.detail || e.message || '載入失敗'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="hsi-decomp">
    <h3 class="panel-heading">HSI 回報分解</h3>

    <div v-if="loading" class="state-msg">載入中...</div>
    <div v-else-if="error" class="state-msg error">{{ error }}</div>

    <template v-else>
      <div class="chart-area">
        <div class="chart-scroll">
          <div
            v-for="(bar, i) in bars"
            :key="i"
            class="bar-group"
          >
            <div class="bar-stack">
              <div
                class="bar fundamental"
                :style="{ height: barHeight(bar.fundamental) + '%' }"
                :title="'基本面: ' + (bar.fundamental * 100).toFixed(1) + '%'"
              />
              <div
                class="bar sentiment"
                :style="{ height: barHeight(bar.sentiment) + '%' }"
                :title="'情緒面: ' + (bar.sentiment * 100).toFixed(1) + '%'"
              />
            </div>
            <span class="bar-label">{{ bar.period || `Q${i + 1}` }}</span>
          </div>
        </div>
      </div>

      <div class="legend">
        <span class="legend-item"><span class="dot fundamental-dot" /> 基本面</span>
        <span class="legend-item"><span class="dot sentiment-dot" /> 情緒面</span>
      </div>

      <div v-if="stats.r_squared != null" class="stats-row">
        <div class="stat-chip">
          <span class="stat-label">R&sup2;</span>
          <span class="stat-value">{{ stats.r_squared.toFixed(3) }}</span>
        </div>
        <div v-if="stats.beta_gdp != null" class="stat-chip">
          <span class="stat-label">Beta GDP</span>
          <span class="stat-value">{{ stats.beta_gdp.toFixed(3) }}</span>
        </div>
        <div v-if="stats.beta_hibor != null" class="stat-chip">
          <span class="stat-label">Beta HIBOR</span>
          <span class="stat-value">{{ stats.beta_hibor.toFixed(3) }}</span>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.hsi-decomp {
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
.chart-area {
  overflow-x: auto;
  margin-bottom: 0.75rem;
}
.chart-scroll {
  display: flex;
  gap: 6px;
  align-items: flex-end;
  min-height: 140px;
  padding-bottom: 4px;
}
.bar-group {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 32px;
}
.bar-stack {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  height: 120px;
  justify-content: flex-end;
}
.bar {
  width: 18px;
  border-radius: 2px 2px 0 0;
  transition: height 0.3s;
}
.bar.fundamental { background: var(--accent-blue, #4f9ce8); }
.bar.sentiment { background: var(--accent-orange, #FF6B35); }
.bar-label {
  font-size: 0.65rem;
  color: var(--text-muted);
  margin-top: 4px;
  white-space: nowrap;
}
.legend {
  display: flex;
  gap: 1rem;
  font-size: 0.8rem;
  color: var(--text-secondary);
  margin-bottom: 0.75rem;
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
.fundamental-dot { background: var(--accent-blue, #4f9ce8); }
.sentiment-dot { background: var(--accent-orange, #FF6B35); }
.stats-row {
  display: flex;
  gap: 0.75rem;
  flex-wrap: wrap;
}
.stat-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 20px;
  font-size: 0.8rem;
}
.stat-label {
  color: var(--text-muted);
  font-weight: 500;
}
.stat-value {
  font-weight: 700;
  font-family: var(--font-mono);
  color: var(--text-primary);
}
</style>
