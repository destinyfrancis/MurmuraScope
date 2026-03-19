<script setup>
import { ref, computed, onMounted } from 'vue'
import { getSessionAgents, getAgentMemories, searchAgentMemories, getSentimentSummary, getSession } from '../api/simulation.js'
import AgentSearchPanel from './AgentSearchPanel.vue'
import AgentDetailPanel from './AgentDetailPanel.vue'
import HKDistrictMap from './HKDistrictMap.vue'
import InterviewMode from './InterviewMode.vue'
import ChatInterface from './ChatInterface.vue'

const props = defineProps({
  session: { type: Object, required: true },
})

const selectedAgent = ref(null)
const targetType = ref('report')
const interviewMode = ref(false)
const chatRef = ref(null)

// Agent search/filter panel
const agentList = ref([])
const agentSearch = ref('')
const filterDistrict = ref('')
const filterOccupation = ref('')
const loadingAgents = ref(false)
const agentMemories = ref([])
const loadingMemories = ref(false)
const memorySearchTerm = ref('')
const matchingAgentIds = ref([])
const sentimentData = ref({})
const selectedDistrict = ref(null)
const simMode = ref('hk_demographic')

async function loadAgents() {
  if (!props.session.sessionId) return
  loadingAgents.value = true
  try {
    const res = await getSessionAgents(props.session.sessionId)
    agentList.value = res.data?.data || res.data || []
  } catch (err) {
    console.error('Failed to load agents:', err)
  } finally {
    loadingAgents.value = false
  }
}

async function selectAgent(agent) {
  selectedAgent.value = agent
  targetType.value = 'agent'
  agentMemories.value = []
  loadingMemories.value = true
  try {
    const res = await getAgentMemories(props.session.sessionId, agent.id)
    agentMemories.value = (res.data?.data || res.data || []).slice(0, 3)
  } catch (err) {
    console.error('Failed to load memories:', err)
  } finally {
    loadingMemories.value = false
  }

  chatRef.value?.resetMessages(
    `已選擇代理人：${agent.oasis_username || agent.username || `#${agent.id}`}（${agent.district || '?'} · ${agent.occupation || '?'}）`
  )
}

function clearAgentSelection() {
  selectedAgent.value = null
  targetType.value = 'report'
  agentMemories.value = []
  chatRef.value?.resetMessages(
    '深度交互模式已啟動。你可以針對報告內容提問，或者選擇同個別代理人對話，仲可以提出 What-If 假設情景。'
  )
}

const agentDistrictMap = computed(() => {
  const map = {}
  for (const agent of agentList.value) {
    const d = agent.district
    if (!d) continue
    if (!map[d]) map[d] = []
    map[d].push(agent.id)
  }
  return map
})

async function onMemorySearch(term) {
  memorySearchTerm.value = term
  if (!term) {
    matchingAgentIds.value = []
    return
  }
  const matching = []
  for (const agent of agentList.value.slice(0, 50)) {
    try {
      const res = await searchAgentMemories(props.session.sessionId, agent.id, term, 1)
      const results = res.data?.data || []
      if (results.length > 0) matching.push(agent.id)
    } catch { /* skip */ }
  }
  matchingAgentIds.value = matching
}

function onSelectDistrict(district) {
  selectedDistrict.value = district
  if (district) {
    filterDistrict.value = district
  }
}

onMounted(() => {
  loadAgents()
  getSession(props.session.sessionId)
    .then(res => {
      const data = res.data?.data || res.data
      simMode.value = data?.sim_mode || 'hk_demographic'
    })
    .catch(() => {})
  getSentimentSummary(props.session.sessionId)
    .then(res => {
      sentimentData.value = res.data?.data || {}
    })
    .catch(() => {})
})
</script>

<template>
  <div class="step5">
    <!-- Left sidebar: agent selection panel -->
    <div class="step5-sidebar">
      <AgentSearchPanel
        v-model:agent-search="agentSearch"
        v-model:filter-district="filterDistrict"
        v-model:filter-occupation="filterOccupation"
        :agent-list="agentList"
        :loading-agents="loadingAgents"
        :selected-agent-id="selectedAgent?.id"
        :sim-mode="simMode"
        @select-agent="selectAgent"
        @clear-selection="clearAgentSelection"
      />

      <!-- Agent Detail Panel (with cross-filtering) -->
      <AgentDetailPanel
        v-if="selectedAgent"
        :session-id="session.sessionId"
        :agent-id="selectedAgent.id"
        :agent-profile="selectedAgent"
        @close="clearAgentSelection"
        @memory-search="onMemorySearch"
      />

      <!-- District Map (cross-filtered) — only for HK mode -->
      <HKDistrictMap
        v-if="simMode === 'hk_demographic'"
        :filter-query="memorySearchTerm"
        :agent-districts="agentDistrictMap"
        :matching-agent-ids="matchingAgentIds"
        :sentiment-data="sentimentData"
        :selected-district="selectedDistrict"
        @select-district="onSelectDistrict"
      />

      <!-- Selected agent profile card -->
      <InterviewMode
        :selected-agent="selectedAgent"
        :agent-memories="agentMemories"
        :loading-memories="loadingMemories"
      />
    </div>

    <!-- Main chat area -->
    <ChatInterface
      ref="chatRef"
      :session-id="session.sessionId"
      :report-id="session.reportId"
      :target-type="targetType"
      :selected-agent="selectedAgent"
      v-model:interview-mode="interviewMode"
    />
  </div>
</template>

<style scoped>
.step5 {
  display: grid;
  grid-template-columns: 300px 1fr;
  gap: 16px;
  min-height: 600px;
}

.step5-sidebar {
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow-y: auto;
  max-height: calc(100vh - 160px);
}
</style>
