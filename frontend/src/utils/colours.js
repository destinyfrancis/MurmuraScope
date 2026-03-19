export const FACTION_PALETTE = [
  '#FF6B35', '#4ECDC4', '#45B7D1', '#96CEB4',
  '#FFEAA7', '#DDA0DD', '#98D8C8', '#F7DC6F',
]

/**
 * Get a stable colour for a faction/cluster by its 0-based index.
 */
export function factionColour(index) {
  return FACTION_PALETTE[Math.abs(index ?? 0) % FACTION_PALETTE.length]
}
