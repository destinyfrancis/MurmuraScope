<script setup>
import { ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import * as d3 from 'd3'
import { getAgentTriples } from '../api/simulation.js'

const props = defineProps({
  sessionId: { type: String, required: true },
  agentId: { type: Number, required: true },
  agentUsername: { type: String, default: '' },
  refreshTrigger: { type: Number, default: 0 },
})

const emit = defineEmits(['close'])

const container = ref(null)
let simulation = null
let refreshDebounce = null

const _PREDICATE_COLORS = {
  worries_about: '#e05252',
  decreases: '#e05252',
  opposes: '#e05252',
  increases: '#4caf7d',
  supports: '#4caf7d',
  observes: '#4f9ce8',
  causes: '#f0a030',
}

// --- Dragging logic ---
const dragging = ref(false)
const pos = ref({ x: 20, y: 100 })
let dragStart = { mx: 0, my: 0, px: 0, py: 0 }

function onHeaderDown(e) {
  dragging.value = true
  dragStart = { mx: e.clientX, my: e.clientY, px: pos.value.x, py: pos.value.y }
  window.addEventListener('mousemove', onMouseMove)
  window.addEventListener('mouseup', onMouseUp)
}

function onMouseMove(e) {
  if (!dragging.value) return
  pos.value = {
    x: dragStart.px + (e.clientX - dragStart.mx),
    y: dragStart.py + (e.clientY - dragStart.my),
  }
}

function onMouseUp() {
  dragging.value = false
  window.removeEventListener('mousemove', onMouseMove)
  window.removeEventListener('mouseup', onMouseUp)
}

// --- Render ---
async function loadAndRender() {
  if (!props.sessionId || !props.agentId) return
  try {
    const res = await getAgentTriples(props.sessionId, props.agentId)
    const tripleData = res.data?.data || []
    await nextTick()
    renderGraph(tripleData)
  } catch (e) {
    console.warn('MiniCognitiveMap load failed', e)
  }
}

function renderGraph(tripleData) {
  const el = container.value
  if (!el) return

  if (simulation) {
    simulation.stop()
    simulation = null
  }
  d3.select(el).selectAll('*').remove()

  if (!tripleData || tripleData.length === 0) return

  const nodeSet = new Map()
  const links = []

  for (const t of tripleData) {
    if (!nodeSet.has(t.subject)) nodeSet.set(t.subject, { id: t.subject, count: 0 })
    if (!nodeSet.has(t.object)) nodeSet.set(t.object, { id: t.object, count: 0 })
    nodeSet.get(t.subject).count++
    nodeSet.get(t.object).count++
    links.push({
      source: t.subject,
      target: t.object,
      predicate: t.predicate,
      confidence: t.confidence || 0.85,
    })
  }

  const nodes = Array.from(nodeSet.values())
  const width = 280
  const height = 230

  const svg = d3.select(el)
    .append('svg')
    .attr('width', width)
    .attr('height', height)
    .attr('viewBox', [0, 0, width, height])

  const sim = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(links).id(d => d.id).distance(50).strength(0.6))
    .force('charge', d3.forceManyBody().strength(-120))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('x', d3.forceX(width / 2).strength(0.08))
    .force('y', d3.forceY(height / 2).strength(0.08))
    .force('collision', d3.forceCollide().radius(12))

  simulation = sim

  const link = svg.append('g')
    .selectAll('line')
    .data(links)
    .enter().append('line')
    .attr('stroke', d => _PREDICATE_COLORS[d.predicate] || '#666')
    .attr('stroke-width', 1)
    .attr('stroke-opacity', 0.6)

  const node = svg.append('g')
    .selectAll('g')
    .data(nodes)
    .enter().append('g')
    .call(d3.drag()
      .on('start', (event, d) => {
        if (!event.active) sim.alphaTarget(0.3).restart()
        d.fx = d.x; d.fy = d.y
      })
      .on('drag', (event, d) => {
        d.fx = event.x; d.fy = event.y
      })
      .on('end', (event, d) => {
        if (!event.active) sim.alphaTarget(0)
        d.fx = null; d.fy = null
      })
    )

  node.append('circle')
    .attr('r', d => 3 + Math.min(d.count, 6))
    .attr('fill', d => {
      if (d.id === props.agentUsername || d.id === '我') return '#4f9ce8'
      return '#6b7280'
    })
    .attr('stroke', '#fff')
    .attr('stroke-width', 0.8)

  node.append('text')
    .attr('dx', 8)
    .attr('dy', 3)
    .attr('font-size', 8)
    .attr('fill', '#4B5563')
    .text(d => d.id.length > 8 ? d.id.slice(0, 8) + '..' : d.id)

  node.append('title').text(d => d.id)

  sim.on('tick', () => {
    const pad = 10
    nodes.forEach(d => {
      d.x = Math.max(pad, Math.min(width - pad, d.x))
      d.y = Math.max(pad, Math.min(height - pad, d.y))
    })
    link
      .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
      .attr('x2', d => d.target.x).attr('y2', d => d.target.y)
    node.attr('transform', d => `translate(${d.x},${d.y})`)
  })
}

watch(() => props.agentId, () => loadAndRender())

watch(() => props.refreshTrigger, () => {
  if (refreshDebounce) clearTimeout(refreshDebounce)
  refreshDebounce = setTimeout(() => loadAndRender(), 3000)
})

onMounted(() => loadAndRender())

onBeforeUnmount(() => {
  if (simulation) { simulation.stop(); simulation = null }
  if (refreshDebounce) clearTimeout(refreshDebounce)
  window.removeEventListener('mousemove', onMouseMove)
  window.removeEventListener('mouseup', onMouseUp)
})
</script>

<template>
  <div
    class="mini-cogmap"
    :style="{ left: pos.x + 'px', top: pos.y + 'px' }"
  >
    <div class="mini-header" @mousedown.prevent="onHeaderDown">
      <span class="mini-title">{{ agentUsername || 'Agent' }}</span>
      <button class="mini-close" @click="emit('close')">&#10005;</button>
    </div>
    <div ref="container" class="mini-canvas">
      <div v-if="!container?.querySelector?.('svg')" class="mini-empty">
        暫無認知數據
      </div>
    </div>
  </div>
</template>

<style scoped>
.mini-cogmap {
  position: absolute;
  width: 300px;
  height: 280px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  z-index: 40;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: var(--shadow-md);
}

.mini-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 10px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-color);
  cursor: move;
  user-select: none;
  flex-shrink: 0;
}

.mini-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--accent-blue);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mini-close {
  background: none;
  border: none;
  color: var(--text-muted);
  font-size: 12px;
  cursor: pointer;
  padding: 2px 4px;
}

.mini-close:hover {
  color: var(--text-primary);
}

.mini-canvas {
  flex: 1;
  overflow: hidden;
  position: relative;
}

.mini-canvas :deep(svg) {
  display: block;
}

.mini-canvas :deep(circle) {
  filter: none;
}

.mini-canvas :deep(line) {
  filter: none;
}

.mini-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-muted);
  font-size: 12px;
}
</style>
