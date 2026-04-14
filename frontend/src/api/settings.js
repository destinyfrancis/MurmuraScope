import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

/**
 * Fetch all current settings (API keys are masked).
 * @returns {Promise<{llm, api_keys, simulation, data}>}
 */
export function getSettings() {
  return api.get('/settings')
}

/**
 * Update one or more settings.
 * @param {Object} payload - Partial settings object (any keys from SettingsUpdateRequest)
 * @returns {Promise<{success, updated, settings}>}
 */
export function updateSettings(payload) {
  return api.put('/settings', payload)
}

/**
 * Test whether an API key (and optionally a specific model) is valid.
 * @param {string} provider - e.g. 'openrouter', 'google', 'openai', 'anthropic'
 * @param {string|null} apiKey - Plain text key to test; null = use stored key
 * @param {string|null} model  - When set, also verifies this model is accessible
 * @returns {Promise<{success, provider, message}>}
 */
export function testApiKey(provider, apiKey = null, model = null) {
  return api.post('/settings/test-key', {
    provider,
    ...(apiKey ? { api_key: apiKey } : {}),
    ...(model  ? { model }          : {}),
  })
}
