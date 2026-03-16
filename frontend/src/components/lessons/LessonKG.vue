<script setup>
import { ref } from 'vue'
import { kgNodes, kgEdges, typeColors } from '../../composables/useLessonData.js'

const hoveredNode = ref(null)
</script>

<template>
  <div class="lesson-content">
    <div class="lesson-text">
      <p>知識圖譜將複雜議題拆解成 <strong>實體</strong>（節點）同 <strong>關係</strong>（邊）。將滑鼠移到節點上面睇描述。</p>
    </div>
    <div class="kg-container glass-panel">
      <svg width="600" height="400" class="kg-svg">
        <line
          v-for="(edge, i) in kgEdges"
          :key="'e'+i"
          :x1="kgNodes.find(n => n.id === edge.from).x"
          :y1="kgNodes.find(n => n.id === edge.from).y"
          :x2="kgNodes.find(n => n.id === edge.to).x"
          :y2="kgNodes.find(n => n.id === edge.to).y"
          stroke="#D1D5DB"
          stroke-width="1.5"
        />
        <g
          v-for="node in kgNodes"
          :key="node.id"
          @mouseenter="hoveredNode = node"
          @mouseleave="hoveredNode = null"
          style="cursor: pointer"
        >
          <circle
            :cx="node.x" :cy="node.y" r="10"
            :fill="typeColors[node.type]" stroke="#fff" stroke-width="2"
          />
          <text
            :x="node.x" :y="node.y - 14"
            text-anchor="middle" font-size="11" fill="#4B5563"
          >{{ node.label }}</text>
        </g>
      </svg>
      <div
        v-if="hoveredNode"
        class="kg-tooltip"
        :style="{ left: hoveredNode.x + 20 + 'px', top: hoveredNode.y - 10 + 'px' }"
      >
        <span class="kg-tooltip-type" :style="{ color: typeColors[hoveredNode.type] }">
          {{ hoveredNode.type }}
        </span>
        <span class="kg-tooltip-label">{{ hoveredNode.label }}</span>
      </div>
    </div>
    <div class="lesson-text">
      <p>模擬過程中，代理人嘅行動會更新圖譜上嘅邊權重 — 反映因果關係嘅強度變化。</p>
    </div>
  </div>
</template>

<style scoped>
.lesson-content {
  animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

.lesson-text {
  margin: 16px 0;
  line-height: 1.8;
  color: var(--text-secondary);
  font-size: 15px;
}

.lesson-text strong {
  color: var(--text-primary);
}

.kg-container {
  position: relative;
  padding: 0;
  overflow: hidden;
  margin: 16px 0;
}

.kg-svg {
  width: 100%;
  height: auto;
  display: block;
  background: var(--bg-surface);
}

.kg-tooltip {
  position: absolute;
  padding: 6px 10px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow-sm);
  font-size: 12px;
  pointer-events: none;
  z-index: 10;
}

.kg-tooltip-type {
  font-weight: 600;
  margin-right: 4px;
}

.kg-tooltip-label {
  color: var(--text-primary);
}
</style>
