<script setup>
import { ref, computed } from 'vue'
import { buildGraph, getGraph, uploadScenarioFile, getGraphStatus, analyzeSeed, uploadSeedFile, uploadPersonas } from '../api/graph.js'
import GraphPanel from './GraphPanel.vue'
import PersonaUpload from './PersonaUpload.vue'

const props = defineProps({
  session: { type: Object, required: true },
})

const emit = defineEmits(['graph-built'])

const inputMode = ref('preset')
const customInput = ref('')
const uploadFile = ref(null)
const building = ref(false)
const progress = ref(0)
const progressMsg = ref('')
const error = ref(null)
const graphData = ref(null)
const stats = ref(null)

// Persona upload state
const personaFile = ref(null)
const personaUploading = ref(false)
const personaStatus = ref(null)
const personaError = ref(null)

const analyzing = ref(false)
const analysisResult = ref(null)
const analysisError = ref(null)

// Seed file upload state
const seedUploadDragging = ref(false)
const seedUploadFile = ref(null)
const seedUploading = ref(false)
const seedUploadError = ref(null)
const seedUploadSuccess = ref(null)

const SEED_MAX_BYTES = 10 * 1024 * 1024
const SEED_ALLOWED_EXTS = ['.pdf', '.txt', '.md', '.markdown']

function getSeedFileExt(name) {
  const idx = name.lastIndexOf('.')
  return idx >= 0 ? name.slice(idx).toLowerCase() : ''
}

function validateSeedFile(file) {
  if (!file) return '請選擇檔案'
  const ext = getSeedFileExt(file.name)
  if (!SEED_ALLOWED_EXTS.includes(ext)) {
    return `不支援 ${ext || '未知'} 格式，請上傳 PDF、TXT 或 Markdown 檔案`
  }
  if (file.size > SEED_MAX_BYTES) {
    return `檔案超過 10 MB 上限（目前 ${(file.size / 1024 / 1024).toFixed(1)} MB）`
  }
  return null
}

function onSeedDragOver(e) {
  e.preventDefault()
  seedUploadDragging.value = true
}

function onSeedDragLeave() {
  seedUploadDragging.value = false
}

function onSeedDrop(e) {
  e.preventDefault()
  seedUploadDragging.value = false
  const file = e.dataTransfer?.files?.[0]
  if (file) handleSeedFile(file)
}

function onSeedFileInput(e) {
  const file = e.target.files?.[0]
  if (file) handleSeedFile(file)
}

function handleSeedFile(file) {
  seedUploadError.value = null
  seedUploadSuccess.value = null
  const err = validateSeedFile(file)
  if (err) {
    seedUploadError.value = err
    return
  }
  seedUploadFile.value = file
}

async function uploadSeedText() {
  if (!seedUploadFile.value) return
  seedUploading.value = true
  seedUploadError.value = null
  seedUploadSuccess.value = null
  try {
    const res = await uploadSeedFile(seedUploadFile.value)
    const data = res.data?.data || res.data
    customInput.value = data.text || ''
    seedUploadSuccess.value = `已載入「${data.filename}」（${Math.round(data.size / 1024)} KB）`
    // Switch to custom tab so user sees the text
    inputMode.value = 'custom'
  } catch (err) {
    seedUploadError.value = err.response?.data?.detail || err.message || '上傳失敗'
  } finally {
    seedUploading.value = false
  }
}

const scenarioLabels = {
  property: '買樓決策',
  emigration: '移民決策',
  fertility: '生育規劃',
  career: '學科/就業前景',
  b2b: 'B2B 營銷預測',
  opinion: '宏觀民意推演',
}

const currentLabel = computed(() => scenarioLabels[props.session.scenarioType] || props.session.scenarioType)

function handleFileSelect(e) {
  const file = e.target.files?.[0]
  if (file) {
    uploadFile.value = file
  }
}

async function pollStatus(graphId) {
  const maxAttempts = 60
  for (let i = 0; i < maxAttempts; i++) {
    try {
      const res = await getGraphStatus(graphId)
      const status = res.data.status
      progress.value = res.data.progress || Math.min(90, (i / maxAttempts) * 100)
      progressMsg.value = res.data.message || '構建中...'

      if (status === 'completed') {
        return res.data
      }
      if (status === 'failed') {
        throw new Error(res.data.error || '圖譜構建失敗')
      }
    } catch (err) {
      if (err.response?.status === 404) {
        // Not ready yet
      } else {
        throw err
      }
    }
    await new Promise((r) => setTimeout(r, 2000))
  }
  throw new Error('圖譜構建超時')
}

