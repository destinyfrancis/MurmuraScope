<script setup>
defineProps({
  tippingPoint: {
    type: Object,
    default: null,
    // { kl_divergence, change_direction, round_number }
  },
})

const DIRECTION_COLOUR = {
  polarize: 'var(--accent-danger)',
  split:    'var(--accent-warn)',
  converge: 'var(--accent)',
}

function colour(dir) {
  return DIRECTION_COLOUR[dir] ?? 'var(--text-muted)'
}
</script>

<template>
  <div class="tstrip">
    <template v-if="tippingPoint">
      <span
        class="tp-badge"
        :style="{ background: colour(tippingPoint.change_direction), color: '#fff' }"
      >
        {{ tippingPoint.change_direction?.toUpperCase() }}
      </span>
      <span class="tp-text">
        R{{ tippingPoint.round_number }} — tipping point detected
      </span>
      <span class="tp-kl">KL: {{ tippingPoint.kl_divergence?.toFixed(3) }}</span>
    </template>
    <template v-else>
      <span class="tp-badge stable">STABLE</span>
      <span class="tp-text">no tipping points detected</span>
    </template>
  </div>
</template>

<style scoped>
.tstrip {
  height: 26px;
  background: var(--bg-app);
  border-top: 1px solid var(--border);
  display: flex;
  align-items: center;
  padding: 0 12px;
  gap: 8px;
  flex-shrink: 0;
  font-family: var(--font-mono);
}
.tp-badge {
  font-size: 7px;
  padding: 2px 5px;
  border-radius: 2px;
  font-weight: 700;
  letter-spacing: .05em;
}
.tp-badge.stable { background: var(--accent); color: #fff; }
.tp-text { font-size: 9px; color: var(--text-primary); }
.tp-kl  { font-size: 7px; color: var(--text-muted); margin-left: auto; }
</style>
