<script setup>
import { ref, onMounted, onUnmounted, watch, toRefs } from 'vue'
import * as d3 from 'd3'

const props = defineProps({
  indicators: {
    type: Array,
    default: () => [
      { key: 'hibor', label: 'HIBOR (1M)', value: 4.12, unit: '%', trend: [3.8, 3.9, 4.0, 4.1, 4.12], change: 0.02 },
      { key: 'unemployment', label: '失業率', value: 3.0, unit: '%', trend: [3.4, 3.3, 3.2, 3.1, 3.0], change: -0.1 },
      { key: 'ccl', label: 'CCL 指數', value: 156.2, unit: '', trend: [160, 158, 157, 156, 156.2], change: -0.5 },
      { key: 'gdp', label: 'GDP 增長', value: 2.8, unit: '%', trend: [2.1, 2.3, 2.5, 2.7, 2.8], change: 0.1 },
      { key: 'cpi', label: 'CPI', value: 2.1, unit: '%', trend: [1.8, 1.9, 2.0, 2.0, 2.1], change: 0.1 },
    ],
  },
})

const sparklineRefs = {}

function drawSparkline(el, data, isPositive) {
  if (!el || !data || data.length === 0) return

  d3.select(el).selectAll('*').remove()

  const width = 80
  const height = 28
  const margin = { top: 2, right: 2, bottom: 2, left: 2 }

  const svg = d3.select(el)
    .attr('width', width)
    .attr('height', height)

  const x = d3.scaleLinear()
    .domain([0, data.length - 1])
    .range([margin.left, width - margin.right])

  const y = d3.scaleLinear()
    .domain(d3.extent(data))
    .range([height - margin.bottom, margin.top])

  const line = d3.line()
    .x((_, i) => x(i))
    .y((d) => y(d))
    .curve(d3.curveMonotoneX)

  const color = isPositive ? '#059669' : '#DC2626'

  svg.append('path')
    .datum(data)
    .attr('fill', 'none')
    .attr('stroke', color)
    .attr('stroke-width', 1.5)
    .attr('d', line)

  svg.append('circle')
    .attr('cx', x(data.length - 1))
    .attr('cy', y(data[data.length - 1]))
    .attr('r', 2.5)
    .attr('fill', color)
}

function renderSparklines() {
  props.indicators.forEach((ind) => {
    const el = sparklineRefs[ind.key]
    if (el) {
      const isPositive = ind.change >= 0
      drawSparkline(el, ind.trend, isPositive)
    }
  })
}

onMounted(() => {
  requestAnimationFrame(renderSparklines)
})

watch(
  () => props.indicators,
  () => {
    requestAnimationFrame(renderSparklines)
  },
  { deep: true }
)
</script>

<template>
  <div class="macro-panel">
    <h3 class="panel-title">香港宏觀指標</h3>
    <div class="indicator-grid">
      <div
        v-for="ind in indicators"
        :key="ind.key"
        class="indicator-card"
      >
        <div class="ind-header">
          <span class="ind-label">{{ ind.label }}</span>
          <span
            class="ind-change"
            :class="ind.change >= 0 ? 'positive' : 'negative'"
          >
            {{ ind.change >= 0 ? '+' : '' }}{{ ind.change }}{{ ind.unit }}
          </span>
        </div>
        <div class="ind-body">
          <span class="ind-value">
            {{ ind.value }}{{ ind.unit }}
          </span>
          <svg :ref="el => { if (el) sparklineRefs[ind.key] = el }" class="sparkline" />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.macro-panel {
  padding: 16px;
}

.panel-title {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 14px;
  color: var(--text-primary);
}

.indicator-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
}

.indicator-card {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 14px;
  transition: var(--transition);
  box-shadow: var(--shadow-card);
}

.indicator-card:hover {
  border-color: var(--accent-blue);
  box-shadow: var(--shadow-md);
}

.ind-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.ind-label {
  font-size: 12px;
  color: var(--text-muted);
}

.ind-change {
  font-size: 12px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 3px;
  font-family: var(--font-mono, 'JetBrains Mono', 'SF Mono', monospace);
}

.ind-change.positive {
  background: rgba(5, 150, 105, 0.1);
  color: var(--accent-green);
}

.ind-change.negative {
  background: rgba(220, 38, 38, 0.1);
  color: var(--accent-red);
}

.ind-body {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
}

.ind-value {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
  font-family: var(--font-mono, 'JetBrains Mono', 'SF Mono', monospace);
}

.sparkline {
  flex-shrink: 0;
}
</style>
