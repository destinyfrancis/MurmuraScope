<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import DomainBuilder from '../components/DomainBuilder.vue'
import DataConnectorPanel from '../components/DataConnectorPanel.vue'
import { quickStart, quickStartWithFile } from '../api/simulation.js'

const router = useRouter()
const quickStartText = ref('')
const quickStartLoading = ref(false)
const quickStartQuestion = ref('')
const quickStartPreset = ref('fast')
const quickStartFile = ref(null)
const quickStartDragging = ref(false)
const quickStartError = ref(null)

const domainPacks = ref([])
const selectedDomain = ref('hk_city')
const showDomainBuilder = ref(false)
const showDataConnector = ref(false)
const customDomainPack = ref(null)

const PRESETS = [
  { key: 'fast',     label: '快速',    hint: '100 agents · 15 rounds (~2 min)' },
  { key: 'standard', label: '標準',    hint: '300 agents · 20 rounds (~8 min)' },
  { key: 'deep',     label: '深度',    hint: '500 agents · 30 rounds (~20 min)' },
]

const QS_MAX_BYTES = 10 * 1024 * 1024
const QS_ALLOWED_EXTS = ['.pdf', '.txt', '.md', '.markdown']

function qsFileExt(name) {
  const i = name.lastIndexOf('.')
  return i >= 0 ? name.slice(i).toLowerCase() : ''
}

function onQSDragOver(e) { e.preventDefault(); quickStartDragging.value = true }
function onQSDragLeave() { quickStartDragging.value = false }
function onQSDrop(e) {
  e.preventDefault()
  quickStartDragging.value = false
  const f = e.dataTransfer?.files?.[0]
  if (f) setQSFile(f)
}
function onQSFileInput(e) {
  const f = e.target.files?.[0]
  if (f) setQSFile(f)
}
function setQSFile(f) {
  quickStartError.value = null
  const ext = qsFileExt(f.name)
  if (!QS_ALLOWED_EXTS.includes(ext)) {
    quickStartError.value = `不支援 ${ext} 格式，請上傳 PDF、TXT 或 Markdown`
    return
  }
  if (f.size > QS_MAX_BYTES) {
    quickStartError.value = `檔案超過 10 MB 上限`
    return
  }
  quickStartFile.value = f
  quickStartText.value = ''   // clear textarea when file selected
}
function clearQSFile() { quickStartFile.value = null }

const canQuickStart = computed(() =>
  !quickStartLoading.value && (quickStartFile.value || quickStartText.value.trim())
)

async function selectDomain(packId) {
  selectedDomain.value = packId
}

onMounted(async () => {
  try {
    const res = await fetch('/api/domain-packs')
    if (res.ok) {
      const data = await res.json()
      domainPacks.value = data.packs || []
    }
  } catch {
    // Fallback: no domain tabs shown
  }
})

async function handleQuickStart() {
  if (!canQuickStart.value) return
  quickStartLoading.value = true
  quickStartError.value = null
  try {
    let res
    if (quickStartFile.value) {
      res = await quickStartWithFile(
        quickStartFile.value,
        quickStartQuestion.value,
        quickStartPreset.value,
      )
    } else {
      res = await quickStart(
        quickStartText.value,
        quickStartQuestion.value,
        quickStartPreset.value,
      )
    }
    const d = res?.data?.data || res?.data
    const sessionId = d?.session_id
    const graphId = d?.graph_id || ''
    if (sessionId) {
      const q = new URLSearchParams({
        express: '1',
        sessionId,
        graphId,
        scenarioQuestion: quickStartQuestion.value,
        preset: quickStartPreset.value,
      })
      router.push(`/process/quick?${q.toString()}`)
    }
  } catch (e) {
    quickStartError.value = e.response?.data?.detail || e.message || '啟動失敗，請重試'
  } finally {
    quickStartLoading.value = false
  }
}


</script>

