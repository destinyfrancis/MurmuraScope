<script setup>
import { computed } from 'vue'

const props = defineProps({
  snapshots: { type: Array, default: () => [] },
})

const FACTION_COLOURS = ['#059669','#3B82F6','#F59E0B','#7C3AED','#DC143C','#EC4899','#14B8A6']

function colourFor(idx) {
  return FACTION_COLOURS[idx % FACTION_COLOURS.length]
}

const latestSnapshot = computed(() => {
  if (!props.snapshots.length) return null
  return props.snapshots[props.snapshots.length - 1]
})

const factions = computed(() => {
  if (!latestSnapshot.value) return []
  try {
    return JSON.parse(latestSnapshot.value.factions_json)
  } catch {
    return []
  }
})

// For sparklines: member count of each faction across rounds
const sparkData = computed(() => {
  const byFaction = {}
  for (const snap of props.snapshots) {
    let parsed = []
    try { parsed = JSON.parse(snap.factions_json) } catch { continue }
    for (const f of parsed) {
      if (!byFaction[f.faction_id]) byFaction[f.faction_id] = []
      byFaction[f.faction_id].push(f.member_agent_ids.length)
    }
  }
  return byFaction
})

function dominantBelief(belief_center) {
  if (!belief_center || !Object.keys(belief_center).length) return { label: '—', value: 0 }
  const [label, value] = Object.entries(belief_center).sort((a, b) => b[1] - a[1])[0]
  return { label, value }
}

function sparklinePath(counts) {
  if (counts.length < 2) return ''
  const W = 60, H = 18
  const max = Math.max(...counts, 1)
  const pts = counts.map((c, i) => {
    const x = (i / (counts.length - 1)) * W
    const y = H - (c / max) * H
    return `${x},${y}`
  })
  return `M${pts.join(' L')}`
}
</script>

<template>
  <div class="faction-tab">
    <div v-if="!factions.length" class="empty">
      <span>派系尚未生成（需 3 輪後）</span>
    </div>
    <template v-else>
      <!-- Summary metrics -->
      <div class="meta-row" v-if="latestSnapshot">
        <span class="meta-badge">
          modularity {{ latestSnapshot.modularity_score?.toFixed(2) }}
        </span>
        <span class="meta-badge danger">
          hostility {{ latestSnapshot.inter_faction_hostility?.toFixed(2) }}
        </span>
      </div>

      <!-- Faction cards -->
      <div class="faction-list">
        <div
          v-for="(f, idx) in factions"
          :key="f.faction_id"
          class="faction-card"
        >
          <div class="fc-header">
            <span class="fc-dot" :style="{ background: colourFor(idx) }" />
            <span class="fc-name">{{ f.faction_id.replace('faction_', 'Faction ') }}</span>
            <span class="fc-count">{{ f.member_agent_ids.length }} agents</span>
          </div>
          <div class="fc-belief-row">
            <span class="fc-belief-label">{{ dominantBelief(f.belief_center).label }}</span>
            <div class="fc-bar-bg">
              <div
                class="fc-bar-fill"
                :style="{
                  width: (dominantBelief(f.belief_center).value * 100).toFixed(0) + '%',
                  background: colourFor(idx),
                }"
              />
            </div>
            <span class="fc-belief-val">
              {{ (dominantBelief(f.belief_center).value * 100).toFixed(0) }}%
            </span>
          </div>
          <!-- Sparkline -->
          <svg v-if="sparkData[f.faction_id]?.length > 1" width="60" height="18" class="sparkline">
            <path :d="sparklinePath(sparkData[f.faction_id])" :stroke="colourFor(idx)" stroke-width="1.5" fill="none" />
          </svg>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.faction-tab { display: flex; flex-direction: column; gap: 8px; padding: 10px; overflow-y: auto; flex: 1; }
.empty { color: var(--text-muted); font-size: 12px; padding: 20px 0; text-align: center; }
.meta-row { display: flex; gap: 6px; }
.meta-badge {
  font-family: var(--font-mono);
  font-size: 8px;
  padding: 2px 6px;
  border-radius: 3px;
  background: var(--bg-app);
  border: 1px solid var(--border);
  color: var(--text-muted);
}
.meta-badge.danger { color: var(--accent-danger); border-color: var(--accent-danger); }
.faction-list { display: flex; flex-direction: column; gap: 6px; }
.faction-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 10px;
}
.fc-header { display: flex; align-items: center; gap: 6px; margin-bottom: 5px; }
.fc-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.fc-name { font-size: 11px; font-weight: 600; color: var(--text-primary); }
.fc-count { font-family: var(--font-mono); font-size: 8px; color: var(--text-muted); margin-left: auto; }
.fc-belief-row { display: flex; align-items: center; gap: 6px; }
.fc-belief-label { font-family: var(--font-mono); font-size: 8px; color: var(--text-muted); min-width: 60px; }
.fc-bar-bg { flex: 1; height: 4px; background: var(--border); border-radius: 2px; overflow: hidden; }
.fc-bar-fill { height: 100%; border-radius: 2px; transition: width .4s; }
.fc-belief-val { font-family: var(--font-mono); font-size: 8px; color: var(--text-muted); min-width: 28px; text-align: right; }
.sparkline { margin-top: 4px; display: block; }
</style>
