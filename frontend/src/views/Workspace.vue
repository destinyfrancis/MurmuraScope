<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { listSessions } from '../api/simulation.js'
import ScaleBenchmarkPanel from '../components/ScaleBenchmarkPanel.vue'

const router = useRouter()
const sessions = ref([])
const total = ref(0)
const loading = ref(true)
const error = ref(null)
const limit = 20
const offset = ref(0)
const showAdmin = ref(false)

const statusColors = {
  completed: 'var(--accent-green)',
  running: 'var(--accent-blue)',
  failed: 'var(--accent-red)',
  pending: 'var(--accent-orange)',
  created: 'var(--text-muted)',
}

const statusLabels = {
  completed: '已完成',
  running: '運行中',
  failed: '失敗',
  pending: '等待中',
  created: '已建立',
}

const scenarioIcons = {
  property: '🏠',
  emigration: '✈️',
  economic: '📊',
  political: '🏛️',
  social: '👥',
}

async function fetchSessions() {
  loading.value = true
  error.value = null
  try {
    const res = await listSessions(limit, offset.value)
    const data = res.data?.data || res.data
    sessions.value = data.sessions || []
    total.value = data.total || 0
  } catch (e) {
    error.value = e.message || '載入失敗'
  } finally {
    loading.value = false
  }
}

function loadMore() {
  offset.value += limit
  fetchMore()
}

async function fetchMore() {
  try {
    const res = await listSessions(limit, offset.value)
    const data = res.data?.data || res.data
    sessions.value = [...sessions.value, ...(data.sessions || [])]
  } catch (e) {
    error.value = e.message || '載入更多失敗'
  }
}

function goToSession(session) {
  router.push(`/app/graph/${session.id}`)
}

function goNew() {
  router.push('/')
}

function formatDate(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  return d.toLocaleDateString('zh-HK', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

onMounted(fetchSessions)
</script>

<template>
  <div class="workspace-page">
    <div class="workspace-header">
      <div>
        <h1 class="workspace-title">工作區</h1>
        <p class="workspace-subtitle">所有預測模擬 Session</p>
      </div>
      <div class="header-actions">
        <button
          class="btn-admin"
          :class="{ active: showAdmin }"
          @click="showAdmin = !showAdmin"
        >
          效能管理
        </button>
        <button class="btn-new" @click="goNew">+ 新預測</button>
      </div>
    </div>

    <!-- Admin panel -->
    <Transition name="panel-slide">
      <div v-if="showAdmin" class="admin-section">
        <ScaleBenchmarkPanel />
      </div>
    </Transition>

    <!-- Loading -->
    <div v-if="loading && sessions.length === 0" class="session-grid">
      <div v-for="i in 6" :key="i" class="skeleton skeleton-card" />
    </div>

    <!-- Error -->
    <div v-else-if="error" class="error-state">
      <p>{{ error }}</p>
      <button class="btn-retry" @click="fetchSessions">重試</button>
    </div>

    <!-- Empty -->
    <div v-else-if="sessions.length === 0" class="empty-state">
      <div class="empty-icon">⬡</div>
      <h2>尚未有預測</h2>
      <p>建立你嘅第一個社會模擬預測</p>
      <button class="btn-new" @click="goNew">+ 新預測</button>
    </div>

    <!-- Sessions grid -->
    <div v-else class="session-grid">
      <div
        v-for="session in sessions"
        :key="session.id"
        class="session-card glass-panel"
        @click="goToSession(session)"
      >
        <div class="card-header">
          <span class="scenario-icon">{{ scenarioIcons[session.scenario_type] || '📋' }}</span>
          <span
            class="status-badge"
            :style="{ color: statusColors[session.status] || 'var(--text-muted)', borderColor: statusColors[session.status] || 'var(--border-color)' }"
          >
            {{ statusLabels[session.status] || session.status }}
          </span>
        </div>
        <h3 class="card-title">{{ session.name || session.scenario_type || 'Untitled' }}</h3>
        <div class="card-meta">
          <span>{{ session.agent_count || 0 }} agents</span>
          <span>{{ session.current_round || 0 }}/{{ session.round_count || 0 }} rounds</span>
        </div>
        <div class="card-date">{{ formatDate(session.created_at) }}</div>
        <div class="card-actions" @click.stop>
          <router-link
            :to="`/app/evidence/${session.id}`"
            class="evidence-link"
          >証據搜尋</router-link>
        </div>
      </div>
    </div>

    <!-- Load more -->
    <div v-if="sessions.length < total" class="load-more">
      <button class="btn-load-more" @click="loadMore">載入更多</button>
    </div>
  </div>
</template>

<style scoped>
.workspace-page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 32px 24px;
}

.workspace-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 28px;
}

