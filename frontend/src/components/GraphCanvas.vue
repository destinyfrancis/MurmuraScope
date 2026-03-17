<script setup>
import { ref, computed, onMounted, onUnmounted, watch, toRefs } from 'vue'
import ForceGraph from 'force-graph'
import { forceManyBody, forceCollide, forceX, forceY } from 'd3-force'

import {
  convexHull, clusterHue, expandHull, drawRoundedHull,
  pointInPolygon, hullCentroid, drawArrowhead,
  getHullFillColor, getHullStrokeColor, getHullStrokeWidth,
} from '../utils/graphHullUtils.js'
import { spawnThoughtBubble, drawThoughtBubbles } from '../utils/graphThoughtBubbles.js'
import { createRippleLoop } from '../utils/graphContagionRenderer.js'
import {
  drawNode as renderNode,
  getNodeColor,
  isHostileCrossCluster,
  getLinkColor as baseLinkColor,
  getLinkWidth as baseLinkWidth,
  getLinkDash as baseLinkDash,
} from '../utils/graphNodeRenderer.js'

const props = defineProps({
  nodes: { type: Array, default: () => [] },
  edges: { type: Array, default: () => [] },
  highlightedNodes: { type: Array, default: () => [] },
  clusterData: { type: Object, default: null },
  contagionAgentIds: { type: Array, default: () => [] },
  communitySummaries: { type: Array, default: () => [] },
  tripleConflicts: { type: Array, default: () => [] },
  polarizationData: { type: Object, default: null },
  latestPosts: { type: Array, default: () => [] },
  showEchoChambers: { type: Boolean, default: false },
  activeTypes: { type: Object, default: null }, // Set or null
  factionColours: { type: Object, default: () => ({}) },
  // { [agent_id]: '#hexcolour' }
})

const emit = defineEmits(['node-click', 'hull-click'])

const { nodes, edges, highlightedNodes } = toRefs(props)

const containerRef = ref(null)
const tooltipData = ref(null)

let graphInstance = null
let resizeObserver = null
let hullCache = new Map()

// Hull memoization: skip recomputation when cluster membership unchanged
let lastClusterFingerprint = ''

function computeClusterFingerprint(data) {
  if (!data?.nodes) return ''
  const parts = []
  for (const node of data.nodes) {
    if (node.cluster_id !== undefined && node.cluster_id !== null) {
      parts.push(`${node.id}:${node.cluster_id}`)
    }
  }
  parts.sort()
  return parts.join('|')
}

// Thought bubble state
let thoughtBubbles = []
let frameCounter = 0

// Ripple animation loop (delegates to utility)
const rippleLoop = createRippleLoop(() => graphInstance)

// Reactive snapshot of node positions for faction hull overlay.
// Updated on each simulation tick via onRenderFramePre.
const nodePositions = ref([])

// Faction hull overlay: groups positioned nodes by faction colour and
// computes a bounding circle for each group.
const factionHulls = computed(() => {
  if (!Object.keys(props.factionColours).length) return []
  const groups = {}
  for (const node of nodePositions.value) {
    const colour = props.factionColours[node.id]
    if (!colour) continue
    if (!groups[colour]) groups[colour] = []
    groups[colour].push({ x: node.x ?? 0, y: node.y ?? 0 })
  }
  return Object.entries(groups).map(([colour, pts]) => {
    const cx = pts.reduce((s, p) => s + p.x, 0) / pts.length
    const cy = pts.reduce((s, p) => s + p.y, 0) / pts.length
    const r = Math.max(...pts.map(p => Math.hypot(p.x - cx, p.y - cy))) + 20
    return { colour, cx, cy, r }
  })
})

// Canvas dimensions for the hull SVG overlay
const canvasWidth = ref(600)
const canvasHeight = ref(400)

// ---------------------------------------------------------------------------
// Graph data builder
// ---------------------------------------------------------------------------
function buildGraphData() {
  const nodeList = nodes.value.map((n) => {
    const node = { ...n }
    if (props.clusterData?.agent_to_cluster) {
      const agentId = parseInt(node.agent_id || node.id, 10)
      if (!isNaN(agentId) && agentId in props.clusterData.agent_to_cluster) {
        node.cluster_id = props.clusterData.agent_to_cluster[agentId]
      }
    }
    if (props.contagionAgentIds.length > 0) {
      const agentId = parseInt(node.agent_id || node.id, 10)
      if (!isNaN(agentId) && props.contagionAgentIds.includes(agentId)) {
        node.contagion_active = true
      }
    }
    return node
  })
  const linkList = edges.value.map((e) => ({
    ...e,
    source: e.source || e.source_id,
    target: e.target || e.target_id,
  }))
  return { nodes: nodeList, links: linkList }
}

