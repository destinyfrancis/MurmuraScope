<script setup>
import { ref, watch, onUnmounted, nextTick } from 'vue'
import * as d3 from 'd3'
import { getSessionActions } from '../api/simulation.js'
import { factionColour } from '../utils/colours.js'

const props = defineProps({
  sessionId: { type: String, default: '' },
})

const svgRef = ref(null)
const hasEdges = ref(true)
const loading = ref(false)

// Single references to D3 objects — cleared on each re-render
let simulation = null
let tooltip = null

function teardown() {
  if (svgRef.value) d3.select(svgRef.value).on('.zoom', null)
  if (simulation) { simulation.stop(); simulation = null }
  if (tooltip) { tooltip.remove(); tooltip = null }
}

async function loadData() {
  if (!props.sessionId) return
  teardown()  // Clean up previous render before starting new one
  loading.value = true
  try {
    const res = await getSessionActions(props.sessionId, { limit: 500 })
    const actions = res.data?.data || []

    const agentPostCount = {}
    const edgeCounts = {}
    for (const a of actions) {
      const from = a.oasis_username
      const to = a.target_agent_username
      if (!from) continue
      agentPostCount[from] = (agentPostCount[from] || 0) + 1
      if (to && to !== from) {
        const key = `${from}→${to}`
        edgeCounts[key] = (edgeCounts[key] || 0) + 1
      }
    }

    const nodes = Object.keys(agentPostCount).map((id, i) => ({
      id,
      posts: agentPostCount[id] || 1,
      colour: factionColour(i),
    }))
    const edges = Object.entries(edgeCounts).map(([key, count]) => {
      const [from, to] = key.split('→')
      return { source: from, target: to, count }
    })

    hasEdges.value = edges.length > 0
    await nextTick()
    renderGraph(nodes, edges)
  } catch (e) {
    console.warn('InteractionNetwork load failed:', e)
    hasEdges.value = false
  } finally {
    loading.value = false
  }
}

function renderGraph(nodes, edges) {
  const el = svgRef.value
  if (!el) return
  d3.select(el).selectAll('*').remove()

  const W = el.clientWidth || 500
  const H = el.clientHeight || 400

  const svg = d3.select(el)
    .attr('width', W)
    .attr('height', H)

  const g = svg.append('g')

  svg.call(d3.zoom().scaleExtent([0.3, 4]).on('zoom', e => g.attr('transform', e.transform)))

  simulation = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(edges).id(d => d.id).distance(60))
    .force('charge', d3.forceManyBody().strength(-80))
    .force('center', d3.forceCenter(W / 2, H / 2))
    .force('collision', d3.forceCollide().radius(d => Math.sqrt(d.posts) * 4 + 4))

  const link = g.append('g').selectAll('line')
    .data(edges)
    .join('line')
    .attr('stroke', '#334155')
    .attr('stroke-width', d => Math.min(Math.sqrt(d.count) + 0.5, 4))
    .attr('stroke-opacity', 0.6)

  const node = g.append('g').selectAll('circle')
    .data(nodes)
    .join('circle')
    .attr('r', d => Math.sqrt(d.posts) * 3 + 3)
    .attr('fill', d => d.colour)
    .attr('stroke', '#0f172a')
    .attr('stroke-width', 1.5)
    .call(d3.drag()
      .on('start', (e, d) => { if (!e.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y })
      .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y })
      .on('end', (e, d) => { if (!e.active) simulation.alphaTarget(0); d.fx = null; d.fy = null })
    )

  // Single tooltip — created once per renderGraph call; torn down in teardown()
  tooltip = d3.select('body').append('div')
    .attr('class', 'd3-tooltip-network')
    .style('position', 'fixed')
    .style('background', '#1e293b')
    .style('color', '#e2e8f0')
    .style('padding', '6px 10px')
    .style('border-radius', '6px')
    .style('font-size', '11px')
    .style('pointer-events', 'none')
    .style('opacity', 0)
    .style('z-index', 999)

  node
    .on('mouseover', (e, d) => {
      tooltip.transition().duration(100).style('opacity', 0.95)
      tooltip.html(`<b>${d.id}</b><br/>${d.posts} 貼文`)
        .style('left', (e.clientX + 12) + 'px')
        .style('top', (e.clientY - 6) + 'px')
    })
    .on('mousemove', (e) => {
      tooltip.style('left', (e.clientX + 12) + 'px').style('top', (e.clientY - 6) + 'px')
    })
    .on('mouseout', () => tooltip.transition().duration(200).style('opacity', 0))

  simulation.on('tick', () => {
    link
      .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
      .attr('x2', d => d.target.x).attr('y2', d => d.target.y)
    node.attr('cx', d => d.x).attr('cy', d => d.y)
  })
}

watch(() => props.sessionId, (id) => { if (id) loadData() }, { immediate: true })

onUnmounted(teardown)
</script>

<template>
  <div class="interaction-network">
    <div v-if="loading" class="net-loading">載入互動網絡...</div>
    <div v-else-if="!hasEdges" class="net-fallback">
      尚無 Agent 互動回覆數據。<br/>互動連線將在模擬產生回覆後顯示。
    </div>
    <svg v-else ref="svgRef" class="net-svg" />
  </div>
</template>

<style scoped>
.interaction-network {
  width: 100%;
  height: 100%;
  position: relative;
  background: var(--bg-card, #1e293b);
  border-radius: 6px;
  overflow: hidden;
}

.net-loading,
.net-fallback {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: #64748b;
  text-align: center;
  padding: 20px;
}

.net-svg {
  width: 100%;
  height: 100%;
}
</style>
