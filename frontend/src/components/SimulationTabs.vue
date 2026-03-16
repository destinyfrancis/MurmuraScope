<script setup>
import { computed } from 'vue'
import SocialFeed from './SocialFeed.vue'
import DissonanceView from './DissonanceView.vue'

const props = defineProps({
  activeTab: { type: String, required: true },
  posts: { type: Array, required: true },
  followedAgent: { type: Object, default: null },
  sessionAgents: { type: Array, default: () => [] },
  sessionId: { type: String, default: null },
  logs: { type: Array, default: () => [] },
})

const emit = defineEmits(['update:activeTab', 'select-agent', 'clear-follow'])

// TOPIC COMMUNITY: group posts by hashtag
const topicGroups = computed(() => {
  const tagMap = {}
  for (const post of props.posts) {
    const content = post.content || ''
    const matches = content.match(/#[\w\u4e00-\u9fff]+/g) || []
    for (const tag of matches) {
      if (!tagMap[tag]) tagMap[tag] = { tag, posts: [], count: 0 }
      tagMap[tag].posts = [...tagMap[tag].posts, post]
      tagMap[tag].count++
    }
  }
  return Object.values(tagMap)
    .sort((a, b) => b.count - a.count)
    .slice(0, 12)
})

function setTab(tab) {
  emit('update:activeTab', tab)
}

function handleSelectAgent(agent) {
  emit('select-agent', agent)
}
</script>

<template>
  <div class="tab-bar">
    <button
      class="tab-btn"
      :class="{ active: activeTab === 'feed' }"
      @click="setTab('feed')"
    >
      動態廣場
    </button>
    <button
      class="tab-btn topic-tab"
      :class="{ active: activeTab === 'topic' }"
      @click="setTab('topic')"
    >
      話題社群
    </button>
    <button
      class="tab-btn agent-tab"
      :class="{ active: activeTab === 'agents' }"
      @click="setTab('agents')"
    >
      代理人
    </button>
    <button
      class="tab-btn network-tab"
      :class="{ active: activeTab === 'network' }"
      @click="setTab('network')"
    >
      網絡演化
    </button>
    <button
      class="tab-btn emotion-tab"
      :class="{ active: activeTab === 'emotion' }"
      @click="setTab('emotion')"
    >
      情緒地圖
    </button>
  </div>

  <div class="feed-area">
    <SocialFeed
      v-if="activeTab === 'feed'"
      :posts="posts"
      :followed-username="followedAgent?.username"
      @clear-follow="emit('clear-follow')"
    />
    <div v-else-if="activeTab === 'topic'" class="topic-feed">
      <div v-if="topicGroups.length === 0" class="topic-empty">
        等待話題生成...
      </div>
      <div
        v-for="group in topicGroups"
        :key="group.tag"
        class="topic-group"
      >
        <div class="topic-header">
          <span class="topic-tag">{{ group.tag }}</span>
          <span class="topic-count">{{ group.count }} 條貼文</span>
        </div>
        <p class="topic-preview">
          {{ (group.posts[group.posts.length - 1]?.content || '').slice(0, 120) }}
        </p>
      </div>
    </div>
    <div v-else-if="activeTab === 'agents'" class="agent-tab-content">
      <div v-if="sessionAgents.length === 0" class="topic-empty">載入代理人...</div>
      <div
        v-for="agent in sessionAgents"
        :key="agent.id"
        class="agent-tab-card"
        :class="{ followed: followedAgent?.agentId === agent.id }"
        @click="handleSelectAgent(agent)"
      >
        <div class="agent-tab-name">{{ agent.oasis_username || `代理人 #${agent.id}` }}</div>
        <div class="agent-tab-meta">
          <span v-if="agent.district">{{ agent.district }}</span>
          <span v-if="agent.occupation">{{ agent.occupation }}</span>
        </div>
      </div>
      <!-- Dissonance section within agents tab -->
      <DissonanceView
        v-if="sessionId && sessionAgents.length > 0"
        :session-id="sessionId"
        style="margin-top: 12px;"
      />
    </div>
    <div v-else-if="activeTab === 'network'" class="tab-content-full">
      <slot name="network" />
    </div>
    <div v-else-if="activeTab === 'emotion'" class="tab-content-full">
      <slot name="emotion" />
    </div>
  </div>
</template>

<style scoped>
.tab-bar {
  display: flex;
  gap: 0;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  overflow: hidden;
  flex-shrink: 0;
}

.tab-btn {
  flex: 1;
  padding: 10px 8px;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.5px;
  transition: var(--transition);
  cursor: pointer;
}

.tab-btn:not(:last-child) {
  border-right: 1px solid var(--border-color);
}

.tab-btn.active {
  background: rgba(74, 158, 255, 0.08);
  color: var(--accent-blue);
  border-bottom-color: var(--accent-blue);
}

.tab-btn.topic-tab.active {
  background: rgba(52, 211, 153, 0.08);
  color: var(--accent-green);
  border-bottom-color: var(--accent-green);
}

.tab-btn.agent-tab.active {
  background: rgba(167, 139, 250, 0.08);
  color: #a78bfa;
  border-bottom-color: #a78bfa;
}

.feed-area {
  flex: 1;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  overflow: hidden;
  min-height: 0;
}

/* TOPIC COMMUNITY styles */
.topic-feed {
  height: 100%;
  overflow-y: auto;
  padding: 8px;
}

.topic-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-muted);
  font-size: 13px;
}

.topic-group {
  padding: 12px;
  border-bottom: 1px solid var(--border-color);
  cursor: pointer;
  transition: var(--transition);
}

.topic-group:hover {
  background: var(--bg-secondary);
}

.topic-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}

.topic-tag {
  font-size: 14px;
  font-weight: 700;
  color: var(--accent-green);
}

.topic-count {
  font-size: 11px;
  color: var(--text-muted);
  background: var(--bg-input);
  padding: 2px 8px;
  border-radius: 10px;
}

.topic-preview {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.5;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

/* AGENT TAB styles */
.agent-tab-content {
  height: 100%;
  overflow-y: auto;
  padding: 8px;
}

.agent-tab-card {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-color);
  cursor: pointer;
  transition: background 0.2s, border-color 0.2s;
}

.agent-tab-card:hover {
  background: var(--bg-secondary);
}

.agent-tab-card.followed {
  background: rgba(74, 158, 255, 0.08);
  border-left: 3px solid var(--accent-blue);
}

.agent-tab-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 3px;
}

.agent-tab-meta {
  display: flex;
  gap: 8px;
  font-size: 11px;
  color: var(--text-muted);
}

.tab-btn.network-tab.active {
  background: rgba(59, 130, 246, 0.08);
  color: #3b82f6;
  border-bottom-color: #3b82f6;
}

.tab-btn.emotion-tab.active {
  background: rgba(239, 68, 68, 0.08);
  color: #ef4444;
  border-bottom-color: #ef4444;
}

.tab-content-full {
  height: 100%;
  overflow-y: auto;
  padding: 0;
}
</style>
