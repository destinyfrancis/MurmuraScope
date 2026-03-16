<script setup>
import { commonMistakes } from '../../composables/useLessonData.js'
</script>

<template>
  <div class="lesson-content">
    <div class="lesson-text">
      <p>以下係使用模擬預測時最常見嘅 5 個誤解。睇下你有冇中招：</p>
    </div>
    <div class="mistakes-grid">
      <div
        v-for="(pair, idx) in commonMistakes"
        :key="idx"
        class="mistake-card glass-panel"
      >
        <div class="mistake-number">#{{ idx + 1 }}</div>
        <div class="mistake-wrong">
          <span class="mistake-icon wrong-icon">\u2717</span>
          <span class="mistake-text">{{ pair.wrong }}</span>
        </div>
        <div class="mistake-arrow">\u2193</div>
        <div class="mistake-correct">
          <span class="mistake-icon correct-icon">\u2713</span>
          <span class="mistake-text">{{ pair.correct }}</span>
        </div>
      </div>
    </div>
    <div class="lesson-text">
      <p>記住：模擬係探索可能性嘅工具，唔係水晶球。理解呢啲常見錯誤可以幫你更有效咁使用預測結果。</p>
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

.mistakes-grid {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin: 16px 0;
}

.mistake-card {
  padding: 16px 20px;
  position: relative;
}

.mistake-number {
  position: absolute;
  top: 12px;
  right: 16px;
  font-size: 11px;
  font-weight: 700;
  color: var(--text-muted);
}

.mistake-wrong {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 12px;
  background: rgba(220, 38, 38, 0.06);
  border-radius: var(--radius-sm);
  border-left: 3px solid #DC2626;
}

.mistake-correct {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 12px;
  background: rgba(5, 150, 105, 0.06);
  border-radius: var(--radius-sm);
  border-left: 3px solid #059669;
}

.mistake-icon {
  flex-shrink: 0;
  font-size: 14px;
  font-weight: 700;
  margin-top: 1px;
}

.wrong-icon {
  color: #DC2626;
}

.correct-icon {
  color: #059669;
}

.mistake-text {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.5;
}

.mistake-arrow {
  text-align: center;
  color: var(--text-muted);
  font-size: 14px;
  margin: 4px 0;
}
</style>
