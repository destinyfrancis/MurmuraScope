<script setup>
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getSession } from '../api/simulation.js'

const props = defineProps({
  sessionId: { type: String, required: true },
})

const router = useRouter()

onMounted(async () => {
  try {
    const res = await getSession(props.sessionId)
    const scenarioType = res.data?.data?.scenario_type || res.data?.scenario_type || 'hk_demographic'
    router.replace({
      name: 'Process',
      params: { scenarioType },
      query: { step: '3', session_id: props.sessionId },
    })
  } catch (err) {
    console.error('Failed to load session:', err)
    router.replace('/')
  }
})
</script>

<template>
  <div class="loading-page">
    <div class="spinner" />
    <p>載入模擬環節中...</p>
  </div>
</template>

<style scoped>
.loading-page {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 60vh;
  gap: 16px;
  color: var(--text-secondary);
}

.spinner {
  width: 40px;
  height: 40px;
  border: 3px solid var(--border-color);
  border-top-color: var(--accent-blue);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
