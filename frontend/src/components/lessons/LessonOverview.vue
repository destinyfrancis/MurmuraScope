<script setup>
</script>

<template>
  <div class="lesson-content">
    <div class="comparison-grid">
      <div class="compare-card glass-panel">
        <h3>傳統民調</h3>
        <ul>
          <li>問 1,000 人佢哋嘅想法</li>
          <li>靜態快照 — 一次性</li>
          <li>忽略社交影響力</li>
          <li>無法模擬政策變化</li>
        </ul>
        <div class="compare-verdict bad">有限</div>
      </div>
      <div class="compare-card glass-panel">
        <h3>MurmuraScope</h3>
        <ul>
          <li>模擬 500 個 AI 代理人互動</li>
          <li>動態演化 — 30+ 輪模擬</li>
          <li>Echo Chamber + 信任網絡</li>
          <li>即時注入政策衝擊</li>
        </ul>
        <div class="compare-verdict good">湧現式預測</div>
      </div>
    </div>
    <div class="lesson-text">
      <p>MurmuraScope 唔係問人「你點諗」，而係用 AI 代理人模擬真實嘅社會互動過程。每個代理人有自己嘅性格、記憶、信任圈子，佢哋會互相影響，最終<strong>湧現</strong>出群體趨勢。</p>
      <p>我哋追蹤嘅指標包括：樓價信心、移民意向、消費模式、政治極化度等。</p>
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

.lesson-text strong {
  color: var(--text-primary);
}

.comparison-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 20px;
}

.compare-card {
  padding: 20px;
}

.compare-card h3 {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 12px;
}

.compare-card ul {
  list-style: none;
  padding: 0;
}

.compare-card li {
  padding: 4px 0;
  font-size: 13px;
  color: var(--text-secondary);
}

.compare-card li::before {
  content: '• ';
  color: var(--text-muted);
}

.compare-verdict {
  margin-top: 12px;
  padding: 4px 10px;
  border-radius: var(--radius-pill);
  font-size: 12px;
  font-weight: 600;
  display: inline-block;
}

.compare-verdict.bad {
  background: var(--accent-orange-light);
  color: var(--accent-orange);
}

.compare-verdict.good {
  background: var(--accent-green-light);
  color: var(--accent-green);
}

@media (max-width: 640px) {
  .comparison-grid {
    grid-template-columns: 1fr;
  }
}
</style>
