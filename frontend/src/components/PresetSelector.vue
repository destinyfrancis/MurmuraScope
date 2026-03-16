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
        <p v-if="preset.byok" class="byok-badge">需要 API Key</p>
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
  { name: 'fast', label: '快速', icon: '\u26A1', agents: 100, rounds: 15, timeEst: '3-5 min', byok: false },
  { name: 'standard', label: '標準', icon: '\u2696\uFE0F', agents: 300, rounds: 20, timeEst: '8-12 min', byok: false },
  { name: 'deep', label: '深度', icon: '\uD83D\uDD2C', agents: 500, rounds: 30, timeEst: '12-18 min', byok: false },
  { name: 'large', label: '大規模', icon: '\uD83C\uDF0F', agents: 1000, rounds: 25, timeEst: '30-50 min', byok: true },
  { name: 'massive', label: '超大規模', icon: '\uD83D\uDE80', agents: 3000, rounds: 20, timeEst: '60-90 min', byok: true },
  { name: 'custom', label: '自訂', icon: '\u2699\uFE0F', agents: 200, rounds: 25, timeEst: 'varies', byok: false },
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
.preset-selector h3 { color: var(--text-primary); }
.preset-cards { display: flex; flex-wrap: wrap; gap: 12px; margin: 12px 0; }
.preset-card {
  flex: 1; min-width: 120px; padding: 16px; border: 2px solid var(--border-color); border-radius: 12px;
  cursor: pointer; text-align: center; transition: border-color 0.2s, background 0.2s, box-shadow 0.2s, transform 0.2s;
  background: var(--bg-card); color: var(--text-primary);
}
.preset-card.active { border-color: var(--accent-blue); background: rgba(0, 212, 255, 0.08); box-shadow: 0 0 16px rgba(0, 212, 255, 0.15); }
.preset-card:hover { border-color: var(--accent-blue); transform: translateY(-2px); }
.preset-card p { color: var(--text-secondary); font-size: 13px; }
.preset-icon { font-size: 24px; display: block; margin-bottom: 8px; }
.time-est { color: var(--text-muted); font-size: 13px; }
.byok-badge { color: var(--accent-orange); font-size: 11px; font-weight: 600; margin-top: 4px; }
.custom-fields { display: flex; gap: 16px; margin-top: 12px; }
.custom-fields label { color: var(--text-secondary); }
.custom-fields input { width: 80px; padding: 4px 8px; border: 1px solid var(--border-color); border-radius: 6px; background: var(--bg-input); color: var(--text-primary); }
</style>
