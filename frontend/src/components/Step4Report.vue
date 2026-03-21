<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { marked } from 'marked'
import { generateReport, getReportStatus, invokeXaiTool, shareReport } from '../api/report.js'
import { getConfidenceScore } from '../api/simulation.js'
import ConfidenceBadge from './ConfidenceBadge.vue'

const props = defineProps({
  session: { type: Object, required: true },
  scenarioQuestion: { type: String, default: '' },
})

const emit = defineEmits(['report-generated', 'update:session'])

const sharing = ref(false)
const shareStatus = ref('')
async function handleShare() {
  const reportId = props.session.reportId
  if (!reportId) return
  sharing.value = true
  shareStatus.value = ''
  try {
    const res = await shareReport(reportId)
    const token = res.data?.data?.token || res.data?.token
    if (token) {
      const url = `${window.location.origin}/report/public/${token}`
      await navigator.clipboard.writeText(url)
      shareStatus.value = '分享連結已複製到剪貼板'
    } else {
      shareStatus.value = '分享成功'
    }
  } catch (e) {
    console.error('Share error:', e)
    shareStatus.value = '分享失敗，請稍後再試'
  } finally {
    sharing.value = false
    setTimeout(() => { shareStatus.value = '' }, 4000)
  }
}

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
    a.download = `murmuroscope-report-${reportId}.pdf`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    console.error('PDF export error:', e)
    alert('PDF 匯出失敗，請稍後再試')
  } finally {
    exporting.value = false
  }
}

const questionInput = ref(props.scenarioQuestion)

const generating = ref(false)
const completed = ref(false)
const error = ref(null)
const reportContent = ref('')
const reactSteps = ref([])

// Collapsible "AI 推理過程" section
const reasoningOpen = ref(true)
const collapsedSteps = ref(new Set())

const startTime = ref(null)
const elapsedLabel = ref('0s')
let elapsedTimer = null

function startElapsedTimer() {
  if (elapsedTimer) {
    clearInterval(elapsedTimer)
    elapsedTimer = null
  }
  startTime.value = Date.now()
  elapsedTimer = setInterval(() => {
    const sec = Math.round((Date.now() - startTime.value) / 1000)
    elapsedLabel.value = sec < 60 ? `${sec}s` : `${Math.floor(sec/60)}m ${sec%60}s`
  }, 1000)
}

const toolCallCount = computed(() =>
  reactSteps.value.filter(s => s.step_type === 'Action').length
)

// Typewriter effect state
const displayedReport = ref('')
const isTyping = ref(false)
let typewriterTimer = null

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
    const data = res.data?.data || res.data

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
      fetchConfidenceScore()
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
  startElapsedTimer()
  generating.value = true
  error.value = null
  reactSteps.value = []
  reportContent.value = ''
  collapsedSteps.value = new Set()
  xaiResults.value = {}
  xaiLoading.value = null

  reactSteps.value = [{
    step_type: 'Thought',
    content: '初始化報告生成流程...',
    timestamp: new Date().toISOString(),
  }]

  try {
    const res = await generateReport({
      session_id: props.session.sessionId,
      scenario_type: props.session.scenarioType,
      scenario_question: questionInput.value || undefined,
    })

    const resData = res.data?.data || res.data
    const reportId = resData.report_id
    emit('update:session', { ...props.session, reportId: reportId })

    // If agent_log is already in the response (synchronous generation), use it directly
    if (resData.agent_log?.length) {
      mergeReactSteps(resData.agent_log)
    }
    if (resData.content_markdown) {
      reportContent.value = resData.content_markdown
      completed.value = true
      generating.value = false
      emit('report-generated', { reportId })
      fetchConfidenceScore()
      return
    }

    reactSteps.value = [...reactSteps.value, {
      step_type: 'Action',
      content: '報告生成請求已提交，開始 ReACT 分析循環...',
      timestamp: new Date().toISOString(),
    }]

    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
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
  if (elapsedTimer) { clearInterval(elapsedTimer); elapsedTimer = null; }
})

