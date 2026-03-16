<script setup>
import { ref } from 'vue'
import GraphCanvas from './GraphCanvas.vue'
import GraphRoundScrubber from './GraphRoundScrubber.vue'

// Props interface is identical to the original GraphPanel so no parent changes needed
const props = defineProps({
  nodes: { type: Array, default: () => [] },
  edges: { type: Array, default: () => [] },
  highlightedNodes: { type: Array, default: () => [] },
  availableRounds: { type: Array, default: () => [] },
  currentRound: { type: Number, default: null },
  clusterData: { type: Object, default: null },
  contagionAgentIds: { type: Array, default: () => [] },
  communitySummaries: { type: Array, default: () => [] },
  tripleConflicts: { type: Array, default: () => [] },
  polarizationData: { type: Object, default: null },
  latestPosts: { type: Array, default: () => [] },
})

const emit = defineEmits(['node-click', 'round-change', 'hull-click'])

const canvasRef = ref(null)
const showEchoChambers = ref(false)

const typeColors = {
  person: '#2563EB',
  organization: '#7C3AED',
  policy: '#D97706',
  economic: '#059669',
  social: '#0891B2',
  event: '#DC2626',
  location: '#F59E0B',
  default: '#6B7280',
}

const typeLabels = {
  person: '人物',
  organization: '機構',
  policy: '政策',
  economic: '經濟',
  social: '社會',
  event: '事件',
  location: '地點',
  default: '其他',
}
</script>

<template>
  <div class="graph-panel">
    <GraphCanvas
      ref="canvasRef"
      :nodes="nodes"
      :edges="edges"
      :highlighted-nodes="highlightedNodes"
      :cluster-data="clusterData"
      :contagion-agent-ids="contagionAgentIds"
      :community-summaries="communitySummaries"
      :triple-conflicts="tripleConflicts"
      :polarization-data="polarizationData"
      :latest-posts="latestPosts"
      :show-echo-chambers="showEchoChambers"
      @node-click="n => emit('node-click', n)"
      @hull-click="h => emit('hull-click', h)"
    />

    <!-- Echo chamber toggle -->
    <button
      class="echo-toggle"
      :class="{ active: showEchoChambers }"
      @click="showEchoChambers = !showEchoChambers"
    >
      <span class="echo-icon">&#x25CE;</span>
      {{ showEchoChambers ? '隱藏同溫層' : '顯示同溫層' }}
    </button>

    <!-- Timeline slider (positioned absolutely via deep selector) -->
    <GraphRoundScrubber
      :available-rounds="availableRounds"
      :current-round="currentRound"
      @round-change="r => emit('round-change', r)"
    />

    <div class="legend">
      <div
        v-for="(color, type) in typeColors"
        :key="type"
        class="legend-item"
      >
        <span class="legend-dot" :style="{ background: color }" />
        <span class="legend-label">{{ typeLabels[type] || type }}</span>
      </div>
      <div v-if="showEchoChambers" class="legend-item">
        <span class="legend-line hostile" />
        <span class="legend-label">敵意連結</span>
      </div>
      <div v-if="showEchoChambers" class="legend-item">
        <span class="legend-dot contagion-dot" />
        <span class="legend-label">恐慌傳染</span>
      </div>
      <div v-if="showEchoChambers && tripleConflicts.length" class="legend-item">
        <span class="legend-line conflict-line" />
        <span class="legend-label">認知衝突</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.graph-panel {
  width: 100%;
  height: 100%;
  position: relative;
  min-height: 300px;
}

/* Position the round scrubber at top-center via deep pierce */
:deep(.timeline-slider) {
  position: absolute;
  top: 10px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 10;
}

.echo-toggle {
  position: absolute;
  top: 10px;
  right: 10px;
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm, 6px);
  color: var(--text-muted, #9CA3AF);
  font-size: 12px;
  cursor: pointer;
  transition: background 0.2s, border-color 0.2s, color 0.2s;
  z-index: 10;
  user-select: none;
}

.echo-toggle:hover {
  background: var(--bg-secondary);
  border-color: var(--border-emphasis);
}

.echo-toggle.active {
  background: rgba(220, 38, 38, 0.08);
  border-color: rgba(220, 38, 38, 0.3);
  color: var(--accent-red);
}

.echo-icon {
  font-size: 14px;
}

.legend {
  position: absolute;
  bottom: 10px;
  left: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 12px;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm, 6px);
  font-size: 11px;
  pointer-events: none;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.legend-label {
  color: var(--text-secondary, #4B5563);
  text-transform: capitalize;
}

.legend-line.hostile {
  width: 18px;
  height: 0;
  border-top: 3px dashed #ef4444;
  flex-shrink: 0;
}

.legend-line.conflict-line {
  width: 18px;
  height: 0;
  border-top: 2px dashed #ef4444;
  flex-shrink: 0;
  opacity: 0.6;
}

.contagion-dot {
  background: #ef4444 !important;
  box-shadow: 0 0 6px 2px rgba(239, 68, 68, 0.5);
  animation: contagion-pulse 1.5s ease-in-out infinite;
}

@keyframes contagion-pulse {
  0%, 100% { box-shadow: 0 0 4px 1px rgba(239, 68, 68, 0.4); }
  50% { box-shadow: 0 0 8px 3px rgba(239, 68, 68, 0.7); }
}
</style>
