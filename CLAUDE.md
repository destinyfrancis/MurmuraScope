# MurmuraScope — CLAUDE.md

## 引擎介紹

**MurmuraScope** 係一個**通用預測引擎**，結合多智能體系統、知識圖譜、LLM 同宏觀經濟預測，模擬任何場景對各種衝擊的集體反應。

掉任何 seed text 入去（紅樓夢、伊朗戰爭、哈利波特、公司競爭等），引擎自動推斷 agents、decisions、metrics、shocks，無需手動配置。

---

## Tech Stack

- **Backend:** FastAPI (Python 3.11), aiosqlite, Pydantic V2, tiktoken
- **Frontend:** Vue 3 + Vite (port 5173 → proxies backend 5001); `src/api/*.js` API layer
- **LLMs:** Agents: `AGENT_LLM_PROVIDER` (default openrouter) · Reports: `LLM_PROVIDER` (default google)
- **Simulation:** OASIS Agentic Engine (subprocess, JSONL IPC)
- **DB:** SQLite WAL at `data/murmuroscope.db` (60+ tables) · `get_db()` from `backend.app.utils.db`
- **Analytics:** DuckDB (read-only attach) + LanceDB (384-dim embeddings)
- **Python:** REQUIRES 3.10 or 3.11 for OASIS engine. Features auto-discovery for compatible binaries and graceful UI degradation (disables Simulation step) if run on Python 3.12+.

---

## Key Commands

```bash
# ── Local dev ──────────────────────────────────────────────────────────────
make quickstart          # First-time: install deps + start + open browser
make start               # Daily dev: start backend (5001) + frontend (5173)
make backend             # Backend only
make frontend            # Frontend only
make stop                # Kill all uvicorn + OASIS processes

# ── Docker & Deployment ────────────────────────────────────────────────────
curl -fsSL https://raw.githubusercontent.com/destinyfrancis/MurmuraScope/main/scripts/install.sh | bash  # 1-minute bootstrap
docker compose --profile demo up -d            # Demo mode (No API keys required)
cp .env.example .env && docker compose up -d   # Live mode (Requires API key)
docker compose --profile observability up -d   # + Jaeger at 16686

# ── Testing ─────────────────────────────────────────────────────────────────
make test                # Unit only (~2700 tests, ~20s)
make test-int            # Integration only
make test-all            # Full suite (~65s)
make test-cov            # Unit + HTML coverage report (htmlcov/)
make test-file F=test_belief_system
make test-changed        # Only tests for git-changed files
```

---

## Architecture

```
backend/
  app/api/          # FastAPI routers (graph, simulation, report, auth, settings, ws…)
  app/domain/       # 7 DomainPacks + locales (zh-HK, en-US)
  app/services/     # 50+ business-logic services
  app/models/       # Pydantic (frozen) + frozen dataclasses
  app/utils/        # db.py, llm_client.py, logger.py, runtime_settings.py, prompt_security.py
  database/         # schema.sql (60+ tables)
  prompts/          # LLM prompt templates
  tests/            # pytest unit + integration
frontend/
  src/views/        # Home, Process, Workspace, Settings, GraphExplorer, GodViewTerminal…
  src/components/   # 35+ components
  src/api/          # graph.js, simulation.js, report.js, settings.js
  src/composables/  # useSettings.js, useOnboarding.js…
```

---

## 5-Step Workflow

```
Step 1: Graph Build → Step 2: Env Setup → Step 3: Simulation → Step 4: Report → Step 5: Interaction
```

- **Step 1:** Seed text → EntityExtractor → KG → ImplicitStakeholderService (≤50 implied actors) → MemoryInitializationService (LanceDB `swc_` tables)
- **Step 2:** ZeroConfigService mode-detect → KGAgentFactory → `hydrate_session_bulk()` → scenario config
- **Step 3:** SimulationWorker enqueues job → enforces `MAX_CONCURRENT_SIMULATIONS` (default 3) → OASIS subprocess + structured concurrency hooks (Group 1/2/3) + heartbeat tracking
- **Step 4:** 3-phase ReACT report (18 XAI tools); PDF export + token sharing
- **Step 5:** InterviewEngine (memory-augmented roleplay) + NarrativeAnalyst dossier

### Simulation Modes

| Mode | Trigger | Agent Source | Decision Space |
|------|---------|-------------|---------------|
| `hk_demographic` | HK keywords in seed | HK Census AgentFactory | Hardcoded DecisionType enum |
| `kg_driven` | Non-HK seed | KGAgentFactory (LLM) | ScenarioGenerator (LLM) |

