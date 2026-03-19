<script setup>
import { ref, onMounted, computed } from 'vue'
import { marked } from 'marked'
import { getReport } from '../api/report.js'

const props = defineProps({
  reportId: { type: String, required: true },
})

const report = ref(null)
const loading = ref(true)
const error = ref(null)

const sanitize = (html) => {
  return html
    .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
    .replace(/\son\w+\s*=/gi, ' data-removed=')
    .replace(/<iframe[\s\S]*?<\/iframe>/gi, '')
    .replace(/<object[\s\S]*?<\/object>/gi, '')
    .replace(/<embed[^>]*>/gi, '')
    .replace(/javascript\s*:/gi, 'data-blocked:')
    .replace(/<base[^>]*>/gi, '')
}

const renderedMarkdown = computed(() => {
  if (!report.value?.content) return ''
  return sanitize(marked.parse(report.value.content))
})

onMounted(async () => {
  try {
    const res = await getReport(props.reportId)
    report.value = res.data?.data || res.data
  } catch (err) {
    error.value = '無法載入報告'
    console.error(err)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="report-page">
    <div v-if="loading" class="loading">
      <div class="spinner" />
      <p>載入報告中...</p>
    </div>

    <div v-else-if="error" class="error-msg">{{ error }}</div>

    <div v-else class="report-content">
      <div class="report-header">
        <h1>{{ report?.title || '模擬分析報告' }}</h1>
        <div class="report-meta">
          <span v-if="report?.created_at">
            生成時間：{{ new Date(report.created_at).toLocaleString('zh-HK') }}
          </span>
        </div>
      </div>
      <div class="markdown-body" v-html="renderedMarkdown" />
    </div>
  </div>
</template>

<style scoped>
.report-page {
  max-width: 900px;
  margin: 0 auto;
  padding: 32px 24px;
}

.loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 80px 0;
  gap: 16px;
  color: var(--text-secondary);
}

.spinner {
  width: 36px;
  height: 36px;
  border: 3px solid var(--border-color);
  border-top-color: var(--accent-blue);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.error-msg {
  text-align: center;
  padding: 60px 0;
  color: var(--accent-red);
}

.report-header {
  margin-bottom: 32px;
}

.report-header h1 {
  font-size: 28px;
  font-weight: 700;
  margin-bottom: 8px;
}

.report-meta {
  font-size: 13px;
  color: var(--text-muted);
}

.markdown-body {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 32px;
  line-height: 1.8;
  font-size: 15px;
}

.markdown-body :deep(h1) {
  font-size: 24px;
  margin: 24px 0 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border-color);
}

.markdown-body :deep(h2) {
  font-size: 20px;
  margin: 20px 0 10px;
}

.markdown-body :deep(h3) {
  font-size: 17px;
  margin: 16px 0 8px;
}

.markdown-body :deep(p) {
  margin-bottom: 12px;
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  padding-left: 24px;
  margin-bottom: 12px;
}

.markdown-body :deep(code) {
  background: var(--bg-input);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 13px;
}

.markdown-body :deep(pre) {
  background: var(--bg-primary);
  padding: 16px;
  border-radius: var(--radius-md);
  overflow-x: auto;
  margin-bottom: 16px;
}

.markdown-body :deep(blockquote) {
  border-left: 3px solid var(--accent-blue);
  padding-left: 16px;
  color: var(--text-secondary);
  margin-bottom: 12px;
}

.markdown-body :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin-bottom: 16px;
}

.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid var(--border-color);
  padding: 8px 12px;
  text-align: left;
}

.markdown-body :deep(th) {
  background: var(--bg-input);
  font-weight: 600;
}
</style>
