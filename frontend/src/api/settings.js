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
 * Test whether an API key is valid for a given provider.
 * @param {string} provider - e.g. 'openrouter', 'google', 'openai', 'anthropic'
 * @param {string} apiKey   - Plain text key to test
 * @returns {Promise<{success, provider, message}>}
 */
export function testApiKey(provider, apiKey) {
  return api.post('/settings/test-key', { provider, api_key: apiKey })
}
