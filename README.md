# MurmuraScope

<div align="center">

**Universal Prediction Engine · 通用預測引擎**

*Turn any text into a living simulation of collective behaviour*
*將任意文本轉化為集體行為的活態模擬*

[![License](https://img.shields.io/badge/license-Prosperity%20Public%202.0-orange)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11-blue)](https://www.python.org/)
[![Vue](https://img.shields.io/badge/vue-3.x-brightgreen)](https://vuejs.org/)
[![FastAPI](https://img.shields.io/badge/fastapi-0.11x-009688)](https://fastapi.tiangolo.com/)

</div>

---

## Overview · 概覽

**[EN]**
MurmuraScope is a multi-agent social simulation engine that transforms any seed text — a news article, a geopolitical brief, a novel excerpt, a company memo — into a dynamic world populated by AI agents. Each agent has a distinct personality, belief system, and memory. They interact, form factions, debate, spread information, and respond to shocks over simulated time, producing statistically rigorous forecasts of collective behaviour.

**[繁中]**
MurmuraScope 是一個多智能體社會模擬引擎，能將任意 seed text（新聞文章、地緣政治簡報、小說片段、公司備忘錄）轉化為一個由 AI agents 組成的動態世界。每個 agent 具備獨特的人格、信仰體系及記憶。它們互動、組成派系、辯論、傳播資訊、回應衝擊，歷經模擬時間後產出集體行為的統計嚴謹預測。

---

## Key Capabilities · 核心能力

| Capability | Description | 說明 |
|-----------|-------------|------|
| **Zero-Config Universal Mode** | Drop any text in; engine auto-infers agents, decisions, metrics, shocks | 掉任意文本入去，引擎自動推斷 agents、決策、指標、衝擊 |
| **4-Stage Actor Discovery** | Finds hidden stakeholders beyond what's explicitly mentioned (up to 80 implied actors) | 發現文本未明確提及的隱藏持份者（最多 80 個） |
| **Cognitive Agent Profiles** | Big Five personality + Attachment Style + Cognitive Fingerprint per agent | 每個 agent 具備大五人格 + 依附風格 + 認知指紋 |
| **Bayesian Belief Revision** | True Bayesian updates, not linear deltas; belief propagation via embeddings | 真正貝葉斯更新，非線性差值；embedding-based 信念傳播 |
| **Emergence Detection** | Faction formation (Louvain), tipping points (JSD), echo chambers, polarisation | 派系形成、引爆點、回音室、極化偵測 |
| **Monte Carlo Ensemble** | Swarm ensemble forks at divergence points; 500-trial LHS + t-Copula | 在分歧點分叉的 Swarm Ensemble；500 次 LHS + t-Copula |
| **Macro-Economic Feedback** | 10 economic indicators updated by agent sentiment every 5 rounds | 10 個宏觀指標每 5 輪由 agent 情緒更新 |
| **What-If Branching** | Inject shocks mid-simulation; auto-fork at tipping points | 模擬中注入衝擊；在引爆點自動分叉反事實 |
| **AI Reports** | 3-phase ReACT report with 18 XAI tools; PDF export + shareable token | 3 階段 ReACT 報告，18 個 XAI 工具；PDF 導出 |
| **Agent Interviews** | Post-simulation roleplay with memory-augmented agents | 模擬後與記憶增強 agents 角色扮演 |
| **Runtime Settings** | Change API keys, LLM models, simulation defaults in-app — no restart needed | 在應用內更改 API keys、模型、預設值，無需重啟 |

---

## Quick Start · 快速啟動

### Option A — Local Development · 本地開發（推薦）

**Requirements · 需求：** Python 3.10 or 3.11 · Node.js 18+

```bash
git clone https://github.com/destinyfrancis/MurmuraScope.git
cd MurmuraScope
make quickstart
```

The wizard automatically · 向導自動執行：
- Creates `.venv311` virtual environment and installs all dependencies · 建立虛擬環境並安裝所有依賴
- Copies `.env.example` → `.env` and prompts for your API key · 複製 `.env.example` 並提示輸入 API key
- Starts backend (`:5001`) + frontend (`:5173`) and opens the browser · 啟動後端 + 前端並自動開啟瀏覽器

**Daily development · 日常開發：**
```bash
make start      # Start both servers · 啟動兩個服務
make stop       # Kill all processes · 停止所有進程
make backend    # Backend only · 只啟動後端
make frontend   # Frontend only · 只啟動前端
```

### Option B — Docker · Docker（零依賴）

```bash
cp .env.example .env        # Fill in API keys · 填入 API keys
docker compose up -d        # Frontend :8080 · Backend :5001
```

```bash
# With distributed tracing · 附分散式追蹤
docker compose --profile observability up -d    # + Jaeger at :16686
```

---

## The 5-Step Workflow · 五步工作流程

```
Seed Text
    │
    ▼
[Step 1] Graph Build ──────── Entity extraction → Knowledge Graph → Hidden actor discovery
    │
    ▼
[Step 2] Environment Setup ── Agent generation → Personality profiles → Memory seeding
    │
    ▼
[Step 3] Simulation ─────────  OASIS engine → Belief dynamics → Faction emergence → Macro feedback
    │
    ▼
[Step 4] Report ─────────────  AI synthesis → 18 XAI tools → PDF export → Share token
    │
    ▼
[Step 5] Interaction ────────  Agent interviews → Belief inspection → Narrative dossier
```

**[EN]**
Each step is stateful and independently resumable. Sessions persist in SQLite so you can revisit any simulation, re-inject shocks, fork branches, or re-generate reports without re-running the full pipeline.

**[繁中]**
每個步驟都有狀態且可獨立恢復。會話持久化在 SQLite 中，你可以重訪任何模擬、重新注入衝擊、分叉分支或重新生成報告，而無需重跑整個流程。

---

## System Architecture · 系統架構

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Browser Client                               │
│   Vue 3 + Vite (:5173)                                              │
│   ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐ │
│   │  Home    │ │ Process  │ │  SimRun  │ │  Report  │ │Settings │ │
│   │ (seed)   │ │(5 steps) │ │ (live)   │ │  (XAI)   │ │(config) │ │
│   └──────────┘ └──────────┘ └──────────┘ └──────────┘ └─────────┘ │
│        │ REST API + WebSocket (real-time progress)                  │
└────────┼────────────────────────────────────────────────────────────┘
         │
┌────────▼────────────────────────────────────────────────────────────┐
│                    FastAPI Gateway (:5001)                           │
│                                                                     │
│  /graph      /simulation    /report    /settings    /auth    /ws   │
│  KG build    Create·Start   AI report  Runtime cfg  JWT      WSS   │
│  Query       Shock·Branch   PDF·Share  API keys     Users    Live  │
│  Temporal    Cleanup        XAI tools  LLM models           Feed  │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              Service Layer  (50+ services)                   │   │
│  │  EntityExtractor · ImplicitStakeholderService · KGAgentFact  │   │
│  │  CognitiveAgentEngine · BeliefSystem · BeliefPropagation     │   │
│  │  ConsensusDebateEngine · EmergenceTracker · MacroController  │   │
│  │  SwarmEnsemble · AutoForkService · MonteCarloEngine          │   │
│  │  ReportAgent · InterviewEngine · NarrativeAnalyst            │   │
│  │  RuntimeSettingsStore · CostTracker · DuckDBAnalytics        │   │
│  └──────────────────────────┬──────────────────────────────────┘   │
└─────────────────────────────┼───────────────────────────────────────┘
                              │
         ┌────────────────────┼──────────────────────┐
         │                    │                      │
┌────────▼──────┐  ┌──────────▼──────────┐  ┌───────▼────────────┐
│  OASIS Engine │  │   SQLite WAL        │  │   LanceDB          │
│  (subprocess) │  │   (60+ tables)      │  │   (vector store)   │
│               │  │                     │  │   384-dim embed    │
│  Per-round    │  │  simulation_sessions│  │   Agent memories   │
│  concurrency  │  │  agent_profiles     │  │   World context    │
│  hooks via    │  │  kg_nodes/edges     │  │   Persona templates│
│  JSONL IPC    │  │  belief_states      │  │                    │
│               │  │  emergence_metrics  │  │   Semantic search  │
│  SIGTERM →    │  │  app_settings       │  │   for cognition    │
│  SIGKILL      │  │  ...57 more         │  │                    │
└───────────────┘  └─────────────────────┘  └────────────────────┘
```

---

## Technical Deep Dive · 技術深度解析

### Actor Discovery Pipeline · 演員發現流程

**[EN]** MurmuraScope discovers simulation actors in 4 recursive stages, each from a different angle, to ensure no significant stakeholder is missed.

**[繁中]** MurmuraScope 透過 4 個遞進階段從不同角度發現模擬演員，確保不遺漏任何重要持份者。

```
Seed Text
    │
    ├─[Stage 1: EntityExtractor]──────────────────────────────────────
    │   Explicit entities + relationships from raw text               
    │   _ALIAS_MAP deduplication (e.g. "B站" ↔ "嗶哩嗶哩")           
    │   → KG nodes + edges                                           
    │                                                                  
    ├─[Stage 2: ImplicitStakeholderService]───────────────────────────
    │   LLM asks: "Who profits? suffers? finances? retaliates?"       
    │   2nd and 3rd order affected stakeholders                       
    │   → up to 50 implied actors (source="implicit_discovery")      
    │                                                                  
    ├─[Stage 3: ScenarioGenerator]────────────────────────────────────
    │   Independent LLM pass to catch Stage 2 misses                 
    │   Different reasoning angle, same seed                         
    │   → up to 30 additional actors                                 
    │                                                                  
    └─[Stage 4: KGAgentFactory]───────────────────────────────────────
        Invents background agents when target_count > eligible_nodes  
        Domain-consistent anonymous actors (citizens, journalists…)   
        → dynamic fill to reach simulation preset count              

Total implied actors per scenario: 50 + 30 + dynamic = up to MASSIVE (3,000)
```

**Knowledge Firewall · 知識防火牆**

Every LLM prompt across all 4 stages embeds this constraint:

```
KNOWLEDGE FIREWALL — CRITICAL:
You must reason ONLY from the provided seed text. Do NOT use training
knowledge about events that occur AFTER the time horizon in the seed.
```

This prevents anachronistic reasoning — seed text from 1850 won't produce agents who "know" about 1900 events.

---

### Cognitive Agent Model · 認知 Agent 模型

**[EN]** Every agent carries a multi-dimensional psychological profile generated by KGAgentFactory:

**[繁中]** 每個 agent 都攜帶由 KGAgentFactory 生成的多維心理檔案：

```
Agent Profile
├── Identity
│   ├── entity_type (government / corporation / individual / media / ngo…)
│   ├── political_stance  [0.0=establishment ↔ 1.0=progressive]
│   ├── nationality
│   └── goals[]            (revised by LLM when belief < 0.15 or > 0.85)
│
├── Big Five Personality   (openness, conscientiousness, extraversion,
│   agreeableness, neuroticism)  →  drives deliberation style
│
├── Attachment Style       (secure / anxious / avoidant / disorganised)
│   →  shapes trust formation speed
│
├── Cognitive Fingerprint
│   ├── risk_tolerance     [0,1]
│   ├── information_processing  (analytical / intuitive / narrative)
│   ├── in_group_bias      [0,1]
│   └── cognitive_dissonance_threshold
│
└── Activation
    ├── activity_level     [0,1]  (stakeholders ≥ 0.8)
    └── is_stakeholder     (uses stronger LLM model)
```

---

### Belief Dynamics · 信念動力學

**[EN]** MurmuraScope uses genuine Bayesian belief revision, not simple linear averaging:

**[繁中]** MurmuraScope 使用真正的貝葉斯信念修正，而非簡單的線性平均：

```
Belief Update Flow (per round per agent)
─────────────────────────────────────────

1. Feed ingestion
   agent_feeds table → feed_ranker.py (recency × salience × source trust)

2. Bayesian core update
   prior_prob = _stance_to_prob(current_belief)   # [-1,+1] → [0,1]
   likelihood = compute_likelihood_ratio(evidence)
   posterior  = _bayesian_core(prior_prob, likelihood)
   new_belief = _prob_to_stance(posterior)         # [0,1] → [-1,+1]

3. Propagation (every round)
   BeliefPropagationEngine.cascade()
   → 1-hop embedding similarity pull
   → dampens extremism reinforcement (NOT convergence)

4. Consensus debate (every 3 rounds, stakeholders only)
   ConsensusDebateEngine: cross-faction structured debate
   → delta cap ±0.15/exchange, ±0.20/round/topic
   → results persisted to belief_states table

5. Cognitive dissonance
   When new belief conflicts sharply with memory/goals
   → cognitive_dissonance table + emotional cascade
```

---

### Simulation Hooks Architecture · 模擬鉤子架構

**[EN]** Each simulation round executes a structured concurrency pipeline. Hooks are grouped to maximise parallelism while respecting causality:

**[繁中]** 每個模擬回合執行一個結構化並發流水線。鉤子按組分組以最大化並行性，同時保持因果關係：

```
Round N
│
├── Pre-Group 1 (sequential)
│   ├── Feed ranking (all modes)
│   └── World event generation† (kg_driven)
│
├── Group 1 (parallel, asyncio.gather)
│   ├── Agent memory update
│   ├── Trust dynamics update
│   ├── Emotional state update*
│   └── Relationship state†*
│
├── Group 2 (sequential, causality-ordered)
│   ├── Decision making (HK: rule 90% + LLM 10% / kg: full LLM)
│   ├── Side effects processing
│   ├── Belief update*
│   ├── Consumption model
│   ├── Strategic planning†
│   ├── Stochastic LLM deliberation† (all activated agents)
│   ├── Consensus debate†  (every 3 rounds)
│   └── Belief propagation†
│
└── Group 3 (periodic, fire-and-forget with 60s timeout)
    ├── Echo chamber detection  (every 3 rounds)*
    ├── Network evolution       (every 3 rounds)*
    ├── Virality scoring        (every 3 rounds)*
    ├── Macro feedback          (every 5 rounds)
    ├── KG evolution            (every 3 rounds)
    ├── Polarisation snapshot   (every 5 rounds)
    ├── TDMI emergence metrics  (every 5 rounds)
    ├── Faction + tipping pts†  (every 3 rounds)
    └── Relationship lifecycle†*(every 3 rounds)

* = requires emergence_enabled (STANDARD/DEEP/LARGE/MASSIVE)
† = kg_driven mode only
```

---

### Swarm Ensemble · 群體集成預測

**[EN]** For probabilistic forecasting, MurmuraScope forks the simulation at the point of maximum divergence:

**[繁中]** 對於概率預測，MurmuraScope 在最大分歧點分叉模擬：

```
Phase A: Single full LLM run
    │
    ├── Every round: measure JSD (Jensen-Shannon Divergence) between belief distributions
    │
    └── Fork at JSD ≥ 0.225 (50% of simulation or configured fork_round)
          │
          ├── Copy 8 state tables from Phase A snapshot
          │   (agent_memories, belief_states, simulation_actions,
          │    emotional_states, agent_relationships, kg_edges,
          │    cognitive_dissonance, kg_nodes)
          │
          └── Phase B: N independent lite replicas (default 50)
                │   (rule-based hooks → 0 LLM cost)
                │
                └── Classify trajectories →
                      disruption_polarised  │ disruption_converged
                      fragmentation         │ consensus
                      stalemate
                      │
                      └── ProbabilityCloud
                            outcome_distribution[]
                            belief_cloud {p25, median, p75}
                            Wilson CIs
```

---

### Macroeconomic Integration · 宏觀經濟整合

**[EN]** MurmuraScope tracks 10 macro indicators and updates them bidirectionally with agent sentiment:

**[繁中]** MurmuraScope 追蹤 10 個宏觀指標，並與 agent 情緒雙向更新：

```
Macro Indicators: gdp_growth · inflation_rate · unemployment_rate ·
                  hsi_level · ccl_index · fed_rate · consumer_confidence ·
                  geopolitical_risk · birth_rate · trade_balance

                  ┌──────────────────────────────┐
                  │      MacroController         │
                  │                              │
Agent actions ───►│  apply_agent_actions_feedback │◄─── External data feed
(every 5 rounds)  │  (every 5 rounds)            │     (FRED + World Bank)
                  │                              │
                  │  Shock dual-path:            │
Shock API ───────►│  (a) narrative post in feeds │
                  │  (b) direct macro field edit │
                  └──────────────────────────────┘
                          │
                          ▼
                  GARCH(1,1) volatility model
                  VAR/VECM forecasting
                  RetrospectiveValidator (walk-forward backtest)
```

---

### Settings & Runtime Configuration · 設定與運行時配置

**[EN]** All LLM models, API keys, and simulation defaults can be changed from the Settings page without restarting the server. Changes take effect on the next LLM call.

**[繁中]** 所有 LLM 模型、API keys 及模擬預設值均可從設定頁面更改，無需重啟服務器。更改在下一次 LLM 調用時立即生效。

```
.env (bootstrap defaults)
      │
      ▼ (startup)
app_settings table (SQLite)
      │
      ▼ load_from_rows()
RuntimeSettingsStore (in-memory dict)
      ▲
      │ PUT /api/settings
Settings Page (Vue)
      │
      ├── UI preferences ──► localStorage (instant, no API call)
      └── Backend settings ─► 500ms debounce ─► PUT /api/settings
                                                  │
                                                  ├─ write DB
                                                  └─ set_override() → in-memory

llm_client.py: get_agent_provider_model()
    → check RuntimeSettingsStore first
    → fallback to .env values
```

---

## Simulation Presets · 模擬預設

| Preset | Agents | Rounds | Emergence | Cost estimate | Use case |
|--------|--------|--------|-----------|---------------|----------|
| **Fast** | 100 | 15 | Off | ~$0.02 | Demo, quick test · 演示、快速測試 |
| **Standard** | 300 | 20 | On | ~$0.18 | General analysis · 一般分析 |
| **Deep** | 500 | 30 | On | ~$0.63 | Research · 研究 |
| **Large** | 1,000 | 25 | On | ~$1.89 | Large-scale · 大規模 |
| **Massive** | 3,000 | 20 | On | ~$5.40 | Stress test · 壓力測試 |
| **Custom** | up to 50,000 | up to 100 | On | varies | Any scale · 任意規模 |

---

## API Reference · API 參考

| Area | Endpoint | Method | Description |
|------|----------|--------|-------------|
| **Health** | `/api/health` | GET | Server health check |
| **Auth** | `/auth/register` | POST | Register new user |
| | `/auth/login` | POST | Login, returns JWT |
| | `/auth/me` | GET | Current user profile |
| **Graph** | `/graph/build` | POST | Seed text → Knowledge Graph |
| | `/graph/{id}` | GET | Full graph (nodes + edges) |
| | `/graph/{id}/temporal` | GET | Graph state at round N |
| | `/graph/analyze-seed` | POST | Preview actors before build |
| **Simulation** | `/simulation/quick-start` | POST | One-call full pipeline |
| | `/simulation/create` | POST | Create session + agents |
| | `/simulation/start` | POST | Start OASIS subprocess |
| | `/simulation/{id}/status` | GET | Live status + progress |
| | `/simulation/{id}/agents` | GET | All agent profiles |
| | `/simulation/{id}/shock` | POST | Inject mid-sim shock |
| | `/simulation/{id}/branch` | POST | Fork counterfactual |
| | `/simulation/{id}/swarm-ensemble` | POST | Run probability cloud |
| | `/simulation/{id}/auto-forks` | GET | Auto-fork results |
| | `/simulation/{id}/cleanup` | POST | Release resources |
| **Report** | `/report/{id}/generate` | POST | Generate AI report |
| | `/report/{id}/pdf` | GET | Download PDF |
| | `/report/{id}/share` | POST | Create share token |
| **Settings** | `/api/settings` | GET | Current config (keys masked) |
| | `/api/settings` | PUT | Update config (live effect) |
| | `/api/settings/test-key` | POST | Validate API key |
| **Emergence** | `/simulation/{id}/factions` | GET | Faction snapshot |
| | `/simulation/{id}/tipping-points` | GET | Detected tipping points |
| | `/simulation/{id}/emergence-metrics` | GET | TDMI + KNN MI scores |
| | `/simulation/{id}/multi-run` | POST | Zero-LLM ensemble |
| **Interview** | `/interview/{session_id}/agents` | GET | Interviewable agents |
| | `/interview/{session_id}/ask` | POST | Ask an agent a question |
| **Forecast** | `/forecast/{metric}` | GET | VAR/VECM forecast |
| | `/forecast/{metric}/backtest` | GET | Walk-forward backtest |
| **Validation** | `/validation/retrospective` | GET | Backtest vs actual data |
| | `/validation/cross-domain` | GET | Cross-domain scores |
| **WebSocket** | `/api/ws/progress/{id}` | WSS | Real-time simulation feed |

---

## Database Schema · 資料庫結構

**[EN]** 60+ tables organised into functional groups:

**[繁中]** 60+ 張資料表，按功能分組：

| Group · 分組 | Tables · 資料表 |
|-------------|----------------|
| **Session** | `simulation_sessions`, `scenario_branches`, `workspace_sessions` |
| **Agents** | `agent_profiles`, `agent_decisions`, `agent_memories`, `memory_triples`, `agent_relationships`, `agent_interviews`, `agent_goal_revisions`, `agent_consumption` |
| **Knowledge Graph** | `kg_nodes`, `kg_edges`, `kg_communities`, `kg_snapshots` |
| **Beliefs & Cognition** | `belief_states`, `cognitive_fingerprints`, `cognitive_dissonance`, `attachment_styles`, `debate_rounds`, `consensus_scores` |
| **Social Dynamics** | `simulation_actions`, `agent_feeds`, `social_sentiment`, `echo_chamber_snapshots`, `filter_bubble_snapshots`, `virality_scores`, `network_events` |
| **Macro & Economy** | `macro_scenarios`, `hk_data_snapshots`, `market_data`, `ensemble_results`, `validation_runs`, `calibration_results`, `scale_benchmarks` |
| **Emergence** | `emergence_metrics`, `faction_snapshots_v2`, `tipping_points`, `polarization_snapshots`, `emotional_states`, `world_events` |
| **Reports** | `reports`, `community_summaries` |
| **Auth & Workspaces** | `users`, `workspaces`, `workspace_members`, `comments` |
| **Seed Memory** | `seed_world_context`, `seed_persona_templates` |
| **Config** | `app_settings` (runtime key-value overrides) |

---

## Configuration · 配置

Copy `.env.example` to `.env`. Most settings can also be changed live in the **Settings page** (`/settings`).

**Required · 必需：**

| Variable | Description · 說明 |
|----------|---------------------|
| `OPENROUTER_API_KEY` | Agent LLM calls · Agent LLM 調用 |
| `GOOGLE_API_KEY` | Report generation · 報告生成 |
| `AUTH_SECRET_KEY` | JWT signing · JWT 簽名 (`openssl rand -hex 32`) |

**LLM Models · LLM 模型：**

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_LLM_PROVIDER` | `openrouter` | Provider for agent decisions |
| `AGENT_LLM_MODEL` | `deepseek/deepseek-v3.2` | Model for stakeholder agents |
| `AGENT_LLM_MODEL_LITE` | *(falls back to above)* | Cheaper model for background agents |
| `LLM_PROVIDER` | `google` | Provider for reports |
| `GOOGLE_REPORT_MODEL` | `gemini-3.1-pro-preview` | Model for report generation |

**Simulation · 模擬：**

| Variable | Default | Description |
|----------|---------|-------------|
| `SIMULATION_CONCURRENCY_LIMIT` | `50` | Max parallel LLM requests per round |
| `SESSION_COST_BUDGET_USD` | `5` | Warning threshold per session |
| `SESSION_COST_HARD_CAP_USD` | `10` | Pause threshold per session |
| `SUBPROCESS_MEMORY_LIMIT_MB` | `2048` | Kill OASIS if RAM exceeds this |

**Optional data feeds · 可選資料源：**

| Variable | Default | Description |
|----------|---------|-------------|
| `FRED_API_KEY` | *(empty)* | US Federal Reserve economic data |
| `EXTERNAL_FEED_ENABLED` | `false` | Live macro data from FRED + World Bank |
| `EXTERNAL_FEED_REFRESH_ROUNDS` | `10` | Refresh interval (rounds) |

---

## Tech Stack · 技術棧

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Backend** | Python 3.11, FastAPI, Uvicorn | API server, async handlers |
| **ORM / DB** | aiosqlite, SQLite WAL | Async database access, 60+ tables |
| **Validation** | Pydantic V2 (frozen models) | Request/response schemas, immutability |
| **Frontend** | Vue 3, Vite, Vue Router | SPA, component-based UI |
| **Visualisation** | D3.js, Recharts, Plotly | Force graphs, charts, heatmaps |
| **Simulation** | OASIS (subprocess) | Multi-agent interaction engine |
| **Vector DB** | LanceDB (embedded) | 384-dim multilingual agent memories |
| **Analytics** | DuckDB (read-only attach) | Fast SQL analytics over SQLite |
| **LLM Routing** | OpenRouter, Google, OpenAI, Anthropic | Multi-provider LLM access |
| **Embeddings** | `paraphrase-multilingual-MiniLM-L12-v2` | 384-dim sentence embeddings |
| **Forecasting** | SciPy, NumPy (custom VAR/GARCH) | Time series, volatility modelling |
| **Testing** | pytest (2700+ unit, 134 integration) | Full test coverage |
| **Observability** | OpenTelemetry + Jaeger (optional) | Distributed tracing |

---

## Project Structure · 項目結構

```
MurmuraScope/
│
├── backend/
│   ├── app/
│   │   ├── api/           # FastAPI routers (20 modules)
│   │   │   ├── graph.py          # Knowledge graph endpoints
│   │   │   ├── simulation.py     # Simulation lifecycle
│   │   │   ├── report.py         # AI report generation
│   │   │   ├── settings.py       # Runtime config API
│   │   │   ├── auth.py           # JWT authentication
│   │   │   ├── ws.py             # WebSocket progress feed
│   │   │   └── ...
│   │   ├── services/      # 140+ business logic modules
│   │   │   ├── cognitive_agent_engine.py
│   │   │   ├── belief_system.py
│   │   │   ├── swarm_ensemble.py
│   │   │   ├── macro_controller.py
│   │   │   ├── runtime_settings.py
│   │   │   └── ...
│   │   ├── models/        # Pydantic models (all frozen)
│   │   ├── utils/         # db.py, llm_client.py, prompt_security.py
│   │   └── domain/        # 7 built-in domain packs + presets
│   ├── database/
│   │   └── schema.sql     # 60+ table definitions
│   └── tests/             # 2700+ unit + 134 integration tests
│
├── frontend/
│   └── src/
│       ├── views/         # Page components
│       │   ├── Home.vue          # Seed text entry
│       │   ├── Process.vue       # 5-step workflow
│       │   ├── SimulationRun.vue # Live simulation view
│       │   ├── Report.vue        # AI report + XAI
│       │   ├── Settings.vue      # Runtime configuration
│       │   └── ...
│       ├── components/    # 35+ reusable components
│       ├── api/           # API client layer
│       └── composables/   # useSettings.js, useOnboarding.js
│
├── scripts/
│   └── quickstart.sh      # Guided first-time setup + launcher
├── Makefile               # All dev commands
├── docker-compose.yml     # Production deployment
└── .env.example           # Configuration template
```

---

## Use Cases · 應用場景

| Scenario · 場景 | What to seed · 輸入內容 | What you get · 輸出結果 |
|----------------|------------------------|------------------------|
| **Breaking News Analysis** 突發新聞分析 | News article text | Faction responses, belief spread map, outcome probabilities |
| **Geopolitical Forecasting** 地緣政治預測 | Intelligence brief | Actor coalition dynamics, escalation risk score, tipping points |
| **Policy Impact Assessment** 政策影響評估 | Policy document | Stakeholder reactions, macro indicator shifts, opposition emergence |
| **Crisis Communication** 危機傳播 | Crisis scenario | Message penetration by demographic, counter-narrative effectiveness |
| **Competitive Intelligence** 競爭情報 | Market news | Company agent strategies, customer sentiment trajectories |
| **Literary / Historical** 文學 / 歷史 | Novel chapter / historical document | Character belief dynamics, emergent alliances, narrative forks |
| **Academic Research** 學術研究 | Research hypothesis | Agent-based model with reproducible ensemble statistics |

---

## Limitations · 限制

**[EN]** MurmuraScope is a research and exploration tool. Please interpret outputs accordingly:

**[繁中]** MurmuraScope 是一個研究和探索工具。請相應地解讀輸出：

| Suitable for · 適合 | Not suitable for · 不適合 |
|--------------------|--------------------------|
| Scenario exploration and what-if analysis | Real-money financial trading decisions |
| Policy impact assessment and research | Actuarial or regulatory compliance reporting |
| Educational simulation | Real-time production decision systems |
| Competitive intelligence framing | Legal or medical advice |
| Hypothesis testing with ensemble validation | High-stakes predictions without expert review |

---

## Testing · 測試

```bash
make test               # Unit tests only (~2700 tests, ~20s)
make test-int           # Integration tests (~134 tests)
make test-all           # Full suite (~65s)
make test-cov           # Unit + HTML coverage report (htmlcov/)
make test-cov-full      # Full suite + coverage
make test-file F=test_belief_system    # Single file
make test-changed       # Only tests for git-changed files
```

Tests are auto-classified as unit or integration based on fixtures used. Integration tests require a live SQLite DB and are excluded from the default `make test` run.

---

## License · 許可證

**Prosperity Public License 2.0.0**

- **Non-commercial:** Free for personal use, academic research, and non-profit projects.
- **Commercial:** Requires a separate commercial license for business or revenue-generating use.

**非商業用途：** 個人使用、學術研究及非牟利項目免費。
**商業用途：** 商業或盈利性使用需要獨立商業授權。

Copyright © 2026 destinyfrancis. All rights reserved.
