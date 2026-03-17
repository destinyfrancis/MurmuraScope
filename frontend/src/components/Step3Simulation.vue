<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { startSimulation, connectWebSocket, createBranch, injectShock, getSessionAgents, getEchoChambers, getContagionData, getCommunitySummaries, getTripleConflicts, getPolarization } from '../api/simulation.js'
import { getFactions, getTippingPoints, getWorldEvents } from '../api/simulation.js'
import { getGraph, getGraphSnapshots, getGraphSnapshot } from '../api/graph.js'
import GraphPanel from './GraphPanel.vue'
import SimMonitor from './SimMonitor.vue'
import GodModePanel from './GodModePanel.vue'
import MiniCognitiveMap from './MiniCognitiveMap.vue'
import CommunityPanel from './CommunityPanel.vue'
import SimulationHeader from './SimulationHeader.vue'
import SimulationTabs from './SimulationTabs.vue'
import ForkModal from './ForkModal.vue'
import NetworkTimeline from './NetworkTimeline.vue'
import EmotionalHeatmap from './EmotionalHeatmap.vue'
import ViralityTree from './ViralityTree.vue'
import FilterBubbleChart from './FilterBubbleChart.vue'
import StatsRow          from './sim/StatsRow.vue'
import TippingPointStrip from './sim/TippingPointStrip.vue'

const props = defineProps({
  session: { type: Object, required: true },
})

const emit = defineEmits(['simulation-complete'])

const running = ref(false)
const completed = ref(false)
const currentRound = ref(0)
const totalRounds = ref(props.session.config.roundCount)
const activeTab = ref('feed')
const error = ref(null)

// Fork modal state
const showForkModal = ref(false)
const forkLoading = ref(false)
const forkError = ref(null)
const forkResult = ref(null)

const graphNodes = ref([])
const graphEdges = ref([])
const highlightedNodes = ref([])
const posts = ref([])
const logs = ref([])

// God Mode shock banner
const shockBanner = ref(null)
let shockBannerTimer = null

// Glitch overlay on shock injection
const showGlitch = ref(false)

// Follow Mode
const followedAgent = ref(null)
const showMiniCogmap = ref(true)
const sessionAgents = ref([])
const tripleRefreshTrigger = ref(0)

// Echo Chamber + Contagion + Graph Snapshots
const echoData = ref(null)
const contagionAgentIds = ref([])
const availableRounds = ref([])
const selectedGraphRound = ref(null)

// Community analysis data
const communitySummaries = ref([])
const tripleConflicts = ref([])
const polarizationData = ref(null)
const selectedCluster = ref(null)

// Cognitive Theater (kg_driven) data
const factionSnapshots = ref([])
const tippingPoints    = ref([])
const worldEvents      = ref([])
const factionCount     = ref(0)
const tippingCount     = ref(0)
const simCompleted     = ref(false)

let ws = null
const MAX_RECONNECT = 5
let reconnectAttempts = 0
let reconnectTimer = null

function addLog(message, type = 'info') {
  const entry = {
    timestamp: new Date().toLocaleTimeString('zh-HK'),
    message,
    type,
  }
  logs.value = [...logs.value, entry]
}

