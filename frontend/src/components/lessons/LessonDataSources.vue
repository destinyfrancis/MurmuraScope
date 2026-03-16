<script setup>
import { useDataSources } from '../../composables/useLessonData.js'

const { sources: dataSourceCards, toggleSource } = useDataSources()

function stars(count) {
  return '\u2B50'.repeat(count) + '\u2606'.repeat(5 - count)
}
</script>

<template>
  <div class="lesson-content">
    <div class="lesson-text">
      <p>HKSimEngine 整合咗多個公開數據源。點擊每個類別了解詳情：</p>
    </div>
    <div class="datasource-list">
      <div
        v-for="src in dataSourceCards"
        :key="src.id"
        class="datasource-card glass-panel"
      >
        <div class="ds-header" @click="toggleSource(src.id)">
          <span class="ds-icon">{{ src.icon }}</span>
          <div class="ds-title">
            <div class="ds-category">{{ src.category }}</div>
            <div class="ds-source">{{ src.source }}</div>
          </div>
          <div class="ds-reliability">{{ stars(src.reliability) }}</div>
          <div class="ds-toggle">{{ src.expanded ? '\u25B2' : '\u25BC' }}</div>
        </div>
        <div v-if="src.expanded" class="ds-details">
          <div class="ds-items">
            <span v-for="item in src.items" :key="item" class="ds-item-chip">{{ item }}</span>
          </div>
          <div class="ds-meta">
            <div class="ds-meta-row">
              <span class="ds-meta-label">更新頻率</span>
              <span class="ds-meta-value">{{ src.frequency }}</span>
            </div>
            <div class="ds-meta-row">
              <span class="ds-meta-label">數據時滯</span>
              <span class="ds-meta-value">{{ src.lag }}</span>
            </div>
            <div class="ds-meta-row">
              <span class="ds-meta-label">可靠性</span>
              <span class="ds-meta-value">{{ src.reliability }} / 5</span>
            </div>
          </div>
        </div>
      </div>
    </div>
    <div class="lesson-text">
      <p>數據嘅時滯同可靠性直接影響模型預測嘅準確度。社交媒體數據雖然即時，但噪音較多；政府統計數據可靠但有 2-3 個月嘅延遲。</p>
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

.datasource-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 16px 0;
}

.datasource-card {
  overflow: hidden;
}

.ds-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  cursor: pointer;
  transition: background 0.15s;
}

.ds-header:hover {
  background: var(--bg-secondary);
}

.ds-icon {
  font-size: 24px;
  flex-shrink: 0;
}

.ds-title {
  flex: 1;
}

.ds-category {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.ds-source {
  font-size: 12px;
  color: var(--text-muted);
}

.ds-reliability {
  font-size: 12px;
  letter-spacing: 1px;
  flex-shrink: 0;
}

.ds-toggle {
  font-size: 10px;
  color: var(--text-muted);
  flex-shrink: 0;
}

.ds-details {
  padding: 12px 16px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-surface);
}

.ds-items {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 12px;
}

.ds-item-chip {
  padding: 3px 10px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-pill);
  font-size: 12px;
  color: var(--text-secondary);
}

.ds-meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.ds-meta-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.ds-meta-label {
  font-size: 12px;
  color: var(--text-muted);
  min-width: 80px;
}

.ds-meta-value {
  font-size: 13px;
  color: var(--text-primary);
  font-weight: 500;
}
</style>
