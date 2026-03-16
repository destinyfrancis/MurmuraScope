<script setup>
import { computed } from 'vue'

const props = defineProps({
  agentProfile: { type: Object, default: null },
})

const bigFiveTraits = computed(() => {
  if (!props.agentProfile) return []
  return [
    { label: '開放性', value: props.agentProfile.openness },
    { label: '盡責性', value: props.agentProfile.conscientiousness },
    { label: '外向性', value: props.agentProfile.extraversion },
    { label: '親和性', value: props.agentProfile.agreeableness },
    { label: '神經質', value: props.agentProfile.neuroticism },
  ]
})
</script>

<template>
  <div v-if="agentProfile" class="tab-content">
    <div class="profile-grid">
      <div class="profile-row">
        <span class="profile-key">年齡</span>
        <span class="profile-val">{{ agentProfile.age }}歲</span>
      </div>
      <div class="profile-row">
        <span class="profile-key">性別</span>
        <span class="profile-val">{{ agentProfile.sex === 'M' ? '男' : '女' }}</span>
      </div>
      <div class="profile-row">
        <span class="profile-key">地區</span>
        <span class="profile-val">{{ agentProfile.district }}</span>
      </div>
      <div class="profile-row">
        <span class="profile-key">職業</span>
        <span class="profile-val">{{ agentProfile.occupation }}</span>
      </div>
      <div class="profile-row">
        <span class="profile-key">學歷</span>
        <span class="profile-val">{{ agentProfile.education_level }}</span>
      </div>
      <div class="profile-row">
        <span class="profile-key">住屋</span>
        <span class="profile-val">{{ agentProfile.housing_type }}</span>
      </div>
      <div class="profile-row">
        <span class="profile-key">收入</span>
        <span class="profile-val">{{ agentProfile.income_bracket }}</span>
      </div>
    </div>

    <div class="big-five">
      <div class="section-label">五大人格</div>
      <div v-for="trait in bigFiveTraits" :key="trait.label" class="trait-row">
        <span class="trait-label">{{ trait.label }}</span>
        <div class="trait-bar-bg">
          <div
            class="trait-bar-fill"
            :style="{ width: Math.round((trait.value || 0) * 100) + '%' }"
          />
        </div>
        <span class="trait-value">{{ Math.round((trait.value || 0) * 100) }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tab-content {
  overflow-y: auto;
  flex: 1;
  padding: 12px 14px;
}

.profile-grid { margin-bottom: 16px; }

.profile-row {
  display: flex;
  justify-content: space-between;
  padding: 6px 0;
  border-bottom: 1px solid var(--border-color);
  font-size: 13px;
}

.profile-key { color: var(--text-muted); }
.profile-val { color: var(--text-primary); font-weight: 500; }

.big-five { margin-top: 8px; }

.section-label {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 10px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.trait-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 7px;
  font-size: 12px;
}

.trait-label {
  width: 48px;
  color: var(--text-secondary);
}

.trait-bar-bg {
  flex: 1;
  height: 6px;
  background: var(--bg-primary);
  border-radius: 3px;
  overflow: hidden;
}

.trait-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--accent-blue), var(--accent-cyan));
  border-radius: 3px;
  transition: width 0.4s ease;
}

.trait-value {
  width: 28px;
  text-align: right;
  color: var(--text-muted);
}
</style>