function handleWsMessage(event) {
  try {
    const msg = JSON.parse(event.data)
    const d = msg.data || {}

    switch (msg.type) {
      case 'progress':
        if (d.round && d.round > currentRound.value) {
          currentRound.value = d.round
          addLog(`第 ${d.round}/${d.total || totalRounds.value} 回合完成 — ${d.detail || ''}`)
          if (d.round % 3 === 0) {
            fetchEchoChamberData()
            fetchContagionData()
            pollCognitiveData(props.session.sessionId)
          }
          if (d.round % 5 === 0) {
            fetchGraphSnapshots()
            fetchCommunityData()
          }
        }
        break

      case 'post':
        if (d.source === 'shock') {
          addLog(`[衝擊事件] ${d.shock_type || ''}: ${d.content || ''}`, 'warning')
          posts.value = [...posts.value, {
            id: Date.now(),
            username: `[系統衝擊: ${d.shock_type || ''}]`,
            content: d.content || '',
            platform: d.platform || 'facebook',
            round: d.round,
            isShock: true,
          }]
        } else {
          posts.value = [...posts.value, {
            id: Date.now(),
            username: d.username || `Agent`,
            content: d.content || '',
            platform: d.platform || 'facebook',
            round: d.round,
          }]
        }
        if (followedAgent.value) tripleRefreshTrigger.value++
        break

      case 'complete':
        completed.value = true
        running.value = false
        simCompleted.value = true
        pollCognitiveData(props.session.sessionId)
        addLog(`模擬完成！共 ${d.rounds_completed || totalRounds.value} 輪，${d.agent_count || 0} 個 agents`, 'success')
        emit('simulation-complete', { sessionId: props.session.sessionId })
        break

      case 'error':
        addLog(d.message || '模擬錯誤', 'error')
        error.value = d.message || '模擬錯誤'
        running.value = false
        break

      case 'news_shock':
        addLog(`[新聞注入] ${d.headline || ''} (${d.source || ''})`, 'warning')
        posts.value = [...posts.value, {
          id: Date.now(),
          username: `[新聞: ${d.source || 'RTHK'}]`,
          content: d.headline || '',
          platform: 'news_injection',
          round: d.round,
          isNewsShock: true,
          sentiment: d.sentiment || null,
          timestamp: new Date().toISOString(),
        }]
        break

      case 'ping':
        break

      default:
        if (msg.message) addLog(msg.message)
    }
  } catch (err) {
    console.error('WS parse error:', err)
  }
}

function connectWs() {
  ws = connectWebSocket(props.session.sessionId)

  ws.onopen = () => {
    reconnectAttempts = 0
    addLog('WebSocket 連接成功', 'success')
  }

  ws.onmessage = handleWsMessage

  ws.onerror = (err) => {
    addLog('WebSocket 連接錯誤', 'error')
    console.error('WS error:', err)
  }

  ws.onclose = () => {
    addLog('WebSocket 連接已關閉')
    if (!completed.value && running.value && reconnectAttempts < MAX_RECONNECT) {
      const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000)
      reconnectAttempts++
      addLog(`${delay / 1000}s 後重連 (${reconnectAttempts}/${MAX_RECONNECT})...`)
      reconnectTimer = setTimeout(connectWs, delay)
    }
  }
}

async function start() {
  running.value = true
  error.value = null
  addLog('正在啟動模擬...')

  try {
    await startSimulation({
      session_id: props.session.sessionId,
    })
    connectWs()
  } catch (err) {
    error.value = err.response?.data?.detail || err.message || '啟動模擬失敗'
    addLog(error.value, 'error')
    running.value = false
  }
}

async function loadGraph() {
  const graphId = props.session.graphId
  if (!graphId) return
  try {
    const res = await getGraph(graphId)
    const data = res.data?.data || res.data
    graphNodes.value = data?.nodes || []
    graphEdges.value = data?.edges || []
  } catch (err) {
    console.warn('Could not load graph for session:', err)
  }
}

// Fork modal handlers
function openForkModal() {
  forkError.value = null
  forkResult.value = null
  showForkModal.value = true
}

async function handleForkSubmit(payload) {
  forkLoading.value = true
  forkError.value = null
  forkResult.value = null
  try {
    const options = {}
    if (payload.fork_round !== null) {
      options.fork_round = payload.fork_round
    }
    if (payload.label) {
      options.label = payload.label
    }
    const res = await createBranch(props.session.sessionId, options)
    forkResult.value = res.data?.data || res.data
    addLog(`分叉模擬已建立：${forkResult.value?.branch_id?.slice(0, 8) || ''}`, 'success')
  } catch (err) {
    forkError.value = err.response?.data?.detail || err.message || '建立分叉失敗'
    addLog(forkError.value, 'error')
  } finally {
    forkLoading.value = false
  }
}

