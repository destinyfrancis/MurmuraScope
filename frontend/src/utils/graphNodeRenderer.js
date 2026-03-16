/**
 * Node rendering for the force-graph canvas.
 * Handles type colors, LOD levels, highlights, KOL halos, and label drawing.
 */

import { drawContagionRipples, drawContagionBorder } from './graphContagionRenderer.js'

// ---------------------------------------------------------------------------
// Type color palette
// ---------------------------------------------------------------------------
const typeColors = {
  person: '#2563EB',
  organization: '#7C3AED',
  policy: '#D97706',
  economic: '#059669',
  social: '#0891B2',
  event: '#DC2626',
  location: '#F59E0B',
  default: '#6B7280',
}

/**
 * Get the fill color for a node based on its type/category.
 */
export function getNodeColor(node) {
  const type = (node.type || node.category || 'default').toLowerCase()
  return typeColors[type] || typeColors.default
}

/**
 * Get the normalized type string for a node.
 */
export function getNodeType(node) {
  return (node.type || node.category || 'default').toLowerCase()
}

// ---------------------------------------------------------------------------
// Link styling helpers
// ---------------------------------------------------------------------------

/**
 * Check if a link is a hostile cross-cluster edge.
 */
export function isHostileCrossCluster(link, showEchoChambers) {
  if (!showEchoChambers) return false
  const sc = link.source?.cluster_id ?? link.source
  const tc = link.target?.cluster_id ?? link.target
  if (sc === undefined || tc === undefined) return false
  return sc !== tc && (link.trust_score || 0) < 0
}

/**
 * Get the color for a link.
 */
export function getLinkColor(link, showEchoChambers) {
  return isHostileCrossCluster(link, showEchoChambers) ? '#ef4444' : '#D1D5DB'
}

/**
 * Get the width for a link.
 */
export function getLinkWidth(link, showEchoChambers) {
  return isHostileCrossCluster(link, showEchoChambers) ? 3 : (link.weight || 1)
}

/**
 * Get the dash pattern for a link (array or null).
 */
export function getLinkDash(link, showEchoChambers) {
  return isHostileCrossCluster(link, showEchoChambers) ? [6, 3] : null
}

// ---------------------------------------------------------------------------
// Main node renderer
// ---------------------------------------------------------------------------

/**
 * Draw a single node on the canvas.
 * @param {object} node - Graph node
 * @param {CanvasRenderingContext2D} ctx
 * @param {number} globalScale - Current zoom level
 * @param {object} opts
 * @param {Set|null} opts.activeTypes - Set of active type strings, or null
 * @param {Set} opts.highlightedSet - Set of highlighted node IDs
 */
export function drawNode(node, ctx, globalScale, opts) {
  const { activeTypes, highlightedSet } = opts

  // LOD Level 1: very zoomed out - just dots
  if (globalScale < 0.3) {
    ctx.beginPath()
    ctx.arc(node.x, node.y, 3, 0, 2 * Math.PI)
    ctx.fillStyle = getNodeColor(node)
    ctx.fill()
    return
  }

  // LOD Level 2: medium zoom - no labels, no glow
  const skipLabelsAndGlow = globalScale < 0.6

  // Apply activeTypes filter -- dim nodes not in the active set
  if (activeTypes && activeTypes.size > 0) {
    const type = getNodeType(node)
    if (!activeTypes.has(type)) {
      ctx.globalAlpha = 0.1
    }
  }

  const label = node.label || node.name || String(node.id)
  const r = node.size || 10
  const color = getNodeColor(node)
  const isHighlighted = highlightedSet.has(node.id)

  // Contagion ripples (behind node body)
  if (node.contagion_active) {
    drawContagionRipples(ctx, node, globalScale)
  }

  // Highlight halo
  if (isHighlighted) {
    ctx.beginPath()
    ctx.arc(node.x, node.y, r + 4, 0, 2 * Math.PI)
    ctx.fillStyle = 'rgba(251, 191, 36, 0.35)'
    ctx.fill()
    ctx.strokeStyle = '#fbbf24'
    ctx.lineWidth = 2
    ctx.stroke()
  }

  // KOL gold halo (trust_score >= 0.7)
  const isTrustedKOL = (node.trust_score || 0) >= 0.7
  if (isTrustedKOL && !skipLabelsAndGlow) {
    ctx.save()
    ctx.strokeStyle = '#fbbf24'
    ctx.shadowColor = '#fbbf24'
    ctx.shadowBlur = 16
    ctx.lineWidth = 2 / globalScale
    ctx.beginPath()
    ctx.arc(node.x, node.y, r + 4 / globalScale, 0, 2 * Math.PI)
    ctx.stroke()
    ctx.restore()
  }

  // Node body with subtle shadow
  ctx.save()
  if (!skipLabelsAndGlow) {
    ctx.shadowColor = 'rgba(0, 0, 0, 0.15)'
    ctx.shadowBlur = 4 * globalScale
    ctx.shadowOffsetX = 0
    ctx.shadowOffsetY = 0
  }
  ctx.beginPath()
  ctx.arc(node.x, node.y, r, 0, 2 * Math.PI)
  ctx.fillStyle = color
  ctx.fill()
  ctx.restore()

  // Node border
  ctx.beginPath()
  ctx.arc(node.x, node.y, r, 0, 2 * Math.PI)
  ctx.strokeStyle = isHighlighted ? '#fbbf24' : '#D1D5DB'
  ctx.lineWidth = isHighlighted ? 2.5 : 1.5
  ctx.stroke()

  // Contagion border ring (on top of node)
  if (node.contagion_active) {
    drawContagionBorder(ctx, node, globalScale)
  }

  // Label
  if (!skipLabelsAndGlow) {
    const fontSize = Math.max(8, 11 / globalScale)
    ctx.font = `${fontSize}px sans-serif`
    ctx.fillStyle = '#111827'
    ctx.textAlign = 'left'
    ctx.textBaseline = 'middle'
    ctx.fillText(label, node.x + r + 3, node.y)
  }

  // Restore alpha after potential dimming
  ctx.globalAlpha = 1.0
}