---

## Actor Discovery Pipeline (4-Stage)

| Stage | Service | Output |
|-------|---------|--------|
| 1 | `EntityExtractor` | Explicit KG nodes + edges; `_ALIAS_MAP` dedup |
| 2 | `ImplicitStakeholderService` | ≤50 hidden actors (best-effort, never raises); `source="implicit_discovery"` |
| 3 | `ScenarioGenerator` | ≤30 additional implied actors; deduped before injection |
| 4 | `KGAgentFactory` | Invents background agents when `target_count > eligible_nodes` |

**Knowledge Firewall** embedded in every prompt: LLM must reason ONLY from seed text, not training knowledge of post-seed events.

---

## Key Services

| Service | Purpose |
|---------|---------|
| `SimulationRunner` | OASIS subprocess orchestration; hooks; `cleanup_session()` |
| `SimulationSubprocessManager` | `launch()`/`stop()`/`cleanup()`/`is_running()` — SIGTERM→SIGKILL |
| `SimulationWorker` | Polling Job Queue; `enqueue()`/`process()`; handles `interrupted` zombies |
| `OASISCompatibility` | `oasis_compatibility.py`: Graceful UI degradation if Python 3.12+ or OASIS missing |
| `ZeroConfigService` | `detect_mode_async()`: HK keyword fast-path + LLM fallback |
| `KGAgentFactory` | filter → profile → fingerprint; `create(graph_id)`; `mark_stakeholders()` |
| `CognitiveAgentEngine` | Stochastic LLM deliberation → `DeliberationResult`; Big Five + attachment |
| `BeliefSystem` | True Bayesian update via `bayesian_update()` + `_bayesian_core()` |
| `BeliefPropagationEngine` | Embedding cascade; dampens extremism (NOT convergence) |
| `ConsensusDebateEngine` | Cross-faction debate every 3 rounds; delta cap ±0.15/exchange |
| `SwarmEnsemble` | Phase A (1 LLM run) → fork → Phase B (N lite replicas) → ProbabilityCloud |
| `AutoForkService` | JSD ≥ 0.225 guard; max `min(5, max(2, round_count//10))` auto-forks |
| `MacroController` | Macro state + shocks + agent feedback every 5 rounds |
| `MonteCarloEngine` | 500-trial LHS + t-Copula |
| `RetrospectiveValidator` | Walk-forward backtest; `_FoldScopedCoefficients` prevents look-ahead bias |
| `RuntimeSettingsStore` | `runtime_settings.py`: in-memory override store; `GET/PUT /api/settings` |
| `CostTracker` | Per-session USD accumulation; hard cap → `cost_pause` WebSocket event |
| `InterviewEngine` | Post-sim roleplay with memory-augmented agents |
| `NarrativeAnalyst` | Chronological dossier from simulation timeline |
| `DuckDBAnalytics` | Read-only SQL analytics over SQLite |

---

## Simulation Hooks (Structured Concurrency)

`HookConfig.emergence_enabled`: FAST → `False`, STANDARD/DEEP → `True`.

- **Pre-Group-1:** feed ranking; kg_driven: world event generation†
- **Group 1 (parallel):** memories, trust, emotional state*, relationship states†*
- **Group 2 (sequential):** decisions, belief update*; kg_driven: strategic planning† + LLM deliberation† + debate†(3) + propagation†
- **Group 3 (periodic):** echo chambers(3), virality*(3), macro(5), polarization(5), TDMI(5); kg_driven: faction+tipping(3)†, relationship lifecycle(3)†*

`*` emergence_enabled only · `†` kg_driven only · `(N)` every N rounds

---

## Simulation Presets

| Preset | Agents | Rounds | Emergence | Use |
|--------|--------|--------|-----------|-----|
| FAST | 100 | 15 | Off | Demo, quick test |
| STANDARD | 300 | 20 | On | General analysis |
| DEEP | 500 | 30 | On | Research |
| LARGE | 1,000 | 25 | On | Large-scale |
| MASSIVE | 3,000 | 20 | On | Stress test |
| custom | ≤50,000 | ≤100 | On | Any scale |

---

## Database Tables (Groups)

