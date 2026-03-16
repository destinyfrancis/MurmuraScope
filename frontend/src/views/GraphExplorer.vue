<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { getGraph } from '../api/graph.js'
import { getGraphSnapshots, getGraphSnapshot } from '../api/graph.js'
import { getEchoChambers, getContagionData, getCommunitySummaries, getTripleConflicts, getPolarization } from '../api/simulation.js'
import GraphCanvas from '../components/GraphCanvas.vue'
import GraphToolbar from '../components/GraphToolbar.vue'
import GraphRoundScrubber from '../components/GraphRoundScrubber.vue'
import GraphDetailDrawer from '../components/GraphDetailDrawer.vue'
import GraphMinimap from '../components/GraphMinimap.vue'
import ContagionMap from '../components/ContagionMap.vue'

const props = defineProps({
  sessionId: { type: String, required: true },
})

const canvasRef = ref(null)
const loading = ref(true)
const error = ref(null)

// Graph data
const nodes = ref([])
const edges = ref([])
const highlightedNodes = ref([])

// Toolbar state
const entityTypes = ref([])
const activeTypes = ref(new Set())
const showEchoChambers = ref(false)
const layout = ref('force')

// Snapshot / round state
const availableRounds = ref([])
const currentRound = ref(null)

// Echo chamber + analysis data
const clusterData = ref(null)
const contagionAgentIds = ref([])
const communitySummaries = ref([])
const tripleConflicts = ref([])
const polarizationData = ref(null)
const latestPosts = ref([])
const showContagionMap = ref(false)

// Drawer state
const drawerVisible = ref(false)
const selectedNode = ref(null)
const graphId = ref('')

async function fetchGraph() {
  loading.value = true
  error.value = null
  try {
    const res = await getGraph(props.sessionId)
    const data = res.data?.data || res.data
    graphId.value = data.graph_id || props.sessionId
    nodes.value = data.nodes || []
    edges.value = data.edges || []

    // Extract entity types
    const types = new Set(nodes.value.map(n => (n.type || 'default').toLowerCase()))
    entityTypes.value = [...types]
    activeTypes.value = new Set(types)
  } catch (e) {
    error.value = e.message || '載入圖譜失敗'
  } finally {
    loading.value = false
  }
}

async function fetchSnapshots() {
  try {
    const res = await getGraphSnapshots(props.sessionId)
    const data = res.data?.data || res.data
    if (Array.isArray(data) && data.length > 0) {
      availableRounds.value = data.map(s => s.round_number)
      currentRound.value = availableRounds.value[availableRounds.value.length - 1]
    }
  } catch {
    // Snapshots may not exist yet
  }
}

async function fetchAnalysisData() {
  try {
    const [echoRes, contagionRes, summaryRes, conflictRes, polarRes] = await Promise.allSettled([
      getEchoChambers(props.sessionId),
      getContagionData(props.sessionId),
      getCommunitySummaries(props.sessionId),
      getTripleConflicts(props.sessionId),
      getPolarization(props.sessionId),
    ])

    if (echoRes.status === 'fulfilled') {
      const d = echoRes.value.data?.data || echoRes.value.data
      if (d) clusterData.value = d
    }
    if (contagionRes.status === 'fulfilled') {
      const d = contagionRes.value.data?.data || contagionRes.value.data
      if (d?.contagion_agents) {
        contagionAgentIds.value = d.contagion_agents.map(a => a.agent_id)
      }
    }
    if (summaryRes.status === 'fulfilled') {
      const d = summaryRes.value.data?.data || summaryRes.value.data
      if (Array.isArray(d)) communitySummaries.value = d
    }
    if (conflictRes.status === 'fulfilled') {
      const d = conflictRes.value.data?.data || conflictRes.value.data
      if (Array.isArray(d)) tripleConflicts.value = d
    }
    if (polarRes.status === 'fulfilled') {
      const d = polarRes.value.data?.data || polarRes.value.data
      if (d) polarizationData.value = d
    }
  } catch {
    // Analysis data is optional
  }
}

function handleFilterChange(newTypes) {
  activeTypes.value = newTypes
}

function handleSearchQuery(query) {
  if (!query) {
    highlightedNodes.value = []
    return
  }
  const q = query.toLowerCase()
  const matches = nodes.value
    .filter(n => (n.label || '').toLowerCase().includes(q) || (n.description || '').toLowerCase().includes(q))
    .map(n => n.id)
  highlightedNodes.value = matches
  // Focus on first match
  if (matches.length > 0 && canvasRef.value) {
    canvasRef.value.focusNode(matches[0])
  }
}

