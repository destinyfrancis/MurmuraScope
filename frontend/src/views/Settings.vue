<script setup>
import { ref, onMounted } from 'vue'
import { useSettings } from '../composables/useSettings.js'
import { testApiKey } from '../api/settings.js'

const { settings, saveStatus, loadSettings, saveApiKey } = useSettings()

// ── Tab state ──────────────────────────────────────────────────────────────────
const activeTab = ref('api')

const tabs = [
  { id: 'api',        label: 'API 金鑰',   icon: '🔑' },
  { id: 'model',      label: '模型選擇',   icon: '🧠' },
  { id: 'simulation', label: '模擬預設',   icon: '⚙️' },
  { id: 'ui',         label: '介面偏好',   icon: '🎨' },
  { id: 'data',       label: '資料來源',   icon: '📊' },
]

// ── API key editing state ──────────────────────────────────────────────────────
const keyDraft = ref({
  openrouter: '',
  google: '',
  openai: '',
  anthropic: '',
  deepseek: '',
  fireworks: '',
  fred: '',
})

const keyVisibility = ref({
  openrouter: false,
  google: false,
  openai: false,
  anthropic: false,
  deepseek: false,
  fireworks: false,
  fred: false,
})

const keyTestStatus = ref({
  openrouter: null,   // null | 'testing' | 'ok' | 'error'
  google: null,
  openai: null,
  anthropic: null,
  deepseek: null,
  fireworks: null,
})

const keyTestMessage = ref({})

// ── Providers config ─────────────────────────────────────────────────────────
const providers = [
  { id: 'openrouter', name: 'OpenRouter', placeholder: 'sk-or-v1-...', color: '#7C3AED' },
  { id: 'google',     name: 'Google AI',  placeholder: 'AIza...',       color: '#4285F4' },
  { id: 'openai',     name: 'OpenAI',     placeholder: 'sk-...',        color: '#10A37F' },
  { id: 'anthropic',  name: 'Anthropic',  placeholder: 'sk-ant-...',    color: '#CC7A00' },
  { id: 'deepseek',   name: 'DeepSeek',   placeholder: 'sk-...',        color: '#1875D1' },
  { id: 'fireworks',  name: 'Fireworks',  placeholder: 'fw-...',        color: '#FF6B35' },
]

const providerOptions = providers.map(p => ({ value: p.id, label: p.name }))

// ── Key actions ───────────────────────────────────────────────────────────────
async function handleSaveKey(provider) {
  const key = keyDraft.value[provider].trim()
  if (!key) return
  await saveApiKey(provider, key)
  keyDraft.value[provider] = ''
}

async function handleTestKey(provider) {
  const key = keyDraft.value[provider].trim() || settings.apiKeys[provider]
  if (!key || key.includes('***')) {
    keyTestMessage.value[provider] = '請先輸入金鑰'
    keyTestStatus.value[provider] = 'error'
    return
  }
  keyTestStatus.value[provider] = 'testing'
  keyTestMessage.value[provider] = ''
  try {
    const testProvider = provider === 'fred' ? 'fred' : provider
    const res = await testApiKey(testProvider, key)
    if (res.data.success) {
      keyTestStatus.value[provider] = 'ok'
      keyTestMessage.value[provider] = res.data.message
    } else {
      keyTestStatus.value[provider] = 'error'
      keyTestMessage.value[provider] = res.data.message
    }
  } catch (err) {
    keyTestStatus.value[provider] = 'error'
    keyTestMessage.value[provider] = err.response?.data?.detail || '連線失敗'
  }
}

function toggleKeyVisibility(provider) {
  keyVisibility.value[provider] = !keyVisibility.value[provider]
}

// ── Preset options ─────────────────────────────────────────────────────────
const presetOptions = [
  { value: 'fast',     label: '⚡ Fast — 快速 (10 rounds, 30 agents)' },
  { value: 'standard', label: '⚖️ Standard — 標準 (20 rounds, 50 agents)' },
  { value: 'deep',     label: '🔬 Deep — 深度 (50 rounds, 200 agents)' },
]

const languageOptions = [
  { value: 'zh-HK', label: '繁體中文（香港）' },
  { value: 'zh-TW', label: '繁體中文（台灣）' },
  { value: 'en-US', label: 'English (US)' },
  { value: 'ja-JP', label: '日本語' },
]

