<script setup>
import { ref, reactive } from 'vue'
import axios from 'axios'

const API = import.meta.env.VITE_API_URL || ''

const props = defineProps({
  sessionId: { type: String, default: null },
})
const emit = defineEmits(['data-uploaded', 'schema-detected'])

// ── Upload state ────────────────────────────────────────────────────────────
const dragOver = ref(false)
const uploading = ref(false)
const uploadError = ref(null)
const uploadedFile = ref(null)

// Detected schema from the server
const detectedSchema = ref(null)   // Array<{ field, type, sample }>

// Field mapping: field name → selected target metric
const fieldMappings = reactive({})

// Available target metrics
const TARGET_METRICS = [
  'hsi_level', 'gdp_growth', 'unemployment_rate', 'consumer_confidence',
  'ccl_index', 'cpi_yoy', 'hibor_1m', 'prime_rate', 'net_migration',
  'retail_sales_index', 'tourist_arrivals', 'northbound_capital_bn',
  '(忽略)',
]

// API config (collapsible)
const showApiConfig = ref(false)
const apiConfig = reactive({
  url: '',
  auth_header: '',
})
const apiConfiguring = ref(false)
const apiError = ref(null)

// ── Drag/drop ───────────────────────────────────────────────────────────────
function onDragOver(event) {
  event.preventDefault()
  dragOver.value = true
}

function onDragLeave() {
  dragOver.value = false
}

function onDrop(event) {
  event.preventDefault()
  dragOver.value = false
  const files = event.dataTransfer?.files
  if (files?.length) handleFile(files[0])
}

function onFileInput(event) {
  const file = event.target.files?.[0]
  if (file) handleFile(file)
}

function openFilePicker() {
  document.getElementById('dcp-file-input')?.click()
}

