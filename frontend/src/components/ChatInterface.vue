<script setup>
import { ref, nextTick } from 'vue'
import { chatWithReport, chatWithAgent } from '../api/report.js'

const props = defineProps({
  sessionId: { type: String, required: true },
  reportId: { type: String, default: null },
  targetType: { type: String, default: 'report' },
  selectedAgent: { type: Object, default: null },
  interviewMode: { type: Boolean, default: false },
})

const emit = defineEmits(['update:interviewMode'])

const messages = ref([
  {
    role: 'system',
    content: '深度交互模式已啟動。你可以針對報告內容提問，或者選擇同個別代理人對話，仲可以提出 What-If 假設情景。',
  },
])
const inputText = ref('')
const sending = ref(false)
const chatContainer = ref(null)

const interviewQuestions = [
  '你對目前香港樓市有咩睇法？',
  '你有冇考慮過移民？點解？',
  '你覺得而家嘅經濟環境對你有咩影響？',
  '你平時喺社交媒體會討論啲咩話題？',
  '你對政府嘅房屋政策有咩意見？',
]

const generalQuestions = [
  '邊個群體最受加息影響？',
  '如果失業率升到 8%，結果會點變？',
  '代理人之間嘅主要分歧係乜？',
  '報告嘅核心結論係乜？',
]

function scrollToBottom() {
  if (chatContainer.value) {
    nextTick(() => {
      chatContainer.value.scrollTop = chatContainer.value.scrollHeight
    })
  }
}

function resetMessages(systemMsg) {
  messages.value = [{ role: 'system', content: systemMsg }]
}