<template>
  <div class="home">
    <section class="hero">
      <h1 class="hero-title">Morai</h1>
      <p class="hero-subtitle">通用預測引擎</p>
      <p class="hero-desc">
        掉任何種子文字入去——新聞、劇本、地緣政治事件——AI 自動構建世界、生成 agents、開始模擬。
        結合多智能體系統、知識圖譜同宏觀預測，預見集體行為。
      </p>
    </section>

    <!-- Quick Start -->
    <div class="quick-start-section" v-if="!showDomainBuilder && !showDataConnector">
      <h2>即刻開始預測</h2>
      <p class="qs-subtitle">上傳文件或輸入種子文字，AI 自動構建世界，開始模擬</p>

      <!-- File drop zone (primary input) -->
      <div
        class="qs-drop-zone"
        :class="{ dragging: quickStartDragging, 'has-file': quickStartFile }"
        @dragover="onQSDragOver"
        @dragleave="onQSDragLeave"
        @drop="onQSDrop"
        @click="!quickStartFile && $refs.qsFileInput.click()"
      >
        <input
          ref="qsFileInput"
          type="file"
          accept=".pdf,.txt,.md,.markdown"
          class="qs-file-hidden"
          @change="onQSFileInput"
        />
        <template v-if="quickStartFile">
          <span class="qs-file-icon">📄</span>
          <span class="qs-file-name">{{ quickStartFile.name }}</span>
          <button class="qs-file-clear" @click.stop="clearQSFile">✕</button>
        </template>
        <template v-else>
          <span class="qs-drop-icon">⬆</span>
          <span class="qs-drop-label">拖放文件至此，或按此選擇</span>
          <span class="qs-drop-hint">支援 PDF、TXT、Markdown · 最大 10 MB</span>
        </template>
      </div>

      <!-- OR divider + text fallback -->
      <div class="qs-or-row">
        <span class="qs-or-line" /><span class="qs-or-text">或</span><span class="qs-or-line" />
      </div>
      <textarea
        v-model="quickStartText"
        :disabled="!!quickStartFile"
        class="qs-textarea"
        placeholder="輸入場景描述，例如：美聯儲宣布加息200個基點，全球股市出現恐慌性拋售..."
        rows="3"
      />

      <!-- Prediction question (optional) -->
      <input
        v-model="quickStartQuestion"
        class="qs-question"
        placeholder="（選填）你想預測什麼？例如：哪個陣營最終會佔主導？社會情緒走向如何？"
      />

      <!-- Preset pills -->
      <div class="qs-presets">
        <button
          v-for="p in PRESETS"
          :key="p.key"
          class="qs-preset-pill"
          :class="{ active: quickStartPreset === p.key }"
          :title="p.hint"
          @click="quickStartPreset = p.key"
        >
          {{ p.label }}
        </button>
      </div>

      <p v-if="quickStartError" class="qs-error">{{ quickStartError }}</p>

      <button
        class="quick-start-btn"
        :disabled="!canQuickStart"
        @click="handleQuickStart"
      >
        {{ quickStartLoading ? '啟動中...' : '一鍵預測' }}
      </button>
    </div>

    <!-- Domain tab bar -->
    <div v-if="domainPacks.length > 0" class="domain-tabs-wrap">
      <div class="domain-tabs">
        <button
          v-for="pack in domainPacks"
          :key="pack.id"
          :class="['domain-tab', { active: selectedDomain === pack.id }]"
          @click="selectDomain(pack.id)"
        >
          {{ pack.name_zh || pack.name_en }}
        </button>
      </div>
    </div>

    <!-- Domain builder + data connector (collapsible) -->
    <div class="tools-row">
      <button class="tool-toggle" @click="showDomainBuilder = !showDomainBuilder">
        <span class="toggle-icon">{{ showDomainBuilder ? '▾' : '▸' }}</span>
        自訂領域包
      </button>
      <button class="tool-toggle" @click="showDataConnector = !showDataConnector">
        <span class="toggle-icon">{{ showDataConnector ? '▾' : '▸' }}</span>
        數據連接器
      </button>
      <button class="tool-toggle god-view-btn" @click="router.push('/god-view')">
        <span class="toggle-icon">⬡</span>
        GOD VIEW
      </button>
    </div>

    <div v-if="showDomainBuilder" class="tool-panel">
      <DomainBuilder v-model="customDomainPack" />
    </div>

    <div v-if="showDataConnector" class="tool-panel">
      <DataConnectorPanel />
    </div>

  </div>
</template>

<style scoped>
.home {
  max-width: 1100px;
  margin: 0 auto;
  padding: 40px 24px 80px;
}

.hero {
  text-align: center;
  padding: 60px 0 50px;
}

