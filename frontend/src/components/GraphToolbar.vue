<script setup>
import { ref } from 'vue'

const props = defineProps({
  entityTypes: { type: Array, default: () => [] },
  activeTypes: { type: Object, default: () => new Set() }, // Set
  showEchoChambers: { type: Boolean, default: false },
  layout: { type: String, default: 'force' },
})

const emit = defineEmits(['filter-change', 'search-query', 'echo-toggle', 'layout-change'])

const searchText = ref('')
let searchTimer = null

const typeColors = {
  person: '#2563EB',
  organization: '#7C3AED',
  policy: '#D97706',
  economic: '#059669',
  social: '#0891B2',
  event: '#DC2626',
  location: '#F59E0B',
}

const typeLabels = {
  person: '人物',
  organization: '機構',
  policy: '政策',
  economic: '經濟',
  social: '社會',
  event: '事件',
  location: '地點',
}

function toggleType(type) {
  const next = new Set(props.activeTypes)
  if (next.has(type)) {
    next.delete(type)
  } else {
    next.add(type)
  }
  emit('filter-change', next)
}

function onSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    emit('search-query', searchText.value.trim())
  }, 300)
}
</script>

<template>
  <div class="graph-toolbar">
    <div class="toolbar-filters">
      <button
        v-for="type in entityTypes"
        :key="type"
        class="filter-chip"
        :class="{ active: activeTypes.has(type) }"
        :style="{ '--chip-color': typeColors[type] || '#6B7280' }"
        @click="toggleType(type)"
      >
        <span class="chip-dot" :style="{ background: typeColors[type] || '#6B7280' }" />
        {{ typeLabels[type] || type }}
      </button>
    </div>
    <div class="toolbar-search">
      <input
        v-model="searchText"
        type="text"
        class="search-input"
        placeholder="搜尋節點..."
        @input="onSearch"
      />
    </div>
    <button
      class="echo-toggle"
      :class="{ active: showEchoChambers }"
      @click="emit('echo-toggle')"
    >
      <span class="echo-icon">&#x25CE;</span>
      {{ showEchoChambers ? '隱藏同溫層' : '顯示同溫層' }}
    </button>
    <select
      class="layout-select"
      :value="layout"
      @change="emit('layout-change', $event.target.value)"
    >
      <option value="force">力導向</option>
      <option value="clustered">社群聚類</option>
      <option value="radial">放射狀</option>
    </select>
  </div>
</template>

<style scoped>
.graph-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 16px;
  background: var(--bg-card, #fff);
  border-bottom: 1px solid var(--border-color);
}

.toolbar-filters {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.filter-chip {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-pill, 9999px);
  background: var(--bg-card, #fff);
  font-size: 12px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: var(--transition);
}

.filter-chip.active {
  border-color: var(--chip-color);
  background: color-mix(in srgb, var(--chip-color) 10%, white);
  color: var(--chip-color);
}

.chip-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.toolbar-search {
  flex: 1;
  max-width: 240px;
}

.search-input {
  width: 100%;
  padding: 6px 12px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md, 8px);
  font-size: 13px;
  background: var(--bg-input, #fff);
  color: var(--text-primary);
  outline: none;
  transition: border-color 0.2s;
}

.search-input:focus {
  border-color: var(--accent-blue);
}

.echo-toggle {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  background: var(--bg-card, #fff);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm, 6px);
  color: var(--text-muted);
  font-size: 12px;
  cursor: pointer;
  transition: background 0.2s, border-color 0.2s, color 0.2s;
  white-space: nowrap;
}

.echo-toggle:hover {
  background: var(--bg-secondary);
  border-color: var(--border-emphasis);
}

.echo-toggle.active {
  background: rgba(220, 38, 38, 0.08);
  border-color: rgba(220, 38, 38, 0.3);
  color: var(--accent-red);
}

.echo-icon {
  font-size: 14px;
}

.layout-select {
  padding: 5px 10px;
  background: var(--bg-card, #fff);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm, 6px);
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  outline: none;
  transition: border-color 0.2s;
}

.layout-select:focus {
  border-color: var(--accent-blue);
}
</style>
