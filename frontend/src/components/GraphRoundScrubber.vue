<script setup>
import { ref, watch, computed } from 'vue'

const props = defineProps({
  availableRounds: { type: Array, default: () => [] },
  currentRound: { type: Number, default: null },
})

const emit = defineEmits(['round-change'])

const sliderRound = ref(0)

watch(() => props.currentRound, (val) => {
  if (val !== null && val !== undefined) sliderRound.value = val
})

watch(() => props.availableRounds, (rounds) => {
  if (rounds.length > 0 && sliderRound.value === 0) {
    sliderRound.value = rounds[rounds.length - 1]
  }
})

function onSliderChange(e) {
  const idx = parseInt(e.target.value, 10)
  const round = props.availableRounds[idx]
  if (round !== undefined) {
    sliderRound.value = round
    emit('round-change', round)
  }
}

const sliderIndex = computed(() => {
  const idx = props.availableRounds.indexOf(sliderRound.value)
  return idx >= 0 ? idx : props.availableRounds.length - 1
})
</script>

<template>
  <div v-if="availableRounds.length > 1" class="timeline-slider">
    <span class="timeline-label">輪次</span>
    <input
      type="range"
      class="slider"
      :min="0"
      :max="availableRounds.length - 1"
      :value="sliderIndex"
      @input="onSliderChange"
    />
    <span class="timeline-round">{{ sliderRound }}</span>
  </div>
</template>

<style scoped>
.timeline-slider {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md, 8px);
  font-size: 12px;
  color: var(--text-muted, #9CA3AF);
}

.slider {
  width: 160px;
  accent-color: var(--accent-blue, #4a9eff);
  cursor: pointer;
}

.timeline-round {
  min-width: 28px;
  text-align: center;
  color: var(--accent-blue, #4a9eff);
  font-weight: 600;
}
</style>
