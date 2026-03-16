<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { createSimulation, suggestConfig } from '../api/simulation.js'
import PresetSelector from './PresetSelector.vue'

const props = defineProps({
  session: { type: Object, required: true },
})

// Domain pack state — loaded when domainPackId is not 'hk_city'
const packDetails = ref(null)

async function loadPackDetails(packId) {
  if (!packId || packId === 'hk_city') {
    packDetails.value = null
    return
  }
  try {
    const res = await fetch(`/api/domain-packs/${packId}`)
    if (res.ok) {
      packDetails.value = await res.json()
    }
  } catch {
    packDetails.value = null
  }
}

onMounted(() => loadPackDetails(props.session.domainPackId))
watch(() => props.session.domainPackId, (id) => loadPackDetails(id))

// Pack-specific shock type labels (for the shock form placeholder / hints)
const packShockTypes = computed(() => {
  if (!packDetails.value?.shock_types?.length) return null
  return packDetails.value.shock_types
})

// Label helper — prefer zh unless locale is not zh-HK
const packIsZh = computed(() => {
  if (!packDetails.value) return true
  return packDetails.value.locale?.startsWith('zh')
})

function shockLabel(spec) {
  return packIsZh.value ? spec.label_zh : spec.label_en
}

const emit = defineEmits(['simulation-created'])

const config = reactive({
  agentCount: props.session.config.agentCount,
  roundCount: props.session.config.roundCount,
  macroScenario: props.session.config.macroScenario,
  platforms: [...props.session.config.platforms],
  shocks: [...props.session.config.shocks],
})

const submitting = ref(false)
const error = ref(null)
const mode = ref('beginner')

const showAiAssistant = ref(false)
const aiQuery = ref('')
const aiSuggesting = ref(false)
const aiSuggestion = ref(null)
const aiError = ref(null)

// Preset integration
const presetConfig = ref({
  name: 'standard',
  agents: config.agentCount,
  rounds: config.roundCount,
})

function onPresetChange(preset) {
  presetConfig.value = { ...preset }
  config.agentCount = preset.agents
  config.roundCount = preset.rounds
}

const newShock = reactive({
  round: 10,
  description: '',
})

const macroOptions = [
  { value: 'baseline', label: '基準情景', desc: '維持現有經濟趨勢' },
  { value: 'rate_hike', label: '加息情景', desc: 'HIBOR 升至 5%+' },
  { value: 'recession', label: '衰退情景', desc: 'GDP 負增長、失業率上升' },
  { value: 'boom', label: '繁榮情景', desc: '經濟復甦、樓市上升' },
  { value: 'custom', label: '自訂情景', desc: '自定義宏觀參數' },
]

const platformOptions = [
  { value: 'facebook', label: 'Facebook / 面書' },
  { value: 'instagram', label: 'Instagram / IG' },
]

function togglePlatform(platform) {
  const idx = config.platforms.indexOf(platform)
  if (idx >= 0) {
    config.platforms = config.platforms.filter((p) => p !== platform)
  } else {
    config.platforms = [...config.platforms, platform]
  }
}

function addShock() {
  if (!newShock.description.trim()) return
  config.shocks = [
    ...config.shocks,
    { round: newShock.round, description: newShock.description },
  ]
  newShock.round = 10
  newShock.description = ''
}

function removeShock(index) {
  config.shocks = config.shocks.filter((_, i) => i !== index)
}

async function runAiSuggest() {
  if (!aiQuery.value.trim()) return
  aiSuggesting.value = true
  aiSuggestion.value = null
  aiError.value = null
  try {
    const res = await suggestConfig({ user_query: aiQuery.value })
    aiSuggestion.value = res.data?.data || res.data
  } catch (err) {
    aiError.value = err.response?.data?.detail || err.message || 'AI 建議失敗'
  } finally {
    aiSuggesting.value = false
  }
}

function applyAiSuggestion() {
  if (!aiSuggestion.value) return
  const s = aiSuggestion.value
  if (s.agent_count) config.agentCount = s.agent_count
  if (s.round_count) config.roundCount = s.round_count
  if (s.macro_scenario) config.macroScenario = s.macro_scenario
  if (s.suggested_shocks?.length) {
    const newShocks = s.suggested_shocks.map(sh => ({
      round: sh.round_number,
      description: sh.description,
    }))
    config.shocks = [...config.shocks, ...newShocks]
  }
  showAiAssistant.value = false
  aiSuggestion.value = null
  aiQuery.value = ''
}

