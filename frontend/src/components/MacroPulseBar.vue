<script setup>
import { ref, computed, watch } from 'vue'
import { getMacroHistory } from '../api/simulation.js'

const props = defineProps({
  sessionId: { type: String, default: '' },
  latestProgress: { type: Object, default: null }, // WebSocket progress payload
})

// Macro indicators we care about — keys must match _KEY_METRICS in macro_history.py
const INDICATORS = [
  { key: 'hsi_level', label: 'HSI', unit: '' },
  { key: 'unemployment_rate', label: '失業率', unit: '%' },
  { key: 'ccl_index', label: 'CCL', unit: '' },
  { key: 'gdp_growth', label: 'GDP', unit: '%' },
  { key: 'consumer_confidence', label: 'CCIdx', unit: '' },
]

const macroHistory = ref([])
const platformFilter = ref('all')

// Fetch full macro history once when sessionId is set
async function loadMacroHistory() {
  if (!props.sessionId) return
  try {
    const res = await getMacroHistory(props.sessionId)
    macroHistory.value = res.data?.data || []
  } catch { /* silent — bar degrades gracefully */ }
}

watch(() => props.sessionId, (id) => { if (id) loadMacroHistory() }, { immediate: true })

// Also refresh when new progress event arrives (new round)
watch(() => props.latestProgress, () => { if (props.sessionId) loadMacroHistory() })

// Build per-indicator sparkline data (last 8 rounds)
const indicatorCards = computed(() => {
  const recent = macroHistory.value.slice(-8)
  return INDICATORS.map(({ key, label, unit }) => {
    const values = recent.map(r => r[key]).filter(v => v != null)
    const latest = values[values.length - 1] ?? null
    const prev = values[values.length - 2] ?? latest
    const change = latest != null && prev != null ? latest - prev : null
    const positive = change != null ? change >= 0 : null
    return { key, label, unit, values, latest, change, positive }
  })
})

// Social sentiment from latest progress event (or latest macro history)
const sentiment = computed(() => {
  const p = props.latestProgress
  if (p?.social_sentiment) return p.social_sentiment
  const last = macroHistory.value[macroHistory.value.length - 1]
  if (last?.social_sentiment) return last.social_sentiment
  return null
})

// Sentiment values for the chosen platform filter
const sentimentValues = computed(() => {
  if (!sentiment.value) return { oppose: 0, neutral: 0, support: 0 }
  const s = sentiment.value
  if (platformFilter.value === 'all') {
    return {
      oppose: s.oppose_pct ?? 0,
      neutral: s.neutral_pct ?? 0,
      support: s.support_pct ?? 0,
    }
  }
  const byPlatform = s.by_platform?.[platformFilter.value]
  if (!byPlatform) return { oppose: 0, neutral: 0, support: 0 }
  return {
    oppose: byPlatform.oppose_pct ?? 0,
    neutral: byPlatform.neutral_pct ?? 0,
    support: byPlatform.support_pct ?? 0,
  }
})

// Compute SVG sparkline path for a series of values
function sparklinePath(values) {
  if (!values || values.length < 2) return ''
  const w = 48
  const h = 20
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  const pts = values.map((v, i) => {
    const x = (i / (values.length - 1)) * w
    const y = h - ((v - min) / range) * h
    return `${x},${y}`
  })
  return `M ${pts.join(' L ')}`
}

const PLATFORM_BTNS = [
  { key: 'all', label: 'All' },
  { key: 'facebook', label: 'FB' },
  { key: 'instagram', label: 'IG' },
  { key: 'lihkg', label: 'HKG' },
]
</script>

