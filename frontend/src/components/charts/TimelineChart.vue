<script setup>
import { computed } from 'vue'

const props = defineProps({
  chartRounds: { type: Array, required: true },
  getSentimentRow: { type: Function, required: true },
  forkInfo: { type: Object, default: null },
})

const SVG_W = 600
const SVG_H = 120
const PADDING = { top: 12, right: 20, bottom: 24, left: 36 }

const yLabels = [0, 25, 50, 75, 100]

function yLabelCoord(val) {
  const plotH = SVG_H - PADDING.top - PADDING.bottom
  return PADDING.top + plotH - (val / 100) * plotH
}

const timelinePoints = computed(() => {
  const allRounds = props.chartRounds
  if (allRounds.length === 0) return { a: [], b: [], forkX: null }

  const minR = allRounds[0]
  const maxR = allRounds[allRounds.length - 1]
  const xRange = maxR - minR || 1
  const plotW = SVG_W - PADDING.left - PADDING.right
  const plotH = SVG_H - PADDING.top - PADDING.bottom

  function toX(r) {
    return PADDING.left + ((r - minR) / xRange) * plotW
  }
  function sentimentScore(row) {
    if (!row || !row.total) return 50
    return Math.round((row.pos / row.total) * 100)
  }
  function toY(score) {
    return PADDING.top + plotH - (score / 100) * plotH
  }

  const getPoints = (sessionKey) =>
    allRounds.map((r) => {
      const row = props.getSentimentRow(sessionKey, r)
      return { x: toX(r), y: toY(sentimentScore(row)), round: r }
    })

  const ptsA = getPoints('session_a')
  const ptsB = getPoints('session_b')

  const forkRound = props.forkInfo?.fork_round
  const forkX = forkRound != null ? toX(forkRound) : null

  return { a: ptsA, b: ptsB, forkX, plotW, plotH }
})

function polyline(pts) {
  if (!pts || pts.length === 0) return ''
  return pts.map((p) => `${p.x},${p.y}`).join(' ')
}
</script>

<template>
  <div class="timeline-chart-wrap">
    <svg
      class="timeline-svg"
      :viewBox="`0 0 ${SVG_W} ${SVG_H}`"
      preserveAspectRatio="xMidYMid meet"
    >
      <!-- Y-axis guide lines + labels -->
      <g v-for="val in yLabels" :key="val">
        <line
          :x1="PADDING.left"
          :y1="yLabelCoord(val)"
          :x2="SVG_W - PADDING.right"
          :y2="yLabelCoord(val)"
          stroke="rgba(0,0,0,0.08)"
          stroke-width="1"
        />
        <text
          :x="PADDING.left - 4"
          :y="yLabelCoord(val) + 4"
          fill="#9CA3AF"
          font-size="9"
          text-anchor="end"
        >{{ val }}%</text>
      </g>

      <!-- Session A line (blue) -->
      <polyline
        v-if="timelinePoints.a.length > 1"
        :points="polyline(timelinePoints.a)"
        fill="none"
        stroke="#2563EB"
        stroke-width="2"
        stroke-linejoin="round"
        stroke-linecap="round"
        opacity="0.9"
      />
      <!-- Session B line (green) -->
      <polyline
        v-if="timelinePoints.b.length > 1"
        :points="polyline(timelinePoints.b)"
        fill="none"
        stroke="#34d399"
        stroke-width="2"
        stroke-linejoin="round"
        stroke-linecap="round"
        opacity="0.9"
      />

      <!-- Fork vertical indicator -->
      <g v-if="timelinePoints.forkX != null">
        <line
          :x1="timelinePoints.forkX"
          y1="0"
          :x2="timelinePoints.forkX"
          :y2="SVG_H - PADDING.bottom"
          stroke="#a78bfa"
          stroke-width="1.5"
          stroke-dasharray="4,3"
        />
        <text
          :x="timelinePoints.forkX + 3"
          y="11"
          fill="#a78bfa"
          font-size="9"
        >分叉點</text>
      </g>

      <!-- Data point dots for A -->
      <circle
        v-for="pt in timelinePoints.a"
        :key="`a-${pt.round}`"
        :cx="pt.x"
        :cy="pt.y"
        r="2.5"
        fill="#2563EB"
        opacity="0.8"
      />
      <!-- Data point dots for B -->
      <circle
        v-for="pt in timelinePoints.b"
        :key="`b-${pt.round}`"
        :cx="pt.x"
        :cy="pt.y"
        r="2.5"
        fill="#34d399"
        opacity="0.8"
      />
    </svg>
    <div class="timeline-legend">
      <span class="tl-dot" style="background:#2563EB" /> 情景 A
      <span class="tl-dot" style="background:#34d399; margin-left:12px" /> 情景 B
      <span v-if="forkInfo?.fork_round != null" class="tl-dot" style="background:#a78bfa; margin-left:12px; border-radius:2px" />
      <span v-if="forkInfo?.fork_round != null" style="margin-left:4px; color:#a78bfa">分叉點</span>
    </div>
    <p v-if="chartRounds.length === 0" class="no-data">暫無情感數據</p>
  </div>
</template>

<style scoped>
.timeline-chart-wrap {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  padding: 8px;
}

.timeline-svg {
  width: 100%;
  height: 120px;
  display: block;
}

.timeline-legend {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 6px;
  padding-left: 4px;
}

.tl-dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.no-data {
  font-size: 13px;
  color: var(--text-muted);
  text-align: center;
  padding: 20px;
}
</style>
