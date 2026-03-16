<script setup>
import { ref } from 'vue'

const props = defineProps({
  sessionId: { type: String, default: null },
  agentId: { type: Number, default: null },
})

const relationships = ref([])
const loading = ref(false)

async function loadRelationships() {
  if (!props.sessionId || !props.agentId) return
  loading.value = true
  try {
    const { default: axios } = await import('axios')
    const base = import.meta.env.VITE_API_BASE || '/api'
    const res = await axios.get(`${base}/simulation/${props.sessionId}/agents/${props.agentId}/relationships`)
    relationships.value = res.data?.data || res.data || []
  } catch (e) {
    // Endpoint may not exist yet -- graceful fallback
    console.error('Failed to load relationships', e)
    relationships.value = []
  } finally {
    loading.value = false
  }
}

function reset() {
  relationships.value = []
}

function trustColor(score) {
  if (score >= 0.6) return '#4caf7d'
  if (score >= 0.3) return '#f0a030'
  return '#e05252'
}

defineExpose({ loadRelationships, reset })
</script>

<template>
  <div class="tab-content">
    <div v-if="loading" class="loading-hint">載入關係中...</div>
    <div v-else-if="relationships.length === 0" class="empty-hint">尚無信任關係數據</div>
    <div v-else class="relationship-list">
      <div
        v-for="rel in relationships"
        :key="`${rel.agent_a_id}-${rel.agent_b_id}`"
        class="rel-card"
      >
        <div class="rel-header">
          <span class="rel-name">{{ rel.agent_b_username || `Agent #${rel.agent_b_id}` }}</span>
          <span
            class="rel-trust"
            :style="{ color: trustColor(rel.trust_score || 0) }"
          >
            信任度 {{ Math.round((rel.trust_score || 0) * 100) }}%
          </span>
        </div>
        <div class="trust-bar-bg">
          <div
            class="trust-bar-fill"
            :style="{
              width: Math.round(Math.abs(rel.trust_score || 0) * 100) + '%',
              background: trustColor(rel.trust_score || 0),
            }"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tab-content {
  overflow-y: auto;
  flex: 1;
  padding: 12px 14px;
}

.relationship-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.rel-card {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 10px 12px;
}

.rel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.rel-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
}

.rel-trust {
  font-size: 11px;
  font-weight: 600;
}

.trust-bar-bg {
  height: 4px;
  background: var(--bg-secondary);
  border-radius: 2px;
  overflow: hidden;
}

.trust-bar-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.4s ease;
}

.loading-hint, .empty-hint {
  text-align: center;
  color: var(--text-muted);
  font-size: 13px;
  padding: 20px 0;
}
</style>
