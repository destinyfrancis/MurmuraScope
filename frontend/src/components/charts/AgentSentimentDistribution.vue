<script setup>
const props = defineProps({
  compData: { type: Object, required: true },
})

function asdPercent(session, key) {
  const d = props.compData?.[session]?.agent_sentiment_distribution
  if (!d || !d.total) return 0
  return Math.round((d[key] / d.total) * 100)
}
</script>

<template>
  <div class="asd-grid">
    <div v-for="(sess, key) in { '情景 A': 'session_a', '情景 B': 'session_b' }" :key="key" class="asd-card">
      <div class="asd-label">{{ key }}</div>
      <div class="asd-bars">
        <div
          v-for="(col, skey) in { positive: '#34d399', negative: '#f87171', neutral: '#94a3b8' }"
          :key="skey"
          class="asd-bar-row"
        >
          <span class="asd-key">{{ skey === 'positive' ? '正面' : skey === 'negative' ? '負面' : '中性' }}</span>
          <div class="asd-track">
            <div
              class="asd-fill"
              :style="{ width: asdPercent(sess, skey) + '%', background: col }"
            />
          </div>
          <span class="asd-pct">{{ asdPercent(sess, skey) }}%</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.asd-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.asd-card {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  padding: 12px 14px;
}

.asd-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 10px;
}

.asd-bars {
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.asd-bar-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.asd-key {
  font-size: 11px;
  color: var(--text-muted);
  width: 36px;
  flex-shrink: 0;
}

.asd-track {
  flex: 1;
  height: 8px;
  background: var(--bg-input);
  border-radius: 4px;
  overflow: hidden;
}

.asd-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.4s ease;
  min-width: 2px;
}

.asd-pct {
  font-size: 11px;
  color: var(--text-muted);
  width: 32px;
  text-align: right;
  flex-shrink: 0;
}
</style>
