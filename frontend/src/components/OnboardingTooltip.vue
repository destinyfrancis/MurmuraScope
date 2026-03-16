<script setup>
const props = defineProps({
  title: { type: String, required: true },
  description: { type: String, required: true },
  step: { type: Number, default: 0 },
  totalSteps: { type: Number, default: 3 },
  position: { type: String, default: 'bottom' },
})

const emit = defineEmits(['next', 'dismiss'])
</script>

<template>
  <Teleport to="body">
    <div class="onboarding-backdrop" @click="emit('dismiss')">
      <div class="onboarding-tooltip" :class="position" @click.stop>
        <div class="tooltip-content">
          <h4 class="tooltip-title">{{ title }}</h4>
          <p class="tooltip-desc">{{ description }}</p>
        </div>
        <div class="tooltip-footer">
          <span class="tooltip-step">{{ step + 1 }} / {{ totalSteps }}</span>
          <div class="tooltip-actions">
            <button class="btn-skip" @click="emit('dismiss')">跳過</button>
            <button class="btn-next" @click="emit('next')">
              {{ step === totalSteps - 1 ? '完成' : '下一步' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.onboarding-backdrop {
  position: fixed;
  inset: 0;
  z-index: 9999;
  background: rgba(0, 0, 0, 0.3);
  display: flex;
  align-items: center;
  justify-content: center;
}

.onboarding-tooltip {
  background: var(--bg-card, #fff);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg, 12px);
  box-shadow: var(--shadow-lg);
  padding: 20px;
  max-width: 360px;
  width: 90%;
}

.tooltip-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 6px;
}

.tooltip-desc {
  font-size: 14px;
  color: var(--text-secondary);
  line-height: 1.6;
}

.tooltip-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 16px;
}

.tooltip-step {
  font-size: 12px;
  color: var(--text-muted);
}

.tooltip-actions {
  display: flex;
  gap: 8px;
}

.btn-skip {
  padding: 6px 12px;
  background: none;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  font-size: 13px;
  color: var(--text-muted);
  cursor: pointer;
}

.btn-next {
  padding: 6px 16px;
  background: var(--accent-blue);
  color: #0d1117;
  border: none;
  border-radius: var(--radius-md);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.btn-next:hover {
  background: #1d4ed8;
}
</style>
