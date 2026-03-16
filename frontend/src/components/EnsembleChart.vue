<template>
  <div class="ensemble-chart">
    <div class="chart-header">
      <h3 class="chart-title">集成模擬分佈圖</h3>
      <p class="chart-subtitle">
        顯示 {{ nTrials }} 次真實模擬試驗的百分位數分佈帶
      </p>
    </div>

    <!-- Empty state -->
    <div v-if="!hasData" class="empty-state">
      <span class="empty-icon">📊</span>
      <p>尚未有集成結果。請先運行集成模擬。</p>
    </div>

    <div v-else>
      <!-- Metric selector tabs -->
      <div class="metric-tabs">
        <button
          v-for="band in distributions"
          :key="band.metric_name"
          class="metric-tab"
          :class="{ active: activeMetric === band.metric_name }"
          @click="activeMetric = band.metric_name"
        >
          {{ metricLabel(band.metric_name) }}
        </button>
      </div>

      <!-- Fan chart for selected metric -->
      <div v-if="activeBand" class="fan-chart-container">
        <div class="fan-chart-label-left">{{ formatValue(activeBand.p10) }}</div>
        <div class="fan-chart" aria-label="百分位數分佈帶">
          <!-- P10–P90 outer band -->
          <div
            class="band band-outer"
            :style="outerBandStyle(activeBand)"
            title="P10–P90 範圍（80% 信賴區間）"
          ></div>
          <!-- P25–P75 IQR band -->
          <div
            class="band band-iqr"
            :style="iqrBandStyle(activeBand)"
            title="P25–P75 四分位距（50% 信賴區間）"
          ></div>
          <!-- P50 median line -->
          <div
            class="median-line"
            :style="medianLineStyle(activeBand)"
            title="P50 中位數"
          ></div>
          <!-- Percentile labels -->
          <div class="percentile-labels">
            <span class="pct-label pct-p10" :style="{ left: '0%' }">P10</span>
            <span class="pct-label pct-p25" :style="iqrLabelLeft(activeBand)">P25</span>
            <span class="pct-label pct-p50" :style="medianLabelLeft(activeBand)">P50</span>
            <span class="pct-label pct-p75" :style="iqrLabelRight(activeBand)">P75</span>
            <span class="pct-label pct-p90" :style="{ left: '100%' }">P90</span>
          </div>
        </div>
        <div class="fan-chart-label-right">{{ formatValue(activeBand.p90) }}</div>
      </div>

      <!-- Percentile table -->
      <div v-if="activeBand" class="percentile-table">
        <table>
          <thead>
            <tr>
              <th>百分位</th>
              <th>數值</th>
              <th>說明</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in percentileRows(activeBand)" :key="row.pct">
              <td class="pct-cell" :class="row.cssClass">{{ row.pct }}</td>
              <td class="value-cell">{{ row.value }}</td>
              <td class="desc-cell">{{ row.desc }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Probability statements -->
      <div v-if="probabilityStatements.length > 0" class="probability-section">
        <h4 class="section-title">概率陳述</h4>
        <ul class="probability-list">
          <li
            v-for="stmt in filteredStatements"
            :key="stmt.metric"
            class="probability-item"
            :class="probabilityClass(stmt.probability)"
          >
            <span class="probability-badge">{{ formatProbability(stmt.probability) }}</span>
            <span class="probability-text">{{ stmt.statement_zh }}</span>
          </li>
        </ul>
      </div>

      <!-- Trial summary -->
      <div v-if="trialMetadata.length > 0" class="trial-summary">
        <h4 class="section-title">試驗摘要</h4>
        <div class="trial-stats">
          <div class="trial-stat">
            <span class="stat-label">總試驗數</span>
            <span class="stat-value">{{ trialMetadata.length }}</span>
          </div>
          <div class="trial-stat">
            <span class="stat-label">成功完成</span>
            <span class="stat-value success">{{ completedCount }}</span>
          </div>
          <div class="trial-stat">
            <span class="stat-label">失敗</span>
            <span class="stat-value failed">{{ failedCount }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

const props = defineProps({
  /** List of DistributionBand dicts from GET /{id}/ensemble/results */
  distributions: {
    type: Array,
    default: () => [],
  },
  /** List of ProbabilityStatement dicts */
  probabilityStatements: {
    type: Array,
    default: () => [],
  },
  /** List of TrialRecord dicts */
  trialMetadata: {
    type: Array,
    default: () => [],
  },
  /** Number of trials (from meta.n_trials) */
  nTrials: {
    type: Number,
    default: 0,
  },
})

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const activeMetric = ref(props.distributions[0]?.metric_name ?? '')

watch(
  () => props.distributions,
  (bands) => {
    if (bands.length > 0 && !bands.find(b => b.metric_name === activeMetric.value)) {
      activeMetric.value = bands[0].metric_name
    }
  },
  { immediate: true },
)

// ---------------------------------------------------------------------------
// Computed
// ---------------------------------------------------------------------------

const hasData = computed(() => props.distributions.length > 0)

const activeBand = computed(() =>
  props.distributions.find(b => b.metric_name === activeMetric.value) ?? null
)

const completedCount = computed(() =>
  props.trialMetadata.filter(t => t.status === 'completed').length
)

const failedCount = computed(() =>
  props.trialMetadata.filter(t => t.status === 'failed').length
)

const filteredStatements = computed(() =>
  props.probabilityStatements.filter(s => s.metric === activeMetric.value)
)

// ---------------------------------------------------------------------------
// Metric labels (Traditional Chinese)
// ---------------------------------------------------------------------------

const _LABELS = {
  hibor_1m:           'HIBOR',
  unemployment_rate:  '失業率',
  ccl_index:          'CCL 指數',
  hsi_level:          '恒生指數',
  consumer_confidence:'消費者信心',
  gdp_growth:         'GDP 增長',
  net_migration:      '淨遷移',
  fed_rate:           '聯儲利率',
  china_gdp_growth:   '中國 GDP',
  taiwan_strait_risk: '台海風險',
}

function metricLabel(name) {
  return _LABELS[name] ?? name
}

// ---------------------------------------------------------------------------
// Value formatting
// ---------------------------------------------------------------------------

const _PCT_METRICS = new Set([
  'hibor_1m', 'unemployment_rate', 'gdp_growth', 'fed_rate', 'china_gdp_growth',
])

function formatValue(val) {
  if (val == null) return '—'
  if (activeMetric.value && _PCT_METRICS.has(activeMetric.value)) {
    return (val * 100).toFixed(2) + '%'
  }
  if (activeMetric.value === 'taiwan_strait_risk') {
    return val.toFixed(3)
  }
  if (activeMetric.value === 'net_migration') {
    return val.toLocaleString('zh-HK', { maximumFractionDigits: 0 })
  }
  if (activeMetric.value === 'hsi_level') {
    return val.toLocaleString('zh-HK', { maximumFractionDigits: 0 })
  }
  return val.toLocaleString('zh-HK', { maximumFractionDigits: 2 })
}

function formatProbability(p) {
  return (p * 100).toFixed(0) + '%'
}

// ---------------------------------------------------------------------------
// Layout computations for CSS-drawn fan chart
// ---------------------------------------------------------------------------

/**
 * Map a value within [p10, p90] to a CSS percentage left offset [0%, 100%].
 * Returns a string like '35.4%'.
 */
function toPercent(value, band) {
  const range = band.p90 - band.p10
  if (range <= 0) return '50%'
  const pct = ((value - band.p10) / range) * 100
  return `${Math.max(0, Math.min(100, pct)).toFixed(2)}%`
}

function outerBandStyle(band) {
  return { left: '0%', width: '100%' }
}

function iqrBandStyle(band) {
  const left = toPercent(band.p25, band)
  const right = toPercent(band.p75, band)
  const width = ((band.p75 - band.p25) / Math.max(band.p90 - band.p10, 1e-9) * 100).toFixed(2)
  return { left, width: width + '%' }
}

function medianLineStyle(band) {
  return { left: toPercent(band.p50, band) }
}

function iqrLabelLeft(band) {
  return { left: toPercent(band.p25, band) }
}

function iqrLabelRight(band) {
  return { left: toPercent(band.p75, band) }
}

function medianLabelLeft(band) {
  return { left: toPercent(band.p50, band) }
}

// ---------------------------------------------------------------------------
// Percentile table rows
// ---------------------------------------------------------------------------

function percentileRows(band) {
  return [
    { pct: 'P10', value: formatValue(band.p10), desc: '最差情景（10% 機率更低）', cssClass: 'p10' },
    { pct: 'P25', value: formatValue(band.p25), desc: '下四分位數', cssClass: 'p25' },
    { pct: 'P50', value: formatValue(band.p50), desc: '中位數（基準情景）', cssClass: 'p50' },
    { pct: 'P75', value: formatValue(band.p75), desc: '上四分位數', cssClass: 'p75' },
    { pct: 'P90', value: formatValue(band.p90), desc: '最佳情景（10% 機率更高）', cssClass: 'p90' },
  ]
}

// ---------------------------------------------------------------------------
// Probability class helpers
// ---------------------------------------------------------------------------

function probabilityClass(p) {
  if (p >= 0.7) return 'high-prob'
  if (p >= 0.4) return 'mid-prob'
  return 'low-prob'
}
</script>

<style scoped>
.ensemble-chart {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 20px;
  color: var(--text-primary);
}

/* Header */
.chart-header {
  margin-bottom: 16px;
}
.chart-title {
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--accent-blue);
  margin: 0 0 4px;
}
.chart-subtitle {
  font-size: 0.8rem;
  color: var(--text-muted);
  margin: 0;
}

/* Empty state */
.empty-state {
  text-align: center;
  padding: 40px 0;
  color: var(--text-muted);
}
.empty-icon {
  font-size: 2.5rem;
  display: block;
  margin-bottom: 8px;
}

/* Metric tabs */
.metric-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 20px;
}
.metric-tab {
  padding: 4px 12px;
  border: 1px solid var(--border-color);
  background: var(--bg-secondary);
  color: var(--text-secondary);
  border-radius: 999px;
  font-size: 0.78rem;
  cursor: pointer;
  transition: all 0.15s;
}
.metric-tab:hover {
  border-color: var(--accent-blue);
  color: var(--accent-blue);
}
.metric-tab.active {
  background: var(--accent-blue-light);
  border-color: var(--accent-blue);
  color: var(--accent-blue);
  font-weight: 600;
}

