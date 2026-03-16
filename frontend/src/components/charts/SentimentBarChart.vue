<script setup>
defineProps({
  chartRounds: { type: Array, required: true },
  getSentimentRow: { type: Function, required: true },
})

const BAR_MAX_H = 80

function sentimentPercent(row, key) {
  if (!row.total || row.total === 0) return 0
  return Math.round((row[key] / row.total) * 100)
}

function barHeight(session, roundNum, key, getSentimentRow) {
  const row = getSentimentRow(session, roundNum)
  const pct = sentimentPercent(row, key)
  return Math.round((pct / 100) * BAR_MAX_H)
}
</script>

<template>
  <div class="sentiment-bar-chart">
    <div class="chart-legend">
      <span class="legend-dot pos" />正面
      <span class="legend-dot neg" />負面
      <span class="legend-dot neu" />中性
    </div>
    <div class="chart-area">
      <div v-for="round in chartRounds" :key="round" class="chart-round-group">
        <div class="chart-round-label">R{{ round }}</div>
        <div class="chart-bars">
          <!-- Session A -->
          <div class="bar-group">
            <div class="bar-label">A</div>
            <div class="bar-stack">
              <div
                class="bar pos"
                :style="{ height: barHeight('session_a', round, 'pos', getSentimentRow) + 'px' }"
                :title="`正面 ${sentimentPercent(getSentimentRow('session_a', round), 'pos')}%`"
              />
              <div
                class="bar neg"
                :style="{ height: barHeight('session_a', round, 'neg', getSentimentRow) + 'px' }"
                :title="`負面 ${sentimentPercent(getSentimentRow('session_a', round), 'neg')}%`"
              />
              <div
                class="bar neu"
                :style="{ height: barHeight('session_a', round, 'neu', getSentimentRow) + 'px' }"
                :title="`中性 ${sentimentPercent(getSentimentRow('session_a', round), 'neu')}%`"
              />
            </div>
          </div>
          <!-- Session B -->
          <div class="bar-group">
            <div class="bar-label">B</div>
            <div class="bar-stack">
              <div
                class="bar pos"
                :style="{ height: barHeight('session_b', round, 'pos', getSentimentRow) + 'px' }"
                :title="`正面 ${sentimentPercent(getSentimentRow('session_b', round), 'pos')}%`"
              />
              <div
                class="bar neg"
                :style="{ height: barHeight('session_b', round, 'neg', getSentimentRow) + 'px' }"
                :title="`負面 ${sentimentPercent(getSentimentRow('session_b', round), 'neg')}%`"
              />
              <div
                class="bar neu"
                :style="{ height: barHeight('session_b', round, 'neu', getSentimentRow) + 'px' }"
                :title="`中性 ${sentimentPercent(getSentimentRow('session_b', round), 'neu')}%`"
              />
            </div>
          </div>
        </div>
      </div>
      <div v-if="chartRounds.length === 0" class="no-data">
        暫無情感數據
      </div>
    </div>
  </div>
</template>

<style scoped>
.chart-legend {
  display: flex;
  align-items: center;
  gap: 14px;
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 12px;
}

.legend-dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 2px;
  margin-right: 4px;
}

.legend-dot.pos { background: #34d399; }
.legend-dot.neg { background: #f87171; }
.legend-dot.neu { background: #94a3b8; }

.chart-area {
  display: flex;
  gap: 10px;
  align-items: flex-end;
  overflow-x: auto;
  padding-bottom: 8px;
  min-height: 110px;
}

.chart-round-group {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.chart-round-label {
  font-size: 11px;
  color: var(--text-muted);
}

.chart-bars {
  display: flex;
  gap: 4px;
  align-items: flex-end;
}

.bar-group {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
}

.bar-label {
  font-size: 10px;
  color: var(--text-muted);
  font-weight: 600;
}

.bar-stack {
  display: flex;
  gap: 2px;
  align-items: flex-end;
  height: 80px;
}

.bar {
  width: 10px;
  border-radius: 2px 2px 0 0;
  min-height: 2px;
  transition: height 0.3s ease;
  cursor: pointer;
}

.bar.pos { background: #34d399; }
.bar.neg { background: #f87171; }
.bar.neu { background: #94a3b8; }

.no-data {
  font-size: 13px;
  color: var(--text-muted);
  text-align: center;
  padding: 20px;
}
</style>
