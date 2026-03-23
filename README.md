# 👁️ MurmuraScope
### Predict the Social Pulse | 預見社會脈動 | 預見社會脈動

![License](https://img.shields.io/badge/license-Proprietary-red)
![Platform](https://img.shields.io/badge/platform-Docker-blue)
![Language](https://img.shields.io/badge/language-English%20%7C%20繁體中文%20%7C%20简体中文-green)

---

## 🌟 Overview / 概覽 / 概览

**[EN]** MurmuraScope is a universal prediction engine that transforms any text into a high-fidelity social simulation. By dropping in news, articles, or reports, it automatically creates digital "agents" that interact, debate, and evolve, providing you with data-driven forecasts on social outcomes.

**[繁中]** MurmuraScope 是一個通用的預測引擎，能將任何文本轉化為高真度的社會模擬。只需放入新聞、文章或報告，系統就會自動創建數位「智能代理」進行互動、辯論與演化，為您提供基於數據的社會發展預測。

**[简中]** MurmuraScope 是一个通用的预测引擎，能将任何文本转化为高真度的社会模拟。只需放入新闻、文章或报告，系统就会自动创建数字“智能代理”进行互动、辩论与演化，为您提供基于数据的社会发展预测。

---

## 🎯 Use Cases: When to use MurmuraScope?
### 應用場景：MurmuraScope 能為你解決什麼？ | 应用场景：MurmuraScope 能为你解决什么？

| Scenario / 場景 / 场景 | How it helps / 運作方式 / 运作方式 |
| :--- | :--- |
| **Breaking News Reaction** <br> 突發新聞反應分析 | Predict how different social factions (e.g., conservatives vs. progressives) will react to a new policy or event. <br> 預測不同社會群體（如：保守派 vs 進取派）對新政策或事件的反應。 |
| **Geopolitical Analysis** <br> 地緣政治分析 | Simulate potential escalations or diplomatic shifts based on recent strategic briefs. <br> 根據最新的戰略簡報，模擬潛在的局勢升級或外交轉向。 |
| **Market Sentiment** <br> 市場情緒預測 | Understand how a new product launch or economic shift ripples through a community’s belief system. <br> 了解新產品發佈或經濟變動如何影響社群的信念體系。 |
| **Crisis Management** <br> 危機管理模擬 | Test different "what-if" scenarios (Shocks) to see which intervention effectively calms social unrest. <br> 測試不同的「如果」場景（衝擊），觀察哪種干預措施能有效平息社會動盪。 |

---

## ✨ Key Features / 核心功能 / 核心功能

*   **🧠 Instant Intelligence (無須設定，即時生成):** No manual agent creation. The engine extracts personalities (Big Five traits) and beliefs directly from your text.
*   **📊 Probabilistic Forecasting (數據化預測):** Runs hundreds of "Monte Carlo" trials to give you clear confidence intervals and likelihoods, not just a single guess.
*   **🗣️ Interactive Interviews (互動式採訪):** Don't just watch—talk to the agents. "Interview" digital characters to understand the logic behind their decisions.
*   **⚡ Branching Realities (多重現實分支):** At any point, inject a "Shock" (e.g., a sudden rumor or a disaster) to see how it alters the future.

---

## 🚀 The 5-Step Workflow / 五步流程 / 五步流程

1.  **Input (輸入):** Paste your source text. / 貼上您的原始文本。
2.  **Extract (提取):** System builds a Knowledge Graph of people and organizations. / 系統自動建立人物與組織的知識圖譜。
3.  **Generate (生成):** Up to 500+ unique agents appear with distinct psychological profiles. / 生成多達 500+ 個具有獨特心理特徵的代理。
4.  **Simulate (模擬):** Watch rounds of debates, faction forming, and belief updates. / 觀察多輪辯論、派系形成和信念更新。
5.  **Report (報告):** Receive a comprehensive AI-generated report with statistical charts. / 獲取包含統計圖表的 AI 生成詳盡報告。

---

## 🛠 Developer Quickstart / 開發者快速入門 / 开发者快速入门

```bash
# 1. Setup Environment
cp .env.example .env

# 2. Launch with Docker
docker compose up -d

# 3. Access
# Frontend: http://localhost:8080
# Backend API: http://localhost:5001
```

<details>
<summary><b>🔍 Technical Specifications (進階技術規格)</b></summary>

- **Forecasting:** VAR/VECM, GARCH(1,1) for volatility, Monte Carlo ensembles.
- **Cognition:** Bayesian belief updating, Big Five personality mapping.
- **Stack:** FastAPI, Vue 3, DuckDB, LanceDB (Vector), SQLite (WAL).
</details>

---

## 📜 License / 許可證 / 许可证

Proprietary. All rights reserved. / 私有軟體，保留所有權利。 / 私有软件，保留所有权利。