function handleEchoToggle() {
  showEchoChambers.value = !showEchoChambers.value
}

function handleLayoutChange(newLayout) {
  layout.value = newLayout
  if (canvasRef.value) {
    canvasRef.value.applyLayout(newLayout)
  }
}

function handleNodeClick(node) {
  selectedNode.value = node
  drawerVisible.value = true
}

async function handleRoundChange(round) {
  currentRound.value = round
  try {
    const res = await getGraphSnapshot(props.sessionId, round)
    const data = res.data?.data || res.data
    if (data?.nodes) nodes.value = data.nodes
    if (data?.edges) edges.value = data.edges
  } catch {
    // Keep current data
  }
}

onMounted(async () => {
  await fetchGraph()
  fetchSnapshots()
  fetchAnalysisData()
})
</script>

<template>
  <div class="explorer-layout">
    <!-- Toolbar -->
    <GraphToolbar
      :entity-types="entityTypes"
      :active-types="activeTypes"
      :show-echo-chambers="showEchoChambers"
      :layout="layout"
      @filter-change="handleFilterChange"
      @search-query="handleSearchQuery"
      @echo-toggle="handleEchoToggle"
      @layout-change="handleLayoutChange"
    />
    <button
      class="contagion-toggle"
      :class="{ active: showContagionMap }"
      @click="showContagionMap = !showContagionMap"
    >
      情緒傳染
    </button>

    <!-- Main area -->
    <div class="explorer-main">
      <!-- Loading -->
      <div v-if="loading" class="explorer-loading">
        <div class="loading-spinner" />
        <p>載入圖譜中...</p>
      </div>

      <!-- Error -->
      <div v-else-if="error" class="explorer-error">
        <p>{{ error }}</p>
        <button class="btn-retry" @click="fetchGraph">重試</button>
      </div>

      <!-- Canvas -->
      <GraphCanvas
        v-else
        ref="canvasRef"
        :nodes="nodes"
        :edges="edges"
        :highlighted-nodes="highlightedNodes"
        :cluster-data="clusterData"
        :contagion-agent-ids="contagionAgentIds"
        :community-summaries="communitySummaries"
        :triple-conflicts="tripleConflicts"
        :polarization-data="polarizationData"
        :latest-posts="latestPosts"
        :show-echo-chambers="showEchoChambers"
        :active-types="activeTypes"
        @node-click="handleNodeClick"
      />
      <!-- Minimap -->
      <GraphMinimap
        v-if="nodes.length > 0"
        :nodes="nodes"
        :graph-instance="canvasRef"
      />
      <!-- Contagion Map overlay -->
      <ContagionMap
        :session-id="sessionId"
        :visible="showContagionMap"
        @toggle="showContagionMap = !showContagionMap"
      />
    </div>

    <!-- Round scrubber -->
    <div class="explorer-scrubber">
      <GraphRoundScrubber
        :available-rounds="availableRounds"
        :current-round="currentRound"
        @round-change="handleRoundChange"
      />
    </div>

    <!-- Detail drawer -->
    <GraphDetailDrawer
      :visible="drawerVisible"
      :selected-node="selectedNode"
      :session-id="sessionId"
      :graph-id="graphId"
      @close="drawerVisible = false"
    />
  </div>
</template>

<style scoped>
.explorer-layout {
  display: grid;
  grid-template-rows: auto 1fr auto;
  height: 100vh;
  overflow: hidden;
}

.explorer-main {
  position: relative;
  overflow: hidden;
}

.explorer-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 12px;
  color: var(--text-muted);
}

.loading-spinner {
  width: 32px;
  height: 32px;
  border: 3px solid var(--border-color);
  border-top-color: var(--accent-blue);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.explorer-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 12px;
  color: var(--accent-red);
}

.btn-retry {
  padding: 8px 16px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  cursor: pointer;
  color: var(--text-primary);
}

.contagion-toggle {
  position: absolute;
  top: 8px;
  right: 340px;
  padding: 4px 12px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-card);
  color: var(--text-muted);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s;
  z-index: 10;
}

.contagion-toggle.active {
  background: rgba(239, 68, 68, 0.1);
  border-color: #ef4444;
  color: #ef4444;
}

.explorer-scrubber {
  display: flex;
  justify-content: center;
  padding: 8px 16px;
  background: var(--bg-card);
  border-top: 1px solid var(--border-color);
}
</style>