async function analyzeText() {
  if (!customInput.value.trim()) {
    analysisError.value = '請先輸入自訂場景描述'
    return
  }
  analyzing.value = true
  analysisResult.value = null
  analysisError.value = null
  try {
    const res = await analyzeSeed({
      scenario_type: props.session.scenarioType,
      seed_text: customInput.value,
    })
    analysisResult.value = res.data?.data || res.data
  } catch (err) {
    analysisError.value = err.response?.data?.detail || err.message || '分析失敗'
  } finally {
    analyzing.value = false
  }
}

async function startBuild() {
  building.value = true
  error.value = null
  progress.value = 5
  progressMsg.value = '提交構建請求...'

  try {
    let res

    if (inputMode.value === 'upload' && uploadFile.value) {
      res = await uploadScenarioFile(uploadFile.value, props.session.scenarioType)
    } else {
      res = await buildGraph({
        scenario_type: props.session.scenarioType,
        seed_text: inputMode.value === 'custom' ? customInput.value : `香港${scenarioLabels[props.session.scenarioType] || '社會'}模擬場景`,
        auto_inject_hk_data: true,
      })
    }

    const responseData = res.data?.data || res.data
    const graphId = responseData.graph_id
    progressMsg.value = '載入圖譜數據...'

    // Fetch real nodes/edges from DB
    const graphRes = await getGraph(graphId)
    const graphFull = graphRes.data?.data || graphRes.data
    graphData.value = graphFull

    progress.value = 100
    progressMsg.value = '構建完成！'

    stats.value = {
      entities: graphFull?.nodes?.length || responseData.node_count || 0,
      relations: graphFull?.edges?.length || responseData.edge_count || 0,
    }

    emit('graph-built', {
      graphId,
      graphData: graphFull,
    })

    // Upload persona file if selected
    if (personaFile.value) {
      personaUploading.value = true
      personaStatus.value = null
      personaError.value = null
      try {
        const pRes = await uploadPersonas(graphId, personaFile.value)
        const pData = pRes.data?.data || pRes.data
        personaStatus.value = `已注入 ${pData.injected_count ?? '?'} 個受訪者角色`
      } catch (pErr) {
        personaError.value = pErr.response?.data?.detail || pErr.message || '角色上傳失敗'
      } finally {
        personaUploading.value = false
      }
    }
  } catch (err) {
    error.value = err.response?.data?.detail || err.message || '構建失敗'
    console.error('Graph build failed:', err)
  } finally {
    building.value = false
  }
}

// Evidence X-ray: watch for highlight requests from other steps (e.g. Report)
import { onMounted as onMountedWatch, watch } from 'vue'
const graphPanelRef = ref(null)

watch(() => props.session.targetHighlight, (newVal) => {
  if (newVal && newVal.id && graphData.value) {
    // Wait a bit for the tab/component to be ready if we just switched
    setTimeout(() => {
      if (graphPanelRef.value) {
        graphPanelRef.value.focusNode(newVal.id)
        // Clear it so it can be re-triggered
        // props.session.targetHighlight = null
      }
    }, 500)
  }
}, { immediate: true })

</script>

