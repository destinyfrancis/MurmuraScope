<script setup>
import { ref, computed, watch } from 'vue'
import SocialFeed from './SocialFeed.vue'
import DissonanceView from './DissonanceView.vue'
import FeedView from './FeedView.vue'
import FactionTab from './sim/FactionTab.vue'
import TippingPointTab from './sim/TippingPointTab.vue'
import MultiRunTab from './sim/MultiRunTab.vue'
import WorldEventCard from './sim/WorldEventCard.vue'
import FactionColumns from './FactionColumns.vue'
import InteractionNetwork from './InteractionNetwork.vue'

const props = defineProps({
  activeTab:        { type: String,  required: true },
  posts:            { type: Array,   default: () => [] },
  agents:           { type: Array,   default: () => [] },
  factionSnapshots: { type: Array,   default: () => [] },
  tippingPoints:    { type: Array,   default: () => [] },
  sessionId:        { type: String,  default: '' },
  simCompleted:     { type: Boolean, default: false },
  worldEvents:      { type: Array,   default: () => [] },
  factionColours:   { type: Object,  default: () => ({}) },
})

const emit = defineEmits(['update:activeTab', 'select-agent', 'post-interact'])

function setTab(key) {
  emit('update:activeTab', key)
}

const activeView = ref('timeline') // 'timeline' | 'factions' | 'network'

// Track UI-only interact counts (repost/reply) keyed by post._key + type
// Use this ref for display — do NOT mutate post objects (immutability rule)
const interactCounts = ref({})

function handleInteract(post, type) {
  const key = `${post._key}-${type}`
  // Immutable update: spread existing counts into new object
  interactCounts.value = { ...interactCounts.value, [key]: (interactCounts.value[key] || 0) + 1 }
  emit('post-interact', { postKey: post._key, type })
}

function getInteractCount(post, type) {
  return interactCounts.value[`${post._key}-${type}`] || 0
}

const mergedFeedItems = computed(() => {
  const posts = props.posts.map(p => ({ ...p, _type: 'post', _key: `p-${p.id || Math.random()}`, _round: p.round || 0 }))
  const events = props.worldEvents.map(e => ({ ...e, _type: 'world_event', _key: `we-${e.id}`, _round: e.round_number || 0 }))
  return [...posts, ...events].sort((a, b) => a._round - b._round)
})

// Build username → colour map for InteractionNetwork
// factionColours is keyed by agent_id (int), but D3 graph uses oasis_username
const usernameColourMap = computed(() => {
  const map = {}
  for (const agent of props.agents) {
    const colour = props.factionColours?.[agent.id]
    if (agent.oasis_username && colour) {
      map[agent.oasis_username] = colour
    }
  }
  return map
})

watch(() => props.sessionId, () => {
  interactCounts.value = {}
  activeView.value = 'timeline'
})
</script>