// Shock handling
async function handleShockDrop(event) {
  event.preventDefault()
  const raw = event.dataTransfer.getData('application/json')
  if (!raw) return
  try {
    const card = JSON.parse(raw)
    shockBanner.value = { text: card.description, visible: true }
    if (shockBannerTimer) clearTimeout(shockBannerTimer)
    shockBannerTimer = setTimeout(() => { shockBanner.value = null }, 5000)
    await injectShock(props.session.sessionId, {
      round_number: currentRound.value || 1,
      shock_type: card.type,
      description: card.description,
      post_content: card.post_content,
    })
    addLog(`[神之手] 注入衝擊: ${card.label}`, 'warning')
    showGlitch.value = true
    setTimeout(() => { showGlitch.value = false }, 300)
  } catch (err) {
    addLog('衝擊注入失敗: ' + (err.response?.data?.detail || err.message), 'error')
  }
}

function handleGodPanelShock(card) {
  handleShockDrop({
    preventDefault() {},
    dataTransfer: { getData: () => JSON.stringify(card) },
  })
}

// Graph interaction
function handleNodeClick(node) {
  const nodeId = node.id
  if (highlightedNodes.value.includes(nodeId)) {
    highlightedNodes.value = highlightedNodes.value.filter(id => id !== nodeId)
  } else {
    highlightedNodes.value = [...highlightedNodes.value, nodeId]
  }
}

// Agent follow mode
function selectAgentFromTab(agent) {
  if (followedAgent.value?.agentId === agent.id) {
    followedAgent.value = null
  } else {
    followedAgent.value = { username: agent.oasis_username || agent.username, agentId: agent.id }
    showMiniCogmap.value = true
    activeTab.value = 'feed'
  }
}

// Data fetching
async function fetchEchoChamberData() {
  try {
    const res = await getEchoChambers(props.session.sessionId)
    echoData.value = res.data?.data || null
  } catch { /* silent */ }
}

async function fetchContagionData() {
  try {
    const res = await getContagionData(props.session.sessionId)
    contagionAgentIds.value = res.data?.data?.agent_ids || []
  } catch { /* silent */ }
}

async function fetchGraphSnapshots() {
  try {
    const res = await getGraphSnapshots(props.session.graphId)
    const snapshots = res.data?.data || []
    availableRounds.value = snapshots.map(s => s.round_number).sort((a, b) => a - b)
  } catch { /* silent */ }
}

async function fetchCommunityData() {
  const sid = props.session.sessionId
  const [sumRes, conflictRes, polRes] = await Promise.allSettled([
    getCommunitySummaries(sid),
    getTripleConflicts(sid),
    getPolarization(sid),
  ])
  if (sumRes.status === 'fulfilled') communitySummaries.value = sumRes.value.data?.data || []
  if (conflictRes.status === 'fulfilled') tripleConflicts.value = conflictRes.value.data?.data || []
  if (polRes.status === 'fulfilled') polarizationData.value = polRes.value.data?.data || null
}

async function pollCognitiveData(sessionId) {
  try {
    const [factRes, tippRes, weRes] = await Promise.allSettled([
      getFactions(sessionId),
      getTippingPoints(sessionId),
      getWorldEvents(sessionId),
    ])
    if (factRes.status === 'fulfilled') {
      factionSnapshots.value = factRes.value.data.data.snapshots ?? []
      factionCount.value = (() => {
        const snaps = factionSnapshots.value
        if (!snaps.length) return 0
        try { return JSON.parse(snaps[snaps.length - 1].factions_json).length } catch { return 0 }
      })()
    }
    if (tippRes.status === 'fulfilled') {
      tippingPoints.value = tippRes.value.data.data.tipping_points ?? []
      tippingCount.value  = tippingPoints.value.length
    }
    if (weRes.status === 'fulfilled') {
      worldEvents.value = weRes.value.data.data.events ?? []
    }
  } catch (e) {
    console.warn('pollCognitiveData failed:', e)
  }
}