<template>
  <div class="macro-pulse-bar" v-if="macroHistory.length > 0 || sentiment">
    <!-- Indicator cards -->
    <div class="indicator-cards">
      <div
        v-for="card in indicatorCards"
        :key="card.key"
        class="indicator-card"
        :class="{ 'has-data': card.latest != null }"
      >
        <div class="ind-label">{{ card.label }}</div>
        <div
          class="ind-value"
          :class="{ positive: card.positive === true, negative: card.positive === false }"
        >
          {{ card.latest != null ? card.latest.toFixed(1) + card.unit : '—' }}
        </div>
        <div v-if="card.change != null" class="ind-change">
          {{ card.positive ? '+' : '' }}{{ card.change.toFixed(2) }}
        </div>
        <svg v-if="card.values.length >= 2" class="sparkline" width="48" height="20" viewBox="0 0 48 20">
          <path :d="sparklinePath(card.values)" fill="none" stroke="currentColor" stroke-width="1.5" />
        </svg>
      </div>
    </div>

    <!-- Divider -->
    <div class="divider" />

    <!-- Social sentiment — only shown when data is available from the DB -->
    <div class="sentiment-section" v-if="sentiment">
      <div class="sentiment-label">社交情感</div>
      <div class="sentiment-bar">
        <div class="seg oppose" :style="{ flex: sentimentValues.oppose }" />
        <div class="seg neutral" :style="{ flex: sentimentValues.neutral }" />
        <div class="seg support" :style="{ flex: sentimentValues.support }" />
      </div>
      <div class="sentiment-pct">
        {{ sentimentValues.oppose.toFixed(0) }}% 反 ·
        {{ sentimentValues.neutral.toFixed(0) }}% 中 ·
        {{ sentimentValues.support.toFixed(0) }}% 支
      </div>
      <!-- Platform filter buttons -->
      <div class="platform-btns">
        <button
          v-for="btn in PLATFORM_BTNS"
          :key="btn.key"
          class="plat-btn"
          :class="{ active: platformFilter === btn.key }"
          @click="platformFilter = btn.key"
        >{{ btn.label }}</button>
      </div>
    </div>
    <!-- Placeholder when sentiment data not yet available -->
    <div class="sentiment-section sentiment-pending" v-else>
      <div class="sentiment-label">社交情感</div>
      <div class="sentiment-pending-text">數據待收集</div>
    </div>
  </div>
</template>

<style scoped>
.macro-pulse-bar {
  flex-shrink: 0;
  height: 120px;
  background: #0f172a;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 16px;
  border-top: 1px solid #1e293b;
}

@media (max-width: 1199px) {
  .macro-pulse-bar {
    height: 40px;
  }
  .indicator-cards,
  .divider {
    display: none;
  }
}

.indicator-cards {
  display: flex;
  gap: 16px;
}

.indicator-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  min-width: 56px;
  opacity: 0.5;
}
.indicator-card.has-data { opacity: 1; }

.ind-label {
  font-size: 9px;
  font-weight: 700;
  color: #94a3b8;
  text-transform: uppercase;
}

.ind-value {
  font-size: 14px;
  font-weight: 700;
  color: #e2e8f0;
}
.ind-value.positive { color: #10b981; }
.ind-value.negative { color: #ef4444; }

.ind-change {
  font-size: 9px;
  color: #64748b;
}

.sparkline {
  color: #475569;
  margin-top: 2px;
}
.indicator-card.has-data .sparkline { color: #64748b; }

.divider {
  width: 1px;
  height: 60px;
  background: #334155;
  flex-shrink: 0;
}

.sentiment-section {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 140px;
}

.sentiment-label {
  font-size: 9px;
  font-weight: 700;
  color: #94a3b8;
  text-transform: uppercase;
}

.sentiment-bar {
  display: flex;
  height: 14px;
  border-radius: 3px;
  overflow: hidden;
  gap: 1px;
}

.seg { transition: flex 0.4s ease; }
.seg.oppose { background: #ef4444; }
.seg.neutral { background: #64748b; }
.seg.support { background: #3b82f6; }

.sentiment-pct {
  font-size: 9px;
  color: #64748b;
}

.platform-btns {
  display: flex;
  gap: 3px;
  margin-top: 2px;
}

.plat-btn {
  font-size: 9px;
  padding: 2px 5px;
  border-radius: 3px;
  background: #1e293b;
  color: #94a3b8;
  border: none;
  cursor: pointer;
  transition: background 0.15s;
}
.plat-btn.active,
.plat-btn:hover {
  background: #334155;
  color: #e2e8f0;
}

.sentiment-pending {
  opacity: 0.45;
}

.sentiment-pending-text {
  font-size: 9px;
  color: #475569;
  margin-top: 4px;
}
</style>
