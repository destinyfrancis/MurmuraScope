<script setup>
import { ref, watch, onMounted } from 'vue'
import { getAgentFeed } from '@/api/simulation'

const props = defineProps({
  sessionId: { type: String, default: '' },
  agentId: { type: Number, default: null },
  post: { type: Object, default: null },
  factionColour: { type: String, default: '#9CA3AF' },
})

const feed = ref([])
const algorithm = ref('')
const loading = ref(false)
const error = ref(null)

const ALGO_LABELS = {
  chronological: '時序排列',
  engagement_first: '互動優先',
  echo_chamber: '同溫層優先',
}

async function fetchFeed() {
  if (!props.sessionId || !props.agentId) return
  loading.value = true
  error.value = null
  try {
    const res = await getAgentFeed(props.sessionId, props.agentId)
    const data = res.data?.data || res.data || {}
    feed.value = data.feed || data.posts || []
    algorithm.value = data.algorithm || ''
  } catch (err) {
    error.value = `載入失敗：${err.message || '未知錯誤'}`
  } finally {
    loading.value = false
  }
}

function formatScore(score) {
  if (score == null) return '—'
  return score.toFixed(3)
}

function sentimentClass(sentiment) {
  if (sentiment > 0.2) return 'sent-positive'
  if (sentiment < -0.2) return 'sent-negative'
  return 'sent-neutral'
}

onMounted(() => { if (!props.post) fetchFeed() })

watch([() => props.sessionId, () => props.agentId], () => { if (!props.post) fetchFeed() })
</script>

<template>
  <!-- Single post card mode (used by SimulationTabs feed) -->
  <div v-if="post" class="feed-item">
    <div class="feed-rank">#{{ post.rank || '—' }}</div>
    <div class="feed-body">
      <div class="feed-meta">
        <!-- Faction colour dot -->
        <span class="f-dot" :style="{ background: factionColour }" />
        <span class="feed-author">{{ post.username || `Agent #${post.agent_id}` }}</span>
        <!-- T1 badge — show when post has tier=1 or agent_tier=1 -->
        <span v-if="post.tier === 1 || post.agent_tier === 1" class="f-tier">T1</span>
        <span class="feed-round">R{{ post.round_number ?? post.round }}</span>
      </div>
      <p class="feed-content">{{ (post.content || '').slice(0, 200) }}</p>
      <div class="feed-scores">
        <span v-if="post.score != null" class="score-chip" title="排序分數">
          分數: {{ formatScore(post.score) }}
        </span>
        <span
          v-if="post.sentiment != null"
          class="score-chip"
          :class="sentimentClass(post.sentiment)"
          title="情緒"
        >
          {{ post.sentiment > 0 ? '+' : '' }}{{ (post.sentiment * 100).toFixed(0) }}%
        </span>
        <span v-if="post.engagement" class="score-chip" title="互動量">
          {{ post.engagement }} 互動
        </span>
      </div>
    </div>
  </div>

  <!-- Full feed list mode (used standalone with sessionId + agentId) -->
  <div v-else class="feed-view">
    <div class="feed-header">
      <h4 class="feed-title">推薦信息流</h4>
      <span v-if="algorithm" class="algo-badge">
        {{ ALGO_LABELS[algorithm] || algorithm }}
      </span>
    </div>

    <div v-if="loading" class="state-msg">
      <span class="spinner" /> 載入中...
    </div>
    <div v-else-if="error" class="state-msg state-error">{{ error }}</div>
    <div v-else-if="feed.length === 0" class="state-msg">
      暫無推薦內容
    </div>

    <div v-else class="feed-list">
      <div
        v-for="(item, idx) in feed"
        :key="item.post_id || idx"
        class="feed-item"
      >
        <div class="feed-rank">#{{ item.rank || idx + 1 }}</div>
        <div class="feed-body">
          <div class="feed-meta">
            <!-- Faction colour dot -->
            <span class="f-dot" :style="{ background: factionColour }" />
            <span class="feed-author">{{ item.username || `Agent #${item.agent_id}` }}</span>
            <!-- T1 badge — show when post has tier=1 or agent_tier=1 -->
            <span v-if="item.tier === 1 || item.agent_tier === 1" class="f-tier">T1</span>
            <span class="feed-round">R{{ item.round_number }}</span>
          </div>
          <p class="feed-content">{{ (item.content || '').slice(0, 200) }}</p>
          <div class="feed-scores">
            <span class="score-chip" title="排序分數">
              分數: {{ formatScore(item.score) }}
            </span>
            <span
              v-if="item.sentiment != null"
              class="score-chip"
              :class="sentimentClass(item.sentiment)"
              title="情緒"
            >
              {{ item.sentiment > 0 ? '+' : '' }}{{ (item.sentiment * 100).toFixed(0) }}%
            </span>
            <span v-if="item.engagement" class="score-chip" title="互動量">
              {{ item.engagement }} 互動
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.feed-view {
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  height: 100%;
  overflow: hidden;
}

.feed-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.feed-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.algo-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--accent-blue-light, rgba(37, 99, 235, 0.1));
  color: var(--accent);
  font-weight: 600;
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
  border: 2px solid var(--accent);
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
  margin-right: 6px;
  vertical-align: middle;
}

@keyframes spin { to { transform: rotate(360deg); } }

.feed-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.feed-item {
  display: flex;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  transition: border-color 0.15s;
}

.feed-item:hover {
  border-color: var(--accent);
}

.feed-rank {
  font-size: 13px;
  font-weight: 700;
  color: var(--accent);
  min-width: 28px;
  text-align: center;
  padding-top: 2px;
}

.feed-body {
  flex: 1;
  min-width: 0;
}

.feed-meta {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-bottom: 4px;
}

.feed-author {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
}

.feed-round {
  font-size: 10px;
  color: var(--text-muted);
  margin-left: auto;
}

.feed-content {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
  margin: 0 0 6px;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
}

.feed-scores {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.score-chip {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--bg-app);
  color: var(--text-muted);
}

.sent-positive { color: var(--accent); background: rgba(0, 217, 101, 0.12); }
.sent-negative { color: var(--accent-red); background: rgba(255, 68, 68, 0.12); }
.sent-neutral { color: var(--text-muted); }

.f-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; display: inline-block; }
.f-tier {
  font-family: var(--font-mono);
  font-size: 7px;
  padding: 1px 4px;
  background: var(--accent);
  color: #fff;
  border-radius: 2px;
  display: inline-block;
  vertical-align: middle;
}
</style>
