<script setup>
defineProps({
  currentRound:    { type: Number,  required: true },
  totalRounds:     { type: Number,  required: true },
  progressPercent: { type: Number,  required: true },
  running:         { type: Boolean, default: false },
  completed:       { type: Boolean, default: false },
  tokenCostUsd:    { type: Number,  default: 0 },
  modelName:       { type: String,  default: '' },
  simMode:         { type: String,  default: '' },
})

const emit = defineEmits(['open-fork', 'abort'])

function handleAbort() {
  if (confirm('確定要中止模擬？此操作不可逆。')) {
    emit('abort')
  }
}
</script>

<template>
  <div class="sim-header">
    <div class="round-info">
      <span class="round-label">回合</span>
      <span class="round-value">{{ currentRound }} / {{ totalRounds }}</span>
    </div>
    <div class="progress-bar">
      <div class="progress-fill" :style="{ width: progressPercent + '%' }" />
    </div>
    <div class="sim-status">
      <span v-if="running"    class="status-badge running status-pulse">模擬中</span>
      <span v-else-if="completed" class="status-badge completed">已完成</span>
      <span v-else            class="status-badge idle">待開始</span>
    </div>
    <span v-if="modelName" class="model-tag">MODEL: {{ modelName }}</span>
    <span v-if="tokenCostUsd > 0" class="cost-tag">${{ tokenCostUsd.toFixed(4) }} USD</span>
    <button
      v-if="running"
      class="abort-btn"
      @click="handleAbort"
    >
      &#x25A0; 中止
    </button>
    <button
      v-if="completed"
      class="fork-btn"
      @click="emit('open-fork')"
    >
      &#x2442; 分叉模擬
    </button>
  </div>
</template>

<style scoped>
.sim-header {
  display: flex;
  align-items: center;
  gap: 16px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 12px 20px;
  flex-shrink: 0;
}

.round-info {
  display: flex;
  align-items: baseline;
  gap: 8px;
  white-space: nowrap;
}

.round-label {
  font-size: 13px;
  color: var(--text-muted);
}

.round-value {
  font-size: 18px;
  font-weight: 700;
  color: var(--accent-blue);
}

.progress-bar {
  flex: 1;
  height: 6px;
  background: var(--bg-primary);
  border-radius: 3px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--accent-blue), var(--accent-cyan));
  border-radius: 3px;
  transition: width 0.3s ease;
}

.sim-status {
  white-space: nowrap;
}

.status-badge {
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
}

.status-badge.running {
  background: rgba(74, 158, 255, 0.15);
  color: var(--accent-blue);
}

.status-badge.completed {
  background: rgba(52, 211, 153, 0.15);
  color: var(--accent-green);
}

.status-badge.idle {
  background: var(--bg-input);
  color: var(--text-muted);
}

.model-tag {
  font-size: 11px;
  color: var(--text-muted);
  white-space: nowrap;
  letter-spacing: 0.03em;
}

.cost-tag {
  font-size: 11px;
  color: var(--accent-green);
  white-space: nowrap;
  font-weight: 600;
}

.abort-btn {
  padding: 6px 14px;
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: var(--radius-sm);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: var(--transition);
  flex-shrink: 0;
}

.abort-btn:hover {
  background: rgba(239, 68, 68, 0.28);
}

.fork-btn {
  padding: 6px 14px;
  background: rgba(167, 139, 250, 0.15);
  color: #a78bfa;
  border: 1px solid rgba(167, 139, 250, 0.3);
  border-radius: var(--radius-sm);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: var(--transition);
  flex-shrink: 0;
}

.fork-btn:hover {
  background: rgba(167, 139, 250, 0.25);
}

/* Breathing pulse for running status */
.status-pulse {
  animation: status-pulse-anim 2s ease-in-out infinite;
}

@keyframes status-pulse-anim {
  0%, 100% { box-shadow: 0 0 0 0 rgba(74, 158, 255, 0.4); }
  50%       { box-shadow: 0 0 0 6px rgba(74, 158, 255, 0); }
}
</style>