.workspace-title {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
}

.workspace-subtitle {
  font-size: 14px;
  color: var(--text-muted);
  margin-top: 4px;
}

.header-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.btn-admin {
  padding: 10px 16px;
  background: var(--bg-card);
  color: var(--text-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: var(--transition);
}

.btn-admin:hover {
  border-color: var(--accent-blue);
  color: var(--accent-blue);
}

.btn-admin.active {
  background: rgba(37, 99, 235, 0.08);
  border-color: var(--accent-blue);
  color: var(--accent-blue);
}

.btn-new {
  padding: 10px 20px;
  background: var(--accent-blue);
  color: #fff;
  border: none;
  border-radius: var(--radius-md);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: var(--transition);
}

.btn-new:hover {
  background: #1d4ed8;
}

.admin-section {
  margin-bottom: 24px;
  padding: 20px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
}

.panel-slide-enter-active,
.panel-slide-leave-active {
  transition: all 0.25s ease;
  overflow: hidden;
}

.panel-slide-enter-from,
.panel-slide-leave-to {
  opacity: 0;
  max-height: 0;
  margin-bottom: 0;
  padding: 0 20px;
}

.session-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}

.session-card {
  padding: 20px;
  cursor: pointer;
  transition: var(--transition);
}

.session-card:hover {
  box-shadow: var(--shadow-md);
  border-color: var(--accent-blue);
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.scenario-icon {
  font-size: 24px;
}

.status-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border: 1px solid;
  border-radius: var(--radius-pill);
}

.card-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
  text-transform: capitalize;
}

.card-meta {
  display: flex;
  gap: 12px;
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 6px;
}

.card-date {
  font-size: 11px;
  color: var(--text-muted);
}

.card-actions {
  margin-top: 10px;
  display: flex;
  gap: 8px;
}

.evidence-link {
  font-size: 12px;
  color: var(--accent-blue);
  text-decoration: none;
  padding: 3px 8px;
  border: 1px solid var(--accent-blue);
  border-radius: var(--radius-sm);
  transition: var(--transition);
}

.evidence-link:hover {
  background: var(--accent-blue);
  color: #fff;
}

.empty-state {
  text-align: center;
  padding: 80px 24px;
}

.empty-icon {
  font-size: 48px;
  color: var(--accent-blue);
  margin-bottom: 16px;
}

.empty-state h2 {
  font-size: 20px;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.empty-state p {
  color: var(--text-muted);
  margin-bottom: 20px;
}

.error-state {
  text-align: center;
  padding: 60px 24px;
  color: var(--accent-red);
}

.btn-retry {
  margin-top: 12px;
  padding: 8px 16px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  cursor: pointer;
  color: var(--text-primary);
}

.load-more {
  text-align: center;
  margin-top: 24px;
}

.btn-load-more {
  padding: 10px 24px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  font-size: 14px;
  cursor: pointer;
  transition: var(--transition);
}

.btn-load-more:hover {
  border-color: var(--accent-blue);
  color: var(--accent-blue);
}
</style>
