<script setup>
import { ref, onMounted, computed } from 'vue'
import { getForecast, getBacktest, listSessions } from '../api/simulation.js'
import { getStockTickers, getStockForecast, getStockBacktest, getStockSummary } from '../api/stock.js'

// ── Backtest cache (5-min TTL) ────────────────────────────────────────────────
const BACKTEST_CACHE_TTL = 5 * 60 * 1000
const backtestCache = new Map()

function getCachedBacktest(metric, trainEnd, horizon) {
  const key = `${metric}:${trainEnd}:${horizon}`
  const entry = backtestCache.get(key)
  if (entry && Date.now() - entry.timestamp < BACKTEST_CACHE_TTL) {
    return entry.data
  }
  return null
}

function setCachedBacktest(metric, trainEnd, horizon, data) {
  const key = `${metric}:${trainEnd}:${horizon}`
  backtestCache.set(key, { data, timestamp: Date.now() })
}

async function cachedGetBacktest(metric, trainEnd, horizon) {
  const cached = getCachedBacktest(metric, trainEnd, horizon)
  if (cached) return cached
  const result = await getBacktest(metric, trainEnd, horizon)
  setCachedBacktest(metric, trainEnd, horizon, result)
  return result
}

// ── Tab state ────────────────────────────────────────────────────────────────
const activeTab = ref('macro')

// ── Macro tab state (unchanged) ───────────────────────────────────────────────
const METRICS = [
  { key: 'ccl_index', label: 'CCL 樓價指數', unit: '' },
  { key: 'unemployment_rate', label: '失業率', unit: '%' },
  { key: 'hsi_level', label: '恒生指數', unit: '' },
  { key: 'cpi_yoy', label: 'CPI 按年', unit: '%' },
  { key: 'gdp_growth', label: 'GDP 增長率', unit: '%' },
  { key: 'consumer_confidence', label: '消費者信心', unit: '' },
  { key: 'net_migration', label: '淨移民', unit: '人' },
  { key: 'hibor_1m', label: '1M HIBOR', unit: '%' },
  { key: 'retail_sales_index', label: '零售銷售指數', unit: '' },
  { key: 'tourist_arrivals', label: '旅客人數', unit: '人' },
  { key: 'interest_rate', label: '利率 (HIBOR 1M)', unit: '%' },
]

const selectedMetric = ref('ccl_index')
const forecastData = ref(null)
const backtestData = ref(null)
const loadingForecast = ref(false)
const loadingBacktest = ref(false)
const backtestSummary = ref([])
const loadingSummary = ref(false)
const error = ref(null)

const selectedLabel = computed(() => {
  const m = METRICS.find(m => m.key === selectedMetric.value)
  return m ? m.label : selectedMetric.value
})

async function loadMetric(metric) {
  selectedMetric.value = metric
  error.value = null
  loadingForecast.value = true
  loadingBacktest.value = true

  try {
    const [fcRes, btRes] = await Promise.allSettled([
      getForecast(metric, 12),
      cachedGetBacktest(metric, '2022-Q4', 8),
    ])
    forecastData.value = fcRes.status === 'fulfilled' ? fcRes.value?.data?.data : null
    backtestData.value = btRes.status === 'fulfilled' ? btRes.value?.data?.data : null
  } catch (e) {
    error.value = e.message
  } finally {
    loadingForecast.value = false
    loadingBacktest.value = false
  }
}

async function loadAllBacktests() {
  loadingSummary.value = true
  const results = await Promise.allSettled(
    METRICS.map(m => cachedGetBacktest(m.key, '2022-Q4', 8).then(r => ({
      metric: m.key,
      label: m.label,
      ...r?.data?.data,
    })))
  )
  backtestSummary.value = results
    .filter(r => r.status === 'fulfilled')
    .map(r => r.value)
    .filter(r => r && r.mape != null)
  loadingSummary.value = false
}

function mapeColor(mape) {
  if (mape == null) return '#999'
  if (mape < 5) return '#22c55e'
  if (mape < 15) return '#eab308'
  return '#ef4444'
}

function dirAccColor(acc) {
  if (acc == null) return '#999'
  if (acc >= 0.7) return '#22c55e'
  if (acc >= 0.5) return '#eab308'
  return '#ef4444'
}

