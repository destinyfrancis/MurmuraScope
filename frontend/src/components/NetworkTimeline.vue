<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { getNetworkEvents } from '@/api/simulation'

const props = defineProps({
  sessionId: { type: String, required: true },
  currentRound: { type: Number, default: null },
  refreshInterval: { type: Number, default: 30000 },
})

const events = ref([])
const loading = ref(false)
const error = ref(null)
const selectedType = ref(null)
const selectedRound = ref(null)
let _timer = null

const EVENT_TYPES = [
  { key: 'TIE_FORMED', label: '連結形成', color: '#22c55e', icon: '+' },
  { key: 'TIE_DISSOLVED', label: '連結斷裂', color: '#ef4444', icon: '−' },
  { key: 'BRIDGE_DETECTED', label: '橋接發現', color: '#3b82f6', icon: '⬡' },
  { key: 'TRIADIC_CLOSURE', label: '三角閉合', color: '#a855f7', icon: '△' },
  { key: 'CLUSTER_SHIFT', label: '群組遷移', color: '#f59e0b', icon: '↻' },
]

const EVENT_MAP = Object.fromEntries(EVENT_TYPES.map(e => [e.key, e]))

const filteredEvents = computed(() => {
  let result = events.value
  if (selectedType.value) {
    result = result.filter(e => e.event_type === selectedType.value)
  }
  if (selectedRound.value != null) {
    result = result.filter(e => e.round_number === selectedRound.value)
  }
  return result
})

const eventCounts = computed(() => {
  const counts = {}
  for (const t of EVENT_TYPES) counts[t.key] = 0
  for (const e of events.value) {
    if (counts[e.event_type] != null) counts[e.event_type]++
  }
  return counts
})

const rounds = computed(() => {
  const set = new Set(events.value.map(e => e.round_number))
  return [...set].sort((a, b) => a - b)
})

function toggleType(key) {
  selectedType.value = selectedType.value === key ? null : key
}

function selectRound(round) {
  selectedRound.value = selectedRound.value === round ? null : round
}

function eventMeta(type) {
  return EVENT_MAP[type] || { label: type, color: '#6b7280', icon: '?' }
}

async function fetchEvents() {
  if (!props.sessionId) return
  loading.value = true
  error.value = null
  try {
    const params = {}
    if (selectedRound.value != null) params.round_number = selectedRound.value
    if (selectedType.value) params.event_type = selectedType.value
    params.limit = 200
    const res = await getNetworkEvents(props.sessionId, params)
    events.value = res.data?.data || []
  } catch (err) {
    error.value = `載入失敗：${err.message || '未知錯誤'}`
  } finally {
    loading.value = false
  }
}

function startAutoRefresh() {
  stopAutoRefresh()
  if (props.refreshInterval > 0) {
    _timer = setInterval(fetchEvents, props.refreshInterval)
  }
}

function stopAutoRefresh() {
  if (_timer) { clearInterval(_timer); _timer = null }
}

onMounted(() => {
  fetchEvents()
  startAutoRefresh()
})

watch(() => props.sessionId, () => {
  fetchEvents()
  startAutoRefresh()
})

watch(() => props.currentRound, (r) => {
  if (r != null) fetchEvents()
})
</script>

<template>
  <div class="net-timeline">
    <div class="timeline-header">
      <h3 class="timeline-title">網絡演化時間線</h3>
      <span class="event-total" v-if="events.length">
        共 {{ events.length }} 個事件
      </span>
    </div>

    <!-- Type filter badges -->
    <div class="type-filters">
      <button
        v-for="t in EVENT_TYPES"
        :key="t.key"
        class="type-badge"
        :class="{ active: selectedType === t.key }"
        :style="{ '--badge-color': t.color }"
        @click="toggleType(t.key)"
      >
        <span class="badge-icon">{{ t.icon }}</span>
        <span class="badge-label">{{ t.label }}</span>
        <span class="badge-count">{{ eventCounts[t.key] }}</span>
      </button>
    </div>

    <!-- Round scrubber -->
    <div v-if="rounds.length > 0" class="round-bar">
      <button
        v-for="r in rounds"
        :key="r"
        class="round-chip"
        :class="{ active: selectedRound === r }"
        @click="selectRound(r)"
      >
        R{{ r }}
      </button>
    </div>

    <!-- Loading / Error / Empty -->
    <div v-if="loading && events.length === 0" class="state-msg">
      <span class="spinner" /> 載入中...
    </div>
    <div v-else-if="error" class="state-msg state-error">{{ error }}</div>
    <div v-else-if="filteredEvents.length === 0" class="state-msg">
      尚無網絡演化事件
    </div>

    <!-- Event list -->
    <div v-else class="event-list">
      <div
        v-for="(ev, idx) in filteredEvents.slice(0, 100)"
        :key="idx"
        class="event-row"
      >
        <div
          class="event-dot"
          :style="{ background: eventMeta(ev.event_type).color }"
        />
        <div class="event-body">
          <div class="event-top">
            <span class="event-type-label" :style="{ color: eventMeta(ev.event_type).color }">
              {{ eventMeta(ev.event_type).icon }} {{ eventMeta(ev.event_type).label }}
            </span>
            <span class="event-round">第 {{ ev.round_number }} 輪</span>
          </div>
          <div v-if="ev.agent_a_id || ev.agent_b_id" class="event-agents">
            <span v-if="ev.agent_a_id">Agent #{{ ev.agent_a_id }}</span>
            <span v-if="ev.agent_a_id && ev.agent_b_id"> → </span>
            <span v-if="ev.agent_b_id">Agent #{{ ev.agent_b_id }}</span>
          </div>
          <div v-if="ev.detail" class="event-detail">{{ ev.detail }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.net-timeline {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 16px;
  box-shadow: var(--shadow-card);
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;
  overflow: hidden;
}

.timeline-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.timeline-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.event-total {
  font-size: 11px;
  color: var(--text-muted);
  background: var(--bg-secondary);
  padding: 2px 10px;
  border-radius: 12px;
}

.type-filters {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.type-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border: 1px solid var(--border-color);
  border-radius: 999px;
  background: var(--bg-secondary);
  color: var(--text-muted);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s;
}

.type-badge.active {
  border-color: var(--badge-color);
  color: var(--badge-color);
  background: color-mix(in srgb, var(--badge-color) 10%, transparent);
}

.badge-icon { font-size: 12px; font-weight: 700; }
.badge-count {
  background: var(--bg-card);
  padding: 0 5px;
  border-radius: 8px;
  font-size: 10px;
  font-weight: 600;
}

.round-bar {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.round-chip {
  padding: 2px 8px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-primary);
  color: var(--text-muted);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s;
}

.round-chip.active {
  background: var(--accent-blue);
  border-color: var(--accent-blue);
  color: #fff;
}

.state-msg {
  text-align: center;
  padding: 24px;
  color: var(--text-muted);
  font-size: 13px;
}

.state-error { color: var(--accent-red); }

.spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid var(--accent-blue);
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
  margin-right: 6px;
  vertical-align: middle;
}

@keyframes spin { to { transform: rotate(360deg); } }

.event-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.event-row {
  display: flex;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 6px;
  transition: background 0.15s;
}

.event-row:hover { background: var(--bg-secondary); }

.event-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-top: 5px;
  flex-shrink: 0;
}

.event-body { flex: 1; min-width: 0; }

.event-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.event-type-label {
  font-size: 12px;
  font-weight: 600;
}

.event-round {
  font-size: 10px;
  color: var(--text-muted);
}

.event-agents {
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 2px;
}

.event-detail {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
}
</style>
