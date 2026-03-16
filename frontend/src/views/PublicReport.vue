<script setup>
import { ref, onMounted } from 'vue'
import { getPublicReport } from '../api/report.js'

const props = defineProps({
  token: { type: String, required: true },
})

const report = ref(null)
const loading = ref(true)
const error = ref(null)

async function fetchReport() {
  loading.value = true
  error.value = null
  try {
    const res = await getPublicReport(props.token)
    report.value = res.data?.data || res.data
  } catch (e) {
    if (e.response?.status === 404) {
      error.value = '報告未找到或連結已失效'
    } else {
      error.value = e.message || '載入失敗'
    }
  } finally {
    loading.value = false
  }
}

function copyUrl() {
  navigator.clipboard.writeText(window.location.href)
  copied.value = true
  setTimeout(() => { copied.value = false }, 2000)
}

const copied = ref(false)

onMounted(fetchReport)
</script>

<template>
  <div class="public-report">
    <!-- Loading -->
    <div v-if="loading" class="loading-state">
      <div class="skeleton skeleton-title" />
      <div class="skeleton skeleton-text" style="width: 80%" />
      <div class="skeleton skeleton-text" style="width: 60%" />
      <div class="skeleton skeleton-text" style="width: 90%" />
      <div class="skeleton skeleton-text" style="width: 70%" />
    </div>

    <!-- Error -->
    <div v-else-if="error" class="error-state">
      <div class="error-icon">🔒</div>
      <h2>無法存取報告</h2>
      <p>{{ error }}</p>
    </div>

    <!-- Report -->
    <div v-else-if="report" class="report-content">
      <div class="report-header">
        <div class="report-meta">
          <span class="report-badge">{{ report.report_type || '分析報告' }}</span>
          <span class="report-date">{{ report.created_at }}</span>
        </div>
        <h1 class="report-title">{{ report.title }}</h1>
        <button class="btn-copy" @click="copyUrl">
          {{ copied ? '已複製!' : '複製連結' }}
        </button>
      </div>

      <!-- Summary -->
      <div v-if="report.summary" class="report-summary glass-panel">
        <h3>摘要</h3>
        <p>{{ report.summary }}</p>
      </div>

      <!-- Key Findings -->
      <div v-if="report.key_findings?.length" class="key-findings glass-panel">
        <h3>主要發現</h3>
        <ul>
          <li v-for="(finding, i) in report.key_findings" :key="i">{{ finding }}</li>
        </ul>
      </div>

      <!-- Main Content -->
      <div class="report-body glass-panel" v-html="renderMarkdown(report.content_markdown)" />

      <!-- Footer -->
      <div class="report-footer">
        <span>HKSimEngine</span>
        <span>Session: {{ report.session_id }}</span>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  methods: {
    renderMarkdown(md) {
      if (!md) return ''
      // Basic markdown to HTML (headings, bold, lists, paragraphs)
      return md
        .replace(/^### (.*$)/gm, '<h3>$1</h3>')
        .replace(/^## (.*$)/gm, '<h2>$1</h2>')
        .replace(/^# (.*$)/gm, '<h1>$1</h1>')
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/^\- (.*$)/gm, '<li>$1</li>')
        .replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>')
        .replace(/\n\n/g, '</p><p>')
        .replace(/^(?!<[hul])/gm, '<p>')
    },
  },
}
</script>

<style scoped>
.public-report {
  max-width: 900px;
  margin: 0 auto;
  padding: 32px 24px;
}

.loading-state {
  padding: 40px 0;
}

.error-state {
  text-align: center;
  padding: 80px 24px;
}

.error-icon {
  font-size: 48px;
  margin-bottom: 16px;
}

.error-state h2 {
  font-size: 20px;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.error-state p {
  color: var(--text-muted);
}

.report-header {
  margin-bottom: 24px;
}

.report-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}

.report-badge {
  padding: 2px 10px;
  background: var(--accent-blue-light);
  color: var(--accent-blue);
  border-radius: var(--radius-pill);
  font-size: 12px;
  font-weight: 600;
}

.report-date {
  font-size: 12px;
  color: var(--text-muted);
}

.report-title {
  font-size: 28px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 12px;
}

.btn-copy {
  padding: 6px 14px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  font-size: 13px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: var(--transition);
}

.btn-copy:hover {
  border-color: var(--accent-blue);
  color: var(--accent-blue);
}

.report-summary,
.key-findings {
  padding: 20px;
  margin-bottom: 16px;
}

.report-summary h3,
.key-findings h3 {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 8px;
  color: var(--text-primary);
}

.report-summary p {
  color: var(--text-secondary);
  line-height: 1.7;
}

.key-findings ul {
  list-style: none;
  padding: 0;
}

.key-findings li {
  padding: 6px 0;
  color: var(--text-secondary);
  line-height: 1.6;
}

.key-findings li::before {
  content: '▸ ';
  color: var(--accent-blue);
}

.report-body {
  padding: 24px;
  margin-bottom: 24px;
  line-height: 1.8;
  color: var(--text-secondary);
}

.report-body :deep(h1),
.report-body :deep(h2),
.report-body :deep(h3) {
  color: var(--text-primary);
  margin-top: 20px;
  margin-bottom: 8px;
}

.report-footer {
  display: flex;
  justify-content: space-between;
  padding: 16px 0;
  border-top: 1px solid var(--border-color);
  font-size: 12px;
  color: var(--text-muted);
}
</style>
