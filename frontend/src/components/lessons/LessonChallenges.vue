<script setup>
import { useChallengeChecklist } from '../../composables/useLessonData.js'

const { checklist, allChecked, toggleCheck, resetChecklist } = useChallengeChecklist()
</script>

<template>
  <div class="lesson-content">
    <div class="lesson-text">
      <p>模擬結果唔應該被盲目接受。以下係 5 步批判性評估清單 — 每完成一步就剔一個：</p>
    </div>
    <div class="challenge-checklist glass-panel">
      <div
        v-for="item in checklist"
        :key="item.id"
        class="check-item"
        :class="{ checked: item.checked }"
        @click="toggleCheck(item.id)"
      >
        <div class="check-box">
          <svg v-if="item.checked" width="18" height="18" viewBox="0 0 18 18">
            <rect width="18" height="18" rx="4" fill="#059669" />
            <path d="M4 9l3 3 7-7" stroke="#fff" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          <svg v-else width="18" height="18" viewBox="0 0 18 18">
            <rect x="0.5" y="0.5" width="17" height="17" rx="3.5" fill="none" stroke="#D1D5DB" stroke-width="1" />
          </svg>
        </div>
        <div class="check-content">
          <div class="check-label">{{ item.label }}</div>
          <div class="check-detail">{{ item.detail }}</div>
        </div>
        <div class="check-step">{{ checklist.indexOf(item) + 1 }}/5</div>
      </div>
      <div v-if="allChecked" class="check-complete">
        全部完成！你已經掌握咗批判性評估模型嘅方法。
      </div>
      <button v-if="allChecked" class="reset-btn" @click="resetChecklist">重置</button>
    </div>
    <div class="lesson-text">
      <p>養成呢 5 步習慣，可以幫你避免過度依賴模型輸出，做出更明智嘅判斷。</p>
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

.challenge-checklist {
  padding: 16px 20px;
  margin: 16px 0;
}

.check-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  margin-bottom: 8px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.2s;
  background: var(--bg-surface);
}

.check-item:hover {
  background: var(--bg-secondary);
}

.check-item.checked {
  border-color: #059669;
  background: rgba(5, 150, 105, 0.04);
}

.check-box {
  flex-shrink: 0;
  margin-top: 1px;
}

.check-content {
  flex: 1;
}

.check-label {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 2px;
}

.check-detail {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.5;
}

.check-step {
  font-size: 11px;
  color: var(--text-muted);
  flex-shrink: 0;
}

.check-complete {
  margin-top: 12px;
  padding: 10px 14px;
  background: rgba(5, 150, 105, 0.1);
  color: #059669;
  border-radius: var(--radius-sm);
  font-size: 13px;
  font-weight: 600;
  text-align: center;
}

.reset-btn {
  display: block;
  margin: 10px auto 0;
  padding: 6px 16px;
  background: none;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  font-size: 12px;
  color: var(--text-muted);
  cursor: pointer;
  transition: var(--transition);
}

.reset-btn:hover {
  border-color: var(--text-secondary);
  color: var(--text-secondary);
}
</style>
