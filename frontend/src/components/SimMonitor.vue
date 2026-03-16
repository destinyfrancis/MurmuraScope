<script setup>
import { ref, watch, nextTick } from 'vue'

const props = defineProps({
  logs: { type: Array, default: () => [] },
})

const logContainer = ref(null)

watch(
  () => props.logs.length,
  () => {
    nextTick(() => {
      if (logContainer.value) {
        logContainer.value.scrollTop = logContainer.value.scrollHeight
      }
    })
  }
)

function typeClass(type) {
  return type || 'info'
}
</script>

<template>
  <div class="sim-monitor">
    <div class="monitor-header">
      <span class="monitor-title">MONITOR</span>
      <span class="monitor-dot" />
    </div>
    <div ref="logContainer" class="log-output">
      <div v-if="logs.length === 0" class="log-empty">
        等待模擬日誌...
      </div>
      <div
        v-for="(log, i) in logs"
        :key="i"
        class="log-line"
        :class="typeClass(log.type)"
      >
        <span class="log-time">{{ log.timestamp }}</span>
        <span class="log-msg">{{ log.message }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sim-monitor {
  display: flex;
  flex-direction: column;
  height: 100%;
  font-family: var(--font-mono, 'JetBrains Mono', 'SF Mono', 'Fira Code', monospace);
  background: var(--bg-card);
  border: 1px solid var(--border-color);
}

.monitor-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-color);
}

.monitor-title {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-muted);
  letter-spacing: 1px;
}

.monitor-dot {
  width: 6px;
  height: 6px;
  background: var(--accent-green);
  border-radius: 50%;
  animation: blink 2s ease-in-out infinite;
}

@keyframes blink {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.3;
  }
}

.log-output {
  flex: 1;
  overflow-y: auto;
  padding: 8px 12px;
  background: var(--bg-primary);
  font-size: 12px;
  line-height: 1.6;
}

.log-empty {
  color: var(--text-muted);
  font-size: 12px;
  padding: 12px 0;
}

.log-line {
  display: flex;
  gap: 10px;
  padding: 1px 0;
}

.log-time {
  color: var(--text-muted);
  flex-shrink: 0;
  min-width: 70px;
}

.log-msg {
  color: var(--text-secondary);
}

.log-line.info .log-msg {
  color: var(--text-secondary);
}

.log-line.success .log-msg {
  color: var(--accent-green);
}

.log-line.warning .log-msg {
  color: var(--accent-orange);
}

.log-line.error .log-msg {
  color: var(--accent-red);
}
</style>
