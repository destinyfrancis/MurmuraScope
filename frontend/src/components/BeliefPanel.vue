<script setup>
import { ref, watch, onMounted } from 'vue'
import { getAgentBeliefs } from '@/api/simulation'

const props = defineProps({
  sessionId: { type: String, required: true },
  agentId: { type: Number, required: true },
})

const beliefs = ref([])
const loading = ref(false)
const error = ref(null)

const TOPIC_LABELS = {
  property_outlook: '樓市前景',
  economy_outlook: '經濟前景',
  immigration_stance: '移民態度',
  government_trust: '政府信任',
  social_stability: '社會穩定',
  ai_impact: 'AI 影響',
}

const TOPIC_ICONS = {
  property_outlook: '🏠',
  economy_outlook: '📈',
  immigration_stance: '✈️',
  government_trust: '🏛️',
  social_stability: '⚖️',
  ai_impact: '🤖',
}

async function fetchBeliefs() {
  if (!props.sessionId || !props.agentId) return
  loading.value = true
  error.value = null
  try {
    const res = await getAgentBeliefs(props.sessionId, props.agentId)
    beliefs.value = res.data?.data || []
  } catch (err) {
    error.value = `載入失敗：${err.message || '未知錯誤'}`
  } finally {
    loading.value = false
  }
}

function topicLabel(topic) {
  return TOPIC_LABELS[topic] || topic
}

function topicIcon(topic) {
  return TOPIC_ICONS[topic] || '📊'
}

function stanceLabel(stance) {
  if (stance > 0.3) return '正面'
  if (stance < -0.3) return '負面'
  return '中立'
}

function stanceClass(stance) {
  if (stance > 0.3) return 'stance-positive'
  if (stance < -0.3) return 'stance-negative'
  return 'stance-neutral'
}

function confidenceLevel(confidence) {
  if (confidence >= 0.7) return { label: '確信', cls: 'conf-high' }
  if (confidence >= 0.4) return { label: '一般', cls: 'conf-medium' }
  return { label: '不確定', cls: 'conf-low' }
}

function stanceBarStyle(stance) {
  // Map [-1, 1] to [0%, 100%] for left position
  const pct = ((stance + 1) / 2) * 100
  return { left: `${pct}%` }
}

onMounted(fetchBeliefs)

watch([() => props.sessionId, () => props.agentId], fetchBeliefs)
</script>

<template>
  <div class="belief-panel">
    <div class="panel-title">信念系統</div>

    <div v-if="loading" class="state-msg">
      <span class="spinner" /> 載入中...
    </div>
    <div v-else-if="error" class="state-msg state-error">{{ error }}</div>
    <div v-else-if="beliefs.length === 0" class="state-msg">
      尚無信念數據
    </div>

    <div v-else class="belief-list">
      <div
        v-for="belief in beliefs"
        :key="belief.topic"
        class="belief-card"
      >
        <div class="belief-header">
          <span class="belief-icon">{{ topicIcon(belief.topic) }}</span>
          <span class="belief-topic">{{ topicLabel(belief.topic) }}</span>
          <span class="belief-stance-label" :class="stanceClass(belief.stance || 0)">
            {{ stanceLabel(belief.stance || 0) }}
          </span>
        </div>

        <!-- Stance bar -->
        <div class="stance-track">
          <div class="stance-center" />
          <div class="stance-marker" :style="stanceBarStyle(belief.stance || 0)" />
          <div class="stance-labels">
            <span>-1</span>
            <span>0</span>
            <span>+1</span>
          </div>
        </div>

        <!-- Confidence + Evidence -->
        <div class="belief-footer">
          <div class="conf-info">
            <span class="conf-label">確信度</span>
            <span class="conf-bar-track">
              <span
                class="conf-bar-fill"
                :class="confidenceLevel(belief.confidence || 0).cls"
                :style="{ width: ((belief.confidence || 0) * 100) + '%' }"
              />
            </span>
            <span class="conf-value" :class="confidenceLevel(belief.confidence || 0).cls">
              {{ ((belief.confidence || 0) * 100).toFixed(0) }}%
            </span>
          </div>
          <div class="evidence-info">
            <span class="evidence-label">證據數量</span>
            <span class="evidence-count">{{ belief.evidence_count || 0 }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.belief-panel {
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  height: 100%;
  overflow-y: auto;
}

.panel-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.state-msg {
  text-align: center;
  padding: 24px;
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

.belief-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.belief-card {
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 12px;
  transition: border-color 0.15s;
}

.belief-card:hover { border-color: var(--accent-blue); }

.belief-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.belief-icon { font-size: 16px; }

.belief-topic {
  flex: 1;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.belief-stance-label {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
}

.stance-positive { background: #D1FAE5; color: #059669; }
.stance-negative { background: #FEE2E2; color: #DC2626; }
.stance-neutral { background: #F3F4F6; color: #6B7280; }

.stance-track {
  position: relative;
  height: 20px;
  background: var(--bg-secondary);
  border-radius: 4px;
  margin-bottom: 8px;
}

.stance-center {
  position: absolute;
  left: 50%;
  top: 2px;
  bottom: 2px;
  width: 1px;
  background: var(--border-color);
}

.stance-marker {
  position: absolute;
  top: 3px;
  width: 10px;
  height: 14px;
  background: var(--accent-blue);
  border-radius: 3px;
  transform: translateX(-50%);
  transition: left 0.3s;
}

.stance-labels {
  position: absolute;
  bottom: -14px;
  left: 0;
  right: 0;
  display: flex;
  justify-content: space-between;
  font-size: 9px;
  color: var(--text-muted);
}

.belief-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 14px;
  gap: 12px;
}

.conf-info {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
}

.conf-label {
  font-size: 10px;
  color: var(--text-muted);
  white-space: nowrap;
}

.conf-bar-track {
  flex: 1;
  height: 6px;
  background: var(--bg-secondary);
  border-radius: 3px;
  overflow: hidden;
}

.conf-bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s;
}

.conf-bar-fill.conf-high { background: #22c55e; }
.conf-bar-fill.conf-medium { background: #f59e0b; }
.conf-bar-fill.conf-low { background: #ef4444; }

.conf-value {
  font-size: 11px;
  font-weight: 600;
  min-width: 30px;
  text-align: right;
}

.conf-high { color: #059669; }
.conf-medium { color: #D97706; }
.conf-low { color: #DC2626; }

.evidence-info {
  display: flex;
  align-items: center;
  gap: 4px;
}

.evidence-label {
  font-size: 10px;
  color: var(--text-muted);
  white-space: nowrap;
}

.evidence-count {
  font-size: 13px;
  font-weight: 700;
  color: var(--accent-blue);
}
</style>
