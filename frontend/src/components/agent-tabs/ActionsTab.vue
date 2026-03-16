<script setup>
import { ref } from 'vue'
import { getSessionActions } from '../../api/simulation.js'

const props = defineProps({
  sessionId: { type: String, default: null },
  agentProfile: { type: Object, default: null },
})

const actions = ref([])
const loadingActions = ref(false)

function sentimentClass(sentiment) {
  return {
    positive: 'sent-pos',
    negative: 'sent-neg',
    neutral: 'sent-neu',
  }[sentiment] || 'sent-neu'
}

async function loadActions() {
  if (!props.sessionId || !props.agentProfile) return
  loadingActions.value = true
  try {
    const username = props.agentProfile.oasis_username
    const res = await getSessionActions(props.sessionId, { limit: 100 })
    const all = res.data?.data || []
    actions.value = all.filter(a => a.oasis_username === username)
  } catch (e) {
    console.error('Failed to load actions', e)
  } finally {
    loadingActions.value = false
  }
}

function reset() {
  actions.value = []
}

defineExpose({ loadActions, reset })
</script>

<template>
  <div class="tab-content">
    <div v-if="loadingActions" class="loading-hint">載入帖子中...</div>
    <div v-else-if="actions.length === 0" class="empty-hint">尚無帖子記錄</div>
    <div v-else class="action-list">
      <div
        v-for="a in actions"
        :key="a.id"
        class="action-card"
      >
        <div class="action-meta">
          <span class="action-round">輪 {{ a.round_number }}</span>
          <span class="action-platform">{{ a.platform }}</span>
          <span class="action-sentiment" :class="sentimentClass(a.sentiment)">
            {{ a.sentiment }}
          </span>
        </div>
        <p class="action-content">{{ a.content }}</p>
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

.action-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.action-card {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 10px 12px;
}

.action-meta {
  display: flex;
  gap: 8px;
  margin-bottom: 6px;
  font-size: 11px;
}

.action-round { color: var(--text-muted); }

.action-platform {
  background: var(--bg-card);
  padding: 1px 6px;
  border-radius: 8px;
  color: var(--text-secondary);
}

.action-sentiment {
  font-weight: 600;
  margin-left: auto;
}

.sent-pos { color: #4caf7d; }
.sent-neg { color: #e05252; }
.sent-neu { color: var(--text-muted); }

.action-content {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.6;
}

.loading-hint, .empty-hint {
  text-align: center;
  color: var(--text-muted);
  font-size: 13px;
  padding: 20px 0;
}
</style>
