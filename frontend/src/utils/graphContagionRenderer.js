/**
 * Contagion ripple animation rendering for nodes with active social contagion.
 */

/**
 * Draw 3-layer expanding ripple rings around a contagion-active node.
 * @param {CanvasRenderingContext2D} ctx
 * @param {object} node - Graph node with x, y, size
 * @param {number} globalScale - Current zoom level
 */
export function drawContagionRipples(ctx, node, globalScale) {
  const r = node.size || 10
  const now = Date.now()
  for (let i = 0; i < 3; i++) {
    const phase = ((now / 1500) + i * 0.33) % 1
    const rippleR = r + 4 + phase * 28
    const alpha = (1 - phase) * 0.5
    ctx.beginPath()
    ctx.arc(node.x, node.y, rippleR, 0, 2 * Math.PI)
    ctx.strokeStyle = `rgba(239, 68, 68, ${alpha})`
    ctx.lineWidth = 2.5 / globalScale
    ctx.stroke()
  }
}

/**
 * Draw a solid contagion ring around the node body (after main circle).
 * @param {CanvasRenderingContext2D} ctx
 * @param {object} node - Graph node with x, y, size
 * @param {number} globalScale - Current zoom level
 */
export function drawContagionBorder(ctx, node, globalScale) {
  const r = node.size || 10
  ctx.beginPath()
  ctx.arc(node.x, node.y, r + 2, 0, 2 * Math.PI)
  ctx.strokeStyle = 'rgba(239, 68, 68, 0.6)'
  ctx.lineWidth = 1.5 / globalScale
  ctx.stroke()
}

/**
 * Manage the ripple animation frame loop.
 * Returns start/stop/update helpers and holds mutable state.
 */
export function createRippleLoop(getGraphInstance) {
  let animationFrame = null
  let hasContagionNodes = false

  function start() {
    if (animationFrame) return
    function tick() {
      const inst = getGraphInstance()
      if (inst && hasContagionNodes) inst.refresh()
      animationFrame = requestAnimationFrame(tick)
    }
    animationFrame = requestAnimationFrame(tick)
  }

  function stop() {
    if (animationFrame) {
      cancelAnimationFrame(animationFrame)
      animationFrame = null
    }
  }

  function update(nodes) {
    hasContagionNodes = nodes.some(n => n.contagion_active)
    if (hasContagionNodes) start()
    else stop()
  }

  return { start, stop, update }
}
