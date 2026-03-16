<script setup>
</script>

<template>
  <div class="lesson-content">
    <div class="lesson-text">
      <p>每段種子文本都會經歷以下處理管道，最終成為知識圖譜中嘅節點同邊：</p>
    </div>
    <div class="pipeline-diagram glass-panel">
      <div class="pipeline-steps">
        <div class="pipeline-step" v-for="(step, i) in [
          { label: '原始文本', icon: '\uD83D\uDCC4', color: '#6B7280' },
          { label: '分詞', icon: '\u2702\uFE0F', color: '#2563EB' },
          { label: 'NER 命名體識別', icon: '\uD83C\uDFF7\uFE0F', color: '#7C3AED' },
          { label: '關係抽取', icon: '\uD83D\uDD17', color: '#D97706' },
          { label: 'KG 節點', icon: '\u2B21', color: '#059669' },
        ]" :key="i">
          <div class="ps-icon" :style="{ background: step.color }">{{ step.icon }}</div>
          <div class="ps-label">{{ step.label }}</div>
          <div v-if="i < 4" class="ps-arrow">\u2192</div>
        </div>
      </div>
      <div class="pipeline-example">
        <p class="example-label">示例：</p>
        <div class="example-text">「<strong>聯儲局</strong>宣布<strong>加息</strong> 0.25厘，影響<strong>香港樓市</strong>」</div>
        <div class="example-output">
          <span class="entity-chip org">聯儲局 (組織)</span>
          <span class="rel-arrow">\u2192 宣布 \u2192</span>
          <span class="entity-chip event">加息 (事件)</span>
          <span class="rel-arrow">\u2192 影響 \u2192</span>
          <span class="entity-chip economic">香港樓市 (經濟)</span>
        </div>
      </div>
    </div>
    <div class="lesson-text">
      <p>呢個過程由 DeepSeek V3.2 驅動，自動識別實體類型同因果關係，構建結構化知識表示。</p>
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

.pipeline-diagram {
  padding: 20px;
  margin: 16px 0;
}

.pipeline-steps {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
  margin-bottom: 20px;
}

.pipeline-step {
  display: flex;
  align-items: center;
  gap: 6px;
}

.ps-icon {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  color: #0d1117;
}

.ps-label {
  font-size: 12px;
  color: var(--text-secondary);
  max-width: 80px;
  line-height: 1.3;
}

.ps-arrow {
  font-size: 18px;
  color: var(--text-muted);
  margin: 0 4px;
}

.pipeline-example {
  border-top: 1px solid var(--border-color);
  padding-top: 16px;
}

.example-label {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 8px;
}

.example-text {
  font-size: 14px;
  color: var(--text-primary);
  margin-bottom: 12px;
  background: var(--bg-surface);
  padding: 8px 12px;
  border-radius: var(--radius-sm);
}

.example-output {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.entity-chip {
  padding: 3px 10px;
  border-radius: var(--radius-pill);
  font-size: 12px;
  font-weight: 600;
}

.entity-chip.org { background: rgba(124, 58, 237, 0.12); color: #7C3AED; }
.entity-chip.event { background: rgba(220, 38, 38, 0.1); color: #DC2626; }
.entity-chip.economic { background: rgba(5, 150, 105, 0.1); color: #059669; }

.rel-arrow {
  font-size: 12px;
  color: var(--text-muted);
}
</style>
