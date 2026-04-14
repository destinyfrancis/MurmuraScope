# MurmuraScope 超越計劃：次世代社會模擬引擎藍圖 (Beyond MiroFish)

## 1. 戰略願景：從「研究原型」到「次世代真相與模擬平台」
MiroFish 的成功在於其出色的「工程管道一致性 (Pipeline Coherence)」——它確保了資料流從文件到圖譜再到報告的單向暢通。
然而，MurmuraScope 真正的護城河與潛力在於其**「社會動力學的深度與廣度」**。
為了解決落差並實現超越，我們不只要追平 MiroFish 的 E2E 工程流暢度，更要引入 MiroFish 沒有的**高維度溯源架構 (High-Dimensional Provenance)** 與**雙軌圖譜系統 (Dual-Track Graph System)**，將 MurmuraScope 打造成具備自我修正與時序推理能力的頂級產品。

---

## 2. 核心架構典範轉移 (Architectural Paradigm Shift)

要真正與 MiroFish 拉開技術差距，必須在底層設計上做顛覆並加入防禦性架構：

1. **從「單一圖譜」升級為「支援視角的多視角認知圖譜 (Perspectival Dual-Layer Graph)」**：
   - **底層（Truth Graph: 事實圖譜）**：由 Seed Text 構成，絕對客觀。
   - **上層（Belief/Simulation Graph: 信念/模擬圖譜）**：由 Agent 互動產生動態邊緣。支援時效性、信心度，**並且支援 `source_agent_id`**，允許多個 Agent 對同一件事有衝突的觀點，不互相覆蓋。

2. **GraphRAG 不再只是輔助外掛，而是「系統唯一的推理編譯器」**：
   - 廢除所有的 `LIKE %` 傳統 SQL fallback 機制。
   - 所有的 Report、Query 與 Agent 決策，強制轉換為 Subgraph Traversal。

3. **引入「網絡科學審查演算法 (NetworkX Topo-Auditor)」**：
   - 任何推導出的潛在隱藏人物，必須通過圖論計算驗證（如結構洞、中介中心性）。
   - **防禦機制**：為避免 SQLite 算圖論導致效能崩潰，全系統強制採用「DB 取出、NetworkX 記憶體內計算、寫回資料庫」的架構。

4. **防禦「冷啟動死亡螺旋 (Cold Start Bootstrapping)」的代理約束機制**：
   - Agent 生成原則上必須 100% 依賴圖譜證據。
   - **特例協議**：當圖譜極度稀疏（如初期節點數 < 50）時，自動開啟「Bootstrapping 模式」，允許大模型低信心度臨時生成角色來激活社群；豐富後即自動關閉生造功能。

---

## 3. 全新 10 大技術優先項目 (Next-Gen Priorities)

1. ✅ **統一與精簡 Ingestion Pipeline**：廢除 hard-coded data，單一標準寫入資料庫。
2. ✅ **帶有相容機制的 Schema 重構**：升級 Database 支援 雙層機制與 `source_agent_id`，並撰寫 `ALTER TABLE` 腳本以防現有 `.db` 損毀。
3. ✅ **開發 Strict Multi-dimensional GraphRAG**：廢止 fallback，實裝矛盾檢測 (Contradiction Detection)。
4. ✅ **實裝避險防呆的 Graph-Constrained 代理生成器**：引入「節點數守門員」，確保冷啟動不卡死，穩定後強制證據對齊。
5. ✅ **重構隱藏角色發現演算法**：結合 NetworkX 記憶體運算與 LLM 推理審查暗樁。
6. ✅ **建構動態回流閉環 (Simulation-to-Graph Loop)**：讓每一輪互動，即時轉換回對應 Agent 視角的 Belief Graph 權重變動。
7. ✅ **嚴謹的 Database Schema 合約修復**：徹底對齊 `agent_memory` 與 `relationship_memory`。
8. ✅ **打造標準化基準框架**：建立 5 條合成資料集路徑，量化 Node F1 與 Edge F1。
9. ✅ **UI/UX 證據透視鏡 (Evidence X-ray)**：在前端實作「一鍵展開證據樹/圖」功能，可視化每句話的圖譜支援路徑。
10. ✅ **部署穩定化與可觀測性**：建立非同步 Job Queue 對抗大併發，並追蹤狀態。

