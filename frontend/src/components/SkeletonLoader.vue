<script setup>
defineProps({
  type: { type: String, default: 'text' },
  width: { type: String, default: '100%' },
  height: { type: String, default: null },
  lines: { type: Number, default: 3 },
  circle: { type: Number, default: 0 },
})
</script>

<template>
  <div class="skeleton-container">
    <!-- Card skeleton -->
    <div v-if="type === 'card'" class="skel skel-card" :style="{ width, height: height || '120px' }" />

    <!-- Text lines skeleton -->
    <template v-else-if="type === 'text'">
      <div class="skel skel-title" :style="{ width: '60%' }" />
      <div
        v-for="i in lines"
        :key="i"
        class="skel skel-line"
        :style="{ width: i === lines ? '40%' : '100%' }"
      />
    </template>

    <!-- Circle + text skeleton (avatar row) -->
    <div v-else-if="type === 'avatar'" class="skel-avatar-row">
      <div class="skel skel-circle" :style="{ width: (circle || 40) + 'px', height: (circle || 40) + 'px' }" />
      <div class="skel-avatar-text">
        <div class="skel skel-line" style="width: 50%" />
        <div class="skel skel-line" style="width: 80%" />
      </div>
    </div>

    <!-- Chart skeleton -->
    <div v-else-if="type === 'chart'" class="skel skel-chart" :style="{ width, height: height || '200px' }" />

    <!-- Custom slot -->
    <slot v-else />
  </div>
</template>

<style scoped>
@keyframes shimmer {
  0% { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}

.skel {
  background: linear-gradient(90deg, #1a2332 25%, #2a3d52 50%, #1a2332 75%);
  background-size: 200% 100%;
  animation: shimmer 1.5s ease-in-out infinite;
  border-radius: var(--radius-sm, 4px);
}

.skel-title {
  height: 20px;
  margin-bottom: 12px;
}

.skel-line {
  height: 14px;
  margin-bottom: 8px;
}

.skel-line:last-child {
  margin-bottom: 0;
}

.skel-card {
  border-radius: var(--radius-md, 8px);
}

.skel-chart {
  border-radius: var(--radius-md, 8px);
}

.skel-circle {
  border-radius: 50%;
  flex-shrink: 0;
}

.skel-avatar-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.skel-avatar-text {
  flex: 1;
}
</style>
