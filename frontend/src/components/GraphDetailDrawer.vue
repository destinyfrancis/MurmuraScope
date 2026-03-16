<script setup>
import { ref, watch } from 'vue'
import { getNodeEvidence, getNodeNeighborhood } from '../api/graph.js'

const props = defineProps({
  selectedNode: { type: Object, default: null },
  selectedEdge: { type: Object, default: null },
  sessionId: { type: String, default: '' },
  graphId: { type: String, default: '' },
  visible: { type: Boolean, default: false },
})

const emit = defineEmits(['close'])

const activeTab = ref('overview')
const evidence = ref(null)
const neighbors = ref(null)
const loadingEvidence = ref(false)
const loadingNeighbors = ref(false)

const tabs = [
  { id: 'overview', label: '概覽' },
  { id: 'evidence', label: '證據' },
  { id: 'relations', label: '關係' },
  { id: 'timeline', label: '時間線' },
  { id: 'impact', label: '預測影響' },
]

watch(() => props.selectedNode, (node) => {
  if (node) {
    activeTab.value = 'overview'
    evidence.value = null
    neighbors.value = null
  }
})

async function loadEvidence() {
  if (!props.graphId || !props.selectedNode?.id) return
  loadingEvidence.value = true
  try {
    const res = await getNodeEvidence(props.graphId, props.selectedNode.id)
    evidence.value = res.data?.data || res.data
  } catch (e) {
    evidence.value = { memories: [], provenance: [], error: e.message }
  } finally {
    loadingEvidence.value = false
  }
}

async function loadNeighbors() {
  if (!props.graphId || !props.selectedNode?.id) return
  loadingNeighbors.value = true
  try {
    const res = await getNodeNeighborhood(props.graphId, props.selectedNode.id, 2)
    neighbors.value = res.data?.data || res.data
  } catch (e) {
    neighbors.value = { nodes: [], edges: [], error: e.message }
  } finally {
    loadingNeighbors.value = false
  }
}

watch(activeTab, (tab) => {
  if (tab === 'evidence' && !evidence.value) loadEvidence()
  if (tab === 'relations' && !neighbors.value) loadNeighbors()
})

const typeColors = {
  person: '#2563EB',
  organization: '#7C3AED',
  policy: '#D97706',
  economic: '#059669',
  social: '#0891B2',
  event: '#DC2626',
  location: '#F59E0B',
}
</script>

<template>
  <transition name="slide">
    <div v-if="visible && selectedNode" class="drawer-overlay" @click.self="emit('close')">
      <div class="drawer">
        <div class="drawer-header">
          <div class="drawer-title-row">
            <span
              class="type-badge"
              :style="{ background: typeColors[selectedNode.type] || '#6B7280' }"
            >
              {{ selectedNode.type }}
            </span>
            <h3 class="drawer-title">{{ selectedNode.label || selectedNode.id }}</h3>
          </div>
          <button class="btn-close" @click="emit('close')">✕</button>
        </div>

        <!-- Tabs -->
        <div class="drawer-tabs">
          <button
            v-for="tab in tabs"
            :key="tab.id"
            class="tab-btn"
            :class="{ active: activeTab === tab.id }"
            @click="activeTab = tab.id"
          >
            {{ tab.label }}
          </button>
        </div>

        <!-- Tab Content -->
        <div class="drawer-body">
          <!-- Overview -->
          <div v-if="activeTab === 'overview'" class="tab-content">
            <div class="info-row">
              <span class="info-label">名稱</span>
              <span class="info-value">{{ selectedNode.label }}</span>
            </div>
            <div class="info-row">
              <span class="info-label">類型</span>
              <span class="info-value">{{ selectedNode.type }}</span>
            </div>
            <div v-if="selectedNode.description" class="info-row">
              <span class="info-label">描述</span>
              <span class="info-value">{{ selectedNode.description }}</span>
            </div>
            <div v-if="selectedNode.size" class="info-row">
              <span class="info-label">權重</span>
              <span class="info-value">{{ selectedNode.size }}</span>
            </div>
          </div>

          <!-- Evidence -->
          <div v-if="activeTab === 'evidence'" class="tab-content">
            <div v-if="loadingEvidence" class="tab-loading">
              <div class="skeleton skeleton-text" v-for="i in 4" :key="i" />
            </div>
            <div v-else-if="evidence">
              <h4 class="section-title">Agent 記憶 ({{ evidence.memories?.length || 0 }})</h4>
              <div v-if="evidence.memories?.length" class="evidence-list">
                <div v-for="(mem, i) in evidence.memories" :key="i" class="evidence-card">
                  <div class="evidence-meta">
                    <span>Agent #{{ mem.agent_id }}</span>
                    <span class="salience">{{ (mem.salience_score * 100).toFixed(0) }}%</span>
                  </div>
                  <p class="evidence-text">{{ mem.memory_text }}</p>
                </div>
              </div>
              <p v-else class="empty-tab">暫無相關記憶</p>

              <h4 class="section-title" style="margin-top: 16px">數據來源 ({{ evidence.provenance?.length || 0 }})</h4>
              <div v-if="evidence.provenance?.length" class="evidence-list">
                <div v-for="(prov, i) in evidence.provenance" :key="i" class="evidence-card">
                  <div class="evidence-meta">
                    <span>{{ prov.category }}/{{ prov.metric }}</span>
                    <span class="source-type">{{ prov.source_type }}</span>
                  </div>
                </div>
              </div>
              <p v-else class="empty-tab">暫無數據來源</p>
            </div>
          </div>

          <!-- Relations -->
          <div v-if="activeTab === 'relations'" class="tab-content">
            <div v-if="loadingNeighbors" class="tab-loading">
              <div class="skeleton skeleton-text" v-for="i in 4" :key="i" />
            </div>
            <div v-else-if="neighbors">
              <p class="neighbor-count">{{ neighbors.nodes?.length || 0 }} 個相關節點</p>
              <div v-for="node in (neighbors.nodes || [])" :key="node.id" class="neighbor-item">
                <span
                  class="neighbor-dot"
                  :style="{ background: typeColors[node.type] || '#6B7280' }"
                />
                <span class="neighbor-label">{{ node.label }}</span>
                <span class="neighbor-type">{{ node.type }}</span>
              </div>
            </div>
          </div>

          <!-- Timeline -->
          <div v-if="activeTab === 'timeline'" class="tab-content">
            <p class="empty-tab">節點權重變化時間線（需要 snapshot 數據）</p>
          </div>

          <!-- Impact -->
          <div v-if="activeTab === 'impact'" class="tab-content">
            <p class="empty-tab">預測影響分析（即將推出）</p>
          </div>
        </div>
      </div>
    </div>
  </transition>
