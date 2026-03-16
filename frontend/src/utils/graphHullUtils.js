/**
 * Convex hull utilities for echo chamber rendering.
 * Graham scan, hull expansion, point-in-polygon, centroid, and style helpers.
 */

// Cross product of vectors OA and OB
function _cross(o, a, b) {
  return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
}

/**
 * Graham scan convex hull.
 * @param {number[][]} points - Array of [x, y] pairs
 * @returns {number[][]} Convex hull vertices in order
 */
export function convexHull(points) {
  if (points.length < 3) return [...points]
  const sorted = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1])
  const lower = []
  for (const p of sorted) {
    while (lower.length >= 2 && _cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0)
      lower.pop()
    lower.push(p)
  }
  const upper = []
  for (let i = sorted.length - 1; i >= 0; i--) {
    const p = sorted[i]
    while (upper.length >= 2 && _cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0)
      upper.pop()
    upper.push(p)
  }
  return lower.slice(0, -1).concat(upper.slice(0, -1))
}

/**
 * Deterministic hue from cluster ID string.
 */
export function clusterHue(clusterId) {
  let hash = 0
  const s = String(clusterId)
  for (let i = 0; i < s.length; i++) hash = s.charCodeAt(i) + ((hash << 5) - hash)
  return Math.abs(hash) % 360
}

/**
 * Expand hull outward from centroid by `pad` pixels.
 */
export function expandHull(hull, pad) {
  if (hull.length < 2) return hull
  let cx = 0, cy = 0
  for (const [x, y] of hull) { cx += x; cy += y }
  cx /= hull.length; cy /= hull.length
  return hull.map(([x, y]) => {
    const dx = x - cx, dy = y - cy
    const dist = Math.sqrt(dx * dx + dy * dy) || 1
    return [x + (dx / dist) * pad, y + (dy / dist) * pad]
  })
}

/**
 * Draw a rounded convex hull path on the canvas context.
 */
export function drawRoundedHull(ctx, hull, radius) {
  if (hull.length < 2) return
  if (hull.length === 2) {
    ctx.beginPath()
    ctx.moveTo(hull[0][0], hull[0][1])
    ctx.lineTo(hull[1][0], hull[1][1])
    return
  }
  ctx.beginPath()
  const n = hull.length
  for (let i = 0; i < n; i++) {
    const prev = hull[(i - 1 + n) % n]
    const curr = hull[i]
    const next = hull[(i + 1) % n]
    const v1x = prev[0] - curr[0], v1y = prev[1] - curr[1]
    const v2x = next[0] - curr[0], v2y = next[1] - curr[1]
    const len1 = Math.sqrt(v1x * v1x + v1y * v1y) || 1
    if (i === 0) {
      const mx = curr[0] + (v1x / len1) * radius
      const my = curr[1] + (v1y / len1) * radius
      ctx.moveTo(mx, my)
    }
    const len2 = Math.sqrt(v2x * v2x + v2y * v2y) || 1
    ctx.arcTo(curr[0], curr[1],
      curr[0] + (v2x / len2) * radius,
      curr[1] + (v2y / len2) * radius,
      radius)
  }
  ctx.closePath()
}

/**
 * Ray-casting point-in-polygon test.
 */
export function pointInPolygon(x, y, polygon) {
  let inside = false
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const xi = polygon[i][0], yi = polygon[i][1]
    const xj = polygon[j][0], yj = polygon[j][1]
    if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) {
      inside = !inside
    }
  }
  return inside
}

/**
 * Centroid of a hull (simple average).
 */
export function hullCentroid(hull) {
  let cx = 0, cy = 0
  for (const [x, y] of hull) { cx += x; cy += y }
  return [cx / hull.length, cy / hull.length]
}

/**
 * Hull fill color, optionally polarization-tinted.
 */
export function getHullFillColor(clusterId, hue, polarizationData) {
  if (polarizationData?.cluster_stances) {
    const stance = polarizationData.cluster_stances[String(clusterId)]
    if (stance) {
      const deviation = Math.abs((stance.avg_stance ?? 0.5) - 0.5) * 2
      const polarHue = 120 * (1 - deviation)
      return `hsla(${polarHue}, 65%, 50%, 0.12)`
    }
  }
  return `hsla(${hue}, 65%, 50%, 0.08)`
}

/**
 * Hull stroke color, optionally polarization-tinted.
 */
export function getHullStrokeColor(clusterId, hue, polarizationData) {
  if (polarizationData?.cluster_stances) {
    const stance = polarizationData.cluster_stances[String(clusterId)]
    if (stance) {
      const deviation = Math.abs((stance.avg_stance ?? 0.5) - 0.5) * 2
      const polarHue = 120 * (1 - deviation)
      return `hsla(${polarHue}, 65%, 55%, 0.4)`
    }
  }
  return `hsla(${hue}, 65%, 55%, 0.35)`
}

/**
 * Hull stroke width, optionally thicker for high polarization.
 */
export function getHullStrokeWidth(clusterId, globalScale, polarizationData) {
  if (polarizationData?.cluster_stances) {
    const stance = polarizationData.cluster_stances[String(clusterId)]
    if (stance) {
      const deviation = Math.abs((stance.avg_stance ?? 0.5) - 0.5) * 2
      return (deviation > 0.7 ? 3 : 2) / globalScale
    }
  }
  return 2 / globalScale
}

/**
 * Draw arrowhead at `to` pointing from `from`.
 */
export function drawArrowhead(ctx, from, to, size) {
  const angle = Math.atan2(to[1] - from[1], to[0] - from[0])
  ctx.fillStyle = 'rgba(239, 68, 68, 0.6)'
  ctx.beginPath()
  ctx.moveTo(to[0], to[1])
  ctx.lineTo(to[0] - size * Math.cos(angle - Math.PI / 6), to[1] - size * Math.sin(angle - Math.PI / 6))
  ctx.lineTo(to[0] - size * Math.cos(angle + Math.PI / 6), to[1] - size * Math.sin(angle + Math.PI / 6))
  ctx.closePath()
  ctx.fill()
}
