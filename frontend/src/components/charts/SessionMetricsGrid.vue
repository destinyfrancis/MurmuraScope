<script setup>
import { computed } from 'vue'

const props = defineProps({
  compData: { type: Object, required: true },
})

const metricDiffs = computed(() => {
  const a = props.compData.session_a
  const b = props.compData.session_b
  return [
    { label: '代理人數量', a: a.agent_count, b: b.agent_count },
    { label: '模擬輪次', a: a.round_count, b: b.round_count },
    { label: '情景類型', a: a.scenario_type || '?', b: b.scenario_type || '?' },
    { label: '狀態', a: a.status || '?', b: b.status || '?' },
  ]
})

const memDivergence = computed(() => ({
  a: props.compData.session_a.memory_divergence,
  b: props.compData.session_b.memory_divergence,
}))

const keyEventsA = computed(() => props.compData.session_a?.key_events || [])
const keyEventsB = computed(() => props.compData.session_b?.key_events || [])

function sentimentColor(s) {
  if (s === 'positive') return '#34d399'
  if (s === 'negative') return '#f87171'
  return '#94a3b8'
}
</script>

<template>
  <div class="session-metrics-grid">
    <!-- Key metrics diff -->
    <div class="section-title">關鍵指標對比</div>
    <div class="metrics-table">
      <div class="metrics-header">
        <span class="m-label">指標</span>
        <span class="m-val">情景 A</span>
        <span class="m-val">情景 B</span>
        <span class="m-diff">差異</span>
      </div>
      <div v-for="m in metricDiffs" :key="m.label" class="metrics-row">
        <span class="m-label">{{ m.label }}</span>
        <span class="m-val">{{ m.a }}</span>
        <span class="m-val">{{ m.b }}</span>
        <span class="m-diff" :class="typeof m.a === 'number' && m.b > m.a ? 'up' : typeof m.a === 'number' && m.b < m.a ? 'down' : ''">
          <template v-if="typeof m.a === 'number' && typeof m.b === 'number'">
            {{ m.b - m.a > 0 ? '+' : '' }}{{ m.b - m.a }}
          </template>
          <template v-else>—</template>
        </span>
      </div>
    </div>

    <!-- Memory divergence -->
    <template v-if="memDivergence.a || memDivergence.b">
      <div class="section-title">記憶差異分析</div>
      <div class="mem-div-grid">
        <div v-for="(md, idx) in [memDivergence.a, memDivergence.b]" :key="idx" class="mem-div-card">
          <div class="mem-div-title">情景 {{ idx === 0 ? 'A' : 'B' }}</div>
          <div class="mem-div-row">
            <span class="mem-div-label">總記憶數</span>
            <span class="mem-div-value">{{ md?.total_memories ?? 0 }}</span>
          </div>
          <div class="mem-div-row">
            <span class="mem-div-label">獨特主題數</span>
            <span class="mem-div-value">{{ md?.unique_themes ?? 0 }}</span>
          </div>
          <div v-if="md?.theme_breakdown" class="mem-themes">
            <span
              v-for="(cnt, theme) in md.theme_breakdown"
              :key="theme"
              class="mem-theme-tag"
            >{{ theme }} ({{ cnt }})</span>
          </div>
        </div>
      </div>
    </template>

    <!-- Key events side by side -->
    <div class="section-title">關鍵事件（各 Top 5）</div>
    <div class="events-grid">
      <div v-for="(events, label) in { '情景 A': keyEventsA, '情景 B': keyEventsB }" :key="label" class="events-col">
        <div class="events-col-title">{{ label }}</div>
        <div v-if="events.length === 0" class="no-data">暫無數據</div>
        <div v-for="(ev, i) in events" :key="i" class="event-card">
          <div class="event-meta">
            <span class="event-round">R{{ ev.round_number }}</span>
            <span class="event-username">{{ ev.oasis_username }}</span>
            <span
              class="event-sentiment"
              :style="{ color: sentimentColor(ev.sentiment), borderColor: sentimentColor(ev.sentiment) }"
            >{{ ev.sentiment === 'positive' ? '正面' : ev.sentiment === 'negative' ? '負面' : '中性' }}</span>
            <span class="event-platform">{{ ev.platform }}</span>
          </div>
          <p class="event-content">{{ ev.content?.slice(0, 140) }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 10px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border-color);
}

/* Metrics table */
.metrics-table {
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  overflow: hidden;
  font-size: 13px;
  margin-bottom: 20px;
}

.metrics-header,
.metrics-row {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr 80px;
  padding: 8px 14px;
}

.metrics-header {
  background: var(--bg-input);
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
}

.metrics-row {
  border-top: 1px solid var(--border-color);
}

.metrics-row:hover {
  background: var(--bg-input);
}

.m-label {
  color: var(--text-secondary);
}

.m-val {
  color: var(--text-primary);
  font-weight: 500;
}

.m-diff {
  text-align: right;
  font-weight: 600;
}

.m-diff.up { color: var(--accent-green, #34d399); }
.m-diff.down { color: var(--accent-red); }

/* Memory divergence */
.mem-div-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 20px;
}

.mem-div-card {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  padding: 12px 14px;
}

.mem-div-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.mem-div-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  padding: 3px 0;
  border-bottom: 1px solid var(--border-color);
}

.mem-div-label {
  color: var(--text-muted);
}

.mem-div-value {
  color: var(--text-primary);
  font-weight: 600;
}

.mem-themes {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.mem-theme-tag {
  padding: 2px 8px;
  background: var(--bg-input);
  border-radius: 10px;
  font-size: 10px;
  color: var(--text-muted);
}

/* Key events */
.events-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.events-col {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.events-col-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.event-card {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  padding: 10px 12px;
}

.event-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 5px;
}

.event-round {
  font-size: 10px;
  font-weight: 700;
  color: var(--accent-blue);
  background: rgba(74, 158, 255, 0.1);
  padding: 1px 6px;
  border-radius: 10px;
}

.event-username {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
}

.event-sentiment {
  font-size: 10px;
  border: 1px solid;
  padding: 1px 6px;
  border-radius: 10px;
}

.event-platform {
  font-size: 10px;
  color: var(--text-muted);
  margin-left: auto;
}

.event-content {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.5;
  margin: 0;
}

.no-data {
  font-size: 13px;
  color: var(--text-muted);
  text-align: center;
  padding: 20px;
}
</style>
