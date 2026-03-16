<script setup>
import { computed } from 'vue'

const props = defineProps({
  /** Object mapping district name → { positive, negative, neutral } counts */
  sentimentData: { type: Object, default: () => ({}) },
  /** Currently selected district (string or null) */
  selectedDistrict: { type: String, default: null },
  /** Cross-filter query string from memory search */
  filterQuery: { type: String, default: '' },
  /** Mapping district name → array of agent IDs */
  agentDistricts: { type: Object, default: () => ({}) },
  /** Array of agent IDs matching the current memory search */
  matchingAgentIds: { type: Array, default: () => [] },
})

const emit = defineEmits(['select-district'])

// 18 HK Districts with approximate SVG positions
const DISTRICTS = [
  // HK Island
  { id: 'central_western', name: '中西區', x: 180, y: 320, island: 'hk' },
  { id: 'eastern', name: '東區', x: 260, y: 300, island: 'hk' },
  { id: 'southern', name: '南區', x: 200, y: 370, island: 'hk' },
  { id: 'wanchai', name: '灣仔', x: 230, y: 320, island: 'hk' },
  // Kowloon
  { id: 'kowloon_city', name: '九龍城', x: 220, y: 260, island: 'kln' },
  { id: 'kwun_tong', name: '觀塘', x: 270, y: 255, island: 'kln' },
  { id: 'sham_shui_po', name: '深水埗', x: 185, y: 255, island: 'kln' },
  { id: 'wong_tai_sin', name: '黃大仙', x: 240, y: 240, island: 'kln' },
  { id: 'yau_tsim_mong', name: '油尖旺', x: 195, y: 275, island: 'kln' },
  // New Territories
  { id: 'islands', name: '離島', x: 100, y: 380, island: 'nt' },
  { id: 'kwai_tsing', name: '葵青', x: 155, y: 230, island: 'nt' },
  { id: 'north', name: '北區', x: 240, y: 140, island: 'nt' },
  { id: 'sai_kung', name: '西貢', x: 320, y: 240, island: 'nt' },
  { id: 'sha_tin', name: '沙田', x: 270, y: 200, island: 'nt' },
  { id: 'tai_po', name: '大埔', x: 290, y: 170, island: 'nt' },
  { id: 'tsuen_wan', name: '荃灣', x: 145, y: 210, island: 'nt' },
  { id: 'tuen_mun', name: '屯門', x: 100, y: 210, island: 'nt' },
  { id: 'yuen_long', name: '元朗', x: 130, y: 170, island: 'nt' },
]

function getSentiment(districtName) {
  const data = props.sentimentData[districtName]
  if (!data) return null
  const total = (data.positive || 0) + (data.negative || 0) + (data.neutral || 0)
  if (total === 0) return null
  const score = ((data.positive || 0) - (data.negative || 0)) / total
  return score  // -1 to +1
}

const activeDistricts = computed(() => {
  if (!props.filterQuery) return null
  if (props.matchingAgentIds.length === 0) return new Set()  // All dimmed
  // Find which districts have agents matching the search
  const active = new Set()
  for (const [district, agentIds] of Object.entries(props.agentDistricts)) {
    if (agentIds.some(id => props.matchingAgentIds.includes(id))) {
      active.add(district)
    }
  }
  return active
})

function getColor(districtName) {
  if (activeDistricts.value && !activeDistricts.value.has(districtName)) {
    return 'rgba(200, 200, 210, 0.4)'
  }
  const score = getSentiment(districtName)
  if (score === null) return 'var(--bg-secondary, #F3F4F6)'
  if (score > 0.3) return 'rgba(76, 175, 125, 0.6)'
  if (score > 0) return 'rgba(76, 175, 125, 0.3)'
  if (score < -0.3) return 'rgba(224, 82, 82, 0.6)'
  if (score < 0) return 'rgba(224, 82, 82, 0.3)'
  return 'rgba(100, 120, 160, 0.4)'
}

function getOpacity(districtName) {
  if (activeDistricts.value && !activeDistricts.value.has(districtName)) return 0.3
  return 1.0
}

