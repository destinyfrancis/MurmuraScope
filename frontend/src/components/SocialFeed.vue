<script setup>
import { ref, watch, nextTick, computed } from 'vue'

const props = defineProps({
  posts: { type: Array, default: () => [] },
  followedUsername: { type: String, default: null },
})

const emit = defineEmits(['clear-follow'])

const feedContainer = ref(null)
const autoScroll = ref(true)

const avatarColors = [
  '#2563EB', '#7C3AED', '#059669', '#D97706', '#0891B2',
  '#DC2626', '#CA8A04', '#4F46E5', '#C026D3', '#0284C7',
]

function getAvatarColor(name) {
  if (!name) return avatarColors[0]
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash)
  }
  return avatarColors[Math.abs(hash) % avatarColors.length]
}

function getInitial(name) {
  if (!name) return '?'
  return name.charAt(0).toUpperCase()
}

function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  return d.toLocaleTimeString('zh-HK', { hour: '2-digit', minute: '2-digit' })
}

watch(
  () => props.posts.length,
  () => {
    if (autoScroll.value && feedContainer.value) {
      nextTick(() => {
        feedContainer.value.scrollTop = feedContainer.value.scrollHeight
      })
    }
  }
)

function onScroll() {
  if (!feedContainer.value) return
  const el = feedContainer.value
  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60
  autoScroll.value = atBottom
}

// Platform badge styling
const PLATFORM_STYLES = {
  facebook:  { bg: '#1877F2', color: '#fff', label: 'Facebook' },
  instagram: { bg: '#E4405F', color: '#fff', label: 'Instagram' },
  twitter:   { bg: '#1DA1F2', color: '#fff', label: 'Twitter' },
  reddit:    { bg: '#FF4500', color: '#fff', label: 'Reddit' },
}

function getPlatformStyle(platform) {
  return PLATFORM_STYLES[platform?.toLowerCase()] || { bg: 'var(--bg-input)', color: 'var(--text-muted)', label: platform || '' }
}

// Facebook reaction emoji map
const FB_REACTIONS = {
  like:    { emoji: '👍', label: '讚好' },
  love:    { emoji: '❤️', label: '愛心' },
  angry:   { emoji: '😠', label: '嬲嬲' },
  haha:    { emoji: '😆', label: '哈哈' },
  sad:     { emoji: '😢', label: '慘慘' },
  wow:     { emoji: '😮', label: '嘩' },
}

const displayPosts = computed(() => {
  if (!props.followedUsername) return props.posts
  return props.posts.filter(p => (p.username || p.agent_name || '') === props.followedUsername)
})

function getFbReactions(post) {
  if (!post.reactions || typeof post.reactions !== 'object') return []
  return Object.entries(post.reactions)
    .filter(([, count]) => count > 0)
    .map(([type, count]) => ({
      ...(FB_REACTIONS[type] || { emoji: '👍', label: type }),
      count,
    }))
}
</script>

