# MurmuraScope

**Universal Prediction Engine** — turn any text into a living simulation of collective behaviour.

Drop in any seed text (news, fiction, geopolitics, corporate rivalry) and the engine auto-generates agents, relationships, decision spaces, and macro metrics — no manual configuration required.

---

## Quick Start

### Option A — Local (Recommended for Development)

Requires Python 3.10/3.11 and Node.js 18+. Everything else is automated.

```bash
git clone <repo-url> && cd MurmuraScope
make quickstart
```

The wizard will:
- Create a Python virtual environment (`.venv311`) and install all dependencies
- Copy `.env.example` → `.env` and prompt for your `OPENROUTER_API_KEY`
- Start backend (`:5001`) + frontend (`:5173`) and open the browser automatically

After first-time setup, use `make start` for daily development.

### Option B — Docker

```bash
cp .env.example .env   # fill in API keys
docker compose up -d   # frontend at :8080, backend at :5001
```

Add `--profile observability` to also run Jaeger tracing at `:16686`.

---

## What It Does

MurmuraScope runs a **5-step pipeline**:

1. **Graph Build** — extracts entities and relationships from seed text into a Knowledge Graph. Discovers hidden stakeholders (up to 80 implied actors) beyond what's explicitly mentioned.
2. **Environment Setup** — generates agent personalities (Big Five + Cognitive Fingerprint), memories, and scenario configuration.
3. **Simulation** — runs OASIS multi-agent engine with Bayesian belief updates, faction dynamics, social contagion, and macro-economic feedback.
4. **Report** — produces an AI-synthesised report with 18 XAI tools, PDF export, and shareable token.
5. **Interaction** — interview any agent post-simulation; inspect their beliefs, memories, and relationships.

### Simulation Presets

| Preset | Agents | Rounds | Use |
|--------|--------|--------|-----|
| Fast | 100 | 15 | Demo, quick test |
| Standard | 300 | 20 | General analysis |
| Deep | 500 | 30 | Research |
| Large | 1,000 | 25 | Large-scale |
| Massive | 3,000 | 20 | Stress test |

---

## Key Commands

```bash
make start              # Start backend + frontend
make stop               # Kill all processes
make test               # Run unit tests (~20s)
make test-all           # Full test suite (~65s)
make test-cov           # Unit tests + coverage report
make docker-up          # Docker start
make docker-logs        # Stream Docker logs
```

---

## Configuration

Copy `.env.example` to `.env` and fill in your keys. Runtime settings (LLM models, API keys, simulation defaults) can also be changed in-app via **Settings** (`/settings`) without restarting the server.

### Minimum Required

| Variable | Description |
|----------|-------------|
| `OPENROUTER_API_KEY` | For agent LLM calls (simulation) |
| `GOOGLE_API_KEY` | For report generation |
| `AUTH_SECRET_KEY` | JWT signing key (generate: `openssl rand -hex 32`) |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_LLM_MODEL` | `deepseek/deepseek-v3.2` | Model for agent decisions |
| `GOOGLE_REPORT_MODEL` | `gemini-3.1-pro-preview` | Model for report generation |
| `SIMULATION_CONCURRENCY_LIMIT` | `50` | Max parallel LLM requests |
| `SESSION_COST_HARD_CAP_USD` | `10` | Pause simulation above this cost |
| `EXTERNAL_FEED_ENABLED` | `false` | Live macro data from FRED + World Bank |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11, FastAPI, aiosqlite, Pydantic V2 |
| Frontend | Vue 3, Vite, D3.js, Recharts |
| Simulation | OASIS (subprocess, JSONL IPC) |
| Database | SQLite WAL (60+ tables) |
| Analytics | DuckDB (read-only), LanceDB (384-dim embeddings) |
| LLM Routing | OpenRouter, Google Gemini, OpenAI, Anthropic |

---

## Architecture

```
Browser (Vue 3)
    │  REST + WebSocket
    ▼
FastAPI (port 5001)
    ├── /graph      Knowledge Graph build + query
    ├── /simulation  Create · Start · Shock · Branch
    ├── /report     AI report generation
    ├── /settings   Runtime LLM + API config
    └── /ws         Real-time simulation progress
         │
         ▼
OASIS Engine (subprocess)
    ├── Cognitive Agent Engine (Big Five + Bayesian belief)
    ├── Macro Controller (10 economic indicators)
    ├── Swarm Ensemble (Monte Carlo forks)
    └── Emergence Tracker (factions, tipping points)
         │
         ▼
SQLite WAL + LanceDB (vector memory)
```

---

## Project Structure

```
backend/
  app/api/        FastAPI routers
  app/services/   50+ business logic services
  app/models/     Pydantic models (all frozen)
  app/utils/      db.py, llm_client.py, runtime_settings.py
  database/       schema.sql
  tests/          ~2700 unit + ~134 integration tests
frontend/
  src/views/      Page components (Home, Process, Settings…)
  src/components/ 35+ UI components
  src/api/        API client layer
  src/composables useSettings, useOnboarding…
```

---

## License

**Prosperity Public License 2.0.0**

- Free for personal and non-commercial research use
- Commercial use requires a separate license

Copyright © 2026 destinyfrancis. All rights reserved.