function getStroke(districtName) {
  return props.selectedDistrict === districtName
    ? 'var(--accent-blue)'
    : 'var(--border-emphasis)'
}

function getStrokeWidth(districtName) {
  return props.selectedDistrict === districtName ? 2.5 : 1
}

function selectDistrict(districtName) {
  emit('select-district', districtName === props.selectedDistrict ? null : districtName)
}

const districtStats = computed(() => {
  return DISTRICTS.map(d => {
    const data = props.sentimentData[d.name] || {}
    const total = (data.positive || 0) + (data.negative || 0) + (data.neutral || 0)
    return { ...d, total, data }
  })
})
</script>

<template>
  <div class="district-map">
    <div class="map-title">香港18區情緒地圖</div>
    <svg viewBox="60 100 320 320" class="map-svg" xmlns="http://www.w3.org/2000/svg">
      <!-- Background -->
      <rect x="60" y="100" width="320" height="320" fill="var(--bg-primary, #FAFBFC)" rx="8"/>

      <!-- District circles -->
      <g v-for="d in districtStats" :key="d.id">
        <circle
          :cx="d.x"
          :cy="d.y"
          :r="d.total > 0 ? Math.min(22, 14 + d.total * 0.05) : 14"
          :fill="getColor(d.name)"
          :stroke="getStroke(d.name)"
          :stroke-width="getStrokeWidth(d.name)"
          :opacity="getOpacity(d.name)"
          class="district-circle"
          @click="selectDistrict(d.name)"
        />
        <text
          :x="d.x"
          :y="d.y + 1"
          text-anchor="middle"
          dominant-baseline="middle"
          class="district-label"
          :class="{ selected: selectedDistrict === d.name }"
        >{{ d.name.length > 3 ? d.name.slice(0,3) : d.name }}</text>
      </g>

      <!-- Legend -->
      <g transform="translate(68, 400)">
        <circle cx="8" cy="8" r="6" fill="rgba(76,175,125,0.6)" />
        <text x="17" y="12" class="legend-text">正面</text>
        <circle cx="60" cy="8" r="6" fill="rgba(100,120,160,0.4)" />
        <text x="69" y="12" class="legend-text">中性</text>
        <circle cx="112" cy="8" r="6" fill="rgba(224,82,82,0.6)" />
        <text x="121" y="12" class="legend-text">負面</text>
      </g>
    </svg>

    <!-- Selected district info -->
    <div v-if="selectedDistrict && sentimentData[selectedDistrict]" class="district-info">
      <div class="info-name">{{ selectedDistrict }}</div>
      <div class="info-stats">
        <span class="stat-pos">正 {{ sentimentData[selectedDistrict].positive || 0 }}</span>
        <span class="stat-neu">中 {{ sentimentData[selectedDistrict].neutral || 0 }}</span>
        <span class="stat-neg">負 {{ sentimentData[selectedDistrict].negative || 0 }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.district-map {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 16px;
  box-shadow: var(--shadow-card);
}

.map-title {
  font-size: 13px;
  color: var(--text-muted);
  margin-bottom: 8px;
  text-align: center;
}

.map-svg {
  width: 100%;
  height: auto;
  display: block;
}

.district-circle {
  cursor: pointer;
  transition: opacity 0.2s, filter 0.2s;
}

.district-circle:hover {
  opacity: 0.8;
  filter: drop-shadow(0 0 6px currentColor);
}

.district-label {
  font-size: 9px;
  fill: var(--text-primary, #111827);
  pointer-events: none;
  font-weight: 500;
}

.district-label.selected {
  fill: var(--accent-blue);
  font-weight: 700;
}

.legend-text {
  font-size: 10px;
  fill: var(--text-muted, #9CA3AF);
}

.district-info {
  margin-top: 8px;
  padding: 10px 12px;
  background: var(--bg-primary);
  border-radius: var(--radius-md);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.info-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.info-stats {
  display: flex;
  gap: 12px;
  font-size: 13px;
}

.stat-pos { color: #4caf7d; }
.stat-neu { color: var(--text-muted); }
.stat-neg { color: #e05252; }
</style>
