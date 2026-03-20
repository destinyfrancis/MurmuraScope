<script setup>
import { ref, onMounted, computed } from 'vue'
import { getCrossDomainValidation } from '../api/simulation.js'

const loading = ref(true)
const error = ref(null)
const data = ref(null)

const domains = computed(() => data.value?.domains || [])
const aggregate = computed(() => data.value?.aggregate || null)

const DOMAIN_LABELS = {
  hk_macro: '香港宏觀',
  us_markets: '美國市場',
  geopolitical: '地緣政治',
}

const GRADE_COLORS = {
  A: '#22c55e',
  B: '#14b8a6',
  C: '#eab308',
  D: '#f97316',
  F: '#ef4444',
}

function gradeColor(grade) {
  return GRADE_COLORS[grade] || 'var(--text-muted)'
}

function gradeBg(grade) {
  const color = GRADE_COLORS[grade]
  if (!color) return 'transparent'
  return color + '18'
}

onMounted(async () => {
  try {
    const res = await getCrossDomainValidation()
    data.value = res.data?.data || res.data
  } catch (e) {
    error.value = e.response?.data?.detail || e.message || '載入失敗'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="cross-domain">
    <h3 class="panel-heading">跨域驗證結果</h3>

    <div v-if="loading" class="state-msg">載入中...</div>
    <div v-else-if="error" class="state-msg error">{{ error }}</div>

    <template v-else>
      <div v-if="!domains.length" class="state-msg">暫無驗證數據</div>

      <div v-else class="domain-cards">
        <div
          v-for="d in domains"
          :key="d.domain"
          class="domain-card"
        >
          <div class="card-header">
            <span class="domain-name">{{ DOMAIN_LABELS[d.domain] || d.domain }}</span>
            <span
              class="grade-badge"
              :style="{ color: gradeColor(d.grade), background: gradeBg(d.grade), borderColor: gradeColor(d.grade) }"
            >
              {{ d.grade }}
            </span>
          </div>
          <div class="card-body">
            <div class="card-stat">
              <span class="card-stat-label">分數</span>
              <span class="card-stat-value">{{ d.score != null ? d.score.toFixed(2) : '---' }}</span>
            </div>
            <div class="card-stat">
              <span class="card-stat-label">指標數</span>
              <span class="card-stat-value">{{ d.metrics_validated ?? d.metrics_count ?? '---' }}</span>
            </div>
          </div>
        </div>
      </div>

      <div v-if="aggregate" class="aggregate-section">
        <div class="aggregate-row">
          <span class="aggregate-label">綜合評級</span>
          <span
            class="grade-badge grade-badge-lg"
            :style="{ color: gradeColor(aggregate.grade), background: gradeBg(aggregate.grade), borderColor: gradeColor(aggregate.grade) }"
          >
            {{ aggregate.grade }}
          </span>
          <span v-if="aggregate.credibility_summary" class="credibility-text">
            {{ aggregate.credibility_summary }}
          </span>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.cross-domain {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 1.25rem;
}
.panel-heading {
  font-size: 1rem;
  font-weight: 600;
  margin: 0 0 1rem;
  color: var(--text-primary);
}
.state-msg {
  text-align: center;
  padding: 2rem;
  color: var(--text-muted);
}
.state-msg.error {
  color: var(--accent-red);
}
.domain-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.75rem;
  margin-bottom: 1rem;
}
.domain-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 1rem;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.75rem;
}
.domain-name {
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--text-primary);
}
.grade-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  font-weight: 800;
  font-size: 0.9rem;
  border: 1px solid;
}
.grade-badge-lg {
  width: 36px;
  height: 36px;
  font-size: 1.1rem;
}
.card-body {
  display: flex;
  gap: 1rem;
}
.card-stat {
  display: flex;
  flex-direction: column;
}
.card-stat-label {
  font-size: 0.72rem;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.card-stat-value {
  font-size: 1.1rem;
  font-weight: 700;
  font-family: var(--font-mono);
  color: var(--text-primary);
}
.aggregate-section {
  border-top: 1px solid var(--border-color);
  padding-top: 0.75rem;
}
.aggregate-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.aggregate-label {
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--text-secondary);
}
.credibility-text {
  font-size: 0.82rem;
  color: var(--text-secondary);
  line-height: 1.5;
}

@media (max-width: 640px) {
  .domain-cards {
    grid-template-columns: 1fr;
  }
}
</style>