// ── Upload ───────────────────────────────────────────────────────────────────
async function handleFile(file) {
  const allowed = ['text/csv', 'application/json',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.ms-excel']
  const ext = file.name.split('.').pop()?.toLowerCase()
  if (!allowed.includes(file.type) && !['csv', 'json', 'xlsx', 'xls'].includes(ext)) {
    uploadError.value = '僅支援 CSV / Excel / JSON 格式'
    return
  }

  uploadedFile.value = file
  uploadError.value = null
  uploading.value = true

  try {
    const formData = new FormData()
    formData.append('file', file)
    if (props.sessionId) formData.append('session_id', props.sessionId)

    // Try primary endpoint, fall back to alternative
    let res
    try {
      res = await axios.post(`${API}/api/data/upload`, formData)
    } catch {
      res = await axios.post(`${API}/api/ingest/upload`, formData)
    }

    const schema = res.data?.schema ?? res.data?.fields ?? []
    detectedSchema.value = schema

    // Initialise field mappings
    schema.forEach((f) => {
      const name = f.field ?? f.name ?? ''
      fieldMappings[name] = guessMetric(name)
    })

    emit('schema-detected', { schema, file: file.name })
    emit('data-uploaded', { schema, rows: res.data?.rows ?? res.data?.count ?? 0 })
  } catch (e) {
    uploadError.value = e.response?.data?.detail ?? '上傳失敗，請重試'
  } finally {
    uploading.value = false
  }
}

function guessMetric(fieldName) {
  const lower = fieldName.toLowerCase()
  if (lower.includes('hsi') || lower.includes('hang seng')) return 'hsi_level'
  if (lower.includes('gdp')) return 'gdp_growth'
  if (lower.includes('unemp')) return 'unemployment_rate'
  if (lower.includes('confidence') || lower.includes('sentiment')) return 'consumer_confidence'
  if (lower.includes('ccl') || lower.includes('property')) return 'ccl_index'
  if (lower.includes('cpi') || lower.includes('inflation')) return 'cpi_yoy'
  if (lower.includes('hibor')) return 'hibor_1m'
  if (lower.includes('prime')) return 'prime_rate'
  if (lower.includes('migr')) return 'net_migration'
  return '(忽略)'
}

// ── Apply mappings ────────────────────────────────────────────────────────────
async function applyMappings() {
  if (!props.sessionId || !detectedSchema.value) return
  uploading.value = true
  uploadError.value = null
  try {
    await axios.post(`${API}/api/data/map-fields`, {
      session_id: props.sessionId,
      mappings: fieldMappings,
      file_name: uploadedFile.value?.name,
    })
    emit('data-uploaded', { mappings: { ...fieldMappings } })
  } catch (e) {
    uploadError.value = e.response?.data?.detail ?? '欄位映射儲存失敗'
  } finally {
    uploading.value = false
  }
}

// ── API connector ─────────────────────────────────────────────────────────────
async function connectApi() {
  if (!apiConfig.url.trim()) return
  apiConfiguring.value = true
  apiError.value = null
  try {
    const res = await axios.post(`${API}/api/data/connect-api`, {
      session_id: props.sessionId,
      url: apiConfig.url,
      auth_header: apiConfig.auth_header || null,
    })
    emit('data-uploaded', { api: true, url: apiConfig.url, rows: res.data?.rows ?? 0 })
  } catch (e) {
    apiError.value = e.response?.data?.detail ?? 'API 連接失敗'
  } finally {
    apiConfiguring.value = false
  }
}

function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
</script>

<template>
  <div class="dcp">
    <div class="dcp-header">
      <h3 class="dcp-title">數據連接器</h3>
      <p class="dcp-subtitle">上傳 CSV / Excel / JSON 數據或連接外部 API</p>
    </div>

    <!-- Error -->
    <div v-if="uploadError" class="dcp-error" role="alert">{{ uploadError }}</div>

    <!-- Drop zone -->
    <div
      class="drop-zone"
      :class="{ active: dragOver, uploading }"
      role="button"
      tabindex="0"
      aria-label="拖放文件或點擊選擇"
      @dragover="onDragOver"
      @dragleave="onDragLeave"
      @drop="onDrop"
      @click="openFilePicker"
      @keydown.enter="openFilePicker"
    >
      <input
        id="dcp-file-input"
        type="file"
        accept=".csv,.json,.xlsx,.xls"
        class="file-input-hidden"
        @change="onFileInput"
      />

      <div v-if="uploading" class="drop-content">
        <div class="upload-spinner" />
        <span class="drop-text">上傳中…</span>
      </div>

      <div v-else-if="uploadedFile" class="drop-content">
        <span class="drop-icon uploaded">✓</span>
        <span class="drop-text">
          {{ uploadedFile.name }}
          <span class="file-size">({{ formatFileSize(uploadedFile.size) }})</span>
        </span>
        <span class="drop-hint">點擊或拖放以替換</span>
      </div>

      <div v-else class="drop-content">
        <span class="drop-icon">⬆</span>
        <span class="drop-text">拖放文件到此處，或點擊選擇</span>
        <span class="drop-hint">支援 CSV、Excel、JSON</span>
      </div>
    </div>

    <!-- Schema table -->
    <div v-if="detectedSchema && detectedSchema.length > 0" class="schema-section">
      <div class="schema-label">偵測到的欄位結構</div>
      <table class="schema-table">
        <thead>
          <tr>
            <th>欄位名稱</th>
            <th>類型</th>
            <th>樣本值</th>
            <th>映射至指標</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="field in detectedSchema" :key="field.field ?? field.name">
            <td class="field-name">{{ field.field ?? field.name }}</td>
            <td class="field-type">
              <span class="type-badge">{{ field.type ?? 'unknown' }}</span>
            </td>
            <td class="field-sample">{{ field.sample ?? field.example ?? '—' }}</td>
            <td class="field-mapping">
              <select
                v-model="fieldMappings[field.field ?? field.name]"
                class="mapping-select"
              >
                <option v-for="m in TARGET_METRICS" :key="m" :value="m">{{ m }}</option>
              </select>
            </td>
          </tr>
        </tbody>
      </table>

      <div class="schema-actions">
        <button
          class="btn-primary"
          :disabled="uploading"
          @click="applyMappings"
        >
          套用欄位映射
        </button>
      </div>
    </div>

    <!-- API config (collapsible) -->
    <div class="api-section">
      <button class="api-toggle" @click="showApiConfig = !showApiConfig">
        <span class="toggle-icon">{{ showApiConfig ? '▾' : '▸' }}</span>
        外部 API 連接（可選）
      </button>

      <div v-if="showApiConfig" class="api-form">
        <div v-if="apiError" class="dcp-error">{{ apiError }}</div>
        <div class="form-row">
          <label class="form-label">API URL</label>
          <input
            v-model="apiConfig.url"
            class="dcp-input"
            placeholder="https://api.example.com/data"
            type="url"
          />
        </div>
        <div class="form-row">
          <label class="form-label">Authorization Header（可選）</label>
          <input
            v-model="apiConfig.auth_header"
            class="dcp-input"
            placeholder="Bearer your-token-here"
            type="password"
          />
        </div>
        <button
          class="btn-primary"
          :disabled="apiConfiguring || !apiConfig.url.trim()"
          @click="connectApi"
        >
          <span v-if="apiConfiguring" class="spinner-sm" />
          <span v-else>連接 API</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dcp {
  background: var(--bg-card, #fff);
  border: 1px solid var(--border-color, #E5E7EB);
  border-radius: 12px;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.dcp-header {}
.dcp-title { font-size: 18px; font-weight: 700; margin: 0 0 4px; color: var(--text-primary, #111); }
.dcp-subtitle { font-size: 13px; color: var(--text-muted, #9CA3AF); margin: 0; }

.dcp-error {
  background: rgba(255, 68, 68, 0.08);
  border: 1px solid #FCA5A5;
  border-radius: 8px;
  color: #B91C1C;
  padding: 10px 14px;
  font-size: 13px;
}

.drop-zone {
  border: 2px dashed var(--border-color, #D1D5DB);
  border-radius: 12px;
  padding: 40px 20px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
  background: var(--bg-secondary, #F9FAFB);
  outline: none;
}

.drop-zone:hover,
.drop-zone:focus,
.drop-zone.active {
  border-color: var(--accent-blue, #2563EB);
  background: var(--accent-blue-light, #EFF6FF);
}

.drop-zone.uploading {
  pointer-events: none;
  opacity: 0.7;
}

.file-input-hidden {
  display: none;
}

.drop-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.drop-icon {
  font-size: 32px;
  line-height: 1;
  color: var(--text-muted, #9CA3AF);
}

.drop-icon.uploaded {
  color: var(--accent-green, #059669);
}

.drop-text {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary, #111);
}

.file-size {
  font-weight: 400;
  color: var(--text-muted, #9CA3AF);
  font-size: 12px;
}

.drop-hint {
  font-size: 12px;
  color: var(--text-muted, #9CA3AF);
}

.upload-spinner {
  width: 32px;
  height: 32px;
  border: 3px solid var(--border-color, #E5E7EB);
  border-top-color: var(--accent-blue, #2563EB);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin: 0 auto;
}

.schema-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.schema-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary, #6B7280);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.schema-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.schema-table th {
  text-align: left;
  padding: 8px 12px;
  background: var(--bg-secondary, #F9FAFB);
  border-bottom: 2px solid var(--border-color, #E5E7EB);
  font-weight: 600;
  color: var(--text-secondary, #6B7280);
}

.schema-table td {
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-color, #E5E7EB);
  color: var(--text-primary, #111);
}

.field-name { font-weight: 600; font-family: monospace; font-size: 12px; }
.field-type {}
.type-badge {
  background: var(--bg-secondary, #F3F4F6);
  color: var(--text-secondary, #6B7280);
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 11px;
  font-family: monospace;
}

.field-sample {
  color: var(--text-muted, #9CA3AF);
  font-family: monospace;
  font-size: 12px;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mapping-select {
  border: 1px solid var(--border-color, #E5E7EB);
  border-radius: 6px;
  padding: 4px 8px;
  font-size: 12px;
  background: var(--bg-secondary, #F9FAFB);
  color: var(--text-primary, #111);
  outline: none;
  width: 100%;
}

.schema-actions {
  display: flex;
  justify-content: flex-end;
}

.api-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.api-toggle {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary, #6B7280);
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0;
}

.api-toggle:hover { color: var(--text-primary, #111); }
.toggle-icon { font-size: 14px; }

.api-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
  background: var(--bg-secondary, #F9FAFB);
  border-radius: 8px;
  border: 1px solid var(--border-color, #E5E7EB);
}

.form-row { display: flex; flex-direction: column; gap: 4px; }
.form-label { font-size: 12px; font-weight: 600; color: var(--text-secondary, #6B7280); }

.dcp-input {
  border: 1px solid var(--border-color, #E5E7EB);
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 13px;
  background: var(--bg-card, #fff);
  color: var(--text-primary, #111);
  outline: none;
}
.dcp-input:focus { border-color: var(--accent-blue, #2563EB); }

.btn-primary {
  align-self: flex-start;
  background: var(--accent-blue, #2563EB);
  color: #0d1117;
  border: none;
  border-radius: 8px;
  padding: 8px 16px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: opacity 0.2s;
}
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

.spinner-sm {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255,255,255,0.4);
  border-top-color: var(--text-primary);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
