<script setup>
import { ref, watch } from 'vue'
import { getAgentMemories, searchAgentMemories } from '../../api/simulation.js'

const props = defineProps({
  sessionId: { type: String, default: null },
  agentId: { type: Number, default: null },
})

const emit = defineEmits(['memory-search', 'triples-loaded'])

const memories = ref([])
const triples = ref([])
const loadingMemories = ref(false)
const memorySearchQuery = ref('')
const memorySearchResults = ref([])
const searchingMemories = ref(false)
let searchDebounceTimer = null

function memoryTypeLabel(type) {
  const map = {
    observation: '觀察',
    belief_update: '觀點更新',
    emotional_reaction: '情緒反應',
    social_interaction: '社交互動',
  }
  return map[type] || type
}

const salience = (score) => Math.round((score || 0) * 100)

async function loadMemories() {
  if (!props.sessionId || !props.agentId) return
  loadingMemories.value = true
  try {
    const res = await getAgentMemories(props.sessionId, props.agentId, { limit: 50 })
    const payload = res.data?.data || {}
    if (Array.isArray(payload)) {
      memories.value = payload
    } else {
      memories.value = payload.memories || []
      triples.value = payload.triples || []
      emit('triples-loaded', triples.value)
    }
  } catch (e) {
    console.error('Failed to load memories', e)
  } finally {
    loadingMemories.value = false
  }
}

function onMemorySearch(event) {
  const q = event.target.value.trim()
  memorySearchQuery.value = q
  emit('memory-search', q)
  if (searchDebounceTimer) clearTimeout(searchDebounceTimer)
  if (!q) {
    memorySearchResults.value = []
    return
  }
  searchDebounceTimer = setTimeout(() => doMemorySearch(q), 300)
}

async function doMemorySearch(query) {
  if (!props.sessionId || !props.agentId || !query) return
  searchingMemories.value = true
  try {
    const res = await searchAgentMemories(props.sessionId, props.agentId, query, 10)
    memorySearchResults.value = res.data?.data || []
  } catch (e) {
    console.error('Semantic search failed', e)
    memorySearchResults.value = []
  } finally {
    searchingMemories.value = false
  }
}

function reset() {
  memories.value = []
  triples.value = []
  memorySearchQuery.value = ''
  memorySearchResults.value = []
}

function getTriples() {
  return triples.value
}

defineExpose({ loadMemories, reset, getTriples })
</script>

<template>
  <div class="tab-content">
    <div class="memory-search-bar">
      <input
        type="text"
        class="memory-search-input"
        placeholder="語義搜索記憶 (例: 金融危機)..."
        :value="memorySearchQuery"
        @input="onMemorySearch"
      />
      <span v-if="searchingMemories" class="search-spinner">...</span>
    </div>

    <!-- Search results -->
    <template v-if="memorySearchQuery && memorySearchResults.length > 0">
      <div class="search-results-label">搜索結果 ({{ memorySearchResults.length }})</div>
      <div class="memory-list">
        <div
          v-for="m in memorySearchResults"
          :key="'search-' + m.memory_id"
          class="memory-card search-result"
        >
          <div class="memory-meta">
            <span class="memory-round">輪次 {{ m.round_number }}</span>
            <span class="memory-type">{{ memoryTypeLabel(m.memory_type) }}</span>
            <span class="similarity-badge">相似度 {{ Math.round(m.similarity_score * 100) }}%</span>
            <span class="memory-salience">重要度 {{ salience(m.salience_score) }}%</span>
          </div>
          <p class="memory-text">{{ m.memory_text }}</p>
        </div>
      </div>
    </template>
    <template v-else-if="memorySearchQuery && !searchingMemories">
      <div class="empty-hint">搜索無結果</div>
    </template>

    <!-- Default memory list -->
    <template v-if="!memorySearchQuery">
      <div v-if="loadingMemories" class="loading-hint">載入記憶中...</div>
      <div v-else-if="memories.length === 0" class="empty-hint">尚無記憶記錄</div>
      <div v-else class="memory-list">
        <div
          v-for="m in memories"
          :key="m.id"
          class="memory-card"
        >
          <div class="memory-meta">
            <span class="memory-round">輪次 {{ m.round_number }}</span>
            <span class="memory-type">{{ memoryTypeLabel(m.memory_type) }}</span>
            <span class="memory-salience">重要度 {{ salience(m.salience_score) }}%</span>
          </div>
          <p class="memory-text">{{ m.memory_text }}</p>
          <div class="salience-bar-bg">
            <div
              class="salience-bar-fill"
              :style="{ width: salience(m.salience_score) + '%' }"
            />
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.tab-content {
  overflow-y: auto;
  flex: 1;
  padding: 12px 14px;
}

.memory-search-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 10px;
}

.memory-search-input {
  flex: 1;
  padding: 7px 10px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--bg-primary);
  color: var(--text-primary);
  font-size: 13px;
  outline: none;
  transition: border-color 0.2s;
}

.memory-search-input:focus {
  border-color: var(--accent-blue);
}

.memory-search-input::placeholder {
  color: var(--text-muted);
}

.search-spinner {
  color: var(--accent-blue);
  font-size: 13px;
  animation: pulse 1s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.search-results-label {
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.memory-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.memory-card {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 10px 12px;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.memory-card:hover {
  border-color: var(--accent-blue);
  box-shadow: var(--shadow-card);
}

.memory-card.search-result {
  border-left: 3px solid var(--accent-blue);
}

.memory-meta {
  display: flex;
  gap: 8px;
  margin-bottom: 6px;
  font-size: 11px;
}

.memory-round {
  color: var(--accent-blue);
  font-weight: 600;
}

.memory-type {
  background: rgba(79,156,232,0.15);
  color: var(--accent-blue);
  padding: 1px 6px;
  border-radius: 8px;
}

.memory-salience {
  color: var(--text-muted);
  margin-left: auto;
}

.memory-text {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.6;
  margin-bottom: 8px;
}

.salience-bar-bg {
  height: 3px;
  background: var(--bg-secondary);
  border-radius: 2px;
  overflow: hidden;
}

.salience-bar-fill {
  height: 100%;
  background: var(--accent-blue);
  border-radius: 2px;
}

.similarity-badge {
  background: rgba(79, 156, 232, 0.2);
  color: var(--accent-blue);
  padding: 1px 6px;
  border-radius: 8px;
  font-weight: 600;
}

.loading-hint, .empty-hint {
  text-align: center;
  color: var(--text-muted);
  font-size: 13px;
  padding: 20px 0;
}
</style>
