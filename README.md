<div align="center">

# ⚖️ Moirai

### *Universal Prediction Engine*

**Drop any text. Simulate any world. Predict any outcome.**

[![Python](https://img.shields.io/badge/Python-3.10%2F3.11-blue?logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green?logo=fastapi)](https://fastapi.tiangolo.com)
[![Vue 3](https://img.shields.io/badge/Vue-3.x-brightgreen?logo=vue.js)](https://vuejs.org)
[![LanceDB](https://img.shields.io/badge/Vector_DB-LanceDB-orange)](https://lancedb.com)
[![License](https://img.shields.io/badge/License-Proprietary-red)](LICENSE)

<br/>

> *Named after the Greek Fates who weave, measure, and cut the threads of destiny —*
> *Moirai weaves agents, knowledge, and time into collective intelligence.*

<br/>

**[中文介紹](#-中文介紹) · [English Introduction](#-english-introduction) · [Workflow Showcase](#-workflow-showcase) · [5-Step Workflow](#-5-step-workflow) · [Architecture](#-architecture) · [Installation](#-installation--setup) · [User Guide](#-user-guide) · [API Reference](#-api-reference)**

</div>

---

## What Makes Moirai Different

Most simulation tools are domain-locked. Moirai is not.

**Paste any seed text** — a news article, a historical event, a geopolitical briefing, a company filing — and Moirai automatically infers the actors, decisions, metrics, and shocks. Within seconds, hundreds of AI agents with distinct personalities, memories, and beliefs begin interacting. Emergent factions form. Tipping points trigger. The knowledge graph evolves. Macro forecasts update.

No configuration. No domain expertise required. Just text.

| What you drop in | What Moirai builds |
|---|---|
| `"港府宣布加息50個基點..."` | 300 HK agents across 18 districts reacting to a rate hike |
| `"Archduke assassinated in Sarajevo, alliances mobilizing..."` | 1914 July Crisis — escalation probability curves, WWI onset simulation |
| `"Iran drone strike on Israeli positions..."` | Geopolitical agent network, escalation scenarios, oil price Monte Carlo |
| `"OpenAI vs Anthropic vs Google Q4 competition..."` | Corporate agent simulation, market share forecast, faction dynamics |
| `"Colonial governor imposes trade restrictions on the port..."` | Historical economic crisis — merchant faction emergence, collective action |

---

## 🇭🇰 中文介紹

### Moirai 係咩？

**Moirai**（希臘命運三女神）係一個**通用預測引擎**，結合多智能體系統、知識圖譜同大型語言模型，模擬任何場景對各種衝擊嘅集體反應。

掉任何 seed text 入去 — 伊朗戰爭、WWI 危機、企業競爭、歷史事件 — 引擎自動推斷 agents、decisions、metrics、shocks，無需手動配置 Domain Pack。

### 核心能力

**🤖 多智能體社會模擬**
- 100–500 個 AI 代理人，自動從 seed text 生成（唔係預設 HK profiles）
- 每位代理人：記憶系統（LanceDB）、信念系統（Bayesian）、情緒狀態（VAD）、大五人格、認知偏差
- Facebook + Instagram 平台互動（OASIS 框架）

**📊 宏觀預測（HK 模式）**
- 11 個核心指標：CCL 樓價指數、失業率、恒生指數、GDP、消費者信心、HIBOR 等
- AutoARIMA + VAR，12 季度前瞻 + Monte Carlo 100 次（LHS + t-Copula）
- 回溯驗證：對比真實 HK 歷史數據（MAPE、Pearson r、方向準確率）

**🧠 知識圖譜演化**
- 從 seed text 自動抽取實體關係，構建動態 KG
- 隨模擬演化：代理人行動 → NL 描述 → 實體抽取 → 圖譜注入（Zep-style）
- WebGL 可視化 + 時間軸回放 + 回音室群組渲染

**⚡ 湧現行為**
- 回音室偵測（Louvain）、情緒蔓延、集體動量、信念極化
- 派系追蹤（FactionMapper）+ 引爆點偵測（KL 散度 vs 3 輪前）
- 認知失調：衝突信念偵測 + 4 種解決策略

**🔮 Polymarket 預測市場整合**
- 自動匹配 seed text → 真實 Polymarket 合約
- 引擎概率 vs 市場定價 → 套利信號（Alpha: BUY_YES / BUY_NO / HOLD）

**🎯 零配置快速啟動**
- 任何文字貼入，30 秒啟動，自動推斷一切

### 適用對象

| 用戶 | 用途 |
|------|------|
| 政策研究員 | 模擬政策衝擊對社會情緒嘅影響 |
| 金融分析師 | HK 宏觀指標預測 + 歷史回溯驗證 |
| 學術研究者 | 多智能體社會模擬、信息傳播、極化研究 |
| 地緣政治分析師 | 國際危機升級路徑、聯盟動態 |
| 企業策略師 | 競爭對手行為模擬、市場份額預測 |
| 投資者 | Polymarket 信號 + 宏觀情景分析 |

---

## 🌐 English Introduction

### What is Moirai?

**Moirai** is a **Universal Prediction Engine** — a multi-agent simulation system that accepts any seed text, automatically constructs a world of AI agents with distinct identities, and simulates collective behavior under shocks and evolving conditions.

It is simultaneously:
- A **social simulator** (agent interactions, echo chambers, belief propagation)
- A **forecasting engine** (macroeconomic time-series, Monte Carlo ensembles)
- A **knowledge graph** (dynamic entity-relationship tracking, Zep-style evolution)
- A **prediction market oracle** (Polymarket signal generation)
- A **narrative stress-tester** (What-If branches, counterfactual analysis)

### The Two Modes

| Mode | Trigger | Agent Source | Decision Space |
|------|---------|-------------|----------------|
| `hk_demographic` | HK keywords in seed | HK Census demographic factory | Hardcoded HK decision types |
| `kg_driven` | Any other seed text | KGAgentFactory (LLM extracts from KG nodes) | ScenarioGenerator (LLM, fully dynamic) |

In `kg_driven` mode the engine:
1. Builds a KG from your seed text
2. LLM extracts agent candidates from KG nodes (people, organizations, factions)
3. Generates cognitive fingerprints + personality profiles per agent
4. Creates domain-specific decision types, metrics, and shock types via LLM
5. Seeds agent memories with world context extracted from the text
6. Runs full simulation with Tier 1 agents (top 30–100 by influence) getting full LLM deliberation every round

---

## 🎬 Workflow Showcase

> **Five real examples showing what Moirai actually does — step by step.**

---

### Showcase 1 — Hong Kong Rate Hike Crisis

**Seed Text:**
```
港府宣布跟隨美聯儲加息50個基點，本港樓市即時出現恐慌性拋售，
多個屋苑成交價急跌8-12%，銀行按揭審批收緊，業主聯盟發起遊行示威。
```

**What happens in 5 steps:**

```
Step 1 │ GRAPH BUILD
       │ KG extracts: 港府, 美聯儲, 業主聯盟, 銀行系統, 樓市
       │ Entities linked: rate_hike → mortgage_squeeze → property_panic
       │ MemoryInitializationService seeds world context into LanceDB
       │
Step 2 │ AGENT GENERATION
       │ Mode: hk_demographic (HK keywords detected)
       │ 300 agents across 18 districts, weighted by census demographics
       │ Agent profiles: age 22–67, income HK$15K–$120K
       │ Tier 1 assigned: top 30 agents get full LLM deliberation every round
       │
Step 3 │ SIMULATION (20 rounds)
       │ Round 3:  Echo chamber forms — homeowners cluster, renters cluster
       │ Round 7:  Tipping point detected — KL divergence spike in property sentiment
       │ Round 12: Collective action emerges — protest momentum score hits 0.73
       │ Round 17: Belief polarization: pro-government 34% vs anti-government 58%
       │ Polymarket match: "HK property index decline >10% by Q3" — Engine: 67%, Market: 51%
       │
Step 4 │ REPORT
       │ ReACT agent runs 10 XAI tools: sentiment trajectory, faction map, tipping point timeline
       │ CCL index forecast: -14.2% (95% CI: -8.1% to -19.4%) over 4 quarters
       │ Monte Carlo: 78% probability of >10% property decline in 12 months
       │
Step 5 │ INTERACTION
       │ Interview Agent #147 (Sham Shui Po homeowner, age 54):
       │ "我知道而家要賣，但係我唔捨得，呢度係我嘅根..."
       │ Inject God Mode shock: "Government announces emergency mortgage relief"
       │ Watch: protest momentum drops from 0.73 → 0.41 within 3 rounds
```

**Output snapshot:**
```
Macro Forecast (12Q):      CCL: -14.2%  │  Unemployment: +1.8pp  │  HSI: -9.3%
Faction Map:               Homeowners (38%) │ Renters (29%) │ Investors (19%) │ Neutral (14%)
Tipping Points Detected:   Round 7 (property sentiment), Round 14 (political trust)
Polymarket Alpha Signal:   BUY_YES on HK property decline contract (+16% edge vs market)
Agent Consensus:           63% expect further rate hikes within 6 months
```

---

### Showcase 2 — The July Crisis 1914 (WWI Trigger Simulation)

**Seed Text:**
```
Archduke Franz Ferdinand assassinated in Sarajevo, June 28 1914.
Austria-Hungary issues ultimatum to Serbia. Russia begins partial mobilization
in support of Serbia. Germany issues blank cheque guarantee to Austria-Hungary.
France bound by alliance to Russia. Britain watches Belgian neutrality.
Ottoman Empire and Bulgaria calculating alignment. Six weeks to world war.
```

**What the engine builds:**

```
KG Nodes extracted:        Austria-Hungary, Serbia, Russia, Germany, France,
                           Britain, Ottoman Empire, Bulgaria, Franz Joseph,
                           Kaiser Wilhelm II, Tsar Nicholas II, Grey (UK FM),
                           Poincaré, Serbian Black Hand
Relationships mapped:      alliance_obligation, ultimatum_issuer, mobilization_trigger,
                           blank_cheque_guarantee, naval_rivalry, pan-Slavic_solidarity,
                           Belgian_neutrality_guarantor

Agents generated (kg_driven mode):
  "Kaiser Wilhelm II"      Tier 1 │ Values: prestige 0.91, restraint 0.21
                           Susceptibility: 0.61 │ Confirmation bias: 0.77
  "Tsar Nicholas II"       Tier 1 │ Values: pan_slavic_duty 0.83, war_aversion 0.69
  "Sir Edward Grey"        Tier 1 │ Values: balance_of_power 0.88, non-intervention 0.71
  "Franz Joseph"           Tier 1 │ Values: imperial_dignity 0.94, Serbia_punishment 0.88
  ... (54 total agents)

Decision types (LLM-generated):
  ISSUE_ULTIMATUM, ACCEPT_TERMS, REJECT_TERMS, PARTIAL_MOBILIZATION,
  FULL_MOBILIZATION, INVOKE_ALLIANCE, OFFER_MEDIATION, DECLARE_WAR

Metrics (LLM-generated):
  escalation_momentum, alliance_cohesion, mobilization_irreversibility,
  diplomatic_window, great_power_prestige
```

**Simulation result after 15 rounds:**
```
Round 2:   Serbia accepts 9/10 ultimatum terms — diplomatic window: 0.61
           Austrian hawks override moderates; full rejection demanded
Round 5:   Russia partial mobilization triggers German war planning lock-in
           Tipping point: mobilization_irreversibility crosses 0.70
Round 9:   Schlieffen Plan activated — diplomatic window collapses to 0.04
           Cascade: France mobilizes → Britain invokes Belgian guarantee
Round 15:  escalation_momentum: 0.94 │ diplomatic_window: 0.02

Monte Carlo (100 trials):
  War avoided (Serbia capitulates fully):      8%  (CI: 4–13%)
  Limited Austro-Serbian war only:            19%  (CI: 13–25%)
  World War (historical outcome):             52%  (CI: 45–59%)

Counterfactual branch: "Kaiser halts mobilization at Round 5"
  → War probability drops to 0.23
  → BUT internal regime crisis emerges in 67% of those trials by Round 12
```

---

### Showcase 3 — Iran-Israel Escalation Scenario

**Seed Text:**
```
Iranian drone swarms struck Israeli military positions in the Negev.
Israel's Iron Dome intercepted 94% of projectiles. PM Netanyahu calls emergency
cabinet session. US 5th Fleet repositions to Persian Gulf. Oil futures spike 12%.
Hezbollah signals readiness for northern front activation.
```

**Agents and scenario:**
```
Corporate agents (Tier 1):
  Netanyahu Cabinet (6)    — hawkish vs pragmatist split
  IDF High Command (4)     — escalation threshold modeling
  Iranian IRGC Council (5) — proxy calculus
  Hezbollah Command (3)    — activation timing
  US NSC (4)               — deterrence signaling
  Arab League (8)          — normalization preservation
  ... (67 total)

Metrics:    escalation_probability, oil_price_delta, civilian_casualty_risk,
            normalization_treaty_survival, regional_stability_index

Shocks:     HEZBOLLAH_ACTIVATION, US_CARRIER_DEPLOYMENT,
            SAUDI_MEDIATION_OFFER, IRAN_NUCLEAR_ESCALATION
```

**Simulation output:**
```
Escalation probability by round:
  Round 3:  0.34  (cabinet divided, US restraint signal)
  Round 7:  0.61  (Hezbollah activation shock injected)
  Round 11: 0.78  (tipping point — IRGC hawks dominate council)
  Round 15: 0.52  (US ultimatum triggers Iranian de-escalation signaling)

Monte Carlo ensemble (100 trials):
  Full regional war:        23% (CI: 17–29%)
  Limited exchange + halt:  54% (CI: 48–60%)
  Negotiated ceasefire:     23% (CI: 17–29%)

Oil price forecast:   +18–34% over 3 months (95% CI)
```

---

### Showcase 4 — OpenAI vs Anthropic vs Google (Corporate Competition)

**Seed Text:**
```
OpenAI's GPT-5 launch captures enterprise market. Anthropic's Claude 4 leads
on safety benchmarks and European regulatory approval. Google DeepMind's Gemini
Ultra 2.0 integrates into 3B Android devices. Microsoft locks in $10B OpenAI
exclusivity. Meta releases LLaMA 4 open-source. Enterprise CIOs face platform lock-in anxiety.
```

**Agents and scenario:**
```
Corporate agents (Tier 1):
  OpenAI Strategy Team     — market share defense, pricing pressure
  Anthropic Safety Board   — regulatory leverage, enterprise trust
  Google DeepMind R&D      — distribution moat exploitation
  Microsoft Azure BD       — exclusivity enforcement
  Meta AI (Open Source)    — ecosystem commoditization strategy
  Enterprise CIO Council   — vendor evaluation, lock-in risk assessment

Metrics:    market_share, regulatory_risk, enterprise_adoption,
            open_source_pressure, safety_perception, developer_mindshare

Decision types:
  PRICE_CUT, OPEN_SOURCE_RELEASE, REGULATORY_LOBBY, PARTNERSHIP_EXCLUSIVE,
  SAFETY_CERTIFICATION, BENCHMARK_PUBLISH, ENTERPRISE_PILOT
```

**Output:**
```
Round 12 faction snapshot:
  Safety-first camp:   Anthropic + EU regulators (34% of decision weight)
  Distribution moat:   Google + Microsoft (41%)
  Open ecosystem:      Meta + developers (25%)

Market share forecast (Monte Carlo, 8Q):
  OpenAI:    38% → 31% (CI: 27–35%)
  Google:    22% → 28% (CI: 24–33%)
  Anthropic: 12% → 18% (CI: 14–22%)
  Meta/OSS:   8% → 15% (CI: 11–19%)

Tipping point Round 9: EU enforcement shock collapses proprietary model trust
  → Triggers 3-round cascade of enterprise re-evaluation decisions
```

---

### Showcase 5 — What-If Branch: "What if the Fed cut rates in 2022?"

**Using Moirai's counterfactual branch simulation:**

```bash
POST /simulation/{session_id}/branch
{
  "branch_name": "Fed_Pivot_2022",
  "shock_at_round": 3,
  "shock_type": "RATE_CUT_50BPS",
  "description": "Fed reverses course — 50bps cut instead of hike"
}
```

```
Base timeline:    Fed hikes → inflation persists → recession probability 0.61
Branch timeline:  Fed cuts → asset prices spike → inflation re-accelerates
                  Round 8 divergence: 0.43 correlation with base (major fork)

Monte Carlo comparison (100 trials each):
  Base:    Recession probability 0.61 (CI: 0.54–0.68)
  Branch:  Recession probability 0.29 (CI: 0.22–0.36)
           BUT: Inflation above 5% in 12M: 0.71 (CI: 0.64–0.78)

Agent belief divergence at Round 15:
  Base:    property_confidence: 0.31 │ job_security: 0.44
  Branch:  property_confidence: 0.67 │ job_security: 0.71
           BUT: purchasing_power: 0.29 (vs 0.41 in base)

Report: "The Fed pivot would have avoided near-term recession but embedded
structural inflation — a worse outcome by 2025."
```

---

## 🏗 5-Step Workflow

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                       │
│  STEP 1          STEP 2          STEP 3      STEP 4      STEP 5     │
│  Graph Build  →  Agent Gen    →  Simulate →  Report  →  Interact   │
│                                                                       │
│  Seed text       KGAgentFactory  OASIS       ReACT       Interview  │
│  → KG nodes      LLM profiles    subprocess  10 XAI      agents     │
│  → entities      memories        God Mode    PDF export  God shocks │
│  → relations     fingerprints    shocks      Polymarket  branches   │
│                  Tier 1/2        Monte Carlo signals     What-If    │
│                  assignment      emergence                           │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

### What happens under the hood

**Step 1 — Knowledge Graph Build** (`POST /graph/build`)
- LLM extracts entities, relationships, and world context from seed text
- KG stored as nodes/edges in SQLite + WebGL-renderable JSON
- `MemoryInitializationService` runs: Phase 2 → world context (`seed_world_context` + LanceDB `swc_` tables); Phase 3 → persona templates (`seed_persona_templates`)

**Step 2 — Agent Generation + Memory Hydration** (`POST /simulation/start`)
- `ZeroConfigService.detect_mode_async()` → `hk_demographic` or `kg_driven`
- `KGAgentFactory.create(graph_id)` → three-stage LLM pipeline: eligibility filter → profile → cognitive fingerprint
- `hydrate_session_bulk()` → writes round_number=0 seed memories per agent (beliefs, context, personality)
- Tier 1 agents assigned (top 30–100 by influence score) — full LLM deliberation every round

**Step 3 — Simulation** (OASIS subprocess, structured concurrency)
- **Pre-Group 1:** Feed ranking; world event generation (kg_driven)
- **Group 1 (parallel):** Memory retrieval, trust update, emotional state
- **Group 2 (sequential):** Decisions, side effects, belief updates; kg_driven: Tier 1 LLM deliberation + belief propagation
- **Group 3 (periodic):**
  - r1: attention decay
  - r2: company decisions
  - r3: media influence, echo chambers, network evolution, virality, emotional contagion, KG evolution, faction snapshot + tipping point detection (kg_driven)
  - r5: macro feedback, KG snapshot, news shock, polarization, group formation, wealth transfers, collective momentum
- God Mode: inject shocks at any round via WebSocket

**Step 4 — Report** (`POST /report/{id}/generate`)
- ReACT agent with 10 XAI tools: `get_faction_map`, `get_tipping_points`, `get_sentiment_trajectory`, `get_belief_distribution`, `get_echo_chambers`, `run_monte_carlo`, `get_macro_forecast`, `get_polymarket_signals`, `get_agent_consensus`, `get_narrative_trace`
- PDF export + shareable public link (token-based, no auth required)

**Step 5 — Interaction**
- Interview any agent: natural language Q&A backed by their actual memory + belief state
- Inspect belief history, memory salience decay, cognitive dissonance events
- Create counterfactual branches: replay from any round with different shocks

---

## ⚙ Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                       Frontend (Vue 3 + Vite)                       │
│  Home │ GraphExplorer │ GodViewTerminal │ PredictionDashboard       │
│  Workspace │ PublicReport │ DomainBuilder │ Process                 │
└──────────────────────────┬─────────────────────────────────────────┘
                            │ HTTP + WebSocket  (5173 → 5001)
┌──────────────────────────▼─────────────────────────────────────────┐
│                   FastAPI Backend (port 5001)                        │
│  /simulation │ /graph │ /report │ /forecast │ /prediction-market    │
│  /auth │ /workspace │ /api/domain-packs │ /ws                       │
└──────┬──────────────────┬──────────────────────┬────────────────────┘
       │                  │                       │
┌──────▼──────┐   ┌───────▼──────┐   ┌──────────▼──────────────────┐
│ SQLite WAL  │   │   LanceDB    │   │   OASIS Subprocess           │
│ (55 tables) │   │ vector store │   │   Facebook/Instagram sim     │
│             │   │ 384-dim emb  │   │   100–500 LLM agents         │
└─────────────┘   └──────────────┘   └─────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────────────────────┐
│           HK Data Lake — 32 sources (hk_demographic mode only)       │
│  HKMA │ data.gov.hk │ Yahoo Finance (HSI) │ FRED │ RTHK RSS │ LIHKG │
└──────────────────────────────────────────────────────────────────────┘
```

### Key Services

| Service | Role |
|---------|------|
| `ZeroConfigService` | Detects `hk_demographic` vs `kg_driven` from seed text |
| `KGAgentFactory` | Three-stage LLM pipeline: eligibility → profile → cognitive fingerprint |
| `MemoryInitializationService` | Extracts world context + persona templates at graph build (Step 1) |
| `ScenarioGenerator` | LLM-generates decision types, metrics, shocks for any domain |
| `UniversalDecisionEngine` | kg_driven: entity-type filter + full LLM deliberation |
| `DecisionEngine` | hk_demographic: rule filter (90%) → LLM batch (10%) |
| `CognitiveAgentEngine` | Tier 1 full-LLM deliberation → `DeliberationResult` per round |
| `BeliefPropagationEngine` | Embedding-based belief update + confirmation bias dampening + conformity blending |
| `AgentMemoryService` | Memory storage, salience decay, semantic search (LanceDB) |
| `EmotionalEngine` | VAD model + Big Five personality modulation |
| `BeliefSystem` | Bayesian updates across 6 core topics; cognitive dissonance detection |
| `EmergenceTracker` | `FactionMapper` (Louvain) + `TippingPointDetector` (KL divergence vs 3 rounds ago) |
| `MultiRunOrchestrator` | Phase B zero-LLM stochastic ensemble; t-distribution sampling; up to 10,000 trials |
| `WorldEventGenerator` | Per-round LLM world events filtered to active simulation metrics (kg_driven) |
| `MacroController` | HK macro state + shock application + sentiment feedback loop |
| `MonteCarloEngine` | 100-trial LHS + t-Copula with Wilson score CIs |
| `TimeSeriesForecaster` | AutoARIMA + VAR, 12-quarter forecast (HK mode) |
| `CalibrationPipeline` | OLS + BH-FDR correction, 13 HK indicator pairs |
| `RetrospectiveValidator` | Period-based backtest vs HK actual historical data |
| `KGGraphUpdater` | Zep-style dynamic KG evolution from agent actions |
| `SocialNetworkBuilder` | Network init, Louvain echo chamber detection |
| `NetworkEvolutionEngine` | Tie formation/dissolution, triadic closure |
| `FeedRankingEngine` | 3 algorithms: chronological / engagement / echo chamber |
| `ReportAgent` | ReACT loop with 10 XAI tools → narrative + PDF |
| `PolymarketClient` | Gamma API matching + alpha signal generation (10-min TTL cache) |

### Database Tables (55)

| Category | Tables |
|----------|--------|
| Core | `simulation_sessions`, `agent_profiles`, `kg_nodes`, `kg_edges`, `kg_communities`, `kg_snapshots` |
| Simulation | `simulation_actions`, `agent_memories`, `memory_triples`, `agent_relationships`, `agent_decisions` |
| Economy | `hk_data_snapshots`, `market_data`, `macro_scenarios`, `ensemble_results`, `validation_runs` |
| Social | `social_sentiment`, `echo_chamber_snapshots`, `news_headlines`, `data_provenance` |
| Emergence | `network_events`, `agent_feeds`, `filter_bubble_snapshots`, `virality_scores`, `emotional_states`, `belief_states`, `cognitive_dissonance`, `polarization_snapshots`, `scale_benchmarks` |
| B2B | `company_profiles`, `company_decisions`, `media_agents` |
| Auth | `users`, `workspaces`, `workspace_members`, `comments` |
| Other | `reports`, `scenario_branches`, `population_distributions`, `custom_domain_packs`, `prediction_signals` |
| Cognitive Theater (kg_driven) | `cognitive_fingerprints`, `world_events`, `faction_snapshots_v2`, `tipping_points`, `narrative_traces`, `multi_run_results` |
| Seed Memory (kg_driven) | `seed_world_context`, `seed_persona_templates` |

---

## 🛠 Installation & Setup

### Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | **3.10 or 3.11 only** | OASIS does NOT support 3.12+ |
| Node.js | 18+ | Frontend |
| pyenv | recommended | Python version management |

### 1. Clone

```bash
git clone https://github.com/destinyfrancis/Moirai.git
cd Moirai
```

### 2. Python Environment

```bash
pyenv install 3.11.9
pyenv local 3.11.9

python -m venv .venv311
source .venv311/bin/activate  # Windows: .venv311\Scripts\activate

pip install -e ".[dev]"
```

> **Warning:** Python 3.12+ will break OASIS. Strictly use 3.10 or 3.11.

### 3. OASIS Framework

```bash
pip install camel-ai[all]
# or from source:
# pip install git+https://github.com/camel-ai/oasis.git
```

### 4. Environment Variables

```bash
cp .env.example .env
```

```env
# Required
OPENROUTER_API_KEY=sk-or-v1-your-key-here   # DeepSeek V3.2 (~$0.00014/1K tokens)

# Optional
FIREWORKS_API_KEY=fw_your-key-here
ANTHROPIC_API_KEY=sk-ant-your-key-here
FRED_API_KEY=your-fred-key                   # HK macroeconomic data

# Server
DATABASE_PATH=data/hksimengine.db
HOST=0.0.0.0
PORT=5001
LLM_PROVIDER=openrouter
```

**Get OpenRouter key:** [openrouter.ai/keys](https://openrouter.ai/keys) — DeepSeek V3.2 runs a 300-agent, 20-round simulation for ~$1.12.

### 5. Frontend

```bash
cd frontend && npm install && cd ..
```

### 6. Initialize Data (HK mode)

```bash
# Pre-seed HK public data (optional — auto-downloads on first launch)
.venv311/bin/python -m backend.data_pipeline.download_all --normalize
```

### 7. Launch

**Terminal 1 — Backend:**
```bash
source .venv311/bin/activate
cd backend && uvicorn run:app --reload --port 5001
```

**Terminal 2 — Frontend:**
```bash
cd frontend && npm run dev
```

Open **http://localhost:5173**

---

## ⚙️ Simulation Presets

| Preset | Agents | Rounds | MC Trials | Emergence | Cost (DeepSeek V3.2) |
|--------|--------|--------|-----------|-----------|----------------------|
| `PRESET_FAST` | 100 | 15 | 30 | Off | ~$0.42 |
| `PRESET_STANDARD` | 300 | 20 | 100 | On | ~$1.12 |
| `PRESET_DEEP` | 500 | 30 | 500 | On | ~$1.89 |

## 🗂 Domain Packs (7 built-in)

| Pack ID | Domain | Language |
|---------|--------|----------|
| `hk_city` | Hong Kong urban society | zh-HK |
| `us_markets` | US financial markets | en-US |
| `global_macro` | Global macroeconomics | en-US |
| `public_narrative` | Public opinion & narrative | zh-HK / en-US |
| `real_estate` | Property market | zh-HK |
| `company_competitor` | Corporate competitive analysis | en-US |
| `community_movement` | Community movements | zh-HK |

Custom packs: `POST /api/domain-packs/generate` → edit in DomainBuilder → `POST /api/domain-packs/save`

---

## 🖥 User Guide

### Step-by-Step Workflow

#### Step 1 — Quick Start
1. Navigate to **http://localhost:5173**
2. Paste any text into the Quick Start box (news, briefing, historical event, company filing)
3. Click **Launch Simulation**
4. The system auto-detects mode (`hk_demographic` vs `kg_driven`), infers scale and parameters

#### Step 2 — Monitor Simulation (Live)
- **Live Feed**: Watch agents post, respond, and debate in real-time
- **Topics**: Track trending hashtags and emerging narratives
- **Agents**: Inspect individual agent beliefs, memories, and decisions
- **Network**: Watch social network topology change across rounds
- **Emotional Map**: Heatmap of agent VAD emotional states

#### Step 3 — Inject Shocks (God Mode)
- Click **God Mode** panel
- Select a shock type (rate hike, political crisis, pandemic, military escalation)
- Set magnitude (0.0–1.0) and target round
- Watch agents react in real-time via WebSocket updates

#### Step 4 — Analyze Results
- **Knowledge Graph Explorer**: Navigate entity relationships with timeline scrubber and echo chamber hull rendering
- **Prediction Dashboard**: View 11-indicator forecasts (HK mode) with backtest validation, 80%/95% confidence intervals
- **God View Terminal**: Dark terminal UI — live Polymarket contract monitoring, signal dashboard, agent consensus feed

#### Step 5 — Export & Share
- Generate AI report with 10 XAI tools (ReACT mode) — typically 5–15 minutes for STANDARD preset
- Export as PDF
- Share via public link (token-based, no authentication required for recipients)

#### Step 6 — Counterfactual Analysis
- From any completed simulation, click **Create Branch**
- Set a divergence point (round number) and inject an alternative shock
- Compare base vs branch: agent belief divergence, metric trajectories, Monte Carlo outcomes

---

## 📡 API Reference

### Quick Start (Zero Config)
```http
POST /simulation/quick-start
{ "seed_text": "..." }
→ { session_id, status_url, estimated_duration_seconds }
```

### Full Config Start
```http
POST /simulation/start
{
  "seed_text": "...",
  "preset": "PRESET_STANDARD",
  "num_agents": 300,
  "num_rounds": 20
}
```

### Simulation Status & Results
```http
GET  /simulation/{id}/status
GET  /simulation/{id}/agents
GET  /simulation/{id}/actions
GET  /simulation/{id}/decisions
GET  /simulation/{id}/echo-chambers
GET  /simulation/{id}/factions
GET  /simulation/{id}/tipping-points
GET  /simulation/{id}/multi-run
GET  /simulation/{id}/macro-history
GET  /simulation/{id}/emotional-heatmap
GET  /simulation/{id}/agents/{agent_id}/beliefs
GET  /simulation/{id}/cognitive-dissonance
```

### God Mode — Inject Shock
```http
POST /simulation/{id}/shock
{ "shock_type": "rate_hike", "magnitude": 0.5, "description": "加息50bps" }
```

### Counterfactual Branch
```http
POST /simulation/{id}/branch
{ "branch_name": "no_rate_hike", "shock_at_round": 5, "shock_type": "RATE_CUT" }
```

### Knowledge Graph
```http
POST /graph/build
GET  /graph/{id}/snapshots
GET  /graph/analyze-seed
POST /graph/upload-seed
```

### Macroeconomic Forecast (HK mode)
```http
GET /forecast/{metric}          # ccl_index, unemployment, hsi_level, gdp_growth, ...
GET /forecast/{metric}/backtest
GET /simulation/{id}/macro-history
```

### Report
```http
POST /report/{id}/generate
GET  /report/{id}/pdf
POST /report/{id}/share
```

### Prediction Market
```http
GET /api/prediction-market/contracts
GET /api/prediction-market/matched
GET /api/prediction-market/signals?session_id={id}
```

### Auth & Workspace
```http
POST /auth/register
POST /auth/login
GET  /auth/me
POST /workspace
POST /workspace/{id}/invite
```

### Domain Packs
```http
GET  /api/domain-packs
POST /api/domain-packs/generate
POST /api/domain-packs/save
```

Full interactive docs: **http://localhost:5001/docs**

---

## 🧪 Testing

```bash
make test                              # Unit only (~2001 tests, ~21s)
make test-int                          # Integration (~186 tests)
make test-all                          # Full suite (~2200 tests, ~62s)
make test-file F=test_belief_system    # Single file
make test-changed                      # Only tests for git-changed source files
```

Test markers: `unit` (default, pure logic), `integration` (DB/HTTP), `slow` (>10s, manual).

---

## 🛡 Process Management

Kill stray simulation processes (important after crashes):

```bash
# Kill OASIS subprocesses
pkill -f "run_.*_simulation.py" || true

# Kill backend server
pkill -f "uvicorn" || true

# Or use Makefile shortcut
make stop
```

---

## 📋 System Requirements

```
Python:   3.10 or 3.11 (NOT 3.12+)
Node.js:  18+
RAM:      8GB minimum, 16GB recommended (500-agent simulations)
Storage:  2GB+ (data lake + vector stores)
API Keys: OpenRouter (required); FRED, Fireworks (optional)
```

---

## 🤝 Contributing

1. Open an [Issue](https://github.com/destinyfrancis/Moirai/issues)
2. Fork + Pull Request
3. Code style: `ruff`, immutable Pydantic models (`ConfigDict(frozen=True)`), async-first, `dataclasses.replace()` for state changes, 200–400 lines per file

---

## 📄 License

Proprietary — All rights reserved. Contact the repository owner for licensing inquiries.

---

<div align="center">

**⚖️ Moirai** — *Weaving the threads of any world's future*

*Multi-agent simulation · Knowledge graphs · Macroeconomic forecasting · Emergent behavior · Prediction markets*

</div>
