<script setup>
import { ref, onMounted } from 'vue'
import { chatWithReport, chatWithAgent, getReport } from '../api/report.js'

const props = defineProps({
  sessionId: { type: String, required: true },
})

const messages = ref([])
const inputText = ref('')
const targetType = ref('report')
const selectedAgent = ref('')
const agents = ref([])
const sending = ref(false)
const chatContainer = ref(null)

onMounted(async () => {
  messages.value = [
    {
      role: 'system',
      content: '歡迎進入深度交互模式。你可以針對報告內容提問，或者同個別代理人對話。',
    },
  ]
})

function scrollToBottom() {
  if (chatContainer.value) {
    requestAnimationFrame(() => {
      chatContainer.value.scrollTop = chatContainer.value.scrollHeight
    })
  }
}

async function sendMessage() {
  const text = inputText.value.trim()
  if (!text || sending.value) return

  const userMsg = { role: 'user', content: text }
  messages.value = [...messages.value, userMsg]
  inputText.value = ''
  sending.value = true
  scrollToBottom()

  try {
    let res
    if (targetType.value === 'agent' && selectedAgent.value) {
      res = await chatWithAgent({
        session_id: props.sessionId,
        agent_id: selectedAgent.value,
        message: text,
      })
    } else {
      res = await chatWithReport({
        session_id: props.sessionId,
        message: text,
      })
    }

    const assistantMsg = {
      role: 'assistant',
      content: res.data.response || res.data.message || '（無回應）',
    }
    messages.value = [...messages.value, assistantMsg]
  } catch (err) {
    const errorMsg = {
      role: 'error',
      content: '發送失敗：' + (err.response?.data?.detail || err.message),
    }
    messages.value = [...messages.value, errorMsg]
  } finally {
    sending.value = false
    scrollToBottom()
  }
}

function handleKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendMessage()
  }
}
</script>

<template>
  <div class="interaction-page">
    <div class="chat-sidebar">
      <h3 class="sidebar-title">對話設定</h3>

      <div class="setting-group">
        <label class="setting-label">對話對象</label>
        <select v-model="targetType" class="setting-select">
          <option value="report">報告分析師</option>
          <option value="agent">指定代理人</option>
        </select>
      </div>

      <div v-if="targetType === 'agent'" class="setting-group">
        <label class="setting-label">選擇代理人</label>
        <select v-model="selectedAgent" class="setting-select">
          <option value="" disabled>請選擇...</option>
          <option v-for="a in agents" :key="a.id" :value="a.id">
            {{ a.name }}
          </option>
        </select>
      </div>

      <div class="setting-group">
        <label class="setting-label">What-If 參數</label>
        <p class="setting-hint">喺對話中描述假設情景，例如「如果失業率升到 8%」</p>
      </div>
    </div>

    <div class="chat-main">
      <div ref="chatContainer" class="chat-messages">
        <div
          v-for="(msg, i) in messages"
          :key="i"
          class="chat-bubble"
          :class="msg.role"
        >
          <div class="bubble-label">
            <span v-if="msg.role === 'user'">你</span>
            <span v-else-if="msg.role === 'assistant'">AI</span>
            <span v-else-if="msg.role === 'system'">系統</span>
            <span v-else>錯誤</span>
          </div>
          <div class="bubble-content">{{ msg.content }}</div>
        </div>
      </div>

      <div class="chat-input-area">
        <textarea
          v-model="inputText"
          class="chat-input"
          placeholder="輸入你嘅問題..."
          rows="2"
          :disabled="sending"
          @keydown="handleKeydown"
        />
        <button
          class="send-btn"
          :disabled="!inputText.trim() || sending"
          @click="sendMessage"
        >
          {{ sending ? '發送中...' : '發送' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.interaction-page {
  display: flex;
  height: calc(100vh - 56px);
  max-width: 1400px;
  margin: 0 auto;
}

.chat-sidebar {
  width: 260px;
  background: var(--bg-secondary);
  border-right: 1px solid var(--border-color);
  padding: 24px 20px;
  flex-shrink: 0;
  overflow-y: auto;
}

.sidebar-title {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 24px;
  color: var(--text-primary);
}

.setting-group {
  margin-bottom: 20px;
}

.setting-label {
  display: block;
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 6px;
}

.setting-select {
  width: 100%;
  padding: 8px 10px;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-size: 14px;
}

.setting-hint {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.5;
}

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.chat-bubble {
  max-width: 720px;
  padding: 12px 16px;
  border-radius: var(--radius-md);
  font-size: 14px;
  line-height: 1.6;
}

.chat-bubble.user {
  align-self: flex-end;
  background: rgba(74, 158, 255, 0.15);
  border: 1px solid rgba(74, 158, 255, 0.3);
}

.chat-bubble.assistant {
  align-self: flex-start;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
}

.chat-bubble.system {
  align-self: center;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  color: var(--text-muted);
  font-size: 13px;
}

.chat-bubble.error {
  align-self: center;
  background: rgba(248, 113, 113, 0.1);
  border: 1px solid rgba(248, 113, 113, 0.3);
  color: var(--accent-red);
  font-size: 13px;
}

.bubble-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  margin-bottom: 4px;
  text-transform: uppercase;
}

.chat-input-area {
  padding: 16px 24px;
  border-top: 1px solid var(--border-color);
  display: flex;
  gap: 12px;
  background: var(--bg-secondary);
}

.chat-input {
  flex: 1;
  padding: 10px 14px;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  color: var(--text-primary);
  font-size: 14px;
  resize: none;
  outline: none;
  transition: var(--transition);
}

.chat-input:focus {
  border-color: var(--accent-blue);
}

.send-btn {
  padding: 10px 20px;
  background: var(--accent-blue);
  color: #fff;
  border: none;
  border-radius: var(--radius-md);
  font-size: 14px;
  font-weight: 600;
  transition: var(--transition);
  white-space: nowrap;
}

.send-btn:hover:not(:disabled) {
  background: #3d8be0;
}

.send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
