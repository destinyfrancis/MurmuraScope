<script setup>
defineProps({
  post: { type: Object, required: true },
  factionColour: { type: String, default: '#999' },
  repostCount: { type: Number, default: 0 },
  replyCount: { type: Number, default: 0 },
})

const emit = defineEmits(['repost', 'reply', 'select-agent'])

function avatarInitial(name) {
  return (name || '?')[0].toUpperCase()
}

function actionLabel(post) {
  if (post._type === 'world_event') return 'EVENT'
  const content = (post.content || '').toLowerCase()
  if (content.includes('comment') || content.includes('reply') || content.includes('回覆')) return 'COMMENT'
  if (content.includes('repost') || content.includes('轉發')) return 'REPOST'
  if (!content || content === 'idle') return 'IDLE'
  return 'POST'
}

function sentimentDot(sentiment) {
  if (sentiment > 0.2) return 'dot-positive'
  if (sentiment < -0.2) return 'dot-negative'
  return 'dot-neutral'
}
</script>

<template>
  <div class="post-card" :class="{ 'post-event': post._type === 'world_event' }">
    <div class="post-avatar" :style="{ background: factionColour }">
      {{ avatarInitial(post.username || post.title) }}
    </div>
    <div class="post-main">
      <div class="post-header">
        <span class="post-author" @click.stop="emit('select-agent', { id: post.agent_id })">{{ post.username || post.title || `Agent #${post.agent_id}` }}</span>
        <span v-if="post.tier === 1 || post.agent_tier === 1" class="post-tier">T1</span>
        <span class="post-action-badge" :class="'badge-' + actionLabel(post).toLowerCase()">
          {{ actionLabel(post) }}
        </span>
        <span class="post-round">R{{ post.round_number ?? post.round ?? post._round }}</span>
      </div>
      <p class="post-content">{{ (post.content || post.description || '').slice(0, 280) }}</p>
      <div v-if="post.parent_content" class="post-quote">
        {{ post.parent_content.slice(0, 120) }}
      </div>
      <div class="post-footer">
        <span v-if="post.sentiment != null" class="post-sentiment">
          <span class="sentiment-dot" :class="sentimentDot(post.sentiment)" />
          {{ post.sentiment > 0 ? '+' : '' }}{{ (post.sentiment * 100).toFixed(0) }}%
        </span>
        <span v-if="post.engagement" class="post-engagement">{{ post.engagement }} 互動</span>
        <span class="post-spacer" />
        <button class="post-react-btn" @click="emit('repost', post)">
          ↩ 轉發 <span v-if="repostCount">{{ repostCount }}</span>
        </button>
        <button class="post-react-btn" @click="emit('reply', post)">
          ← 評論 <span v-if="replyCount">{{ replyCount }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.post-card {
  display: flex;
  gap: 12px;
  padding: 16px 20px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm, 2px);
  transition: box-shadow var(--duration-standard, 0.2s);
}
.post-card:hover {
  box-shadow: var(--shadow-hover, 0 4px 12px rgba(0,0,0,0.05));
}
.post-event {
  border-left: 3px solid var(--accent-warn, #FF9800);
  background: #FFFDF5;
}
.post-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  color: #FFF;
  font-size: 14px;
  font-weight: 700;
  font-family: var(--font-mono);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  text-transform: uppercase;
}
.post-main {
  flex: 1;
  min-width: 0;
}
.post-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}
.post-author {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary, #000);
  cursor: pointer;
}
.post-author:hover {
  text-decoration: underline;
}
.post-tier {
  font-family: var(--font-mono);
  font-size: 9px;
  font-weight: 700;
  padding: 1px 4px;
  background: var(--text-primary, #000);
  color: #FFF;
  border-radius: 2px;
}
.post-action-badge {
  font-size: 9px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 2px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  font-family: var(--font-mono);
}
.badge-post    { background: #F0F0F0; color: #333; }
.badge-comment { background: #F0F0F0; color: #666; }
.badge-repost  { background: #F0F0F0; color: #666; }
.badge-event   { background: #FFF3E0; color: #E65100; }
.badge-idle    { background: #FAFAFA; color: #999; border: 1px dashed #DDD; opacity: 0.6; }
.post-round {
  font-size: 10px;
  font-family: var(--font-mono);
  color: var(--text-muted, #999);
  margin-left: auto;
}
.post-content {
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-primary, #000);
  margin: 0 0 8px;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
}
.post-quote {
  background: #F9F9F9;
  border: 1px solid #EEE;
  padding: 8px 12px;
  border-radius: 2px;
  font-size: 12px;
  color: #555;
  margin-bottom: 8px;
  line-height: 1.5;
}
.post-footer {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 10px;
  font-family: var(--font-mono);
  color: var(--text-muted, #999);
}
.post-spacer { flex: 1; }
.sentiment-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  margin-right: 3px;
  vertical-align: middle;
}
.dot-positive { background: var(--accent-success, #10B981); }
.dot-negative { background: var(--accent-danger, #DC2626); }
.dot-neutral  { background: var(--text-muted, #999); }
.post-engagement {
  color: var(--text-muted);
}
.post-react-btn {
  font-size: 10px;
  font-family: var(--font-mono);
  color: var(--text-muted, #999);
  background: none;
  border: none;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 2px;
  transition: background var(--duration-fast, 0.15s), color var(--duration-fast, 0.15s);
}
.post-react-btn:hover {
  background: #F0F0F0;
  color: var(--text-primary, #000);
}
</style>
