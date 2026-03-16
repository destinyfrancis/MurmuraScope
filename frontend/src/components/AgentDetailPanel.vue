<script setup>
import { ref, watch, onBeforeUnmount } from 'vue'
import ProfileTab from './agent-tabs/ProfileTab.vue'
import MemoriesTab from './agent-tabs/MemoriesTab.vue'
import ActionsTab from './agent-tabs/ActionsTab.vue'
import RelationshipsTab from './agent-tabs/RelationshipsTab.vue'
import CognitiveMapTab from './agent-tabs/CognitiveMapTab.vue'
import FeedView from './FeedView.vue'
import BeliefPanel from './BeliefPanel.vue'

const props = defineProps({
  sessionId: { type: String, default: null },
  agentId: { type: Number, default: null },
  agentProfile: { type: Object, default: null },
})

const emit = defineEmits(['close', 'memory-search'])

const activeTab = ref('profile')
const memoriesTabRef = ref(null)
const actionsTabRef = ref(null)
const relationshipsTabRef = ref(null)
const cogMapTabRef = ref(null)

// Triples cache shared between memories and cogmap tabs
let cachedTriples = []

const tabs = [
  { id: 'profile', label: '個人資料' },
  { id: 'memories', label: '記憶' },
  { id: 'relationships', label: '關係' },
  { id: 'cogmap', label: '認知星圖' },
  { id: 'actions', label: '帖子' },
  { id: 'feed', label: '推薦信息流' },
  { id: 'beliefs', label: '信念系統' },
]

function onTriplesLoaded(triples) {
  cachedTriples = triples
}

function onMemorySearch(query) {
  emit('memory-search', query)
}

watch(activeTab, (tab) => {
  if (tab === 'memories' && memoriesTabRef.value) {
    memoriesTabRef.value.loadMemories()
  }
  if (tab === 'cogmap' && cogMapTabRef.value) {
    const existingTriples = memoriesTabRef.value?.getTriples() || cachedTriples
    cogMapTabRef.value.loadGraph(existingTriples)
  }
  if (tab === 'actions' && actionsTabRef.value) {
    actionsTabRef.value.loadActions()
  }
  if (tab === 'relationships' && relationshipsTabRef.value) {
    relationshipsTabRef.value.loadRelationships()
  }
})

watch(() => props.agentId, () => {
  activeTab.value = 'profile'
  cachedTriples = []
  memoriesTabRef.value?.reset()
  actionsTabRef.value?.reset()
  relationshipsTabRef.value?.reset()
  cogMapTabRef.value?.reset()
})

onBeforeUnmount(() => {
  cogMapTabRef.value?.reset()
})
</script>

<template>
  <div v-if="agentId" class="agent-panel">
    <div class="panel-header">
      <div class="agent-title">
        <span class="agent-icon">👤</span>
        <span class="agent-name">{{ agentProfile?.oasis_username || `Agent #${agentId}` }}</span>
      </div>
      <button class="close-btn" @click="$emit('close')">✕</button>
    </div>

    <div class="panel-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        class="tab-btn"
        :class="{ active: activeTab === tab.id }"
        @click="activeTab = tab.id"
      >
        {{ tab.label }}
      </button>
    </div>

    <ProfileTab
      v-if="activeTab === 'profile'"
      :agent-profile="agentProfile"
    />

    <MemoriesTab
      v-else-if="activeTab === 'memories'"
      ref="memoriesTabRef"
      :session-id="sessionId"
      :agent-id="agentId"
      @memory-search="onMemorySearch"
      @triples-loaded="onTriplesLoaded"
    />

    <RelationshipsTab
      v-else-if="activeTab === 'relationships'"
      ref="relationshipsTabRef"
      :session-id="sessionId"
      :agent-id="agentId"
    />

    <CognitiveMapTab
      v-else-if="activeTab === 'cogmap'"
      ref="cogMapTabRef"
      :session-id="sessionId"
      :agent-id="agentId"
      :agent-profile="agentProfile"
    />

    <ActionsTab
      v-else-if="activeTab === 'actions'"
      ref="actionsTabRef"
      :session-id="sessionId"
      :agent-profile="agentProfile"
    />

    <FeedView
      v-else-if="activeTab === 'feed'"
      :session-id="sessionId"
      :agent-id="agentId"
    />

    <BeliefPanel
      v-else-if="activeTab === 'beliefs'"
      :session-id="sessionId"
      :agent-id="agentId"
    />
  </div>
</template>

<style scoped>
.agent-panel {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  max-height: 600px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 16px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-card);
}

.agent-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.agent-icon { font-size: 18px; }

.agent-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.close-btn {
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 16px;
  padding: 2px 6px;
}

.close-btn:hover { color: var(--text-primary); }

.panel-tabs {
  display: flex;
  border-bottom: 1px solid var(--border-color);
}

.tab-btn {
  flex: 1;
  padding: 10px;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-muted);
  font-size: 13px;
  cursor: pointer;
  transition: var(--transition);
}

.tab-btn.active {
  color: var(--accent-blue);
  border-bottom-color: var(--accent-blue);
}
</style>
