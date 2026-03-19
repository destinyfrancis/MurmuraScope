<script setup>
import { ref } from 'vue'

defineProps({
  tippingPoints: { type: Array, default: () => [] },
  // Each item: { id, round_number, kl_divergence, change_direction, affected_factions_json }
})

const expanded = ref(new Set())

function toggle(id) {
  const next = new Set(expanded.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expanded.value = next
}

const COLOUR = {
  polarize: 'var(--accent-danger)',
  split:    'var(--accent-warn)',
  converge: 'var(--accent)',
}
function dotColour(dir) { return COLOUR[dir] ?? 'var(--text-muted)' }

function parseFactions(json) {
  try { return JSON.parse(json) } catch { return [] }
}
</script>

<template>
  <div class="tp-tab">
    <div v-if="!tippingPoints.length" class="empty">
      臨界點尚未偵測到
    </div>
    <div v-else class="timeline">
      <div
        v-for="tp in [...tippingPoints].reverse()"
        :key="tp.id"
        class="tp-row"
        @click="toggle(tp.id)"
      >
        <div class="tp-main">
          <span class="tp-dot" :style="{ background: dotColour(tp.change_direction) }" />
          <span class="tp-round">R{{ tp.round_number }}</span>
          <span class="tp-dir">{{ tp.change_direction }}</span>
          <span class="tp-kl-badge">KL {{ tp.kl_divergence?.toFixed(3) }}</span>
          <span class="tp-expand">{{ expanded.has(tp.id) ? '▲' : '▼' }}</span>
        </div>
        <div v-if="expanded.has(tp.id)" class="tp-detail">
          <div class="tp-factions">
            <span
              v-for="fid in parseFactions(tp.affected_factions_json)"
              :key="fid"
              class="faction-chip"
            >{{ fid }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tp-tab { flex: 1; overflow-y: auto; padding: 8px 10px; }
.empty { color: var(--text-muted); font-size: 12px; padding: 20px 0; text-align: center; }
.timeline { display: flex; flex-direction: column; gap: 4px; }
.tp-row {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 5px;
  cursor: pointer;
}
.tp-main {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 7px 9px;
}
.tp-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.tp-round { font-family: var(--font-mono); font-size: 10px; font-weight: 700; color: var(--text-primary); }
.tp-dir { font-size: 10px; color: var(--text-primary); flex: 1; }
.tp-kl-badge {
  font-family: var(--font-mono);
  font-size: 8px;
  padding: 1px 5px;
  border-radius: 3px;
  background: var(--bg-app);
  border: 1px solid var(--border);
  color: var(--text-muted);
}
.tp-expand { font-size: 8px; color: var(--text-muted); }
.tp-detail { padding: 0 9px 7px; }
.tp-factions { display: flex; flex-wrap: wrap; gap: 4px; }
.faction-chip {
  font-family: var(--font-mono);
  font-size: 8px;
  padding: 1px 5px;
  background: var(--bg-app);
  border: 1px solid var(--border);
  border-radius: 2px;
  color: var(--text-muted);
}
</style>
