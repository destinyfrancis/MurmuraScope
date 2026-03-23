# MurmuraScope

[English] | [繁體中文] | [简体中文]

---

## 🌟 Overview / 概覽 / 概览

**[EN]** MurmuraScope is a universal prediction engine that turns any text—news articles, novel excerpts, or geopolitical briefs—into a runnable social simulation. It helps you visualize how events might unfold by creating digital "agents" that interact based on the information you provide.

**[繁中]** MurmuraScope 是一個通用的預測引擎，能將任何文本（如新聞文章、小說片段或地緣政治簡報）轉化為可運行的社會模擬。它透過創建數位「智能代理」，根據您提供的資訊進行互動，幫助您預見事件可能如何發展。

**[简中]** MurmuraScope 是一个通用的预测引擎，能将任何文本（如新闻文章、小说片段或地缘政治简报）转化为可运行的社会模拟。它通过创建数字“智能代理”，根据您提供的信息进行互动，帮助您预见事件可能如何发展。

---

## 🚀 How it works / 工作原理 / 工作原理

### 1. Paste Text / 貼上文本 / 贴上文本
**[EN]** Drop in any text. The engine automatically identifies key people, organizations, and relationships.
**[繁中]** 放入任何文本，引擎會自動識別關鍵人物、組織及其相互關係。
**[简中]** 放入任何文本，引擎会自动识别关键人物、组织及其相互关系。

### 2. Agents Appear / 代理生成 / 代理生成
**[EN]** The system creates digital characters (agents) with distinct personalities, beliefs, and emotional states—no manual setup required.
**[繁中]** 系統會自動創建具有獨特個性、信念和情緒狀態的數位角色（代理），無需手動設置。
**[简中]** 系统会自动创建具有独特个性、信念和情绪状态的数字角色（代理），无需手动设置。

### 3. Run Simulation / 運行模擬 / 运行模拟
**[EN]** Agents interact, debate, and form groups. They update their beliefs as they "talk" to each other across multiple rounds.
**[繁中]** 代理之間會進行互動、辯論並形成群體。他們在多輪「對話」中不斷更新自己的觀點。
**[简中]** 代理之间会进行互动、辩论并形成群体。他们在多轮“对话”中不断更新自己的观点。

### 4. Get Forecasts / 獲取預測 / 获取预测
**[EN]** The engine runs hundreds of scenarios to give you probabilistic forecasts and data-driven insights.
**[繁中]** 引擎會運行數百種場景，為您提供概率預測和數據驅動的洞察。
**[简中]** 引擎会运行数百种场景，为您提供概率预测和数据驱动的洞察。

### 5. Explore & Interact / 探索與互動 / 探索与互动
**[EN]** "Interview" any agent to understand their logic, or introduce new events (shocks) to see how the simulation changes.
**[繁中]** 您可以「採訪」任何代理以了解他們的邏輯，或加入突發事件（衝擊）來觀察模擬的變化。
**[简中]** 您可以“采访”任何代理以了解他们的逻辑，或加入突发事件（冲击）来观察模拟的变化。

---

## 🛠 For Developers / 開發者指南 / 开发者指南

### Quickstart / 快速入門 / 快速入门

```bash
# Setup environment / 設置環境 / 设置环境
cp .env.example .env        # Add API keys (OpenRouter & Google)

# Run with Docker / 使用 Docker 運行 / 使用 Docker 运行
docker compose up -d        # Frontend :8080 | Backend :5001
```

### Tech Stack / 技術棧 / 技术栈
- **Backend:** Python 3.11, FastAPI, SQLite (WAL mode)
- **Analytical Queries:** DuckDB (High-speed columnar aggregation)
- **Frontend:** Vue 3, Vite, TypeScript
- **AI/LLMs:** OpenRouter (Agent deliberation), Google AI (Reports)
- **Vector DB:** LanceDB (384-dim multilingual embeddings)

---

## 📊 System Architecture / 系統架構 / 系统架构

MurmuraScope uses a sophisticated multi-layered architecture to manage everything from individual agent cognition to complex statistical forecasting. For full technical details, including Monte Carlo ensembles and VAR/GARCH econometric models, please refer to the documentation in the `docs/` folder.

---

## 📜 License / 許可證 / 许可证

Proprietary. All rights reserved. / 私有軟體，保留所有權利。 / 私有软件，保留所有权利。
