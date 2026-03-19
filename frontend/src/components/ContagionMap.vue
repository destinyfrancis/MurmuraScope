<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { getEmotionalContagionMap } from '@/api/simulation'

const props = defineProps({
  sessionId: { type: String, required: true },
  visible: { type: Boolean, default: true },
  refreshInterval: { type: Number, default: 30000 },
})

const contagionData = ref(null)
const loading = ref(false)
const error = ref(null)
let _timer = null

async function fetchData() {
  if (!props.sessionId) return
  loading.value = true
  error.value = null
  try {
    const res = await getEmotionalContagionMap(props.sessionId)
    contagionData.value = res.data?.data || null
  } catch (err) {
    error.value = `載入失敗：${err.message || '未知錯誤'}`
  } finally {
    loading.value = false
  }
}

function startAutoRefresh() {
  stopAutoRefresh()
  if (props.refreshInterval > 0) {
    _timer = setInterval(fetchData, props.refreshInterval)
  }
}

function stopAutoRefresh() {
  if (_timer) { clearInterval(_timer); _timer = null }
}

const spreaders = computed(() => {
  if (!contagionData.value?.spreaders) return []
  return contagionData.value.spreaders.slice(0, 30)
})

const connections = computed(() => {
  if (!contagionData.value?.connections) return []
  return contagionData.value.connections.slice(0, 50)
})

const totalSpreaders = computed(() => spreaders.value.length)

const avgArousal = computed(() => {
  if (spreaders.value.length === 0) return 0
  const sum = spreaders.value.reduce((acc, s) => acc + (s.arousal || 0), 0)
  return sum / spreaders.value.length
})

function valenceColor(valence) {
  if (valence > 0.2) return '#22c55e'
  if (valence < -0.2) return '#ef4444'
  return '#6b7280'
}

function arousalOpacity(arousal) {
  return 0.3 + (arousal || 0) * 0.7
}

function formatVal(v) {
  if (v == null) return '—'
  return v.toFixed(2)
}

onMounted(() => {
  if (props.visible) {
    fetchData()
    startAutoRefresh()
  }
})

watch(() => props.visible, (visible) => {
  if (visible) {
    fetchData()
    startAutoRefresh()
  } else {
    stopAutoRefresh()
  }
})

watch(() => props.sessionId, () => {
  if (props.visible) {
    fetchData()
    startAutoRefresh()
  }
})

onUnmounted(() => {
  stopAutoRefresh()
})
</script>

