<script setup>
const props = defineProps({
  show: { type: Boolean, required: true },
  currentRound: { type: Number, default: 0 },
  totalRounds: { type: Number, default: 30 },
  loading: { type: Boolean, default: false },
  error: { type: String, default: null },
  result: { type: Object, default: null },
})

const emit = defineEmits(['close', 'submit'])

import { ref, watch } from 'vue'

const forkRound = ref(null)
const forkLabel = ref('')

watch(() => props.show, (visible) => {
  if (visible) {
    forkRound.value = props.currentRound > 0 ? props.currentRound : null
    forkLabel.value = ''
  }
})

function handleSubmit() {
  emit('submit', {
    fork_round: forkRound.value !== null && forkRound.value !== '' ? Number(forkRound.value) : null,
    label: forkLabel.value.trim() || null,
  })
}
</script>

<template>
  <teleport to="body">
    <div v-if="show" class="fork-overlay" @click.self="emit('close')">
      <div class="fork-modal">
        <div class="fork-modal-header">
          <h4 class="fork-modal-title">建立分叉模擬</h4>
          <button class="fork-modal-close" @click="emit('close')">&#x2715;</button>
        </div>
        <div class="fork-modal-body">
          <div class="fork-field">
            <label class="fork-label">分叉輪次（留空則從頭開始）</label>
            <input
              v-model="forkRound"
              type="number"
              class="fork-input"
              :placeholder="`目前回合：${currentRound}`"
              :min="1"
              :max="totalRounds"
            />
            <p class="fork-hint">將複製此輪次及之前的所有代理記憶與行為。</p>
          </div>
          <div class="fork-field">
            <label class="fork-label">分叉標籤（可選）</label>
            <input
              v-model="forkLabel"
              type="text"
              class="fork-input"
              placeholder="例：高通脹情景"
              maxlength="80"
            />
          </div>
          <p v-if="error" class="fork-error">{{ error }}</p>
          <div v-if="result" class="fork-success">
            <p>&#x2713; 分叉建立成功！</p>
            <p class="fork-id">分叉 ID：{{ result.branch_id }}</p>
          </div>
        </div>
        <div class="fork-modal-footer">
          <button class="fork-cancel-btn" @click="emit('close')">取消</button>
          <button
            class="fork-confirm-btn"
            :disabled="loading || !!result"
            @click="handleSubmit"
          >
            {{ loading ? '建立中...' : result ? '已建立' : '確認分叉' }}
          </button>
        </div>
      </div>
    </div>
  </teleport>
</template>

<style scoped>
.fork-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.fork-modal {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  width: 400px;
  max-width: 90vw;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.fork-modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
}

.fork-modal-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
}

.fork-modal-close {
  background: transparent;
  border: none;
  color: var(--text-muted);
  font-size: 14px;
  cursor: pointer;
  padding: 2px 6px;
}

.fork-modal-close:hover {
  color: var(--text-primary);
}

.fork-modal-body {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.fork-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.fork-label {
  font-size: 12px;
  color: var(--text-muted);
  font-weight: 500;
}

.fork-input {
  padding: 8px 10px;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-size: 13px;
  outline: none;
}

.fork-input:focus {
  border-color: #a78bfa;
}

.fork-hint {
  margin: 0;
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.4;
}

.fork-error {
  margin: 0;
  font-size: 13px;
  color: var(--accent-red);
}

.fork-success {
  padding: 10px 12px;
  background: rgba(52, 211, 153, 0.08);
  border: 1px solid rgba(52, 211, 153, 0.2);
  border-radius: var(--radius-sm);
  font-size: 13px;
  color: var(--accent-green);
}

.fork-id {
  margin: 4px 0 0;
  font-size: 11px;
  font-family: monospace;
  opacity: 0.8;
}

.fork-modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 14px 20px;
  border-top: 1px solid var(--border-color);
}

.fork-cancel-btn {
  padding: 8px 16px;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
}

.fork-cancel-btn:hover {
  color: var(--text-primary);
}

.fork-confirm-btn {
  padding: 8px 18px;
  background: #7c3aed;
  border: none;
  border-radius: var(--radius-sm);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: var(--transition);
}

.fork-confirm-btn:hover:not(:disabled) {
  background: #6d28d9;
}

.fork-confirm-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
