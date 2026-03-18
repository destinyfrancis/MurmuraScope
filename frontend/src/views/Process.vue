<script setup>
import { ref, reactive, computed, watch, onMounted, onUnmounted } from 'vue'
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

// Express mode — populated by /process/quick?express=1&sessionId=X&graphId=Y&...
const expressMode = computed(() => route.query.express === '1')
const expressSessionId = computed(() => route.query.sessionId || null)
const expressGraphId = computed(() => route.query.graphId || null)
const expressScenarioQuestion = computed(() => route.query.scenarioQuestion || '')

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
  scenarioQuestion: '',           // passed through to Step 4 report
  preset: { name: 'standard', agents: 300, rounds: 20 },
  config: {
    agentCount: 100,
    roundCount: 30,
    macroScenario: 'baseline',
    platforms: ['facebook', 'instagram'],
    shocks: [],
  },
})

const stepConfig = {
  1: { leftWidth: 70 },
  2: { leftWidth: 50 },
  3: { leftWidth: 65 },
  4: { leftWidth: 75 },
  5: { leftWidth: 45 },
}

const stepStyle = computed(() => ({
  '--left-width': `${stepConfig[currentStep.value]?.leftWidth ?? 60}%`,
}))

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

// currentComponentProps — passes scenarioQuestion to Step4Report, session to all others
const currentComponentProps = computed(() => {
  if (currentStep.value === 4) {
    return { session, scenarioQuestion: session.scenarioQuestion }
  }
  return { session }
})

// Express mode: unmount-safe guard
let _expressAdvanceCancelled = false

onUnmounted(() => {
  _expressAdvanceCancelled = true
})

onMounted(async () => {
  if (!expressMode.value) return
  _expressAdvanceCancelled = false

  // Pre-populate session from URL params (reactive() mutation is intentional here —
  // direct field mutation is Vue's intended pattern for reactive(); accepted exception
  // to the project's immutability rule)
  Object.assign(session, {
    graphId: expressGraphId.value,
    sessionId: expressSessionId.value,
    scenarioQuestion: expressScenarioQuestion.value,
  })

  // Auto-advance: briefly show each step as "auto-completed" before landing on Step 3
  currentStep.value = 1
  await new Promise((r) => setTimeout(r, 600))
  if (_expressAdvanceCancelled) return
  currentStep.value = 2
  await new Promise((r) => setTimeout(r, 400))
  if (_expressAdvanceCancelled) return
  currentStep.value = 3
})

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
    <nav class="app-nav">
      <span class="nav-brand" @click="router.push('/')">HKSIMENGINE</span>
      <span class="step-indicator">
        <span class="step-num">{{ currentStep }}</span>
        <span class="step-label">{{ steps[currentStep - 1]?.label }}</span>
      </span>
      <span class="step-divider" />
      <div class="nav-view-switcher">
        <button
          v-for="step in steps"
          :key="step.key"
          class="view-switch-btn"
          :class="{ active: currentStep === step.key, done: canGoToStep(step.key) && step.key < currentStep }"
          :disabled="!canGoToStep(step.key)"
          @click="goToStep(step.key)"
        >
          {{ step.navLabel }}
        </button>
      </div>
      <span class="nav-spacer" />
      <span v-if="roundLabel" class="nav-step-badge">
        <span class="status-dot processing" />
        {{ roundLabel }}
      </span>
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

    <!-- Express mode indicator -->
    <div v-if="expressMode" class="express-badge">⚡ 快速模式 · 已自動配置</div>

    <!-- Step content — preserve existing PresetSelector + component bindings -->
    <div class="step-content" :style="stepStyle">
      <PresetSelector
        v-if="currentStep === 2"
        v-model="session.preset"
        class="preset-selector-row"
      />
      <component
        :is="currentComponent"
        v-bind="currentComponentProps"
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
  display: flex;
  align-items: center;
  height: 60px;
  padding: 0 24px;
  background: var(--bg-card, #FFF);
  border-bottom: 1px solid var(--border, #EAEAEA);
}
.nav-brand {
  font-family: var(--font-mono);
  font-size: 18px;
  font-weight: 800;
  letter-spacing: 1px;
  color: var(--text-primary, #000);
  margin-right: 24px;
  cursor: pointer;
}
.step-indicator {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-right: 16px;
}
.step-num {
  font-family: var(--font-mono);
  font-size: 14px;
  font-weight: 700;
  color: var(--text-muted, #999);
}
.step-label {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary, #000);
}
.step-divider {
  width: 1px;
  height: 20px;
  background: var(--border, #E0E0E0);
  margin: 0 12px;
}
.nav-step-badge {
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 700;
  background: var(--accent, #FF6B35);
  color: #FFF;
  padding: 2px 8px;
  border-radius: 2px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  display: flex;
  align-items: center;
  gap: 4px;
}
.nav-view-switcher {
  display: flex;
  background: #F5F5F5;
  padding: 4px;
  border-radius: var(--radius-md, 4px);
  gap: 4px;
}
.view-switch-btn {
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary, #666);
  background: none;
  border: none;
  padding: 6px 16px;
  border-radius: var(--radius-sm, 2px);
  cursor: pointer;
  transition: background var(--duration-fast, 0.15s), color var(--duration-fast, 0.15s);
}
.view-switch-btn:hover:not(:disabled) {
  color: var(--text-primary, #000);
}
.view-switch-btn.active {
  background: var(--bg-card, #FFF);
  color: var(--text-primary, #000);
  box-shadow: 0 2px 4px rgba(0,0,0,0.05);
}
.view-switch-btn.done {
  color: var(--text-muted, #999);
}
.view-switch-btn:disabled {
  color: #D1D5DB;
  cursor: not-allowed;
}
.nav-spacer { flex: 1; }
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}
.status-dot.processing {
  background: #FFF;
  animation: nav-pulse 1s infinite;
}
@keyframes nav-pulse {
  50% { opacity: 0.5; }
}

.step-progress-bar {
  height: 3px;
  display: flex;
  background: var(--bg-app);
}
.progress-seg { flex: 1; background: var(--border); }
.progress-seg.done { background: var(--accent); }
.progress-seg.active { background: var(--accent); opacity: .5; }

.step-content { flex: 1; display: flex; flex-direction: column; }

.express-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  background: rgba(59, 130, 246, 0.12);
  color: var(--accent-blue);
  border: 1px solid var(--accent-blue);
  border-radius: 20px;
  padding: 0.2rem 0.8rem;
  font-size: 0.8rem;
  font-weight: 600;
  margin-bottom: 0.5rem;
}
</style>
