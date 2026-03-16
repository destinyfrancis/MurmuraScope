<script setup>
import { ref, computed, onMounted } from 'vue'
import { getBacktest } from '../api/simulation.js'

const props = defineProps({
  /**
   * narrative: {
   *   executive_summary: string,
   *   trends: Array<{
   *     title: string,
   *     direction: 'up'|'down'|'flat'|'volatile',
   *     confidence: 'high'|'medium'|'low',
   *     narrative: string,
   *     evidence: string[],
   *     counter_signals: string[]
   *   }>,
   *   deep_dive_summary: string,
   *   methodology_note: string
   * }
   */
  narrative: { type: Object, default: null },
  /**
   * confidence: { score: number, level: 'high'|'medium'|'low' }
   */
  confidence: { type: Object, default: null },
  /**
   * Role-adapted display: 'investor' | 'researcher' | 'general'
   */
  role: { type: String, default: 'general' },
})

// Collapsible state
const activeSection = ref('summary')
const deepDiveOpen = ref(false)
const methodologyOpen = ref(false)
const expandedTrends = ref(new Set())

const SECTIONS = [
  { key: 'summary', label: '概述' },
  { key: 'trends', label: '趨勢' },
  { key: 'deep', label: '深度分析' },
]

function toggleTrend(idx) {
  const next = new Set(expandedTrends.value)
  if (next.has(idx)) { next.delete(idx) } else { next.add(idx) }
  expandedTrends.value = next
}

function isTrendExpanded(idx) {
  return expandedTrends.value.has(idx)
}

// Direction icon mapping
const DIRECTION_ICONS = {
  up: '↑', down: '↓', flat: '→', volatile: '↕',
  rising: '↑', falling: '↓', stable: '→',
}

const DIRECTION_CLASSES = {
  up: 'dir-up', rising: 'dir-up',
  down: 'dir-down', falling: 'dir-down',
  flat: 'dir-flat', stable: 'dir-flat',
  volatile: 'dir-volatile',
}

function dirIcon(dir) { return DIRECTION_ICONS[dir] ?? '→' }
function dirClass(dir) { return DIRECTION_CLASSES[dir] ?? 'dir-flat' }

// Confidence badge helpers
const CONFIDENCE_CLASSES = { high: 'conf-high', medium: 'conf-medium', low: 'conf-low' }
const CONFIDENCE_LABELS = { high: '高信心', medium: '中信心', low: '低信心' }

function confClass(level) { return CONFIDENCE_CLASSES[level] ?? 'conf-medium' }
function confLabel(level) { return CONFIDENCE_LABELS[level] ?? level }

const overallConfScore = computed(() => {
  if (!props.confidence) return null
  const score = props.confidence.score ?? props.confidence.confidence_score ?? null
  return score != null ? Math.round(score * 100) : null
})

const overallConfLevel = computed(() => {
  return props.confidence?.level ?? props.confidence?.confidence_level ?? null
})

const trends = computed(() => props.narrative?.trends ?? [])

// Role-adapted labels
const ROLE_LABELS = {
  investor: { summary: '投資摘要', trends: '市場趨勢', deep: '詳細分析' },
  researcher: { summary: '研究摘要', trends: '變量趨勢', deep: '完整分析' },
  general: { summary: '執行摘要', trends: '趨勢分析', deep: '深度分析' },
}

const roleLabels = computed(() => ROLE_LABELS[props.role] || ROLE_LABELS.general)

// ── Backtest accuracy data for deep dive section ──────────────────────────
const BACKTEST_METRICS = [
  { key: 'ccl_index', label: 'CCL 樓價指數' },
  { key: 'unemployment_rate', label: '失業率' },
  { key: 'hsi_level', label: '恒生指數' },
  { key: 'cpi_yoy', label: 'CPI 按年' },
  { key: 'gdp_growth', label: 'GDP 增長率' },
  { key: 'consumer_confidence', label: '消費者信心' },
]

const backtestResults = ref([])
const loadingBacktest = ref(false)

async function loadBacktestAccuracy() {
  loadingBacktest.value = true
  const results = await Promise.allSettled(
    BACKTEST_METRICS.map(m =>
      getBacktest(m.key, '2022-Q4', 8).then(r => ({
        metric: m.key,
        label: m.label,
        mape: r?.data?.data?.mape ?? null,
        directional_accuracy: r?.data?.data?.directional_accuracy ?? null,
      }))
    )
  )
  backtestResults.value = results
    .filter(r => r.status === 'fulfilled')
    .map(r => r.value)
  loadingBacktest.value = false
}