// ---------------------------------------------------------------------------
// Echo chamber hull + conflict line rendering (pre-frame callback)
// ---------------------------------------------------------------------------
function drawHulls(ctx, globalScale) {
  // Thought bubbles always render
  thoughtBubbles = drawThoughtBubbles(ctx, globalScale, thoughtBubbles)
  frameCounter++

  // Refresh reactive node positions every 3 frames for the faction hull overlay
  if (frameCounter % 3 === 0 && Object.keys(props.factionColours).length) {
    const data = graphInstance?.graphData()
    if (data?.nodes) {
      nodePositions.value = data.nodes.map(n => ({ id: n.id, x: n.x, y: n.y }))
    }
  }
  if (frameCounter >= 120) {
    frameCounter = 0
    const fdata = graphInstance?.graphData()
    if (fdata) {
      thoughtBubbles = spawnThoughtBubble({
        latestPosts: props.latestPosts,
        graphData: fdata,
        currentBubbles: thoughtBubbles,
      })
    }
  }

  if (!props.showEchoChambers) return
  const data = graphInstance?.graphData()
  if (!data) return

  // Memoize: only recompute hulls when cluster membership changes
  const fingerprint = computeClusterFingerprint(data)
  const membershipChanged = fingerprint !== lastClusterFingerprint
  if (membershipChanged) {
    lastClusterFingerprint = fingerprint
  }

  const clusters = new Map()
  for (const node of data.nodes) {
    const cid = node.cluster_id
    if (cid === undefined || cid === null) continue
    if (!clusters.has(cid)) clusters.set(cid, [])
    clusters.get(cid).push(node)
  }

  if (membershipChanged) {
    hullCache = new Map()
  }

  for (const [cid, clusterNodes] of clusters) {
    if (clusterNodes.length < 2) continue
    const points = clusterNodes.map(n => [n.x, n.y])
    let hull = convexHull(points)
    if (hull.length < 2) continue
    hull = expandHull(hull, 28)

    hullCache.set(cid, hull)

    const hue = clusterHue(cid)
    let deviation = 0
    if (props.polarizationData?.cluster_stances) {
      const stance = props.polarizationData.cluster_stances[String(cid)]
      if (stance) deviation = Math.abs((stance.avg_stance ?? 0.5) - 0.5) * 2
    }
    const strokeColor = getHullStrokeColor(cid, hue, props.polarizationData)
    ctx.save()
    if (deviation > 0.5) {
      ctx.shadowColor = strokeColor
      ctx.shadowBlur = 8
    }
    drawRoundedHull(ctx, hull, 20)
    ctx.fillStyle = getHullFillColor(cid, hue, props.polarizationData)
    ctx.fill()
    ctx.strokeStyle = strokeColor
    ctx.lineWidth = getHullStrokeWidth(cid, globalScale, props.polarizationData)
    ctx.setLineDash([])
    ctx.stroke()
    ctx.restore()
  }

  drawConflictLines(ctx, globalScale)
}

