<script setup>
import { ref, defineAsyncComponent } from 'vue'
import { lessons } from '../composables/useLessonData.js'

const activeLesson = ref(0)

const lessonComponents = [
  defineAsyncComponent(() => import('../components/lessons/LessonOverview.vue')),
  defineAsyncComponent(() => import('../components/lessons/LessonBoids.vue')),
  defineAsyncComponent(() => import('../components/lessons/LessonKG.vue')),
  defineAsyncComponent(() => import('../components/lessons/LessonNER.vue')),
  defineAsyncComponent(() => import('../components/lessons/LessonShocks.vue')),
  defineAsyncComponent(() => import('../components/lessons/LessonPercentiles.vue')),
  defineAsyncComponent(() => import('../components/lessons/LessonUncertainty.vue')),
  defineAsyncComponent(() => import('../components/lessons/LessonChallenges.vue')),
  defineAsyncComponent(() => import('../components/lessons/LessonMistakes.vue')),
  defineAsyncComponent(() => import('../components/lessons/LessonDataSources.vue')),
]
</script>

<template>
  <div class="learn-page">
    <h1 class="learn-title">教學</h1>
    <p class="learn-subtitle">了解 HKSimEngine 背後嘅原理</p>

    <!-- Lesson tabs -->
    <div class="lesson-tabs">
      <button
        v-for="lesson in lessons"
        :key="lesson.id"
        class="lesson-tab"
        :class="{ active: activeLesson === lesson.id }"
        @click="activeLesson = lesson.id"
      >
        <span class="tab-icon">{{ lesson.icon }}</span>
        {{ lesson.title }}
      </button>
    </div>

    <!-- Active lesson content -->
    <KeepAlive>
      <component :is="lessonComponents[activeLesson]" :key="activeLesson" />
    </KeepAlive>
  </div>
</template>

<style scoped>
.learn-page {
  max-width: 900px;
  margin: 0 auto;
  padding: 32px 24px;
}

.learn-title {
  font-size: 24px;
  font-weight: 700;
}

.learn-subtitle {
  color: var(--text-muted);
  margin-top: 4px;
  margin-bottom: 24px;
}

.lesson-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 24px;
  border-bottom: 1px solid var(--border-color);
  padding-bottom: 0;
  flex-wrap: wrap;
}

.lesson-tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 16px;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  font-size: 14px;
  color: var(--text-muted);
  cursor: pointer;
  transition: var(--transition);
}

.lesson-tab.active {
  color: var(--accent-blue);
  border-bottom-color: var(--accent-blue);
}

.lesson-tab:hover {
  color: var(--text-primary);
}

.tab-icon {
  font-size: 18px;
}
</style>
