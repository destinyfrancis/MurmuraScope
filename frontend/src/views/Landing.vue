<script setup>
import { useRouter } from 'vue-router'

const router = useRouter()

const scenarios = [
  {
    type: 'property',
    icon: '🏠',
    title: '樓市走勢預測',
    description: '模擬加息、撤辣、北部都會區等因素對香港樓價嘅影響',
  },
  {
    type: 'emigration',
    icon: '✈️',
    title: '移民潮預測',
    description: '分析政治、經濟、地緣因素如何影響香港人口流動',
  },
  {
    type: 'economic',
    icon: '📊',
    title: '消費信心預測',
    description: '追蹤零售、就業、通脹對市民消費行為嘅連鎖反應',
  },
]

const steps = [
  { num: 1, title: '建立知識圖譜', desc: '系統自動分析議題，建立因果關係網絡' },
  { num: 2, title: '配置模擬環境', desc: '設定代理人數量、地區分佈、經濟情境' },
  { num: 3, title: '運行社會模擬', desc: 'AI 代理人互動、做決策、形成群體趨勢' },
  { num: 4, title: '生成分析報告', desc: 'ReACT 推理引擎深度分析模擬結果' },
  { num: 5, title: '互動式探索', desc: '訪問代理人、注入衝擊、比較場景分支' },
]

function goScenario(type) {
  router.push(`/process/${type}`)
}

function goWorkspace() {
  router.push('/app')
}
</script>

<template>
  <div class="landing">
    <!-- Hero -->
    <section class="hero">
      <div class="hero-content">
        <div class="hero-text">
          <h1 class="hero-title">
            香港社會<span class="highlight">預測引擎</span>
          </h1>
          <p class="hero-subtitle">
            用 500 個 AI 代理人模擬真實社會互動，預測政策變化對香港嘅影響。
            唔係問人點諗 — 而係睇社會點演化。
          </p>
          <div class="hero-actions">
            <button class="btn-primary" @click="goScenario('property')">開始預測</button>
            <button class="btn-secondary" @click="goWorkspace">工作區</button>
          </div>
          <div class="hero-stats">
            <div class="stat">
              <span class="stat-value">500+</span>
              <span class="stat-label">AI 代理人</span>
            </div>
            <div class="stat">
              <span class="stat-value">18</span>
              <span class="stat-label">香港地區</span>
            </div>
            <div class="stat">
              <span class="stat-value">30+</span>
              <span class="stat-label">模擬輪次</span>
            </div>
          </div>
        </div>
        <div class="hero-visual">
          <div class="mini-graph">
            <svg viewBox="0 0 300 250" class="mini-graph-svg">
              <!-- Edges -->
              <line x1="150" y1="40" x2="60" y2="110" stroke="#2a3d52" stroke-width="1.5" />
              <line x1="150" y1="40" x2="240" y2="110" stroke="#2a3d52" stroke-width="1.5" />
              <line x1="60" y1="110" x2="100" y2="200" stroke="#2a3d52" stroke-width="1.5" />
              <line x1="240" y1="110" x2="200" y2="200" stroke="#2a3d52" stroke-width="1.5" />
              <line x1="100" y1="200" x2="200" y2="200" stroke="#2a3d52" stroke-width="1.5" />
              <line x1="60" y1="110" x2="240" y2="110" stroke="#2a3d52" stroke-width="1" opacity="0.5" />
              <line x1="150" y1="40" x2="100" y2="200" stroke="#2a3d52" stroke-width="1" opacity="0.5" />
              <line x1="150" y1="40" x2="200" y2="200" stroke="#2a3d52" stroke-width="1" opacity="0.5" />
              <!-- Nodes -->
              <circle cx="150" cy="40" r="12" fill="#00d965" class="node-pulse" />
              <circle cx="60" cy="110" r="10" fill="#00d4ff" />
              <circle cx="240" cy="110" r="10" fill="#a78bfa" />
              <circle cx="100" cy="200" r="9" fill="#ff9f43" />
              <circle cx="200" cy="200" r="9" fill="#00d4ff" />
              <!-- Labels -->
              <text x="150" y="18" text-anchor="middle" fill="#9aa8ba" font-size="10">HIBOR</text>
              <text x="40" y="105" text-anchor="middle" fill="#9aa8ba" font-size="10">首置</text>
              <text x="265" y="105" text-anchor="middle" fill="#9aa8ba" font-size="10">滙豐</text>
              <text x="85" y="222" text-anchor="middle" fill="#9aa8ba" font-size="10">印花稅</text>
              <text x="215" y="222" text-anchor="middle" fill="#9aa8ba" font-size="10">移民</text>
            </svg>
          </div>
        </div>
      </div>
    </section>

    <!-- How it works -->
    <section class="how-it-works">
      <h2 class="section-title">運作流程</h2>
      <div class="steps-flow">
        <div v-for="step in steps" :key="step.num" class="step-item">
          <div class="step-num">{{ step.num }}</div>
          <h3 class="step-title">{{ step.title }}</h3>
          <p class="step-desc">{{ step.desc }}</p>
        </div>
      </div>
    </section>

    <!-- Example predictions -->
    <section class="predictions">
      <h2 class="section-title">預測場景</h2>
      <div class="scenario-grid">
        <div
          v-for="s in scenarios"
          :key="s.type"
          class="scenario-card glass-panel"
          @click="goScenario(s.type)"
        >
          <span class="scenario-icon">{{ s.icon }}</span>
          <h3 class="scenario-title">{{ s.title }}</h3>
          <p class="scenario-desc">{{ s.description }}</p>
          <span class="scenario-cta">開始模擬 →</span>
        </div>
      </div>
    </section>

    <!-- Methodology -->
    <section class="methodology">
      <h2 class="section-title">方法論</h2>
      <div class="method-content glass-panel">
        <div class="method-grid">
          <div class="method-item">
            <h4>Agent-Based Modeling</h4>
            <p>每個代理人有獨立嘅性格（Big Five）、記憶系統、信任網絡，根據自身經驗做決策。</p>
          </div>
          <div class="method-item">
            <h4>知識圖譜推理</h4>
            <p>GraphRAG 技術將議題拆解為實體-關係網絡，追蹤因果鏈條嘅權重變化。</p>
          </div>
          <div class="method-item">
            <h4>宏觀-微觀反饋迴路</h4>
            <p>代理人行為匯總影響宏觀指標（HSI、CCL、失業率），再反過來影響下一輪決策。</p>
          </div>
          <div class="method-item">
            <h4>蒙特卡洛模擬</h4>
            <p>100 次擾動試驗生成信賴區間，量化預測不確定性。</p>
          </div>
        </div>
      </div>
    </section>

    <!-- Footer -->
    <footer class="landing-footer">
      <span>HKSimEngine</span>
      <span>Hong Kong Society Simulation Engine</span>
    </footer>
  </div>
