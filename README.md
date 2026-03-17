<div align="center">

# ⚖️ Moirai

### 通用預測引擎 · Universal Prediction Engine

**掉入任何文字。模擬任何世界。預測任何結果。**
**Drop any text. Simulate any world. Predict any outcome.**

[![Python](https://img.shields.io/badge/Python-3.10%2F3.11-blue?logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green?logo=fastapi)](https://fastapi.tiangolo.com)
[![Vue 3](https://img.shields.io/badge/Vue-3.x-brightgreen?logo=vue.js)](https://vuejs.org)
[![LanceDB](https://img.shields.io/badge/Vector_DB-LanceDB-orange)](https://lancedb.com)
[![License](https://img.shields.io/badge/License-Proprietary-red)](LICENSE)

<br/>

> 命名自希臘神話掌管命運嘅三位女神——紡線、度量、剪斷。
> Moirai 將代理人、知識同時間，編織成集體智能。
>
> *Named after the Greek Fates who weave, measure, and cut the threads of destiny —*
> *Moirai weaves agents, knowledge, and time into collective intelligence.*

<br/>

**[引擎特色](#-引擎特色--what-makes-moirai-different) · [核心能力](#-核心能力--core-capabilities) · [Workflow Showcase](#-workflow-showcase) · [5步工作流程](#-5步工作流程--5-step-workflow) · [架構](#-架構--architecture) · [安裝](#-安裝--installation--setup) · [用戶指南](#-用戶指南--user-guide) · [API 參考](#-api-參考--api-reference)**

</div>

---

## 🌟 引擎特色 / What Makes Moirai Different

大多數模擬工具只能處理固定領域。**Moirai 沒有這個限制。**

Most simulation tools are domain-locked. **Moirai is not.**

貼入任何文字 — 新聞報道、地緣政治簡報、歷史事件、公司業績 — Moirai 自動推斷出所有角色、決策、指標同衝擊事件。數十秒內，數百個擁有獨特個性、記憶同信念的 AI 代理人開始互動。派系自然湧現。引爆點觸發。知識圖譜持續演化。宏觀預測實時更新。

Paste any text — a news article, geopolitical briefing, historical event, or company filing — and Moirai automatically infers the actors, decisions, metrics, and shocks. Within seconds, hundreds of AI agents with distinct personalities, memories, and beliefs begin interacting. Emergent factions form. Tipping points trigger. The knowledge graph evolves. Macro forecasts update.

**無需配置。無需領域專業知識。只需文字。**
**No configuration. No domain expertise required. Just text.**

| 你輸入什麼 / What you drop in | Moirai 建構什麼 / What Moirai builds |
|---|---|
| `"港府宣布加息50個基點..."` | 300 個跨 18 區 HK 代理人，模擬加息衝擊 |
| `"Archduke assassinated in Sarajevo, alliances mobilizing..."` | 1914 年七月危機 — 升級概率曲線，WWI 爆發模擬 |
| `"Iran drone strike on Israeli positions..."` | 地緣政治代理人網絡，升級情景，油價 Monte Carlo |
| `"OpenAI vs Anthropic vs Google Q4 competition..."` | 企業競爭模擬，市場份額預測，派系動態 |
| `"Colonial governor imposes trade restrictions on the port..."` | 歷史經濟危機 — 商人派系湧現，集體行動模擬 |

---

## 🧠 核心能力 / Core Capabilities

### 🤖 多智能體社會模擬 / Multi-Agent Social Simulation

**多智能體系統（Multi-Agent System）** 係指由大量獨立 AI 個體（代理人 / Agent）組成的系統，每個代理人都有自己嘅個性、記憶同決策邏輯，互相影響、互相反應，從而產生整體層面嘅集體行為。就好似模擬一個真實社會，每個人都係獨立個體，但整體社會行為係由所有人互動所湧現出嚟。

*A multi-agent system consists of many independent AI individuals (agents), each with their own personality, memory, and decision logic — interacting and influencing each other to produce emergent collective behavior. Think of it as simulating a real society where every person is an independent actor, but collective behavior emerges from all their interactions.*

- **100–500 個 AI 代理人**，自動從 seed text 生成，唔係預設 HK profiles（kg_driven 模式）
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

- **11 個核心 HK 指標**：CCL 樓價指數、失業率、恒生指數、GDP 增長、消費者信心指數、HIBOR 1 個月、淨移民、零售銷售、旅客人次、CPI 年比、利率
- **AutoARIMA + VAR 時間序列模型**，12 季度前瞻預測 + 80%/95% 信賴區間
- **100 次蒙地卡羅模擬**（LHS 抽樣 + t-Copula 相關結構）
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
- **WebGL 可視化**：3D 力導向圖，支持時間軸回放同回音室群組渲染
- 每 5 輪自動快照（Snapshot），可回溯任意時間點

---

### ⚡ 湧現行為 / Emergence Behaviors

**湧現（Emergence）** 係指整體層面出現嘅現象，係無法單純從個體行為預測嘅。例如每隻螞蟻都很簡單，但蟻群卻能建造複雜巢穴。Moirai 追蹤多種社會層面嘅湧現現象：

*Emergence refers to phenomena that appear at the collective level and cannot be predicted from individual behavior alone. Just as individual ants are simple but ant colonies build complex structures, Moirai tracks multiple social-level emergent phenomena:*

**回音室偵測（Echo Chamber Detection）**
> 使用 **Louvain 社群偵測算法**將代理人自動分群，識別哪些人只跟相似觀點嘅人互動。Louvain 係一種圖分割算法，透過最大化「模塊度（Modularity）」找出社群邊界。
>
> *Uses the Louvain community detection algorithm to automatically cluster agents and identify filter bubbles. Louvain is a graph partitioning algorithm that finds community boundaries by maximizing modularity — the degree to which a network's connections are denser within groups than between groups.*

**引爆點偵測（Tipping Point Detection）**
> 使用 **KL 散度（KL Divergence）**比較當前輪次同 3 輪前嘅信念分佈。KL 散度係衡量兩個概率分佈有幾「唔同」嘅指標 — 數值突然大幅上升，代表社會信念正在發生根本性轉變，即「引爆點」。
>
> *Uses KL Divergence to compare the current round's belief distribution against 3 rounds prior. KL Divergence measures how "different" two probability distributions are — a sudden large increase signals a fundamental shift in collective beliefs, i.e. a tipping point.*

**情緒蔓延（Emotional Contagion）**
> 高喚醒度（High Arousal）嘅代理人（即情緒激動嘅人）會透過信任網絡向鄰居傳播情緒狀態，類似現實中恐慌情緒嘅傳播。

**認知失調（Cognitive Dissonance）**
> 當代理人同時持有互相矛盾嘅信念時，系統偵測衝突並模擬 4 種解決策略：合理化（Rationalization）、行為改變、信念修正、輕視化（Trivialization）。

**集體動量（Collective Momentum）**
> 追蹤群組形成同集體行動嘅動量分數，識別社會運動嘅早期信號。

---

### 🔮 預測市場整合 / Prediction Market Integration

**預測市場（Prediction Market）** 係一個讓人用真實金錢押注未來事件結果嘅市場，市場價格反映群眾對事件發生概率嘅集體估計。Moirai 整合 Polymarket（全球最大去中心化預測市場）。

*A prediction market lets people bet real money on future event outcomes — the market price reflects the crowd's collective estimate of event probability. Moirai integrates Polymarket, the world's largest decentralized prediction market.*

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

## 🎬 Workflow Showcase

> **五個真實例子，逐步展示 Moirai 實際做咩。**
> **Five real examples showing what Moirai actually does — step by step.**

---

### Showcase 1 — 香港加息危機 / Hong Kong Rate Hike Crisis

**Seed Text:**
```
港府宣布跟隨美聯儲加息50個基點，本港樓市即時出現恐慌性拋售，
多個屋苑成交價急跌8-12%，銀行按揭審批收緊，業主聯盟發起遊行示威。
```

**5 步模擬過程：**

```
Step 1 │ 知識圖譜建立 GRAPH BUILD
       │ 提取實體: 港府, 美聯儲, 業主聯盟, 銀行系統, 樓市
       │ 關係鏈: rate_hike → mortgage_squeeze → property_panic
       │ MemoryInitializationService 將世界背景植入 LanceDB
       │
Step 2 │ 代理人生成 AGENT GENERATION
       │ 模式: hk_demographic（檢測到 HK 關鍵字）
       │ 300 個代理人橫跨 18 區，按人口普查比例加權
       │ 人物檔案: 年齡 22–67，月入 HK$15K–$120K
       │ Tier 1 分配: 最高影響力 30 人，每輪完整 LLM 審議
       │
Step 3 │ 模擬運行 SIMULATION（20 輪）
       │ 第 3 輪:  回音室形成 — 業主群組 vs 租客群組分裂
       │第 7 輪:  引爆點偵測 — 樓市情緒 KL 散度急升
       │第 12 輪: 集體行動湧現 — 示威動量分數達 0.73
       │第 17 輪: 信念極化: 親政府 34% vs 反政府 58%
       │ Polymarket 匹配: "HK 樓價跌逾10%" — 引擎: 67%, 市場: 51%
       │
Step 4 │ 報告生成 REPORT
       │ ReACT 代理人運行 10 個 XAI 工具: 情緒軌跡、派系地圖、引爆點時間軸
       │ CCL 指數預測: -14.2%（95% CI: -8.1% 至 -19.4%）未來 4 季
       │ 蒙地卡羅: 78% 概率 12 個月內樓價跌逾 10%
       │
Step 5 │ 互動 INTERACTION
       │ 訪問代理人 #147（深水埗業主，54 歲）:
       │ "我知道而家要賣，但係我唔捨得，呢度係我嘅根..."
       │ 注入 God Mode 衝擊: "政府宣佈緊急按揭援助計劃"
       │ 觀察: 示威動量 0.73 → 3 輪後降至 0.41
```

**輸出快照 / Output snapshot:**
```
宏觀預測 (12Q):         CCL: -14.2%  │  失業率: +1.8pp  │  恒指: -9.3%
派系地圖:               業主 (38%) │ 租客 (29%) │ 投資者 (19%) │ 中立 (14%)
引爆點:                 第 7 輪 (樓市情緒), 第 14 輪 (政治信任)
Polymarket Alpha 信號:  BUY_YES 樓價下跌合約（市場優勢 +16%）
代理人共識:             63% 預期 6 個月內再次加息
```

---

### Showcase 2 — 1914 年七月危機（WWI 爆發模擬）/ The July Crisis 1914

**Seed Text:**
```
Archduke Franz Ferdinand assassinated in Sarajevo, June 28 1914.
Austria-Hungary issues ultimatum to Serbia. Russia begins partial mobilization
in support of Serbia. Germany issues blank cheque guarantee to Austria-Hungary.
France bound by alliance to Russia. Britain watches Belgian neutrality.
Six weeks to world war.
```

**引擎建構內容 / What the engine builds:**

```
KG 節點提取:        奧匈帝國, 塞爾維亞, 俄國, 德國, 法國, 英國,
                    鄂圖曼帝國, 保加利亞, 弗朗茨·約瑟夫,
                    威廉二世, 尼古拉二世, 格雷外相, 潘加萊
關係映射:           alliance_obligation, ultimatum_issuer, mobilization_trigger,
                    blank_cheque_guarantee, pan-Slavic_solidarity

生成代理人 (kg_driven 模式):
  "威廉二世 Kaiser Wilhelm II"
                    Tier 1 │ 價值觀: prestige 0.91, restraint 0.21
                    易感性: 0.61 │ 確認偏誤: 0.77
  "尼古拉二世 Tsar Nicholas II"
                    Tier 1 │ 泛斯拉夫責任感 0.83, 厭戰 0.69
  "愛德華·格雷 Sir Edward Grey"
                    Tier 1 │ 均勢原則 0.88, 不干涉 0.71
  ... (共 54 個代理人)

LLM 生成決策類型:
  ISSUE_ULTIMATUM, ACCEPT_TERMS, REJECT_TERMS, PARTIAL_MOBILIZATION,
  FULL_MOBILIZATION, INVOKE_ALLIANCE, OFFER_MEDIATION, DECLARE_WAR

LLM 生成指標:
  escalation_momentum（升級動量）, alliance_cohesion（聯盟凝聚力）,
  mobilization_irreversibility（動員不可逆性）, diplomatic_window（外交窗口）
```

**15 輪模擬結果 / Simulation result:**
```
第 2 輪: 塞爾維亞接受最後通牒 9/10 條款 — 外交窗口: 0.61
         奧匈鷹派壓倒溫和派，要求完全拒絕
第 5 輪: 俄國部分動員觸發德國戰爭計劃鎖定
         引爆點: 動員不可逆性越過 0.70 門檻
第 9 輪: 施利芬計劃啟動 — 外交窗口崩潰至 0.04
         連鎖反應: 法國動員 → 英國援引比利時中立保障
第 15 輪: 升級動量: 0.94 │ 外交窗口: 0.02

蒙地卡羅（100 次試驗）:
  避免戰爭（塞爾維亞完全屈服）: 8%  (CI: 4–13%)
  局部奧塞戰爭:               19%  (CI: 13–25%)
  世界大戰（歷史結果）:        52%  (CI: 45–59%)

反事實分支: "威廉二世在第 5 輪叫停動員"
  → 開戰概率跌至 0.23
  → 但 67% 試驗中，第 12 輪前出現內部政權危機
```

---

### Showcase 3 — 伊朗-以色列升級情景 / Iran-Israel Escalation

**Seed Text:**
```
Iranian drone swarms struck Israeli military positions in the Negev.
Israel's Iron Dome intercepted 94% of projectiles. PM Netanyahu calls emergency
cabinet session. US 5th Fleet repositions to Persian Gulf. Oil futures spike 12%.
Hezbollah signals readiness for northern front activation.
```

**代理人和場景 / Agents and scenario:**
```
Tier 1 代理人:
  內塔尼亞胡內閣 (6)  — 鷹派 vs 務實派分裂
  以色列國防軍 (4)    — 升級門檻建模
  伊朗革命衛隊 (5)    — 代理人戰爭計算
  真主黨指揮部 (3)    — 啟動時機評估
  美國 NSC (4)        — 威懾信號
  阿拉伯聯盟 (8)      — 正常化協議保護
  ... (共 67 個)

LLM 生成指標:
  escalation_probability（升級概率）, oil_price_delta（油價變動）,
  civilian_casualty_risk（平民傷亡風險）, regional_stability_index（地區穩定指數）

LLM 生成衝擊:
  HEZBOLLAH_ACTIVATION, US_CARRIER_DEPLOYMENT,
  SAUDI_MEDIATION_OFFER, IRAN_NUCLEAR_ESCALATION
```

**模擬輸出 / Output:**
```
升級概率走勢:
  第 3 輪:  0.34  (內閣分裂，美國發出克制信號)
  第 7 輪:  0.61  (注入真主黨啟動衝擊)
  第 11 輪: 0.78  (引爆點 — 革命衛隊鷹派主導委員會)
  第 15 輪: 0.52  (美國最後通牒觸發伊朗降級信號)

蒙地卡羅（100 次試驗）:
  全面地區戰爭:        23% (CI: 17–29%)
  有限交火後停火:      54% (CI: 48–60%)
  談判停火:            23% (CI: 17–29%)

油價預測:   未來 3 個月 +18–34%（95% CI）
```

---

### Showcase 4 — OpenAI vs Anthropic vs Google（企業競爭）/ Corporate Competition

**Seed Text:**
```
OpenAI's GPT-5 launch captures enterprise market. Anthropic's Claude 4 leads
on safety benchmarks and European regulatory approval. Google DeepMind's Gemini
Ultra 2.0 integrates into 3B Android devices. Microsoft locks in $10B OpenAI
exclusivity. Meta releases LLaMA 4 open-source.
```

**場景 / Scenario:**
```
Tier 1 企業代理人:
  OpenAI 策略團隊     — 市場份額防守，定價壓力
  Anthropic 安全委員會 — 監管槓桿，企業信任
  Google DeepMind R&D — 分發護城河
  Microsoft Azure BD  — 排他協議執行
  Meta AI（開源）     — 生態系統商品化策略
  企業 CIO 委員會     — 供應商評估，鎖定風險

LLM 生成指標:
  market_share（市場份額）, regulatory_risk（監管風險）,
  enterprise_adoption（企業採用率）, open_source_pressure（開源壓力）
```

**輸出 / Output:**
```
第 12 輪派系快照:
  安全優先陣營:  Anthropic + 歐盟監管機構 (34% 決策權重)
  分發護城河:    Google + Microsoft (41%)
  開源生態:      Meta + 開發者社群 (25%)

市場份額預測（蒙地卡羅，未來 8 季）:
  OpenAI:    38% → 31% (CI: 27–35%)
  Google:    22% → 28% (CI: 24–33%)
  Anthropic: 12% → 18% (CI: 14–22%)
  Meta/OSS:   8% → 15% (CI: 11–19%)

第 9 輪引爆點: 歐盟執法衝擊令閉源模型信任崩潰
  → 觸發 3 輪企業重新評估決策連鎖反應
```

---

### Showcase 5 — 反事實分析：「如果美聯儲 2022 年降息？」/ What-If Branch

**使用 Moirai 反事實分支功能 / Using Moirai's counterfactual branch:**

```bash
POST /simulation/{session_id}/branch
{
  "branch_name": "Fed_Pivot_2022",
  "shock_at_round": 3,
  "shock_type": "RATE_CUT_50BPS",
  "description": "美聯儲逆轉 — 降息 50bps 代替加息"
}
```

```
基線時間線:   美聯儲加息 → 通脹持續 → 衰退概率 0.61
分支時間線:   美聯儲降息 → 資產價格飆升 → 通脹重新加速
              第 8 輪分歧: 兩條時間線相關性降至 0.43（重大分叉）

蒙地卡羅對比（各 100 次試驗）:
  基線:  衰退概率 0.61 (CI: 0.54–0.68)
  分支:  衰退概率 0.29 (CI: 0.22–0.36)
         但是: 12 個月通脹 >5% 概率: 0.71 (CI: 0.64–0.78)

第 15 輪代理人信念對比:
  基線:  物業信心: 0.31 │ 工作安全感: 0.44
  分支:  物業信心: 0.67 │ 工作安全感: 0.71
         但是: 購買力: 0.29（vs 基線 0.41）

報告結論: "聯儲降息會避免短期衰退，
但埋下結構性通脹 — 從 2025 年視角看是更差的結果。"
```

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
│  → KG 節點       LLM 人格        子進程    10 XAI    God Mode 衝擊   │
│  → 實體          記憶植入        God Mode  PDF 導出  分支模擬        │
│  → 關係          Tier 1/2        蒙地卡羅  Polymark  反事實分析      │
│                  分級            湧現行為  信號                       │
│                                                                        │
└──────────────────────────────────────────────────────────────────────┘
```

### 底層運作詳解 / What happens under the hood

**第 1 步 — 知識圖譜建立 / Knowledge Graph Build** (`POST /graph/build`)
- LLM 從 seed text 抽取實體、關係、世界背景
- KG 以節點/邊儲存於 SQLite + WebGL 渲染 JSON
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
- **ReACT 代理人**（Reasoning + Acting）反覆思考、調用工具、得出結論
- 10 個 XAI（可解釋 AI）工具：`get_faction_map`、`get_tipping_points`、`get_sentiment_trajectory`、`get_belief_distribution`、`get_echo_chambers`、`run_monte_carlo`、`get_macro_forecast`、`get_polymarket_signals`、`get_agent_consensus`、`get_narrative_trace`
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
┌────────────────────────────────────────────────────────────────────┐
│                  前端 Frontend (Vue 3 + Vite)                        │
│  Home │ GraphExplorer │ GodViewTerminal │ PredictionDashboard       │
│  Workspace │ PublicReport │ DomainBuilder │ Process                 │
└──────────────────────────┬─────────────────────────────────────────┘
                            │ HTTP + WebSocket  (5173 → 5001)
┌──────────────────────────▼─────────────────────────────────────────┐
│                後端 FastAPI Backend (port 5001)                       │
│  /simulation │ /graph │ /report │ /forecast │ /prediction-market    │
│  /auth │ /workspace │ /api/domain-packs │ /ws                       │
└──────┬──────────────────┬──────────────────────┬────────────────────┘
       │                  │                       │
┌──────▼──────┐   ┌───────▼──────┐   ┌──────────▼──────────────────┐
│ SQLite WAL  │   │   LanceDB    │   │   OASIS Subprocess           │
│ (55 個表)   │   │ 向量資料庫   │   │   Facebook/Instagram 模擬    │
│             │   │ 384 維嵌入   │   │   100–500 個 LLM 代理人      │
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
| `MemoryInitializationService` | 第 1 步圖譜建立時提取世界背景 + 人格模板 |
| `ScenarioGenerator` | LLM 為任意領域生成決策類型、指標、衝擊 |
| `UniversalDecisionEngine` | kg_driven：實體類型篩選 + 完整 LLM 審議 |
| `DecisionEngine` | hk_demographic：規則篩選（90%）→ LLM 批次（10%） |
| `CognitiveAgentEngine` | Tier 1 每輪完整 LLM 審議 → `DeliberationResult` |
| `BeliefPropagationEngine` | 嵌入向量信念更新 + 確認偏誤抑制 + 從衆混合 |
| `AgentMemoryService` | 記憶儲存、顯著性衰減、語義搜索（LanceDB） |
| `EmotionalEngine` | VAD 情緒模型 + 大五人格調節 |
| `BeliefSystem` | 6 個核心議題的 Bayesian 更新；認知失調偵測 |
| `EmergenceTracker` | `FactionMapper`（Louvain）+ `TippingPointDetector`（KL 散度） |
| `MultiRunOrchestrator` | Phase B 零 LLM 隨機集成；t 分佈抽樣；最多 10,000 次試驗 |
| `WorldEventGenerator` | 每輪 LLM 世界事件，按活躍指標篩選（kg_driven） |
| `MacroController` | HK 宏觀狀態 + 衝擊應用 + 情緒反饋迴路 |
| `MonteCarloEngine` | 100 次 LHS + t-Copula 試驗，Wilson 分數 CI |
| `TimeSeriesForecaster` | AutoARIMA + VAR，12 季度預測（HK 模式） |
| `CalibrationPipeline` | OLS + BH-FDR 校正，13 對 HK 指標 |
| `RetrospectiveValidator` | 對比真實 HK 歷史數據的分段回測 |
| `KGGraphUpdater` | Zep-style 動態 KG 演化，由代理人行動驅動 |
| `SocialNetworkBuilder` | 網絡初始化、Louvain 回音室偵測 |
| `NetworkEvolutionEngine` | 關係形成/解散、三角閉合 |
| `FeedRankingEngine` | 3 種算法：時序 / 互動 / 回音室 |
| `ReportAgent` | ReACT 循環，10 個 XAI 工具 → 敘事報告 + PDF |
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

### 先決條件 / Prerequisites

| 需求 / Requirement | 版本 / Version | 備注 / Notes |
|-------------|---------|-------|
| Python | **3.10 或 3.11 only** | OASIS 不支持 3.12+ |
| Node.js | 18+ | 前端 |
| pyenv | 建議 / recommended | Python 版本管理 |

### 1. 克隆倉庫 / Clone

```bash
git clone https://github.com/destinyfrancis/Moirai.git
cd Moirai
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
DATABASE_PATH=data/hksimengine.db
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

| 方案 / Preset | 代理人數 / Agents | 輪數 / Rounds | MC 試驗 / MC Trials | 湧現 / Emergence | 費用 / Cost |
|--------|--------|--------|-----------|-----------|----------------------|
| `PRESET_FAST` | 100 | 15 | 30 | 關閉 Off | ~$0.42 |
| `PRESET_STANDARD` | 300 | 20 | 100 | 開啟 On | ~$1.12 |
| `PRESET_DEEP` | 500 | 30 | 500 | 開啟 On | ~$1.89 |

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
- **知識圖譜探索器 / Knowledge Graph Explorer**：3D 力導向圖，時間軸回放，回音室群組渲染
- **預測儀表板 / Prediction Dashboard**：11 個 HK 指標預測（HK 模式），回測驗證，80%/95% 信賴區間
- **God View 終端 / God View Terminal**：深色終端介面 — Polymarket 合約實時監控、信號儀表板、代理人共識追蹤

#### 第 5 步 — 導出與分享 / Export & Share
- 生成 AI 報告（ReACT 模式），包含 10 個 XAI 工具分析（STANDARD 預設通常需時 5–15 分鐘）
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
make test                              # 單元測試 Unit only (~2001 tests, ~21s)
make test-int                          # 集成測試 Integration (~186 tests)
make test-all                          # 完整測試 Full suite (~2200 tests, ~62s)
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

1. 開啟 [Issue](https://github.com/destinyfrancis/Moirai/issues)
2. Fork + Pull Request
3. 代碼風格 / Code style: `ruff`，不可變 Pydantic 模型（`ConfigDict(frozen=True)`），async 優先，`dataclasses.replace()` 用於狀態變更，每個文件 200–400 行

---

## 📄 授權 / License

Proprietary — 保留所有權利。如需授權合作，請聯絡倉庫擁有者。
All rights reserved. Contact the repository owner for licensing inquiries.

---

<div align="center">

**⚖️ Moirai** — *編織任何世界嘅未來 / Weaving the threads of any world's future*

*多智能體模擬 · 知識圖譜 · 宏觀預測 · 湧現行為 · 預測市場*
*Multi-agent simulation · Knowledge graphs · Macroeconomic forecasting · Emergent behavior · Prediction markets*

</div>
