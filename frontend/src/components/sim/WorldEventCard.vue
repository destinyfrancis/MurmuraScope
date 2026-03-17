<script setup>
defineProps({
  event: {
    type: Object,
    required: true,
    // { content, event_type, round_number, credibility }
  },
})
</script>

<template>
  <div class="event-card">
    <div class="e-header">
      <span class="e-label">{{ event.event_type?.toUpperCase() || 'WORLD EVENT' }}</span>
      <span class="e-round">R{{ event.round_number }}</span>
      <span class="e-cred" v-if="event.credibility != null">
        cred {{ (event.credibility * 100).toFixed(0) }}%
      </span>
    </div>
    <div class="e-text">{{ event.content }}</div>
  </div>
</template>

<style scoped>
.event-card {
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-left: 3px solid var(--accent-warn);
  border-radius: 6px;
  padding: 7px 9px;
}
.e-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 3px;
}
.e-label {
  font-family: var(--font-mono);
  font-size: 7.5px;
  color: #b45309;
  letter-spacing: .08em;
  font-weight: 700;
}
.e-round, .e-cred {
  font-family: var(--font-mono);
  font-size: 7.5px;
  color: #b45309;
  opacity: .7;
}
.e-cred { margin-left: auto; }
.e-text {
  font-size: 10px;
  color: #92400e;
  line-height: 1.4;
}
</style>
