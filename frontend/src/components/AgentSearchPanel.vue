<script setup>
import { computed } from 'vue'
import AgentBadge from './AgentBadge.vue'

const props = defineProps({
  agentList: { type: Array, default: () => [] },
  agentSearch: { type: String, default: '' },
  filterDistrict: { type: String, default: '' },
  filterOccupation: { type: String, default: '' },
  loadingAgents: { type: Boolean, default: false },
  selectedAgentId: { type: Number, default: null },
})

const emit = defineEmits([
  'update:agentSearch',
  'update:filterDistrict',
  'update:filterOccupation',
  'select-agent',
  'clear-selection',
])

const districts = computed(() => {
  const set = new Set(props.agentList.map((a) => a.district).filter(Boolean))
  return [...set].sort()
})

const occupations = computed(() => {
  const set = new Set(props.agentList.map((a) => a.occupation).filter(Boolean))
  return [...set].sort()
})

// Stance badge — political_stance is REAL: 0.0=pro-establishment(建制), 0.5=centrist(中立), 1.0=pro-democracy(民主)
function stanceBadge(agent) {
  const stance = agent.political_stance
  if (stance == null) return null
  if (stance <= 0.33) return { label: '建制派', color: '#3b82f6' }
  if (stance >= 0.67) return { label: '民主派', color: '#ef4444' }
  return { label: '中立', color: '#64748b' }
}

// Tier badge
function tierBadge(agent) {
  const tier = agent.tier
  if (tier == null) return null
  return tier === 1
    ? { label: 'Tier 1', color: '#10b981' }
    : { label: 'Tier 2', color: '#94a3b8' }
}

function agentBadges(agent) {
  return [stanceBadge(agent), tierBadge(agent)].filter(Boolean)
}

const filteredAgents = computed(() => {
  return props.agentList.filter((a) => {
    const q = props.agentSearch.toLowerCase()
    const matchSearch = !q ||
      (a.oasis_username || a.username || '').toLowerCase().includes(q) ||
      (a.district || '').toLowerCase().includes(q) ||
      (a.occupation || '').toLowerCase().includes(q)
    const matchDistrict = !props.filterDistrict || a.district === props.filterDistrict
    const matchOcc = !props.filterOccupation || a.occupation === props.filterOccupation
    return matchSearch && matchDistrict && matchOcc
  })
})
</script>

<template>
  <div class="sidebar-section">
    <div class="sidebar-heading-row">
      <h3 class="sidebar-heading">代理人選擇</h3>
      <button
        v-if="selectedAgentId"
        class="clear-btn"
        @click="$emit('clear-selection')"
      >
        ✕ 取消
      </button>
    </div>

    <!-- Search -->
    <input
      :value="agentSearch"
      type="text"
      class="search-input"
      placeholder="搜尋姓名 / 地區 / 職業..."
      @input="$emit('update:agentSearch', $event.target.value)"
    />

    <!-- Filter dropdowns -->
    <div class="filter-row">
      <select
        :value="filterDistrict"
        class="filter-select"
        @change="$emit('update:filterDistrict', $event.target.value)"
      >
        <option value="">所有地區</option>
        <option v-for="d in districts" :key="d" :value="d">{{ d }}</option>
      </select>
      <select
        :value="filterOccupation"
        class="filter-select"
        @change="$emit('update:filterOccupation', $event.target.value)"
      >
        <option value="">所有職業</option>
        <option v-for="o in occupations" :key="o" :value="o">{{ o }}</option>
      </select>
    </div>

    <!-- Agent list -->
    <div class="agent-list">
      <div v-if="loadingAgents" class="agent-loading">載入中...</div>
      <div
        v-for="agent in filteredAgents.slice(0, 40)"
        :key="agent.id"
        class="agent-card"
        :class="{ selected: selectedAgentId === agent.id }"
        @click="$emit('select-agent', agent)"
      >
        <div class="agent-name">{{ agent.oasis_username || agent.username || `代理人 #${agent.id}` }}</div>
        <div class="agent-meta">
          <span>{{ agent.age ? agent.age + ' 歲' : '' }}</span>
          <span v-if="agent.district">{{ agent.district }}</span>
          <span v-if="agent.occupation">{{ agent.occupation }}</span>
        </div>
        <!-- Stance/Tier badges -->
        <div class="agent-badges" v-if="agentBadges(agent).length">
          <AgentBadge
            v-for="(badge, i) in agentBadges(agent)"
            :key="i"
            :label="badge.label"
            :color="badge.color"
          />
        </div>
      </div>
      <div v-if="!loadingAgents && filteredAgents.length === 0" class="agent-empty">
        無符合代理人
      </div>
    </div>
  </div>
</template>

<style scoped>
.sidebar-section {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.sidebar-heading-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.sidebar-heading {
  font-size: 14px;
  font-weight: 600;
  margin: 0;
}

.clear-btn {
  font-size: 11px;
  padding: 3px 8px;
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-muted);
  cursor: pointer;
  transition: var(--transition);
}

.clear-btn:hover {
  border-color: var(--accent-red);
  color: var(--accent-red);
}

.search-input {
  width: 100%;
  padding: 7px 10px;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-size: 13px;
  outline: none;
  box-sizing: border-box;
}

.search-input:focus {
  border-color: var(--accent-blue);
}

.filter-row {
  display: flex;
  gap: 6px;
}

.filter-select {
  flex: 1;
  padding: 6px 8px;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-size: 12px;
  outline: none;
}

.filter-select:focus {
  border-color: var(--accent-blue);
}

.agent-list {
  max-height: 260px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.agent-loading,
.agent-empty {
  font-size: 12px;
  color: var(--text-muted);
  text-align: center;
  padding: 12px;
}

.agent-card {
  padding: 8px 10px;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: var(--transition);
}

.agent-card:hover {
  border-color: var(--accent-blue);
}

.agent-card.selected {
  border-color: var(--accent-blue);
  background: var(--accent-blue-light);
}

.agent-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  margin-bottom: 3px;
}

.agent-meta {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 11px;
  color: var(--text-muted);
}

.agent-badges {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  margin-top: 4px;
}
</style>