---

## 4. 6 週超越計劃：通往「系統霸權」的路線圖 (6-Week Supremacy Roadmap)

### ✅ 第 1~1.5 週：The Great Refactoring (大收斂與統一) — **已完成**
- **行動**：合併 `api/graph.py` 與 `services/graph_builder.py`。徹底移除 hard-coded graph 邏輯。

### ✅ 第 2~3 週：Dual-Layer Graph & Core Retrieval (雙層視角圖譜與無盲區檢索) — **已完成**
- **行動**：寫入安全 Migration 腳本，改變 Schema 支援 Temporal, Confidence 與 Source Agent。開發完成 Strict Subgraph Query。
- **完成**：Schema migration 與 Phase 3 Strict GraphRAG / Subgraph Query 已上線，實裝了真相與信念的矛盾檢測。

### ✅ 第 4 週：Autonomy & Rigorous Discovery (嚴謹推理與代理冷啟動) — **已完成**
- **行動**：實裝 NetworkX 計算機制與 Validator Agent。設定並上線冷啟動例外協議，正式啟動 Latent Actor Discovery 2.0。

### ✅ 第 5 週：The Micro-Macro Loop (微觀認知與宏觀版圖閉環) — **已完成**
- **行動**：將模擬之互動轉換為 Belief Graph 上的動態 Edge 並標註觀點擁有者。強化 Report Agent 解讀衝突的能力。

### ✅ 第 6 週：Benchmarks & Showpiece UI (展示絕對統治力) — **已完成**
- **行動**：完成 5 大量化基準評測。前端全面上線「證據透視鏡 (Evidence X-ray)」。
- **完成**：已實裝 `BenchmarkingService` 與合成場景腳本；前端已實裝 Evidence X-ray 標籤解析與點擊跳轉圖譜定位功能。

---

## 5. 顛覆性的評估標準 (Disruptive Evaluation Metrics)

1. **Truth vs Context Separation (事實與前設隔離率)**
2. **Latent Actor Precision-Recall with Constraints (受拓樸約束的隱藏角色準確率)**
3. **Graph Impact of Simulation (模擬的圖譜實質影響度)**
4. **End-to-End Auditability (100% 端到端可審計度)**

---

## 6. AI 執行指令手冊 (AI Execution Playbook)

> **給 AI 開發的系統級指示**：這部分包含了避險策略與具體的技術實作限制。當你要指派 AI 動工時，請直接抽取下列提示詞。

### ✅ Phase 1: 統一圖譜攝取管道 (Ingestion Unification) — **已完成**

**已完成變更：**
- `backend/app/api/graph.py`：刪除 ~370 行 hardcoded `_HK_PROPERTY_NODES`、`_HK_PROPERTY_EDGES` 及 `_persist_graph()` 函式；`POST /graph/build` 對所有模式（HK + kg_driven）統一用 `TextProcessor → SeedGraphInjector → ImplicitStakeholderService → MemoryInitializationService` 路徑
- `backend/app/services/graph_builder.py`：移除 `hk_data: dict[str, Any]` 參數，entity extraction 純 LLM
- `backend/app/services/entity_extractor.py`：移除 `hk_data` 參數
- `backend/prompts/ontology_prompts.py`：移除 `{hk_data_json}` 段落
- `backend/app/api/simulation.py`、`backend/tests/test_pipeline_verification.py`：移除 `hk_data={}` kwarg

**結果：** `entity_types` / `relation_types` 永遠從 DB `DISTINCT` 查詢；`existing_for_dedup` 永遠來自 DB；無任何靜態字典殘留。

### ✅ Phase 2: 雙層認知圖譜資料庫重構與安全遷移 (Safe Schema Migration) — **已完成**

