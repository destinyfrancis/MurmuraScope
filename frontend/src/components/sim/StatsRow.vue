<script setup>
defineProps({
  agentCount:    { type: Number, default: 0 },
  currentRound:  { type: Number, default: 0 },
  totalRounds:   { type: Number, default: 0 },
  factionCount:  { type: Number, default: 0 },
  tippingCount:  { type: Number, default: 0 },
})
</script>

<template>
  <div class="stats-row">
    <div class="stat-cell">
      <div class="stat-n">{{ agentCount }}</div>
      <div class="stat-l">AGENTS</div>
    </div>
    <div class="stat-cell">
      <div class="stat-n">{{ currentRound }}<span class="stat-denom">/{{ totalRounds }}</span></div>
      <div class="stat-l">ROUND</div>
    </div>
    <div class="stat-cell">
      <div class="stat-n green">{{ factionCount }}</div>
      <div class="stat-l">FACTIONS</div>
    </div>
    <div class="stat-cell">
      <div class="stat-n" :class="tippingCount > 0 ? 'red' : 'muted'">{{ tippingCount }}</div>
      <div class="stat-l">TIPPING PTS</div>
    </div>
  </div>
</template>

<style scoped>
.stats-row {
  display: flex;
  border-bottom: 1px solid var(--border);
  background: var(--bg-card);
  flex-shrink: 0;
}
.stat-cell {
  flex: 1;
  padding: 8px 10px;
  border-right: 1px solid var(--border);
}
.stat-cell:last-child { border-right: none; }
.stat-n {
  font-family: var(--font-mono);
  font-size: 17px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.1;
}
.stat-denom { font-size: 12px; color: var(--text-muted); }
.stat-n.green { color: var(--accent); }
.stat-n.red   { color: var(--accent-danger); }
.stat-n.muted { color: var(--text-muted); }
.stat-l {
  font-family: var(--font-mono);
  font-size: 7.5px;
  color: var(--text-muted);
  letter-spacing: .08em;
  margin-top: 2px;
}
</style>