function handleHullClick({ cluster_id, summary }) {
  selectedCluster.value = { cluster_id, summary }
}

const selectedClusterAgents = computed(() => {
  if (!selectedCluster.value || !echoData.value?.agent_to_cluster) return []
  const cid = selectedCluster.value.cluster_id
  const mapping = echoData.value.agent_to_cluster
  return sessionAgents.value.filter(a => mapping[a.id] === cid)
})

const selectedClusterConflicts = computed(() => {
  if (!selectedCluster.value || !tripleConflicts.value.length) return []
  const cid = selectedCluster.value.cluster_id
  const mapping = echoData.value?.agent_to_cluster || {}
  return tripleConflicts.value.filter(c => {
    const aCluster = (c.agent_ids_a || []).some(id => mapping[id] === cid)
    const bCluster = (c.agent_ids_b || []).some(id => mapping[id] === cid)
    return aCluster || bCluster
  })
})

async function handleRoundChange(round) {
  selectedGraphRound.value = round
  try {
    const res = await getGraphSnapshot(props.session.graphId, round)
    const snapshot = res.data?.data || {}
    if (snapshot.nodes) graphNodes.value = snapshot.nodes
    if (snapshot.edges) graphEdges.value = snapshot.edges
  } catch (err) {
    console.warn('Failed to load graph snapshot:', err)
  }
}

onMounted(() => {
  loadGraph()
  if (props.session.sessionId) {
    start()
    getSessionAgents(props.session.sessionId)
      .then(r => { sessionAgents.value = r.data?.data || [] })
      .catch(() => {})
  }
})

onUnmounted(() => {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  if (ws) {
    ws.close()
    ws = null
  }
})

const progressPercent = ref(0)
watch(currentRound, (r) => {
  progressPercent.value = Math.round((r / totalRounds.value) * 100)
})
</script>

<template>
  <div class="step3">
    <SimulationHeader
      :current-round="currentRound"
      :total-rounds="totalRounds"
      :progress-percent="progressPercent"
      :running="running"
      :completed="completed"
      @open-fork="openForkModal"
    />

    <ForkModal
      :show="showForkModal"
      :current-round="currentRound"
      :total-rounds="totalRounds"
      :loading="forkLoading"
      :error="forkError"
      :result="forkResult"
      @close="showForkModal = false"
      @submit="handleForkSubmit"
    />

    <div class="sim-body">
      <div class="sim-left">
        <div class="graph-container" @drop="handleShockDrop" @dragover.prevent>
          <Transition name="banner-fade">
            <div v-if="shockBanner?.visible" class="shock-banner">
              突發新聞注入中：{{ shockBanner.text }} — 觀察代理人反應...
            </div>
          </Transition>
          <GraphPanel
            :nodes="graphNodes"
            :edges="graphEdges"
            :highlighted-nodes="highlightedNodes"
            :cluster-data="echoData"
            :contagion-agent-ids="contagionAgentIds"
            :available-rounds="availableRounds"
            :community-summaries="communitySummaries"
            :triple-conflicts="tripleConflicts"
            :polarization-data="polarizationData"
            @node-click="handleNodeClick"
            @round-change="handleRoundChange"
            @hull-click="handleHullClick"
          />
        </div>
        <Transition name="slide-in">
          <CommunityPanel
            v-if="selectedCluster"
            :session-id="session.sessionId"
            :cluster-id="selectedCluster.cluster_id"
            :summary="selectedCluster.summary"
            :cluster-agents="selectedClusterAgents"
            :conflicts="selectedClusterConflicts"
            @close="selectedCluster = null"
          />
        </Transition>
        <MiniCognitiveMap
          v-if="followedAgent && showMiniCogmap"
          :session-id="session.sessionId"
          :agent-id="followedAgent.agentId"
          :agent-username="followedAgent.username"
          :refresh-trigger="tripleRefreshTrigger"
          @close="showMiniCogmap = false"
        />
      </div>

      <div class="sim-right">
        <StatsRow
          :agent-count="sessionAgents.length"
          :current-round="currentRound"
          :total-rounds="totalRounds"
          :faction-count="factionCount"
          :tipping-count="tippingCount"
        />

        <SimulationTabs
          :active-tab="activeTab"
          :posts="posts"
          :followed-agent="followedAgent"
          :session-agents="sessionAgents"
          :session-id="props.session.sessionId"
          :faction-snapshots="factionSnapshots"
          :tipping-points="tippingPoints"
          :world-events="worldEvents"
          :sim-completed="simCompleted"
          @update:active-tab="activeTab = $event"
          @select-agent="selectAgentFromTab"
          @clear-follow="followedAgent = null"
        >
          <template #network>
            <NetworkTimeline :session-id="session.sessionId" :current-round="currentRound" />
          </template>
          <template #emotion>
            <EmotionalHeatmap :session-id="session.sessionId" />
          </template>
        </SimulationTabs>

        <TippingPointStrip
          :tipping-point="tippingPoints[tippingPoints.length - 1] ?? null"
        />

        <!-- Virality + Filter Bubble below tabs -->
        <div v-if="completed" class="post-sim-panels">
          <ViralityTree :session-id="session.sessionId" />
          <FilterBubbleChart :session-id="session.sessionId" />
        </div>

        <div class="monitor-area">
          <SimMonitor :logs="logs" />
        </div>
      </div>
    </div>

    <GodModePanel v-if="running" @inject-shock="handleGodPanelShock" />

    <p v-if="error" class="error-text">{{ error }}</p>

    <!-- Glitch overlay on shock injection -->
    <div v-if="showGlitch" class="glitch-overlay" />
  </div>
