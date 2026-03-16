<template>
  <div class="preset-selector">
    <h3>模擬規模</h3>
    <div class="preset-cards">
      <div
        v-for="preset in presets"
        :key="preset.name"
        class="preset-card"
        :class="{ active: selected === preset.name }"
        @click="select(preset)"
      >
        <span class="preset-icon">{{ preset.icon }}</span>
        <strong>{{ preset.label }}</strong>
        <p>{{ preset.agents }} agents / {{ preset.rounds }} rounds</p>
        <p class="time-est">~{{ preset.timeEst }}</p>
      </div>
    </div>
    <div v-if="selected === 'custom'" class="custom-fields">
      <label>Agents: <input type="number" v-model.number="customAgents" min="50" max="1000" /></label>
      <label>Rounds: <input type="number" v-model.number="customRounds" min="5" max="50" /></label>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  modelValue: { type: Object, default: () => ({ name: 'standard', agents: 300, rounds: 20 }) }
})
const emit = defineEmits(['update:modelValue'])

const presets = [
  { name: 'fast', label: '快速', icon: '\u26A1', agents: 100, rounds: 15, timeEst: '3-5 min' },
  { name: 'standard', label: '標準', icon: '\u2696\uFE0F', agents: 300, rounds: 20, timeEst: '8-12 min' },
  { name: 'deep', label: '深度', icon: '\uD83D\uDD2C', agents: 500, rounds: 30, timeEst: '12-18 min' },
  { name: 'custom', label: '自訂', icon: '\u2699\uFE0F', agents: 200, rounds: 25, timeEst: 'varies' },
]

const selected = ref(props.modelValue.name || 'standard')
const customAgents = ref(200)
const customRounds = ref(25)

function select(preset) {
  selected.value = preset.name
  if (preset.name === 'custom') {
    emit('update:modelValue', { name: 'custom', agents: customAgents.value, rounds: customRounds.value })
  } else {
    emit('update:modelValue', { name: preset.name, agents: preset.agents, rounds: preset.rounds })
  }
}

watch([customAgents, customRounds], () => {
  if (selected.value === 'custom') {
    emit('update:modelValue', { name: 'custom', agents: customAgents.value, rounds: customRounds.value })
  }
})
</script>

<style scoped>
.preset-cards { display: flex; gap: 12px; margin: 12px 0; }
.preset-card {
  flex: 1; padding: 16px; border: 2px solid #e0e0e0; border-radius: 12px;
  cursor: pointer; text-align: center; transition: border-color 0.2s;
}
.preset-card.active { border-color: #4f46e5; background: #f0f0ff; }
.preset-card:hover { border-color: #a0a0ff; }
.preset-icon { font-size: 24px; display: block; margin-bottom: 8px; }
.time-est { color: #888; font-size: 13px; }
.custom-fields { display: flex; gap: 16px; margin-top: 12px; }
.custom-fields input { width: 80px; padding: 4px 8px; border: 1px solid #ccc; border-radius: 6px; }
</style>