<template>
  <div class="social-feed">
    <div v-if="followedUsername" class="follow-filter-bar">
      <span class="follow-text">正在追蹤: {{ followedUsername }}</span>
      <button class="follow-clear" @click="emit('clear-follow')">清除篩選 &#10005;</button>
    </div>
    <div class="feed-header">
      <span class="feed-title">代理人動態</span>
      <span class="feed-count">{{ displayPosts.length }} 則貼文</span>
    </div>

    <div
      ref="feedContainer"
      class="feed-list"
      @scroll="onScroll"
    >
      <div v-if="displayPosts.length === 0" class="feed-empty">
        {{ followedUsername ? '此代理人暫無貼文' : '等待代理人發表動態...' }}
      </div>

      <div
        v-for="(post, i) in displayPosts"
        :key="i"
        class="post-card"
      >
        <div
          class="post-avatar"
          :style="{ background: getAvatarColor(post.username || post.agent_name) }"
        >
          {{ getInitial(post.username || post.agent_name) }}
        </div>

        <div class="post-body">
          <div class="post-header">
            <span class="post-username">{{ post.username || post.agent_name || '匿名' }}</span>
            <span
              v-if="post.platform"
              class="post-platform"
              :style="{
                background: getPlatformStyle(post.platform).bg,
                color: getPlatformStyle(post.platform).color,
              }"
            >{{ getPlatformStyle(post.platform).label }}</span>
            <span class="post-time">{{ formatTime(post.timestamp || post.created_at) }}</span>
          </div>

          <div class="post-content">{{ post.content || post.text }}</div>

          <div class="post-actions">
            <span class="action-item">
              <span class="action-icon">&#9825;</span>
              {{ post.likes || 0 }}
            </span>
            <span class="action-item">
              <span class="action-icon">&#128172;</span>
              {{ post.comments || 0 }}
            </span>
            <span v-if="post.sentiment" class="action-item sentiment">
              {{ post.sentiment > 0 ? '+' : '' }}{{ (post.sentiment * 100).toFixed(0) }}%
            </span>
          </div>

          <!-- Facebook reaction breakdown (shown when reactions object is present) -->
          <div
            v-if="getFbReactions(post).length > 0"
            class="fb-reactions"
          >
            <span
              v-for="reaction in getFbReactions(post)"
              :key="reaction.label"
              class="fb-reaction-item"
              :title="reaction.label"
            >
              {{ reaction.emoji }} {{ reaction.count }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <div
      v-if="!autoScroll && posts.length > 0"
      class="scroll-notice"
      @click="autoScroll = true"
    >
      有新貼文 - 點擊跳到底部
    </div>
  </div>
</template>

<style scoped>
.social-feed {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.follow-filter-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 14px;
  background: var(--accent-blue-light);
  border-left: 3px solid var(--accent-blue);
  flex-shrink: 0;
}

.follow-text {
  font-size: 12px;
  font-weight: 600;
  color: var(--accent-blue);
}

.follow-clear {
  background: transparent;
  border: 1px solid var(--border-color);
  color: var(--text-secondary);
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  cursor: pointer;
  transition: color 0.2s, border-color 0.2s;
}

.follow-clear:hover {
  color: var(--text-primary);
  border-color: var(--accent-blue);
}

.feed-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border-color);
}

.feed-title {
  font-size: 13px;
  font-weight: 600;
}

.feed-count {
  font-size: 12px;
  color: var(--text-muted);
}

.feed-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.feed-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-muted);
  font-size: 13px;
}

.post-card {
  display: flex;
  gap: 10px;
  padding: 10px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  margin-bottom: 4px;
  transition: var(--transition);
}

.post-card:hover {
  border-color: var(--accent-blue);
  box-shadow: var(--shadow-md);
}

.post-card:last-child {
  border-bottom: none;
}

.post-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 700;
  color: #fff;
  flex-shrink: 0;
  box-shadow: none;
}

.post-body {
  flex: 1;
  min-width: 0;
}

.post-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.post-username {
  font-size: 13px;
  font-weight: 600;
}

.post-platform {
  font-size: 10px;
  padding: 1px 6px;
  background: var(--bg-input);
  border-radius: 3px;
  color: var(--text-muted);
}

.post-time {
  font-size: 11px;
  color: var(--text-muted);
  margin-left: auto;
}

.post-content {
  font-size: 13px;
  line-height: 1.5;
  color: var(--text-secondary);
  word-break: break-word;
}

.post-actions {
  display: flex;
  gap: 16px;
  margin-top: 6px;
}

.action-item {
  font-size: 12px;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 4px;
}

.action-icon {
  font-size: 13px;
}

.action-item.sentiment {
  margin-left: auto;
  font-weight: 600;
  color: var(--accent-blue);
}

.scroll-notice {
  text-align: center;
  padding: 6px;
  font-size: 12px;
  color: var(--accent-blue);
  cursor: pointer;
  border-top: 1px solid var(--border-color);
  background: var(--bg-secondary);
}

.scroll-notice:hover {
  background: var(--bg-input);
}

/* Facebook reaction strip */
.fb-reactions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 5px;
}

.fb-reaction-item {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: 11px;
  color: var(--text-muted);
  background: var(--bg-input);
  border-radius: 10px;
  padding: 1px 7px;
}
</style>
