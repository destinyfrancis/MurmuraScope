<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  score: { type: Number, required: true },
  size: { type: String, default: 'md' },
  /** Optional breakdown: { validation_score, mc_convergence, consensus_level } */
  breakdown: { type: Object, default: null },
  /** Previous score for trend arrow */
  previousScore: { type: Number, default: null },
  /** Historical backtest MAPE (%) for this metric */
  backtestMape: { type: Number, default: null },
})

const showTooltip = ref(false)

const level = computed(() => {
  if (props.score >= 0.7) return 'high'
  if (props.score >= 0.4) return 'medium'
  return 'low'
})

const label = computed(() => {
  if (props.score >= 0.7) return '高信心'
  if (props.score >= 0.4) return '中信心'
  return '低信心'
})

const pct = computed(() => Math.round(props.score * 100))

const trendArrow = computed(() => {
  if (props.previousScore == null) return null
  const diff = props.score - props.previousScore
  if (diff > 0.02) return { icon: '↑', cls: 'trend-up' }
  if (diff < -0.02) return { icon: '↓', cls: 'trend-down' }
  return { icon: '→', cls: 'trend-flat' }
})

const hasBreakdown = computed(() => {
  if (props.backtestMape != null) return true
  if (!props.breakdown) return false
  return props.breakdown.validation_score != null ||
    props.breakdown.mc_convergence != null ||
    props.breakdown.consensus_level != null
})

function mapeLevel(mape) {
  if (mape == null) return ''
  if (mape < 5) return 'bd-high'
  if (mape < 15) return 'bd-medium'
  return 'bd-low'
}

function formatBreakdownPct(val) {
  if (val == null) return '—'
  return Math.round(val * 100) + '%'
}

function breakdownLevel(val) {
  if (val == null) return ''
  if (val >= 0.7) return 'bd-high'
  if (val >= 0.4) return 'bd-medium'
  return 'bd-low'
}
</script>

<template>
  <span
    :class="['confidence-badge', `confidence-${level}`, `size-${size}`]"
    @mouseenter="showTooltip = true"
    @mouseleave="showTooltip = false"
  >
    <span class="confidence-dot" />
    <span class="confidence-label">{{ label }}</span>
    <span class="confidence-pct">{{ pct }}%</span>
    <span v-if="trendArrow" class="confidence-trend" :class="trendArrow.cls">
      {{ trendArrow.icon }}
    </span>

    <!-- Tooltip -->
    <Transition name="tooltip-fade">
      <div v-if="showTooltip && hasBreakdown" class="confidence-tooltip">
        <div class="tooltip-title">信心度分解</div>
        <div class="tooltip-row" v-if="backtestMape != null">
          <span class="tooltip-label">Historical MAPE</span>
          <span class="tooltip-value" :class="mapeLevel(backtestMape)">
            {{ backtestMape.toFixed(1) }}%
          </span>
        </div>
        <div class="tooltip-row" v-if="breakdown && breakdown.validation_score != null">
          <span class="tooltip-label">驗證分數</span>
          <span class="tooltip-value" :class="breakdownLevel(breakdown.validation_score)">
            {{ formatBreakdownPct(breakdown.validation_score) }}
          </span>
        </div>
        <div class="tooltip-row" v-if="breakdown && breakdown.mc_convergence != null">
          <span class="tooltip-label">MC 收斂度</span>
          <span class="tooltip-value" :class="breakdownLevel(breakdown.mc_convergence)">
            {{ formatBreakdownPct(breakdown.mc_convergence) }}
          </span>
        </div>
        <div class="tooltip-row" v-if="breakdown && breakdown.consensus_level != null">
          <span class="tooltip-label">共識水平</span>
          <span class="tooltip-value" :class="breakdownLevel(breakdown.consensus_level)">
            {{ formatBreakdownPct(breakdown.consensus_level) }}
          </span>
        </div>
      </div>
    </Transition>
  </span>
</template>

<style scoped>
.confidence-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 10px;
  border-radius: var(--radius-pill, 9999px);
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
  position: relative;
  cursor: default;
}

.size-sm {
  padding: 2px 8px;
  font-size: 11px;
  gap: 4px;
}

.size-lg {
  padding: 4px 14px;
  font-size: 14px;
  gap: 6px;
}

.confidence-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.confidence-high {
  background: rgba(0, 217, 101, 0.12);
  border: 1px solid rgba(0, 217, 101, 0.3);
  color: var(--accent-green);
}

.confidence-high .confidence-dot {
  background: var(--accent-green);
}

.confidence-medium {
  background: rgba(255, 159, 67, 0.12);
  border: 1px solid rgba(255, 159, 67, 0.3);
  color: var(--accent-orange);
}

.confidence-medium .confidence-dot {
  background: var(--accent-orange);
}

.confidence-low {
  background: rgba(255, 68, 68, 0.12);
  border: 1px solid rgba(255, 68, 68, 0.3);
  color: var(--accent-red);
}

.confidence-low .confidence-dot {
  background: var(--accent-red);
}

.confidence-pct {
  opacity: 0.7;
  font-size: 0.9em;
}

.confidence-trend {
  font-size: 0.85em;
  font-weight: 700;
}

.trend-up { color: var(--accent-green); }
.trend-down { color: var(--accent-red); }
.trend-flat { color: var(--text-muted); }

/* Tooltip */
.confidence-tooltip {
  position: absolute;
  top: calc(100% + 8px);
  left: 50%;
  transform: translateX(-50%);
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 10px 12px;
  min-width: 160px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5);
  z-index: 100;
  pointer-events: none;
}

.tooltip-title {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 8px;
  text-align: center;
}

.tooltip-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 3px 0;
  font-size: 11px;
}

.tooltip-label {
  color: var(--text-muted, #9CA3AF);
}

.tooltip-value {
  font-weight: 600;
}

.bd-high { color: var(--accent-green); }
.bd-medium { color: var(--accent-orange); }
.bd-low { color: var(--accent-red); }

.tooltip-fade-enter-active,
.tooltip-fade-leave-active {
  transition: opacity 0.15s ease;
}

.tooltip-fade-enter-from,
.tooltip-fade-leave-to {
  opacity: 0;
}
</style>