// ---------------------------------------------------------------------------
// XAI tool panel
// ---------------------------------------------------------------------------

const XAI_TOOLS = [
  { name: 'query_graph',                label: '知識圖譜查詢' },
  { name: 'get_global_narrative',       label: '全局敘事分析' },
  { name: 'get_sentiment_distribution', label: '情緒分佈' },
  { name: 'get_demographic_breakdown',  label: '人口結構拆解' },
  { name: 'interview_agents',           label: '智能體訪談' },
  { name: 'get_macro_context',          label: '宏觀經濟背景' },
  { name: 'calculate_cashflow',         label: '現金流預測' },
  { name: 'get_decision_summary',       label: '決策統計摘要' },
  { name: 'get_sentiment_timeline',     label: '情緒時間軸' },
  { name: 'get_ensemble_forecast',      label: '集成預測分佈' },
  { name: 'get_macro_history',          label: '宏觀指標歷史' },
  { name: 'get_validation_summary',     label: '預測可信度報告' },
  { name: 'insight_forge',              label: '深度洞察查詢' },
  { name: 'get_topic_evolution',        label: '議題演變追蹤' },
  { name: 'get_platform_breakdown',     label: '平台行為拆解' },
  { name: 'get_agent_story_arcs',       label: 'Agent 故事弧線' },
]

const confidenceScore = ref(null)

async function fetchConfidenceScore() {
  const sessionId = props.session?.sessionId
  if (!sessionId) return
  try {
    const res = await getConfidenceScore(sessionId)
    const score = res.data?.data?.score ?? res.data?.score ?? null
    confidenceScore.value = score
  } catch {
    confidenceScore.value = null
  }
}

const xaiResults = ref({})
const xaiLoading = ref(null)

