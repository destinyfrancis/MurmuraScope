<script setup>
import { ref, onMounted, watch } from 'vue'
import axios from 'axios'

const API = import.meta.env.VITE_API_URL || ''

const props = defineProps({
  modelValue: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue'])

// ── State ──────────────────────────────────────────────────────────────────
const builtinPacks = ref([])
const selectedPackId = ref(null)
const loading = ref(false)
const generating = ref(false)
const saving = ref(false)
const error = ref(null)
const generatePrompt = ref('')

// Editable pack fields
const editedPack = ref(null)

// Add-chip input buffers
const addInputs = ref({
  regions: '',
  occupations: '',
  shocks: '',
  metrics: '',
  sentiment_keywords: '',
})

// ── Lifecycle ──────────────────────────────────────────────────────────────
onMounted(async () => {
  try {
    const res = await axios.get(`${API}/api/domain-packs`)
    builtinPacks.value = res.data?.packs ?? res.data ?? []
  } catch (e) {
    error.value = '無法載入領域包列表'
  }
})

// When parent passes a modelValue, reflect it into editedPack
watch(
  () => props.modelValue,
  (v) => {
    if (v) editedPack.value = deepCopy(v)
  },
  { immediate: true },
)

// ── Helpers ────────────────────────────────────────────────────────────────
function deepCopy(obj) {
  return JSON.parse(JSON.stringify(obj))
}

function arrayField(pack, key) {
  const val = pack[key]
  if (Array.isArray(val)) return val
  if (typeof val === 'string') {
    try { return JSON.parse(val) } catch { return val.split(',').map((s) => s.trim()).filter(Boolean) }
  }
  return []
}

// ── Pack selection ─────────────────────────────────────────────────────────
async function selectBuiltin(pack) {
  selectedPackId.value = pack.id ?? pack.pack_id
  loading.value = true
  error.value = null
  try {
    const res = await axios.get(`${API}/api/domain-packs/${selectedPackId.value}`)
    const data = res.data?.pack ?? res.data
    editedPack.value = {
      id: data.id ?? data.pack_id,
      name: data.name,
      description: data.description ?? '',
      regions: arrayField(data, 'regions'),
      occupations: arrayField(data, 'occupations'),
      shocks: arrayField(data, 'shocks'),
      metrics: arrayField(data, 'metrics'),
      sentiment_keywords: arrayField(data.demographics ?? data, 'sentiment_keywords'),
      locale: data.locale ?? 'zh-HK',
    }
    emit('update:modelValue', deepCopy(editedPack.value))
  } catch (e) {
    error.value = `無法載入領域包: ${selectedPackId.value}`
  } finally {
    loading.value = false
  }
}

// ── AI generation ──────────────────────────────────────────────────────────
async function generatePack() {
  if (!generatePrompt.value.trim()) return
  generating.value = true
  error.value = null
  try {
    const res = await axios.post(`${API}/api/domain-packs/generate`, {
      prompt: generatePrompt.value,
    })
    const data = res.data?.pack ?? res.data
    editedPack.value = {
      id: null,
      name: data.name ?? '自定義領域包',
      description: data.description ?? '',
      regions: arrayField(data, 'regions'),
      occupations: arrayField(data, 'occupations'),
      shocks: arrayField(data, 'shocks'),
      metrics: arrayField(data, 'metrics'),
      sentiment_keywords: arrayField(data, 'sentiment_keywords'),
      locale: data.locale ?? 'zh-HK',
    }
    emit('update:modelValue', deepCopy(editedPack.value))
  } catch (e) {
    error.value = 'AI 生成失敗，請重試'
  } finally {
    generating.value = false
  }
}

// ── Chip editing ───────────────────────────────────────────────────────────
function removeChip(fieldKey, idx) {
  if (!editedPack.value) return
  const updated = [...editedPack.value[fieldKey]]
  updated.splice(idx, 1)
  editedPack.value = { ...editedPack.value, [fieldKey]: updated }
  emit('update:modelValue', deepCopy(editedPack.value))
}

function addChip(fieldKey) {
  const val = addInputs.value[fieldKey].trim()
  if (!val || !editedPack.value) return
  const updated = [...editedPack.value[fieldKey], val]
  editedPack.value = { ...editedPack.value, [fieldKey]: updated }
  addInputs.value[fieldKey] = ''
  emit('update:modelValue', deepCopy(editedPack.value))
}

function handleChipKeydown(event, fieldKey) {
  if (event.key === 'Enter' || event.key === ',') {
    event.preventDefault()
    addChip(fieldKey)
  }
}

// ── Save ───────────────────────────────────────────────────────────────────
async function savePack() {
  if (!editedPack.value) return
  saving.value = true
  error.value = null
  try {
    const res = await axios.post(`${API}/api/domain-packs/save`, editedPack.value)
    const saved = res.data?.pack ?? res.data
    if (saved?.id) editedPack.value = { ...editedPack.value, id: saved.id }
    emit('update:modelValue', deepCopy(editedPack.value))
  } catch (e) {
    error.value = '儲存失敗，請重試'
  } finally {
    saving.value = false
  }
}

// ── Field labels ───────────────────────────────────────────────────────────
const FIELD_LABELS = {
  regions: '地區',
  occupations: '職業',
  shocks: '衝擊事件',
  metrics: '指標',
  sentiment_keywords: '情感關鍵詞',
}
const CHIP_FIELDS = ['regions', 'occupations', 'shocks', 'metrics', 'sentiment_keywords']
</script>

<template>
  <div class="domain-builder">
    <div class="db-header">
      <h3 class="db-title">領域包編輯器</h3>
      <p class="db-subtitle">選擇內建包或用 AI 生成自訂領域</p>
    </div>

    <!-- Error banner -->
    <div v-if="error" class="db-error" role="alert">{{ error }}</div>

    <!-- Builtin pack selection cards -->
    <div class="db-section">
      <div class="db-section-label">內建領域包</div>
      <div v-if="loading && !editedPack" class="db-spinner">載入中…</div>
      <div v-else class="pack-grid">
        <button
          v-for="pack in builtinPacks"
          :key="pack.id ?? pack.pack_id"
          class="pack-card"
          :class="{ selected: (pack.id ?? pack.pack_id) === selectedPackId }"
          @click="selectBuiltin(pack)"
        >
          <span class="pack-name">{{ pack.name }}</span>
          <span class="pack-desc">{{ pack.description ?? '' }}</span>
        </button>
      </div>
    </div>

    <!-- AI generation -->
    <div class="db-section">
      <div class="db-section-label">AI 自動生成</div>
      <div class="ai-gen-row">
        <input
          v-model="generatePrompt"
          class="db-input"
          placeholder="描述你的模擬場景，例如：台灣科技業勞工市場研究…"
          :disabled="generating"
          @keydown.enter="generatePack"
        />
        <button
          class="btn-primary"
          :disabled="generating || !generatePrompt.trim()"
          @click="generatePack"
        >
          <span v-if="generating" class="spinner-sm" />
          <span v-else>AI 生成</span>
        </button>
      </div>
    </div>

    <!-- Editable pack fields -->
    <div v-if="editedPack" class="db-section db-edit-section">
      <div class="db-section-label">
        編輯: {{ editedPack.name }}
        <span v-if="editedPack.locale" class="locale-badge">{{ editedPack.locale }}</span>
      </div>

      <div
        v-for="fieldKey in CHIP_FIELDS"
        :key="fieldKey"
        class="chip-group"
      >
        <div class="chip-group-label">{{ FIELD_LABELS[fieldKey] }}</div>
        <div class="chip-row">
          <span
            v-for="(chip, idx) in editedPack[fieldKey]"
            :key="`${fieldKey}-${idx}`"
            class="chip"
          >
            {{ chip }}
            <button class="chip-delete" aria-label="刪除" @click="removeChip(fieldKey, idx)">×</button>
          </span>
          <input
            v-model="addInputs[fieldKey]"
            class="chip-add-input"
            :placeholder="`+ 新增${FIELD_LABELS[fieldKey]}`"
            @keydown="handleChipKeydown($event, fieldKey)"
            @blur="addChip(fieldKey)"
          />
        </div>
      </div>

      <div class="db-actions">
        <button
          class="btn-primary"
          :disabled="saving"
          @click="savePack"
        >
          <span v-if="saving" class="spinner-sm" />
          <span v-else>儲存領域包</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.domain-builder {
  background: var(--bg-card, #fff);
  border: 1px solid var(--border-color, #E5E7EB);
  border-radius: 12px;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.db-header {}
.db-title { font-size: 18px; font-weight: 700; margin: 0 0 4px; color: var(--text-primary, #111); }
.db-subtitle { font-size: 13px; color: var(--text-muted, #9CA3AF); margin: 0; }

.db-error {
  background: rgba(255, 68, 68, 0.08);
  border: 1px solid #FCA5A5;
  border-radius: 8px;
  color: #B91C1C;
  padding: 10px 14px;
  font-size: 13px;
}

.db-section { display: flex; flex-direction: column; gap: 10px; }
.db-section-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary, #6B7280);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  display: flex;
  align-items: center;
  gap: 8px;
}

.pack-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 10px;
}

.pack-card {
  background: var(--bg-secondary, #F9FAFB);
  border: 2px solid var(--border-color, #E5E7EB);
  border-radius: 10px;
  padding: 12px;
  cursor: pointer;
  text-align: left;
  transition: border-color 0.2s, background 0.2s;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.pack-card:hover { border-color: var(--accent-blue, #2563EB); }
.pack-card.selected {
  border-color: var(--accent-blue, #2563EB);
  background: var(--accent-blue-light, #DBEAFE);
}

.pack-name { font-size: 13px; font-weight: 600; color: var(--text-primary, #111); }
.pack-desc { font-size: 11px; color: var(--text-muted, #9CA3AF); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.ai-gen-row { display: flex; gap: 8px; }
.db-input {
  flex: 1;
  border: 1px solid var(--border-color, #E5E7EB);
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 13px;
  background: var(--bg-secondary, #F9FAFB);
  color: var(--text-primary, #111);
  outline: none;
}
.db-input:focus { border-color: var(--accent-blue, #2563EB); }

.btn-primary {
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
  white-space: nowrap;
  transition: opacity 0.2s;
}
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

.locale-badge {
  font-size: 11px;
  font-weight: 500;
  background: var(--bg-secondary, #F3F4F6);
  color: var(--text-muted, #9CA3AF);
  border-radius: 4px;
  padding: 2px 6px;
  text-transform: none;
  letter-spacing: 0;
}

.db-edit-section { margin-top: 4px; }

.chip-group { display: flex; flex-direction: column; gap: 6px; }
.chip-group-label { font-size: 12px; font-weight: 600; color: var(--text-secondary, #6B7280); }

.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  background: var(--bg-secondary, #F9FAFB);
  border: 1px solid var(--border-color, #E5E7EB);
  border-radius: 8px;
  padding: 8px;
  min-height: 40px;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: var(--accent-blue-light, #DBEAFE);
  color: var(--accent-blue, #1D4ED8);
  border-radius: 20px;
  padding: 3px 10px;
  font-size: 12px;
  font-weight: 500;
}

.chip-delete {
  background: none;
  border: none;
  color: var(--accent-blue, #1D4ED8);
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
  padding: 0 0 0 2px;
  opacity: 0.6;
}
.chip-delete:hover { opacity: 1; }

.chip-add-input {
  border: none;
  outline: none;
  background: transparent;
  font-size: 12px;
  color: var(--text-primary, #111);
  min-width: 140px;
  flex: 1;
}

.db-actions { display: flex; justify-content: flex-end; margin-top: 8px; }

.db-spinner {
  text-align: center;
  color: var(--text-muted, #9CA3AF);
  font-size: 13px;
  padding: 20px;
}

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