const itemsPerPageOptions = [10, 20, 50, 100]

// ── Lifecycle ─────────────────────────────────────────────────────────────────
onMounted(loadSettings)

// ── Save indicator helpers ─────────────────────────────────────────────────────
const saveStatusLabel = {
  idle:   '',
  saving: '● 儲存中…',
  saved:  '✓ 已儲存',
  error:  '✗ 儲存失敗',
}

const saveStatusClass = {
  idle:   '',
  saving: 'status-saving',
  saved:  'status-saved',
  error:  'status-error',
}
</script>

<template>
  <div class="settings-page">
    <!-- Page header -->
    <div class="page-header">
      <div class="header-left">
        <h1 class="page-title">設定</h1>
        <p class="page-subtitle">管理 API 金鑰、模型選擇及系統偏好設定</p>
      </div>
      <div class="save-indicator" :class="saveStatusClass[saveStatus]" aria-live="polite">
        {{ saveStatusLabel[saveStatus] }}
      </div>
    </div>

    <!-- Layout: tab sidebar + content -->
    <div class="settings-layout">

      <!-- Tab sidebar -->
      <nav class="settings-sidebar" role="navigation" aria-label="設定分頁">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          :id="`settings-tab-${tab.id}`"
          class="sidebar-tab"
          :class="{ active: activeTab === tab.id }"
          @click="activeTab = tab.id"
          :aria-selected="activeTab === tab.id"
          role="tab"
        >
          <span class="tab-icon">{{ tab.icon }}</span>
          <span class="tab-label">{{ tab.label }}</span>
        </button>
      </nav>

      <!-- Content area -->
      <div class="settings-content" role="tabpanel" :aria-labelledby="`settings-tab-${activeTab}`">

        <!-- ═══ Tab: API 金鑰 ═══════════════════════════════════════════════ -->
        <div v-if="activeTab === 'api'" class="tab-pane" id="tab-panel-api">
          <div class="tab-header">
            <h2 class="tab-title">API 金鑰</h2>
            <p class="tab-desc">設定各 LLM 服務提供商的 API 金鑰。金鑰已加密儲存，顯示時僅顯示尾部 4 碼。</p>
          </div>

          <div class="api-key-list">
            <div
              v-for="p in providers"
              :key="p.id"
              class="api-key-card"
            >
              <div class="key-card-header">
                <div class="provider-badge" :style="{ background: p.color + '18', borderColor: p.color + '40', color: p.color }">
                  {{ p.name }}
                </div>
                <div class="current-key" v-if="settings.apiKeys[p.id]">
                  <span class="key-masked font-mono">{{ settings.apiKeys[p.id] }}</span>
                </div>
                <div class="current-key empty" v-else>
                  <span class="key-empty">— 未設定 —</span>
                </div>
              </div>

              <div class="key-input-row">
                <div class="key-input-wrapper">
                  <input
                    :id="`key-input-${p.id}`"
                    v-model="keyDraft[p.id]"
                    :type="keyVisibility[p.id] ? 'text' : 'password'"
                    class="key-input"
                    :placeholder="p.placeholder"
                    autocomplete="off"
                    spellcheck="false"
                    @keyup.enter="handleSaveKey(p.id)"
                    :aria-label="`${p.name} API Key`"
                  />
                  <button
                    class="btn-eye"
                    @click="toggleKeyVisibility(p.id)"
                    :title="keyVisibility[p.id] ? '隱藏金鑰' : '顯示金鑰'"
                    :aria-label="keyVisibility[p.id] ? '隱藏金鑰' : '顯示金鑰'"
                  >
                    {{ keyVisibility[p.id] ? '🙈' : '👁️' }}
                  </button>
                </div>
                <button
                  class="btn-secondary"
                  @click="handleTestKey(p.id)"
                  :disabled="keyTestStatus[p.id] === 'testing'"
                  :aria-label="`測試 ${p.name} 金鑰`"
                >
                  <span v-if="keyTestStatus[p.id] === 'testing'">⏳ 測試中…</span>
                  <span v-else>測試</span>
                </button>
                <button
                  class="btn-primary"
                  @click="handleSaveKey(p.id)"
                  :disabled="!keyDraft[p.id].trim()"
                  :aria-label="`儲存 ${p.name} 金鑰`"
                >
                  儲存
                </button>
              </div>

              <!-- Test result badge -->
              <div v-if="keyTestStatus[p.id]" class="test-result" :class="`test-${keyTestStatus[p.id]}`">
                <span v-if="keyTestStatus[p.id] === 'ok'">✓ {{ keyTestMessage[p.id] }}</span>
                <span v-else-if="keyTestStatus[p.id] === 'error'">✗ {{ keyTestMessage[p.id] }}</span>
                <span v-else>⏳ 正在驗證金鑰…</span>
              </div>
            </div>
          </div>
        </div>

        <!-- ═══ Tab: 模型選擇 ════════════════════════════════════════════════ -->
        <div v-if="activeTab === 'model'" class="tab-pane" id="tab-panel-model">
          <div class="tab-header">
            <h2 class="tab-title">模型選擇</h2>
            <p class="tab-desc">選擇用於代理決策及報告生成的 LLM 模型。變更即時生效，無需重啟伺服器。</p>
          </div>

          <div class="settings-grid">

            <div class="settings-group">
              <h3 class="group-title">代理決策 LLM</h3>

              <div class="form-field">
                <label class="field-label" for="agent-provider">Provider</label>
                <select id="agent-provider" v-model="settings.llm.agent_provider" class="field-select">
                  <option v-for="opt in providerOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                </select>
                <p class="field-hint">代理思考、決策、發文所用的 LLM 提供商</p>
              </div>

              <div class="form-field">
                <label class="field-label" for="agent-model">Agent Model（主力）</label>
                <input
                  id="agent-model"
                  v-model="settings.llm.agent_model"
                  class="field-input"
                  placeholder="e.g. deepseek/deepseek-v3.2"
                  spellcheck="false"
                />
                <p class="field-hint">Stakeholder agents（關鍵人物）使用此模型</p>
              </div>

              <div class="form-field">
                <label class="field-label" for="agent-model-lite">Agent Model（精簡）</label>
                <input
                  id="agent-model-lite"
                  v-model="settings.llm.agent_model_lite"
                  class="field-input"
                  placeholder="留空則與主力模型相同"
                  spellcheck="false"
                />
                <p class="field-hint">一般 background agents 使用此較便宜的模型（可選）</p>
              </div>
            </div>

            <div class="settings-group">
              <h3 class="group-title">報告生成 LLM</h3>

              <div class="form-field">
                <label class="field-label" for="report-provider">Provider</label>
                <select id="report-provider" v-model="settings.llm.report_provider" class="field-select">
                  <option v-for="opt in providerOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                </select>
                <p class="field-hint">最終報告、摘要、圖表分析所用的 LLM</p>
              </div>

              <div class="form-field">
                <label class="field-label" for="report-model">Report Model</label>
                <input
                  id="report-model"
                  v-model="settings.llm.report_model"
                  class="field-input"
                  placeholder="e.g. gemini-3.1-pro-preview"
                  spellcheck="false"
                />
                <p class="field-hint">留空則使用該提供商的預設模型</p>
              </div>
            </div>

          </div>
        </div>

        <!-- ═══ Tab: 模擬預設 ════════════════════════════════════════════════ -->
        <div v-if="activeTab === 'simulation'" class="tab-pane" id="tab-panel-simulation">
          <div class="tab-header">
            <h2 class="tab-title">模擬預設</h2>
            <p class="tab-desc">設定新建模擬時的預設參數。</p>
          </div>

          <div class="settings-grid single">

            <div class="settings-group">

              <div class="form-field">
                <label class="field-label" for="default-preset">預設 Preset</label>
                <div class="preset-selector">
                  <label
                    v-for="opt in presetOptions"
                    :key="opt.value"
                    class="preset-option"
                    :class="{ selected: settings.simulation.default_preset === opt.value }"
                  >
                    <input
                      type="radio"
                      :id="`preset-${opt.value}`"
                      v-model="settings.simulation.default_preset"
                      :value="opt.value"
                      class="preset-radio"
                    />
                    {{ opt.label }}
                  </label>
                </div>
              </div>

              <div class="form-field">
                <label class="field-label" for="agent-count">預設代理數量</label>
                <div class="input-with-unit">
                  <input
                    id="agent-count"
                    v-model.number="settings.simulation.default_agent_count"
                    type="number"
                    min="5"
                    max="500"
                    class="field-input narrow"
                  />
                  <span class="unit">agents</span>
                </div>
                <p class="field-hint">建立新模擬時的預設代理數量（5–500）</p>
              </div>

              <div class="form-field">
                <label class="field-label" for="concurrency-limit">
                  Concurrency Limit
                  <span class="field-value">{{ settings.simulation.concurrency_limit }}</span>
                </label>
                <input
                  id="concurrency-limit"
                  v-model.number="settings.simulation.concurrency_limit"
                  type="range"
                  min="1"
                  max="200"
                  class="field-range"
                />
                <div class="range-labels">
                  <span>1</span>
                  <span>200</span>
                </div>
                <p class="field-hint">同時執行 LLM 請求的最大數量。建議 30–80</p>
              </div>

              <div class="form-field">
                <label class="field-label" for="default-domain">預設 Domain Pack</label>
                <input
                  id="default-domain"
                  v-model="settings.simulation.default_domain"
                  class="field-input"
                  placeholder="e.g. hk_city"
                  spellcheck="false"
                />
                <p class="field-hint">新模擬套用的預設 Domain Pack ID</p>
              </div>

            </div>
          </div>
        </div>

        <!-- ═══ Tab: 介面偏好 ════════════════════════════════════════════════ -->
        <div v-if="activeTab === 'ui'" class="tab-pane" id="tab-panel-ui">
          <div class="tab-header">
            <h2 class="tab-title">介面偏好</h2>
            <p class="tab-desc">以下偏好儲存於本機（localStorage），即時生效。</p>
          </div>

          <div class="settings-grid single">
            <div class="settings-group">

              <div class="form-field">
                <label class="field-label" for="ui-language">UI 語言</label>
                <select id="ui-language" v-model="settings.ui.language" class="field-select">
                  <option v-for="opt in languageOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                </select>
              </div>

              <div class="form-field">
                <label class="field-label" for="items-per-page">每頁顯示數量</label>
                <div class="segmented-control">
                  <button
                    v-for="n in itemsPerPageOptions"
                    :key="n"
                    :id="`items-per-page-${n}`"
                    class="seg-btn"
                    :class="{ active: settings.ui.items_per_page === n }"
                    @click="settings.ui.items_per_page = n"
                  >{{ n }}</button>
                </div>
              </div>

              <div class="form-field toggle-field">
                <div class="toggle-info">
                  <label class="field-label" for="auto-open-report">模擬完成後自動開啟報告</label>
                  <p class="field-hint">完成 simulation 後自動跳轉至報告頁面</p>
                </div>
                <label class="toggle-switch" :class="{ active: settings.ui.auto_open_report }">
                  <input
                    id="auto-open-report"
                    v-model="settings.ui.auto_open_report"
                    type="checkbox"
                    class="toggle-input"
                    role="switch"
                    :aria-checked="settings.ui.auto_open_report"
                  />
                  <span class="toggle-track">
                    <span class="toggle-thumb" />
                  </span>
                </label>
              </div>

            </div>
          </div>
        </div>

        <!-- ═══ Tab: 資料來源 ═══════════════════════════════════════════════ -->
        <div v-if="activeTab === 'data'" class="tab-pane" id="tab-panel-data">
          <div class="tab-header">
            <h2 class="tab-title">資料來源</h2>
            <p class="tab-desc">設定外部數據源 API 金鑰及整合選項。</p>
          </div>

          <div class="settings-grid single">
            <div class="settings-group">

              <!-- FRED API Key -->
              <div class="form-field">
                <label class="field-label" for="fred-key-input">FRED API Key</label>
                <div class="key-card-header minimal">
                  <div class="current-key" v-if="settings.data.fred_api_key">
                    <span class="key-masked font-mono">{{ settings.data.fred_api_key }}</span>
                  </div>
                  <div class="current-key empty" v-else>
                    <span class="key-empty">— 未設定 —</span>
                  </div>
                </div>
                <div class="key-input-row">
                  <div class="key-input-wrapper">
                    <input
                      id="fred-key-input"
                      v-model="keyDraft.fred"
                      :type="keyVisibility.fred ? 'text' : 'password'"
                      class="key-input"
                      placeholder="Your FRED API key"
                      autocomplete="off"
                      @keyup.enter="handleSaveKey('fred')"
                      aria-label="FRED API Key"
                    />
                    <button class="btn-eye" @click="toggleKeyVisibility('fred')" :title="keyVisibility.fred ? '隱藏' : '顯示'">
                      {{ keyVisibility.fred ? '🙈' : '👁️' }}
                    </button>
                  </div>
                  <button class="btn-secondary" @click="handleTestKey('fred')" :disabled="keyTestStatus.fred === 'testing'">
                    <span v-if="keyTestStatus.fred === 'testing'">⏳</span>
                    <span v-else>測試</span>
                  </button>
                  <button class="btn-primary" @click="handleSaveKey('fred')" :disabled="!keyDraft.fred.trim()">
                    儲存
                  </button>
                </div>
                <div v-if="keyTestStatus.fred" class="test-result" :class="`test-${keyTestStatus.fred}`">
                  <span v-if="keyTestStatus.fred === 'ok'">✓ {{ keyTestMessage.fred }}</span>
                  <span v-else-if="keyTestStatus.fred === 'error'">✗ {{ keyTestMessage.fred }}</span>
                  <span v-else>⏳ 正在驗證…</span>
                </div>
                <p class="field-hint">來自 <a href="https://fred.stlouisfed.org/docs/api/api_key.html" target="_blank" rel="noopener">St. Louis Fed</a>，用於獲取宏觀經濟數據</p>
              </div>

              <!-- External Feed Toggle -->
              <div class="form-field toggle-field">
                <div class="toggle-info">
                  <label class="field-label" for="external-feed-toggle">啟用外部數據源</label>
                  <p class="field-hint">啟用後系統將從 FRED、World Bank 等源定時更新數據</p>
                </div>
                <label class="toggle-switch" :class="{ active: settings.data.external_feed_enabled }">
                  <input
                    id="external-feed-toggle"
                    v-model="settings.data.external_feed_enabled"
                    type="checkbox"
                    class="toggle-input"
                    role="switch"
                    :aria-checked="settings.data.external_feed_enabled"
                  />
                  <span class="toggle-track">
                    <span class="toggle-thumb" />
                  </span>
                </label>
              </div>

              <!-- Refresh interval -->
              <div class="form-field" v-if="settings.data.external_feed_enabled">
                <label class="field-label" for="refresh-interval">更新頻率</label>
                <div class="input-with-unit">
                  <input
                    id="refresh-interval"
                    v-model.number="settings.data.feed_refresh_interval"
                    type="number"
                    min="300"
                    max="86400"
                    step="300"
                    class="field-input narrow"
                  />
                  <span class="unit">秒</span>
                </div>
                <p class="field-hint">每次自動更新的間隔（300–86400 秒）</p>
              </div>

            </div>
          </div>
        </div>

      </div>
    </div>
  </div>