.hero-title {
  font-size: 48px;
  font-weight: 800;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.hero-subtitle {
  font-size: 22px;
  color: var(--text-secondary);
  margin-bottom: 16px;
}

.hero-desc {
  font-size: 15px;
  color: var(--text-muted);
  max-width: 560px;
  margin: 0 auto;
}

/* Quick Start */
.quick-start-section {
  text-align: center;
  margin-bottom: 40px;
  padding: 32px 24px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
}

.quick-start-section h2 {
  font-size: 20px;
  font-weight: 600;
  margin-bottom: 8px;
}

.qs-subtitle { color: var(--text-muted); font-size: 0.9rem; margin-bottom: 1.2rem; }

.qs-drop-zone {
  border: 1px dashed #CCC;
  background: #FAFAFA;
  padding: 32px 24px;
  text-align: center;
  min-height: 120px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  transition: background 0.2s, border-color 0.2s;
  cursor: pointer;
  border-radius: 0;
  margin-bottom: 0.8rem;
  max-width: 600px;
  margin-left: auto;
  margin-right: auto;
}
.qs-drop-zone.dragging {
  background: #F0F0F0;
  border-color: var(--accent, #FF6B35);
}
.qs-drop-zone.has-file {
  border-style: solid;
  border-color: var(--accent-green);
  cursor: default;
  flex-direction: row;
  justify-content: center;
  padding: 1rem 2rem;
}
.qs-file-hidden { display: none; }
.qs-drop-icon { font-size: 2rem; opacity: 0.5; }
.qs-drop-label { font-weight: 600; }
.qs-drop-hint { font-size: 0.8rem; color: var(--text-muted); }
.qs-file-icon { font-size: 1.5rem; }
.qs-file-name { font-weight: 600; flex: 1; text-align: left; margin-left: 0.5rem; }
.qs-file-clear {
  background: none; border: none; cursor: pointer;
  color: var(--text-muted); font-size: 1rem; padding: 0 0.25rem;
}
.qs-or-row { display: flex; align-items: center; gap: 0.75rem; margin: 0.5rem auto; max-width: 600px; }
.qs-or-line { flex: 1; height: 1px; background: var(--border-color); }
.qs-or-text { color: var(--text-muted); font-size: 0.85rem; white-space: nowrap; }
.qs-textarea {
  width: 100%; max-width: 600px; background: var(--bg-input, var(--bg-secondary));
  border: 1px solid var(--border-color); border-radius: 8px;
  color: var(--text-primary); padding: 0.75rem; font-size: 0.95rem;
  resize: vertical; box-sizing: border-box; margin-bottom: 0.75rem;
  font-family: inherit;
}
.qs-textarea:disabled { opacity: 0.4; cursor: not-allowed; }
.qs-question {
  width: 100%; max-width: 600px; background: var(--bg-input, var(--bg-secondary));
  border: 1px solid var(--border-color); border-radius: 8px;
  color: var(--text-primary); padding: 0.65rem 0.75rem;
  font-size: 0.9rem; box-sizing: border-box; margin-bottom: 0.75rem;
  font-family: inherit;
}
.qs-presets { display: flex; gap: 0.5rem; margin-bottom: 1rem; justify-content: center; }
.qs-preset-pill {
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 600;
  padding: 6px 16px;
  border: 1px solid var(--border, #EAEAEA);
  background: var(--bg-card, #FFF);
  color: var(--text-secondary, #666);
  border-radius: 2px;
  cursor: pointer;
  transition: all 0.15s;
}
.qs-preset-pill.active {
  background: #000;
  border-color: #000;
  color: #FFF;
}
.qs-preset-pill:hover:not(.active) {
  border-color: var(--border-hover, #999);
}
.qs-error { color: var(--accent-red); font-size: 0.85rem; margin-bottom: 0.5rem; }

.quick-start-btn {
  width: 100%;
  padding: 20px;
  background: #000;
  color: #FFF;
  border: 1px solid #000;
  border-radius: 0;
  font-family: var(--font-mono);
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 1px;
  text-transform: uppercase;
  cursor: pointer;
  animation: engine-pulse 2s infinite;
  transition: background 0.2s, border-color 0.2s;
}
.quick-start-btn:hover:not(:disabled) {
  background: var(--accent, #FF6B35);
  border-color: var(--accent, #FF6B35);
  transform: translateY(-2px);
}
.quick-start-btn:disabled {
  background: #E5E5E5;
  border-color: #E5E5E5;
  color: #999;
  animation: none;
}
@keyframes engine-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(0,0,0,0.2); }
  50%      { box-shadow: 0 0 0 6px rgba(0,0,0,0); }
}

/* Domain tabs */
.domain-tabs-wrap {
  display: flex;
  justify-content: center;
  margin-bottom: 32px;
}

.domain-tabs {
  display: flex;
  gap: 8px;
  padding: 4px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 9999px;
  flex-wrap: wrap;
  justify-content: center;
}

.domain-tab {
  padding: 8px 20px;
  border: none;
  border-radius: 9999px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: var(--transition);
  white-space: nowrap;
}

.domain-tab:hover {
  color: var(--text-primary);
  background: rgba(0, 212, 255, 0.08);
}

.domain-tab.active {
  background: var(--accent-blue);
  color: #0d1117;
  font-weight: 700;
}

/* Tools row (domain builder + data connector toggles) */
.tools-row {
  display: flex;
  gap: 12px;
  justify-content: center;
  margin-bottom: 24px;
}

.tool-toggle {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 10px 20px;
  font-size: 14px;
  font-weight: 500;
  color: var(--text-secondary);
  cursor: pointer;
  transition: var(--transition);
  display: flex;
  align-items: center;
  gap: 6px;
}

.tool-toggle:hover {
  color: var(--text-primary);
  border-color: var(--accent-blue);
}

.god-view-btn {
  border-color: #00d4aa;
  color: #00d4aa;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  letter-spacing: 1px;
  font-weight: 700;
}

.god-view-btn:hover {
  background: #001a14;
  border-color: #00ffcc;
  color: #00ffcc;
}

.toggle-icon {
  font-size: 12px;
}

.tool-panel {
  margin-bottom: 32px;
}


</style>