<template>
  <div class="tab-bar">
    <button class="tab-btn" :class="{ active: activeTab === 'feed' }" @click="setTab('feed')">動態廣場</button>
    <button class="tab-btn" :class="{ active: activeTab === 'agents' }" @click="setTab('agents')">Agents</button>
    <button class="tab-btn" :class="{ active: activeTab === 'factions' }" @click="setTab('factions')">派系</button>
    <button class="tab-btn" :class="{ active: activeTab === 'tipping' }" @click="setTab('tipping')">臨界點</button>
    <button class="tab-btn" :class="{ active: activeTab === 'predict' }" @click="setTab('predict')">預測</button>
  </div>

  <div class="feed-area">
    <!-- Tab 1: Live feed -->
    <div v-if="activeTab === 'feed'" class="tab-content-feed">
      <!-- View switcher -->
      <div class="view-switcher">
        <button class="view-btn" :class="{ active: activeView === 'timeline' }" @click="activeView = 'timeline'">時間流</button>
        <button class="view-btn" :class="{ active: activeView === 'factions' }" @click="activeView = 'factions'">陣營分欄</button>
        <button class="view-btn" :class="{ active: activeView === 'network' }" @click="activeView = 'network'">互動網絡</button>
      </div>

      <!-- View 1: Timeline (existing + interact buttons) -->
      <div v-if="activeView === 'timeline'" class="view-timeline">
        <template v-for="item in mergedFeedItems" :key="item._key">
          <WorldEventCard v-if="item._type === 'world_event'" :event="item" />
          <div v-else class="feed-post-wrapper" :style="{ borderLeftColor: factionColours?.[item.agent_id] ?? '#9CA3AF' }">
            <FeedView
              :post="item"
              :faction-colour="factionColours?.[item.agent_id] ?? '#9CA3AF'"
              @select-agent="emit('select-agent', $event)"
            />
            <div class="post-actions">
              <button class="post-action-btn" @click="handleInteract(item, 'repost')">↩ 轉發 {{ getInteractCount(item, 'repost') }}</button>
              <button class="post-action-btn" @click="handleInteract(item, 'reply')">💬 評論 {{ getInteractCount(item, 'reply') }}</button>
            </div>
          </div>
        </template>
      </div>

      <!-- View 2: Faction columns -->
      <div v-else-if="activeView === 'factions'" class="view-factions">
        <FactionColumns
          :session-id="sessionId"
          :posts="posts"
          :faction-colours="factionColours"
        />
      </div>

      <!-- View 3: Interaction network -->
      <div v-else-if="activeView === 'network'" class="view-network">
        <InteractionNetwork
          :session-id="sessionId"
          :faction-colours="usernameColourMap"
        />
      </div>
    </div>

    <!-- Tab 2: Agents -->
    <div v-else-if="activeTab === 'agents'" class="agent-tab-content">
      <div v-if="agents.length === 0" class="topic-empty">載入代理人...</div>
      <div
        v-for="agent in agents"
        :key="agent.id"
        class="agent-tab-card"
        @click="emit('select-agent', agent)"
      >
        <div class="agent-tab-name">{{ agent.oasis_username || `代理人 #${agent.id}` }}</div>
        <div class="agent-tab-meta">
          <span v-if="agent.district">{{ agent.district }}</span>
          <span v-if="agent.occupation">{{ agent.occupation }}</span>
        </div>
      </div>
      <!-- Dissonance section within agents tab -->
      <DissonanceView
        v-if="sessionId && agents.length > 0"
        :session-id="sessionId"
        style="margin-top: 12px;"
      />
    </div>

    <!-- Tab 3: Factions -->
    <FactionTab
      v-else-if="activeTab === 'factions'"
      :snapshots="factionSnapshots"
    />

    <!-- Tab 4: Tipping Points -->
    <TippingPointTab
      v-else-if="activeTab === 'tipping'"
      :tipping-points="tippingPoints"
    />

    <!-- Tab 5: Multi-Run -->
    <MultiRunTab
      v-else-if="activeTab === 'predict'"
      :session-id="sessionId"
      :sim-completed="simCompleted"
    />
  </div>
</template>

<style scoped>
.tab-bar {
  display: flex;
  gap: 0;
  background: var(--bg-card);
  border: 1px solid var(--border);
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
  border-right: 1px solid var(--border);
}

.tab-btn.active {
  background: rgba(var(--accent-rgb, 74, 158, 255), 0.08);
  color: var(--accent);
  border-bottom-color: var(--accent);
}

.feed-area {
  flex: 1;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  overflow: hidden;
  min-height: 0;
}

/* FEED TAB styles */
.tab-content-feed {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.view-switcher {
  display: flex;
  gap: 4px;
  padding: 6px 8px;
  border-bottom: 1px solid var(--border, #1e293b);
  flex-shrink: 0;
}

.view-btn {
  padding: 3px 10px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
  background: transparent;
  color: #94a3b8;
  border: none;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}

.view-btn.active,
.view-btn:hover {
  background: var(--accent-primary, #6366f1);
  color: #fff;
}

.view-timeline {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  padding: 8px;
}

.view-factions,
.view-network {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  padding: 8px;
}

.feed-post-wrapper {
  border-left: 4px solid #9CA3AF;
  padding-left: 0;
}

.post-actions {
  display: flex;
  gap: 8px;
  padding: 3px 8px 6px;
}

.post-action-btn {
  font-size: 10px;
  color: #64748b;
  background: none;
  border: none;
  cursor: pointer;
  padding: 2px 4px;
  border-radius: 3px;
  transition: color 0.15s;
}
.post-action-btn:hover { color: #6366f1; }

/* AGENT TAB styles */
.agent-tab-content {
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

.agent-tab-card {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  transition: background 0.2s, border-color 0.2s;
}

.agent-tab-card:hover {
  background: var(--bg-app);
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
</style>