</template>

<style scoped>
/* ── Page layout ─────────────────────────────────────────────────────────── */

.settings-page {
  max-width: 1100px;
  margin: 0 auto;
  padding: 40px 32px;
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 36px;
}

.page-title {
  font-family: var(--font-mono);
  font-size: 28px;
  font-weight: 800;
  letter-spacing: -0.5px;
  color: var(--text-primary);
  margin: 0 0 4px;
}

.page-subtitle {
  font-size: 14px;
  color: var(--text-secondary);
  margin: 0;
}

/* ── Save indicator ──────────────────────────────────────────────────────── */

.save-indicator {
  font-size: 13px;
  font-weight: 600;
  padding: 4px 12px;
  border-radius: 20px;
  transition: all 0.25s ease;
  min-width: 90px;
  text-align: right;
}

.status-saving {
  color: var(--accent-warn);
}

.status-saved {
  color: var(--accent-success);
}

.status-error {
  color: var(--accent-danger);
}

/* ── Layout ──────────────────────────────────────────────────────────────── */

.settings-layout {
  display: grid;
  grid-template-columns: 200px 1fr;
  gap: 0;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-card);
  overflow: hidden;
  min-height: 560px;
}

/* ── Sidebar ─────────────────────────────────────────────────────────────── */

.settings-sidebar {
  background: var(--bg-graph);
  border-right: 1px solid var(--border);
  padding: 16px 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sidebar-tab {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 10px 16px;
  background: none;
  border: none;
  border-left: 3px solid transparent;
  text-align: left;
  cursor: pointer;
  color: var(--text-secondary);
  font-size: 14px;
  font-weight: 500;
  transition: all 0.15s ease;
}

.sidebar-tab:hover {
  background: rgba(0, 0, 0, 0.04);
  color: var(--text-primary);
}

.sidebar-tab.active {
  border-left-color: var(--accent);
  background: var(--accent-subtle);
  color: var(--accent);
  font-weight: 700;
}

.tab-icon {
  font-size: 16px;
  flex-shrink: 0;
}

.tab-label {
  flex: 1;
}

/* ── Content ─────────────────────────────────────────────────────────────── */

.settings-content {
  padding: 32px;
  overflow-y: auto;
}

.tab-pane {
  animation: fadeIn 0.18s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to   { opacity: 1; transform: translateY(0); }
}

.tab-header {
  margin-bottom: 28px;
}

.tab-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 6px;
}