// ---------------------------------------------------------------------------
// Conflict lines between communities
// ---------------------------------------------------------------------------
function drawConflictLines(ctx, globalScale) {
  if (!props.tripleConflicts.length || !props.clusterData?.agent_to_cluster) return
  const mapping = props.clusterData.agent_to_cluster

  for (const conflict of props.tripleConflicts) {
    const clustersA = new Set()
    const clustersB = new Set()
    for (const aid of (conflict.agent_ids_a || [])) {
      const cid = mapping[aid]
      if (cid !== undefined) clustersA.add(cid)
    }
    for (const aid of (conflict.agent_ids_b || [])) {
      const cid = mapping[aid]
      if (cid !== undefined) clustersB.add(cid)
    }

    for (const cidA of clustersA) {
      for (const cidB of clustersB) {
        if (cidA === cidB) continue
        const hullA = hullCache.get(cidA)
        const hullB = hullCache.get(cidB)
        if (!hullA || !hullB) continue

        const cA = hullCentroid(hullA)
        const cB = hullCentroid(hullB)

        ctx.save()
        ctx.setLineDash([8 / globalScale, 4 / globalScale])
        ctx.strokeStyle = 'rgba(239, 68, 68, 0.6)'
        ctx.lineWidth = 2 / globalScale
        ctx.beginPath()
        ctx.moveTo(cA[0], cA[1])
        ctx.lineTo(cB[0], cB[1])
        ctx.stroke()

        drawArrowhead(ctx, cA, cB, 10 / globalScale)

        const mx = (cA[0] + cB[0]) / 2
        const my = (cA[1] + cB[1]) / 2
        const label = conflict.entity || ''
        if (label) {
          const fontSize = Math.max(10, 12 / globalScale)
          ctx.font = `${fontSize}px sans-serif`
          const tw = ctx.measureText(label).width
          ctx.fillStyle = 'rgba(239, 68, 68, 0.7)'
          ctx.fillRect(mx - tw / 2 - 4, my - fontSize / 2 - 2, tw + 8, fontSize + 4)
          ctx.fillStyle = '#fff'
          ctx.textAlign = 'center'
          ctx.textBaseline = 'middle'
          ctx.fillText(label, mx, my)
        }

        ctx.setLineDash([])
        ctx.restore()
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Hull hover / click handlers
// ---------------------------------------------------------------------------
function findHullAtPoint(screenX, screenY) {
  if (!graphInstance) return null
  const coords = graphInstance.screen2GraphCoords(screenX, screenY)
  if (!coords) return null
  for (const [cid, hull] of hullCache) {
    if (pointInPolygon(coords.x, coords.y, hull)) return cid
  }
  return null
}

function findSummaryForCluster(clusterId) {
  return props.communitySummaries.find(
    s => s.cluster_id === clusterId || s.cluster_id === String(clusterId)
  ) || null
}

function handleHullHover(e) {
  if (!props.showEchoChambers || !props.communitySummaries.length) {
    tooltipData.value = null
    return
  }
  const cid = findHullAtPoint(e.offsetX, e.offsetY)
  if (cid === null) { tooltipData.value = null; return }
  const summary = findSummaryForCluster(cid)
  if (!summary) { tooltipData.value = null; return }
  tooltipData.value = {
    screenX: e.offsetX + 12,
    screenY: e.offsetY - 10,
    cluster_id: cid,
    core_narrative: summary.core_narrative || '',
    shared_anxieties: summary.shared_anxieties || '',
    member_count: summary.member_count || 0,
    avg_trust: summary.avg_trust || 0,
  }
}

function handleHullClick(e) {
  if (!props.showEchoChambers) return
  const cid = findHullAtPoint(e.offsetX, e.offsetY)
  if (cid === null) return
  const summary = findSummaryForCluster(cid)
  if (!summary) return
  emit('hull-click', { cluster_id: cid, summary })
}

function hullBadgeStyle(clusterId) {
  const hue = clusterHue(clusterId)
  return {
    background: `hsla(${hue}, 65%, 50%, 0.2)`,
    color: `hsl(${hue}, 65%, 35%)`,
  }
}

// ---------------------------------------------------------------------------
// Link styling wrappers (bind showEchoChambers)
// ---------------------------------------------------------------------------
function getLinkColor(link) { return baseLinkColor(link, props.showEchoChambers) }
function getLinkWidth(link) { return baseLinkWidth(link, props.showEchoChambers) }
function getLinkDash(link) { return baseLinkDash(link, props.showEchoChambers) }

// ---------------------------------------------------------------------------
// Faction colour helper
// ---------------------------------------------------------------------------
function nodeColour(node) {
  return props.factionColours[node.id] ?? '#9CA3AF'
}

// ---------------------------------------------------------------------------
// Node draw wrapper (bind props)
// ---------------------------------------------------------------------------
function drawNode(node, ctx, globalScale) {
  const highlightSet = new Set(highlightedNodes.value)
  renderNode(node, ctx, globalScale, {
    activeTypes: props.activeTypes,
    highlightedSet: highlightSet,
    factionColour: nodeColour(node),
  })
}

// ---------------------------------------------------------------------------
// Graph init
// ---------------------------------------------------------------------------
function initGraph() {
  if (!containerRef.value) return

  if (graphInstance) {
    graphInstance._destructor?.()
    graphInstance = null
    containerRef.value.innerHTML = ''
  }

  if (nodes.value.length === 0) return

  const width = containerRef.value.clientWidth || 600
  const height = containerRef.value.clientHeight || 400
  canvasWidth.value = width
  canvasHeight.value = height

  graphInstance = ForceGraph()(containerRef.value)
    .width(width)
    .height(height)
    .graphData(buildGraphData())
    .nodeCanvasObject(drawNode)
    .nodeCanvasObjectMode(() => 'replace')
    .nodePointerAreaPaint((node, color, ctx) => {
      const r = (node.size || 10) + 4
      ctx.fillStyle = color
      ctx.beginPath()
      ctx.arc(node.x, node.y, r, 0, 2 * Math.PI)
      ctx.fill()
    })
    .onNodeClick((node) => emit('node-click', node))
    .linkColor(getLinkColor)
    .linkWidth(getLinkWidth)
    .linkLineDash(getLinkDash)
    .linkLabel((link) => link.label || link.relation || '')
    .linkCanvasObjectMode(() => 'after')
    .linkCanvasObject((link, ctx) => {
      const weight = link.weight || 1
      if (weight < 3 && !isHostileCrossCluster(link, props.showEchoChambers)) return
      const src = typeof link.source === 'object' ? link.source : { x: 0, y: 0 }
      const tgt = typeof link.target === 'object' ? link.target : { x: 0, y: 0 }
      ctx.save()
      ctx.beginPath()
      ctx.moveTo(src.x, src.y)
      ctx.lineTo(tgt.x, tgt.y)
      const glowColor = isHostileCrossCluster(link, props.showEchoChambers) ? '#ef4444' : getLinkColor(link)
      ctx.strokeStyle = glowColor
      ctx.shadowColor = glowColor
      ctx.shadowBlur = isHostileCrossCluster(link, props.showEchoChambers) ? 8 : 4
      ctx.lineWidth = getLinkWidth(link)
      ctx.stroke()
      ctx.restore()
    })
    .onRenderFramePre(drawHulls)
    .backgroundColor('transparent')
    .cooldownTicks(100)
    .d3Force('charge', forceManyBody().strength(-150))
    .d3Force('collide', forceCollide(22))
    .d3Force('x', forceX(width / 2).strength(0.06))
    .d3Force('y', forceY(height / 2).strength(0.06))

  containerRef.value.addEventListener('mousemove', handleHullHover)
  containerRef.value.addEventListener('click', handleHullClick)

  rippleLoop.update(nodes.value)
}

function refreshHighlights() {
  if (graphInstance) {
    graphInstance.nodeCanvasObject(drawNode)
    graphInstance.refresh()
  }
}

// ---------------------------------------------------------------------------
// Watchers
// ---------------------------------------------------------------------------
watch([nodes, edges], () => {
  initGraph()
}, { deep: true })

watch(highlightedNodes, () => {
  refreshHighlights()
}, { deep: true })

watch([() => props.clusterData, () => props.contagionAgentIds], () => {
  if (graphInstance) {
    graphInstance.graphData(buildGraphData())
    rippleLoop.update(nodes.value)
  }
}, { deep: true })

watch(() => props.showEchoChambers, (val) => {
  if (!graphInstance) return
  if (!val) tooltipData.value = null
  graphInstance
    .linkColor(getLinkColor)
    .linkWidth(getLinkWidth)
    .linkLineDash(getLinkDash)
  graphInstance.refresh()
})

watch(() => props.activeTypes, () => {
  if (graphInstance) graphInstance.refresh()
}, { deep: true })

watch([() => props.communitySummaries, () => props.tripleConflicts, () => props.polarizationData], () => {
  if (graphInstance) graphInstance.refresh()
}, { deep: true })

watch(() => props.factionColours, () => {
  if (graphInstance) graphInstance.refresh()
}, { deep: true })

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------
onMounted(() => {
  initGraph()

  resizeObserver = new ResizeObserver(() => {
    if (!containerRef.value || !graphInstance) return
    const w = containerRef.value.clientWidth || 600
    const h = containerRef.value.clientHeight || 400
    canvasWidth.value = w
    canvasHeight.value = h
    graphInstance.width(w).height(h)
  })

  if (containerRef.value) {
    resizeObserver.observe(containerRef.value)
  }
})

onUnmounted(() => {
  rippleLoop.stop()
  if (containerRef.value) {
    containerRef.value.removeEventListener('mousemove', handleHullHover)
    containerRef.value.removeEventListener('click', handleHullClick)
  }
  if (graphInstance) {
    graphInstance._destructor?.()
    graphInstance = null
  }
  if (resizeObserver) {
    resizeObserver.disconnect()
    resizeObserver = null
  }
})

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------
function applyLayout(layout) {
  if (!graphInstance) return
  const g = graphInstance
  if (layout === 'force') {
    g.d3Force('x', null)
    g.d3Force('y', null)
  } else if (layout === 'clustered') {
    const clusters = {}
    let ci = 0
    props.nodes.forEach(n => {
      const cid = n.cluster_id ?? 'default'
      if (!(cid in clusters)) clusters[cid] = ci++
    })
    const cx = (id) => (clusters[id] || 0) % 4 * 200 - 300
    const cy = (id) => Math.floor((clusters[id] || 0) / 4) * 200 - 200
    g.d3Force('x', forceX(n => cx(n.cluster_id ?? 'default')).strength(0.3))
    g.d3Force('y', forceY(n => cy(n.cluster_id ?? 'default')).strength(0.3))
  } else if (layout === 'radial') {
    const total = props.nodes.length || 1
    g.d3Force('x', forceX((n, i) => Math.cos(2 * Math.PI * i / total) * 300).strength(0.4))
    g.d3Force('y', forceY((n, i) => Math.sin(2 * Math.PI * i / total) * 300).strength(0.4))
  }
  g.d3ReheatSimulation()
}

defineExpose({
  focusNode(nodeId) {
    if (!graphInstance) return
    const data = graphInstance.graphData()
    const node = data.nodes.find(n => n.id === nodeId)
    if (node) {
      graphInstance.centerAt(node.x, node.y, 500)
      graphInstance.zoom(2, 500)
      setTimeout(() => emit('node-click', node), 600)
    }
  },
  applyLayout,
})
</script>

<template>
  <div class="graph-canvas-wrapper">
    <div ref="containerRef" class="graph-canvas" />
    <div v-if="nodes.length === 0" class="empty-overlay">
      <p>暫無圖譜數據</p>
    </div>

    <!-- Faction echo-hull overlay -->
    <svg
      v-if="factionHulls.length"
      class="hull-overlay"
      :width="canvasWidth"
      :height="canvasHeight"
    >
      <circle
        v-for="(hull, idx) in factionHulls"
        :key="idx"
        :cx="hull.cx"
        :cy="hull.cy"
        :r="hull.r"
        :fill="hull.colour"
        fill-opacity="0.08"
        stroke="none"
      />
    </svg>

    <!-- Hull hover tooltip -->
    <div
      v-if="tooltipData && showEchoChambers"
      class="hull-tooltip"
      :style="{ left: tooltipData.screenX + 'px', top: tooltipData.screenY + 'px' }"
    >
      <div class="hull-tooltip-header">
        <span class="hull-cluster-badge" :style="hullBadgeStyle(tooltipData.cluster_id)">
          社群 #{{ tooltipData.cluster_id }}
        </span>
        <span class="hull-member-count">{{ tooltipData.member_count }} 人</span>
      </div>
      <div class="hull-tooltip-narrative">{{ tooltipData.core_narrative }}</div>
      <div v-if="tooltipData.shared_anxieties" class="hull-tooltip-anxieties">
        共同焦慮：{{ tooltipData.shared_anxieties }}
      </div>
      <div class="hull-tooltip-trust">
        群體信任度：{{ (tooltipData.avg_trust * 100).toFixed(0) }}%
      </div>
    </div>
  </div>
</template>

<style scoped>
.graph-canvas-wrapper {
  width: 100%;
  height: 100%;
  position: relative;
}

.graph-canvas {
  width: 100%;
  height: 100%;
  display: block;
}

.empty-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  font-size: 14px;
  pointer-events: none;
}

.hull-overlay {
  position: absolute;
  top: 0;
  left: 0;
  pointer-events: none;
}

/* Hull tooltip */
.hull-tooltip {
  position: absolute;
  z-index: 20;
  max-width: 280px;
  padding: 10px 14px;
  background: var(--glass-bg);
  backdrop-filter: blur(12px);
  border: 1px solid var(--border);
  border-radius: 8px;
  pointer-events: none;
  box-shadow: var(--shadow-md);
}

.hull-tooltip-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}

.hull-cluster-badge {
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
}

.hull-member-count {
  font-size: 11px;
  color: var(--text-muted, #9CA3AF);
}

.hull-tooltip-narrative {
  font-size: 12px;
  color: var(--text-primary, #111827);
  line-height: 1.5;
  margin-bottom: 4px;
}

.hull-tooltip-anxieties {
  font-size: 11px;
  color: var(--accent-red);
  line-height: 1.4;
  margin-bottom: 4px;
}

.hull-tooltip-trust {
  font-size: 11px;
  color: var(--text-muted, #9CA3AF);
}
</style>