<template>
  <div class="step1">
    <div class="step1-left">
      <div class="graph-area">
        <GraphPanel
          v-if="graphData"
          ref="graphPanelRef"
          :nodes="graphData.nodes"
          :edges="graphData.edges"
        />
        <div v-else class="graph-placeholder">
          <span class="placeholder-icon">⬡</span>
          <p>知識圖譜將喺呢度顯示</p>
        </div>
      </div>

      <div v-if="stats" class="graph-stats">
        <div class="stat-item">
          <span class="stat-value">{{ stats.entities }}</span>
          <span class="stat-label">實體節點</span>
        </div>
        <div class="stat-item">
          <span class="stat-value">{{ stats.relations }}</span>
          <span class="stat-label">關係邊</span>
        </div>
      </div>
    </div>

    <div class="step1-right">
      <h2 class="panel-title">圖譜構建</h2>
      <p class="panel-subtitle">場景：{{ currentLabel }}</p>

      <!-- Seed text file upload zone (PDF / MD / TXT) -->
      <div
        class="seed-drop-zone"
        :class="{ dragging: seedUploadDragging, 'has-file': seedUploadFile }"
        @dragover="onSeedDragOver"
        @dragleave="onSeedDragLeave"
        @drop="onSeedDrop"
        @click="$refs.seedFileInput.click()"
      >
        <input
          ref="seedFileInput"
          type="file"
          accept=".pdf,.txt,.md,.markdown"
          style="display: none"
          @change="onSeedFileInput"
        />
        <span v-if="seedUploadFile" class="seed-file-icon">📄</span>
        <span v-else class="seed-file-icon">📂</span>
        <div class="seed-drop-text">
          <p v-if="seedUploadFile">{{ seedUploadFile.name }}</p>
          <p v-else>拖放或點擊上傳種子文本</p>
          <small>支援 PDF、TXT、Markdown（最大 10 MB）</small>
        </div>
        <button
          v-if="seedUploadFile"
          class="seed-upload-btn"
          :disabled="seedUploading"
          @click.stop="uploadSeedText"
        >
          {{ seedUploading ? '載入中...' : '載入文字' }}
        </button>
      </div>
      <p v-if="seedUploadError" class="seed-error">{{ seedUploadError }}</p>
      <p v-if="seedUploadSuccess" class="seed-success">{{ seedUploadSuccess }}</p>

      <!-- Persona upload -->
      <PersonaUpload v-model="personaFile" />
      <p v-if="personaUploading" class="persona-status">上傳角色數據中...</p>
      <p v-if="personaStatus" class="seed-success">{{ personaStatus }}</p>
      <p v-if="personaError" class="seed-error">{{ personaError }}</p>

      <div class="input-mode-tabs">
        <button
          class="mode-tab"
          :class="{ active: inputMode === 'preset' }"
          @click="inputMode = 'preset'"
        >
          預設場景
        </button>
        <button
          class="mode-tab"
          :class="{ active: inputMode === 'custom' }"
          @click="inputMode = 'custom'"
        >
          自訂輸入
        </button>
        <button
          class="mode-tab"
          :class="{ active: inputMode === 'upload' }"
          @click="inputMode = 'upload'"
        >
          上傳數據
        </button>
      </div>

      <div v-if="inputMode === 'preset'" class="input-section">
        <p class="input-hint">
          使用預設嘅「{{ currentLabel }}」場景數據構建知識圖譜。
        </p>
      </div>

      <div v-else-if="inputMode === 'custom'" class="input-section">
        <label class="field-label">自訂場景描述</label>
        <textarea
          v-model="customInput"
          class="text-area"
          rows="6"
          placeholder="描述你想模擬嘅場景，例如：模擬 2025 年加息環境下，30歲年輕人嘅買樓決策..."
        />

        <button
          class="analyze-btn"
          :disabled="analyzing || !customInput.trim()"
          @click="analyzeText"
        >
          {{ analyzing ? '分析中...' : 'AI 分析文本' }}
        </button>

        <div v-if="analysisResult" class="analysis-result">
          <div class="analysis-header">
            <span class="analysis-badge">AI 分析結果</span>
            <span class="analysis-confidence">信心值 {{ Math.round(analysisResult.confidence * 100) }}%</span>
          </div>
          <div class="analysis-row">
            <span class="analysis-label">建議情景</span>
            <span class="analysis-value scenario-tag">{{ analysisResult.suggested_scenario }}</span>
          </div>
          <div class="analysis-row">
            <span class="analysis-label">情感傾向</span>
            <span class="analysis-value" :class="`sentiment-${analysisResult.sentiment}`">{{ analysisResult.sentiment }}</span>
          </div>
          <div v-if="analysisResult.key_claims?.length" class="analysis-row">
            <span class="analysis-label">核心論點</span>
            <ul class="analysis-claims">
              <li v-for="(claim, i) in analysisResult.key_claims" :key="i">{{ claim }}</li>
            </ul>
          </div>
          <div v-if="analysisResult.entities?.length" class="analysis-row">
            <span class="analysis-label">關鍵實體</span>
            <div class="entity-tags">
              <span
                v-for="e in analysisResult.entities.slice(0, 6)"
                :key="e.name"
                class="entity-tag"
              >{{ e.name }}</span>
            </div>
          </div>
          <div v-if="analysisResult.suggested_districts?.length" class="analysis-row">
            <span class="analysis-label">重點地區</span>
            <div class="entity-tags">
              <span
                v-for="d in analysisResult.suggested_districts"
                :key="d"
                class="district-tag"
              >{{ d }}</span>
            </div>
          </div>
        </div>
        <p v-if="analysisError" class="error-text">{{ analysisError }}</p>
      </div>

      <div v-else class="input-section">
        <label class="field-label">上傳場景資料</label>
        <div class="upload-area" @click="$refs.fileInput.click()">
          <input
            ref="fileInput"
            type="file"
            accept=".json,.csv,.txt,.xlsx"
            style="display: none"
            @change="handleFileSelect"
          />
          <p v-if="uploadFile" class="upload-name">{{ uploadFile.name }}</p>
          <p v-else class="upload-hint">
            點擊上傳檔案<br />
            <small>支援 JSON、CSV、TXT、XLSX</small>
          </p>
        </div>
      </div>

      <div v-if="building" class="progress-section">
        <div class="ring-loader-container">
          <div class="ring-loader">
            <div class="ring ring-1" />
            <div class="ring ring-2" />
            <div class="ring ring-3" />
          </div>
          <p class="ring-label">{{ progressMsg || '構建知識圖譜中...' }}</p>
          <p class="ring-progress">{{ progress }}%</p>
        </div>
        <div class="progress-bar">
          <div class="progress-fill" :style="{ width: progress + '%' }" />
        </div>
      </div>

      <p v-if="error" class="error-text">{{ error }}</p>

      <button
        class="build-btn"
        :disabled="building"
        @click="startBuild"
      >
        {{ building ? '構建中...' : '開始構建圖譜' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.step1 {
  display: grid;
  grid-template-columns: 1fr 380px;
  gap: 24px;
  min-height: 680px;
}

.graph-area {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  min-height: 600px;
  position: relative;
  overflow: hidden;
}

.graph-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 600px;
  color: var(--text-muted);
  gap: 12px;
}

.placeholder-icon {
  font-size: 64px;
  opacity: 0.3;
}

.graph-stats {
  display: flex;
  gap: 16px;
  margin-top: 16px;
}

.stat-item {
  flex: 1;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 16px;
  text-align: center;
}

.stat-value {
  display: block;
  font-size: 28px;
  font-weight: 700;
  color: var(--accent-blue);
}

.stat-label {
  font-size: 13px;
  color: var(--text-muted);
}

.step1-right {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 24px;
}

.panel-title {
  font-size: 20px;
  font-weight: 700;
  margin-bottom: 4px;
}

.panel-subtitle {
  font-size: 14px;
  color: var(--text-muted);
  margin-bottom: 20px;
}

.input-mode-tabs {
  display: flex;
  gap: 4px;
  background: var(--bg-primary);
  border-radius: var(--radius-sm);
  padding: 3px;
  margin-bottom: 20px;
}

.mode-tab {
  flex: 1;
  padding: 8px;
  background: transparent;
  border: none;
  border-radius: 4px;
  color: var(--text-muted);
  font-size: 13px;
  transition: var(--transition);
}

.mode-tab.active {
  background: var(--bg-card);
  color: var(--text-primary);
}

.input-section {
  margin-bottom: 20px;
}

.input-hint {
  font-size: 14px;
  color: var(--text-secondary);
  line-height: 1.6;
}

.field-label {
  display: block;
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.text-area {
  width: 100%;
  padding: 12px;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  color: var(--text-primary);
  font-size: 14px;
  resize: vertical;
  outline: none;
  transition: var(--transition);
}

.text-area:focus {
  border-color: var(--accent-blue);
}

.upload-area {
  border: 2px dashed var(--border-color);
  border-radius: var(--radius-md);
  padding: 32px;
  text-align: center;
  cursor: pointer;
  transition: var(--transition);
}

.upload-area:hover {
  border-color: var(--accent-blue);
}

.upload-hint {
  color: var(--text-muted);
  font-size: 14px;
}

.upload-hint small {
  font-size: 12px;
}

.upload-name {
  color: var(--accent-blue);
  font-size: 14px;
  font-weight: 500;
}

.progress-section {
  margin-bottom: 16px;
}

.progress-bar {
  height: 6px;
  background: var(--bg-primary);
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 8px;
}

.progress-fill {
  height: 100%;
  background: var(--accent-blue);
  border-radius: 3px;
  transition: width 0.3s ease;
}

.progress-text {
  font-size: 13px;
  color: var(--text-muted);
}

.ring-loader-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  gap: 16px;
}
.ring-loader {
  position: relative;
  width: 100px;
  height: 100px;
}
.ring {
  position: absolute;
  border: 2px solid transparent;
  border-radius: 50%;
  animation: ring-rotate 1.5s linear infinite;
}
.ring-1 {
  width: 80px;
  height: 80px;
  top: 10px;
  left: 10px;
  border-top-color: #000;
}
.ring-2 {
  width: 60px;
  height: 60px;
  top: 20px;
  left: 20px;
  border-top-color: var(--accent, #FF6B35);
  animation-delay: 0.2s;
}
.ring-3 {
  width: 40px;
  height: 40px;
  top: 30px;
  left: 30px;
  border-top-color: #666;
  animation-delay: 0.4s;
}
@keyframes ring-rotate {
  to { transform: rotate(360deg); }
}
.ring-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary, #000);
  font-family: var(--font-mono);
}
.ring-progress {
  font-size: 11px;
  color: var(--text-muted, #999);
  font-family: var(--font-mono);
}

.error-text {
  color: var(--accent-red);
  font-size: 13px;
  margin-bottom: 12px;
}

.build-btn {
  width: 100%;
  padding: 12px;
  background: var(--accent-blue);
  color: #0d1117;
  border: none;
  border-radius: var(--radius-md);
  font-size: 15px;
  font-weight: 600;
  transition: var(--transition);
}

.build-btn:hover:not(:disabled) {
  background: #3d8be0;
}

.build-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.analyze-btn {
  margin-top: 10px;
  width: 100%;
  padding: 9px;
  background: var(--bg-secondary);
  border: 1px solid var(--accent-blue);
  border-radius: var(--radius-md);
  color: var(--accent-blue);
  font-size: 14px;
  font-weight: 500;
  transition: var(--transition);
}

.analyze-btn:hover:not(:disabled) {
  background: var(--accent-blue);
  color: #0d1117;
}

.analyze-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.analysis-result {
  margin-top: 12px;
  padding: 14px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  font-size: 13px;
}

.analysis-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.analysis-badge {
  font-size: 12px;
  font-weight: 600;
  color: var(--accent-blue);
  background: rgba(79, 156, 232, 0.15);
  padding: 2px 8px;
  border-radius: 10px;
}

.analysis-confidence {
  font-size: 11px;
  color: var(--text-muted);
}

.analysis-row {
  display: flex;
  gap: 10px;
  margin-bottom: 8px;
  align-items: flex-start;
}

.analysis-label {
  flex-shrink: 0;
  width: 70px;
  color: var(--text-muted);
  font-size: 12px;
  padding-top: 2px;
}

.analysis-value {
  color: var(--text-primary);
  font-weight: 500;
}

.scenario-tag {
  background: rgba(79, 156, 232, 0.2);
  color: var(--accent-blue);
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 12px;
}

.sentiment-positive { color: var(--accent-green, #4caf7d); }
.sentiment-negative { color: var(--accent-red, #e05252); }
.sentiment-neutral { color: var(--text-secondary); }
.sentiment-mixed { color: var(--accent-yellow, #e0a632); }

.analysis-claims {
  margin: 0;
  padding-left: 16px;
  color: var(--text-secondary);
  line-height: 1.7;
}

.entity-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.entity-tag {
  font-size: 11px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  padding: 1px 7px;
  border-radius: 10px;
  color: var(--text-secondary);
}

.district-tag {
  font-size: 11px;
  background: rgba(76, 175, 125, 0.15);
  color: var(--accent-green, #4caf7d);
  padding: 1px 7px;
  border-radius: 10px;
}

/* Seed text file upload drop zone */
.seed-drop-zone {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border: 2px dashed var(--border-color);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: var(--transition);
  margin-bottom: 12px;
}

.seed-drop-zone:hover,
.seed-drop-zone.dragging {
  border-color: var(--accent-blue);
  background: rgba(74, 158, 255, 0.05);
}

.seed-drop-zone.has-file {
  border-color: var(--accent-green, #4caf7d);
  border-style: solid;
}

.seed-file-icon {
  font-size: 22px;
  flex-shrink: 0;
}

.seed-drop-text {
  flex: 1;
  min-width: 0;
}

.seed-drop-text p {
  margin: 0 0 2px;
  font-size: 13px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.seed-drop-text small {
  font-size: 11px;
  color: var(--text-muted);
}

.seed-upload-btn {
  flex-shrink: 0;
  padding: 5px 12px;
  background: var(--accent-blue);
  color: #0d1117;
  border: none;
  border-radius: var(--radius-sm);
  font-size: 12px;
  font-weight: 600;
  transition: var(--transition);
}

.seed-upload-btn:hover:not(:disabled) {
  background: #3d8be0;
}

.seed-upload-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.seed-error {
  color: var(--accent-red);
  font-size: 12px;
  margin: -8px 0 10px;
}

.seed-success {
  color: var(--accent-green, #4caf7d);
  font-size: 12px;
  margin: -8px 0 10px;
}

.persona-status {
  font-size: 12px;
  color: var(--accent-blue);
  margin: 4px 0 10px;
}
</style>
