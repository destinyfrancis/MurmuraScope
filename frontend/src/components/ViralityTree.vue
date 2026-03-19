<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { getViralPosts } from '@/api/simulation'

const props = defineProps({
  sessionId: { type: String, required: true },
  refreshInterval: { type: Number, default: 30000 },
})

const viralPosts = ref([])
const loading = ref(false)
const error = ref(null)
const expandedPosts = ref(new Set())
let _timer = null

async function fetchData() {
  if (!props.sessionId) return
  loading.value = true
  error.value = null
  try {
    const res = await getViralPosts(props.sessionId)
    viralPosts.value = res.data?.data || []
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

function toggleExpand(postId) {
  const next = new Set(expandedPosts.value)
  if (next.has(postId)) {
    next.delete(postId)
  } else {
    next.add(postId)
  }
  expandedPosts.value = next
}

function isExpanded(postId) {
  return expandedPosts.value.has(postId)
}

function formatIndex(val) {
  if (val == null) return '—'
  return val.toFixed(2)
}

function viralityLevel(index) {
  if (index >= 0.7) return { label: '爆發', cls: 'viral-high' }
  if (index >= 0.4) return { label: '擴散', cls: 'viral-medium' }
  return { label: '局部', cls: 'viral-low' }
}

const topPosts = computed(() =>
  [...viralPosts.value]
    .sort((a, b) => (b.virality_index || 0) - (a.virality_index || 0))
    .slice(0, 20)
)

onMounted(() => {
  fetchData()
  startAutoRefresh()
})

watch(() => props.sessionId, () => {
  fetchData()
  startAutoRefresh()
})

onUnmounted(() => {
  stopAutoRefresh()
})
</script>

<template>
  <div class="virality-tree">
    <div class="vt-header">
      <h3 class="vt-title">病毒式傳播追蹤</h3>
      <span class="vt-count" v-if="viralPosts.length">
        {{ viralPosts.length }} 個病毒帖
      </span>
    </div>

    <div v-if="loading && viralPosts.length === 0" class="state-msg">
      <span class="spinner" /> 載入中...
    </div>
    <div v-else-if="error" class="state-msg state-error">{{ error }}</div>
    <div v-else-if="topPosts.length === 0" class="state-msg">
      尚無病毒式傳播數據
    </div>

    <div v-else class="vt-list">
      <div
        v-for="post in topPosts"
        :key="post.post_id || post.action_id"
        class="vt-card"
        :class="{ expanded: isExpanded(post.post_id || post.action_id) }"
      >
        <button
          class="vt-card-header"
          @click="toggleExpand(post.post_id || post.action_id)"
        >
          <div class="vt-index-badge" :class="viralityLevel(post.virality_index || 0).cls">
            {{ formatIndex(post.virality_index) }}
          </div>
          <div class="vt-card-info">
            <span class="vt-card-content">
              {{ (post.content || '').slice(0, 80) || `Post #${post.post_id}` }}
            </span>
            <span class="vt-card-level" :class="viralityLevel(post.virality_index || 0).cls">
              {{ viralityLevel(post.virality_index || 0).label }}
            </span>
          </div>
          <span class="vt-toggle">{{ isExpanded(post.post_id || post.action_id) ? '▾' : '▸' }}</span>
        </button>

        <div v-if="isExpanded(post.post_id || post.action_id)" class="vt-details">
          <div class="metric-row">
            <div class="metric-item">
              <span class="metric-label">R0（再生數）</span>
              <span class="metric-value">{{ formatIndex(post.r0) }}</span>
            </div>
            <div class="metric-item">
              <span class="metric-label">傳播深度</span>
              <span class="metric-value">{{ post.depth ?? '—' }}</span>
            </div>
            <div class="metric-item">
              <span class="metric-label">傳播廣度</span>
              <span class="metric-value">{{ post.breadth ?? '—' }}</span>
            </div>
          </div>
          <div class="metric-row">
            <div class="metric-item">
              <span class="metric-label">傳播速度</span>
              <span class="metric-value">{{ formatIndex(post.velocity) }}</span>
            </div>
            <div class="metric-item">
              <span class="metric-label">跨群觸及</span>
              <span class="metric-value">{{ formatIndex(post.cross_cluster_reach) }}</span>
            </div>
            <div class="metric-item">
              <span class="metric-label">來源 Agent</span>
              <span class="metric-value">{{ post.agent_id ?? post.username ?? '—' }}</span>
            </div>
          </div>

          <!-- Cascade tree preview -->
          <div v-if="post.cascade?.length" class="cascade-section">
            <div class="cascade-label">傳播路徑</div>
            <div class="cascade-tree">
              <div
                v-for="(node, ni) in post.cascade.slice(0, 10)"
                :key="ni"
                class="cascade-node"
                :style="{ marginLeft: (node.depth || 0) * 20 + 'px' }"
              >
                <span class="cascade-dot" />
                <span class="cascade-agent">{{ node.username || `Agent #${node.agent_id}` }}</span>
                <span v-if="node.sentiment != null" class="cascade-sent" :class="node.sentiment > 0 ? 'sent-pos' : 'sent-neg'">
                  {{ node.sentiment > 0 ? '+' : '' }}{{ (node.sentiment * 100).toFixed(0) }}%
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.virality-tree {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 16px;
  box-shadow: var(--shadow-card);
}

.vt-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.vt-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.vt-count {
  font-size: 11px;
  color: var(--text-muted);
  background: var(--bg-secondary);
  padding: 2px 10px;
  border-radius: 12px;
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

.vt-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 400px;
  overflow-y: auto;
}

.vt-card {
  border: 1px solid var(--border-color);
  border-radius: 8px;
  overflow: hidden;
  transition: border-color 0.2s;
}

.vt-card.expanded { border-color: var(--accent-blue); }

.vt-card-header {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: none;
  border: none;
  cursor: pointer;
  text-align: left;
}

.vt-card-header:hover { background: var(--bg-secondary); }

.vt-index-badge {
  min-width: 44px;
  text-align: center;
  font-size: 13px;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 6px;
}

.viral-high { background: #FEE2E2; color: #DC2626; }
.viral-medium { background: #FEF9C3; color: #D97706; }
.viral-low { background: #D1FAE5; color: #059669; }

.vt-card-info { flex: 1; min-width: 0; }

.vt-card-content {
  font-size: 12px;
  color: var(--text-secondary);
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.vt-card-level {
  font-size: 10px;
  font-weight: 600;
}

.vt-toggle {
  font-size: 14px;
  color: var(--text-muted);
  flex-shrink: 0;
}

.vt-details {
  padding: 12px;
  border-top: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.metric-row {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 8px;
}

.metric-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.metric-label {
  font-size: 10px;
  color: var(--text-muted);
}

.metric-value {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.cascade-section { margin-top: 4px; }

.cascade-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  margin-bottom: 6px;
}

.cascade-tree {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.cascade-node {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
}

.cascade-dot {
  width: 6px;
  height: 6px;
  background: var(--accent-blue);
  border-radius: 50%;
  flex-shrink: 0;
}

.cascade-agent { color: var(--text-secondary); }

.cascade-sent { font-size: 10px; font-weight: 600; }
.sent-pos { color: #059669; }
.sent-neg { color: #DC2626; }
</style>
