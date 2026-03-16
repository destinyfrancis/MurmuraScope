/**
 * Thought bubble rendering for the force graph canvas.
 * Bubbles appear above random nodes showing latest post snippets.
 */

function roundRect(ctx, x, y, width, height, radius) {
  ctx.beginPath()
  ctx.moveTo(x + radius, y)
  ctx.lineTo(x + width - radius, y)
  ctx.quadraticCurveTo(x + width, y, x + width, y + radius)
  ctx.lineTo(x + width, y + height - radius)
  ctx.quadraticCurveTo(x + width, y + height, x + width - radius, y + height)
  ctx.lineTo(x + radius, y + height)
  ctx.quadraticCurveTo(x, y + height, x, y + height - radius)
  ctx.lineTo(x, y + radius)
  ctx.quadraticCurveTo(x, y, x + radius, y)
  ctx.closePath()
}

/**
 * Spawn a new thought bubble from a random post + node.
 * @param {object} params
 * @param {Array} params.latestPosts - Available posts
 * @param {object} params.graphData - { nodes: [...] } from force-graph
 * @param {Array} params.currentBubbles - Existing bubble array (immutable read)
 * @returns {Array} New bubbles array (immutable)
 */
export function spawnThoughtBubble({ latestPosts, graphData, currentBubbles }) {
  if (!latestPosts.length || !graphData?.nodes?.length) return currentBubbles
  const post = latestPosts[Math.floor(Math.random() * latestPosts.length)]
  if (!post?.content) return currentBubbles
  const node = graphData.nodes[Math.floor(Math.random() * graphData.nodes.length)]
  if (!node || node.x == null || node.y == null) return currentBubbles
  const text = post.content.length > 20
    ? post.content.slice(0, 20) + '...'
    : post.content
  const updated = [...currentBubbles, {
    nodeId: node.id,
    text,
    x: node.x,
    y: node.y,
    life: 60,
    maxLife: 60,
  }]
  return updated.length > 4 ? updated.slice(-4) : updated
}

/**
 * Draw all active thought bubbles on the canvas, decrementing their life.
 * @param {CanvasRenderingContext2D} ctx
 * @param {number} globalScale
 * @param {Array} bubbles - Mutable array; entries are mutated (life--)
 * @returns {Array} Filtered bubbles with life > 0
 */
export function drawThoughtBubbles(ctx, globalScale, bubbles) {
  const alive = bubbles.filter(b => b.life > 0)
  for (const bubble of alive) {
    bubble.life--
    const alpha = Math.min(1, bubble.life / 12) * (bubble.life / bubble.maxLife)
    const fontSize = Math.max(8, 10 / globalScale)
    ctx.save()
    ctx.font = `${fontSize}px sans-serif`
    const textW = ctx.measureText(bubble.text).width
    const padX = 6 / globalScale
    const padY = 4 / globalScale
    const boxW = textW + padX * 2
    const boxH = fontSize + padY * 2
    const bx = bubble.x - boxW / 2
    const by = bubble.y - (bubble.nodeId ? 18 / globalScale : 0) - boxH - 8 / globalScale
    const radius = 4 / globalScale
    ctx.globalAlpha = alpha * 0.92
    ctx.fillStyle = 'rgba(255, 255, 255, 0.95)'
    roundRect(ctx, bx, by, boxW, boxH, radius)
    ctx.fill()
    ctx.strokeStyle = 'rgba(37, 99, 235, 0.3)'
    ctx.lineWidth = 0.8 / globalScale
    roundRect(ctx, bx, by, boxW, boxH, radius)
    ctx.stroke()
    ctx.fillStyle = '#111827'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(bubble.text, bubble.x, by + boxH / 2)
    ctx.restore()
  }
  return alive
}