.tab-desc {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 0;
  line-height: 1.5;
}

/* ── Settings grid ───────────────────────────────────────────────────────── */

.settings-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 32px;
}

.settings-grid.single {
  grid-template-columns: 1fr;
  max-width: 540px;
}

.settings-group {}

.group-title {
  font-size: 13px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-muted);
  margin: 0 0 16px;
}

/* ── Form fields ─────────────────────────────────────────────────────────── */

.form-field {
  margin-bottom: 24px;
}

.field-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 6px;
}

.field-value {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--accent);
  font-weight: 700;
}

.field-hint {
  font-size: 12px;
  color: var(--text-muted);
  margin: 6px 0 0;
  line-height: 1.4;
}

.field-hint a {
  color: var(--accent);
}

.field-input, .field-select {
  width: 100%;
  padding: 9px 12px;
  background: var(--bg-input);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  font-size: 14px;
  color: var(--text-primary);
  outline: none;
  transition: border-color 0.15s;
}

.field-input:focus, .field-select:focus {
  border-color: var(--accent);
  background: var(--bg-card);
}

.field-input.narrow {
  width: 100px;
}

.field-range {
  width: 100%;
  accent-color: var(--accent);
  margin: 4px 0;
}

.range-labels {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: var(--text-muted);
}

.input-with-unit {
  display: flex;
  align-items: center;
  gap: 8px;
}

