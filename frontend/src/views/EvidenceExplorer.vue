<template>
  <div class="evidence-explorer">
    <div class="explorer-header">
      <router-link :to="`/app`" class="back-btn">← 返回工作台</router-link>
      <h1>証據探索器</h1>
      <div class="session-info">Session: {{ sessionId }}</div>
    </div>

    <div class="search-bar">
      <input
        v-model="query"
        @input="debouncedSearch"
        placeholder="搜尋記憶、知識圖譜節點、社交動態..."
        class="search-input"
      />
      <span class="result-count" v-if="hasResults">
        {{ totalResults }} 項結果
      </span>
    </div>

    <div class="results-grid" v-if="hasResults">
      <!-- Agent Memories -->
      <div class="result-col">
        <h3>Agent 記憶 ({{ results.memories?.length || 0 }})</h3>
        <div
          v-for="mem in results.memories"
          :key="mem.id"
          class="result-card"
          @click="selectItem(mem, 'memory')"
        >
          <div class="card-agent">{{ mem.oasis_username || mem.agent_id }}</div>
          <div class="card-content">{{ mem.content }}</div>
          <div class="card-meta">
            <span class="salience">顯著度: {{ (mem.salience || 0).toFixed(2) }}</span>
            <span class="round">Round {{ mem.round_number }}</span>
          </div>
        </div>
      </div>

      <!-- Graph Nodes -->
      <div class="result-col">
        <h3>知識圖譜節點 ({{ results.graph_nodes?.length || 0 }})</h3>
        <div
          v-for="node in results.graph_nodes"
          :key="node.id"
          class="result-card"
          @click="selectItem(node, 'node')"
        >
          <div class="card-label">{{ node.label }}</div>
          <div class="card-type node-type">{{ node.entity_type }}</div>
          <div class="card-content">{{ node.description }}</div>
        </div>
      </div>

      <!-- Actions/Posts -->
      <div class="result-col">
        <h3>社交動態 ({{ results.actions?.length || 0 }})</h3>
        <div
          v-for="action in results.actions"
          :key="action.id"
          class="result-card"
          @click="selectItem(action, 'action')"
        >
          <div class="card-agent">{{ action.oasis_username || action.agent_id }}</div>
          <div class="card-content">{{ action.content }}</div>
          <div class="card-meta">
            <span :class="['sentiment', sentimentClass(action.sentiment_score)]">
              情感: {{ (action.sentiment_score || 0).toFixed(2) }}
            </span>
            <span class="round">Round {{ action.round_number }}</span>
          </div>
        </div>
      </div>
    </div>

    <div class="empty-state" v-else-if="query && !loading">
      <div class="empty-icon">🔍</div>
      <p>未找到與「{{ query }}」相關的結果</p>
    </div>

    <div class="empty-state" v-else-if="!query">
      <div class="empty-icon">💡</div>
      <p>輸入關鍵詞開始搜尋證據</p>
    </div>

    <!-- Detail Panel -->
    <div class="detail-panel" v-if="selected" @click.self="selected = null">
      <div class="detail-content">
        <button class="close-btn" @click="selected = null">✕</button>
        <h3>{{ selectedType === 'memory' ? '記憶詳情' : selectedType === 'node' ? '節點詳情' : '動態詳情' }}</h3>
        <pre class="detail-json">{{ JSON.stringify(selected, null, 2) }}</pre>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const sessionId = route.params.sessionId
const query = ref('')
const results = ref({ memories: [], graph_nodes: [], actions: [] })
const loading = ref(false)
const selected = ref(null)
const selectedType = ref(null)

const hasResults = computed(() => {
  return (results.value.memories?.length || 0) +
         (results.value.graph_nodes?.length || 0) +
         (results.value.actions?.length || 0) > 0
})

const totalResults = computed(() => {
  return (results.value.memories?.length || 0) +
         (results.value.graph_nodes?.length || 0) +
         (results.value.actions?.length || 0)
})

let debounceTimer = null
function debouncedSearch() {
  clearTimeout(debounceTimer)
  if (!query.value.trim()) {
    results.value = { memories: [], graph_nodes: [], actions: [] }
    return
  }
  debounceTimer = setTimeout(search, 350)
}

async function search() {
  if (!query.value.trim()) return
  loading.value = true
  try {
    const res = await fetch(`/api/simulation/${sessionId}/evidence-search?q=${encodeURIComponent(query.value)}&limit=20`)
    if (res.ok) results.value = await res.json()
  } catch (e) {
    console.error('Evidence search error:', e)
  } finally {
    loading.value = false
  }
}

function selectItem(item, type) {
  selected.value = item
  selectedType.value = type
}

function sentimentClass(score) {
  if (!score) return 'neutral'
  if (score > 0.2) return 'positive'
  if (score < -0.2) return 'negative'
  return 'neutral'
}
</script>

<style scoped>
.evidence-explorer {
  min-height: 100vh;
  background: var(--bg-primary);
  color: var(--text-primary);
  padding: 24px;
}
.explorer-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 24px;
}
.back-btn {
  color: var(--accent-blue);
  text-decoration: none;
  font-size: 0.9em;
}
.back-btn:hover { text-decoration: underline; }
h1 { font-size: 1.5em; margin: 0; color: var(--text-primary); }
.session-info { color: var(--text-muted); font-size: 0.8em; margin-left: auto; }
.search-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 24px;
}
.search-input {
  flex: 1;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  color: var(--text-primary);
  padding: 12px 16px;
  border-radius: 8px;
  font-size: 1em;
  outline: none;
}
.search-input:focus { border-color: var(--accent-blue); }
.result-count { color: var(--accent-blue); font-size: 0.9em; white-space: nowrap; }
.results-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}
.result-col h3 { margin: 0 0 12px; font-size: 0.95em; color: var(--accent-blue); }
.result-card {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: border-color 0.2s, transform 0.2s, box-shadow 0.2s;
}
.result-card:hover { border-color: var(--accent-blue); transform: translateY(-2px); box-shadow: var(--shadow-glow-cyan); }
.card-agent { font-size: 0.8em; color: var(--accent-blue); margin-bottom: 4px; }
.card-label { font-weight: bold; margin-bottom: 4px; color: var(--text-primary); }
.card-type { font-size: 0.75em; color: var(--accent-purple); margin-bottom: 4px; }
.card-content {
  font-size: 0.85em;
  line-height: 1.4;
  color: var(--text-secondary);
  margin-bottom: 8px;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
}
.card-meta { display: flex; gap: 8px; font-size: 0.75em; color: var(--text-muted); }
.sentiment.positive { color: var(--accent-green); }
.sentiment.negative { color: var(--accent-red); }
.sentiment.neutral { color: var(--text-muted); }
.empty-state { text-align: center; padding: 80px 20px; color: var(--text-muted); }
.empty-icon { font-size: 3em; margin-bottom: 16px; }
.detail-panel {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.detail-content {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 24px;
  max-width: 600px;
  width: 90%;
  max-height: 80vh;
  overflow-y: auto;
  position: relative;
}
.close-btn {
  position: absolute;
  top: 12px;
  right: 12px;
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 1.1em;
}
.detail-json { font-size: 0.8em; color: var(--accent-blue); white-space: pre-wrap; word-break: break-all; }
</style>