| Group | Tables |
|-------|--------|
| Core | `simulation_sessions`, `simulation_jobs`, `agent_profiles`, `kg_nodes`, `kg_edges`, `kg_communities` |
| Simulation | `simulation_actions`, `agent_memories`, `agent_interviews`, `memory_triples`, `agent_relationships`, `agent_decisions` |
| Economy | `hk_data_snapshots`, `market_data`, `macro_scenarios`, `ensemble_results`, `validation_runs` |
| Social | `social_sentiment`, `echo_chamber_snapshots`, `news_headlines` |
| Emergence | `network_events`, `agent_feeds`, `belief_states`, `emotional_states`, `polarization_snapshots`, `emergence_metrics` |
| Auth | `users`, `workspaces`, `workspace_members`, `comments` |
| Cognitive Theater | `cognitive_fingerprints`, `world_events`, `faction_snapshots_v2`, `tipping_points`, `debate_rounds` |
| Config | `app_settings` (runtime key-value store for Settings page) |

---

## API Endpoints (Summary)

| Area | Key Endpoints |
|------|--------------|
| Auth | `POST /auth/register`, `/login`, `GET /auth/me` |
| Graph | `POST /graph/build`, `GET /{id}`, `GET /{id}/temporal?round=N` |
| Simulation | `POST /simulation/quick-start`, `/create`, `/start`; `GET /{id}/status`; `GET /admin/queue`; `POST /admin/jobs/{id}/cancel` |
| Report | `POST /report/{id}/generate`, `GET /report/{id}/pdf`, `POST /{id}/share` |
| Settings | `GET /api/settings`, `PUT /api/settings`, `POST /api/settings/test-key` |
| Forecast | `GET /forecast/{metric}`, `/{metric}/backtest` |
| Cognitive Theater | `GET /{id}/factions`, `/{id}/tipping-points`, `/{id}/multi-run` |
| Swarm | `POST /simulation/{id}/swarm-ensemble`, `GET /{id}/auto-forks` |
| Domain Packs | `GET /api/domain-packs`, `POST /generate`, `POST /save` |

---

## LLM Configuration

Settings page (`/settings`) or `.env` (fallback). Runtime overrides stored in `app_settings` DB table, loaded into `RuntimeSettingsStore` at startup — no server restart needed.

```
Agents:  AGENT_LLM_PROVIDER=openrouter | AGENT_LLM_MODEL=deepseek/deepseek-v3.2
         AGENT_LLM_MODEL_LITE=<cheaper>  # background agents
Reports: LLM_PROVIDER=google | GOOGLE_REPORT_MODEL=gemini-3.1-pro-preview
Cost:    500 agents × 30 rounds ≈ $1.89
```

`get_agent_provider_model()` / `get_report_provider_model()` in `llm_client.py` — check `RuntimeSettingsStore` first, fallback to env.

---

## Code Style (ENFORCED)

- **Immutable:** frozen dataclasses + `ConfigDict(frozen=True)`, `dataclasses.replace()` only
- **File size:** 200–400 lines typical, 800 max
- **Async:** all handlers async, all DB via aiosqlite
- **Errors:** handle explicitly; `detail="Internal server error"` in responses (never `str(exc)`)
- **Prompt injection:** ALL user text → `sanitize_seed_text()` / `sanitize_scenario_description()` in `prompt_security.py`

---

## Known Patterns & Gotchas

**DB columns** (wrong names → silent OperationalError):
- `agent_memories`: `memory_text` (NOT `content`), `salience_score` (NOT `salience`)
- `kg_edges`: `source_id`/`target_id`, `session_id` (NOT `graph_id`), `relation_type` (NOT `label`)
- `kg_nodes`: `session_id` (NOT `graph_id`), `title` (NOT `name`)
- `news_headlines`: `title` (NOT `headline`)
- `agent_profiles`: `political_stance` + `tier` added via ALTER TABLE at runtime (NOT in schema.sql)
- `simulation_sessions`: `sim_mode` (NOT `mode`); test inserts need `name`, `llm_provider`, `sim_mode`
- `simulation_actions`: `oasis_username` is NOT NULL — always include in test inserts

**LLM Client:**
- Never instantiate per-call — use `_get_llm_client()`, `_get_xai_llm()`, `_get_emergence_llm()` singletons
- `chat()` → `LLMResponse` (access `.content`); `chat_json()` → raw `dict` — different return types, different mocks
- Patch `_get_xai_llm` / `_get_llm_client` directly in tests (NOT the LLMClient class)