.unit {
  font-size: 13px;
  color: var(--text-secondary);
}

/* ── API key cards ───────────────────────────────────────────────────────── */

.api-key-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.api-key-card {
  padding: 18px;
  background: var(--bg-graph);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  transition: border-color 0.15s;
}

.api-key-card:hover {
  border-color: var(--border-hover);
}

.key-card-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.key-card-header.minimal {
  margin-bottom: 8px;
}

.provider-badge {
  padding: 3px 10px;
  border-radius: 20px;
  border: 1px solid;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.03em;
  flex-shrink: 0;
}

.current-key {
  flex: 1;
}

.key-masked {
  font-size: 13px;
  color: var(--text-secondary);
  letter-spacing: 0.05em;
}

.key-empty {
  font-size: 12px;
  color: var(--text-muted);
}

.key-input-row {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}

.key-input-wrapper {
  flex: 1;
  position: relative;
}

.key-input {
  width: 100%;
  padding: 8px 36px 8px 12px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  font-size: 13px;
  font-family: var(--font-mono);
  color: var(--text-primary);
  outline: none;
  transition: border-color 0.15s;
}

.key-input:focus {
  border-color: var(--accent);
}

.btn-eye {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  font-size: 14px;
  cursor: pointer;
  padding: 2px;
  opacity: 0.6;
  transition: opacity 0.15s;
}