async function runXaiTool(toolName) {
  if (!props.session?.sessionId) return
  xaiLoading.value = toolName
  try {
    const result = await invokeXaiTool(props.session.sessionId, toolName)
    xaiResults.value = { ...xaiResults.value, [toolName]: result }
  } catch (e) {
    xaiResults.value = { ...xaiResults.value, [toolName]: { error: e.message } }
  } finally {
    xaiLoading.value = null
  }
}
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

        <!-- Stats bar -->
        <div class="react-stats">
          <span class="react-stat">
            <span class="stat-value">{{ reactSteps.length }}</span>
            <span class="stat-label">STEPS</span>
          </span>
          <span class="react-stat">
            <span class="stat-value">{{ toolCallCount }}</span>
            <span class="stat-label">TOOLS</span>
          </span>
          <span class="react-stat">
            <span class="stat-value">{{ elapsedLabel }}</span>
            <span class="stat-label">ELAPSED</span>
          </span>
          <span v-if="completed" class="react-stat stat-done">
            <span class="stat-value">DONE</span>
          </span>
        </div>

        <div v-if="reasoningOpen" class="react-steps">
          <div
            v-for="(step, idx) in reactSteps"
            :key="idx"
            class="timeline-item"
            :class="{ 'is-last': idx === reactSteps.length - 1 }"
          >
            <div class="timeline-connector">
              <div
                class="timeline-dot"
                :class="{
                  'dot-thought': step.step_type === 'Thought',
                  'dot-action': step.step_type === 'Action',
                  'dot-observe': step.step_type === 'Observation',
                  'dot-active': idx === reactSteps.length - 1 && generating,
                }"
              />
              <div v-if="idx < reactSteps.length - 1" class="timeline-line" />
            </div>
            <div class="timeline-content" @click="toggleStep(idx)">
              <div class="timeline-header">
                <span class="step-type-badge" :class="stepClass(step.step_type)">
                  {{ step.step_type }}
                </span>
                <span class="step-time">{{ formatTimestamp(step.timestamp) }}</span>
              </div>
              <div v-if="!collapsedSteps.has(idx)" class="timeline-body">
                {{ step.content }}
              </div>
            </div>
          </div>

          <div v-if="generating" class="timeline-item">
            <div class="timeline-connector">
              <div class="timeline-dot dot-active dot-pulsing" />
            </div>
            <div class="timeline-content">
              <div class="thinking-dots">
                <span class="t-dot" />
                <span class="t-dot" style="animation-delay: 0.2s" />
                <span class="t-dot" style="animation-delay: 0.4s" />
                <span>思考中...</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="step4-right">
      <div class="report-panel">
        <div class="report-panel-header">
          <h3 class="panel-heading">
            分析報告
            <ConfidenceBadge
              v-if="confidenceScore != null"
              :score="confidenceScore"
              size="lg"
              class="confidence-inline"
            />
          </h3>
          <div v-if="completed" class="report-actions">
            <button
              class="pdf-btn"
              @click="handleShare"
              :disabled="sharing"
            >
              {{ sharing ? '分享中...' : '分享報告' }}
            </button>
            <button
              class="pdf-btn"
              @click="exportPDF"
              :disabled="exporting"
            >
              {{ exporting ? '生成中...' : '匯出 PDF' }}
            </button>
          </div>
          <span v-if="shareStatus" class="share-status">{{ shareStatus }}</span>
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

        <!-- Question input — always visible so user can set context before generating -->
        <div class="report-question-row">
          <input
            v-model="questionInput"
            class="report-question-input"
            :disabled="generating"
            placeholder="分析問題（可選）：例如「GDP 增長率會轉負嗎？」"
          />
        </div>

        <!-- Regen button — only after first completion -->
        <div v-if="completed" class="report-regen-row">
          <button class="report-regen-btn" @click="startGeneration">重新生成</button>
        </div>
      </div>
    </div>

    <!-- XAI sidebar — visible only after report is complete -->
    <div v-if="completed" class="xai-sidebar">
      <h3 class="xai-title">🔬 深度分析工具</h3>
      <button
        v-for="tool in XAI_TOOLS"
        :key="tool.name"
        class="xai-btn"
        :class="{ active: xaiLoading === tool.name }"
        :disabled="xaiLoading !== null"
        @click="runXaiTool(tool.name)"
      >
        <span v-if="xaiLoading === tool.name">⏳ </span>{{ tool.label }}
      </button>
      <div
        v-for="(result, name) in xaiResults"
        :key="name"
        class="xai-result-block"
      >
        <h4 class="xai-result-title">{{ name }}</h4>
        <pre class="xai-result-body">{{ JSON.stringify(result, null, 2) }}</pre>
      </div>
    </div>
  </div>
</template>