<template>
  <div v-if="visible" class="contagion-map">
    <div class="cm-header">
      <h3 class="cm-title">情緒傳染地圖</h3>
      <button class="cm-close" @click="$emit('toggle')" title="關閉">✕</button>
    </div>

    <div v-if="loading && !contagionData" class="state-msg">
      <span class="spinner" /> 載入中...
    </div>
    <div v-else-if="error" class="state-msg state-error">{{ error }}</div>
    <div v-else-if="!contagionData || spreaders.length === 0" class="state-msg">
      尚無情緒傳染數據
    </div>

    <template v-else>
      <!-- Summary -->
      <div class="cm-summary">
        <div class="cm-stat">
          <span class="cm-stat-label">傳播源</span>
          <span class="cm-stat-value">{{ totalSpreaders }}</span>
        </div>
        <div class="cm-stat">
          <span class="cm-stat-label">平均激發度</span>
          <span class="cm-stat-value" :class="avgArousal > 0.7 ? 'val-warn' : ''">
            {{ avgArousal.toFixed(2) }}
          </span>
        </div>
        <div class="cm-stat">
          <span class="cm-stat-label">傳染連結</span>
          <span class="cm-stat-value">{{ connections.length }}</span>
        </div>
      </div>

      <!-- Spreader list (network diagram substitute) -->
      <div class="spreader-list">
        <div
          v-for="spreader in spreaders"
          :key="spreader.agent_id"
          class="spreader-card"
        >
          <div class="spreader-node" :style="{
            background: valenceColor(spreader.valence),
            opacity: arousalOpacity(spreader.arousal),
          }" />
          <div class="spreader-info">
            <div class="spreader-name">{{ spreader.username || `Agent #${spreader.agent_id}` }}</div>
            <div class="spreader-metrics">
              <span title="效價">V: {{ formatVal(spreader.valence) }}</span>
              <span title="激發度">A: {{ formatVal(spreader.arousal) }}</span>
            </div>
          </div>
          <!-- Targets -->
          <div class="target-dots">
            <div
              v-for="(target, ti) in (spreader.targets || []).slice(0, 5)"
              :key="ti"
              class="target-dot"
              :style="{ background: valenceColor(target.valence_change || 0) }"
              :title="`→ ${target.username || 'Agent #' + target.agent_id} (${formatVal(target.valence_change)})`"
            />
            <span v-if="(spreader.targets || []).length > 5" class="target-more">
              +{{ (spreader.targets || []).length - 5 }}
            </span>
          </div>
        </div>
      </div>

      <!-- Connection list -->
      <div v-if="connections.length > 0" class="connection-section">
        <div class="section-label">傳染路徑</div>
        <div class="connection-list">
          <div
            v-for="(conn, ci) in connections.slice(0, 20)"
            :key="ci"
            class="connection-row"
          >
            <span class="conn-from" :style="{ color: valenceColor(conn.from_valence || 0) }">
              {{ conn.from_username || `#${conn.from_id}` }}
            </span>
            <span class="conn-arrow">→</span>
            <span class="conn-to">
              {{ conn.to_username || `#${conn.to_id}` }}
            </span>
            <span class="conn-strength" :title="'信任: ' + formatVal(conn.trust_score)">
              {{ formatVal(conn.trust_score) }}
            </span>
          </div>
        </div>
      </div>

      <!-- Legend -->
      <div class="cm-legend">
        <span class="legend-item">
          <span class="legend-dot" style="background: #22c55e" /> 正面
        </span>
        <span class="legend-item">
          <span class="legend-dot" style="background: #6b7280" /> 中性
        </span>
        <span class="legend-item">
          <span class="legend-dot" style="background: #ef4444" /> 負面
        </span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.contagion-map {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 16px;
  box-shadow: var(--shadow-card);
  position: absolute;
  top: 10px;
  right: 10px;
  width: 320px;
  max-height: 500px;
  overflow-y: auto;
  z-index: 20;
}

.cm-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.cm-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.cm-close {
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 14px;
  padding: 2px 6px;
}

.cm-close:hover { color: var(--text-primary); }

.state-msg {
  text-align: center;
  padding: 20px;
  color: var(--text-muted);
  font-size: 12px;
}

.state-error { color: var(--accent-red); }

.spinner {
  display: inline-block;
  width: 12px;
  height: 12px;
  border: 2px solid var(--accent-blue);
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
  margin-right: 6px;
  vertical-align: middle;
}

@keyframes spin { to { transform: rotate(360deg); } }

.cm-summary {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
}

.cm-stat {
  flex: 1;
  text-align: center;
  background: var(--bg-secondary);
  padding: 6px;
  border-radius: 6px;
}

.cm-stat-label { font-size: 9px; color: var(--text-muted); display: block; }
.cm-stat-value { font-size: 14px; font-weight: 700; color: var(--text-primary); }
.val-warn { color: #f59e0b; }

.spreader-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 10px;
}

.spreader-card {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  transition: background 0.15s;
}

.spreader-card:hover { background: var(--bg-secondary); }

.spreader-node {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  flex-shrink: 0;
}

.spreader-info { flex: 1; min-width: 0; }

.spreader-name {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.spreader-metrics {
  font-size: 9px;
  color: var(--text-muted);
  display: flex;
  gap: 6px;
}

.target-dots {
  display: flex;
  gap: 2px;
  align-items: center;
}

.target-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  cursor: help;
}

.target-more {
  font-size: 9px;
  color: var(--text-muted);
  margin-left: 2px;
}

.section-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  margin-bottom: 6px;
}

.connection-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.connection-row {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  padding: 3px 0;
}

.conn-from { font-weight: 600; }
.conn-arrow { color: var(--text-muted); }
.conn-to { color: var(--text-secondary); }
.conn-strength {
  margin-left: auto;
  font-size: 9px;
  color: var(--text-muted);
}

.cm-legend {
  display: flex;
  gap: 10px;
  justify-content: center;
  margin-top: 10px;
  font-size: 10px;
  color: var(--text-muted);
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 3px;
}

.legend-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}
</style>
