<script setup>
import { useRouter } from 'vue-router'

const router = useRouter()

const steps = [
  { num: '01', label: 'GRAPH', title: 'Knowledge Graph', desc: 'Seed text → entity extraction → causal network auto-built' },
  { num: '02', label: 'ENV', title: 'Environment Setup', desc: 'Agent factory generates profiles from KG nodes, zero config needed' },
  { num: '03', label: 'SIM', title: 'Simulation', desc: 'OASIS multi-agent engine runs with emergent behavior fully on' },
  { num: '04', label: 'REPORT', title: 'ReACT Report', desc: '3-phase LLM: outline → per-section tool calls → markdown assembly' },
  { num: '05', label: 'INTERACT', title: 'Deep Interaction', desc: 'Interview agents, inject shocks, branch into What-If scenarios' },
]

const features = [
  { icon: '◈', title: 'Universal Mode', desc: 'Drop any seed text — news, fiction, geopolitics. Engine infers agents, decisions, metrics, shocks automatically.' },
  { icon: '⬡', title: 'Knowledge Graph', desc: 'GraphRAG tracks entity relationships and causal chains. Snapshots every 5 rounds, evolves with each interaction.' },
  { icon: '⊕', title: 'Emergence Engine', desc: 'Faction formation, tipping points, echo chambers, virality cascades — all emergent, not scripted.' },
  { icon: '◱', title: 'Monte Carlo', desc: '100-trial LHS + t-Copula sampling. Wilson score confidence intervals. Up to 10,000 stochastic trials.' },
  { icon: '⟳', title: 'Macro Feedback', desc: '11 macro indicators updated per round. Agent micro-decisions feed back into macro state in real time.' },
  { icon: '⊞', title: 'Scenario Branches', desc: 'Fork any simulation at any round. Compare diverging timelines side by side.' },
]
</script>