<style scoped>
.step4 {
  display: grid;
  grid-template-columns: 1fr 1fr 220px;
  gap: 20px;
  min-height: 500px;
  align-items: start;
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

/* Stats bar */
.react-stats {
  display: flex;
  gap: 12px;
  margin-bottom: 14px;
  padding: 8px 0;
  border-bottom: 1px solid var(--border);
}
.react-stat {
  display: flex;
  align-items: center;
  gap: 4px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
  background: #F5F5F5;
  padding: 4px 12px;
  border-radius: 20px;
}
.stat-value {
  font-weight: 700;
  color: var(--text-primary, #000);
}
.stat-label {
  color: var(--text-muted, #999);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.stat-done .stat-value {
  color: var(--accent-success, #10B981);
}

/* Timeline */
.react-steps {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
.timeline-item {
  display: grid;
  grid-template-columns: 24px 1fr;
  gap: 12px;
  min-height: 0;
}
.timeline-connector {
  display: flex;
  flex-direction: column;
  align-items: center;
}
.timeline-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #D1D5DB;
  border: 2px solid var(--bg-card, #FFF);
  flex-shrink: 0;
  z-index: 1;
}
.dot-thought { background: #F59E0B; }
.dot-action  { background: var(--text-primary, #000); }
.dot-observe { background: var(--accent-success, #10B981); }
.dot-active {
  box-shadow: 0 0 0 3px rgba(0, 0, 0, 0.1);
}
.dot-pulsing {
  animation: dot-pulse 1.5s infinite;
}
@keyframes dot-pulse {
  0%, 100% { box-shadow: 0 0 0 3px rgba(0, 0, 0, 0.1); }
  50%      { box-shadow: 0 0 0 5px rgba(0, 0, 0, 0.05); }
}
.timeline-line {
  width: 2px;
  flex: 1;
  background: #F3F4F6;
  min-height: 8px;
}
.timeline-content {
  padding: 4px 12px 16px;
  cursor: pointer;
  border-radius: var(--radius-md, 4px);
  transition: background var(--duration-fast, 0.15s);
}
.timeline-content:hover {
  background: #F9FAFB;
}
.timeline-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.step-type-badge {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 2px;
  font-family: var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.step-type-badge.step-thought { background: rgba(245,158,11,0.1); color: #D97706; }
.step-type-badge.step-action  { background: rgba(0,0,0,0.06); color: #000; }
.step-type-badge.step-observe { background: rgba(16,185,129,0.1); color: #059669; }
.step-time {
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--text-quaternary, #9CA3AF);
}
.timeline-body {
  font-size: 13px;
  color: var(--text-secondary, #666);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.thinking-dots {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-muted, #999);
  padding: 4px 0;
}
.t-dot {
  width: 8px;
  height: 8px;
  background: var(--text-muted, #999);
  border-radius: 50%;
  animation: typing-bounce 1.4s infinite ease-in-out;
}
@keyframes typing-bounce {
  0%, 100% { transform: translateY(0); }
  30%      { transform: translateY(-8px); }
}

.confidence-inline {
  margin-left: 10px;
  vertical-align: middle;
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

.report-actions {
  display: flex;
  gap: 8px;
}

.share-status {
  font-size: 11px;
  color: var(--text-muted);
  white-space: nowrap;
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

.report-question-row {
  margin-bottom: 12px;
}

.report-regen-row {
  display: flex;
  gap: 0.75rem;
  margin-top: 0.5rem;
  padding-top: 1rem;
  border-top: 1px solid var(--border-color);
}
.report-question-input {
  width: 100%;
  background: var(--bg-input, var(--bg-secondary));
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-primary);
  padding: 0.5rem 0.75rem;
  font-size: 0.9rem;
}
.report-question-input:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.report-regen-btn {
  white-space: nowrap;
  padding: 0.5rem 1rem;
  border-radius: 8px;
  background: var(--accent-blue);
  color: #fff;
  border: none;
  cursor: pointer;
  font-size: 0.9rem;
}

/* XAI sidebar */
.xai-sidebar {
  width: 220px;
  flex-shrink: 0;
  padding: 12px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  overflow-y: auto;
  max-height: 80vh;
}
.xai-title {
  margin: 0 0 10px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-muted, #aaa);
}
.xai-btn {
  display: block;
  width: 100%;
  margin-bottom: 6px;
  padding: 7px 10px;
  background: var(--bg-input, #1e1e1e);
  border: 1px solid var(--border-color, #333);
  border-radius: 5px;
  color: var(--text-primary, #e0e0e0);
  cursor: pointer;
  text-align: left;
  font-size: 12px;
  transition: var(--transition);
}
.xai-btn:hover:not(:disabled) {
  border-color: var(--accent-orange, #FF6B35);
  color: var(--accent-orange, #FF6B35);
}
.xai-btn.active,
.xai-btn:disabled {
  opacity: 0.5;
  cursor: wait;
}
.xai-result-block {
  margin-top: 10px;
  border-top: 1px solid var(--border-color, #333);
  padding-top: 8px;
}
.xai-result-title {
  margin: 0 0 4px;
  font-size: 11px;
  font-weight: 600;
  color: var(--accent-orange, #FF6B35);
}
.xai-result-body {
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 10px;
  font-family: var(--font-mono, monospace);
  max-height: 180px;
  overflow-y: auto;
  margin: 0;
  color: var(--text-secondary, #888);
}
</style>
