<script setup>
import { ref } from 'vue'

const uncertaintySources = ref([
  { label: '代理人行為隨機性', pct: 35, detail: '每個 AI 代理人嘅 LLM 決策有內在隨機性，係冇辦法完全控制嘅。', expanded: false },
  { label: '宏觀數據誤差', pct: 25, detail: 'GDP、失業率等宏觀數據有測量誤差同修訂，直接影響初始條件。', expanded: false },
  { label: '模型結構假設', pct: 22, detail: '消費函數、信任衰減率等參數係由校準數據估計，有統計不確定性。', expanded: false },
  { label: '外部衝擊不可預測性', pct: 18, detail: '地緣政治事件、自然災害等外生衝擊無法提前納入模型。', expanded: false },
])

function toggleUncertainty(idx) {
  uncertaintySources.value = uncertaintySources.value.map((s, i) =>
    i === idx ? { ...s, expanded: !s.expanded } : s
  )
}
</script>

<template>
  <div class="lesson-content">
    <div class="lesson-text">
      <p>HKSimEngine 嘅預測不確定性來自四個主要來源。點擊每個來源了解更多：</p>
    </div>
    <div class="uncertainty-chart glass-panel">
      <div
        v-for="(source, idx) in uncertaintySources"
        :key="idx"
        class="uncertainty-row"
      >
        <div class="uncertainty-header" @click="toggleUncertainty(idx)">
          <div class="u-label">{{ source.label }}</div>
          <div class="u-bar-wrap">
            <div class="u-bar" :style="{ width: source.pct + '%', background: `hsl(${200 + idx * 40}, 70%, 50%)` }" />
          </div>
          <div class="u-pct">{{ source.pct }}%</div>
          <div class="u-toggle">{{ source.expanded ? '\u25B2' : '\u25BC' }}</div>
        </div>
        <div v-if="source.expanded" class="u-detail">
          {{ source.detail }}
        </div>
      </div>
    </div>
    <div class="lesson-text">
      <p>透明地呈現不確定性係負責任 AI 預測嘅核心原則。HKSimEngine 唔係「預言機」，而係幫助思考多個可能未來嘅工具。</p>
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

.uncertainty-chart {
  padding: 16px 20px;
  margin: 16px 0;
}

.uncertainty-row {
  margin-bottom: 8px;
  border-radius: var(--radius-sm);
  overflow: hidden;
  border: 1px solid var(--border-color);
}

.uncertainty-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  cursor: pointer;
  background: var(--bg-surface);
  transition: background 0.15s;
}

.uncertainty-header:hover {
  background: var(--bg-secondary);
}

.u-label {
  font-size: 13px;
  color: var(--text-primary);
  min-width: 160px;
}

.u-bar-wrap {
  flex: 1;
  height: 8px;
  background: var(--bg-input);
  border-radius: 4px;
  overflow: hidden;
}

.u-bar {
  height: 100%;
  border-radius: 4px;
  transition: width 0.5s;
}

.u-pct {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
  min-width: 36px;
  text-align: right;
}

.u-toggle {
  font-size: 10px;
  color: var(--text-muted);
}

.u-detail {
  padding: 10px 12px;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.6;
  background: var(--bg-card);
  border-top: 1px solid var(--border-color);
}
</style>