<template>
  <div class="landing">
    <!-- Background grid -->
    <div class="bg-grid" />

    <!-- Nav -->
    <nav class="nav">
      <div class="nav-inner">
        <span class="nav-logo">MORAI</span>
        <div class="nav-links">
          <a href="#how-it-works" class="nav-link">How it works</a>
          <a href="#features" class="nav-link">Features</a>
          <button class="nav-cta" @click="router.push('/app')">Launch Engine →</button>
        </div>
      </div>
    </nav>

    <!-- Hero -->
    <section class="hero">
      <div class="hero-eyebrow">UNIVERSAL PREDICTION ENGINE</div>
      <h1 class="hero-title">
        Drop any text.<br/>
        <span class="hero-title-accent">Simulate any world.</span>
      </h1>
      <p class="hero-sub">
        Feed Morai a sentence, a document, a scenario — it builds the knowledge graph,<br/>
        spawns agents, runs the simulation, and predicts collective outcomes.
      </p>
      <div class="hero-actions">
        <button class="btn-primary" @click="router.push('/app')">Start Predicting</button>
        <button class="btn-ghost" @click="router.push('/app/workspace')">Workspace</button>
      </div>
      <div class="hero-stats">
        <div class="stat-item">
          <span class="stat-n">50–10,000</span>
          <span class="stat-l">Agents per run</span>
        </div>
        <div class="stat-divider" />
        <div class="stat-item">
          <span class="stat-n">11</span>
          <span class="stat-l">Macro indicators</span>
        </div>
        <div class="stat-divider" />
        <div class="stat-item">
          <span class="stat-n">100+</span>
          <span class="stat-l">Monte Carlo trials</span>
        </div>
        <div class="stat-divider" />
        <div class="stat-item">
          <span class="stat-n">14</span>
          <span class="stat-l">XAI analysis tools</span>
        </div>
      </div>
      <!-- Hero visual: animated graph -->
      <div class="hero-visual">
        <svg viewBox="0 0 480 200" class="hero-svg" fill="none" xmlns="http://www.w3.org/2000/svg">
          <!-- connection lines -->
          <line x1="240" y1="40" x2="80" y2="120" stroke="#00d4ff" stroke-width="1" stroke-dasharray="4 4" opacity="0.4"/>
          <line x1="240" y1="40" x2="400" y2="120" stroke="#a78bfa" stroke-width="1" stroke-dasharray="4 4" opacity="0.4"/>
          <line x1="80" y1="120" x2="160" y2="180" stroke="#00ff94" stroke-width="1" stroke-dasharray="4 4" opacity="0.4"/>
          <line x1="400" y1="120" x2="320" y2="180" stroke="#00d4ff" stroke-width="1" stroke-dasharray="4 4" opacity="0.4"/>
          <line x1="160" y1="180" x2="320" y2="180" stroke="#a78bfa" stroke-width="1" stroke-dasharray="4 4" opacity="0.3"/>
          <line x1="80" y1="120" x2="400" y2="120" stroke="#00ff94" stroke-width="1" stroke-dasharray="4 4" opacity="0.2"/>
          <!-- nodes -->
          <circle cx="240" cy="40" r="10" fill="#00d4ff" opacity="0.9" class="pulse-node"/>
          <circle cx="80" cy="120" r="8" fill="#00ff94" opacity="0.8"/>
          <circle cx="400" cy="120" r="8" fill="#a78bfa" opacity="0.8"/>
          <circle cx="160" cy="180" r="7" fill="#00d4ff" opacity="0.7"/>
          <circle cx="320" cy="180" r="7" fill="#00ff94" opacity="0.7"/>
          <circle cx="240" cy="120" r="5" fill="#a78bfa" opacity="0.5"/>
          <!-- labels -->
          <text x="240" y="24" text-anchor="middle" fill="#00d4ff" font-size="9" font-family="monospace" opacity="0.7">SEED EVENT</text>
          <text x="60" y="116" text-anchor="middle" fill="#9aa8ba" font-size="8" font-family="monospace">ACTOR A</text>
          <text x="420" y="116" text-anchor="middle" fill="#9aa8ba" font-size="8" font-family="monospace">ACTOR B</text>
          <text x="150" y="196" text-anchor="middle" fill="#9aa8ba" font-size="8" font-family="monospace">POLICY</text>
          <text x="330" y="196" text-anchor="middle" fill="#9aa8ba" font-size="8" font-family="monospace">MARKET</text>
        </svg>
      </div>
    </section>

    <!-- 5-Step Workflow -->
    <section id="how-it-works" class="workflow">
      <div class="section-label">HOW IT WORKS</div>
      <h2 class="section-title">5-Step Workflow</h2>
      <div class="steps-row">
        <template v-for="(step, i) in steps" :key="step.num">
          <div class="step-card">
            <div class="step-num">{{ step.num }}</div>
            <div class="step-label-tag">{{ step.label }}</div>
            <h3 class="step-name">{{ step.title }}</h3>
            <p class="step-desc">{{ step.desc }}</p>
          </div>
          <div v-if="i < steps.length - 1" class="step-arrow">→</div>
        </template>
      </div>
    </section>

    <!-- Features -->
    <section id="features" class="features">
      <div class="section-label">CAPABILITIES</div>
      <h2 class="section-title">What the Engine Does</h2>
      <div class="features-grid">
        <div v-for="f in features" :key="f.title" class="feature-card">
          <span class="feature-icon">{{ f.icon }}</span>
          <h3 class="feature-title">{{ f.title }}</h3>
          <p class="feature-desc">{{ f.desc }}</p>
        </div>
      </div>
    </section>

    <!-- Example Use Cases -->
    <section class="use-cases">
      <div class="section-label">USE CASES</div>
      <h2 class="section-title">Works on Any Domain</h2>
      <div class="use-case-row">
        <div class="use-case-item">
          <span class="uc-tag">Geopolitics</span>
          <p>Taiwan Strait escalation, Iran-Israel scenarios, trade war cascades</p>
        </div>
        <div class="use-case-item">
          <span class="uc-tag">Finance</span>
          <p>Fed rate hike contagion, crypto market panics, corporate competition</p>
        </div>
        <div class="use-case-item">
          <span class="uc-tag">Society</span>
          <p>Policy impact modeling, social movement dynamics, demographic shifts</p>
        </div>
        <div class="use-case-item">
          <span class="uc-tag">Fiction</span>
          <p>Dream of the Red Chamber, Harry Potter, any narrative world</p>
        </div>
      </div>
    </section>

    <!-- CTA -->
    <section class="cta-section">
      <div class="cta-box">
        <div class="cta-label">READY TO SIMULATE?</div>
        <h2 class="cta-title">Drop your first scenario</h2>
        <p class="cta-sub">No configuration needed. Paste any text and the engine handles the rest.</p>
        <button class="btn-primary btn-large" @click="router.push('/app')">
          Launch Engine →
        </button>
      </div>
    </section>

    <!-- Footer -->
    <footer class="footer">
      <span class="footer-brand">MORAI</span>
      <span class="footer-desc">Universal Prediction Engine · Agent-Based Simulation</span>
      <span class="footer-copy">Built with FastAPI · Vue 3 · OASIS · LanceDB</span>
    </footer>
  </div>
