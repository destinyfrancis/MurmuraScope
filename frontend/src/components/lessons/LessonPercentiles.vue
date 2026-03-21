<script setup>
import { ref } from 'vue'
import { percentileBands } from '../../composables/useLessonData.js'

const scenarioSlider = ref(50)
const l5Answer1 = ref(null)
const l5Answer2 = ref(null)
const l5Feedback1 = ref(null)
const l5Feedback2 = ref(null)

function checkL5Q1(ans) {
  l5Answer1.value = ans
  l5Feedback1.value = ans === 'p50' ? 'correct' : 'wrong'
}
function checkL5Q2(ans) {
  l5Answer2.value = ans
  l5Feedback2.value = ans === 'wide' ? 'correct' : 'wrong'
}
</script>

<template>
  <div class="lesson-content">
    <div class="lesson-text">
      <p>MurmuraScope 唔只輸出一條預測線，而係整個概率分佈。拖動滑桿調整情景強度：</p>
    </div>
    <div class="percentile-chart glass-panel">
      <div class="chart-label">樓價信心指數預測</div>
      <div class="chart-area">
        <div class="band-container">
          <div
            v-for="band in percentileBands"
            :key="band.label"
            class="pct-band"
            :style="{
              background: band.color,
              height: (band.height + scenarioSlider * 0.3) + 'px',
              borderTop: band.height === 3 ? `3px solid ${band.color}` : 'none',
            }"
          >
            <span class="band-label">{{ band.label }}</span>
          </div>
        </div>
      </div>
      <div class="slider-row">
        <span>溫和衝擊</span>
        <input type="range" min="0" max="100" v-model="scenarioSlider" class="scenario-slider" />
        <span>極端衝擊</span>
      </div>
      <div class="scenario-value">情景強度：{{ scenarioSlider }}%</div>
    </div>
    <div class="lesson-quiz">
      <div class="quiz-q">問題 1：p50 代表咩？</div>
      <div class="quiz-options">
        <button
          v-for="opt in [{ v: 'p50', label: '中位數預測' }, { v: 'avg', label: '平均值' }, { v: 'best', label: '最佳情景' }]"
          :key="opt.v"
          class="quiz-btn"
          :class="{ correct: l5Answer1 === opt.v && l5Feedback1 === 'correct', wrong: l5Answer1 === opt.v && l5Feedback1 === 'wrong' }"
          @click="checkL5Q1(opt.v)"
        >{{ opt.label }}</button>
      </div>
      <div v-if="l5Feedback1" class="quiz-feedback" :class="l5Feedback1">
        {{ l5Feedback1 === 'correct' ? '正確！p50 即中位數，一半模擬結果高於此值，一半低於。' : '錯誤，p50 係中位數（第50百分位數），唔係平均值。' }}
      </div>
      <div class="quiz-q" style="margin-top: 16px;">問題 2：p10-p90 區間越寬代表咩？</div>
      <div class="quiz-options">
        <button
          v-for="opt in [{ v: 'wide', label: '不確定性更高' }, { v: 'certain', label: '預測更準確' }, { v: 'same', label: '結果相同' }]"
          :key="opt.v"
          class="quiz-btn"
          :class="{ correct: l5Answer2 === opt.v && l5Feedback2 === 'correct', wrong: l5Answer2 === opt.v && l5Feedback2 === 'wrong' }"
          @click="checkL5Q2(opt.v)"
        >{{ opt.label }}</button>
      </div>
      <div v-if="l5Feedback2" class="quiz-feedback" :class="l5Feedback2">
        {{ l5Feedback2 === 'correct' ? '正確！更寬嘅區間反映更高嘅預測不確定性。' : '錯誤，更寬嘅區間意味不確定性更高，唔係更準確。' }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.lesson-content {
  animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

.lesson-text {
  margin: 16px 0;
  line-height: 1.8;
  color: var(--text-secondary);
  font-size: 15px;
}

.percentile-chart {
  padding: 20px;
  margin: 16px 0;
}

.chart-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 12px;
}

.chart-area {
  height: 160px;
  display: flex;
  align-items: flex-end;
  margin-bottom: 16px;
}

.band-container {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  justify-content: flex-end;
  gap: 2px;
}

.pct-band {
  width: 100%;
  border-radius: 3px;
  position: relative;
  transition: height 0.3s;
  display: flex;
  align-items: center;
  padding-left: 8px;
}

.band-label {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.7);
}

.slider-row {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 8px;
}

.scenario-slider {
  flex: 1;
  accent-color: #4ecca3;
}

.scenario-value {
  font-size: 12px;
  color: var(--text-muted);
}

.lesson-quiz {
  margin-top: 20px;
}

.quiz-q {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 10px;
}

.quiz-options {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.quiz-btn {
  padding: 6px 14px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  font-size: 13px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: var(--transition);
}

.quiz-btn:hover {
  border-color: var(--accent-blue);
}

.quiz-btn.correct {
  background: rgba(5, 150, 105, 0.1);
  border-color: #059669;
  color: #059669;
}

.quiz-btn.wrong {
  background: rgba(220, 38, 38, 0.08);
  border-color: #DC2626;
  color: #DC2626;
}

.quiz-feedback {
  margin-top: 8px;
  font-size: 13px;
  padding: 8px 12px;
  border-radius: var(--radius-sm);
}

.quiz-feedback.correct {
  background: rgba(5, 150, 105, 0.1);
  color: #059669;
}

.quiz-feedback.wrong {
  background: rgba(220, 38, 38, 0.08);
  color: #DC2626;
}
</style>
