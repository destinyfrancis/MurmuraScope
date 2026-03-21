<div align="center">

# 🔭 MurmuraScope

### 通用預測引擎 · Universal Prediction Engine

**掉入任何文字。模擬任何世界。預測任何結果。**
**Drop any text. Simulate any world. Predict any outcome.**

[![Python](https://img.shields.io/badge/Python-3.10%2F3.11-blue?logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green?logo=fastapi)](https://fastapi.tiangolo.com)
[![Vue 3](https://img.shields.io/badge/Vue-3.x-brightgreen?logo=vue.js)](https://vuejs.org)
[![LanceDB](https://img.shields.io/badge/Vector_DB-LanceDB-orange)](https://lancedb.com)
[![License](https://img.shields.io/badge/License-Proprietary-red)](LICENSE)

<br/>

> *Murmur* — 千萬個 AI 聲音交織成嘅集體低語。*Scope* — 洞察群體動態嘅透鏡。
> MurmuraScope 將個體噪音轉化為可預測嘅集體信號。
>
> *Murmur — the collective whisper of thousands of AI voices interacting.*
> *Scope — the lens that transforms that noise into predictable collective signal.*

<br/>

**[引擎特色](#-引擎特色--what-makes-murmuroscope-different) · [核心能力](#-核心能力--core-capabilities) · [5步工作流程](#-5步工作流程--5-step-workflow) · [架構](#-架構--architecture) · [安裝](#-安裝--installation--setup) · [用戶指南](#-用戶指南--user-guide) · [API 參考](#-api-參考--api-reference)**

</div>

---

## 🌟 引擎特色 / What Makes MurmuraScope Different

### 對所有人的解釋 / For Everyone — No Technical Background Needed

想像一個工具：你把一篇新聞貼入去，幾秒鐘後，幾百個有性格、有記憶、有立場嘅 AI 人物自動出現，開始互相討論、爭論、形成派系——最後告訴你這件事最可能點樣發展，概率係幾多，哪個引爆點最危險。

唔需要你識程式。唔需要設定任何嘢。只需要文字。

*Imagine: you paste a news article, and within seconds, hundreds of AI characters with distinct personalities, memories, and beliefs automatically appear — debating, forming factions, and ultimately telling you the most likely outcome, the probability, and which tipping point is most dangerous.*

*No coding. No configuration. Just text.*

---

### MurmuraScope 能做什麼？/ What MurmuraScope Can Do

**掉任何文字入去，引擎自動建構一個可模擬的世界。**

唔需要你懂程式，唔需要事先配置任何嘢。把一段新聞、一份歷史記錄、一篇地緣政治簡報，甚至一本小說的段落貼進去——引擎會自動識別裡面的人物、組織、事件、關係，然後產生幾百至幾萬個有獨立性格、記憶和信念的 AI 代理人，讓他們在你眼前互動、爭論、形成派系，最後告訴你這個世界最可能怎樣演化。

*Drop any text — a news article, historical record, geopolitical brief, or even a novel excerpt — and the engine automatically identifies the actors, organizations, events, and relationships inside. It generates hundreds to tens of thousands of AI agents with distinct personalities, memories, and beliefs, lets them interact, debate, and form factions — and tells you how this world is most likely to evolve.*

---

### 引擎的核心強項 / Core Strengths

**🔍 從文字到世界，全自動**

貼入任何文字，引擎自動推斷：有哪些行動者、他們會做哪些決策、用哪些指標衡量局勢、可能發生哪些衝擊事件。無需手動設定任何領域配置，30 秒內啟動模擬。

*Paste any text — the engine infers actors, decisions, metrics, and potential shocks automatically. No domain configuration needed. Simulation starts in 30 seconds.*

**🧠 真正有深度的 AI 人物**

每個代理人不只是一個標籤。他們有大五人格、三維情緒狀態、會根據新信息不斷更新的信念系統，以及獨特的認知指紋——決定他們怎樣解讀世界、做出決策。

*Each agent carries Big Five personality traits, a three-dimensional emotional state, a belief system that updates as new information arrives, and a unique cognitive fingerprint that shapes how they interpret events and make decisions.*

**📊 量化預測，唔係純模擬**

模擬結束後，引擎輸出有數字、有信賴區間的量化預測——例如「12個月內樓價跌逾10%的概率是78%（80% CI: 71–84%）」。背後依靠蒙地卡羅集成（500次試驗）、AutoARIMA 時序預測、多指標向量自回歸，以及對比真實歷史數據的回溯驗證。

*The engine outputs quantitative forecasts with numbers and confidence intervals — e.g. "78% probability property prices fall >10% within 12 months." Powered by Monte Carlo ensemble (500 trials), AutoARIMA time-series forecasting, VAR multi-indicator modeling, and retrospective validation against real historical data.*

**🌐 知識圖譜，記錄世界的演化**

引擎建立並持續更新一張知識圖譜，把人物、組織、事件之間的關係以結構化方式記錄下來。每輪模擬後自動快照，可以回溯任意時間點，觀察關係網絡如何逐輪演化。

*The engine builds and continuously updates a knowledge graph — recording relationships between actors, organizations, and events. Auto-snapshots every round, with full temporal replay.*

**⚡ 湧現行為，讓你看見群體動態**

引擎偵測整個群體層面的湧現現象：回音室（哪些人只跟相似觀點的人交流？）、引爆點（哪一輪集體信念發生根本性轉變？）、情緒蔓延、認知失調、集體行動動量。全部係算法偵測的量化輸出。

*The engine detects emergent collective phenomena: echo chambers, tipping points, emotional contagion, cognitive dissonance, and collective action momentum — all algorithmically detected and quantified.*

**🔀 反事實分支——「如果換一個決策？」**

在任意輪次注入不同衝擊，創建一條平行時間線。兩條時間線分別跑蒙地卡羅模擬，對比概率分佈，清楚看見那個決策究竟改變了多少。

*Pause at any round, inject a different shock, and branch into a parallel timeline. Both timelines run Monte Carlo ensembles — compare probability distributions and see exactly how much that one decision changed.*

**📡 對接真實預測市場**

整合 Polymarket，自動匹配模擬主題的真實合約，計算引擎預測概率 vs 市場定價的差距，輸出 BUY / HOLD 信號。

*Integrates Polymarket to match your simulation topic against real prediction market contracts — outputs alpha signals based on the gap between engine probability and market pricing.*

---

### 你可以用 MurmuraScope 做什麼？/ Real-World Applications

**政策制定者 / Policy Makers**
> 在推行新政策前，先模擬它對不同社群的衝擊——哪個群體最先反彈？哪一輪會爆發示威動量？哪個微調可以降低社會阻力？

**投資者 / Investors**
> 輸入地緣政治事件，預測資產走勢的概率分佈，對比預測市場信號，在市場反應前識別風險與機會。

**歷史學家 / 教師 / Historians & Educators**
> 重播任何歷史轉捩點，改變一個決策，觀察歷史如何分叉。比教科書更直觀地展示因果鏈。

**企業策略師 / Corporate Strategists**
> 模擬競爭對手的行動後，市場動態如何演化——誰會轉投陣營？監管風險幾時爆發？

**記者 / 研究者 / Journalists & Researchers**
> 追蹤輿論敘事在不同社群的傳播路徑，識別回音室邊界同引爆點時機，量化資訊生態的極化程度。

**遊戲設計師 / Game Designers**
> 輸入任何虛構世界，引擎自動生成角色代理人同社會動態，測試敘事分叉點的可信度。

**安全分析師 / Security Analysts**
> 模擬衝突升級情景，計算多條路徑的概率，識別最關鍵的干預窗口。

---

| 你輸入什麼 / What you drop in | MurmuraScope 建構什麼 / What MurmuraScope builds |
|---|---|
| 香港加息政策新聞 | HK 代理人社會，樓市走勢 Monte Carlo，政治信任分析 |
| 1914 年七月危機文本 | 列強代理人網絡，升級概率曲線，WWI 爆發情景樹 |
| 中東衝突新聞 | 地緣政治代理人，升級情景，油價概率分佈 |
| AI 公司競爭簡報 | 企業競爭模擬，市場份額預測，派系動態 |
| 虛構世界設定（小說、遊戲） | 角色代理人社會，情感網絡，派系對立，命運分叉 |


---

## 🧠 核心能力 / Core Capabilities

### 🤖 多智能體社會模擬 / Multi-Agent Social Simulation

**多智能體系統（Multi-Agent System）** 係指由大量獨立 AI 個體（代理人 / Agent）組成的系統，每個代理人都有自己嘅個性、記憶同決策邏輯，互相影響、互相反應，從而產生整體層面嘅集體行為。就好似模擬一個真實社會，每個人都係獨立個體，但整體社會行為係由所有人互動所湧現出嚟。

*A multi-agent system consists of many independent AI individuals (agents), each with their own personality, memory, and decision logic — interacting and influencing each other to produce emergent collective behavior. Think of it as simulating a real society where every person is an independent actor, but collective behavior emerges from all their interactions.*

- **100 至 50,000 個 AI 代理人**，自動從 seed text 生成，唔係預設 HK profiles（kg_driven 模式）；內建 preset 涵蓋 100 / 300 / 500 / 1,000 / 3,000，亦可完全自定義
- 每位代理人擁有：
  - **情節記憶（Episodic Memory）**：儲存於 LanceDB 向量資料庫，按語義相關性提取
  - **貝葉斯信念系統（Bayesian Belief System）**：根據新資訊更新對世界嘅看法（見下方解釋）
  - **VAD 情緒模型**：用 Valence（正負）、Arousal（激動程度）、Dominance（控制感）三個維度描述情緒
  - **大五人格（Big Five Personality）**：開放性、盡責性、外向性、親和性、神經質
  - **認知偏差（Cognitive Bias）**：確認偏誤、從衆效應
- 模擬 Facebook + Instagram 平台互動（OASIS 框架）

> **貝葉斯信念更新（Bayesian Belief Update）** 係一種根據新證據調整自己信念強度嘅方法。例如你原本 60% 相信樓價會跌，睇到一則利淡新聞後，系統會根據呢則新聞嘅可信度同影響力，將你嘅信念自動更新至 75%。唔係直接替換，而係加權更新。
>
> *Bayesian belief update is a method of adjusting belief strength based on new evidence. If you originally 60% believed property prices would fall, and you read a bearish news article, the system updates your belief to, say, 75% based on the article's credibility and impact — not replacing, but probabilistically reweighting.*

---

### 📊 宏觀經濟預測 / Macroeconomic Forecasting
*(HK 模式 / hk_demographic mode only)*

- **10 個核心 HK 指標**：CCL 樓價指數、失業率、恒生指數、GDP 增長、消費者信心指數、HIBOR 1 個月、淨移民、零售銷售、旅客人次、CPI 年比
- **AutoARIMA + VAR 時間序列模型**，12 季度前瞻預測 + 80%/95% 信賴區間
- **500 次蒙地卡羅模擬**（LHS 抽樣 + t-Copula 相關結構）
- **回溯驗證（Retrospective Validation）**：對比真實 HK 歷史數據（MAPE、Pearson r、方向準確率）

> **蒙地卡羅模擬（Monte Carlo Simulation）** 唔係靠一個固定公式計出一個答案，而係透過成千上萬次帶有隨機性嘅模擬，睇下結果嘅概率分佈係點。就好似你想知道一場颱風登陸嘅概率 — 唔係估一條路徑，而係模擬一千條可能路徑，計算各種結果出現嘅頻率。
>
> *Monte Carlo simulation doesn't compute a single answer via a fixed formula. Instead it runs thousands of randomized simulations to map the probability distribution of outcomes — like simulating 1,000 possible typhoon tracks to estimate landfall probability, rather than guessing one path.*

> **AutoARIMA + VAR** 係兩種時間序列預測模型：AutoARIMA 自動尋找最佳參數去預測單一指標（例如樓價）；VAR（向量自回歸）同時考慮多個指標之間嘅相互影響（例如失業率上升如何影響樓價）。
>
> *AutoARIMA automatically finds optimal parameters to forecast a single indicator (e.g. property prices). VAR (Vector Autoregression) simultaneously models the cross-indicator interactions — e.g. how rising unemployment feeds into property price movements.*

> **信賴區間（Confidence Interval）** 係指預測值嘅不確定範圍。95% 信賴區間意思係：如果我哋重複做一百次預測，有 95 次真實值會落入呢個範圍之內。區間越窄，代表預測越有把握。
>
> *A confidence interval is the uncertainty range around a forecast. A 95% CI means: if we repeated the forecast 100 times, the true value would fall within that range 95 times. A narrower interval means a more precise forecast.*

---

### 🧠 知識圖譜演化 / Dynamic Knowledge Graph

**知識圖譜（Knowledge Graph）** 係一種將實體（人物、組織、事件、地點）同佢哋之間嘅關係，以「節點-邊」結構儲存嘅資料庫。例如「港府」→「宣布」→「加息政策」，呢種三元組結構讓引擎理解世界嘅結構性關係，而唔係只係處理文字。

*A knowledge graph stores entities (people, organizations, events, places) and their relationships as a node-edge structure. E.g. "HKSAR Government" → "announces" → "rate hike policy". This triadic structure lets the engine understand the world's structural relationships, not just process text.*

- 從 seed text 自動抽取實體關係，構建動態 KG
- **Zep-style 圖譜演化**：代理人行動 → 自然語言描述 → 實體抽取 → 圖譜注入。模擬過程中圖譜持續更新
- **力導向圖（Force-Directed Graph）可視化**：支持時間軸回放同回音室群組渲染
- 每 5 輪自動快照（Snapshot），可回溯任意時間點

---

### ⚡ 湧現行為 / Emergence Behaviors

**湧現（Emergence）** 係指整體層面出現嘅現象，係無法單純從個體行為預測嘅。例如每隻螞蟻都很簡單，但蟻群卻能建造複雜巢穴。MurmuraScope 追蹤多種社會層面嘅湧現現象：

*Emergence refers to phenomena that appear at the collective level and cannot be predicted from individual behavior alone. Just as individual ants are simple but ant colonies build complex structures, MurmuraScope tracks multiple social-level emergent phenomena:*

**回音室偵測（Echo Chamber Detection）**
> 使用 **Louvain 社群偵測算法**將代理人自動分群，識別哪些人只跟相似觀點嘅人互動。Louvain 係一種圖分割算法，透過最大化「模塊度（Modularity）」找出社群邊界。
>
> *Uses the Louvain community detection algorithm to automatically cluster agents and identify filter bubbles. Louvain is a graph partitioning algorithm that finds community boundaries by maximizing modularity — the degree to which a network's connections are denser within groups than between groups.*

**引爆點偵測（Tipping Point Detection）**
> 使用 **Jensen-Shannon 散度（JSD）**比較當前輪次同 3 輪前嘅信念分佈。JSD 係衡量兩個概率分佈之間相似度嘅對稱指標，數值介乎 0 至 1 之間 — 數值突然大幅上升，代表社會信念正在發生根本性轉變，即「引爆點」。
>
> *Uses Jensen-Shannon Divergence (JSD) to compare the current round's belief distribution against 3 rounds prior. JSD is a symmetric measure of similarity between two probability distributions, bounded between 0 and 1 — a sudden large increase signals a fundamental shift in collective beliefs, i.e. a tipping point.*

**情緒蔓延（Emotional Contagion）**
> 高喚醒度（High Arousal）嘅代理人（即情緒激動嘅人）會透過信任網絡向鄰居傳播情緒狀態，類似現實中恐慌情緒嘅傳播。

**認知失調（Cognitive Dissonance）**
> 當代理人同時持有互相矛盾嘅信念時，系統偵測衝突並模擬 4 種解決策略：合理化（Rationalization）、行為改變、信念修正、輕視化（Trivialization）。

**集體動量（Collective Momentum）**
> 追蹤群組形成同集體行動嘅動量分數，識別社會運動嘅早期信號。

---

### 🌀 概率雲 / Probability Cloud (Swarm Ensemble)

**概率雲（Probability Cloud）** 係引擎最核心嘅預測輸出形式——唔係一條單一預測線，而係 N 條由真實代理人互動產生嘅可能未來軌跡，形成一片概率空間。

*The Probability Cloud is the engine's core predictive output — not a single forecast line, but N possible future trajectories generated from genuine agent interactions, forming a probability space.*

這係引擎同普通蒙地卡羅統計模型嘅根本區別：

*This is the fundamental difference between this engine and ordinary Monte Carlo statistical models:*

| | 傳統蒙地卡羅 / Traditional MC | 概率雲 / Probability Cloud |
|---|---|---|
| 輸入 | 擾動宏觀參數 | 真實代理人信念、互動、派系 |
| 隨機性來源 | 數字統計噪音 | 個性化決策 × 情緒 × 認知偏差 |
| 輸出 | 統計分佈 | 湧現行為分類的情景樹 |

**Phase A + Phase B 雙階段架構：**

1. **Phase A（深度 LLM 模擬）**：完整 LLM 模擬，所有代理人建立真實記憶、信念系統、情感狀態、派系網絡
2. **分叉點（Fork Round = 50% 輪次）**：Phase A 達到中點時，完整複製所有代理人狀態（記憶、信念、互動歷史、情感）
3. **Phase B（N 條輕量副本）**：每條副本繼承 Phase A 深度初始化，然後用基於規則的隨機鉤子（`lite_hooks`）獨立跑完剩餘輪次，6 個隨機化源點確保軌跡真正分叉

**輸出結構（`ProbabilityCloud`）：**
- `outcome_distribution`：各情景類型概率（`disruption_polarized`, `disruption_converged`, `fragmentation`, `consensus`, `stalemate`）
- `belief_cloud`：每個指標嘅 p25/median/p75 信念分佈
- `wilson_ci`：Wilson 分數 95% 信賴區間
- `dominant_outcome`：最可能情景 + 概率百分比

**API：**`POST /simulation/{id}/swarm-ensemble?n_replicas=50&fork_round=15`
`GET /simulation/{id}/swarm-ensemble/results`

**自動引爆點分叉（Auto-Fork at Tipping Points）：**引擎偵測到 JSD ≥ 0.225（強烈信念轉變信號）時，自動創建兩條反事實分支：自然演化 vs 反向干預。每場模擬嘅分叉預算由 `min(5, max(2, round_count // 10))` 自適應計算。

---

### 🔮 預測市場整合 / Prediction Market Integration

**預測市場（Prediction Market）** 係一個讓人用真實金錢押注未來事件結果嘅市場，市場價格反映群眾對事件發生概率嘅集體估計。MurmuraScope 整合 Polymarket（全球最大去中心化預測市場）。

*A prediction market lets people bet real money on future event outcomes — the market price reflects the crowd's collective estimate of event probability. MurmuraScope integrates Polymarket, the world's largest decentralized prediction market.*

- 自動匹配 seed text 主題 → 真實 Polymarket 合約（關鍵字 + 主題組重疊評分）
- 計算引擎預測概率 vs 市場定價 → **套利信號（Alpha Signal）**：BUY_YES / BUY_NO / HOLD
- God View 終端：深色終端介面，實時合約監控 + 代理人共識追蹤

---

### 🎯 零配置快速啟動 / Zero-Config Quick Start

- 貼入任何文字，引擎自動偵測模式（HK 模式 vs 通用模式）、推斷規模同參數
- **30 秒內啟動**，無需手動配置任何 Domain Pack
- `ZeroConfigService.detect_mode_async()` 先用關鍵字快速判斷，再用 LLM 兜底

---

### 👥 兩種運作模式 / The Two Modes

| 模式 / Mode | 觸發條件 / Trigger | 代理人來源 / Agent Source | 決策空間 / Decision Space |
|------|---------|-------------|----------------|
| `hk_demographic` | Seed text 含 HK 關鍵字 | HK 人口普查統計工廠 | 預設 HK 決策類型 |
| `kg_driven` | 任何其他 seed text | KGAgentFactory（LLM 從 KG 節點提取） | ScenarioGenerator（LLM 動態生成） |

**`kg_driven` 模式下，引擎自動：**
1. 從 seed text 建立知識圖譜
2. LLM 從圖譜節點提取代理人候選（人物、組織、派系）
3. 為每個代理人生成認知指紋（Cognitive Fingerprint）+ 人格 Profile
4. LLM 創建領域專屬決策類型、指標、衝擊類型
5. 將世界背景記憶植入每個代理人
6. Tier 1 代理人（影響力最高的 30–100 人）每輪獲得完整 LLM 審議

> **認知指紋（Cognitive Fingerprint）** 係每個代理人嘅價值觀向量（3–12 個數值，範圍 0–1），例如 `prestige: 0.91, restraint: 0.21`，加上資訊飲食習慣、群組歸屬、易感性同確認偏誤強度。呢個指紋決定代理人如何詮釋世界事件同做出決策。
>
> *A cognitive fingerprint is each agent's value vector (3–12 values in [0,1]), e.g. `prestige: 0.91, restraint: 0.21`, plus information diet habits, group memberships, susceptibility, and confirmation bias strength. This fingerprint determines how the agent interprets world events and makes decisions.*

---

## 🏗 5步工作流程 / 5-Step Workflow

```
┌──────────────────────────────────────────────────────────────────────┐
│                                                                        │
│  第1步           第2步           第3步      第4步      第5步          │
│  STEP 1          STEP 2          STEP 3    STEP 4    STEP 5          │
│  圖譜建立      → 代理人生成    → 模擬運行→ 報告生成→ 互動分析       │
│  Graph Build     Agent Gen       Simulate  Report    Interact        │
│                                                                        │
│  Seed text       KGAgentFactory  OASIS     ReACT     訪問代理人       │
│  → KG 節點       LLM 人格        子進程    18 XAI    God Mode 衝擊   │
│  → 實體          記憶植入        God Mode  PDF 導出  分支模擬        │
│  → 關係          Tier 1/2        蒙地卡羅  Polymark  反事實分析      │
│                  分級            湧現行為  信號                       │
│                                                                        │
└──────────────────────────────────────────────────────────────────────┘
```

### 底層運作詳解 / What happens under the hood

**第 1 步 — 知識圖譜建立 / Knowledge Graph Build** (`POST /graph/build`)
- LLM 從 seed text 抽取實體、關係、世界背景
- KG 以節點/邊儲存於 SQLite + 力導向圖渲染 JSON
- `MemoryInitializationService`：第 2 階段 → 世界背景（`seed_world_context` + LanceDB `swc_` 表）；第 3 階段 → 人格模板（`seed_persona_templates`）

**第 2 步 — 代理人生成 + 記憶植入 / Agent Generation + Memory Hydration** (`POST /simulation/start`)
- `ZeroConfigService.detect_mode_async()` → `hk_demographic` 或 `kg_driven`
- `KGAgentFactory.create(graph_id)` → 三階段 LLM：資格篩選 → 人格生成 → 認知指紋
- `hydrate_session_bulk()` → 為每個代理人寫入 round_number=0 種子記憶（信念、背景、人格）
- Tier 1 代理人分配（按影響力評分最高的 30–100 人）— 每輪完整 LLM 審議

**第 3 步 — 模擬運行 / Simulation**（OASIS 子進程，結構化並發）
- **Group 前置**：動態排序；世界事件生成（kg_driven）
- **Group 1（並行）**：記憶提取、信任更新、情緒狀態
- **Group 2（順序）**：決策、副作用、信念更新；kg_driven: Tier 1 LLM 審議 + 信念傳播
- **Group 3（週期）**：
  - r1: 注意力衰減
  - r2: 公司決策
  - r3: 媒體影響、回音室、網絡演化、病毒傳播、情緒蔓延、KG 演化、派系快照 + 引爆點偵測（kg_driven）
  - r5: 宏觀反饋、KG 快照、新聞衝擊、極化、群組形成、財富轉移、集體動量
- God Mode：透過 WebSocket 在任意輪次注入衝擊

**第 4 步 — 報告生成 / Report** (`POST /report/{id}/generate`)
- **3-phase 結構化報告**（提供 `scenario_question` 時啟動）：Phase 1 LLM 生成大綱 → Phase 2 逐章 ReACT（每章最少 3 次工具調用）→ Phase 3 Markdown 組裝
- **18 個 XAI（可解釋 AI）工具**：`query_graph`、`get_global_narrative`、`get_sentiment_distribution`、`get_demographic_breakdown`、`interview_agents`、`get_macro_context`、`calculate_cashflow`、`get_decision_summary`、`get_sentiment_timeline`、`get_ensemble_forecast`、`get_macro_history`、`get_validation_summary`、`insight_forge`、`get_topic_evolution`、`get_platform_breakdown`、`get_agent_story_arcs`、`get_debate_summary`、`get_emergence_score`
- **未來式敘事框架**：報告以「模擬世界的演化就是對未來的預演」為立場，每章以編號預測清單作結
- PDF 導出 + 公開分享連結（基於 token，接收者無需帳號）

> **ReACT（Reasoning + Acting）** 係一種 LLM 推理模式：LLM 唔係一次過生成答案，而係反覆循環「思考 → 決定使用哪個工具 → 觀察工具結果 → 再思考」，直至答案足夠可靠。就好似一個偵探逐步收集證據，而唔係一開始就下結論。
>
> *ReACT is an LLM reasoning pattern where the model doesn't generate a single answer — instead it loops: "think → decide which tool to use → observe tool result → think again" until the answer is reliable enough. Like a detective gathering evidence step by step, rather than jumping to conclusions.*

> **XAI（Explainable AI / 可解釋人工智能）** 係指讓 AI 嘅決策過程透明化嘅技術。與其只給你一個預測數字，XAI 工具會展示「為什麼」得出呢個預測 — 哪些因素最重要、哪些代理人影響最大、哪個時間點發生了關鍵轉折。
>
> *XAI makes AI decision-making transparent. Rather than just giving you a prediction number, XAI tools show "why" — which factors matter most, which agents had the greatest influence, at which moment the critical shift occurred.*

**第 5 步 — 互動分析 / Interaction**
- 訪問任意代理人：基於其真實記憶 + 信念狀態的自然語言問答
- 查看信念歷史、記憶顯著性衰減曲線、認知失調事件
- 創建反事實分支：從任意輪次出發，以不同衝擊重播

---

## ⚙ 架構 / Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│           🐳 Docker Compose（推薦 / Recommended）                        │
│   docker compose up -d  →  frontend(:8080) + backend(:5001)             │
│   --profile observability  →  + Jaeger UI (:16686)                      │
└──────────────────┬──────────────────────────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────────────────────────┐
│                  前端 Frontend (Vue 3 + nginx / Vite)                    │
│  Home │ GraphExplorer │ GodViewTerminal │ PredictionDashboard            │
│  Workspace │ PublicReport │ DomainBuilder │ Process │ PersonaUpload ⬆️   │
└──────────────────────────┬──────────────────────────────────────────────┘
                            │ HTTP + WebSocket  (:8080 → :5001)
┌──────────────────────────▼──────────────────────────────────────────────┐
│                後端 FastAPI Backend (port 5001)                           │
│  /simulation │ /graph │ /report │ /forecast │ /prediction-market          │
│  /auth │ /workspace │ /api/domain-packs │ /ws                             │
│  /graph/{id}/temporal ⬆️ │ /graph/{id}/personas ⬆️                       │
│                                                                           │
│  📊 OpenTelemetry（opt-in） → Jaeger / OTLP Collector ⬆️                 │
└──────┬──────────────────┬──────────────────────┬─────────────────────────┘
       │                  │                       │
┌──────▼──────┐   ┌───────▼──────┐   ┌──────────▼──────────────────┐
│ SQLite WAL  │   │   LanceDB    │   │   OASIS Subprocess           │
│ (55+ 個表)  │   │ 向量資料庫   │   │   Facebook/Instagram 模擬    │
│ kg_edges:   │   │ 384 維嵌入   │   │   100–50,000 個 LLM 代理人   │
│ valid_from ⬆│   │ 記憶壓縮 ⬆️  │   │   PIANO 並行審議 ⬆️         │
│ valid_until │   │ 重要性評分⬆️ │   │   asyncio.gather + Semaphore │
└─────────────┘   └──────────────┘   └─────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────────────────────┐
│        HK 數據湖 Data Lake — 32 個來源（僅 hk_demographic 模式）      │
│  HKMA │ data.gov.hk │ Yahoo Finance (HSI) │ FRED │ RTHK RSS │ LIHKG │
└──────────────────────────────────────────────────────────────────────┘
```

> **向量資料庫（Vector Database）** 係一種儲存「語義向量」的資料庫。每段文字會被轉換成一個高維度數字向量（例如 384 維），語義相近的文字其向量距離也近。代理人搜索記憶時，唔係用關鍵字匹配，而係用語義相似度搜索 — 例如「今天市況如何」能夠找到「恒指下跌了300點」的記憶。
>
> *A vector database stores "semantic vectors". Each piece of text is converted into a high-dimensional numeric vector (e.g. 384 dimensions), and semantically similar texts have vectors close together. When an agent searches memory, it's not keyword matching — it's semantic similarity search. "How is the market today" can retrieve the memory "Hang Seng dropped 300 points".*

### 核心服務 / Key Services

| 服務 / Service | 職責 / Role |
|---------|------|
| `ZeroConfigService` | 從 seed text 偵測模式（hk_demographic vs kg_driven） |
| `KGAgentFactory` | 三階段 LLM 流水線：資格篩選 → 人格 → 認知指紋 |
| `MemoryInitializationService` | 第 1 步圖譜建立時提取世界背景 + 人格模板；支持 `persona_upload` 跳過 LLM |
| `PersonaProfileLoader` | ⬆️ **新** CSV/JSON 人口檔案解析 → `inject_as_kg_nodes()`，`source="persona_upload"` |
| `ScenarioGenerator` | LLM 為任意領域生成決策類型、指標、衝擊 |
| `UniversalDecisionEngine` | kg_driven：實體類型篩選 + 完整 LLM 審議 |
| `DecisionEngine` | hk_demographic：規則篩選（90%）→ LLM 批次（10%） |
| `CognitiveAgentEngine` | Tier 1 每輪完整 LLM 審議 → `DeliberationResult`；支持關係深度披露 |
| `BeliefPropagationEngine` | 嵌入向量信念更新 + 確認偏誤抑制 + 從衆混合 |
| `AgentMemoryService` | 記憶儲存、顯著性衰減、語義搜索；⬆️ **新** 重要性預評分 + 壓縮（閾值 200） |
| `KGTemporalQueries` | ⬆️ **新** `get_kg_edges_at_round()`、`get_edge_history()`、`get_kg_diff()` |
| `CostTracker` | ⬆️ **新** 每會話 LLM 費用累積器；`SESSION_COST_BUDGET_USD` 預算警告 |
| `SimulationSubprocessManager` | ⬆️ **新** 子進程生命週期管理；SIGTERM→SIGKILL 升級；`init: true` Docker 兼容 |
| `EmotionalEngine` | VAD 情緒模型 + 大五人格調節 |
| `BeliefSystem` | 6 個核心議題的 Bayesian 更新；認知失調偵測 |
| `EmergenceTracker` | `FactionMapper`（Louvain）+ `TippingPointDetector`（JSD） |
| `MultiRunOrchestrator` | Phase B 零 LLM 隨機集成；t 分佈抽樣；最多 10,000 次試驗 |
| `SwarmEnsemble` | 概率雲管道：Phase A（1 次 LLM 模擬）→ fork_round 分叉 → Phase B（N 條 lite 副本）→ `ProbabilityCloud`（情景分佈 + 信念雲 + Wilson CI） |
| `AutoForkService` | 引爆點自適應分叉；預算 = `min(5, max(2, round_count//10))`；JSD ≥ 0.225 觸發；反事實干預策略（極化→壓縮，收斂→放大） |
| `SurrogateIntegration` | `auto_train_surrogate()`；5 秒超時包裝；Phase B 前自動訓練 SurrogateModel |
| `WorldEventGenerator` | 每輪 LLM 世界事件，按活躍指標篩選（kg_driven） |
| `MacroController` | HK 宏觀狀態 + 衝擊應用 + 情緒反饋迴路 |
| `MonteCarloEngine` | 500 次 LHS + t-Copula 試驗，Wilson 分數 CI |
| `TimeSeriesForecaster` | AutoARIMA + VAR，12 季度預測（HK 模式） |
| `CalibrationPipeline` | OLS + BH-FDR 校正，13 對 HK 指標 |
| `RetrospectiveValidator` | 對比真實 HK 歷史數據的分段回測 |
| `KGGraphUpdater` | Zep-style 動態 KG 演化；⬆️ **新** `valid_from` + `dissolve_edges_between()` |
| `SocialNetworkBuilder` | 網絡初始化、Louvain 回音室偵測 |
| `NetworkEvolutionEngine` | 關係形成/解散、三角閉合 |
| `FeedRankingEngine` | 3 種算法：時序 / 互動 / 回音室 |
| `ReportAgent` | 3-phase ReACT 報告（`scenario_question` 啟動）；18 個 XAI 工具 → 未來式預測敘事報告 + PDF |
| `PolymarketClient` | Gamma API 匹配 + Alpha 信號生成（10 分鐘 TTL 緩存） |

### 數據庫表（55 個）/ Database Tables (55)

| 分類 / Category | 表名 / Tables |
|----------|--------|
| 核心 Core | `simulation_sessions`, `agent_profiles`, `kg_nodes`, `kg_edges`, `kg_communities`, `kg_snapshots` |
| 模擬 Simulation | `simulation_actions`, `agent_memories`, `memory_triples`, `agent_relationships`, `agent_decisions` |
| 經濟 Economy | `hk_data_snapshots`, `market_data`, `macro_scenarios`, `ensemble_results`, `validation_runs` |
| 社交 Social | `social_sentiment`, `echo_chamber_snapshots`, `news_headlines`, `data_provenance` |
| 湧現 Emergence | `network_events`, `agent_feeds`, `filter_bubble_snapshots`, `virality_scores`, `emotional_states`, `belief_states`, `cognitive_dissonance`, `polarization_snapshots`, `scale_benchmarks` |
| 企業 B2B | `company_profiles`, `company_decisions`, `media_agents` |
| 認證 Auth | `users`, `workspaces`, `workspace_members`, `comments` |
| 其他 Other | `reports`, `scenario_branches`, `population_distributions`, `custom_domain_packs`, `prediction_signals` |
| 認知劇場 Cognitive Theater（kg_driven）| `cognitive_fingerprints`, `world_events`, `faction_snapshots_v2`, `tipping_points`, `narrative_traces`, `multi_run_results` |
| 種子記憶 Seed Memory（kg_driven）| `seed_world_context`, `seed_persona_templates` |

---

## 🛠 安裝 / Installation & Setup

### 🐳 Docker（推薦 / Recommended）

最簡單的方式。只需 Docker Desktop。

```bash
git clone https://github.com/destinyfrancis/MurmuraScope.git
cd MurmuraScope
cp .env.example .env         # Fill in OPENROUTER_API_KEY + GOOGLE_API_KEY
docker compose up -d

# Frontend → http://localhost:8080
# Backend  → http://localhost:5001

# Optional: Jaeger trace UI at http://localhost:16686
docker compose --profile observability up -d

# Development (hot-reload)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

---

### 💻 本地安裝 / Local Setup

### 先決條件 / Prerequisites

| 需求 / Requirement | 版本 / Version | 備注 / Notes |
|-------------|---------|-------|
| Python | **3.10 或 3.11 only** | OASIS 不支持 3.12+ |
| Node.js | 18+ | 前端 |
| pyenv | 建議 / recommended | Python 版本管理 |

### 1. 克隆倉庫 / Clone

```bash
git clone https://github.com/destinyfrancis/MurmuraScope.git
cd MurmuraScope
```

### 2. Python 環境 / Python Environment

```bash
pyenv install 3.11.9
pyenv local 3.11.9

python -m venv .venv311
source .venv311/bin/activate  # Windows: .venv311\Scripts\activate

pip install -e ".[dev]"
```

> ⚠️ **重要 / Warning:** Python 3.12+ 會破壞 OASIS。必須使用 3.10 或 3.11。
> *Python 3.12+ will break OASIS. Strictly use 3.10 or 3.11.*

### 3. OASIS 框架 / OASIS Framework

```bash
pip install camel-ai[all]
# 或從源碼安裝 / or from source:
# pip install git+https://github.com/camel-ai/oasis.git
```

### 4. 環境變數 / Environment Variables

```bash
cp .env.example .env
```

```env
# 必填 / Required
OPENROUTER_API_KEY=sk-or-v1-your-key-here   # DeepSeek V3.2 (~$0.00014/1K tokens)

# 選填 / Optional
FIREWORKS_API_KEY=fw_your-key-here
ANTHROPIC_API_KEY=sk-ant-your-key-here
FRED_API_KEY=your-fred-key                   # HK 宏觀數據

# 服務器 / Server
DATABASE_PATH=data/murmuroscope.db
HOST=0.0.0.0
PORT=5001
LLM_PROVIDER=openrouter
```

**獲取 OpenRouter 密鑰 / Get OpenRouter key:** [openrouter.ai/keys](https://openrouter.ai/keys)
300 個代理人 × 20 輪模擬費用約 ~$1.12 / 300-agent, 20-round simulation costs ~$1.12

### 5. 前端 / Frontend

```bash
cd frontend && npm install && cd ..
```

### 6. 初始化 HK 數據（選填）/ Initialize HK Data (optional)

```bash
# 預載 HK 公共數據（首次啟動時也會自動下載）
# Pre-seed HK public data (also auto-downloads on first launch)
.venv311/bin/python -m backend.data_pipeline.download_all --normalize
```

### 7. 啟動 / Launch

**終端 1 — 後端 / Terminal 1 — Backend:**
```bash
source .venv311/bin/activate
cd backend && uvicorn run:app --reload --port 5001
```

**終端 2 — 前端 / Terminal 2 — Frontend:**
```bash
cd frontend && npm run dev
```

開啟瀏覽器 / Open browser: **http://localhost:5173**

---

## ⚙️ 模擬預設方案 / Simulation Presets

內建 5 個預設方案，亦支持完全自定義（最高 50,000 個代理人）。
*5 built-in presets, plus fully custom configuration (up to 50,000 agents).*

| 方案 / Preset | 代理人數 / Agents | 輪數 / Rounds | MC 試驗 / MC Trials | 湧現 / Emergence | 費用估算 / Est. Cost |
|--------|--------|--------|-----------|-----------|----------------------|
| `PRESET_FAST` | 100 | 15 | 30 | 關閉 Off | ~$0.42 |
| `PRESET_STANDARD` | 300 | 20 | 50 | 開啟 On | ~$1.12 |
| `PRESET_DEEP` | 500 | 30 | 100 | 開啟 On | ~$1.89 |
| `PRESET_LARGE` | 1,000 | 25 | 200 | 開啟 On | ~$3.50 |
| `PRESET_MASSIVE` | 3,000 | 20 | 300 | 開啟 On | ~$8.40 |
| `custom` | **自定義，最高 50,000** | 最高 100 | 自定義 | 自動調整 | 依規模而定 |

> **大規模模擬自動優化 / Auto-scaling for large simulations:**
> - 代理人數 > 1,000：hook 執行間隔自動加寬（例如回音室偵測從每 5 輪改為每 10 輪），減少計算開銷
> - 代理人數 > 5,000：湧現行為（Emergence）自動關閉，專注核心決策模擬
> - *Agents > 1,000: hook intervals auto-widened (e.g. echo chamber detection every 10 rounds instead of 5)*
> - *Agents > 5,000: emergence behaviors auto-disabled to focus on core decision simulation*

## 🗂 Domain Packs（7 個內建）/ Domain Packs (7 built-in)

Domain Pack 係預設的領域配置，包含代理人類型、決策類型同指標。在 kg_driven 模式下，這些會被 LLM 動態生成取代。

*A Domain Pack is a preset domain configuration including agent types, decision types, and metrics. In kg_driven mode, these are replaced by LLM-generated equivalents.*

| Pack ID | 領域 / Domain | 語言 / Language |
|---------|--------|----------|
| `hk_city` | 香港城市社會 / Hong Kong urban society | zh-HK |
| `us_markets` | 美國金融市場 / US financial markets | en-US |
| `global_macro` | 全球宏觀 / Global macroeconomics | en-US |
| `public_narrative` | 輿論敘事 / Public opinion & narrative | zh-HK / en-US |
| `real_estate` | 房地產 / Property market | zh-HK |
| `company_competitor` | 企業競爭 / Corporate competitive analysis | en-US |
| `community_movement` | 社區運動 / Community movements | zh-HK |

自定義 Pack / Custom packs: `POST /api/domain-packs/generate` → DomainBuilder 介面編輯 → `POST /api/domain-packs/save`

---

## 🖥 用戶指南 / User Guide

### 步驟指南 / Step-by-Step Workflow

#### 第 1 步 — 快速啟動 / Quick Start
1. 打開 **http://localhost:5173**
2. 將任何文字貼入 Quick Start 框（新聞、簡報、歷史事件、公司文件均可）
3. 點擊**啟動模擬 / Launch Simulation**
4. 系統自動偵測模式（hk_demographic vs kg_driven）、推斷規模和參數

#### 第 2 步 — 實時監控 / Monitor Simulation (Live)
- **動態廣場 / Live Feed**：實時觀看代理人發帖、回應、辯論
- **話題 / Topics**：追蹤趨勢標籤和正在湧現的敘事
- **代理人 / Agents**：查看個別代理人的信念、記憶和決策
- **網絡 / Network**：觀察社交網絡拓撲在每輪的演化
- **情緒地圖 / Emotional Map**：代理人 VAD 情緒狀態熱力圖

#### 第 3 步 — 注入衝擊（God Mode）/ Inject Shocks
- 點擊 **God Mode** 面板
- 選擇衝擊類型（加息、政治危機、疫情、軍事升級）
- 設定強度（0.0–1.0）和目標輪次
- 透過 WebSocket 實時觀看代理人反應

#### 第 4 步 — 分析結果 / Analyze Results
- **知識圖譜探索器 / Knowledge Graph Explorer**：力導向圖（Force-Directed Graph），時間軸回放，回音室群組渲染
- **預測儀表板 / Prediction Dashboard**：10 個 HK 指標預測（HK 模式），回測驗證，80%/95% 信賴區間
- **God View 終端 / God View Terminal**：深色終端介面 — Polymarket 合約實時監控、信號儀表板、代理人共識追蹤

#### 第 5 步 — 導出與分享 / Export & Share
- 生成 AI 報告（ReACT 模式），包含 18 個 XAI 工具分析（STANDARD 預設通常需時 5–15 分鐘）
- 導出 PDF
- 透過公開連結分享（基於 token，接收者無需帳號）

#### 第 6 步 — 反事實分析 / Counterfactual Analysis
- 從任何已完成模擬中點擊**創建分支 / Create Branch**
- 設定分叉點（輪次編號）和替代衝擊
- 對比基線 vs 分支：代理人信念分歧、指標軌跡、蒙地卡羅結果

---

## 📡 API 參考 / API Reference

### 零配置快速啟動 / Zero-Config Quick Start
```http
POST /simulation/quick-start
{ "seed_text": "..." }
→ { session_id, status_url, estimated_duration_seconds }
```

### 完整配置啟動 / Full Config Start
```http
POST /simulation/start
{
  "seed_text": "...",
  "preset": "PRESET_STANDARD",
  "num_agents": 300,
  "num_rounds": 20
}
```

### 模擬狀態與結果 / Simulation Status & Results
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

### God Mode — 注入衝擊 / Inject Shock
```http
POST /simulation/{id}/shock
{ "shock_type": "rate_hike", "magnitude": 0.5, "description": "加息50bps" }
```

### 反事實分支 / Counterfactual Branch
```http
POST /simulation/{id}/branch
{ "branch_name": "no_rate_hike", "shock_at_round": 5, "shock_type": "RATE_CUT" }
```

### 知識圖譜 / Knowledge Graph
```http
POST /graph/build
GET  /graph/{id}/snapshots
GET  /graph/analyze-seed
POST /graph/upload-seed
GET  /graph/{id}/temporal?round=N   # ⬆️ 新：查詢第 N 輪時的有效 KG 邊
POST /graph/{id}/personas            # ⬆️ 新：上傳 CSV/JSON 人口檔案初始化代理人
```

### 宏觀預測（HK 模式）/ Macroeconomic Forecast (HK mode)
```http
GET /forecast/{metric}           # ccl_index, unemployment, hsi_level, gdp_growth ...
GET /forecast/{metric}/backtest  # 回測驗證
GET /simulation/{id}/macro-history
```

### 報告 / Report
```http
POST /report/{id}/generate
GET  /report/{id}/pdf
POST /report/{id}/share
```

### 預測市場 / Prediction Market
```http
GET /api/prediction-market/contracts
GET /api/prediction-market/matched
GET /api/prediction-market/signals?session_id={id}
```

### 認證與工作空間 / Auth & Workspace
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

完整互動文檔 / Full interactive docs: **http://localhost:5001/docs**

---

## 🧪 測試 / Testing

```bash
make test                              # 單元測試 Unit only (~2547 tests, ~18s)
make test-int                          # 集成測試 Integration (~134 tests)
make test-all                          # 完整測試 Full suite (~2681 tests, ~65s)
make test-file F=test_belief_system    # 單文件 Single file
make test-changed                      # 僅測試 git 變更文件
```

測試標記 / Test markers: `unit`（純邏輯，默認）, `integration`（DB/HTTP）, `slow`（>10s，手動標記）

---

## 🛡 進程管理 / Process Management

崩潰後清理殘留進程 / Kill stray processes after crashes:

```bash
# 殺死 OASIS 子進程 / Kill OASIS subprocesses
pkill -f "run_.*_simulation.py" || true

# 殺死後端服務 / Kill backend server
pkill -f "uvicorn" || true

# 或使用 Makefile 快捷方式 / Or use Makefile shortcut
make stop
```

---

## 📋 系統需求 / System Requirements

```
Python:   3.10 或 3.11（不可用 3.12+）/ 3.10 or 3.11 (NOT 3.12+)
Node.js:  18+
RAM:      最低 8GB，建議 16GB（500代理人模擬）/ 8GB min, 16GB recommended (500-agent)
Storage:  2GB+（數據湖 + 向量存儲）/ 2GB+ (data lake + vector stores)
API Keys: OpenRouter（必填）; FRED, Fireworks（選填）/ OpenRouter (required); FRED, Fireworks (optional)
```

---

## 🤝 貢獻 / Contributing

歡迎貢獻！以下係參與方式：

1. 開啟 [Issue](https://github.com/destinyfrancis/MurmuraScope/issues) 描述 bug 或功能建議
2. Fork 倉庫，創建功能分支，提交 Pull Request
3. 代碼風格 / Code style: `ruff`，不可變 Pydantic 模型（`ConfigDict(frozen=True)`），async 優先，`dataclasses.replace()` 用於狀態變更，每個文件 200–400 行

### 致謝 / Acknowledgements

感謝以下開源項目：

- **[OASIS](https://github.com/camel-ai/oasis)** 同 **[CAMEL](https://github.com/camel-ai/camel)**（camel-ai）
- **[Generative Agents](https://github.com/joonspk-research/generative_agents)**（Stanford, Park et al. 2023）
- **[Zep Memory](https://github.com/getzep/zep)**
- **[LanceDB](https://github.com/lancedb/lancedb)**、**[FastAPI](https://github.com/tiangolo/fastapi)**、**[Vue 3](https://github.com/vuejs/vue)**

---

## 📬 聯絡 / Contact

有問題、合作洽詢或授權查詢，請聯絡：

**Email:** savouringofdestiny@gmail.com

GitHub Issues: [github.com/destinyfrancis/MurmuraScope/issues](https://github.com/destinyfrancis/MurmuraScope/issues)

---

## 📄 授權 / License

Proprietary — 保留所有權利。如需授權合作，請聯絡倉庫擁有者。
All rights reserved. Contact the repository owner for licensing inquiries.

---

<div align="center">

**🔭 MurmuraScope** — *聆聽集體低語，洞察任何世界嘅未來 / Listen to the collective murmur, see the future of any world*

*多智能體模擬 · 知識圖譜 · 宏觀預測 · 湧現行為 · 預測市場*
*Multi-agent simulation · Knowledge graphs · Macroeconomic forecasting · Emergent behavior · Prediction markets*

Built with ❤️ — savouringofdestiny@gmail.com

</div>