**Simulation:**
- `KG Node IDs`: MUST prefix `{graph_id[:8]}_`; implicit actors use `{prefix}_imp_{slug}`
- `active_metrics` is `dict[str, float]` — NEVER a list
- `_run_dry()` caps at 3 rounds EXCEPT `lite_ensemble=True` (runs all rounds)
- `embed_single()` is sync — wrap with `asyncio.to_thread()` in async methods
- `keep_alive_for_report(session_id)` BEFORE finally block; `release_after_report()` in report API
- `FastAPI route ordering:` static paths BEFORE parameterized (`/quick-start` before `/{id}/`)
- `SimulationSubprocessManager`: use `launch()`/`stop()`/`cleanup()` — never access subprocess dict directly
- Stochastic activation: NO fixed tier budget; stakeholders get floor 0.8; all activated agents use LLM
- `SwarmEnsemble` Phase B copies 8 tables from Phase A up to `fork_round`

**Auth / Security:**
- `AUTH_SECRET_KEY` missing in production → `SystemExit` at startup; debug mode uses random fallback
- Rate limits: global 120/min; login 5/min, register 3/min
- `/{id}/shock` and `/{id}/resume` require auth (`Depends(get_optional_user)`)
- SSRF protection: `llm_base_url` rejects non-https, loopback, RFC-1918

**Forecasting:**
- `VARForecaster`: ADF + KPSS dual-test; auto-difference up to d=2; returns `tuple[dict, int, bool]`
- `GARCH(1,1)`: persistence (α+β) < 1 required; returns None if fit fails
- `ValidationReporter`: 30% directional + 30% |Pearson r| + 20% (1-MAPE) + 20% Brier skill

**Settings (new):**
- `RuntimeSettingsStore` (`runtime_settings.py`): module-level `_store` dict; `set_override()` updates in-memory immediately
- `PUT /api/settings` → writes to `app_settings` DB table + calls `set_override()` — next LLM call uses new value
- API keys masked as `sk-***last4` in GET response; never log raw keys

---

## Frontend Patterns & Gotchas

- **API envelope:** `{success, data, meta}` — access via `res.data?.data || res.data`
- **Settings:** `useSettings()` composable; UI prefs → localStorage immediately; backend settings → 500ms debounce → `PUT /api/settings`
- **Vue timers:** ALL `setInterval`/`setTimeout` MUST be cleared in `onUnmounted`
- **WebSocket:** `let isUnmounted = false`; check at TOP of `ws.onclose` before scheduling
- **Stale async:** capture `const capturedId` before `await`, check after
- **Vue `<script setup>`:** `defineProps()`/`defineEmits()` MUST be first statements; never mutate props
- **Markdown:** `marked.parse(text)` then `sanitize()` (strip `<script>`, `<iframe>`, `javascript:`)
- **D3 cleanup:** `d3.select(el).on('.zoom', null)` in teardown
- `political_stance` scale: `0.0 = 建制派`, `0.5 = 中立`, `1.0 = 民主派`

---

## Test Infrastructure

- **unit** (~2700 tests, ~20s): pure logic, no DB/HTTP
- **integration** (~134 tests): uses DB fixtures
- Auto-classified by `conftest.py::pytest_collection_modifyitems`
- **Embedding mock:** patch `EmbeddingProvider.embed_single` (NOT `LLMClient.embed_single`) with fixed 384-dim vector
- **Pipeline verification:** `test_pipeline_verification.py` — 15 tests covering full seed→sim→DB flow

---

## Domain Packs (7 Built-in)

`hk_city` (zh-HK), `us_markets` (en-US), `global_macro` (en-US), `public_narrative` (bi), `real_estate` (zh-HK), `company_competitor` (en-US), `community_movement` (zh-HK).
Custom: `POST /api/domain-packs/generate` → DomainBuilder.vue → `POST /save`.

---

## Debugging & Observability

```bash
tail -f logs/backend.log | grep "LLM "     # Per-call latency + cost
tail -f logs/backend.log | grep "hook="    # Per-round hook timing
```

- OTEL: `OTEL_ENABLED=true` + `--profile observability` → Jaeger at 16686
- Cost: `SESSION_COST_BUDGET_USD` (warning), `SESSION_COST_HARD_CAP_USD` (pause, default $10)
- Memory: `SUBPROCESS_MEMORY_LIMIT_MB` (default 2048) — watchdog kills over-limit processes

---

## MiroFish Reference

UI/UX references MiroFish 5-step workflow (GitHub: 666ghj/MiroFish).
Do NOT copy code — clean room implementation only (AGPL v3 risk).
