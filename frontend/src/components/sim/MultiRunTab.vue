<script setup>
import { ref, computed, onUnmounted } from 'vue'
import { triggerMultiRun, getMultiRun } from '../../api/simulation.js'

const props = defineProps({
  sessionId: { type: String, required: true },
  simCompleted: { type: Boolean, default: false },
})

const result = ref(null)
const polling = ref(false)
const loading = ref(false)
const error = ref(null)
let pollTimer = null

async function runEnsemble() {
  loading.value = true
  error.value = null
  try {
    await triggerMultiRun(props.sessionId)
    startPolling()
  } catch (e) {
    error.value = e.message || 'Failed to trigger ensemble'
  } finally {
    loading.value = false
  }
}

function startPolling() {
  polling.value = true
  let pollCount = 0
  const MAX_POLLS = 150  // 150 × 2s = 5 minutes
  pollTimer = setInterval(async () => {
    pollCount++
    if (pollCount > MAX_POLLS) {
      stopPolling()
      error.value = '多次執行逾時（超過5分鐘），請重試'
      return
    }
    try {
      const res = await getMultiRun(props.sessionId)
      const multiRunResult = res.data?.data?.result
      if (multiRunResult) {
        result.value = multiRunResult
        stopPolling()
      }
    } catch (e) {
      stopPolling()
      error.value = e.message || '獲取結果失敗'
    }
  }, 2000)
}

function stopPolling() {
  polling.value = false
  clearInterval(pollTimer)
  pollTimer = null
}

onUnmounted(stopPolling)

function resetEnsemble() {
  result.value = null
}

const outcomes = computed(() => {
  if (!result.value) return []
  try {
    const dist = JSON.parse(result.value.outcome_distribution_json)
    const cis  = JSON.parse(result.value.confidence_intervals_json)
    return Object.entries(dist).map(([label, prob]) => ({
      label,
      prob: Math.round(prob * 100),
      lo:   Math.round((cis[label]?.[0] ?? prob) * 100),
      hi:   Math.round((cis[label]?.[1] ?? prob) * 100),
    })).sort((a, b) => b.prob - a.prob)
  } catch { return [] }
})
</script>

<template>
  <div class="mr-tab">
    <!-- Empty state: not yet run -->
    <div v-if="!result && !polling" class="mr-idle">
      <p class="mr-desc">
        Phase B 隨機集成預測：以標準模擬為基準，運行多次零成本試驗，輸出概率分佈同置信區間。
      </p>
      <button
        class="mr-btn"
        :disabled="loading || !simCompleted"
        @click="runEnsemble"
      >
        {{ loading ? '啟動中…' : !simCompleted ? '等待模擬完成' : '▶ Run Ensemble' }}
      </button>
      <p v-if="error" class="mr-error">{{ error }}</p>
    </div>

    <!-- Running: polling -->
    <div v-else-if="polling" class="mr-running">
      <div class="mr-spinner" />
      <span class="mr-run-label">Phase B 運行中…</span>
    </div>

    <!-- Results -->
    <div v-else-if="result" class="mr-results">
      <div class="mr-header">
        Phase B Ensemble · {{ result.trial_count }} trials
      </div>
      <div class="mr-bars">
        <div v-for="o in outcomes" :key="o.label" class="mr-bar-row">
          <span class="mr-label">{{ o.label }}</span>
          <div class="mr-bar-bg">
            <div class="mr-bar-fill" :style="{ width: o.prob + '%' }" />
          </div>
          <span class="mr-pct">{{ o.prob }}%</span>
          <span class="mr-ci">[{{ o.lo }}–{{ o.hi }}%]</span>
        </div>
      </div>
      <div class="mr-summary" v-if="result.avg_tipping_point_round || result.faction_stability_score">
        <span v-if="result.avg_tipping_point_round">
          Avg tipping pt: R{{ result.avg_tipping_point_round?.toFixed(1) }}
        </span>
        <span v-if="result.faction_stability_score">
          Stability: {{ (result.faction_stability_score * 100).toFixed(0) }}%
        </span>
      </div>
      <button class="mr-btn-sm" @click="resetEnsemble">重新執行</button>
    </div>
  </div>
</template>

<style scoped>
.mr-tab { flex: 1; padding: 12px; overflow-y: auto; display: flex; flex-direction: column; }
.mr-idle { display: flex; flex-direction: column; gap: 12px; }
.mr-desc { font-size: 11px; color: var(--text-muted); line-height: 1.5; }
.mr-btn {
  align-self: flex-start;
  padding: 8px 16px;
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: 5px;
  font-family: var(--font-mono);
  font-size: 11px;
  cursor: pointer;
}
.mr-btn:disabled { opacity: .4; cursor: not-allowed; }
.mr-error { font-size: 10px; color: var(--accent-danger); }
.mr-running { display: flex; align-items: center; gap: 10px; padding: 20px 0; }
.mr-spinner {
  width: 20px; height: 20px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin .8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.mr-run-label { font-family: var(--font-mono); font-size: 11px; color: var(--text-muted); }
.mr-header { font-family: var(--font-mono); font-size: 10px; color: var(--text-muted); margin-bottom: 12px; }
.mr-bars { display: flex; flex-direction: column; gap: 6px; }
.mr-bar-row { display: flex; align-items: center; gap: 7px; }
.mr-label { font-size: 10px; color: var(--text-primary); flex: 0 0 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mr-bar-bg { flex: 1; height: 6px; background: var(--border); border-radius: 3px; overflow: hidden; }
.mr-bar-fill { height: 100%; background: var(--accent); border-radius: 3px; transition: width .5s; }
.mr-pct { font-family: var(--font-mono); font-size: 9px; color: var(--text-primary); min-width: 28px; }
.mr-ci { font-family: var(--font-mono); font-size: 8px; color: var(--text-muted); }
.mr-summary { margin-top: 10px; display: flex; gap: 14px; font-family: var(--font-mono); font-size: 9px; color: var(--text-muted); }
.mr-btn-sm { margin-top: 12px; align-self: flex-start; padding: 4px 10px; background: transparent; border: 1px solid var(--border); border-radius: 4px; font-size: 10px; color: var(--text-muted); cursor: pointer; }
</style>
