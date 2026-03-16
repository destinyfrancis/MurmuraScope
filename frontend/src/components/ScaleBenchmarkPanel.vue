<script setup>
import { ref, computed, onMounted } from 'vue'
import { getBenchmarks, getBenchmarkResult, runBenchmark } from '@/api/simulation'

const benchmarks = ref([])
const loading = ref(false)
const error = ref(null)
const runningTarget = ref(null)
const expandedTarget = ref(null)

const TARGETS = [
  { key: '1k', label: '1K', agents: 1000, rounds: 10, maxRound: 30, maxMem: 4096, maxTotal: 300 },
  { key: '3k', label: '3K', agents: 3000, rounds: 10, maxRound: 90, maxMem: 8192, maxTotal: 900 },
  { key: '10k', label: '10K', agents: 10000, rounds: 5, maxRound: 300, maxMem: 16384, maxTotal: 1500 },
]

async function fetchBenchmarks() {
  loading.value = true
  error.value = null
  try {
    const res = await getBenchmarks()
    benchmarks.value = res.data?.data || []
  } catch (err) {
    error.value = `載入失敗：${err.message || '未知錯誤'}`
  } finally {
    loading.value = false
  }
}

async function handleRun(target) {
  if (runningTarget.value) return
  runningTarget.value = target
  try {
    await runBenchmark(target)
    // Refresh after a short delay
    setTimeout(fetchBenchmarks, 2000)
  } catch (err) {
    error.value = `執行失敗：${err.message || '未知錯誤'}`
  } finally {
    runningTarget.value = null
  }
}

function toggleExpand(target) {
  expandedTarget.value = expandedTarget.value === target ? null : target
}

function getLatestResult(target) {
  return benchmarks.value.find(b => b.target === target) || null
}

function passClass(actual, sla) {
  if (actual == null) return ''
  return actual <= sla ? 'sla-pass' : 'sla-fail'
}

function formatTime(seconds) {
  if (seconds == null) return '—'
  if (seconds < 1) return `${(seconds * 1000).toFixed(0)}ms`
  return `${seconds.toFixed(1)}s`
}

function formatMem(mb) {
  if (mb == null) return '—'
  if (mb > 1024) return `${(mb / 1024).toFixed(1)} GB`
  return `${Math.round(mb)} MB`
}

