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
  { key: 1, label: '圖譜構建', icon: '⬡', navLabel: 'GRAPH' },
  { key: 2, label: '環境搭建', icon: '⚙',  navLabel: 'ENV' },
  { key: 3, label: '開始模擬', icon: '▶',  navLabel: 'SIM' },
  { key: 4, label: '報告生成', icon: '📄', navLabel: 'REPORT' },
  { key: 5, label: '深度交互', icon: '💬', navLabel: 'INTERACT' },
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

const roundLabel = computed(() =>
  currentStep.value === 3 && session.sessionId ? 'RUNNING' : ''
)

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
  <div class="process-root">
    <!-- Black 42px nav bar -->
    <nav class="app-nav">
      <span class="brand">HKSimEngine</span>
      <div class="nav-tabs">
        <button
          v-for="step in steps"
          :key="step.key"
          class="nav-tab"
          :class="{ active: currentStep === step.key, completed: currentStep > step.key }"
          :disabled="!canGoToStep(step.key)"
          @click="goToStep(step.key)"
        >
          {{ step.navLabel }}
        </button>
      </div>
      <div class="nav-status" v-if="currentStep === 3 && session.sessionId">
        <span class="pulse-dot" />
        <span class="nav-round">{{ roundLabel }}</span>
      </div>
    </nav>

    <!-- 3px progress bar -->
    <div class="step-progress-bar">
      <div
        v-for="step in steps"
        :key="step.key"
        class="progress-seg"
        :class="{
          done: currentStep > step.key,
          active: currentStep === step.key,
        }"
      />
    </div>

    <!-- Step content — preserve existing PresetSelector + component bindings -->
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
.process-root { display: flex; flex-direction: column; min-height: 100vh; }

.app-nav {
  height: 42px;
  background: var(--bg-nav);
  display: flex;
  align-items: center;
  padding: 0 18px;
  gap: 14px;
  flex-shrink: 0;
  position: sticky;
  top: 0;
  z-index: 100;
}
.brand {
  font-family: var(--font-mono);
  font-weight: 700;
  font-size: 13px;
  color: #fff;
  letter-spacing: .03em;
  margin-right: 4px;
}
.nav-tabs {
  display: flex;
  gap: 2px;
  background: rgba(255,255,255,.08);
  border-radius: 5px;
  padding: 2px;
}
.nav-tab {
  font-family: var(--font-mono);
  font-size: 9px;
  color: rgba(255,255,255,.38);
  padding: 3px 9px;
  border-radius: 3px;
  border: none;
  background: transparent;
  cursor: pointer;
  letter-spacing: .04em;
}
.nav-tab:disabled { cursor: not-allowed; opacity: .25; }
.nav-tab.active { background: #fff; color: #000; font-weight: 700; }
.nav-tab.completed { color: rgba(255,255,255,.6); }
.nav-status {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 7px;
}
.pulse-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--accent);
  animation: pulse 1.6s ease-in-out infinite;
}
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.3} }
.nav-round { font-family: var(--font-mono); font-size: 9px; color: rgba(255,255,255,.38); }

.step-progress-bar {
  height: 3px;
  display: flex;
  background: var(--bg-app);
}
.progress-seg { flex: 1; background: var(--border); }
.progress-seg.done { background: var(--accent); }
.progress-seg.active { background: var(--accent); opacity: .5; }

.step-content { flex: 1; display: flex; flex-direction: column; }
</style>