.btn-eye:hover { opacity: 1; }

/* ── Buttons ─────────────────────────────────────────────────────────────── */

.btn-primary {
  padding: 8px 16px;
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: var(--radius-md);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s, opacity 0.15s;
  flex-shrink: 0;
}

.btn-primary:hover:not(:disabled) { background: var(--accent-hover); }
.btn-primary:disabled { opacity: 0.4; cursor: not-allowed; }

.btn-secondary {
  padding: 8px 14px;
  background: none;
  color: var(--text-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
  flex-shrink: 0;
}

.btn-secondary:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--accent);
}

.btn-secondary:disabled { opacity: 0.4; cursor: not-allowed; }

/* ── Test result ─────────────────────────────────────────────────────────── */

.test-result {
  margin-top: 8px;
  padding: 6px 12px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  font-weight: 600;
}

.test-ok    { background: rgba(16,185,129,0.1); color: var(--accent-success); }
.test-error { background: rgba(220,38,38,0.1);  color: var(--accent-danger); }
.test-testing { background: rgba(255,152,0,0.1); color: var(--accent-warn); }

/* ── Preset selector ─────────────────────────────────────────────────────── */

.preset-selector {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.preset-option {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: var(--bg-graph);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  cursor: pointer;
  font-size: 14px;
  color: var(--text-primary);
  transition: all 0.15s;
}

.preset-option:hover {
  border-color: var(--accent);
  background: var(--accent-subtle);
}

.preset-option.selected {
  border-color: var(--accent);
  background: var(--accent-subtle);
  font-weight: 600;
  color: var(--accent);
}

.preset-radio {
  display: none;
}

/* ── Segmented control ───────────────────────────────────────────────────── */

.segmented-control {
  display: flex;
  gap: 4px;
  background: var(--bg-graph);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 4px;
  width: fit-content;
}

.seg-btn {
  padding: 6px 16px;
  background: none;
  border: none;
  border-radius: var(--radius-sm);
  font-size: 14px;
  font-weight: 500;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s;
}

.seg-btn:hover:not(.active) {
  background: rgba(0,0,0,0.05);
  color: var(--text-primary);
}

.seg-btn.active {
  background: var(--bg-card);
  color: var(--accent);
  font-weight: 700;
  box-shadow: var(--shadow-card);
}

/* ── Toggle switch ───────────────────────────────────────────────────────── */

.toggle-field {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.toggle-info {
  flex: 1;
}

.toggle-info .field-label {
  justify-content: flex-start;
}

.toggle-switch {
  cursor: pointer;
  flex-shrink: 0;
}

.toggle-input {
  position: absolute;
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle-track {
  display: flex;
  align-items: center;
  width: 44px;
  height: 24px;
  background: var(--border);
  border-radius: 12px;
  padding: 2px;
  transition: background 0.2s ease;
}

.toggle-switch.active .toggle-track {
  background: var(--accent);
}

.toggle-thumb {
  width: 20px;
  height: 20px;
  background: #fff;
  border-radius: 50%;
  box-shadow: 0 1px 3px rgba(0,0,0,0.2);
  transition: transform 0.2s ease;
}

.toggle-switch.active .toggle-thumb {
  transform: translateX(20px);
}

/* ── Font mono util ──────────────────────────────────────────────────────── */
.font-mono { font-family: var(--font-mono); }

/* ── Responsive ──────────────────────────────────────────────────────────── */

@media (max-width: 768px) {
  .settings-page {
    padding: 24px 16px;
  }

  .settings-layout {
    grid-template-columns: 1fr;
  }

  .settings-sidebar {
    flex-direction: row;
    flex-wrap: nowrap;
    overflow-x: auto;
    border-right: none;
    border-bottom: 1px solid var(--border);
    padding: 8px;
    gap: 4px;
  }

  .sidebar-tab {
    flex-shrink: 0;
    border-left: none;
    border-bottom: 3px solid transparent;
    padding: 8px 12px;
    border-radius: var(--radius-sm);
  }

  .sidebar-tab.active {
    border-left-color: transparent;
    border-bottom-color: var(--accent);
  }

  .settings-grid {
    grid-template-columns: 1fr;
  }

  .settings-content {
    padding: 20px;
  }
}
</style>
