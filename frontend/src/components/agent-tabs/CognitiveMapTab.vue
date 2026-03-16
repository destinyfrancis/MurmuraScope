<script setup>
import { ref, computed, onBeforeUnmount, nextTick } from 'vue'
import { getAgentMemories } from '../../api/simulation.js'
import * as d3 from 'd3'

const props = defineProps({
  sessionId: { type: String, default: null },
  agentId: { type: Number, default: null },
  agentProfile: { type: Object, default: null },
})

const loadingGraph = ref(false)
const cogGraphContainer = ref(null)
const triples = ref([])
let graphSimulation = null

const _PREDICATE_COLORS = {
  worries_about: '#e05252',
  decreases: '#e05252',
  opposes: '#e05252',
  increases: '#4caf7d',
  supports: '#4caf7d',
  observes: '#4f9ce8',
  causes: '#f0a030',
}

function predicateLabel(pred) {
  const map = {
    worries_about: '擔心',
    increases: '上升',
    decreases: '下跌',
    observes: '觀察到',
    causes: '導致',
    supports: '支持',
    opposes: '反對',
  }
  return map[pred] || pred
}

const tripleStats = computed(() => {
  if (!triples.value.length) return null
  const predicates = {}
  for (const t of triples.value) {
    predicates[t.predicate] = (predicates[t.predicate] || 0) + 1
  }
  const uniqueEntities = new Set()
  for (const t of triples.value) {
    uniqueEntities.add(t.subject)
    uniqueEntities.add(t.object)
  }
  return {
    totalTriples: triples.value.length,
    uniqueEntities: uniqueEntities.size,
    predicates,
  }
})

async function loadGraph(existingTriples) {
  if (existingTriples && existingTriples.length > 0) {
    triples.value = existingTriples
    await nextTick()
    renderCognitiveMap(existingTriples)
    return
  }
  if (!props.sessionId || !props.agentId) return
  loadingGraph.value = true
  try {
    const res = await getAgentMemories(props.sessionId, props.agentId, { limit: 200 })
    const payload = res.data?.data || {}
    if (!Array.isArray(payload)) {
      triples.value = payload.triples || []
    }
    await nextTick()
    renderCognitiveMap(triples.value)
  } catch (e) {
    console.error('Failed to load triples for cognitive map', e)
  } finally {
    loadingGraph.value = false
  }
}