</template>

<style scoped>
.landing {
  overflow-x: hidden;
}

/* Hero */
.hero {
  padding: 60px 24px 40px;
  max-width: 1200px;
  margin: 0 auto;
}

.hero-content {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 48px;
  align-items: center;
}

.hero-title {
  font-size: 36px;
  font-weight: 800;
  line-height: 1.3;
  color: var(--text-primary);
  margin-bottom: 16px;
}

.highlight {
  color: var(--accent-blue);
}

.hero-subtitle {
  font-size: 16px;
  line-height: 1.8;
  color: var(--text-secondary);
  margin-bottom: 24px;
}

.hero-actions {
  display: flex;
  gap: 12px;
  margin-bottom: 32px;
}

.btn-primary {
  padding: 12px 28px;
  background: var(--accent-blue);
  color: #0d1117;
  border: none;
  border-radius: var(--radius-md);
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: var(--transition);
}

.btn-primary:hover {
  background: rgba(0, 212, 255, 0.8);
  box-shadow: var(--shadow-glow-cyan);
}

.btn-secondary {
  padding: 12px 28px;
  background: var(--bg-card);
  color: var(--text-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  font-size: 15px;
  cursor: pointer;
  transition: var(--transition);
}

.btn-secondary:hover {
  border-color: var(--accent-blue);
  color: var(--accent-blue);
}

.hero-stats {
  display: flex;
  gap: 32px;
}

.stat {
  display: flex;
  flex-direction: column;
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: var(--accent-blue);
  font-family: var(--font-mono);
}

.stat-label {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 2px;
}

.hero-visual {
  display: flex;
  justify-content: center;
}

.mini-graph {
  width: 300px;
  height: 250px;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.mini-graph-svg {
  width: 100%;
  height: 100%;
}

.node-pulse {
  animation: pulse-node 2s ease-in-out infinite;
}

@keyframes pulse-node {
  0%, 100% { r: 12; opacity: 1; }
  50% { r: 14; opacity: 0.8; }
}

/* How it works */
.how-it-works {
  padding: 48px 24px;
  max-width: 1200px;
  margin: 0 auto;
}

.section-title {
  font-size: 24px;
  font-weight: 700;
  text-align: center;
  margin-bottom: 32px;
  color: var(--text-primary);
}

.steps-flow {
  display: flex;
  gap: 16px;
  overflow-x: auto;
  padding-bottom: 8px;
}

.step-item {
  flex: 1;
  min-width: 180px;
  text-align: center;
  padding: 20px 16px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  position: relative;
}

.step-num {
  width: 32px;
  height: 32px;
  line-height: 32px;
  border-radius: 50%;
  background: var(--accent-blue);
  color: #0d1117;
  font-weight: 700;
  font-size: 14px;
  margin: 0 auto 12px;
}

.step-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 6px;
}

.step-desc {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.5;
}

/* Predictions */
.predictions {
  padding: 48px 24px;
  max-width: 1200px;
  margin: 0 auto;
}

.scenario-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.scenario-card {
  padding: 24px;
  cursor: pointer;
  transition: var(--transition);
}

.scenario-card:hover {
  box-shadow: var(--shadow-md);
  border-color: var(--accent-blue);
}

.scenario-icon {
  font-size: 32px;
  display: block;
  margin-bottom: 12px;
}

.scenario-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.scenario-desc {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.6;
  margin-bottom: 12px;
}

.scenario-cta {
  font-size: 13px;
  color: var(--accent-blue);
  font-weight: 600;
}

/* Methodology */
.methodology {
  padding: 48px 24px;
  max-width: 1200px;
  margin: 0 auto;
}

.method-content {
  padding: 32px;
}

.method-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
}

.method-item h4 {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 6px;
}

.method-item p {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.6;
}

/* Footer */
.landing-footer {
  display: flex;
  justify-content: space-between;
  padding: 24px;
  border-top: 1px solid var(--border-color);
  max-width: 1200px;
  margin: 0 auto;
  font-size: 12px;
  color: var(--text-muted);
}

@media (max-width: 768px) {
  .hero-content {
    grid-template-columns: 1fr;
  }
  .hero-visual {
    display: none;
  }
  .scenario-grid {
    grid-template-columns: 1fr;
  }
  .method-grid {
    grid-template-columns: 1fr;
  }
}
</style>
