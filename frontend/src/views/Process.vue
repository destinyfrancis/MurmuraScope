<script setup>
import { ref, reactive, computed, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import PresetSelector from '../components/PresetSelector.vue'
import Step1GraphBuild from '../components/Step1GraphBuild.vue'
import Step2EnvSetup from '../components/Step2EnvSetup.vue'
import Step3Simulation from '../components/Step3Simulation.vue'
import Step4Report from '../components/Step4Report.vue'
import Step5Interaction from '../components/Step5Interaction.vue'

const props = defineProps({
  scenarioType: { type: String, required: true },
})

const route = useRoute()

const router = useRouter()

// domainPackId comes from query param (?domainPackId=market_sector)
// Defaults to 'hk_city' for backward compatibility
const domainPackId = ref(route.query.domainPackId || 'hk_city')

const steps = [
  { key: 1, label: '圖譜構建', icon: '⬡' },
  { key: 2, label: '環境搭建', icon: '⚙' },
  { key: 3, label: '開始模擬', icon: '▶' },
  { key: 4, label: '報告生成', icon: '📄' },
  { key: 5, label: '深度交互', icon: '💬' },
]

const currentStep = ref(1)

const session = reactive({
  scenarioType: props.scenarioType,
  domainPackId: domainPackId.value,
  graphId: null,
  graphData: null,
  sessionId: null,
  reportId: null,
  preset: { name: 'standard', agents: 300, rounds: 20 },
  config: {
    agentCount: 100,
    roundCount: 30,
    macroScenario: 'baseline',
    platforms: ['facebook', 'instagram'],
    shocks: [],
  },
})

const currentComponent = computed(() => {
  const map = {
    1: Step1GraphBuild,
    2: Step2EnvSetup,
    3: Step3Simulation,
    4: Step4Report,
    5: Step5Interaction,
  }
  return map[currentStep.value]
})

function canGoToStep(step) {
  if (step <= 1) return true
  if (step === 2) return session.graphId !== null
  if (step === 3) return session.graphId !== null
  if (step === 4) return session.sessionId !== null
  if (step === 5) return session.reportId !== null
  return false
}

function goToStep(step) {
  if (canGoToStep(step)) {
    currentStep.value = step
  }
}

function nextStep() {
  if (currentStep.value < 5) {
    currentStep.value += 1
  }
}

function onGraphBuilt(data) {
  session.graphId = data.graphId
  session.graphData = data.graphData
  nextStep()
}

function onSimulationCreated(data) {
  session.sessionId = data.sessionId
  nextStep()
}

function onSimulationComplete(data) {
  session.sessionId = data.sessionId
  nextStep()
}

function onReportGenerated(data) {
  session.reportId = data.reportId
  nextStep()
}

// Sync preset agents/rounds into config whenever preset changes
watch(
  () => session.preset,
  (p) => {
    if (p && p.agents) session.config.agentCount = p.agents
    if (p && p.rounds) session.config.roundCount = p.rounds
  },
  { deep: true },
)
</script>

<template>
  <div class="process-page">
    <div class="stepper">
      <div
        v-for="step in steps"
        :key="step.key"
        class="step-item"
        :class="{
          active: currentStep === step.key,
          completed: currentStep > step.key,
          clickable: canGoToStep(step.key),
        }"
        @click="goToStep(step.key)"
      >
        <div class="step-indicator">
          <span v-if="currentStep > step.key" class="step-check">✓</span>
          <span v-else class="step-icon">{{ step.icon }}</span>
        </div>
        <span class="step-label">{{ step.label }}</span>
        <div v-if="step.key < 5" class="step-connector" />
      </div>
    </div>

    <div class="step-content">
      <PresetSelector
        v-if="currentStep === 2"
        v-model="session.preset"
        class="preset-selector-row"
      />
      <component
        :is="currentComponent"
        :session="session"
        @graph-built="onGraphBuilt"
        @simulation-created="onSimulationCreated"
        @simulation-complete="onSimulationComplete"
        @report-generated="onReportGenerated"
      />
    </div>
  </div>
</template>

<style scoped>
.process-page {
  max-width: 1400px;
  margin: 0 auto;
  padding: 24px;
}

.stepper {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px 0 32px;
  gap: 0;
}

.step-item {
  display: flex;
  align-items: center;
  gap: 8px;
  position: relative;
  user-select: none;
}

.step-item.clickable {
  cursor: pointer;
}

.step-indicator {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  background: var(--bg-card);
  border: 2px solid var(--border-color);
  transition: var(--transition);
  flex-shrink: 0;
}

.step-item.active .step-indicator {
  border-color: var(--accent-blue);
  background: var(--accent-blue-light, #DBEAFE);
  color: var(--accent-blue);
}

.step-item.completed .step-indicator {
  border-color: var(--accent-green);
  background: var(--accent-green-light, #D1FAE5);
  color: var(--accent-green);
}

.step-label {
  font-size: 14px;
  color: var(--text-muted);
  white-space: nowrap;
  transition: var(--transition);
}

.step-item.active .step-label {
  color: var(--text-primary);
  font-weight: 600;
}

.step-item.completed .step-label {
  color: var(--accent-green);
}

.step-connector {
  width: 48px;
  height: 2px;
  background: var(--border-color);
  margin: 0 12px;
  flex-shrink: 0;
}

.step-item.completed .step-connector {
  background: var(--accent-green);
}

.step-check {
  font-size: 18px;
}

.step-content {
  min-height: 500px;
}
</style>