async function sendMessage(text) {
  const msg = (text || inputText.value).trim()
  if (!msg || sending.value) return

  messages.value = [...messages.value, {
    role: props.interviewMode && props.targetType === 'agent' ? 'interviewer' : 'user',
    content: msg,
  }]
  inputText.value = ''
  sending.value = true
  scrollToBottom()

  try {
    let res
    if (props.targetType === 'agent' && props.selectedAgent) {
      res = await chatWithAgent({
        session_id: props.sessionId,
        agent_id: props.selectedAgent.id,
        message: msg,
      })
    } else {
      res = await chatWithReport({
        session_id: props.sessionId,
        report_id: props.reportId,
        message: msg,
      })
    }

    messages.value = [
      ...messages.value,
      {
        role: 'assistant',
        content: res.data.response || res.data.reply || res.data.message || res.data?.data?.answer || '（無回應）',
      },
    ]
  } catch (err) {
    messages.value = [
      ...messages.value,
      {
        role: 'error',
        content: '發送失敗：' + (err.response?.data?.detail || err.message),
      },
    ]
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

defineExpose({ resetMessages })
</script>

<template>
  <div class="step5-main">
    <div class="chat-toolbar">
      <!-- Interview mode toggle -->
      <label class="interview-toggle">
        <input
          :checked="interviewMode"
          type="checkbox"
          class="toggle-input"
          @change="$emit('update:interviewMode', $event.target.checked)"
        />
        <span class="toggle-track">
          <span class="toggle-thumb" />
        </span>
        <span class="toggle-label">訪問模式</span>
      </label>

      <div class="quick-section">
        <span class="quick-label">
          {{ targetType === 'agent' && selectedAgent ? '訪問問題' : '快速提問' }}
        </span>
        <div class="quick-questions">
          <button
            v-for="q in (targetType === 'agent' && selectedAgent ? interviewQuestions : generalQuestions)"
            :key="q"
            class="quick-btn"
            @click="sendMessage(q)"
          >
            {{ q }}
          </button>
        </div>
      </div>
    </div>

    <div ref="chatContainer" class="message-list">
      <div
        v-for="(msg, i) in messages"
        :key="i"
        class="msg-bubble"
        :class="[msg.role, { 'interview-mode': interviewMode && (msg.role === 'interviewer' || msg.role === 'assistant') }]"
      >
        <div class="msg-label">
          <span v-if="msg.role === 'user'">你</span>
          <span v-else-if="msg.role === 'interviewer'">訪問員</span>
          <span v-else-if="msg.role === 'assistant'">
            {{ targetType === 'agent' && selectedAgent
              ? (selectedAgent.oasis_username || selectedAgent.username || `代理人 #${selectedAgent.id}`)
              : 'AI 分析師' }}
          </span>
          <span v-else-if="msg.role === 'system'">系統</span>
          <span v-else>錯誤</span>
        </div>
        <div class="msg-content">{{ msg.content }}</div>
      </div>

      <div v-if="sending" class="typing-indicator">
        <span /><span /><span />
      </div>
    </div>

    <div class="input-bar">
      <textarea
        v-model="inputText"
        class="msg-input"
        :placeholder="targetType === 'agent' && selectedAgent
          ? `向 ${selectedAgent.oasis_username || selectedAgent.username || '代理人'} 提問...`
          : '輸入你嘅問題...'"
        rows="2"
        :disabled="sending"
        @keydown="handleKeydown"
      />
      <button
        class="send-btn"
        :disabled="!inputText.trim() || sending"
        @click="sendMessage()"
      >
        發送
      </button>
    </div>
  </div>
</template>

<style scoped>
.step5-main {
  display: flex;
  flex-direction: column;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.chat-toolbar {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.interview-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  user-select: none;
  width: fit-content;
}

.toggle-input { display: none; }

.toggle-track {
  width: 36px;
  height: 20px;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  position: relative;
  transition: background 0.2s, border-color 0.2s;
}

.toggle-input:checked + .toggle-track {
  background: var(--accent-blue);
  border-color: var(--accent-blue);
}

.toggle-thumb {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 14px;
  height: 14px;
  background: #fff;
  border-radius: 50%;
  transition: transform 0.2s;
}

.toggle-input:checked ~ .toggle-track .toggle-thumb,
.toggle-input:checked + .toggle-track .toggle-thumb {
  transform: translateX(16px);
}

.toggle-label {
  font-size: 13px;
  color: var(--text-secondary);
}

.quick-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.quick-label {
  font-size: 11px;
  color: var(--text-muted);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.quick-questions {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.quick-btn {
  padding: 5px 10px;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.4;
  transition: var(--transition);
  text-align: left;
}

.quick-btn:hover {
  border-color: var(--accent-blue);
  color: var(--text-primary);
}

.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.msg-bubble {
  max-width: 680px;
  padding: 10px 14px;
  border-radius: var(--radius-md);
  font-size: 14px;
  line-height: 1.6;
}

.msg-bubble.user {
  align-self: flex-end;
  background: var(--accent-blue-light);
  border: 1px solid rgba(37, 99, 235, 0.2);
}

.msg-bubble.interviewer,
.msg-bubble.user.interview-mode {
  align-self: flex-end;
  background: var(--accent-blue-light);
  border: 1px solid rgba(37, 99, 235, 0.3);
}

.msg-bubble.assistant.interview-mode {
  align-self: flex-start;
  background: rgba(5, 150, 105, 0.08);
  border: 1px solid rgba(5, 150, 105, 0.2);
}

.msg-bubble.assistant {
  align-self: flex-start;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
}

.msg-bubble.system {
  align-self: center;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  color: var(--text-muted);
  font-size: 13px;
  text-align: center;
}

.msg-bubble.error {
  align-self: center;
  color: var(--accent-red);
  font-size: 13px;
}

.msg-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  margin-bottom: 4px;
}

.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 8px 14px;
}

.typing-indicator span {
  width: 6px;
  height: 6px;
  background: var(--text-muted);
  border-radius: 50%;
  animation: bounce 1.2s ease-in-out infinite;
}

.typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
.typing-indicator span:nth-child(3) { animation-delay: 0.4s; }

@keyframes bounce {
  0%, 80%, 100% { transform: translateY(0); }
  40% { transform: translateY(-6px); }
}

.input-bar {
  display: flex;
  gap: 10px;
  padding: 14px 20px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-secondary);
}

.msg-input {
  flex: 1;
  padding: 10px 12px;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  color: var(--text-primary);
  font-size: 14px;
  resize: none;
  outline: none;
}

.msg-input:focus {
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
}

.send-btn:hover:not(:disabled) {
  background: #1d4ed8;
}

.send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
