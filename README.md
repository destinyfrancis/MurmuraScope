<div align="center">

# 🏙️ Moirai — HK Society Simulation Engine

**香港社會模擬引擎 | Hong Kong Society Simulation Engine**

[![Python](https://img.shields.io/badge/Python-3.10%2F3.11-blue?logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green?logo=fastapi)](https://fastapi.tiangolo.com)
[![Vue 3](https://img.shields.io/badge/Vue-3.x-brightgreen?logo=vue.js)](https://vuejs.org)
[![License](https://img.shields.io/badge/License-Proprietary-red)](LICENSE)

<br/>

*A multi-agent social simulation engine that models Hong Kong society's collective response to economic, political, and social shocks — powered by LLMs, knowledge graphs, and agent-based modeling.*

</div>

---

## 目錄 / Table of Contents

- [中文介紹](#-中文介紹)
- [English Introduction](#-english-introduction)
- [Installation](#-installation--setup)
- [Launching](#-launching-the-system)
- [Configuration](#-configuration)
- [Architecture](#-architecture-overview)
- [API Reference](#-api-reference)

---

## 🇭🇰 中文介紹

### 係咩？

**Moirai（命運女神）** 係一個香港社會模擬引擎，結合多智能體系統、知識圖譜同大型語言模型，模擬香港市民對各種社會衝擊（樓市崩盤、利率上升、政治事件）嘅集體反應。

系統命名自希臘神話中掌管命運嘅三位女神，象徵對未來走勢嘅預測同模擬能力。

### 核心能力

#### 🤖 多智能體社會模擬
- 100–500 個 AI 代理人，代表唔同背景嘅香港市民（年齡、職業、地區、政治傾向）
- 模擬 Facebook / Instagram 平台上嘅互動、討論同輿論演變
- 每位代理人擁有：記憶系統、信念系統、情緒狀態（VAD 模型）、大五人格

#### 📊 宏觀經濟預測
- 11 個核心 HK 指標：CCL 樓價指數、失業率、恒生指數、GDP 增長、消費者信心等
- AutoARIMA + VAR 模型，12 季度前瞻預測 + 80%/95% 信賴區間
- 100 次 Monte Carlo 模擬（LHS 抽樣 + t-Copula）
- 回溯驗證：對比歷史數據（MAPE、Pearson r、方向準確率）

#### 🧠 知識圖譜演化
- 從種子文本自動提取實體關係，構建動態知識圖譜
- 隨模擬演化：代理人行動 → NL 描述 → 實體抽取 → 圖譜注入
- WebGL 可視化，支持時間軸回放

#### ⚡ 湧現行為（Emergence）
- **回音室偵測**：Louvain 社群算法識別信息繭房
- **情緒蔓延**：高喚醒代理人向信任鄰居傳播情緒
- **集體行動**：群組形成 + 動量追蹤
- **信念系統**：Bayesian 更新，6 個核心議題
- **認知失調**：衝突信念偵測 + 4 種解決策略

#### 🔮 預測市場整合（Polymarket）
- 自動匹配模擬種子主題 → Polymarket 真實合約
- 計算引擎預測概率 vs 市場定價 → 套利信號（Alpha）
- God View 終端：實時合約監控 + 代理人共識追蹤

#### 🎯 零配置快速啟動
- 貼入任何 HK 新聞或市場文字，引擎自動推斷域、規模、參數
- 無需手動配置，30 秒內啟動模擬

### 適用對象
| 用戶 | 用途 |
|------|------|
| 政策研究員 | 模擬政策衝擊對社會情緒嘅影響 |
| 金融分析師 | HK 宏觀指標預測 + 歷史回溯驗證 |
| 學術研究者 | 多智能體社會模擬、信息傳播、極化研究 |
| 新聞工作者 | 公眾輿論演化可視化 |
| 投資者 | Polymarket 信號 + 宏觀情景分析 |

---

## 🌐 English Introduction

### What is Moirai?

**Moirai** (named after the Greek Fates) is a Hong Kong Society Simulation Engine that combines multi-agent systems, knowledge graphs, and large language models to model Hong Kong society's collective response to economic, political, and social shocks.

Given a seed text (news article, policy document, or market event), Moirai spins up hundreds of AI agents representing Hong Kong citizens, simulates their interactions on Facebook/Instagram platforms, forecasts 11 macroeconomic indicators, and generates explainable AI reports — all with zero manual configuration.

### Core Capabilities

#### 🤖 Multi-Agent Social Simulation
- **100–500 AI agents** representing diverse Hong Kong demographics (age, occupation, district, political leaning, Big Five personality)
- Simulates interactions on **Facebook + Instagram** platforms via the OASIS framework
- Each agent maintains: episodic memory (LanceDB vector store), Bayesian belief system, VAD emotional state, trust network

#### 📊 Macroeconomic Forecasting
- **11 HK indicators**: CCL property index, unemployment, Hang Seng Index, GDP growth, consumer confidence, HIBOR 1M, net migration, retail sales, tourist arrivals, CPI YoY, interest rate
- **AutoARIMA + VAR** models with 12-quarter forecasts and 80%/95% confidence intervals
- **Monte Carlo ensemble** (100 trials, Latin Hypercube Sampling + t-Copula)
- **Retrospective validation**: compares predictions against actual HK historical data (MAPE, Pearson r, directional accuracy)

#### 🧠 Dynamic Knowledge Graph
- Auto-extracts entities and relationships from seed text
- Evolves with simulation: agent actions → NL descriptions → entity extraction → KG injection (Zep-style)
- **WebGL force-graph** visualization with timeline scrubber and echo chamber hull rendering

#### ⚡ Emergence Behaviors
- **Echo chamber detection**: Louvain community algorithm identifies filter bubbles
- **Emotional contagion**: high-arousal agents propagate emotions to trusted neighbors
- **Collective action**: group formation tracking and momentum scoring
- **Belief system**: Bayesian updates across 6 core HK topics
- **Cognitive dissonance**: conflict detection + 4 resolution strategies (rationalization, behavior change, belief change, trivialization)

#### 🔮 Prediction Market Integration
- Auto-matches simulation topics → live Polymarket contracts (keyword + topic group overlap scoring)
- Computes engine probability vs market price → alpha signal (BUY_YES / BUY_NO / HOLD)
- **God View Terminal**: dark terminal UI with live contract monitoring, signal dashboard, agent consensus feed

#### 🚀 Zero-Config Quick Start
- Paste any HK news text → engine infers domain, scale, and parameters automatically
- No manual configuration needed; simulation launches in under 30 seconds

### Data Sources (32 sources)
- **HKMA API**: mortgage approvals, bank data, monetary statistics
- **data.gov.hk CKAN**: census, property, employment, retail, tourism
- **Yahoo Finance**: HSI, sector indices, FX rates
- **FRED**: Fed Funds Rate, USD/HKD exchange rate
- **World Bank**: China GDP, PMI, CPI
- **RTHK RSS**: live HK news headlines for real-time shock injection
- **LIHKG**: 吹水台/政事台/財經台 community sentiment

---

## 🛠 Installation & Setup

### Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | **3.10 or 3.11 only** | OASIS does NOT support 3.12+ |
| Node.js | 18+ | For frontend |
| pyenv | recommended | For Python version management |

### 1. Clone the Repository

```bash
git clone https://github.com/destinyfrancis/Moirai.git
cd Moirai
```

### 2. Set Up Python Environment

```bash
# Install Python 3.11 (if not already installed)
pyenv install 3.11.9
pyenv local 3.11.9

# Create virtual environment
python -m venv .venv311
source .venv311/bin/activate  # Windows: .venv311\Scripts\activate

# Install dependencies
pip install -e ".[dev]"
```

> **⚠️ Important:** Python 3.12+ will break OASIS simulation subprocess. Strictly use 3.10 or 3.11.

### 3. Install OASIS Framework

OASIS is the underlying social simulation framework. Install it from source:

```bash
pip install camel-ai[all]
# or from OASIS GitHub:
# pip install git+https://github.com/camel-ai/oasis.git
```

### 4. Set Up Environment Variables

```bash
cp .env.example .env
```

Edit `.env` with your API keys:

```env
# Required: LLM provider (choose one or both)
OPENROUTER_API_KEY=sk-or-v1-your-key-here    # Primary: DeepSeek V3.2 via OpenRouter
FIREWORKS_API_KEY=fw_your-key-here            # Alternative provider

# Optional: Direct model access
ANTHROPIC_API_KEY=sk-ant-your-key-here
DEEPSEEK_API_KEY=sk-your-key-here

# Database (default path, usually no change needed)
DATABASE_PATH=data/hksimengine.db

# Server config
HOST=0.0.0.0
PORT=5001
DEBUG=true

# LLM provider selection (openrouter recommended)
LLM_PROVIDER=openrouter
```

**Getting API Keys:**
- **OpenRouter** (recommended): [openrouter.ai/keys](https://openrouter.ai/keys) — supports DeepSeek V3.2 at ~$0.00014/1K tokens
- **Fireworks**: [fireworks.ai](https://fireworks.ai) — alternative provider
- **Anthropic**: [console.anthropic.com](https://console.anthropic.com) — backup only

### 5. Set Up Frontend

```bash
cd frontend
npm install
cd ..
```

### 6. Initialize Data

On first launch, the system auto-downloads HK public data. You can also pre-seed it:

```bash
# Download all HK public data sources
.venv311/bin/python -m backend.data_pipeline.download_all --normalize
```

---

## 🚀 Launching the System

### Quick Start (Development)

Open **two terminals**:

**Terminal 1 — Backend:**
```bash
source .venv311/bin/activate
cd backend
uvicorn run:app --reload --port 5001
```

**Terminal 2 — Frontend:**
```bash
cd frontend
npm run dev
```

Then open **http://localhost:5173** in your browser.

### Production (Docker)

```bash
# Build and run
docker compose up --build

# Or run in background
docker compose up -d
```

### Demo Mode

```bash
# Requires OPENROUTER_API_KEY to be set in .env
bash scripts/demo.sh
```

### Run Tests

```bash
# Run full test suite (1795 tests)
.venv311/bin/python -m pytest backend/tests/ -v

# Run specific test file
.venv311/bin/python -m pytest backend/tests/test_prediction_market.py -v

# Run with coverage
.venv311/bin/python -m pytest backend/tests/ --cov=backend/app --cov-report=html
```

---

## ⚙️ Configuration

### Simulation Presets

| Preset | Agents | Rounds | Monte Carlo | Emergence | Use Case |
|--------|--------|--------|-------------|-----------|----------|
| `PRESET_FAST` | 100 | 15 | 30 | ❌ | Quick demo, testing |
| `PRESET_STANDARD` | 300 | 20 | 100 | ✅ | General analysis |
| `PRESET_DEEP` | 500 | 30 | 500 | ✅ | Academic research |

### Domain Packs (7 built-in)

| Pack ID | Domain | Language |
|---------|--------|----------|
| `hk_city` | Hong Kong urban society | zh-HK |
| `us_markets` | US financial markets | en-US |
| `global_macro` | Global macroeconomics | en-US |
| `public_narrative` | Public opinion & narrative | zh-HK/en-US |
| `real_estate` | Property market | zh-HK |
| `company_competitor` | Corporate competitive analysis | en-US |
| `community_movement` | Community movements | zh-HK |

### Cost Estimate

| Scenario | Tokens (approx.) | Cost (OpenRouter DeepSeek V3.2) |
|----------|-----------------|--------------------------------|
| PRESET_FAST (100 agents × 15 rounds) | ~3M | ~$0.42 |
| PRESET_STANDARD (300 agents × 20 rounds) | ~8M | ~$1.12 |
| PRESET_DEEP (500 agents × 30 rounds) | ~13.5M | ~$1.89 |

---

## 📐 Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Frontend (Vue 3)                      │
│  Home → Quick Start │ GraphExplorer │ PredictionDashboard│
│  GodViewTerminal │ Workspace │ PublicReport │ Learn      │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP/WebSocket (port 5173→5001)
┌────────────────────────▼────────────────────────────────┐
│                  FastAPI Backend (port 5001)              │
│  /simulation │ /graph │ /report │ /forecast              │
│  /api/prediction-market │ /auth │ /workspace             │
└──────┬──────────────┬──────────────┬────────────────────┘
       │              │              │
┌──────▼──────┐ ┌─────▼──────┐ ┌───▼──────────────────────┐
│  SQLite WAL │ │  LanceDB   │ │  OASIS Subprocess        │
│  (47 tables)│ │(vector     │ │  Facebook/Instagram      │
│             │ │ memories)  │ │  100–500 LLM agents      │
└─────────────┘ └────────────┘ └──────────────────────────┘
       │
┌──────▼─────────────────────────────────────────────────┐
│              HK Data Lake (32 sources)                  │
│  HKMA │ data.gov.hk │ Yahoo Finance │ FRED │ RTHK RSS  │
└────────────────────────────────────────────────────────┘
```

### Key Services

| Service | Purpose |
|---------|---------|
| `SimulationRunner` | Orchestrates OASIS subprocess + all hooks |
| `ZeroConfigService` | Keyword domain inference → auto-launch |
| `AgentMemoryService` | Memory storage, salience decay, semantic search |
| `MacroController` | Macro state + shock application + sentiment feedback |
| `MonteCarloEngine` | 100-trial LHS + t-Copula ensemble |
| `TimeSeriesForecaster` | AutoARIMA + VAR 12-quarter forecasts |
| `RetrospectiveValidator` | Backtest vs HK actual data |
| `KGGraphUpdater` | Zep-style dynamic KG evolution |
| `PolymarketClient` | Polymarket Gamma API + 10-min TTL cache |
| `ReportAgent` | ReACT-style report with 10 XAI tools |

---

## 📡 API Reference

### Quick Start (Zero Config)
```http
POST /simulation/quick-start
Content-Type: application/json

{ "seed_text": "港府宣布加息50個基點，樓市即時反應..." }
```
Returns: `{ session_id, status_url, estimated_duration_seconds }`

### Start Simulation (Full Config)
```http
POST /simulation/start
Content-Type: application/json

{
  "seed_text": "...",
  "domain_pack": "hk_city",
  "preset": "PRESET_STANDARD",
  "num_agents": 300,
  "num_rounds": 20
}
```

### Check Status
```http
GET /simulation/{session_id}/status
```

### Get Forecast
```http
GET /forecast/ccl_index
GET /forecast/unemployment
GET /forecast/hsi_level
```

### Inject Mid-Simulation Shock (God Mode)
```http
POST /simulation/{session_id}/shock
Content-Type: application/json

{ "shock_type": "rate_hike", "magnitude": 0.5, "description": "加息50bps" }
```

### Polymarket Signals
```http
GET /api/prediction-market/signals?session_id={id}
```

Full API documentation available at **http://localhost:5001/docs** when backend is running.

---

## 🖥 User Guide

### Step-by-Step Workflow

#### Step 1: Quick Start
1. Navigate to **http://localhost:5173**
2. Paste any HK news article or market commentary into the Quick Start box
3. Click **啟動模擬 / Launch Simulation**
4. The system auto-infers domain, scale, and parameters

#### Step 2: Monitor Simulation
- **動態廣場 / Live Feed**: Watch agents post in real-time
- **話題社群 / Topics**: Track trending hashtags and clusters
- **代理人 / Agents**: Inspect individual agent beliefs, memories, decisions
- **網絡演化 / Network**: Watch social network topology change over rounds
- **情緒地圖 / Emotional Map**: Heatmap of agent emotional states

#### Step 3: Inject Shocks (God Mode)
- Drag shock cards (rate hike, pandemic, political crisis) onto the simulation
- Watch agents react in real-time

#### Step 4: Analyze Results
- **Knowledge Graph Explorer**: Navigate entity relationships with timeline scrubber
- **Prediction Dashboard**: View 11-indicator forecasts with backtest validation
- **God View Terminal**: Monitor Polymarket contracts matched to your simulation

#### Step 5: Export & Share
- Generate AI report with 10 XAI tools (ReACT mode)
- Export as PDF
- Share via public link (token-based, no auth required)

---

## 🛡 Process Management

Kill stray simulation processes (important after crashes):

```bash
# Kill OASIS subprocesses
pkill -f "run_.*_simulation.py" || true

# Kill all related Python processes
pkill -f "uvicorn" || true

# Or use Makefile
make stop
```

---

## 📋 Requirements Summary

```
Python:     3.10 or 3.11 (NOT 3.12+)
Node.js:    18+
RAM:        8GB minimum, 16GB recommended (500-agent simulations)
Storage:    2GB+ for data lake and vector stores
API Keys:   OpenRouter (required) or Fireworks
```

---

## 🤝 Contributing

This project is under active development. For questions, issues, or contributions:

1. Open an [Issue](https://github.com/destinyfrancis/Moirai/issues)
2. Fork the repository and submit a Pull Request
3. Follow the existing code style (ruff, immutable patterns, async-first)

---

## 📄 License

Proprietary — All rights reserved. Contact the repository owner for licensing inquiries.

---

<div align="center">

**Moirai** — *Weaving the threads of Hong Kong's future*

Built with ❤️ for Hong Kong social research

</div>
