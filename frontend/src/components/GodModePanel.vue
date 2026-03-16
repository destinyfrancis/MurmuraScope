<script setup>
import { ref } from 'vue'

const emit = defineEmits(['inject-shock'])

const open = ref(false)

const shockCards = [
  {
    id: 'rate_hike',
    label: '加息 2 厘',
    icon: '\u{1F4C8}',
    type: 'interest_rate_hike',
    description: '金管局宣布跟隨美聯儲加息2厘',
    post_content: '【突發】金管局宣布即時加息2厘，供樓人士月供即時增加...',
  },
  {
    id: 'pandemic',
    label: '爆發新疫情',
    icon: '\u{1F9A0}',
    type: 'pandemic',
    description: '世衛宣布新型傳染病全球大流行',
    post_content: '【突發】世衛確認新型傳染病已構成全球大流行，各國啟動防疫措施...',
  },
  {
    id: 'celeb_arrest',
    label: '某名人被捕',
    icon: '\u2696\uFE0F',
    type: 'social_event',
    description: '知名公眾人物因涉嫌違法被拘捕',
    post_content: '【突發】知名人士今日被捕，社會各界反應強烈...',
  },
]

function onDragStart(event, card) {
  event.dataTransfer.setData('application/json', JSON.stringify(card))
  event.dataTransfer.effectAllowed = 'copy'
}

function handleClick(card) {
  emit('inject-shock', card)
}
</script>

<template>
  <div class="god-mode">
    <button class="god-toggle" @click="open = !open">
      {{ open ? '收起' : '神之手 Intervene' }}
    </button>

    <Transition name="slide">
      <div v-if="open" class="god-panel">
        <div class="panel-title">拖曳衝擊卡到圖譜區域</div>
        <div class="card-list">
          <div
            v-for="card in shockCards"
            :key="card.id"
            class="shock-card"
            draggable="true"
            @dragstart="onDragStart($event, card)"
            @click="handleClick(card)"
          >
            <span class="card-icon">{{ card.icon }}</span>
            <div class="card-info">
              <span class="card-label">{{ card.label }}</span>
              <span class="card-desc">{{ card.description }}</span>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.god-mode {
  position: fixed;
  bottom: 20px;
  right: 20px;
  z-index: 50;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
}

.god-toggle {
  padding: 8px 18px;
  background: var(--bg-card);
  color: var(--accent-blue);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s, border-color 0.2s;
  white-space: nowrap;
  box-shadow: var(--shadow-card);
}

.god-toggle:hover {
  background: var(--bg-secondary);
  border-color: var(--accent-blue);
}

.god-panel {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  box-shadow: var(--shadow-md);
  padding: 14px;
  width: 280px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.panel-title {
  font-size: 11px;
  color: var(--text-muted);
  text-align: center;
  letter-spacing: 0.03em;
}

.card-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.shock-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  cursor: grab;
  transition: border-color 0.2s, background 0.2s, box-shadow 0.2s, transform 0.2s;
  user-select: none;
}

.shock-card:hover {
  border-color: var(--accent-orange, #fb923c);
  box-shadow: var(--shadow-card);
  background: var(--accent-blue-light);
  transform: translateY(-2px);
}

.shock-card:active {
  cursor: grabbing;
  opacity: 0.7;
}

.card-icon {
  font-size: 22px;
  flex-shrink: 0;
}

.card-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.card-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.card-desc {
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Slide transition */
.slide-enter-active,
.slide-leave-active {
  transition: all 0.25s ease;
}

.slide-enter-from,
.slide-leave-to {
  opacity: 0;
  transform: translateY(12px);
}
</style>
