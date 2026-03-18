<script setup>
defineProps({
  label: { type: String, required: true },
  color: { type: String, default: '#64748b' }, // hex background color
})
</script>

<template>
  <span class="agent-badge" :style="{ background: color }">{{ label }}</span>
</template>

<style scoped>
.agent-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 10px;
  font-weight: 600;
  color: #fff;
  white-space: nowrap;
}
</style>
