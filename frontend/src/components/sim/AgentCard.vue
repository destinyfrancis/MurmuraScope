<script setup>
const props = defineProps({
  agent: { type: Object, required: true },
  factionColour: { type: String, default: '#999' },
})

function avatarInitial(name) {
  return (name || '?')[0].toUpperCase()
}

function stanceLabel(stance) {
  if (stance == null) return { text: '未知', cls: 'stance-neutral' }
  if (stance > 0.6) return { text: '建制派', cls: 'stance-supportive' }
  if (stance < 0.4) return { text: '民主派', cls: 'stance-opposing' }
  return { text: '中立', cls: 'stance-neutral' }
}

function tierLabel(tier) {
  return tier === 1 ? 'Tier 1' : 'Tier 2'
}

function personalityParams(agent) {
  const params = []
  if (agent.openness != null) params.push({ label: '開放性', value: agent.openness })
  if (agent.conscientiousness != null) params.push({ label: '盡責性', value: agent.conscientiousness })
  if (agent.extraversion != null) params.push({ label: '外向性', value: agent.extraversion })
  if (agent.agreeableness != null) params.push({ label: '親和性', value: agent.agreeableness })
  if (agent.neuroticism != null) params.push({ label: '神經質', value: agent.neuroticism })
  if (agent.risk_appetite != null) params.push({ label: '風險', value: agent.risk_appetite })
  return params.slice(0, 6)
}
</script>

<template>
  <div class="agent-card">
    <div class="agent-identity">
      <div class="agent-avatar" :style="{ background: factionColour }">
        {{ avatarInitial(agent.name || agent.oasis_username) }}
      </div>
      <div class="agent-info">
        <div class="agent-name-row">
          <span class="agent-name">{{ agent.name || agent.oasis_username || `Agent #${agent.id}` }}</span>
          <span class="agent-tier" :class="{ 'tier-1': agent.tier === 1 }">{{ tierLabel(agent.tier) }}</span>
        </div>
        <div class="agent-meta-row">
          <span v-if="agent.agent_type || agent.role" class="agent-type-badge">
            {{ agent.agent_type || agent.role }}
          </span>
          <span class="agent-stance" :class="stanceLabel(agent.political_stance).cls">
            {{ stanceLabel(agent.political_stance).text }}
          </span>
          <span v-if="agent.district" class="agent-district">{{ agent.district }}</span>
        </div>
      </div>
    </div>
    <div v-if="personalityParams(agent).length" class="param-grid">
      <div v-for="p in personalityParams(agent)" :key="p.label" class="param-item">
        <span class="param-label">{{ p.label }}</span>
        <div class="param-bar-track">
          <div class="param-bar-fill" :style="{ width: (p.value * 100) + '%' }" />
        </div>
        <span class="param-value">{{ (p.value * 100).toFixed(0) }}</span>
      </div>
    </div>
    <div class="agent-id-row">
      <span class="agent-id">{{ (agent.id || '').toString().slice(0, 12) }}</span>
    </div>
  </div>
</template>

<style scoped>
.agent-card {
  background: #F9F9F9;
  border: 1px solid var(--border, #EAEAEA);
  border-radius: var(--radius-md, 4px);
  padding: 14px;
  transition: border-color var(--duration-standard, 0.2s), background var(--duration-standard, 0.2s);
}
.agent-card:hover {
  border-color: var(--border-hover, #999);
  background: var(--bg-card, #FFF);
}
.agent-identity {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
}
.agent-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  color: #FFF;
  font-size: 16px;
  font-weight: 700;
  font-family: var(--font-mono);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  text-transform: uppercase;
}
.agent-info { flex: 1; min-width: 0; }
.agent-name-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}
.agent-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary, #000);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.agent-tier {
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 2px;
  background: #F0F0F0;
  color: #666;
}
.agent-tier.tier-1 {
  background: var(--text-primary, #000);
  color: #FFF;
}
.agent-meta-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.agent-type-badge {
  font-size: 10px;
  font-family: var(--font-mono);
  color: #64748B;
  background: #F1F5F9;
  padding: 2px 8px;
  border-radius: 2px;
}
.agent-stance {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 2px;
}
.stance-supportive { background: #DCFCE7; color: #16A34A; }
.stance-opposing   { background: #FEE2E2; color: #DC2626; }
.stance-neutral    { background: #F1F5F9; color: #64748B; }
.agent-district {
  font-size: 10px;
  color: var(--text-muted, #999);
}
.param-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-bottom: 10px;
}
.param-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.param-label {
  font-size: 10px;
  color: var(--text-quaternary, #9CA3AF);
}
.param-bar-track {
  height: 4px;
  background: #E2E8F0;
  border-radius: 2px;
  max-width: 40px;
}
.param-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #6366F1, #A855F7);
  border-radius: 2px;
  transition: width var(--duration-medium, 0.3s);
}
.param-value {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
  color: #475569;
}
.agent-id-row {
  border-top: 1px solid var(--border, #EAEAEA);
  padding-top: 8px;
}
.agent-id {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-quaternary, #9CA3AF);
}
</style>