/* Fan chart */
.fan-chart-container {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 24px;
}
.fan-chart-label-left,
.fan-chart-label-right {
  font-size: 0.75rem;
  color: var(--text-muted);
  white-space: nowrap;
  min-width: 60px;
}
.fan-chart-label-right {
  text-align: right;
}
.fan-chart {
  flex: 1;
  position: relative;
  height: 64px;
  background: var(--bg-secondary);
  border-radius: var(--radius-md);
  overflow: visible;
}
.band {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  border-radius: 4px;
}
.band-outer {
  height: 28px;
  background: rgba(37, 99, 235, 0.08);
  border: 1px solid rgba(37, 99, 235, 0.2);
}
.band-iqr {
  height: 44px;
  background: rgba(37, 99, 235, 0.15);
  border: 1px solid rgba(37, 99, 235, 0.3);
}
.median-line {
  position: absolute;
  top: 8px;
  bottom: 8px;
  width: 2px;
  background: var(--accent-blue);
  border-radius: 1px;
  transform: translateX(-50%);
}
.percentile-labels {
  position: absolute;
  bottom: -20px;
  left: 0;
  right: 0;
  height: 20px;
}
.pct-label {
  position: absolute;
  font-size: 0.65rem;
  color: var(--text-muted);
  transform: translateX(-50%);
}
.pct-p10 { transform: translateX(0); }
.pct-p90 { transform: translateX(-100%); }