function formatDate(dateStr) {
  if (!dateStr) return '—'
  const d = new Date(dateStr)
  return d.toLocaleDateString('zh-HK', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

onMounted(fetchBenchmarks)
</script>

<template>
  <div class="scale-panel">
    <div class="sp-header">
      <h2 class="sp-title">效能基準測試</h2>
      <p class="sp-subtitle">監測模擬引擎在不同規模下的性能</p>
    </div>

    <div v-if="loading && benchmarks.length === 0" class="state-msg">
      <span class="spinner" /> 載入中...
    </div>
    <div v-else-if="error" class="state-msg state-error">{{ error }}</div>

    <div class="target-grid">
      <div
        v-for="target in TARGETS"
        :key="target.key"
        class="target-card"
        :class="{ expanded: expandedTarget === target.key }"
      >
        <div class="target-header" @click="toggleExpand(target.key)">
          <div class="target-label-area">
            <span class="target-badge">{{ target.label }}</span>
            <span class="target-desc">{{ target.agents }} agents / {{ target.rounds }} rounds</span>
          </div>
          <div class="target-status">
            <template v-if="getLatestResult(target.key)">
              <span
                class="status-dot"
                :class="getLatestResult(target.key).passed ? 'dot-pass' : 'dot-fail'"
              />
              <span class="status-label">
                {{ getLatestResult(target.key).passed ? '通過' : '未達標' }}
              </span>
            </template>
            <span v-else class="status-label status-na">未測試</span>
          </div>
          <button
            class="run-btn"
            :disabled="runningTarget != null"
            @click.stop="handleRun(target.key)"
          >
            {{ runningTarget === target.key ? '執行中...' : '執行' }}
          </button>
        </div>

        <!-- SLA table -->
        <div v-if="expandedTarget === target.key" class="target-details">
          <table class="sla-table">
            <thead>
              <tr>
                <th>指標</th>
                <th>SLA 上限</th>
                <th>實際數值</th>
                <th>狀態</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>每輪時間</td>
                <td>{{ formatTime(target.maxRound) }}</td>
                <td :class="passClass(getLatestResult(target.key)?.avg_round_time, target.maxRound)">
                  {{ formatTime(getLatestResult(target.key)?.avg_round_time) }}
                </td>
                <td>
                  <span v-if="getLatestResult(target.key)?.avg_round_time != null" :class="passClass(getLatestResult(target.key)?.avg_round_time, target.maxRound)">
                    {{ getLatestResult(target.key)?.avg_round_time <= target.maxRound ? '通過' : '超標' }}
                  </span>
                  <span v-else>—</span>
                </td>
              </tr>
              <tr>
                <td>最大記憶體</td>
                <td>{{ formatMem(target.maxMem) }}</td>
                <td :class="passClass(getLatestResult(target.key)?.peak_memory_mb, target.maxMem)">
                  {{ formatMem(getLatestResult(target.key)?.peak_memory_mb) }}
                </td>
                <td>
                  <span v-if="getLatestResult(target.key)?.peak_memory_mb != null" :class="passClass(getLatestResult(target.key)?.peak_memory_mb, target.maxMem)">
                    {{ getLatestResult(target.key)?.peak_memory_mb <= target.maxMem ? '通過' : '超標' }}
                  </span>
                  <span v-else>—</span>
                </td>
              </tr>
              <tr>
                <td>總耗時</td>
                <td>{{ formatTime(target.maxTotal) }}</td>
                <td :class="passClass(getLatestResult(target.key)?.total_time, target.maxTotal)">
                  {{ formatTime(getLatestResult(target.key)?.total_time) }}
                </td>
                <td>
                  <span v-if="getLatestResult(target.key)?.total_time != null" :class="passClass(getLatestResult(target.key)?.total_time, target.maxTotal)">
                    {{ getLatestResult(target.key)?.total_time <= target.maxTotal ? '通過' : '超標' }}
                  </span>
                  <span v-else>—</span>
                </td>
              </tr>
            </tbody>
          </table>

          <!-- Bottlenecks -->
          <div v-if="getLatestResult(target.key)?.bottlenecks?.length" class="bottleneck-section">
            <div class="section-label">瓶頸分析</div>
            <div class="bottleneck-list">
              <div
                v-for="(b, bi) in getLatestResult(target.key).bottlenecks"
                :key="bi"
                class="bottleneck-item"
              >
                <span class="bn-name">{{ b.hook || b.name }}</span>
                <span class="bn-time">{{ formatTime(b.avg_time || b.time) }}</span>
              </div>
            </div>
          </div>

          <div v-if="getLatestResult(target.key)?.created_at" class="test-date">
            最後測試: {{ formatDate(getLatestResult(target.key).created_at) }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.scale-panel {
  max-width: 800px;
  margin: 0 auto;
}

.sp-header { margin-bottom: 20px; }

.sp-title {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 4px;
}

.sp-subtitle {
  font-size: 13px;
  color: var(--text-muted);
  margin: 0;
}

.state-msg {
  text-align: center;
  padding: 40px;
  color: var(--text-muted);
  font-size: 13px;
}

.state-error { color: var(--accent-red); }

.spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid var(--accent-blue);
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
  margin-right: 6px;
  vertical-align: middle;
}

@keyframes spin { to { transform: rotate(360deg); } }

.target-grid {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.target-card {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  overflow: hidden;
  transition: border-color 0.2s;
}

.target-card.expanded { border-color: var(--accent-blue); }

.target-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  cursor: pointer;
}

.target-header:hover { background: var(--bg-secondary); }

.target-label-area { flex: 1; }

.target-badge {
  font-size: 16px;
  font-weight: 700;
  color: var(--accent-blue);
  margin-right: 8px;
}

.target-desc {
  font-size: 12px;
  color: var(--text-muted);
}

.target-status {
  display: flex;
  align-items: center;
  gap: 6px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.dot-pass { background: #22c55e; }
.dot-fail { background: #ef4444; }

.status-label { font-size: 12px; font-weight: 600; }
.status-na { color: var(--text-muted); }

.run-btn {
  padding: 6px 14px;
  background: var(--accent-blue);
  color: #0d1117;
  border: none;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
}

.run-btn:hover { background: #1d4ed8; }
.run-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.target-details {
  padding: 0 16px 16px;
  border-top: 1px solid var(--border-color);
}

.sla-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  margin-top: 12px;
}

.sla-table th {
  text-align: left;
  padding: 6px 10px;
  background: var(--bg-secondary);
  color: var(--text-muted);
  font-weight: 500;
  border-bottom: 1px solid var(--border-color);
}

.sla-table td {
  padding: 6px 10px;
  border-bottom: 1px solid var(--border-color);
  color: var(--text-secondary);
}

.sla-pass { color: #059669; font-weight: 600; }
.sla-fail { color: #DC2626; font-weight: 600; }

.bottleneck-section { margin-top: 12px; }

.section-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
  margin-bottom: 6px;
}

.bottleneck-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.bottleneck-item {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  padding: 4px 8px;
  background: var(--bg-secondary);
  border-radius: 4px;
}

.bn-name { color: var(--text-secondary); }
.bn-time { font-weight: 600; color: var(--accent-orange); }

.test-date {
  margin-top: 10px;
  font-size: 10px;
  color: var(--text-muted);
  text-align: right;
}
</style>