// ── Stock tab state ────────────────────────────────────────────────────────────

const STOCK_GROUPS = [
  { key: 'hk_stock', label: 'HK股票' },
  { key: 'hk_index', label: 'HK指數' },
  { key: 'us_stock', label: 'US股票' },
  { key: 'us_index', label: 'US指數' },
]

const stockGroup = ref('hk_stock')
const stockTickers = ref([])
const loadingTickers = ref(false)
const selectedTicker = ref(null)

const stockForecastData = ref(null)
const stockBacktestData = ref(null)
const loadingStockForecast = ref(false)
const loadingStockBacktest = ref(false)
const stockError = ref(null)

// Session selector for social signal overlay
const sessions = ref([])
const selectedSession = ref(null)
const loadingSessions = ref(false)

const filteredTickers = computed(() =>
  stockTickers.value.filter(t => t.group === stockGroup.value)
)

const selectedTickerMeta = computed(() =>
  stockTickers.value.find(t => t.ticker === selectedTicker.value) || null
)

const signals = computed(() => {
  const raw = stockForecastData.value?.signals
  if (!raw || !Array.isArray(raw)) return []
  return [...raw].sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution))
})

function signalClass(contribution) {
  if (contribution > 0.001) return 'signal-bullish'
  if (contribution < -0.001) return 'signal-bearish'
  return 'signal-neutral'
}

function signalIcon(contribution) {
  if (contribution > 0.001) return '▲'
  if (contribution < -0.001) return '▼'
  return '─'
}

function netShift(sigs) {
  if (!sigs.length) return null
  const total = sigs.reduce((s, sg) => s + (sg.contribution || 0), 0)
  return total * 100
}

async function loadStockTickers() {
  loadingTickers.value = true
  try {
    const res = await getStockTickers()
    stockTickers.value = res?.data?.data || res?.data || []
    // Auto-select first in current group
    const first = stockTickers.value.find(t => t.group === stockGroup.value)
    if (first && !selectedTicker.value) {
      await loadStockData(first.ticker)
    }
  } catch (e) {
    stockError.value = e.message
  } finally {
    loadingTickers.value = false
  }
}

async function loadStockData(ticker) {
  selectedTicker.value = ticker
  stockError.value = null
  loadingStockForecast.value = true
  loadingStockBacktest.value = true

  try {
    const [fcRes, btRes] = await Promise.allSettled([
      getStockForecast(ticker, 12, selectedSession.value),
      getStockBacktest(ticker, '2024-W40', 8),
    ])
    stockForecastData.value = fcRes.status === 'fulfilled' ? fcRes.value?.data?.data : null
    stockBacktestData.value = btRes.status === 'fulfilled' ? btRes.value?.data?.data : null
  } catch (e) {
    stockError.value = e.message
  } finally {
    loadingStockForecast.value = false
    loadingStockBacktest.value = false
  }
}

async function switchGroup(groupKey) {
  stockGroup.value = groupKey
  stockForecastData.value = null
  stockBacktestData.value = null
  selectedTicker.value = null
  const first = filteredTickers.value[0]
  if (first) await loadStockData(first.ticker)
}

async function onSessionChange() {
  if (selectedTicker.value) await loadStockData(selectedTicker.value)
}

async function loadSessions() {
  loadingSessions.value = true
  try {
    const res = await listSessions(20, 0)
    sessions.value = (res?.data?.data?.sessions || []).filter(s => s.status === 'completed')
  } catch {
    sessions.value = []
  } finally {
    loadingSessions.value = false
  }
}

function formatWeek(weekStr) {
  if (!weekStr) return '—'
  return weekStr
}

onMounted(() => {
  // Macro tab initial load
  loadMetric('ccl_index')
  loadAllBacktests()
  // Stock tab preloads
  loadStockTickers()
  loadSessions()
})
</script>

