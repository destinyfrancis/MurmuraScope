# MurmuraScope

A universal prediction engine that turns any text into a runnable social simulation.

Drop in a news article, novel excerpt, or geopolitical brief — the engine automatically extracts actors, generates agents with distinct personalities and beliefs, runs the simulation, and outputs probabilistic forecasts with confidence intervals.

---

## What it does

**Step 1 — Paste text.** The engine reads seed text, extracts entities and relationships into a knowledge graph, and generates up to 50 implied actors you didn't mention explicitly.

**Step 2 — Agents appear.** Each agent gets Big Five personality traits, a three-dimensional emotional state, a Bayesian belief system, and a cognitive fingerprint. No manual configuration.

**Step 3 — Simulation runs.** Agents interact across rounds: debate, form factions, update beliefs, propagate information. LLM deliberation for key stakeholders; rule-based lite hooks for background agents (cost-efficient).

**Step 4 — Forecasts with numbers.** Monte Carlo ensemble (up to 500 trials), AutoARIMA + VAR time-series models, stationarity-checked before fitting, GARCH(1,1) for volatility during crises. Walk-forward backtesting with CRPS, Brier skill, MAPE, Pearson r.

**Step 5 — Explore.** Interview any agent in character. Branch the simulation at any tipping point. Inject shocks. Compare counterfactuals.

---

## Quickstart

```bash
cp .env.example .env        # add OPENROUTER_API_KEY + GOOGLE_API_KEY
docker compose up -d        # frontend :8080 · backend :5001
```

Or locally:
```bash
cd backend && uvicorn run:app --reload --port 5001
cd frontend && npm run dev   # :5173
```

---

## Key commands

```bash
make test           # unit tests (~2700 tests, ~20s)
make test-int       # integration tests
make test-cov       # coverage report → htmlcov/
make test-changed   # only tests for files you changed
make stop           # kill all simulation processes
make docker-logs    # follow container logs
```

---

## Architecture

```
backend/app/
  api/            FastAPI routers
  services/       50+ business logic services
  models/         Pydantic (frozen) + frozen dataclasses
  utils/          db.py · llm_client.py · duckdb_analytics.py
  domain/         7 built-in domain packs

frontend/src/
  views/          5-step workflow UI
  components/     35+ Vue components
  api/            Typed API client layer
```

### Simulation modes

| Mode | Trigger | Agents |
|------|---------|--------|
| `kg_driven` | Any non-HK seed | LLM-generated via KGAgentFactory |
| `hk_demographic` | HK keywords in seed | HK Census AgentFactory |

### Simulation presets

| Preset | Agents | Rounds |
|--------|--------|--------|
| FAST | 100 | 15 |
| STANDARD | 300 | 20 |
| DEEP | 500 | 30 |
| LARGE | 1,000 | 25 |
| custom | up to 50,000 | up to 100 |

---

## Statistical / econometric layer

| Feature | Implementation |
|---------|---------------|
| Stationarity | ADF + KPSS dual test before every VAR fit; auto-differencing if I(1)/I(2) |
| VAR / VECM | Johansen cointegration test; VECM when cointegrated, VAR otherwise |
| GARCH(1,1) | Bollerslev (1986) MLE; fits automatically when ARCH effects detected |
| Monte Carlo | 500-trial LHS + t-Copula; GARCH-adjusted CIs during volatility clustering |
| TDMI | Kraskov KNN estimator; permutation null-model (200 shuffles, 95th pct) |
| Brier skill | Climatological baseline p×(1-p) from dataset prevalence |
| CRPS | Continuous Ranked Probability Score for probabilistic forecast evaluation |
| Backtesting | Walk-forward k-fold; _FoldScopedCoefficients prevents look-ahead bias |

---

## Tech stack

| Layer | Stack |
|-------|-------|
| Backend | Python 3.11, FastAPI, aiosqlite (SQLite WAL) |
| Analytical queries | DuckDB (read-only overlay on SQLite) |
| Frontend | Vue 3, Vite, TypeScript |
| Vector DB | LanceDB (384-dim multilingual embeddings) |
| LLMs — agents | OpenRouter (`AGENT_LLM_MODEL`) |
| LLMs — reports | Google AI (`GOOGLE_REPORT_MODEL`) |
| Observability | OpenTelemetry → Jaeger (`--profile observability`) |

---

## Environment variables

```env
OPENROUTER_API_KEY=         # agent LLM calls
GOOGLE_API_KEY=             # report generation

AGENT_LLM_MODEL=google/gemini-3.1-flash-lite-preview
AGENT_LLM_MODEL_LITE=       # background agents (cheaper; falls back to above)
GOOGLE_REPORT_MODEL=gemini-3.1-pro-preview

SESSION_COST_BUDGET_USD=5   # warning threshold
SESSION_COST_HARD_CAP_USD=10 # hard pause
SUBPROCESS_MEMORY_LIMIT_MB=2048

EXTERNAL_FEED_ENABLED=false
OTEL_ENABLED=false
```

---

## Development notes

- **Python version**: 3.10 or 3.11 only. OASIS does not support 3.12+.
- **Immutability**: all models use `frozen=True` dataclasses or `ConfigDict(frozen=True)`. Use `dataclasses.replace()`, never mutate.
- **DB write pattern**: all simulation writes go through `BatchWriter` → `executemany()` per round. Analytical reads use `DuckDBAnalytics` (zero-copy SQLite scanner).
- **LLM singletons**: never instantiate `LLMClient` per-call. Use `_get_llm_client()` / `_get_xai_llm()`.
- **Column names**: `agent_memories` uses `memory_text` (not `content`), `salience_score` (not `salience`). `kg_nodes` uses `session_id` (not `graph_id`), `title` (not `name`).

---

## Licence

Proprietary. All rights reserved.