</template>

<style scoped>
/* ─── Base ─────────────────────────────────────────────────────────────── */
.landing {
  background: #080d18;
  color: #e2e8f0;
  min-height: 100vh;
  overflow-x: hidden;
  position: relative;
}

.bg-grid {
  position: fixed;
  inset: 0;
  background-image:
    linear-gradient(rgba(0, 212, 255, 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0, 212, 255, 0.03) 1px, transparent 1px);
  background-size: 40px 40px;
  pointer-events: none;
  z-index: 0;
}

/* ─── Nav ───────────────────────────────────────────────────────────────── */
.nav {
  position: sticky;
  top: 0;
  z-index: 100;
  background: rgba(8, 13, 24, 0.85);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid rgba(0, 212, 255, 0.1);
}
.nav-inner {
  max-width: 1100px;
  margin: 0 auto;
  padding: 14px 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.nav-logo {
  font-size: 18px;
  font-weight: 800;
  letter-spacing: 4px;
  color: #00d4ff;
  font-family: 'JetBrains Mono', 'SF Mono', monospace;
}
.nav-links { display: flex; align-items: center; gap: 24px; }
.nav-link {
  font-size: 13px;
  color: #64748b;
  text-decoration: none;
  transition: color 0.2s;
}
.nav-link:hover { color: #e2e8f0; }
.nav-cta {
  padding: 8px 18px;
  background: rgba(0, 212, 255, 0.1);
  border: 1px solid rgba(0, 212, 255, 0.3);
  border-radius: 6px;
  color: #00d4ff;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}
.nav-cta:hover {
  background: rgba(0, 212, 255, 0.2);
  box-shadow: 0 0 20px rgba(0, 212, 255, 0.2);
}

/* ─── Hero ──────────────────────────────────────────────────────────────── */
.hero {
  position: relative;
  z-index: 1;
  max-width: 900px;
  margin: 0 auto;
  padding: 100px 24px 60px;
  text-align: center;
}
.hero-eyebrow {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 3px;
  color: #00d4ff;
  font-family: 'JetBrains Mono', monospace;
  margin-bottom: 24px;
  opacity: 0.8;
}
.hero-title {
  font-size: clamp(36px, 6vw, 64px);
  font-weight: 800;
  line-height: 1.15;
  color: #f1f5f9;
  margin-bottom: 24px;
  letter-spacing: -1px;
}
.hero-title-accent {
  background: linear-gradient(135deg, #00d4ff, #a78bfa);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.hero-sub {
  font-size: 17px;
  color: #64748b;
  line-height: 1.8;
  margin-bottom: 36px;
  max-width: 600px;
  margin-left: auto;
  margin-right: auto;
}
.hero-actions {
  display: flex;
  gap: 12px;
  justify-content: center;
  margin-bottom: 48px;
}
.btn-primary {
  padding: 12px 28px;
  background: linear-gradient(135deg, #00d4ff, #00b4cc);
  color: #080d18;
  border: none;
  border-radius: 8px;
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s;
  letter-spacing: 0.3px;
}
.btn-primary:hover {
  box-shadow: 0 0 30px rgba(0, 212, 255, 0.5);
  transform: translateY(-1px);
}
.btn-primary.btn-large {
  padding: 16px 40px;
  font-size: 16px;
}
.btn-ghost {
  padding: 12px 28px;
  background: transparent;
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 8px;
  color: #94a3b8;
  font-size: 15px;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-ghost:hover {
  border-color: rgba(255,255,255,0.3);
  color: #e2e8f0;
}
.hero-stats {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 0;
  margin-bottom: 48px;
  flex-wrap: wrap;
}
.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 0 32px;
}
.stat-n {
  font-size: 26px;
  font-weight: 800;
  color: #f1f5f9;
  font-family: 'JetBrains Mono', monospace;
  line-height: 1;
  margin-bottom: 4px;
}
.stat-l {
  font-size: 11px;
  color: #475569;
  letter-spacing: 1px;
  text-transform: uppercase;
}
.stat-divider {
  width: 1px;
  height: 40px;
  background: rgba(255,255,255,0.08);
}
.hero-visual {
  display: flex;
  justify-content: center;
}
.hero-svg {
  width: 100%;
  max-width: 480px;
  height: 200px;
  opacity: 0.7;
}
.pulse-node {
  animation: pulse-glow 2.5s ease-in-out infinite;
}
@keyframes pulse-glow {
  0%, 100% { opacity: 0.9; filter: drop-shadow(0 0 6px #00d4ff); }
  50% { opacity: 0.6; filter: drop-shadow(0 0 12px #00d4ff); }
}

/* ─── Section Label ─────────────────────────────────────────────────────── */
.section-label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 4px;
  color: #00ff94;
  font-family: 'JetBrains Mono', monospace;
  margin-bottom: 12px;
  text-align: center;
}
.section-title {
  font-size: clamp(22px, 3vw, 32px);
  font-weight: 700;
  text-align: center;
  color: #f1f5f9;
  margin-bottom: 48px;
  letter-spacing: -0.5px;
}

/* ─── Workflow ──────────────────────────────────────────────────────────── */
.workflow {
  position: relative;
  z-index: 1;
  padding: 80px 24px;
  max-width: 1200px;
  margin: 0 auto;
  border-top: 1px solid rgba(255,255,255,0.05);
}
.steps-row {
  display: flex;
  align-items: flex-start;
  gap: 0;
  overflow-x: auto;
  padding-bottom: 8px;
}
.step-card {
  flex: 1;
  min-width: 160px;
  padding: 24px 20px;
  background: rgba(255,255,255,0.02);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 12px;
  transition: border-color 0.2s, background 0.2s;
}
.step-card:hover {
  border-color: rgba(0, 212, 255, 0.3);
  background: rgba(0, 212, 255, 0.04);
}
.step-num {
  font-size: 28px;
  font-weight: 800;
  color: rgba(255,255,255,0.07);
  font-family: 'JetBrains Mono', monospace;
  line-height: 1;
  margin-bottom: 8px;
}
.step-label-tag {
  display: inline-block;
  padding: 2px 8px;
  background: rgba(0, 212, 255, 0.1);
  border: 1px solid rgba(0, 212, 255, 0.2);
  border-radius: 4px;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 2px;
  color: #00d4ff;
  font-family: 'JetBrains Mono', monospace;
  margin-bottom: 10px;
}
.step-name {
  font-size: 14px;
  font-weight: 600;
  color: #e2e8f0;
  margin-bottom: 6px;
}
.step-desc {
  font-size: 12px;
  color: #475569;
  line-height: 1.6;
}
.step-arrow {
  padding: 0 8px;
  color: rgba(255,255,255,0.15);
  font-size: 18px;
  align-self: center;
  flex-shrink: 0;
  margin-top: -16px;
}

/* ─── Features ──────────────────────────────────────────────────────────── */
.features {
  position: relative;
  z-index: 1;
  padding: 80px 24px;
  max-width: 1200px;
  margin: 0 auto;
  border-top: 1px solid rgba(255,255,255,0.05);
}
.features-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}
.feature-card {
  padding: 28px 24px;
  background: rgba(255,255,255,0.02);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 12px;
  transition: all 0.2s;
}
.feature-card:hover {
  border-color: rgba(167, 139, 250, 0.3);
  background: rgba(167, 139, 250, 0.03);
}
.feature-icon {
  display: block;
  font-size: 20px;
  color: #a78bfa;
  margin-bottom: 14px;
}
.feature-title {
  font-size: 15px;
  font-weight: 600;
  color: #e2e8f0;
  margin-bottom: 8px;
}
.feature-desc {
  font-size: 13px;
  color: #475569;
  line-height: 1.65;
}

/* ─── Use Cases ─────────────────────────────────────────────────────────── */
.use-cases {
  position: relative;
  z-index: 1;
  padding: 80px 24px;
  max-width: 1200px;
  margin: 0 auto;
  border-top: 1px solid rgba(255,255,255,0.05);
}
.use-case-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}
.use-case-item {
  padding: 24px 20px;
  background: rgba(255,255,255,0.02);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 12px;
}
.uc-tag {
  display: inline-block;
  padding: 3px 10px;
  background: rgba(0, 255, 148, 0.1);
  border: 1px solid rgba(0, 255, 148, 0.2);
  border-radius: 20px;
  font-size: 11px;
  font-weight: 600;
  color: #00ff94;
  letter-spacing: 0.5px;
  margin-bottom: 12px;
}
.use-case-item p {
  font-size: 13px;
  color: #475569;
  line-height: 1.6;
}

/* ─── CTA ───────────────────────────────────────────────────────────────── */
.cta-section {
  position: relative;
  z-index: 1;
  padding: 80px 24px;
  max-width: 1200px;
  margin: 0 auto;
}
.cta-box {
  text-align: center;
  padding: 72px 40px;
  background: radial-gradient(ellipse at 50% 100%, rgba(0, 212, 255, 0.06) 0%, transparent 70%),
              rgba(255,255,255,0.02);
  border: 1px solid rgba(0, 212, 255, 0.15);
  border-radius: 20px;
}
.cta-label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 4px;
  color: #00d4ff;
  font-family: 'JetBrains Mono', monospace;
  margin-bottom: 16px;
}
.cta-title {
  font-size: clamp(24px, 3vw, 36px);
  font-weight: 700;
  color: #f1f5f9;
  margin-bottom: 12px;
}
.cta-sub {
  font-size: 15px;
  color: #475569;
  margin-bottom: 32px;
}

/* ─── Footer ─────────────────────────────────────────────────────────────── */
.footer {
  position: relative;
  z-index: 1;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 24px;
  max-width: 1200px;
  margin: 0 auto;
  border-top: 1px solid rgba(255,255,255,0.05);
  flex-wrap: wrap;
  gap: 8px;
}
.footer-brand {
  font-size: 13px;
  font-weight: 800;
  letter-spacing: 3px;
  color: #00d4ff;
  font-family: 'JetBrains Mono', monospace;
}
.footer-desc, .footer-copy {
  font-size: 11px;
  color: #334155;
}

/* ─── Responsive ─────────────────────────────────────────────────────────── */
@media (max-width: 900px) {
  .features-grid { grid-template-columns: repeat(2, 1fr); }
  .use-case-row { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 600px) {
  .features-grid { grid-template-columns: 1fr; }
  .use-case-row { grid-template-columns: 1fr; }
  .steps-row { flex-direction: column; }
  .step-arrow { display: none; }
  .hero-stats { gap: 24px; }
  .stat-divider { display: none; }
  .footer { flex-direction: column; text-align: center; }
}
</style>