**已完成變更：**
- `backend/database/schema.sql`：`kg_nodes` 與 `kg_edges` 各加入 3 個新欄位：
  - `layer_type TEXT NOT NULL DEFAULT 'truth'`（Truth vs Belief 雙層）
  - `confidence_score REAL NOT NULL DEFAULT 1.0`（0.1 = bootstrapped，1.0 = 種子事實）
  - `source_agent_id TEXT DEFAULT NULL`（Belief 層邊緣的發出 Agent）
- `backend/app/utils/db.py`：在 `apply_migrations()` 加入 6 條向後相容 `ALTER TABLE`，用現有 `try/except "duplicate column name"` 機制保護，現有 `.db` 升級零崩潰
- `backend/app/services/relationship_memory.py`：修復 `retrieve_relationship_memories` 錯誤列名 `content` → `memory_text`、`salience` → `salience_score`；輸出 dict key 保持不變供 callers 使用

**結果：** 所有現有 `.db` 檔案自動獲得新欄位（預設 truth/1.0/NULL）；雙層圖譜架構 DB 基礎就緒。

### ✅ Phase 3: 嚴格高維 GraphRAG 主幹化 (Strict GraphRAG Enforcement) — **已完成**
- **目標檔案**：`backend/app/services/graph_rag.py`, `backend/app/services/report_agent.py`
- **已完成變更**：
  - 廢除 `ReportAgent` 中所有 `LIKE %` 基礎文字搜尋，強制調用 `semantic_subgraph_query`。
  - 在 `semantic_subgraph_query` 實裝「多視角衝突檢測」，主動對比 Truth 層與不同 Agent 的 Belief 層矛盾。
  - 全局敘事生成器 (`get_global_narrative`) 加入事實 vs 信念的對立分析。

### ✅ Phase 4: 記憶體內拓樸計算與冷啟動保護 (NetworkX Topo-Auditor & Cold Start) — **已完成**
- **目標檔案**：`frontend` (不適用), `backend/app/services/implicit_stakeholder_service.py`, `backend/app/utils/graph_metrics.py`, `backend/app/services/kg_agent_factory.py`
- **已完成變更**：
  - 新增 `graph_metrics.py`：將 SQLite 資料讀入記憶體轉為 NetworkX 物件，計算 Brokerage 與 Hole 指標。
  - 更新 `ImplicitStakeholderService`：整合 NetworkX 拓樸分析篩選 Latent Actors。
  - 更新 `KGAgentFactory`：實裝節點數守門員（< 50 允許 LLM 聯想，>= 50 強制證據對齊）。

### ✅ Phase 5: 動態圖譜回流 (The Micro-Macro Loop) — **已完成**
- **目標檔案**：`backend/app/services/simulation_runner.py`, `backend/app/services/simulation_hooks_kg_driven.py`
- **已完成變更**：
  - 在 `simulation_hooks_kg_driven.py` 實裝 `_kg_graph_feedback_loop`。
  - 監測模擬中顯著的信任變動（Trust > 0.7 或 < -0.7），將其回寫至 `kg_edges` 作為 `layer_type='belief'` 邊緣。
  - 在 `SimulationRunner` 的 Round Hook 管道中激活此回流機制。

### ✅ Phase 7: 部署穩定化與可觀測性 (Deployment Stability & Observability) — **已完成**
- **目標檔案**：`backend/app/services/simulation_worker.py`, `backend/app/services/simulation_manager.py`, `backend/app/api/simulation.py`, `backend/app/__init__.py`
- **已完成變更**：
  - **實裝持久化 Job 佇列**：新增 `simulation_jobs` 表與 `SimulationWorker` 背景服務。
  - **併發控制與排隊**：實裝 `MAX_CONCURRENT_SIMULATIONS` (預設 3)，溢出請求進入 `pending` 狀態。
  - **故障恢復 (Zombie Reaping)**：應用程式啟動時自動將停滯的 `running` 任務標記為 `interrupted`。
  - **可觀測性 API**：新增 `/admin/queue` 與 `/admin/jobs/{id}/cancel` 管理端點。
  - **心跳機制**：模擬執行中會定期更新 Job 心跳時間以供監控。
