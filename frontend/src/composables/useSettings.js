/**
 * useSettings — Vue 3 composable for application settings.
 *
 * Features:
 *  - Fetches all settings from GET /api/settings on first use
 *  - UI prefs (language, theme, etc.) are written to localStorage immediately
 *  - Backend settings are debounced 500ms then auto-saved via PUT /api/settings
 *  - Save status indicator: 'idle' | 'saving' | 'saved' | 'error'
 */

import { reactive, ref, watch } from 'vue'
import { getSettings, updateSettings } from '../api/settings.js'

// ── Shared singleton state ────────────────────────────────────────────────────
// Using module-level state so all components share the same settings instance.

const settings = reactive({
  llm: {
    agent_provider: 'openrouter',
    agent_model: '',
    agent_model_lite: '',
    report_provider: 'openrouter',
    report_model: '',
  },
  apiKeys: {
    openrouter: '',
    google: '',
    openai: '',
    anthropic: '',
    deepseek: '',
    fireworks: '',
  },
  simulation: {
    default_preset: 'standard',
    concurrency_limit: 50,
    default_agent_count: 50,
    default_domain: 'hk_city',
  },
  ui: {
    language: 'zh-HK',
    auto_open_report: true,
    items_per_page: 20,
  },
  data: {
    fred_api_key: '',
    external_feed_enabled: false,
    feed_refresh_interval: 3600,
  },
})

const saveStatus = ref('idle') // 'idle' | 'saving' | 'saved' | 'error'
const isLoaded = ref(false)
let _debounceTimer = null

// ── UI Prefs: apply immediately from localStorage on module load ───────────────
function _loadUiPrefsFromStorage() {
  try {
    const raw = localStorage.getItem('ms_ui_prefs')
    if (raw) {
      const prefs = JSON.parse(raw)
      Object.assign(settings.ui, prefs)
    }
  } catch {
    // Ignore parse errors
  }
  _applyUiPrefs(settings.ui)
}

function _applyUiPrefs(prefs) {
  try {
    localStorage.setItem('ms_ui_prefs', JSON.stringify(prefs))
    document.documentElement.setAttribute('data-lang', prefs.language || 'zh-HK')
    // Future: apply theme token, font size etc.
  } catch {
    // Ignore storage errors
  }
}

// Immediately apply saved UI prefs when the module first loads
_loadUiPrefsFromStorage()

// ── Watch: UI prefs → localStorage (immediate) ────────────────────────────────
watch(
  () => ({ ...settings.ui }),
  (prefs) => _applyUiPrefs(prefs),
  { deep: true }
)

// ── Watch: backend settings → debounced auto-save ────────────────────────────
function _collectBackendSettings() {
  return {
    agent_provider: settings.llm.agent_provider,
    agent_model: settings.llm.agent_model,
    agent_model_lite: settings.llm.agent_model_lite,
    report_provider: settings.llm.report_provider,
    report_model: settings.llm.report_model,
    // Note: API keys are only saved when explicitly changed by the user
    // (they arrive masked from the server so we don't round-trip them)
    default_preset: settings.simulation.default_preset,
    concurrency_limit: settings.simulation.concurrency_limit,
    default_agent_count: settings.simulation.default_agent_count,
    default_domain: settings.simulation.default_domain,
    external_feed_enabled: settings.data.external_feed_enabled,
    feed_refresh_interval: settings.data.feed_refresh_interval,
  }
}

watch(
  _collectBackendSettings,
  () => {
    if (!isLoaded.value) return // Don't save during initial hydration
    _scheduleSave()
  },
  { deep: true }
)

function _scheduleSave() {
  clearTimeout(_debounceTimer)
  _debounceTimer = setTimeout(_autoSave, 500)
}

async function _autoSave() {
  saveStatus.value = 'saving'
  try {
    await updateSettings(_collectBackendSettings())
    saveStatus.value = 'saved'
    setTimeout(() => {
      if (saveStatus.value === 'saved') saveStatus.value = 'idle'
    }, 2500)
  } catch (err) {
    console.error('[useSettings] auto-save failed:', err)
    saveStatus.value = 'error'
  }
}

// ── Public composable function ────────────────────────────────────────────────

export function useSettings() {
  /**
   * Load settings from the backend (idempotent — skips if already loaded).
   */
  async function loadSettings() {
    if (isLoaded.value) return
    try {
      const res = await getSettings()
      const data = res.data
      if (data.llm)         Object.assign(settings.llm, data.llm)
      if (data.api_keys)    Object.assign(settings.apiKeys, data.api_keys)
      if (data.simulation)  Object.assign(settings.simulation, data.simulation)
      if (data.data)        Object.assign(settings.data, data.data)
      isLoaded.value = true
    } catch (err) {
      console.error('[useSettings] loadSettings failed:', err)
    }
  }

  /**
   * Save an API key explicitly (avoids sending masked "sk-or-***" values back).
   * @param {string} provider - 'openrouter' | 'google' | 'openai' | 'anthropic' | 'deepseek' | 'fireworks'
   * @param {string} key      - Plain text API key
   */
  async function saveApiKey(provider, key) {
    const fieldMap = {
      openrouter: 'openrouter_key',
      google: 'google_key',
      openai: 'openai_key',
      anthropic: 'anthropic_key',
      deepseek: 'deepseek_key',
      fireworks: 'fireworks_key',
      fred: 'fred_api_key',
    }
    const field = fieldMap[provider]
    if (!field) return
    saveStatus.value = 'saving'
    try {
      await updateSettings({ [field]: key })
      saveStatus.value = 'saved'
      setTimeout(() => {
        if (saveStatus.value === 'saved') saveStatus.value = 'idle'
      }, 2500)
    } catch (err) {
      console.error('[useSettings] saveApiKey failed:', err)
      saveStatus.value = 'error'
    }
  }

  /**
   * Force immediate save (bypassing debounce).
   */
  async function saveNow() {
    clearTimeout(_debounceTimer)
    await _autoSave()
  }

  return {
    settings,
    saveStatus,
    isLoaded,
    loadSettings,
    saveApiKey,
    saveNow,
  }
}
