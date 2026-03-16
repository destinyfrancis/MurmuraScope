<script setup>
import { computed } from 'vue'

const props = defineProps({
  /**
   * Object mapping round_number (string) → { positive, negative, neutral }
   * e.g. { "1": { positive: 5, negative: 3, neutral: 12 } }
   */
  sentimentByRound: { type: Object, default: () => ({}) },
  /** Max rounds to display */
  maxRounds: { type: Number, default: 40 },
})

const SENTIMENTS = ['positive', 'neutral', 'negative']
const LABELS = { positive: '正面', neutral: '中性', negative: '負面' }
const COLORS = {
  positive: (intensity) => `rgba(6, 214, 160, ${0.1 + intensity * 0.8})`,
  neutral: (intensity) => `rgba(100, 130, 180, ${0.1 + intensity * 0.7})`,
  negative: (intensity) => `rgba(247, 37, 133, ${0.1 + intensity * 0.8})`,
}

const rounds = computed(() => {
  const keys = Object.keys(props.sentimentByRound)
    .map(Number)
    .sort((a, b) => a - b)
    .slice(0, props.maxRounds)
  return keys
})

const maxCount = computed(() => {
  let max = 1
  for (const data of Object.values(props.sentimentByRound)) {
    for (const s of SENTIMENTS) {
      if ((data[s] || 0) > max) max = data[s]
    }
  }
  return max
})

function getIntensity(round, sentiment) {
  const data = props.sentimentByRound[String(round)] || {}
  return (data[sentiment] || 0) / maxCount.value
}

function getCount(round, sentiment) {
  const data = props.sentimentByRound[String(round)] || {}
  return data[sentiment] || 0
}

const cellWidth = computed(() => {
  const n = rounds.value.length
  if (n === 0) return 20
  return Math.min(24, Math.max(10, Math.floor(560 / n)))
})
</script>

<template>
  <div class="heatmap">
    <div class="heatmap-title">情緒熱力圖（輪次 × 情緒）</div>

    <div v-if="rounds.length === 0" class="empty-hint">
      模擬結束後顯示情緒數據
    </div>

    <div v-else class="heatmap-grid">
      <!-- Row labels -->
      <div class="row-labels">
        <div class="corner-cell" />
        <div
          v-for="s in SENTIMENTS"
          :key="s"
          class="row-label"
          :class="`label-${s}`"
        >
          {{ LABELS[s] }}
        </div>
      </div>

      <!-- Scrollable data area -->
      <div class="data-scroll">
        <div class="col-headers">
          <div
            v-for="r in rounds"
            :key="`h${r}`"
            class="col-header"
            :style="{ width: cellWidth + 'px' }"
          >
            {{ r }}
          </div>
        </div>

        <div
          v-for="s in SENTIMENTS"
          :key="s"
          class="data-row"
        >
          <div
            v-for="r in rounds"
            :key="`${s}-${r}`"
            class="cell"
            :style="{
              width: cellWidth + 'px',
              background: COLORS[s](getIntensity(r, s)),
            }"
            :title="`輪次 ${r} | ${LABELS[s]}: ${getCount(r, s)}`"
          />
        </div>
      </div>
    </div>

    <!-- Legend -->
    <div v-if="rounds.length > 0" class="legend">
      <span class="legend-label">低</span>
      <div class="legend-bar positive-bar" />
      <span class="legend-label">高（正面）</span>
      <span class="legend-sep">│</span>
      <div class="legend-bar negative-bar" />
      <span class="legend-label">高（負面）</span>
    </div>
  </div>
</template>

<style scoped>
.heatmap {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 16px;
  box-shadow: var(--shadow-card);
}

.heatmap-title {
  font-size: 13px;
  color: var(--text-muted);
  margin-bottom: 12px;
}

.empty-hint {
  text-align: center;
  color: var(--text-muted);
  font-size: 13px;
  padding: 24px 0;
}

.heatmap-grid {
  display: flex;
  gap: 0;
  overflow-x: auto;
}

.row-labels {
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}

.corner-cell {
  height: 20px;
}

.row-label {
  height: 22px;
  width: 42px;
  font-size: 11px;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding-right: 6px;
  color: var(--text-muted);
}

.label-positive { color: #06d6a0; }
.label-negative { color: #f72585; }
.label-neutral { color: var(--text-secondary); }

.data-scroll {
  overflow-x: auto;
  flex: 1;
}

.col-headers {
  display: flex;
  height: 20px;
}

.col-header {
  font-size: 9px;
  color: var(--text-muted);
  text-align: center;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.data-row {
  display: flex;
  margin-bottom: 2px;
}

.cell {
  height: 20px;
  flex-shrink: 0;
  border-radius: 2px;
  transition: opacity 0.2s;
}

.cell:hover {
  opacity: 0.7;
}

.legend {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 10px;
  font-size: 11px;
  color: var(--text-muted);
}

.legend-bar {
  height: 10px;
  width: 60px;
  border-radius: 2px;
}

.positive-bar {
  background: linear-gradient(to right, rgba(6, 214, 160, 0.1), rgba(6, 214, 160, 0.9));
}

.negative-bar {
  background: linear-gradient(to right, rgba(247, 37, 133, 0.1), rgba(247, 37, 133, 0.9));
}

.legend-sep {
  color: var(--border-color);
  margin: 0 4px;
}
</style>