<template>
  <div class="dashboard">
    <header class="dashboard-header">
      <h1>預測準確度 Dashboard</h1>
      <p class="subtitle">基於歷史數據嘅回測驗證同預測分析</p>
    </header>

    <!-- Tab switcher -->
    <div class="tab-switcher">
      <button
        :class="['tab-btn', { active: activeTab === 'macro' }]"
        @click="activeTab = 'macro'"
      >宏觀指標</button>
      <button
        :class="['tab-btn', { active: activeTab === 'stock' }]"
        @click="activeTab = 'stock'"
      >股票 / 指數</button>
    </div>

    <!-- ── MACRO TAB ─────────────────────────────────────────────────────────── -->
    <div v-show="activeTab === 'macro'" class="dashboard-body">
      <!-- Metric selector -->
      <div class="metric-selector">
        <button
          v-for="m in METRICS"
          :key="m.key"
          :class="['metric-btn', { active: selectedMetric === m.key }]"
          @click="loadMetric(m.key)"
        >
          {{ m.label }}
        </button>
      </div>

      <div class="panels">
        <!-- Backtest panel -->
        <div class="panel backtest-panel">
          <h2>回測結果 — {{ selectedLabel }}</h2>
          <div v-if="loadingBacktest" class="loading">載入中...</div>
          <div v-else-if="backtestData" class="backtest-metrics">
            <div class="metric-card">
              <span class="metric-value" :style="{ color: mapeColor(backtestData.mape) }">
                {{ backtestData.mape != null ? backtestData.mape.toFixed(1) + '%' : 'N/A' }}
              </span>
              <span class="metric-label">MAPE</span>
            </div>
            <div class="metric-card">
              <span class="metric-value">
                {{ backtestData.rmse != null ? backtestData.rmse.toFixed(2) : 'N/A' }}
              </span>
              <span class="metric-label">RMSE</span>
            </div>
            <div class="metric-card">
              <span class="metric-value" :style="{ color: dirAccColor(backtestData.directional_accuracy) }">
                {{ backtestData.directional_accuracy != null ? (backtestData.directional_accuracy * 100).toFixed(0) + '%' : 'N/A' }}
              </span>
              <span class="metric-label">方向準確率</span>
            </div>
          </div>
          <div v-else class="no-data">暫無回測數據</div>
        </div>

        <!-- Forecast panel -->
        <div class="panel forecast-panel">
          <h2>12期預測 — {{ selectedLabel }}</h2>
          <div v-if="loadingForecast" class="loading">載入中...</div>
          <div v-else-if="forecastData && forecastData.forecasts" class="forecast-table">
            <table>
              <thead>
                <tr>
                  <th>期間</th>
                  <th>預測值</th>
                  <th>80% CI 下限</th>
                  <th>80% CI 上限</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(f, i) in forecastData.forecasts" :key="i">
                  <td>{{ f.period || `T+${i + 1}` }}</td>
                  <td class="val">{{ f.point != null ? f.point.toFixed(2) : 'N/A' }}</td>
                  <td class="ci">{{ f.ci_lower_80 != null ? f.ci_lower_80.toFixed(2) : '—' }}</td>
                  <td class="ci">{{ f.ci_upper_80 != null ? f.ci_upper_80.toFixed(2) : '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else class="no-data">暫無預測數據</div>
        </div>
      </div>

      <!-- Summary table -->
      <div class="panel summary-panel">
        <h2>全指標回測摘要</h2>
        <div v-if="loadingSummary" class="loading">載入中...</div>
        <table v-else-if="backtestSummary.length" class="summary-table">
          <thead>
            <tr>
              <th>指標</th>
              <th>MAPE</th>
              <th>RMSE</th>
              <th>方向準確率</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="b in backtestSummary" :key="b.metric" @click="loadMetric(b.metric)" class="clickable">
              <td>{{ b.label }}</td>
              <td :style="{ color: mapeColor(b.mape) }">{{ b.mape != null ? b.mape.toFixed(1) + '%' : 'N/A' }}</td>
              <td>{{ b.rmse != null ? b.rmse.toFixed(2) : 'N/A' }}</td>
              <td :style="{ color: dirAccColor(b.directional_accuracy) }">
                {{ b.directional_accuracy != null ? (b.directional_accuracy * 100).toFixed(0) + '%' : 'N/A' }}
              </td>
            </tr>
          </tbody>
        </table>
        <div v-else class="no-data">暫無數據</div>
      </div>
    </div>

    <!-- ── STOCK TAB ──────────────────────────────────────────────────────────── -->
    <div v-show="activeTab === 'stock'" class="dashboard-body">

      <!-- Group filter -->
      <div class="group-filter">
        <button
          v-for="g in STOCK_GROUPS"
          :key="g.key"
          :class="['group-btn', { active: stockGroup === g.key }]"
          @click="switchGroup(g.key)"
        >{{ g.label }}</button>
      </div>

      <!-- Ticker selector -->
      <div class="ticker-selector">
        <div v-if="loadingTickers" class="loading">載入股票列表...</div>
        <template v-else-if="filteredTickers.length">
          <button
            v-for="t in filteredTickers"
            :key="t.ticker"
            :class="['ticker-btn', { active: selectedTicker === t.ticker }]"
            @click="loadStockData(t.ticker)"
            :title="t.name_en || t.ticker"
          >
            <span class="ticker-code">{{ t.ticker }}</span>
            <span class="ticker-name">{{ t.name_zh || t.name_en || '' }}</span>
          </button>
        </template>
        <div v-else class="no-data">此分類暫無股票數據</div>
      </div>

      <!-- Session selector -->
      <div class="session-row">
        <label class="session-label">模擬 Session（社會信號疊加）：</label>
        <select
          class="session-select"
          v-model="selectedSession"
          @change="onSessionChange"
          :disabled="loadingSessions"
        >
          <option :value="null">— 不選擇（純技術預測）—</option>
          <option v-for="s in sessions" :key="s.id" :value="s.id">
            {{ s.id.slice(0, 8) }} — {{ s.seed_text ? s.seed_text.slice(0, 40) + '…' : '無描述' }}
          </option>
        </select>
        <span v-if="!selectedSession" class="session-hint">
          選擇模擬 session 以查看社會信號影響
        </span>
      </div>

      <!-- Stock content: error state -->
      <div v-if="stockError" class="error-banner">⚠ {{ stockError }}</div>

      <!-- Stock content: no ticker selected -->
      <div v-else-if="!selectedTicker" class="no-data" style="padding: 3rem; text-align: center;">
        請選擇一個股票 / 指數
      </div>

      <template v-else>
        <!-- Backtest badges row -->
        <div class="panel stock-backtest-panel">
          <h2>
            回測結果 —
            <span class="ticker-heading">{{ selectedTicker }}</span>
            <span v-if="selectedTickerMeta" class="ticker-heading-zh">
              {{ selectedTickerMeta.name_zh || selectedTickerMeta.name_en }}
            </span>
          </h2>
          <div v-if="loadingStockBacktest" class="loading">載入中...</div>
          <div v-else-if="stockBacktestData" class="backtest-metrics">
            <div class="metric-card">
              <span class="metric-value" :style="{ color: mapeColor(stockBacktestData.mape) }">
                {{ stockBacktestData.mape != null ? stockBacktestData.mape.toFixed(1) + '%' : 'N/A' }}
              </span>
              <span class="metric-label">MAPE</span>
            </div>
            <div class="metric-card">
              <span class="metric-value">
                {{ stockBacktestData.rmse != null ? stockBacktestData.rmse.toFixed(2) : 'N/A' }}
              </span>
              <span class="metric-label">RMSE</span>
            </div>
            <div class="metric-card">
              <span class="metric-value" :style="{ color: dirAccColor(stockBacktestData.directional_accuracy) }">
                {{ stockBacktestData.directional_accuracy != null
                  ? (stockBacktestData.directional_accuracy * 100).toFixed(0) + '%'
                  : 'N/A' }}
              </span>
              <span class="metric-label">方向準確率</span>
            </div>
          </div>
          <div v-else class="no-data">暫無回測數據</div>
        </div>

        <!-- Two-column: forecast table + signal panel -->
        <div class="stock-columns">

          <!-- Left: 12-Week Forecast Table -->
          <div class="panel forecast-panel">
            <h2>12週預測 — {{ selectedTicker }}</h2>
            <div v-if="loadingStockForecast" class="loading">載入中...</div>
            <div v-else-if="stockForecastData && stockForecastData.forecasts" class="forecast-table">
              <table>
                <thead>
                  <tr>
                    <th>週次</th>
                    <th>收市價</th>
                    <th>80% CI</th>
                    <th>95% CI</th>
                    <th v-if="selectedSession">訊號調整</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="(f, i) in stockForecastData.forecasts"
                    :key="i"
                    :class="{ 'signal-adjusted-row': f.signal_adjusted }"
                  >
                    <td>{{ formatWeek(f.week || f.period) || `W+${i + 1}` }}</td>
                    <td class="val">{{ f.close != null ? f.close.toFixed(2) : f.point != null ? f.point.toFixed(2) : 'N/A' }}</td>
                    <td class="ci">
                      {{ f.ci_lower_80 != null ? f.ci_lower_80.toFixed(2) : '—' }}
                      –
                      {{ f.ci_upper_80 != null ? f.ci_upper_80.toFixed(2) : '—' }}
                    </td>
                    <td class="ci">
                      {{ f.ci_lower_95 != null ? f.ci_lower_95.toFixed(2) : '—' }}
                      –
                      {{ f.ci_upper_95 != null ? f.ci_upper_95.toFixed(2) : '—' }}
                    </td>
                    <td v-if="selectedSession" class="ci">
                      {{ f.signal_adjusted ? '✓' : '—' }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-else class="no-data">暫無預測數據</div>
          </div>

          <!-- Right: Signal Breakdown Panel -->
          <div class="panel signal-panel">
            <h2>社會信號分解</h2>

            <!-- No session selected -->
            <div v-if="!selectedSession" class="signal-no-session">
              <div class="signal-no-session-icon">📊</div>
              <p>選擇模擬 session 以查看社會信號影響</p>
              <p class="signal-note">社會信號來自代理人情緒、信念系統同宏觀反饋，為純技術預測提供調整</p>
            </div>

            <!-- Session selected, loading -->
            <div v-else-if="loadingStockForecast" class="loading">載入信號...</div>

            <!-- Session selected, no signals -->
            <div v-else-if="!signals.length" class="no-data">此 session 暫無信號數據</div>

            <!-- Signal breakdown list -->
            <template v-else>
              <div class="signal-net">
                淨調整：
                <span
                  :class="['signal-net-value', netShift(signals) > 0 ? 'signal-bullish' : netShift(signals) < 0 ? 'signal-bearish' : 'signal-neutral']"
                >
                  {{ netShift(signals) > 0 ? '+' : '' }}{{ netShift(signals) != null ? netShift(signals).toFixed(2) : '0.00' }}%
                </span>
              </div>
              <div class="signal-list">
                <div
                  v-for="(sig, i) in signals"
                  :key="i"
                  :class="['signal-item', signalClass(sig.contribution)]"
                >
                  <span class="signal-icon">{{ signalIcon(sig.contribution) }}</span>
                  <span class="signal-name">{{ sig.name || sig.factor || `信號 ${i + 1}` }}</span>
                  <span class="signal-contribution">
                    {{ sig.contribution != null
                      ? (sig.contribution > 0 ? '+' : '') + (sig.contribution * 100).toFixed(2) + '%'
                      : '—' }}
                  </span>
                  <div class="signal-bar-track">
                    <div
                      class="signal-bar-fill"
                      :style="{
                        width: Math.min(Math.abs(sig.contribution) * 1000, 100) + '%',
                        background: sig.contribution > 0.001 ? '#22c55e' : sig.contribution < -0.001 ? '#ef4444' : '#9ca3af'
                      }"
                    ></div>
                  </div>
                  <p v-if="sig.description" class="signal-desc">{{ sig.description }}</p>
                </div>
              </div>
            </template>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.dashboard {
  max-width: 1200px;
  margin: 0 auto;
  padding: 2rem;
  font-family: var(--font-sans);
}
.dashboard-header {
  margin-bottom: 1.5rem;
}
.dashboard-header h1 {
  font-size: 1.8rem;
  margin: 0 0 0.5rem;
  color: var(--text-primary);
}
.subtitle {
  color: var(--text-secondary);
  margin: 0;
}

/* ── Tab switcher ─────────────────────────────────────────────────────────── */
.tab-switcher {
  display: flex;
  gap: 0;
  border-bottom: 2px solid var(--border-color);
  margin-bottom: 1.5rem;
}
.tab-btn {
  padding: 0.6rem 1.4rem;
  border: none;
  border-bottom: 2px solid transparent;
  background: none;
  cursor: pointer;
  font-size: 0.95rem;
  color: var(--text-muted);
  margin-bottom: -2px;
  transition: var(--transition);
}
.tab-btn:hover {
  color: var(--accent-blue);
}
.tab-btn.active {
  color: var(--accent-blue);
  border-bottom-color: var(--accent-blue);
  font-weight: 600;
}

/* ── Macro tab ─────────────────────────────────────────────────────────────── */
.metric-selector {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-bottom: 1.5rem;
}
.metric-btn {
  padding: 0.4rem 0.8rem;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-card);
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 0.85rem;
  transition: var(--transition);
}
.metric-btn:hover {
  border-color: var(--accent-blue);
  color: var(--accent-blue);
}
.metric-btn.active {
  background: var(--accent-blue);
  color: #0d1117;
  border-color: var(--accent-blue);
}
.panels {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1.5rem;
  margin-bottom: 1.5rem;
}
.panel {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 1.5rem;
}
.panel h2 {
  font-size: 1.1rem;
  margin: 0 0 1rem;
  color: var(--text-primary);
}
.backtest-metrics {
  display: flex;
  gap: 1.5rem;
}
.metric-card {
  display: flex;
  flex-direction: column;
  align-items: center;
}
.metric-value {
  font-size: 1.6rem;
  font-weight: 700;
  font-family: var(--font-mono);
}
.metric-label {
  font-size: 0.8rem;
  color: var(--text-muted);
  margin-top: 0.25rem;
}
.loading {
  color: var(--text-muted);
  padding: 2rem;
  text-align: center;
}
.no-data {
  color: var(--text-muted);
  padding: 2rem;
  text-align: center;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
  font-family: var(--font-mono);
}
th {
  text-align: left;
  padding: 0.5rem;
  border-bottom: 2px solid var(--border-color);
  color: var(--accent-blue);
  font-weight: 600;
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
td {
  padding: 0.5rem;
  border-bottom: 1px solid var(--border-color);
  color: var(--text-secondary);
}
td.val {
  font-weight: 600;
  color: var(--text-primary);
}
td.ci {
  color: var(--text-muted);
}
.summary-table {
  width: 100%;
}
.clickable {
  cursor: pointer;
}
.clickable:hover {
  background: rgba(0, 212, 255, 0.04);
}
.summary-panel {
  grid-column: span 2;
}

/* ── Stock tab — group filter ─────────────────────────────────────────────── */
.group-filter {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 1rem;
  flex-wrap: wrap;
}
.group-btn {
  padding: 0.4rem 1rem;
  border: 1px solid var(--border-color);
  border-radius: 20px;
  background: var(--bg-card);
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 0.85rem;
  font-weight: 500;
  transition: var(--transition);
}
.group-btn:hover {
  border-color: var(--accent-blue);
  color: var(--accent-blue);
}
.group-btn.active {
  background: var(--accent-blue);
  color: #0d1117;
  border-color: var(--accent-blue);
}

/* ── Stock tab — ticker selector ─────────────────────────────────────────── */
.ticker-selector {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-bottom: 1.25rem;
  padding: 0.75rem 1rem;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  min-height: 2.5rem;
  align-items: flex-start;
}
.ticker-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 0.35rem 0.65rem;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-card);
  color: var(--text-secondary);
  cursor: pointer;
  transition: var(--transition);
  min-width: 72px;
}
.ticker-btn:hover {
  border-color: var(--accent-blue);
}
.ticker-btn.active {
  background: var(--accent-blue);
  border-color: var(--accent-blue);
  color: #0d1117;
}
.ticker-code {
  font-size: 0.8rem;
  font-weight: 700;
  letter-spacing: 0.01em;
}
.ticker-name {
  font-size: 0.7rem;
  color: inherit;
  opacity: 0.75;
  max-width: 80px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ── Stock tab — session selector ─────────────────────────────────────────── */
.session-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 1.25rem;
  flex-wrap: wrap;
}
.session-label {
  font-size: 0.85rem;
  color: var(--text-secondary);
  white-space: nowrap;
}
.session-select {
  padding: 0.35rem 0.6rem;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  font-size: 0.85rem;
  background: var(--bg-input);
  color: var(--text-primary);
  min-width: 240px;
  max-width: 400px;
}
.session-select option {
  background: var(--bg-input);
}
.session-hint {
  font-size: 0.8rem;
  color: var(--text-muted);
  font-style: italic;
}

