<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { marked } from 'marked'
import { generateReport, getReportStatus } from '../api/report.js'

const exporting = ref(false)
async function exportPDF() {
  exporting.value = true
  const reportId = props.session.reportId
  try {
    const res = await fetch(`/api/report/${reportId}/pdf`)
    if (!res.ok) throw new Error('PDF generation failed')
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `hksimengine-report-${reportId}.pdf`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    console.error('PDF export error:', e)
    alert('PDF 匯出失敗，請稍後再試')
  } finally {
    exporting.value = false
  }
}

const props = defineProps({
  session: { type: Object, required: true },
})

const emit = defineEmits(['report-generated'])

const generating = ref(false)
const completed = ref(false)
const error = ref(null)
const reportContent = ref('')
const reactSteps = ref([])

// Collapsible "AI 推理過程" section
const reasoningOpen = ref(true)
const collapsedSteps = ref(new Set())

// Typewriter effect state
const displayedReport = ref('')
const isTyping = ref(false)
let typewriterTimer = null

const renderedReport = computed(() => {
  if (!reportContent.value) return ''
  return marked.parse(reportContent.value)
})

const renderedDisplayReport = computed(() => {
  if (!displayedReport.value) return ''
  return marked.parse(displayedReport.value)
})

watch(reportContent, (newContent) => {
  if (!newContent) return
  // Clear any existing typewriter
  if (typewriterTimer) {
    clearInterval(typewriterTimer)
    typewriterTimer = null
  }
  displayedReport.value = ''
  isTyping.value = true
  let idx = 0
  typewriterTimer = setInterval(() => {
    const chunkSize = Math.floor(Math.random() * 6) + 3   // 3-8 chars
    idx = Math.min(idx + chunkSize, newContent.length)
    displayedReport.value = newContent.slice(0, idx)
    if (idx >= newContent.length) {
      clearInterval(typewriterTimer)
      typewriterTimer = null
      isTyping.value = false
    }
  }, 30)
})

const stepIcon = (stepType) => {
  if (stepType === 'Thought') return '🧠'
  if (stepType === 'Action') return '⚡'
  if (stepType === 'Observation') return '👁'
  return '•'
}

const stepClass = (stepType) => {
  if (stepType === 'Thought') return 'step-thought'
  if (stepType === 'Action') return 'step-action'
  if (stepType === 'Observation') return 'step-observe'
  return ''
}

function toggleStep(idx) {
  const next = new Set(collapsedSteps.value)
  if (next.has(idx)) {
    next.delete(idx)
  } else {
    next.add(idx)
  }
  collapsedSteps.value = next
}

function formatTimestamp(ts) {
  if (!ts) return ''
  try {
    return new Date(ts).toLocaleTimeString('zh-HK')
  } catch {
    return ts
  }
}

let pollTimer = null

function mergeReactSteps(incoming) {
  // Merge structured steps from backend (step_type/content/timestamp)
  // or legacy log format (step/action/detail) without duplicates
  incoming.forEach((entry) => {
    if (entry.step_type) {
      // Structured format from 3A backend
      const exists = reactSteps.value.some(
        (s) => s.step_type === entry.step_type &&
               s.content === entry.content &&
               s.timestamp === entry.timestamp
      )
      if (!exists) {
        reactSteps.value = [...reactSteps.value, {
          step_type: entry.step_type,
          content: entry.content,
          timestamp: entry.timestamp,
        }]
      }
    } else {
      // Legacy format
      const exists = reactSteps.value.some(
        (s) => s._legacy && s.step === entry.step && s.action === entry.action
      )
      if (!exists) {
        reactSteps.value = [...reactSteps.value, {
          step_type: entry.action === 'tool' ? 'Action'
                   : entry.action === 'observe' ? 'Observation'
                   : 'Thought',
          content: entry.detail || entry.observation || entry.tool || '',
          timestamp: entry.timestamp || new Date().toISOString(),
          _legacy: true,
          step: entry.step,
          action: entry.action,
        }]
      }
    }
  })
}

async function pollReportStatus(reportId) {
  try {
    const res = await getReportStatus(reportId)
    const data = res.data

    if (data.react_logs) {
      mergeReactSteps(data.react_logs)
    }
    if (data.agent_log) {
      mergeReactSteps(data.agent_log)
    }

    if (data.status === 'completed') {
      reportContent.value = data.content || data.content_markdown || ''
      completed.value = true
      generating.value = false
      clearInterval(pollTimer)
      pollTimer = null
      emit('report-generated', { reportId })
      return
    }

    if (data.status === 'failed') {
      error.value = data.error || '報告生成失敗'
      generating.value = false
      clearInterval(pollTimer)
      pollTimer = null
    }
  } catch (err) {
    console.error('Poll error:', err)
  }
}

