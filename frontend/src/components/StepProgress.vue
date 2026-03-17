<script setup>
const props = defineProps({
  currentStep: {
    type: Number,
    default: 1,
    validator: (v) => v >= 1 && v <= 5,
  },
  completedSteps: {
    type: Array,
    default: () => [],
  },
})

const STEPS = [
  { num: 1, label: '領域+數據' },
  { num: 2, label: '配置模擬' },
  { num: 3, label: '模擬運行' },
  { num: 4, label: '趨勢報告' },
  { num: 5, label: '深度互動' },
]

function stepState(num) {
  if (props.completedSteps.includes(num)) return 'completed'
  if (num === props.currentStep) return 'active'
  return 'pending'
}
</script>

<template>
  <div class="step-progress" role="navigation" aria-label="工作流程進度">
    <div
      v-for="(step, idx) in STEPS"
      :key="step.num"
      class="step-item"
    >
      <!-- Connector line (before each step except the first) -->
      <div
        v-if="idx > 0"
        class="connector"
        :class="{ filled: completedSteps.includes(step.num - 1) || completedSteps.includes(step.num) }"
      />

      <!-- Step circle -->
      <div
        class="step-circle"
        :class="stepState(step.num)"
        :aria-current="step.num === currentStep ? 'step' : undefined"
      >
        <!-- Completed: checkmark -->
        <span v-if="stepState(step.num) === 'completed'" class="step-check">✓</span>
        <!-- Active: pulse ring + number -->
        <span v-else-if="stepState(step.num) === 'active'" class="step-num">{{ step.num }}</span>
        <!-- Pending: number -->
        <span v-else class="step-num">{{ step.num }}</span>

        <!-- Active pulse ring -->
        <span v-if="stepState(step.num) === 'active'" class="pulse-ring" />
      </div>

      <!-- Step label -->
      <div class="step-label" :class="stepState(step.num)">
        {{ step.label }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.step-progress {
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 16px 0 8px;
  position: relative;
}

.step-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  position: relative;
  flex: 1;
  max-width: 120px;
}

/* Connector line between steps */
.connector {
  position: absolute;
  top: 16px;
  right: calc(50% + 18px);
  left: calc(-50% + 18px);
  height: 2px;
  background: var(--border, #E5E7EB);
  transition: background 0.4s ease;
  z-index: 0;
}

.connector.filled {
  background: var(--accent, #059669);
}

/* Step circle */
.step-circle {
  position: relative;
  z-index: 1;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 700;
  border: 2px solid var(--border, #E5E7EB);
  background: var(--bg-app, #F3F4F6);
  color: var(--text-muted, #9CA3AF);
  transition: border-color 0.3s ease, background 0.3s ease, color 0.3s ease;
  margin-bottom: 8px;
}

.step-circle.completed {
  border-color: var(--accent, #059669);
  background: var(--accent, #059669);
  color: #fff;
}

.step-circle.active {
  border-color: var(--accent, #059669);
  background: var(--accent, #059669);
  color: #fff;
}

.step-check {
  font-size: 14px;
  font-weight: 900;
  line-height: 1;
}

.step-num {
  font-size: 13px;
  font-weight: 700;
  line-height: 1;
}

/* Active step pulse ring */
.pulse-ring {
  position: absolute;
  inset: -5px;
  border-radius: 50%;
  border: 2px solid var(--accent, #059669);
  opacity: 0;
  animation: ring-pulse 2s ease-out infinite;
}

@keyframes ring-pulse {
  0% { transform: scale(0.85); opacity: 0.5; }
  70% { transform: scale(1.3); opacity: 0; }
  100% { transform: scale(1.3); opacity: 0; }
}

/* Step labels */
.step-label {
  font-size: 12px;
  text-align: center;
  color: var(--text-muted, #9CA3AF);
  transition: color 0.3s ease;
  white-space: nowrap;
  line-height: 1.3;
}

.step-label.completed {
  color: var(--accent, #059669);
}

.step-label.active {
  color: var(--text-primary, #111827);
  font-weight: 600;
}
</style>