/* ── Stock tab — error banner ─────────────────────────────────────────────── */
.error-banner {
  background: var(--accent-red-light);
  border: 1px solid rgba(255, 68, 68, 0.3);
  border-radius: 6px;
  color: var(--accent-red);
  padding: 0.75rem 1rem;
  margin-bottom: 1rem;
  font-size: 0.9rem;
}

/* ── Stock tab — backtest panel ───────────────────────────────────────────── */
.stock-backtest-panel {
  margin-bottom: 1.25rem;
}
.ticker-heading {
  font-family: var(--font-mono);
  font-size: 1rem;
  color: var(--accent-blue);
}
.ticker-heading-zh {
  font-size: 0.95rem;
  color: var(--text-secondary);
  margin-left: 0.4rem;
}

/* ── Stock tab — two-column layout ───────────────────────────────────────── */
.stock-columns {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1.25rem;
}

/* ── Stock tab — signal adjusted row ─────────────────────────────────────── */
.signal-adjusted-row {
  background: rgba(0, 217, 101, 0.06);
}

/* ── Stock tab — signal panel ────────────────────────────────────────────── */
.signal-panel {
  display: flex;
  flex-direction: column;
  gap: 0;
}
.signal-no-session {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 2rem 1rem;
  color: var(--text-muted);
  text-align: center;
  flex: 1;
}
.signal-no-session-icon {
  font-size: 2.5rem;
  margin-bottom: 0.75rem;
}
.signal-no-session p {
  margin: 0.3rem 0;
  font-size: 0.9rem;
}
.signal-note {
  font-size: 0.78rem !important;
  color: var(--text-muted);
}
.signal-net {
  font-size: 0.9rem;
  color: var(--text-secondary);
  margin-bottom: 0.75rem;
  font-weight: 500;
}
.signal-net-value {
  font-weight: 700;
  font-size: 1rem;
}
.signal-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  overflow-y: auto;
  max-height: 380px;
}
.signal-item {
  display: grid;
  grid-template-columns: 1.2rem 1fr auto;
  grid-template-rows: auto auto;
  gap: 0.15rem 0.5rem;
  padding: 0.5rem 0.6rem;
  border-radius: 6px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  font-size: 0.85rem;
  align-items: center;
}
.signal-icon {
  font-size: 0.8rem;
  font-weight: 700;
  grid-row: 1;
  grid-column: 1;
}
.signal-name {
  grid-row: 1;
  grid-column: 2;
  color: var(--text-secondary);
  font-weight: 500;
}
.signal-contribution {
  grid-row: 1;
  grid-column: 3;
  font-weight: 700;
  font-size: 0.85rem;
  text-align: right;
}
.signal-bar-track {
  grid-row: 2;
  grid-column: 1 / 4;
  height: 4px;
  background: var(--border-color);
  border-radius: 2px;
  overflow: hidden;
}
.signal-bar-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.3s;
}
.signal-desc {
  grid-row: 3;
  grid-column: 1 / 4;
  margin: 0.15rem 0 0;
  font-size: 0.75rem;
  color: var(--text-muted);
}

/* Signal colour classes */
.signal-bullish {
  color: #00d965;
  border-color: rgba(0, 217, 101, 0.3) !important;
  background: rgba(0, 217, 101, 0.06) !important;
}
.signal-bearish {
  color: #ff4444;
  border-color: rgba(255, 68, 68, 0.3) !important;
  background: rgba(255, 68, 68, 0.06) !important;
}
.signal-neutral {
  color: var(--text-muted);
}

/* Responsive */
@media (max-width: 768px) {
  .panels,
  .stock-columns {
    grid-template-columns: 1fr;
  }
  .summary-panel {
    grid-column: span 1;
  }
  .session-select {
    min-width: 200px;
  }
}
</style>