function backtestMapeColor(mape) {
  if (mape == null) return '#999'
  if (mape < 5) return '#059669'
  if (mape < 15) return '#D97706'
  return '#DC2626'
}

function backtestDirColor(acc) {
  if (acc == null) return '#999'
  if (acc >= 0.7) return '#059669'
  if (acc >= 0.5) return '#D97706'
  return '#DC2626'
}

onMounted(() => {
  loadBacktestAccuracy()
})

// Role-adapted summary prefix
const roleSummaryIcon = computed(() => {
  if (props.role === 'investor') return '💼'
  if (props.role === 'researcher') return '🔬'
  return '📋'
})
</script>

<template>
  <div class="trend-report">
    <!-- Overall confidence banner -->
    <div v-if="confidence" class="conf-banner" :class="confClass(overallConfLevel)">
      <span class="conf-icon">
        <span v-if="overallConfLevel === 'high'">●</span>
        <span v-else-if="overallConfLevel === 'medium'">◑</span>
        <span v-else>○</span>
      </span>
      <span class="conf-label">整體信心度: {{ confLabel(overallConfLevel) }}</span>
      <span v-if="overallConfScore != null" class="conf-score">{{ overallConfScore }}%</span>
    </div>

    <!-- Section tabs -->
    <div class="section-tabs">
      <button
        v-for="sec in SECTIONS"
        :key="sec.key"
        class="section-tab"
        :class="{ active: activeSection === sec.key }"
        @click="activeSection = sec.key"
      >
        {{ roleLabels[sec.key] || sec.label }}
      </button>
    </div>

    <!-- Empty state -->
    <div v-if="!narrative" class="empty-state">
      <span class="empty-icon">📊</span>
      <p class="empty-text">尚未生成趨勢報告</p>
    </div>

    <!-- SUMMARY section -->
    <Transition name="section-slide">
      <div v-if="activeSection === 'summary' && narrative?.executive_summary" class="section-body">
        <div class="card">
          <div class="card-header">
            <span class="card-icon">{{ roleSummaryIcon }}</span>
            <span class="card-title">{{ roleLabels.summary }}</span>
          </div>
          <p class="card-body">{{ narrative.executive_summary }}</p>
        </div>
      </div>
    </Transition>

    <!-- TRENDS section -->
    <Transition name="section-slide">
      <div v-if="activeSection === 'trends'" class="section-body">
        <div v-if="trends.length === 0" class="empty-state">
          <p class="empty-text">暫無趨勢數據</p>
        </div>
        <div v-else class="trends-section">
          <div class="section-label">{{ roleLabels.trends }}</div>
          <div
            v-for="(trend, idx) in trends"
            :key="idx"
            class="trend-card"
            :class="{ expanded: isTrendExpanded(idx) }"
          >
            <button
              class="trend-header"
              :aria-expanded="isTrendExpanded(idx)"
              @click="toggleTrend(idx)"
            >
              <span class="trend-dir-badge" :class="dirClass(trend.direction)">
                {{ dirIcon(trend.direction) }}
              </span>
              <span class="trend-title">{{ trend.title }}</span>
              <span v-if="trend.confidence" class="conf-badge" :class="confClass(trend.confidence)">
                {{ confLabel(trend.confidence) }}
              </span>
              <span class="trend-toggle-icon">{{ isTrendExpanded(idx) ? '▾' : '▸' }}</span>
            </button>

            <p class="trend-narrative">{{ trend.narrative }}</p>

            <Transition name="details-expand">
              <div v-if="isTrendExpanded(idx)" class="trend-details">
                <div v-if="trend.evidence?.length" class="evidence-section">
                  <div class="detail-label">支持證據</div>
                  <ul class="evidence-list">
                    <li v-for="(ev, ei) in trend.evidence" :key="ei" class="evidence-item">
                      <span class="evidence-bullet">✓</span>
                      {{ ev }}
                    </li>
                  </ul>
                </div>
                <div v-if="trend.counter_signals?.length" class="counter-section">
                  <div class="detail-label counter-label">反向信號</div>
                  <ul class="counter-list">
                    <li v-for="(cs, ci) in trend.counter_signals" :key="ci" class="counter-item">
                      <span class="counter-bullet">⚠</span>
                      {{ cs }}
                    </li>
                  </ul>
                </div>
              </div>
            </Transition>
          </div>
        </div>
      </div>
    </Transition>

    <!-- DEEP DIVE section -->
    <Transition name="section-slide">
      <div v-if="activeSection === 'deep'" class="section-body">
        <div v-if="narrative?.deep_dive_summary" class="deep-dive-card">
          <div class="card-header">
            <span class="card-icon">🔍</span>
            <span class="card-title">{{ roleLabels.deep }}</span>
          </div>
          <p class="card-body deep-body">{{ narrative.deep_dive_summary }}</p>
        </div>

        <!-- Backtest accuracy section -->
        <div class="backtest-accuracy-section">
          <div class="card-header">
            <span class="card-icon">🎯</span>
            <span class="card-title">預測準確度</span>
          </div>
          <div v-if="loadingBacktest" class="backtest-loading">載入回測數據中...</div>
          <table v-else-if="backtestResults.length" class="backtest-table">
            <thead>
              <tr>
                <th>指標</th>
                <th>MAPE</th>
                <th>方向準確率</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="b in backtestResults" :key="b.metric">
                <td>{{ b.label }}</td>
                <td :style="{ color: backtestMapeColor(b.mape) }">
                  {{ b.mape != null ? b.mape.toFixed(1) + '%' : 'N/A' }}
                </td>
                <td :style="{ color: backtestDirColor(b.directional_accuracy) }">
                  {{ b.directional_accuracy != null ? (b.directional_accuracy * 100).toFixed(0) + '%' : 'N/A' }}
                </td>
              </tr>
            </tbody>
          </table>
          <div v-else class="backtest-empty">暫無回測數據</div>
        </div>

        <!-- Methodology note (collapsible) -->
        <div v-if="narrative?.methodology_note" class="accordion-section methodology">
          <button
            class="accordion-header methodology-toggle"
            :aria-expanded="methodologyOpen"
            @click="methodologyOpen = !methodologyOpen"
          >
            <span class="accordion-icon">{{ methodologyOpen ? '▾' : '▸' }}</span>
            方法論說明
          </button>
          <Transition name="details-expand">
            <div v-if="methodologyOpen" class="accordion-body methodology-body">
              <p>{{ narrative.methodology_note }}</p>
            </div>
          </Transition>
        </div>

        <div v-if="!narrative?.deep_dive_summary && !narrative?.methodology_note" class="empty-state">
          <p class="empty-text">暫無深度分析數據</p>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.trend-report {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* Section tabs */
.section-tabs {
  display: flex;
  gap: 0;
  border: 1px solid var(--border-color, #E5E7EB);
  border-radius: 8px;
  overflow: hidden;
}

.section-tab {
  flex: 1;
  padding: 10px 8px;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-muted, #9CA3AF);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}

.section-tab:not(:last-child) {
  border-right: 1px solid var(--border-color, #E5E7EB);
}

.section-tab.active {
  background: rgba(37, 99, 235, 0.06);
  color: var(--accent-blue, #2563EB);
  border-bottom-color: var(--accent-blue, #2563EB);
}

.section-tab:hover:not(.active) {
  background: var(--bg-secondary, #F9FAFB);
}

/* Section transitions */
.section-slide-enter-active,
.section-slide-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.section-slide-enter-from {
  opacity: 0;
  transform: translateY(8px);
}

.section-slide-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

/* Details expand transition */
.details-expand-enter-active,
.details-expand-leave-active {
  transition: all 0.25s ease;
  overflow: hidden;
}

.details-expand-enter-from,
.details-expand-leave-to {
  opacity: 0;
  max-height: 0;
}

/* Confidence banner */
.conf-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 600;
  border: 1px solid transparent;
}

.conf-banner.conf-high { background: #D1FAE5; border-color: #6EE7B7; color: #065F46; }
.conf-banner.conf-medium { background: #FEF9C3; border-color: #FDE68A; color: #78350F; }
.conf-banner.conf-low { background: #FEE2E2; border-color: #FCA5A5; color: #991B1B; }

.conf-icon { font-size: 18px; line-height: 1; }
.conf-label { flex: 1; }
.conf-score { font-size: 20px; font-weight: 800; }

/* Executive summary card */
.card {
  background: var(--bg-card, #fff);
  border: 1px solid var(--border-color, #E5E7EB);
  border-radius: 12px;
  padding: 20px;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.card-icon { font-size: 18px; }
.card-title { font-size: 15px; font-weight: 700; color: var(--text-primary, #111); }

.card-body {
  font-size: 14px;
  line-height: 1.7;
  color: var(--text-secondary, #374151);
  margin: 0;
}

.deep-body {
  white-space: pre-wrap;
}

.deep-dive-card {
  background: var(--bg-card, #fff);
  border: 1px solid var(--border-color, #E5E7EB);
  border-radius: 12px;
  padding: 20px;
}

/* Empty state */
.empty-state {
  text-align: center;
  padding: 48px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.empty-icon { font-size: 40px; }
.empty-text { font-size: 14px; color: var(--text-muted, #9CA3AF); margin: 0; }

/* Trends section */
.trends-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.section-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary, #6B7280);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.section-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* Trend card */
.trend-card {
  background: var(--bg-card, #fff);
  border: 1px solid var(--border-color, #E5E7EB);
  border-radius: 10px;
  overflow: hidden;
  transition: border-color 0.2s;
}

.trend-card.expanded { border-color: var(--accent-blue, #2563EB); }

.trend-header {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  background: none;
  border: none;
  cursor: pointer;
  text-align: left;
}

.trend-header:hover { background: var(--bg-secondary, #F9FAFB); }

.trend-dir-badge {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  font-weight: 700;
  flex-shrink: 0;
}

.dir-up { background: #D1FAE5; color: #065F46; }
.dir-down { background: #FEE2E2; color: #991B1B; }
.dir-flat { background: #F3F4F6; color: #6B7280; }
.dir-volatile { background: #FEF9C3; color: #78350F; }

.trend-title {
  flex: 1;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary, #111);
}

.conf-badge {
  font-size: 11px;
  font-weight: 600;
  border-radius: 4px;
  padding: 2px 8px;
  white-space: nowrap;
}

.conf-high { background: #D1FAE5; color: #065F46; }
.conf-medium { background: #FEF9C3; color: #78350F; }
.conf-low { background: #FEE2E2; color: #991B1B; }

.trend-toggle-icon {
  font-size: 16px;
  color: var(--text-muted, #9CA3AF);
  flex-shrink: 0;
}

.trend-narrative {
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary, #374151);
  margin: 0;
  padding: 0 16px 14px;
}

.trend-details {
  padding: 0 16px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  border-top: 1px solid var(--border-color, #E5E7EB);
  margin-top: 4px;
  padding-top: 14px;
}

.detail-label {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-secondary, #6B7280);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 6px;
}

.counter-label { color: #92400E; }

.evidence-list,
.counter-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.evidence-item,
.counter-item {
  display: flex;
  gap: 8px;
  font-size: 13px;
  line-height: 1.5;
  color: var(--text-secondary, #374151);
}

.evidence-bullet { color: #059669; font-size: 14px; flex-shrink: 0; }
.counter-bullet { color: #D97706; font-size: 14px; flex-shrink: 0; }

/* Accordion sections */
.accordion-section {
  background: var(--bg-card, #fff);
  border: 1px solid var(--border-color, #E5E7EB);
  border-radius: 10px;
  overflow: hidden;
}

.accordion-header {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 16px;
  background: none;
  border: none;
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary, #111);
  text-align: left;
}

.accordion-header:hover { background: var(--bg-secondary, #F9FAFB); }
.accordion-icon { font-size: 14px; color: var(--text-muted, #9CA3AF); }

.accordion-body {
  padding: 4px 16px 16px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-secondary, #374151);
}

.accordion-body p { margin: 0; }

.methodology .accordion-header { font-size: 13px; color: var(--text-secondary, #6B7280); }
.methodology-body { color: var(--text-muted, #9CA3AF); font-size: 12px; }

/* Backtest accuracy section */
.backtest-accuracy-section {
  background: var(--bg-card, #fff);
  border: 1px solid var(--border-color, #E5E7EB);
  border-radius: 12px;
  padding: 20px;
}

.backtest-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  margin-top: 12px;
}

.backtest-table th {
  text-align: left;
  padding: 8px;
  border-bottom: 2px solid var(--border-color, #E5E7EB);
  color: var(--text-secondary, #6B7280);
  font-weight: 600;
  font-size: 12px;
}

.backtest-table td {
  padding: 8px;
  border-bottom: 1px solid #F3F4F6;
  font-weight: 500;
}

.backtest-loading,
.backtest-empty {
  text-align: center;
  color: var(--text-muted, #9CA3AF);
  padding: 16px 0;
  font-size: 13px;
}
</style>
