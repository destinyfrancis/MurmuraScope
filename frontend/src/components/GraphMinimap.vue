<template>
  <div class="graph-minimap" @click="handleClick">
    <canvas ref="minimapCanvas" :width="width" :height="height"></canvas>
    <div class="minimap-label">縮略圖</div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'

const props = defineProps({
  graphInstance: { type: Object, default: null },
  nodes: { type: Array, default: () => [] },
  width: { type: Number, default: 160 },
  height: { type: Number, default: 120 },
})

const minimapCanvas = ref(null)
let intervalId = null

function draw() {
  const canvas = minimapCanvas.value
  if (!canvas || !props.nodes.length) return
  const ctx = canvas.getContext('2d')
  ctx.clearRect(0, 0, props.width, props.height)

  // Background
  ctx.fillStyle = 'rgba(15, 20, 40, 0.9)'
  ctx.fillRect(0, 0, props.width, props.height)

  // Normalize node positions
  const xs = props.nodes.map(n => n.x || 0)
  const ys = props.nodes.map(n => n.y || 0)
  const minX = Math.min(...xs), maxX = Math.max(...xs)
  const minY = Math.min(...ys), maxY = Math.max(...ys)
  const rangeX = maxX - minX || 1
  const rangeY = maxY - minY || 1
  const pad = 8

  props.nodes.forEach(node => {
    const nx = pad + ((node.x || 0) - minX) / rangeX * (props.width - 2 * pad)
    const ny = pad + ((node.y || 0) - minY) / rangeY * (props.height - 2 * pad)
    ctx.beginPath()
    ctx.arc(nx, ny, 2, 0, 2 * Math.PI)
    ctx.fillStyle = node.entity_type === 'person' ? '#e94560'
                  : node.entity_type === 'organization' ? '#4ecca3' : '#a0a0ff'
    ctx.fill()
  })
}

function handleClick(e) {
  if (!props.graphInstance || !props.nodes.length) return
  const rect = minimapCanvas.value.getBoundingClientRect()
  const px = (e.clientX - rect.left) / props.width
  const py = (e.clientY - rect.top) / props.height
  const xs = props.nodes.map(n => n.x || 0)
  const ys = props.nodes.map(n => n.y || 0)
  const minX = Math.min(...xs), maxX = Math.max(...xs)
  const minY = Math.min(...ys), maxY = Math.max(...ys)
  const worldX = minX + px * (maxX - minX)
  const worldY = minY + py * (maxY - minY)
  props.graphInstance.centerAt(worldX, worldY, 300)
}

onMounted(() => {
  intervalId = setInterval(draw, 1500)
  draw()
})

onUnmounted(() => {
  if (intervalId) clearInterval(intervalId)
})

watch(() => props.nodes, draw, { deep: false })
</script>

<style scoped>
.graph-minimap {
  position: absolute;
  bottom: 16px;
  right: 16px;
  border: 1px solid rgba(78, 204, 163, 0.3);
  border-radius: 6px;
  overflow: hidden;
  cursor: pointer;
  background: rgba(15, 20, 40, 0.9);
  z-index: 10;
}
.minimap-label {
  position: absolute;
  top: 2px;
  left: 4px;
  font-size: 9px;
  color: rgba(255, 255, 255, 0.4);
  pointer-events: none;
}
</style>
