<script setup>
import { ref, onMounted, onUnmounted } from 'vue'

const flockCanvas = ref(null)
let flockCtx = null
let flockAnimId = null
let boids = []

function initBoids() {
  boids = Array.from({ length: 50 }, () => ({
    x: Math.random() * 600,
    y: Math.random() * 400,
    vx: (Math.random() - 0.5) * 2,
    vy: (Math.random() - 0.5) * 2,
  }))
}

function updateBoids() {
  const w = 600, h = 400
  for (const b of boids) {
    let sx = 0, sy = 0, cx = 0, cy = 0, ax = 0, ay = 0, n = 0
    for (const o of boids) {
      if (o === b) continue
      const dx = o.x - b.x, dy = o.y - b.y
      const dist = Math.sqrt(dx * dx + dy * dy)
      if (dist > 80) continue
      n++
      if (dist < 20 && dist > 0) { sx -= dx / dist; sy -= dy / dist }
      ax += o.vx; ay += o.vy
      cx += o.x; cy += o.y
    }
    if (n > 0) {
      ax = ax / n - b.vx; ay = ay / n - b.vy
      cx = cx / n - b.x; cy = cy / n - b.y
      b.vx += sx * 0.05 + ax * 0.05 + cx * 0.005
      b.vy += sy * 0.05 + ay * 0.05 + cy * 0.005
    }
    const speed = Math.sqrt(b.vx * b.vx + b.vy * b.vy)
    if (speed > 2) { b.vx = (b.vx / speed) * 2; b.vy = (b.vy / speed) * 2 }
    b.x = (b.x + b.vx + w) % w
    b.y = (b.y + b.vy + h) % h
  }
}

function drawBoids() {
  if (!flockCtx) return
  flockCtx.clearRect(0, 0, 600, 400)
  flockCtx.fillStyle = '#F9FAFB'
  flockCtx.fillRect(0, 0, 600, 400)
  for (const b of boids) {
    const angle = Math.atan2(b.vy, b.vx)
    flockCtx.save()
    flockCtx.translate(b.x, b.y)
    flockCtx.rotate(angle)
    flockCtx.fillStyle = '#2563EB'
    flockCtx.beginPath()
    flockCtx.moveTo(6, 0)
    flockCtx.lineTo(-3, -3)
    flockCtx.lineTo(-3, 3)
    flockCtx.closePath()
    flockCtx.fill()
    flockCtx.restore()
  }
  updateBoids()
  flockAnimId = requestAnimationFrame(drawBoids)
}

function startFlock() {
  if (!flockCanvas.value) return
  flockCtx = flockCanvas.value.getContext('2d')
  initBoids()
  drawBoids()
}

function stopFlock() {
  if (flockAnimId) cancelAnimationFrame(flockAnimId)
  flockAnimId = null
}

onMounted(() => {
  setTimeout(startFlock, 100)
})

onUnmounted(stopFlock)
</script>

<template>
  <div class="lesson-content">
    <div class="lesson-text">
      <p>下面每隻「鳥」只遵守 3 條簡單規則：</p>
      <ol>
        <li><strong>分離</strong> — 唔好撞到隔籬</li>
        <li><strong>對齊</strong> — 跟住附近嘅方向飛</li>
        <li><strong>凝聚</strong> — 保持喺群體中心附近</li>
      </ol>
      <p>冇任何一隻鳥知道「群體隊形」嘅概念 — 但隊形自然湧現。呢個就係 <strong>emergence（湧現）</strong>。</p>
    </div>
    <div class="flock-container glass-panel">
      <canvas ref="flockCanvas" width="600" height="400" class="flock-canvas" />
    </div>
    <div class="lesson-text">
      <p>MurmuraScope 同理 — 每個代理人只按自己嘅性格同記憶做決策，但整體會湧現出可預測嘅社會趨勢。</p>
    </div>
  </div>
</template>

<style scoped>
.lesson-content {
  animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

.lesson-text {
  margin: 16px 0;
  line-height: 1.8;
  color: var(--text-secondary);
  font-size: 15px;
}

.lesson-text strong {
  color: var(--text-primary);
}

.lesson-text ol {
  padding-left: 20px;
  margin: 8px 0;
}

.lesson-text li {
  margin-bottom: 4px;
}

.flock-container {
  padding: 0;
  overflow: hidden;
  margin: 16px 0;
}

.flock-canvas {
  width: 100%;
  height: auto;
  display: block;
}
</style>