async function startSimulation() {
  submitting.value = true
  error.value = null

  try {
    const res = await createSimulation({
      graph_id: props.session.graphId,
      scenario_type: props.session.scenarioType,
      domain_pack_id: props.session.domainPackId || 'hk_city',
      agent_count: config.agentCount,
      round_count: config.roundCount,
      macro_scenario_id: config.macroScenario,
      platforms: Object.fromEntries(config.platforms.map((p) => [p, true])),
      shocks: config.shocks.map((s) => ({
        round_number: s.round,
        shock_type: 'manual',
        description: s.description,
        post_content: s.description,
      })),
    })

    Object.assign(props.session.config, config)

    const sessionId = res.data?.data?.session_id || res.data?.session_id
    emit('simulation-created', {
      sessionId,
    })
  } catch (err) {
    error.value = err.response?.data?.detail || err.message || '建立模擬失敗'
    console.error('Simulation creation failed:', err)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="step2">
      <div class="mode-toggle">
        <button
          :class="['mode-btn', { active: mode === 'beginner' }]"
          @click="mode = 'beginner'"
        >初學者模式</button>
        <button
          :class="['mode-btn', { active: mode === 'advanced' }]"
          @click="mode = 'advanced'"
        >進階模式</button>
      </div>

      <button class="ai-assist-btn" @click="showAiAssistant = !showAiAssistant">
        AI 配置助手
      </button>

      <!-- AI Assistant Panel -->
      <div v-if="showAiAssistant" class="ai-panel">
        <div class="ai-panel-header">
          <span>AI 配置助手</span>
          <button class="close-ai" @click="showAiAssistant = false">✕</button>
        </div>
        <textarea
          v-model="aiQuery"
          class="ai-textarea"
          rows="3"
          placeholder="描述你想模擬的場景，例如：分析取消限購令後30歲年輕人的買樓反應..."
        />
        <button
          class="ai-suggest-btn"
          :disabled="aiSuggesting || !aiQuery.trim()"
          @click="runAiSuggest"
        >
          {{ aiSuggesting ? '生成中...' : '生成配置建議' }}
        </button>
        <p v-if="aiError" class="ai-error">{{ aiError }}</p>

        <div v-if="aiSuggestion" class="ai-result">
          <div class="ai-result-row">
            <span class="ai-key">情景</span>
            <span class="ai-val">{{ aiSuggestion.scenario_type }}</span>
          </div>
          <div class="ai-result-row">
            <span class="ai-key">Agent 數</span>
            <span class="ai-val">{{ aiSuggestion.agent_count }}</span>
          </div>
          <div class="ai-result-row">
            <span class="ai-key">輪數</span>
            <span class="ai-val">{{ aiSuggestion.round_count }}</span>
          </div>
          <div class="ai-result-row">
            <span class="ai-key">宏觀情景</span>
            <span class="ai-val">{{ aiSuggestion.macro_scenario }}</span>
          </div>
          <div v-if="aiSuggestion.suggested_shocks?.length" class="ai-result-row">
            <span class="ai-key">建議衝擊</span>
            <div class="ai-shocks">
              <div v-for="sh in aiSuggestion.suggested_shocks" :key="sh.round_number" class="ai-shock-item">
                輪 {{ sh.round_number }}: {{ sh.description }}
              </div>
            </div>
          </div>
          <div v-if="aiSuggestion.rationale" class="ai-rationale">
            {{ aiSuggestion.rationale }}
          </div>
          <button class="apply-btn" @click="applyAiSuggestion">
            採用建議配置
          </button>
        </div>
      </div>

    <!-- Preset selector (primary configuration method) -->
    <div class="config-card preset-card-wrapper">
      <PresetSelector
        :modelValue="presetConfig"
        @update:modelValue="onPresetChange"
      />
    </div>

    <div class="config-grid">
      <div v-show="mode === 'advanced'" class="config-card">
        <h3 class="card-heading">代理人微調</h3>
        <div class="field">
          <label class="field-label">
            代理人數量：<strong>{{ config.agentCount }}</strong>
          </label>
          <input
            v-model.number="config.agentCount"
            type="range"
            min="50"
            max="500"
            step="10"
            class="range-input"
          />
          <div class="range-labels">
            <span>50</span>
            <span>500</span>
          </div>
        </div>

        <div class="field">
          <label class="field-label">
            模擬回合數：<strong>{{ config.roundCount }}</strong>
          </label>
          <input
            v-model.number="config.roundCount"
            type="range"
            min="10"
            max="100"
            step="5"
            class="range-input"
          />
          <div class="range-labels">
            <span>10</span>
            <span>100</span>
          </div>
        </div>
      </div>

      <div v-show="mode === 'advanced'" class="config-card">
        <h3 class="card-heading">宏觀情景</h3>
        <div class="macro-options">
          <label
            v-for="opt in macroOptions"
            :key="opt.value"
            class="macro-option"
            :class="{ selected: config.macroScenario === opt.value }"
          >
            <input
              v-model="config.macroScenario"
              type="radio"
              :value="opt.value"
              class="radio-hidden"
            />
            <div class="macro-content">
              <span class="macro-label">{{ opt.label }}</span>
              <span class="macro-desc">{{ opt.desc }}</span>
            </div>
          </label>
        </div>
      </div>

      <div v-show="mode === 'advanced'" class="config-card">
        <h3 class="card-heading">討論平台</h3>
        <div class="platform-toggles">
          <button
            v-for="p in platformOptions"
            :key="p.value"
            class="platform-btn"
            :class="{ active: config.platforms.includes(p.value) }"
            @click="togglePlatform(p.value)"
          >
            {{ p.label }}
          </button>
        </div>
      </div>

      <div v-show="mode === 'advanced'" class="config-card">
        <h3 class="card-heading">事件衝擊排程</h3>

        <!-- Domain-specific shock type quick-add chips -->
        <div v-if="packShockTypes" class="shock-type-chips">
          <span class="chips-label">{{ packIsZh ? '快速加入：' : 'Quick add:' }}</span>
          <button
            v-for="spec in packShockTypes"
            :key="spec.id"
            class="shock-chip"
            @click="config.shocks = [...config.shocks, { round: newShock.round, description: shockLabel(spec) }]"
          >
            {{ shockLabel(spec) }}
          </button>
        </div>

        <div class="shock-list" v-if="config.shocks.length > 0">
          <div
            v-for="(shock, i) in config.shocks"
            :key="i"
            class="shock-item"
          >
            <span class="shock-round">第 {{ shock.round }} 回合</span>
            <span class="shock-desc">{{ shock.description }}</span>
            <button class="shock-remove" @click="removeShock(i)">x</button>
          </div>
        </div>
        <p v-else class="empty-hint">尚未加入任何衝擊事件</p>

        <div class="shock-form">
          <input
            v-model.number="newShock.round"
            type="number"
            min="1"
            :max="config.roundCount"
            class="shock-round-input"
            placeholder="回合"
          />
          <input
            v-model="newShock.description"
            type="text"
            class="shock-desc-input"
            placeholder="事件描述，例如：政府宣布加辣措施"
            @keyup.enter="addShock"
          />
          <button class="shock-add-btn" @click="addShock">+</button>
        </div>
      </div>
    </div>

    <p v-if="error" class="error-text">{{ error }}</p>

    <div class="action-bar">
      <button
        class="start-btn"
        :disabled="submitting"
        @click="startSimulation"
      >
        {{ submitting ? '建立中...' : '開始模擬' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.step2 {
  padding: 8px 0;
}

.preset-card-wrapper {
  margin-bottom: 20px;
}

.config-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  margin-bottom: 24px;
}

.config-card {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 24px;
}

.card-heading {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 16px;
  color: var(--text-primary);
}

.field {
  margin-bottom: 20px;
}

.field-label {
  display: block;
  font-size: 14px;
  color: var(--text-secondary);
  margin-bottom: 10px;
}

.field-label strong {
  color: var(--accent-blue);
}

.range-input {
  width: 100%;
  accent-color: var(--accent-blue);
}

.range-labels {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 4px;
}

.macro-options {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.macro-option {
  display: flex;
  align-items: center;
  padding: 10px 14px;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: var(--transition);
}

.macro-option.selected {
  border-color: var(--accent-blue);
  background: var(--accent-blue-light);
}

.radio-hidden {
  display: none;
}

.macro-content {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.macro-label {
  font-size: 14px;
  font-weight: 500;
}

.macro-desc {
  font-size: 12px;
  color: var(--text-muted);
}

.platform-toggles {
  display: flex;
  gap: 10px;
}

.platform-btn {
  flex: 1;
  padding: 12px;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  font-size: 14px;
  transition: var(--transition);
}

.platform-btn.active {
  border-color: var(--accent-green);
  color: var(--accent-green);
  background: rgba(5, 150, 105, 0.08);
}

.shock-type-chips {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-bottom: 12px;
}

.chips-label {
  font-size: 12px;
  color: var(--text-muted);
  white-space: nowrap;
}

.shock-chip {
  padding: 4px 10px;
  background: rgba(78, 204, 163, 0.08);
  border: 1px solid rgba(78, 204, 163, 0.3);
  border-radius: 9999px;
  color: #4ecca3;
  font-size: 12px;
  cursor: pointer;
  transition: var(--transition);
}

.shock-chip:hover {
  background: rgba(78, 204, 163, 0.18);
  border-color: #4ecca3;
}

.shock-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 12px;
}

.shock-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  background: var(--bg-input);
  border-radius: var(--radius-sm);
  font-size: 13px;
}

.shock-round {
  color: var(--accent-orange);
  font-weight: 600;
  white-space: nowrap;
}

.shock-desc {
  flex: 1;
  color: var(--text-secondary);
}

.shock-remove {
  background: none;
  border: none;
  color: var(--text-muted);
  font-size: 16px;
  padding: 2px 6px;
  border-radius: 4px;
  transition: var(--transition);
}

.shock-remove:hover {
  color: var(--accent-red);
  background: rgba(220, 38, 38, 0.08);
}

.empty-hint {
  font-size: 13px;
  color: var(--text-muted);
  margin-bottom: 12px;
}

.shock-form {
  display: flex;
  gap: 8px;
}

.shock-round-input {
  width: 72px;
  padding: 8px;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-size: 13px;
  text-align: center;
}

.shock-desc-input {
  flex: 1;
  padding: 8px 12px;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-size: 13px;
}

.shock-add-btn {
  padding: 8px 14px;
  background: var(--accent-orange);
  color: #0d1117;
  border: none;
  border-radius: var(--radius-sm);
  font-size: 16px;
  font-weight: 700;
  transition: var(--transition);
}

.shock-add-btn:hover {
  opacity: 0.85;
}

.error-text {
  color: var(--accent-red);
  font-size: 14px;
  text-align: center;
  margin-bottom: 12px;
}

.action-bar {
  display: flex;
  justify-content: center;
}

.start-btn {
  padding: 14px 48px;
  background: linear-gradient(135deg, var(--accent-blue), var(--accent-cyan));
  color: #0d1117;
  border: none;
  border-radius: var(--radius-md);
  font-size: 16px;
  font-weight: 700;
  transition: var(--transition);
}

.start-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: var(--shadow-md);
}

.start-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.ai-assist-btn {
  display: block;
  margin: 8px 0 16px;
  padding: 8px 16px;
  background: transparent;
  border: 1px solid var(--accent-blue);
  border-radius: var(--radius-md);
  color: var(--accent-blue);
  font-size: 13px;
  cursor: pointer;
  transition: var(--transition);
  width: 100%;
}

.ai-assist-btn:hover {
  background: var(--accent-blue-light);
}

.ai-panel {
  background: var(--bg-primary);
  border: 1px solid var(--accent-blue);
  border-radius: var(--radius-lg);
  padding: 16px;
  margin-bottom: 16px;
}

.ai-panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  font-size: 14px;
  font-weight: 600;
  color: var(--accent-blue);
}

.close-ai {
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 14px;
}

.ai-textarea {
  width: 100%;
  padding: 10px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  color: var(--text-primary);
  font-size: 13px;
  resize: vertical;
  outline: none;
  margin-bottom: 10px;
}

.ai-suggest-btn {
  width: 100%;
  padding: 9px;
  background: var(--accent-blue);
  border: none;
  border-radius: var(--radius-md);
  color: #0d1117;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: var(--transition);
}

.ai-suggest-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.ai-error {
  color: var(--accent-red, #e05252);
  font-size: 12px;
  margin-top: 8px;
}

.ai-result {
  margin-top: 12px;
  padding: 12px;
  background: var(--bg-secondary);
  border-radius: var(--radius-md);
}

.ai-result-row {
  display: flex;
  justify-content: space-between;
  padding: 5px 0;
  font-size: 13px;
  border-bottom: 1px solid var(--border-color);
}

.ai-key { color: var(--text-muted); }
.ai-val { color: var(--text-primary); font-weight: 500; }

.ai-shocks {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-width: 200px;
}

.ai-shock-item {
  font-size: 12px;
  color: var(--text-secondary);
}

.ai-rationale {
  margin-top: 10px;
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.6;
  font-style: italic;
}

.apply-btn {
  width: 100%;
  margin-top: 12px;
  padding: 9px;
  background: var(--accent-blue-light);
  border: 1px solid var(--accent-blue);
  border-radius: var(--radius-md);
  color: var(--accent-blue);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: var(--transition);
}

.apply-btn:hover {
  background: var(--accent-blue);
  color: #0d1117;
}

.mode-toggle {
  display: flex;
  gap: 4px;
  padding: 3px;
  background: var(--bg-secondary);
  border-radius: 9999px;
  margin-bottom: 16px;
  width: fit-content;
}

.mode-btn {
  padding: 6px 16px;
  border: none;
  border-radius: 9999px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: var(--transition);
}

.mode-btn.active {
  background: var(--accent-blue);
  color: #FFFFFF;
}
</style>