async function startGeneration() {
  generating.value = true
  error.value = null
  reactSteps.value = []
  reportContent.value = ''
  collapsedSteps.value = new Set()

  reactSteps.value = [{
    step_type: 'Thought',
    content: '初始化報告生成流程...',
    timestamp: new Date().toISOString(),
  }]

  try {
    const res = await generateReport({
      session_id: props.session.sessionId,
      scenario_type: props.session.scenarioType,
    })

    const resData = res.data?.data || res.data
    const reportId = resData.report_id
    props.session.reportId = reportId

    // If agent_log is already in the response (synchronous generation), use it directly
    if (resData.agent_log?.length) {
      mergeReactSteps(resData.agent_log)
    }
    if (resData.content_markdown) {
      reportContent.value = resData.content_markdown
      completed.value = true
      generating.value = false
      emit('report-generated', { reportId })
      return
    }

    reactSteps.value = [...reactSteps.value, {
      step_type: 'Action',
      content: '報告生成請求已提交，開始 ReACT 分析循環...',
      timestamp: new Date().toISOString(),
    }]

    pollTimer = setInterval(() => pollReportStatus(reportId), 3000)
  } catch (err) {
    error.value = err.response?.data?.detail || err.message || '生成失敗'
    generating.value = false
  }
}

onMounted(() => {
  startGeneration()
})

onUnmounted(() => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
  if (typewriterTimer) {
    clearInterval(typewriterTimer)
    typewriterTimer = null
  }
})
</script>

<template>
  <div class="step4">
    <div class="step4-left">
      <!-- AI 推理過程 collapsible panel -->
      <div class="react-panel">
        <div class="react-panel-header" @click="reasoningOpen = !reasoningOpen">
          <h3 class="panel-heading">AI 推理過程</h3>
          <div class="header-right">
            <span v-if="generating" class="generating-badge">
              <span class="dot-pulse" />
              推理中...
            </span>
            <span class="step-count">{{ reactSteps.length }} 步驟</span>
            <span class="collapse-icon">{{ reasoningOpen ? '▲' : '▼' }}</span>
          </div>
        </div>

        <!-- Progress bar while generating -->
        <div v-if="generating" class="gen-progress">
          <div class="gen-progress-fill" />
        </div>

        <div v-if="reasoningOpen" class="react-steps">
          <div
            v-for="(step, idx) in reactSteps"
            :key="idx"
            class="react-step"
            :class="stepClass(step.step_type)"
          >
            <div class="react-step-header" @click="toggleStep(idx)">
              <span class="step-icon">{{ stepIcon(step.step_type) }}</span>
              <span class="step-type-badge" :class="stepClass(step.step_type)">
                {{ step.step_type }}
              </span>
              <span class="step-preview">
                {{ collapsedSteps.has(idx) ? (step.content || '').slice(0, 60) + '...' : '' }}
              </span>
              <span class="step-time">{{ formatTimestamp(step.timestamp) }}</span>
              <span class="step-toggle">{{ collapsedSteps.has(idx) ? '▶' : '▼' }}</span>
            </div>
            <div v-if="!collapsedSteps.has(idx)" class="react-step-body">
              {{ step.content }}
            </div>
          </div>

          <div v-if="generating" class="thinking-pulse">
            <span class="dot-pulse" />
            <span class="dot-pulse" style="animation-delay: 0.2s" />
            <span class="dot-pulse" style="animation-delay: 0.4s" />
            <span>思考中...</span>
          </div>

          <div v-if="!generating && reactSteps.length === 0" class="no-steps">
            尚無推理步驟
          </div>
        </div>
      </div>
    </div>

    <div class="step4-right">
      <div class="report-panel">
        <div class="report-panel-header">
          <h3 class="panel-heading">分析報告</h3>
          <button
            v-if="completed"
            class="pdf-btn"
            @click="exportPDF"
            :disabled="exporting"
          >
            {{ exporting ? '生成中...' : '匯出 PDF' }}
          </button>
        </div>

        <div v-if="!completed && !error" class="report-loading">
          <div class="spinner" />
          <p>報告生成中，請稍候...</p>
          <p class="loading-sub">AI 正在分析模擬數據...</p>
        </div>

        <div v-else-if="error" class="report-error">
          <p>{{ error }}</p>
          <button class="retry-btn" @click="startGeneration">重試</button>
        </div>

        <div v-else class="report-body">
          <span v-html="renderedDisplayReport" />
          <span v-if="isTyping" class="typing-cursor">_</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.step4 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  min-height: 500px;
}

.react-panel,
.report-panel {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 20px;
  display: flex;
  flex-direction: column;
}

.react-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  user-select: none;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border-color);
  margin-bottom: 14px;
}

.panel-heading {
  font-size: 16px;
  font-weight: 600;
  margin: 0;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.generating-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--accent-blue);
  background: var(--accent-blue-light);
  padding: 2px 8px;
  border-radius: 10px;
}

.step-count {
  font-size: 12px;
  color: var(--text-muted);
}

