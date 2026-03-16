<script setup>
import { ref, computed, watch } from 'vue'
import { compareSessions } from '../api/simulation.js'
import SessionMetricsGrid from './charts/SessionMetricsGrid.vue'
import TimelineChart from './charts/TimelineChart.vue'
import AgentSentimentDistribution from './charts/AgentSentimentDistribution.vue'
import SentimentBarChart from './charts/SentimentBarChart.vue'

const props = defineProps({
  sessionA: { type: String, default: '' },
  sessionB: { type: String, default: '' },
})

const loading = ref(false)
const error = ref(null)
const compData = ref(null)

const sessionAInput = ref(props.sessionA)
const sessionBInput = ref(props.sessionB)

watch(() => props.sessionA, (v) => { sessionAInput.value = v })
watch(() => props.sessionB, (v) => { sessionBInput.value = v })

async function loadComparison() {
  if (!sessionAInput.value || !sessionBInput.value) return
  loading.value = true
  error.value = null
  compData.value = null
  try {
    const res = await compareSessions(sessionAInput.value, sessionBInput.value)
    compData.value = res.data?.data || res.data
  } catch (err) {
    error.value = err.response?.data?.detail || err.message || '比較失敗'
  } finally {
    loading.value = false
  }
}

const chartRounds = computed(() => {
  if (!compData.value) return []
  const roundsA = new Set((compData.value.session_a.sentiment_by_round || []).map((r) => r.round_number))
  const roundsB = new Set((compData.value.session_b.sentiment_by_round || []).map((r) => r.round_number))
  const all = new Set([...roundsA, ...roundsB])
  return [...all].sort((x, y) => x - y)
})

function getSentimentRow(session, roundNum) {
  const rows = (compData.value?.[session]?.sentiment_by_round || [])
  return rows.find((r) => r.round_number === roundNum) || { pos: 0, neg: 0, neu: 0, total: 0 }
}
</script>

<template>
  <div class="scenario-comparison">
    <div class="comp-header">
      <h3 class="comp-title">情景對比分析</h3>
      <div class="session-inputs">
        <div class="session-input-group">
          <label class="input-label">情景 A</label>
          <input v-model="sessionAInput" class="session-input" placeholder="工作階段 ID" />
        </div>
        <span class="vs-sep">VS</span>
        <div class="session-input-group">
          <label class="input-label">情景 B</label>
          <input v-model="sessionBInput" class="session-input" placeholder="工作階段 ID" />
        </div>
        <button
          class="compare-btn"
          :disabled="loading || !sessionAInput || !sessionBInput"
          @click="loadComparison"
        >
          {{ loading ? '載入中...' : '對比' }}
        </button>
      </div>
    </div>

    <p v-if="error" class="comp-error">{{ error }}</p>

    <div v-if="compData" class="comp-body">
      <!-- Fork indicator banner -->
      <div v-if="compData.fork_info" class="fork-banner">
        <span class="fork-icon">&#x2442;</span>
        <span>
          此兩個情景共享同一父模擬。
          <strong v-if="compData.fork_info.fork_round != null">
            分叉輪次：第 {{ compData.fork_info.fork_round }} 輪
          </strong>
          <template v-else>（從頭開始）</template>
          <em v-if="compData.fork_info.label">— {{ compData.fork_info.label }}</em>
        </span>
      </div>

      <!-- Key metrics + memory divergence + key events -->
      <SessionMetricsGrid :comp-data="compData" />

      <!-- Timeline divergence chart -->
      <div class="section-title">情感走勢對比（正面情感比率）</div>
      <TimelineChart
        :chart-rounds="chartRounds"
        :get-sentiment-row="getSentimentRow"
        :fork-info="compData.fork_info"
      />

      <!-- Agent sentiment distribution -->
      <div class="section-title">整體代理情感分布</div>
      <AgentSentimentDistribution :comp-data="compData" />

      <!-- Sentiment bar chart comparison -->
      <div class="section-title">每輪情感分布對比</div>
      <SentimentBarChart
        :chart-rounds="chartRounds"
        :get-sentiment-row="getSentimentRow"
      />
    </div>

    <div v-if="!compData && !loading && !error" class="comp-empty">
      輸入兩個工作階段 ID 開始對比
    </div>
  </div>
</template>

<style scoped>
.scenario-comparison {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 24px;
}

.comp-title {
  font-size: 16px;
  font-weight: 600;
  margin: 0 0 16px;
}

.comp-header {
  margin-bottom: 20px;
}

.session-inputs {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}

.session-input-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.input-label {
  font-size: 12px;
  color: var(--text-muted);
}

.session-input {
  padding: 8px 10px;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-size: 13px;
  outline: none;
  width: 240px;
}

.session-input:focus {
  border-color: var(--accent-blue);
}

.vs-sep {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-muted);
  padding-bottom: 8px;
}

.compare-btn {
  padding: 9px 20px;
  background: var(--accent-blue);
  color: #fff;
  border: none;
  border-radius: var(--radius-sm);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: var(--transition);
}

.compare-btn:hover:not(:disabled) {
  background: #3d8be0;
}

.compare-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.comp-error {
  color: var(--accent-red);
  font-size: 13px;
  margin-bottom: 12px;
}

.comp-body {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 10px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border-color);
}

/* Fork banner */
.fork-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: rgba(167, 139, 250, 0.08);
  border: 1px solid rgba(167, 139, 250, 0.25);
  border-radius: var(--radius-sm);
  font-size: 13px;
  color: var(--text-secondary);
}

.fork-icon {
  color: #a78bfa;
  font-size: 16px;
}

.no-data {
  font-size: 13px;
  color: var(--text-muted);
  text-align: center;
  padding: 20px;
}

.comp-empty {
  text-align: center;
  padding: 40px;
  color: var(--text-muted);
  font-size: 14px;
}
</style>