function renderCognitiveMap(tripleData) {
  const container = cogGraphContainer.value
  if (!container) return

  if (graphSimulation) {
    graphSimulation.stop()
    graphSimulation = null
  }
  d3.select(container).selectAll('*').remove()

  if (!tripleData || tripleData.length === 0) return

  const nodeSet = new Map()
  const links = []

  for (const t of tripleData) {
    if (!nodeSet.has(t.subject)) {
      nodeSet.set(t.subject, { id: t.subject, count: 0 })
    }
    if (!nodeSet.has(t.object)) {
      nodeSet.set(t.object, { id: t.object, count: 0 })
    }
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
  const width = container.clientWidth || 360
  const height = 300

  const svg = d3.select(container)
    .append('svg')
    .attr('width', width)
    .attr('height', height)
    .attr('viewBox', [0, 0, width, height])

  const defs = svg.append('defs')
  for (const [pred, color] of Object.entries(_PREDICATE_COLORS)) {
    defs.append('marker')
      .attr('id', `arrow-${pred}`)
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 20)
      .attr('refY', 0)
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path')
      .attr('fill', color)
      .attr('d', 'M0,-5L10,0L0,5')
  }
  defs.append('marker')
    .attr('id', 'arrow-default')
    .attr('viewBox', '0 -5 10 10')
    .attr('refX', 20)
    .attr('refY', 0)
    .attr('markerWidth', 6)
    .attr('markerHeight', 6)
    .attr('orient', 'auto')
    .append('path')
    .attr('fill', '#888')
    .attr('d', 'M0,-5L10,0L0,5')

  const simulation = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(links).id(d => d.id).distance(80))
    .force('charge', d3.forceManyBody().strength(-200))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('x', d3.forceX(width / 2).strength(0.06))
    .force('y', d3.forceY(height / 2).strength(0.06))
    .force('collision', d3.forceCollide().radius(20))

  graphSimulation = simulation

  const linkGroup = svg.append('g')
  const link = linkGroup.selectAll('line')
    .data(links)
    .enter().append('line')
    .attr('stroke', d => _PREDICATE_COLORS[d.predicate] || '#888')
    .attr('stroke-width', d => 1 + d.confidence)
    .attr('stroke-opacity', 0.7)
    .attr('marker-end', d => `url(#arrow-${_PREDICATE_COLORS[d.predicate] ? d.predicate : 'default'})`)

  const linkLabel = svg.append('g')
    .selectAll('text')
    .data(links)
    .enter().append('text')
    .attr('font-size', 9)
    .attr('fill', d => _PREDICATE_COLORS[d.predicate] || '#888')
    .attr('text-anchor', 'middle')
    .attr('dy', -4)
    .text(d => predicateLabel(d.predicate))

  const nodeGroup = svg.append('g')
  const node = nodeGroup.selectAll('g')
    .data(nodes)
    .enter().append('g')
    .call(d3.drag()
      .on('start', (event, d) => {
        if (!event.active) simulation.alphaTarget(0.3).restart()
        d.fx = d.x; d.fy = d.y
      })
      .on('drag', (event, d) => {
        d.fx = event.x; d.fy = event.y
      })
      .on('end', (event, d) => {
        if (!event.active) simulation.alphaTarget(0)
        d.fx = null; d.fy = null
      })
    )

  node.append('circle')
    .attr('r', d => 6 + Math.min(d.count, 8))
    .attr('fill', d => {
      const agentName = props.agentProfile?.oasis_username || '我'
      if (d.id === agentName || d.id === '我') return '#4f9ce8'
      return '#6b7280'
    })
    .attr('stroke', '#fff')
    .attr('stroke-width', 1.5)
    .attr('opacity', 0.9)

  node.append('text')
    .attr('dx', 12)
    .attr('dy', 4)
    .attr('font-size', 11)
    .attr('fill', 'var(--text-primary, #111827)')
    .text(d => d.id.length > 12 ? d.id.slice(0, 12) + '...' : d.id)

  node.append('title')
    .text(d => d.id)

  simulation.on('tick', () => {
    const pad = 16
    nodes.forEach(d => {
      d.x = Math.max(pad, Math.min(width - pad, d.x))
      d.y = Math.max(pad, Math.min(height - pad, d.y))
    })

    link
      .attr('x1', d => d.source.x)
      .attr('y1', d => d.source.y)
      .attr('x2', d => d.target.x)
      .attr('y2', d => d.target.y)

    linkLabel
      .attr('x', d => (d.source.x + d.target.x) / 2)
      .attr('y', d => (d.source.y + d.target.y) / 2)

    node.attr('transform', d => `translate(${d.x},${d.y})`)
  })
}

function reset() {
  triples.value = []
  if (graphSimulation) {
    graphSimulation.stop()
    graphSimulation = null
  }
}

onBeforeUnmount(() => {
  if (graphSimulation) {
    graphSimulation.stop()
    graphSimulation = null
  }
})

defineExpose({ loadGraph, reset })
</script>

<template>
  <div class="tab-content cogmap-tab">
    <div v-if="loadingGraph" class="loading-hint">載入認知圖譜中...</div>
    <template v-else>
      <div ref="cogGraphContainer" class="cog-graph-container"></div>
      <div v-if="triples.length === 0" class="empty-hint">尚無知識圖譜數據</div>
      <div v-if="tripleStats" class="cog-stats">
        <span class="stat-item">節點 {{ tripleStats.uniqueEntities }}</span>
        <span class="stat-item">關係 {{ tripleStats.totalTriples }}</span>
        <span
          v-for="(count, pred) in tripleStats.predicates"
          :key="pred"
          class="stat-badge"
          :style="{ color: _PREDICATE_COLORS[pred] || '#888' }"
        >{{ predicateLabel(pred) }} {{ count }}</span>
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

.cogmap-tab {
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.cog-graph-container {
  width: 100%;
  min-height: 300px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.cog-graph-container :deep(svg) {
  display: block;
}

.cog-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 11px;
  color: var(--text-muted);
}

.stat-item {
  background: var(--bg-primary);
  padding: 2px 8px;
  border-radius: 8px;
  border: 1px solid var(--border-color);
}

.stat-badge {
  padding: 2px 8px;
  border-radius: 8px;
  background: var(--bg-secondary);
  font-weight: 600;
}

.loading-hint, .empty-hint {
  text-align: center;
  color: var(--text-muted);
  font-size: 13px;
  padding: 20px 0;
}
</style>