.collapse-icon {
  font-size: 11px;
  color: var(--text-muted);
}

/* Animated progress bar */
.gen-progress {
  height: 3px;
  background: var(--bg-input);
  border-radius: 2px;
  overflow: hidden;
  margin-bottom: 12px;
}

.gen-progress-fill {
  height: 100%;
  width: 40%;
  background: linear-gradient(90deg, var(--accent-cyan), var(--accent-blue));
  border-radius: 2px;
  animation: progress-slide 1.8s ease-in-out infinite;
}

@keyframes progress-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(350%); }
}

.react-steps {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.react-step {
  border-radius: var(--radius-sm);
  overflow: hidden;
  border: 1px solid transparent;
}

.react-step.step-thought {
  border-color: rgba(217, 119, 6, 0.2);
  background: rgba(217, 119, 6, 0.04);
}

.react-step.step-action {
  border-color: rgba(37, 99, 235, 0.2);
  background: rgba(37, 99, 235, 0.04);
}

.react-step.step-observe {
  border-color: rgba(5, 150, 105, 0.2);
  background: rgba(5, 150, 105, 0.04);
}

.react-step-header {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 8px 10px;
  cursor: pointer;
  user-select: none;
  font-size: 13px;
}

.step-icon {
  font-size: 14px;
  flex-shrink: 0;
}

.step-type-badge {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
  flex-shrink: 0;
  text-transform: uppercase;
}

.step-type-badge.step-thought {
  background: rgba(217, 119, 6, 0.1);
  color: var(--accent-orange);
}

.step-type-badge.step-action {
  background: var(--accent-blue-light);
  color: var(--accent-blue);
}

.step-type-badge.step-observe {
  background: rgba(5, 150, 105, 0.1);
  color: var(--accent-green);
}

.step-preview {
  flex: 1;
  color: var(--text-muted);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.step-time {
  font-size: 11px;
  color: var(--text-muted);
  flex-shrink: 0;
}

.step-toggle {
  font-size: 10px;
  color: var(--text-muted);
  flex-shrink: 0;
}

.react-step-body {
  padding: 0 10px 10px 34px;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.thinking-pulse {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px;
  color: var(--text-muted);
  font-size: 13px;
}

.dot-pulse {
  display: inline-block;
  width: 7px;
  height: 7px;
  background: var(--accent-blue);
  border-radius: 50%;
  animation: pulse 1s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 0.3; transform: scale(0.8); }
  50% { opacity: 1; transform: scale(1); }
}

.no-steps {
  padding: 20px;
  text-align: center;
  color: var(--text-muted);
  font-size: 13px;
}

.report-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border-color);
  margin-bottom: 14px;
}

.pdf-btn {
  padding: 6px 14px;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: var(--transition);
  white-space: nowrap;
}

.pdf-btn:hover:not(:disabled) {
  border-color: var(--accent-blue);
  color: var(--accent-blue);
}

.pdf-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* Report panel */
.report-loading {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--text-muted);
}

.loading-sub {
  font-size: 12px;
  color: var(--text-muted);
}

.spinner {
  width: 32px;
  height: 32px;
  border: 3px solid var(--border-color);
  border-top-color: var(--accent-blue);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.report-error {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  color: var(--accent-red);
}

.retry-btn {
  padding: 8px 20px;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-size: 13px;
  transition: var(--transition);
}

.retry-btn:hover {
  border-color: var(--accent-blue);
}

.report-body {
  flex: 1;
  overflow-y: auto;
  line-height: 1.8;
  font-size: 14px;
}

.report-body :deep(h1) {
  font-size: 22px;
  margin: 20px 0 10px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border-color);
}

.report-body :deep(h2) {
  font-size: 18px;
  margin: 16px 0 8px;
}

.report-body :deep(h3) {
  font-size: 15px;
  margin: 12px 0 6px;
}

.report-body :deep(p) {
  margin-bottom: 10px;
}

.report-body :deep(ul),
.report-body :deep(ol) {
  padding-left: 20px;
  margin-bottom: 10px;
}

.report-body :deep(code) {
  background: var(--bg-input);
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 12px;
}

.report-body :deep(blockquote) {
  border-left: 3px solid var(--accent-blue);
  padding-left: 14px;
  color: var(--text-secondary);
  margin-bottom: 10px;
}

.report-body :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin-bottom: 14px;
  font-size: 13px;
}

.report-body :deep(th),
.report-body :deep(td) {
  border: 1px solid var(--border-color);
  padding: 6px 10px;
}

.report-body :deep(th) {
  background: var(--bg-input);
}

/* Typewriter cursor */
.typing-cursor {
  display: inline;
  color: var(--accent-cyan);
  font-family: var(--font-mono, monospace);
  font-weight: 700;
  animation: cursor-blink 0.8s step-end infinite;
}

@keyframes cursor-blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}
</style>
