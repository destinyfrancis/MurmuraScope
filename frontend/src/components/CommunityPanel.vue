<script setup>
import { computed } from 'vue'

const props = defineProps({
  sessionId: { type: String, default: '' },
  clusterId: { type: Number, default: 0 },
  summary: { type: Object, default: () => ({}) },
  clusterAgents: { type: Array, default: () => [] },
  conflicts: { type: Array, default: () => [] },
})

const emit = defineEmits(['close'])

// Political stance distribution buckets
const stanceDistribution = computed(() => {
  const agents = props.clusterAgents
  if (!agents.length) return { pro: 0, mid: 0, dem: 0 }
  let pro = 0, mid = 0, dem = 0
  for (const a of agents) {
    const s = a.political_stance ?? 0.5
    if (s < 0.35) pro++
    else if (s > 0.65) dem++
    else mid++
  }
  const total = agents.length || 1
  return {
    pro: Math.round((pro / total) * 100),
    mid: Math.round((mid / total) * 100),
    dem: Math.round((dem / total) * 100),
  }
})

const sortedAgents = computed(() => {
  return [...props.clusterAgents]
    .sort((a, b) => (b.trust_score ?? 0) - (a.trust_score ?? 0))
    .slice(0, 10)
})

function stanceBadgeClass(stance) {
  if (stance < 0.35) return 'stance-pro'
  if (stance > 0.65) return 'stance-dem'
  return 'stance-mid'
}

function stanceLabel(stance) {
  if (stance < 0.35) return '建制'
  if (stance > 0.65) return '民主'
  return '中間'
}
</script>

<template>
  <div class="community-panel">
    <div class="cp-header">
      <div class="cp-title-row">
        <span class="cp-title">社群 #{{ clusterId }}</span>
        <span class="cp-count">{{ summary.member_count || clusterAgents.length }} 人</span>
      </div>
      <button class="cp-close" @click="emit('close')">✕</button>
    </div>

    <div class="cp-body">
      <!-- Core narrative -->
      <div class="cp-section">
        <div class="cp-section-label">核心敘事</div>
        <p class="cp-narrative">{{ summary.core_narrative || '暫無摘要' }}</p>
      </div>

      <!-- Shared anxieties -->
      <div v-if="summary.shared_anxieties" class="cp-section">
        <div class="cp-section-label">共同焦慮</div>
        <p class="cp-anxieties">{{ summary.shared_anxieties }}</p>
      </div>

      <!-- Main opposition -->
      <div v-if="summary.main_opposition" class="cp-section">
        <div class="cp-section-label">主要對立面</div>
        <p class="cp-opposition">{{ summary.main_opposition }}</p>
      </div>

      <!-- Political stance distribution -->
      <div class="cp-section">
        <div class="cp-section-label">政治傾向分佈</div>
        <div class="stance-bar-container">
          <div class="stance-bar">
            <div class="stance-segment pro" :style="{ width: stanceDistribution.pro + '%' }" />
            <div class="stance-segment mid" :style="{ width: stanceDistribution.mid + '%' }" />
            <div class="stance-segment dem" :style="{ width: stanceDistribution.dem + '%' }" />
          </div>
          <div class="stance-labels">
            <span class="stance-label-item pro">建制 {{ stanceDistribution.pro }}%</span>
            <span class="stance-label-item mid">中間 {{ stanceDistribution.mid }}%</span>
            <span class="stance-label-item dem">民主 {{ stanceDistribution.dem }}%</span>
          </div>
        </div>
      </div>

      <!-- Member list -->
      <div class="cp-section">
        <div class="cp-section-label">成員（按信任度排序）</div>
        <div v-if="sortedAgents.length === 0" class="cp-empty">暫無成員數據</div>
        <div v-for="agent in sortedAgents" :key="agent.id" class="cp-agent-row">
          <div class="cp-agent-name">{{ agent.oasis_username || agent.username || `#${agent.id}` }}</div>
          <div class="cp-agent-meta">
            <span v-if="agent.district" class="cp-district">{{ agent.district }}</span>
            <span class="cp-stance-badge" :class="stanceBadgeClass(agent.political_stance ?? 0.5)">
              {{ stanceLabel(agent.political_stance ?? 0.5) }}
            </span>
          </div>
        </div>
      </div>

      <!-- Related conflicts -->
      <div v-if="conflicts.length" class="cp-section">
        <div class="cp-section-label">相關認知衝突</div>
        <div v-for="(c, idx) in conflicts" :key="idx" class="cp-conflict-row">
          <div class="cp-conflict-entity">{{ c.entity }}</div>
          <div class="cp-conflict-sides">
            <span class="cp-conflict-a">{{ c.predicate_a }} {{ c.object_a }}</span>
            <span class="cp-conflict-vs">vs</span>
            <span class="cp-conflict-b">{{ c.predicate_b }} {{ c.object_b }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.community-panel {
  position: absolute;
  right: 0;
  top: 0;
  bottom: 0;
  width: 320px;
  background: var(--bg-card);
  border-left: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  z-index: 25;
  overflow: hidden;
  box-shadow: var(--shadow-md);
}

.cp-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.cp-title-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.cp-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
}

