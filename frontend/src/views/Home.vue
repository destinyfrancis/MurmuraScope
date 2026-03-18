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
const packDetails = ref(null)
const loadingDetails = ref(false)
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

const HK_SCENARIOS = [
  {
    key: 'property',
    title: '買樓決策',
    desc: '模擬香港樓市走勢，分析唔同經濟情境下嘅置業決策',
    icon: '🏠',
    color: 'var(--accent-blue)',
  },
  {
    key: 'emigration',
    title: '移民決策',
    desc: '模擬移民潮對社會網絡同經濟嘅影響',
    icon: '✈️',
    color: 'var(--accent-purple)',
  },
  {
    key: 'fertility',
    title: '生育規劃',
    desc: '分析社會因素對生育決策嘅影響同趨勢推演',
    icon: '👶',
    color: 'var(--accent-green)',
  },
  {
    key: 'career',
    title: '學科/就業前景',
    desc: '模擬唔同學科畢業生嘅就業路徑同薪酬走勢',
    icon: '🎓',
    color: 'var(--accent-orange)',
  },
  {
    key: 'b2b',
    title: 'B2B 營銷預測',
    desc: '模擬企業間嘅商業網絡同市場傳播效應',
    icon: '📊',
    color: 'var(--accent-cyan)',
  },
  {
    key: 'opinion',
    title: '宏觀民意推演',
    desc: '模擬公眾輿論形成、傳播同演變過程',
    icon: '🗣️',
    color: 'var(--accent-red)',
  },
]

// Scenario card colors to cycle through for non-HK packs
const FALLBACK_COLORS = [
  'var(--accent-blue)',
  'var(--accent-purple)',
  'var(--accent-green)',
  'var(--accent-orange)',
  'var(--accent-cyan)',
  'var(--accent-red)',
]

const FALLBACK_ICONS = ['🌐', '📈', '🏗️', '💡', '🔬', '🌍']

const activeScenarios = computed(() => {
  // If pack has scenarios defined, map them to cards
  if (packDetails.value?.scenarios?.length) {
    return packDetails.value.scenarios.map((s, i) => ({
      key: s.key || s.id || String(i),
      title: s.title_zh || s.title || s.name_zh || s.name_en || s.name || `Scenario ${i + 1}`,
      desc: s.desc_zh || s.desc || s.description || '',
      icon: s.icon || FALLBACK_ICONS[i % FALLBACK_ICONS.length],
      color: s.color || FALLBACK_COLORS[i % FALLBACK_COLORS.length],
    }))
  }
  // Default to HK scenarios
  return HK_SCENARIOS
})

async function fetchPackDetails(packId) {
  loadingDetails.value = true
  packDetails.value = null
  try {
    const res = await fetch(`/api/domain-packs/${packId}`)
    if (res.ok) {
      packDetails.value = await res.json()
    }
  } catch {
    // Silently fall back to default scenarios
  } finally {
    loadingDetails.value = false
  }
}

async function selectDomain(packId) {
  selectedDomain.value = packId
  await fetchPackDetails(packId)
}

onMounted(async () => {
  try {
    const res = await fetch('/api/domain-packs')
    if (res.ok) {
      const data = await res.json()
      domainPacks.value = data.packs || []
    }
  } catch {
    // Fallback: use hardcoded HK scenarios only
  }
  // Load initial domain details
  await fetchPackDetails(selectedDomain.value)
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

function startScenario(key) {
  router.push({
    name: 'Process',
    params: { scenarioType: key },
    query: selectedDomain.value !== 'hk_city' ? { domainPackId: selectedDomain.value } : undefined,
  })
}
</script>

<template>
  <div class="home">
    <section class="hero">
      <h1 class="hero-title">HKSimEngine</h1>
      <p class="hero-subtitle">香港社會模擬引擎</p>
      <p class="hero-desc">
        基於多代理人系統嘅社會動態模擬平台，透過知識圖譜、AI
        代理人同宏觀數據驅動，深入分析香港社會議題。
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
        placeholder="輸入新聞標題或場景描述，例如：恒指跌破 15000 點，樓市成交量大跌..."
        rows="3"
      />

      <!-- Prediction question (optional) -->
      <input
        v-model="quickStartQuestion"
        class="qs-question"
        placeholder="（選填）你想預測什麼？例如：失業率會否升破 4%？"
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

    <section class="scenarios">
      <h2 class="section-title">選擇模擬場景</h2>

      <div v-if="loadingDetails" class="loading-hint">載入場景中...</div>

      <div v-else class="scenario-grid">
        <div
          v-for="s in activeScenarios"
          :key="s.key"
          class="scenario-card"
          :style="{ '--card-accent': s.color }"
          @click="startScenario(s.key)"
        >
          <div class="card-icon">{{ s.icon }}</div>
          <h3 class="card-title">{{ s.title }}</h3>
          <p class="card-desc">{{ s.desc }}</p>
          <div class="card-arrow">→</div>
        </div>
      </div>
    </section>
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
  border: 2px dashed var(--border-color);
  border-radius: 12px;
  padding: 2rem;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.4rem;
  margin-bottom: 0.8rem;
  max-width: 600px;
  margin-left: auto;
  margin-right: auto;
}
.qs-drop-zone:hover,
.qs-drop-zone.dragging {
  border-color: var(--accent-blue);
  background: rgba(59, 130, 246, 0.05);
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
  border: 1px solid var(--border-color); border-radius: 20px;
  padding: 0.3rem 0.9rem; font-size: 0.85rem; cursor: pointer;
  background: transparent; color: var(--text-secondary); transition: all 0.15s;
}
.qs-preset-pill.active {
  border-color: var(--accent-blue); color: var(--accent-blue);
  background: rgba(59, 130, 246, 0.1);
}
.qs-error { color: var(--accent-red); font-size: 0.85rem; margin-bottom: 0.5rem; }

.quick-start-btn {
  padding: 10px 28px;
  background: var(--accent-blue);
  color: #0d1117;
  border: none;
  border-radius: 8px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: var(--transition);
}

.quick-start-btn:hover:not(:disabled) {
  background: rgba(0, 212, 255, 0.8);
  transform: translateY(-1px);
  box-shadow: var(--shadow-glow-cyan);
}

.quick-start-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
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

.section-title {
  font-size: 20px;
  font-weight: 600;
  margin-bottom: 24px;
  color: var(--text-secondary);
}

.loading-hint {
  text-align: center;
  color: var(--text-muted);
  font-size: 14px;
  padding: 48px 0;
}

.scenario-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 20px;
}

.scenario-card {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 28px 24px;
  cursor: pointer;
  transition: var(--transition);
  position: relative;
  overflow: hidden;
  box-shadow: var(--shadow-card);
}

.scenario-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: var(--card-accent);
  opacity: 0;
  transition: var(--transition);
}

.scenario-card:hover {
  border-color: var(--card-accent);
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}

.scenario-card:hover::before {
  opacity: 1;
}

.card-icon {
  font-size: 32px;
  margin-bottom: 12px;
}

.card-title {
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 8px;
}

.card-desc {
  font-size: 14px;
  color: var(--text-muted);
  line-height: 1.5;
}

.card-arrow {
  position: absolute;
  bottom: 20px;
  right: 20px;
  font-size: 20px;
  color: var(--card-accent);
  opacity: 0;
  transform: translateX(-8px);
  transition: var(--transition);
}

.scenario-card:hover .card-arrow {
  opacity: 1;
  transform: translateX(0);
}
</style>