/* Percentile table */
.percentile-table {
  margin-top: 28px;
  margin-bottom: 20px;
}
.percentile-table table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.82rem;
}
.percentile-table th {
  text-align: left;
  padding: 6px 10px;
  border-bottom: 1px solid var(--border-color);
  color: var(--text-muted);
  font-weight: 500;
}
.percentile-table td {
  padding: 7px 10px;
  border-bottom: 1px solid var(--border-color);
}
.pct-cell {
  font-weight: 600;
  font-size: 0.8rem;
  width: 48px;
}
.pct-cell.p10  { color: var(--accent-red); }
.pct-cell.p25  { color: var(--accent-orange); }
.pct-cell.p50  { color: var(--accent-blue); }
.pct-cell.p75  { color: var(--accent-green); }
.pct-cell.p90  { color: #16a34a; }
.value-cell {
  font-family: var(--font-mono);
  color: var(--text-primary);
}
.desc-cell {
  color: var(--text-muted);
  font-size: 0.78rem;
}

/* Probability statements */
.probability-section {
  margin-top: 20px;
}
.section-title {
  font-size: 0.88rem;
  font-weight: 600;
  color: var(--text-secondary);
  margin: 0 0 10px;
}
.probability-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.probability-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  background: var(--bg-secondary);
  border-radius: var(--radius-md);
  padding: 10px 12px;
  border-left: 3px solid transparent;
}
.probability-item.high-prob { border-left-color: var(--accent-red); }
.probability-item.mid-prob  { border-left-color: var(--accent-orange); }
.probability-item.low-prob  { border-left-color: var(--accent-green); }
.probability-badge {
  font-size: 0.82rem;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 4px;
  white-space: nowrap;
  background: var(--accent-blue-light);
  color: var(--accent-blue);
}
.probability-text {
  font-size: 0.82rem;
  color: var(--text-secondary);
  line-height: 1.5;
}

/* Trial summary */
.trial-summary {
  margin-top: 20px;
}
.trial-stats {
  display: flex;
  gap: 24px;
}
.trial-stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.stat-label {
  font-size: 0.72rem;
  color: var(--text-muted);
}
.stat-value {
  font-size: 1.1rem;
  font-weight: 700;
  color: var(--text-primary);
}
.stat-value.success { color: var(--accent-green); }
.stat-value.failed  { color: var(--accent-red); }
</style>