.cp-count {
  font-size: 12px;
  color: var(--text-muted);
  background: var(--bg-secondary);
  padding: 2px 8px;
  border-radius: 10px;
}

.cp-close {
  background: transparent;
  border: none;
  color: var(--text-muted);
  font-size: 14px;
  cursor: pointer;
  padding: 4px 6px;
  border-radius: 4px;
  transition: color 0.2s, background 0.2s;
}

.cp-close:hover {
  color: var(--text-primary);
  background: var(--bg-secondary);
}

.cp-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.cp-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.cp-section-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.cp-narrative {
  margin: 0;
  font-size: 13px;
  color: var(--text-primary);
  line-height: 1.6;
}

.cp-anxieties {
  margin: 0;
  font-size: 12px;
  color: #f87171;
  line-height: 1.5;
}

.cp-opposition {
  margin: 0;
  font-size: 12px;
  color: #fb923c;
  line-height: 1.5;
}

.cp-empty {
  font-size: 12px;
  color: var(--text-muted);
  padding: 8px 0;
}

/* Stance bar */
.stance-bar-container {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stance-bar {
  display: flex;
  height: 8px;
  border-radius: 4px;
  overflow: hidden;
  background: var(--bg-secondary);
}

.stance-segment {
  transition: width 0.3s ease;
}

.stance-segment.pro {
  background: var(--accent-blue);
}

.stance-segment.mid {
  background: var(--text-muted);
}

.stance-segment.dem {
  background: #34d399;
}

.stance-labels {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
}

.stance-label-item.pro { color: var(--accent-blue); }
.stance-label-item.mid { color: var(--text-muted); }
.stance-label-item.dem { color: #34d399; }

/* Agent rows */
.cp-agent-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 0;
  border-bottom: 1px solid var(--border-color);
}

.cp-agent-name {
  font-size: 12px;
  color: var(--text-primary);
  font-weight: 500;
}

.cp-agent-meta {
  display: flex;
  align-items: center;
  gap: 6px;
}

.cp-district {
  font-size: 10px;
  color: var(--text-muted);
}

.cp-stance-badge {
  font-size: 10px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 8px;
}

.cp-stance-badge.stance-pro {
  background: rgba(74, 158, 255, 0.15);
  color: var(--accent-blue);
}

.cp-stance-badge.stance-mid {
  background: rgba(156, 163, 184, 0.15);
  color: var(--text-muted);
}

.cp-stance-badge.stance-dem {
  background: rgba(52, 211, 153, 0.15);
  color: #34d399;
}

/* Conflict rows */
.cp-conflict-row {
  padding: 8px 10px;
  background: rgba(239, 68, 68, 0.06);
  border: 1px solid rgba(239, 68, 68, 0.15);
  border-radius: 6px;
}

.cp-conflict-entity {
  font-size: 12px;
  font-weight: 600;
  color: #f87171;
  margin-bottom: 4px;
}

.cp-conflict-sides {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-muted);
}

.cp-conflict-vs {
  color: #ef4444;
  font-weight: 700;
  font-size: 10px;
}

.cp-conflict-a,
.cp-conflict-b {
  flex: 1;
}
</style>
