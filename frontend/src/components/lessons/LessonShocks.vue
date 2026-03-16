<script setup>
import { ref } from 'vue'

const miniNodes = ref([
  { id: 1, label: '中央銀行', color: '#4ecca3', sentiment: 'neutral' },
  { id: 2, label: '銀行業', color: '#a0a0ff', sentiment: 'neutral' },
  { id: 3, label: '置業者', color: '#e94560', sentiment: 'neutral' },
])

function injectShock() {
  miniNodes.value = miniNodes.value.map(n => ({ ...n, sentiment: 'neutral' }))
  setTimeout(() => {
    miniNodes.value = miniNodes.value.map((n, i) =>
      i === 0 ? { ...n, sentiment: 'warning', color: '#f59e0b' } : n
    )
  }, 400)
  setTimeout(() => {
    miniNodes.value = miniNodes.value.map((n, i) =>
      i <= 1 ? { ...n, sentiment: 'negative', color: '#e94560' } : n
    )
  }, 900)
  setTimeout(() => {
    miniNodes.value = miniNodes.value.map(n => ({
      ...n, sentiment: 'negative', color: '#e94560',
    }))
  }, 1400)
}
</script>

<template>
  <div class="lesson-content">
    <div class="lesson-text">
      <p>點擊「注入加息」，睇下情感如何喺代理人網絡中擴散：</p>
    </div>
    <div class="mini-sim glass-panel">
      <div class="mini-nodes">
        <div
          v-for="node in miniNodes"
          :key="node.id"
          class="mini-node"
          :style="{ background: node.color, borderColor: node.color }"
        >
          {{ node.label }}
        </div>
      </div>
      <div class="mini-arrows">
        <svg width="100%" height="40" viewBox="0 0 300 40">
          <defs>
            <marker id="arr" markerWidth="6" markerHeight="6" refX="3" refY="3" orient="auto">
              <path d="M0,0 L6,3 L0,6 Z" fill="#666" />
            </marker>
          </defs>
          <line x1="90" y1="20" x2="140" y2="20" stroke="#666" stroke-width="1.5" marker-end="url(#arr)" />
          <line x1="180" y1="20" x2="230" y2="20" stroke="#666" stroke-width="1.5" marker-end="url(#arr)" />
        </svg>
      </div>
      <button class="shock-btn" @click="injectShock">注入加息</button>
    </div>
    <div class="lesson-text">
      <p>情感傳播遵循信任網絡結構 — 被高度信任嘅意見領袖影響力最大，情感可以跨越多個 hop 傳播。</p>
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

.mini-sim {
  padding: 20px;
  margin: 16px 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.mini-nodes {
  display: flex;
  gap: 40px;
  align-items: center;
}

.mini-node {
  padding: 10px 16px;
  border-radius: 8px;
  border: 2px solid;
  color: #0d1117;
  font-size: 13px;
  font-weight: 600;
  transition: background 0.4s, border-color 0.4s;
}

.mini-arrows {
  width: 300px;
}

.shock-btn {
  padding: 8px 20px;
  background: var(--accent-blue, #2563EB);
  color: #0d1117;
  border: none;
  border-radius: var(--radius-md, 8px);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s;
  margin-top: 8px;
}

.shock-btn:hover {
  background: #1d4ed8;
}
</style>