</template>

<style scoped>
.step3 {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: calc(100vh - 120px);
  overflow: hidden;
}

.sim-body {
  flex: 1;
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: 16px;
  min-height: 0;
  overflow: hidden;
}

.sim-left {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.graph-container {
  flex: 1;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  min-height: 0;
  overflow: hidden;
  position: relative;
}

.shock-banner {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  padding: 8px 14px;
  background: rgba(239, 68, 68, 0.9);
  color: #0d1117;
  font-size: 13px;
  font-weight: 600;
  text-align: center;
  z-index: 30;
}

.banner-fade-enter-active,
.banner-fade-leave-active {
  transition: opacity 0.3s ease;
}
.banner-fade-enter-from,
.banner-fade-leave-to {
  opacity: 0;
}

.sim-right {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
  overflow: hidden;
}

.monitor-area {
  height: 180px;
  flex-shrink: 0;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.post-sim-panels {
  display: flex;
  gap: 12px;
  margin-top: 8px;
  max-height: 300px;
  overflow-y: auto;
}

.post-sim-panels > * {
  flex: 1;
  min-width: 0;
}

.error-text {
  color: var(--accent-red);
  font-size: 14px;
  text-align: center;
}

/* Slide-in transition for CommunityPanel */
.slide-in-enter-active,
.slide-in-leave-active {
  transition: transform 0.3s ease;
}

.slide-in-enter-from,
.slide-in-leave-to {
  transform: translateX(100%);
}

/* Glitch overlay on shock injection */
.glitch-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  pointer-events: none;
  background: linear-gradient(transparent 0%, rgba(34, 211, 238, 0.03) 50%, transparent 100%);
  animation: glitch-flash 0.3s ease-out forwards;
}

@keyframes glitch-flash {
  0% { opacity: 1; filter: hue-rotate(90deg) saturate(3); transform: skewX(2deg) translateX(2px); }
  25% { transform: skewX(-1deg) translateX(-1px); filter: hue-rotate(-45deg) saturate(2); }
  50% { transform: skewX(0.5deg); filter: hue-rotate(30deg); }
  100% { opacity: 0; transform: none; filter: none; }
}
</style>
