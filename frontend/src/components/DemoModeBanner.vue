<template>
  <div v-if="isDemoMode" class="demo-banner">
    <div class="content">
      <span class="icon">💡</span>
      <span class="text">您正處於 <strong>展示模式 (Demo Mode)</strong>。LLM 回應是由預置腳本模擬的。</span>
      <router-link to="/settings" class="action-link">切換至實戰模式 (Live Mode) ➔</router-link>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue';
import { useSettingsStore } from '@/stores/settings'; // Assuming existence based on L2 plan

const settingsStore = useSettingsStore();
const isDemoMode = computed(() => settingsStore.settings.DEMO_MODE);
</script>

<style scoped>
.demo-banner {
  background: linear-gradient(90deg, #3b82f6, #2563eb);
  color: white;
  padding: 8px 16px;
  text-align: center;
  font-size: 0.9rem;
  z-index: 1000;
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

.content {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
}

.icon {
  font-size: 1.1rem;
}

.action-link {
  color: white;
  text-decoration: underline;
  font-weight: 600;
  margin-left: 8px;
}

.action-link:hover {
  color: #dbeafe;
}
</style>
