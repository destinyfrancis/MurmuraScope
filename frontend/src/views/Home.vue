<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import DomainBuilder from '../components/DomainBuilder.vue'
import DataConnectorPanel from '../components/DataConnectorPanel.vue'

const router = useRouter()
const quickStartText = ref('')
const quickStartLoading = ref(false)
const domainPacks = ref([])
const selectedDomain = ref('hk_city')
const packDetails = ref(null)
const loadingDetails = ref(false)
const showDomainBuilder = ref(false)
const showDataConnector = ref(false)
const customDomainPack = ref(null)

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
  if (!quickStartText.value.trim()) return
  quickStartLoading.value = true
  try {
    const { quickStart } = await import('../api/simulation.js')
    const res = await quickStart(quickStartText.value)
    const sessionId = res?.data?.data?.session_id
    if (sessionId) {
      router.push(`/simulation/${sessionId}`)
    }
  } catch (e) {
    console.error('Quick start failed:', e)
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
      <h2>快速開始</h2>
      <p>輸入任何新聞標題或場景描述，即刻開始模擬</p>
      <div class="quick-start-input">
        <textarea
          v-model="quickStartText"
          placeholder="例如：恒指跌破15000點，樓市成交量大跌..."
          rows="3"
        />
        <button
          class="quick-start-btn"
          :disabled="!quickStartText.trim() || quickStartLoading"
          @click="handleQuickStart"
        >
          {{ quickStartLoading ? '啟動中...' : '一鍵模擬' }}
        </button>
      </div>
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

.quick-start-section p {
  font-size: 14px;
  color: var(--text-muted);
  margin-bottom: 20px;
}

.quick-start-input {
  max-width: 600px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.quick-start-input textarea {
  width: 100%;
  padding: 12px 16px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  font-size: 14px;
  font-family: inherit;
  resize: vertical;
  background: var(--bg-secondary, #f9fafb);
  color: var(--text-primary);
  transition: border-color 0.2s;
}

.quick-start-input textarea:focus {
  outline: none;
  border-color: #4ecca3;
}

.quick-start-btn {
  align-self: flex-end;
  padding: 10px 28px;
  background: #4ecca3;
  color: #0f1428;
  border: none;
  border-radius: 8px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: var(--transition);
}

.quick-start-btn:hover:not(:disabled) {
  background: #3db88e;
  transform: translateY(-1px);
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
  background: rgba(78, 204, 163, 0.08);
}

.domain-tab.active {
  background: #4ecca3;
  color: #0f1428;
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
  border-color: #4ecca3;
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