</template>

<style scoped>
.drawer-overlay {
  position: fixed;
  inset: 0;
  z-index: 200;
  display: flex;
  justify-content: flex-end;
}

.drawer {
  width: 400px;
  max-width: 90vw;
  height: 100vh;
  background: var(--bg-card, #fff);
  border-left: 1px solid var(--border-color);
  box-shadow: var(--shadow-lg);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.drawer-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
}

.drawer-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
}

.type-badge {
  padding: 2px 8px;
  border-radius: var(--radius-pill);
  font-size: 11px;
  font-weight: 600;
  color: #0d1117;
  flex-shrink: 0;
}

.drawer-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.btn-close {
  background: none;
  border: none;
  font-size: 18px;
  color: var(--text-muted);
  cursor: pointer;
  padding: 4px;
  flex-shrink: 0;
}

.btn-close:hover {
  color: var(--text-primary);
}

.drawer-tabs {
  display: flex;
  border-bottom: 1px solid var(--border-color);
  padding: 0 20px;
  overflow-x: auto;
}

.tab-btn {
  padding: 10px 14px;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  font-size: 13px;
  color: var(--text-muted);
  cursor: pointer;
  white-space: nowrap;
  transition: var(--transition);
}

.tab-btn.active {
  color: var(--accent-blue);
  border-bottom-color: var(--accent-blue);
}

.tab-btn:hover {
  color: var(--text-primary);
}

.drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}

.tab-content {
  animation: fadeIn 0.15s ease;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.info-row {
  display: flex;
  padding: 8px 0;
  border-bottom: 1px solid var(--border-color);
}

.info-label {
  width: 60px;
  flex-shrink: 0;
  font-size: 12px;
  color: var(--text-muted);
  font-weight: 500;
}

.info-value {
  font-size: 13px;
  color: var(--text-primary);
  line-height: 1.5;
}

.section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.evidence-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.evidence-card {
  padding: 10px 12px;
  background: var(--bg-surface, #F9FAFB);
  border-radius: var(--radius-md);
  border: 1px solid var(--border-color);
}

.evidence-meta {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 4px;
}

.salience {
  color: var(--accent-green);
  font-weight: 600;
}

.source-type {
  padding: 1px 6px;
  background: var(--accent-blue-light);
  color: var(--accent-blue);
  border-radius: var(--radius-sm);
  font-size: 10px;
}

.evidence-text {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
}

.neighbor-count {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 10px;
}

.neighbor-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  border-bottom: 1px solid var(--border-color);
}

.neighbor-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.neighbor-label {
  flex: 1;
  font-size: 13px;
  color: var(--text-primary);
}

.neighbor-type {
  font-size: 11px;
  color: var(--text-muted);
}

.empty-tab {
  text-align: center;
  padding: 20px;
  color: var(--text-muted);
  font-size: 13px;
}

.tab-loading {
  padding: 12px 0;
}

/* Slide transition */
.slide-enter-active,
.slide-leave-active {
  transition: all 0.25s ease;
}

.slide-enter-from .drawer,
.slide-leave-to .drawer {
  transform: translateX(100%);
}

.slide-enter-from,
.slide-leave-to {
  opacity: 0;
}
</style>
