<script setup>
import { ref, computed, watch } from 'vue'
import { getEchoChambers } from '../api/simulation.js'
import { FACTION_PALETTE } from '../utils/colours.js'

const props = defineProps({
  sessionId: { type: String, default: '' },
  posts: { type: Array, default: () => [] },
})

const echoData = ref([])

async function loadFactions() {
  if (!props.sessionId) return
  const capturedId = props.sessionId
  try {
    const res = await getEchoChambers(props.sessionId)
    if (props.sessionId !== capturedId) return
    const data = res.data?.data || res.data || []
    echoData.value = (Array.isArray(data) ? data : data.communities || []).slice(0, 4)
  } catch (err) {
    console.warn('[FactionColumns] Failed to load echo chamber data:', err)
    echoData.value = []
  }
}

watch(() => props.sessionId, (id) => { if (id) loadFactions() }, { immediate: true })

// Map posts to faction (by agent_id matching member_agent_ids)
const factionPosts = computed(() => {
  const map = {}
  for (const faction of echoData.value) {
    const ids = new Set((faction.member_agent_ids || []).map(String))
    map[faction.id ?? faction.cluster_id] = props.posts.filter(p =>
      ids.has(String(p.agent_id))
    )
  }
  const allInFaction = new Set(echoData.value.flatMap(f => (f.member_agent_ids || []).map(String)))
  map['__other__'] = props.posts.filter(p => !allInFaction.has(String(p.agent_id)))
  return map
})

const columns = computed(() => {
  const cols = echoData.value.map((f, idx) => ({
    id: f.id ?? f.cluster_id,
    name: f.name || f.label || `陣營 ${f.id ?? f.cluster_id}`,
    count: (f.member_agent_ids || []).length,
    sentiment: f.sentiment_breakdown || null,
    posts: factionPosts.value[f.id ?? f.cluster_id] || [],
    colour: FACTION_PALETTE[idx % FACTION_PALETTE.length],
  }))
  const other = factionPosts.value['__other__'] || []
  if (other.length > 0) {
    cols.push({ id: '__other__', name: '其他', count: 0, sentiment: null, posts: other, colour: '#94a3b8' })
  }
  return cols
})

function sentimentBar(s) {
  if (!s) return { oppose: 33, neutral: 34, support: 33 }
  return {
    oppose: s.oppose_pct ?? s.negative_pct ?? 33,
    neutral: s.neutral_pct ?? 34,
    support: s.support_pct ?? s.positive_pct ?? 33,
  }
}
</script>

<template>
  <div class="faction-columns">
    <div v-if="columns.length === 0" class="empty-state">
      陣營數據載入中... 模擬完成後可見完整分欄
    </div>

    <div
      v-for="col in columns"
      :key="col.id"
      class="faction-col"
    >
      <div class="col-header" :style="{ borderTopColor: col.colour }">
        <span class="col-name" :style="{ color: col.colour }">{{ col.name }}</span>
        <span class="col-count">{{ col.count }} 人</span>
        <div class="col-sentiment">
          <div class="seg oppose" :style="{ flex: sentimentBar(col.sentiment).oppose }" />
          <div class="seg neutral" :style="{ flex: sentimentBar(col.sentiment).neutral }" />
          <div class="seg support" :style="{ flex: sentimentBar(col.sentiment).support }" />
        </div>
      </div>

      <div class="col-posts">
        <div
          v-for="post in col.posts.slice(0, 20)"
          :key="post.id"
          class="faction-post"
        >
          <span class="post-author">{{ post.oasis_username || post.agent_name || '代理人' }}</span>
          <span class="post-content">{{ (post.content || '').slice(0, 60) }}</span>
        </div>
        <div v-if="col.posts.length === 0" class="col-empty">暫無貼文</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.faction-columns {
  display: flex;
  gap: 8px;
  height: 100%;
  overflow-x: auto;
}

.empty-state {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #64748b;
  font-size: 13px;
}

.faction-col {
  flex: 1;
  min-width: 160px;
  max-width: 280px;
  background: var(--bg-card, #1e293b);
  border-radius: 8px;
  border-top: 3px solid #64748b;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.col-header {
  padding: 8px 10px 6px;
  border-top-width: 3px;
  border-top-style: solid;
  flex-shrink: 0;
}

.col-name {
  font-size: 11px;
  font-weight: 700;
  display: block;
}

.col-count {
  font-size: 10px;
  color: #94a3b8;
}

.col-sentiment {
  display: flex;
  height: 6px;
  border-radius: 2px;
  overflow: hidden;
  margin-top: 4px;
  gap: 1px;
}

.seg.oppose { background: #ef4444; }
.seg.neutral { background: #64748b; }
.seg.support { background: #3b82f6; }

.col-posts {
  flex: 1;
  overflow-y: auto;
  padding: 6px 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.faction-post {
  background: var(--bg-app, #0f172a);
  border-radius: 4px;
  padding: 5px 7px;
  font-size: 10px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.post-author {
  font-weight: 600;
  color: #94a3b8;
}

.post-content {
  color: #cbd5e1;
  line-height: 1.4;
}

.col-empty {
  font-size: 11px;
  color: #475569;
  text-align: center;
  margin-top: 8px;
}
</style>
