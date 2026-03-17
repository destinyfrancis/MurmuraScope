<script setup>
import { computed } from 'vue'
import SocialFeed from './SocialFeed.vue'
import DissonanceView from './DissonanceView.vue'
import FeedView from './FeedView.vue'
import FactionTab from './sim/FactionTab.vue'
import TippingPointTab from './sim/TippingPointTab.vue'
import MultiRunTab from './sim/MultiRunTab.vue'
import WorldEventCard from './sim/WorldEventCard.vue'

const props = defineProps({
  activeTab:        { type: String,  required: true },
  posts:            { type: Array,   default: () => [] },
  agents:           { type: Array,   default: () => [] },
  factionSnapshots: { type: Array,   default: () => [] },
  tippingPoints:    { type: Array,   default: () => [] },
  sessionId:        { type: String,  default: '' },
  simCompleted:     { type: Boolean, default: false },
  worldEvents:      { type: Array,   default: () => [] },
})

const emit = defineEmits(['update:activeTab', 'select-agent'])

function setTab(key) {
  emit('update:activeTab', key)
}

const mergedFeedItems = computed(() => {
  const posts = props.posts.map(p => ({ ...p, _type: 'post', _key: `p-${p.id || Math.random()}`, _round: p.round || 0 }))
  const events = props.worldEvents.map(e => ({ ...e, _type: 'world_event', _key: `we-${e.id}`, _round: e.round_number || 0 }))
  return [...posts, ...events].sort((a, b) => a._round - b._round)
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
      <template v-for="item in mergedFeedItems" :key="item._key">
        <WorldEventCard v-if="item._type === 'world_event'" :event="item" />
        <FeedView v-else :post="item" @select-agent="emit('select-agent', $event)" />
      </template>
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
  background: rgba(var(--accent-rgb, 74, 158, 255), 0.08);
  color: var(--accent);
  border-bottom-color: var(--accent);
}

.feed-area {
  flex: 1;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  overflow: hidden;
  min-height: 0;
}

/* FEED TAB styles */
.tab-content-feed {
  height: 100%;
  overflow-y: auto;
  padding: 8px;
}

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
  border-bottom: 1px solid var(--border-color);
  cursor: pointer;
  transition: background 0.2s, border-color 0.2s;
}

.agent-tab-card:hover {
  background: var(--bg-secondary);
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
