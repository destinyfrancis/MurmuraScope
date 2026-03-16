<script setup>
defineProps({
  selectedAgent: { type: Object, default: null },
  agentMemories: { type: Array, default: () => [] },
  loadingMemories: { type: Boolean, default: false },
})
</script>

<template>
  <div v-if="selectedAgent" class="agent-profile">
    <div class="profile-heading">{{ selectedAgent.oasis_username || selectedAgent.username || `代理人 #${selectedAgent.id}` }}</div>
    <div class="profile-meta">
      <span class="meta-chip">{{ selectedAgent.age ? selectedAgent.age + ' 歲' : '?' }}</span>
      <span class="meta-chip">{{ selectedAgent.sex === 'M' ? '男' : selectedAgent.sex === 'F' ? '女' : '?' }}</span>
      <span class="meta-chip">{{ selectedAgent.district || '?' }}</span>
      <span class="meta-chip">{{ selectedAgent.occupation || '?' }}</span>
    </div>

    <!-- Big Five personality bars -->
    <div class="personality-section">
      <div class="profile-subheading">個性特質 (Big Five)</div>
      <div
        v-for="[traitKey, traitLabel] in [
          ['openness', '開放性'],
          ['conscientiousness', '盡責性'],
          ['extraversion', '外向性'],
          ['agreeableness', '親和性'],
          ['neuroticism', '神經質'],
        ]"
        :key="traitKey"
        class="trait-row"
      >
        <span class="trait-label">{{ traitLabel }}</span>
        <div class="trait-bar-bg">
          <div
            class="trait-bar-fill"
            :style="{ width: ((selectedAgent[traitKey] || 0) * 100) + '%' }"
          />
        </div>
        <span class="trait-val">{{ Math.round((selectedAgent[traitKey] || 0) * 100) }}</span>
      </div>
    </div>

    <!-- Memory summary -->
    <div v-if="agentMemories.length" class="memory-section">
      <div class="profile-subheading">近期記憶</div>
      <div v-if="loadingMemories" class="memory-loading">載入中...</div>
      <div
        v-for="mem in agentMemories"
        :key="mem.id"
        class="memory-item"
      >
        <span class="mem-score">{{ Math.round((mem.salience_score || 0) * 100) }}%</span>
        {{ mem.memory_text }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.agent-profile {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 16px;
}

.profile-heading {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 8px;
}

.profile-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 12px;
}

.meta-chip {
  font-size: 11px;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  padding: 2px 7px;
  border-radius: 10px;
  color: var(--text-secondary);
}

.profile-subheading {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 8px;
}

.personality-section {
  margin-bottom: 12px;
}

.trait-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 5px;
}

.trait-label {
  width: 50px;
  font-size: 11px;
  color: var(--text-muted);
  flex-shrink: 0;
}

.trait-bar-bg {
  flex: 1;
  height: 5px;
  background: var(--bg-input);
  border-radius: 3px;
  overflow: hidden;
}

.trait-bar-fill {
  height: 100%;
  background: var(--accent-blue);
  border-radius: 3px;
  transition: width 0.4s ease;
}

.trait-val {
  width: 26px;
  font-size: 11px;
  color: var(--text-muted);
  text-align: right;
}

.memory-section {
  margin-top: 4px;
}

.memory-loading {
  font-size: 12px;
  color: var(--text-muted);
}

.memory-item {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
  padding: 5px 0;
  border-bottom: 1px solid var(--border-color);
  display: flex;
  gap: 6px;
  align-items: flex-start;
}

.memory-item:last-child {
  border-bottom: none;
}

.mem-score {
  flex-shrink: 0;
  font-size: 10px;
  background: var(--accent-blue-light);
  color: var(--accent-blue);
  padding: 1px 5px;
  border-radius: 4px;
  font-weight: 600;
}
</style>
