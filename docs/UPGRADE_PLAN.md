# Murmura 升級計劃

**版本目標：** 品牌統一、全站雙語、每步驟模型設定、教學重建  
**執行方式：** 逐 Phase 完成，每完成一個 Phase 在對應核取方塊打勾  
**品牌名稱：** Murmura（全站統一，不再使用 MurmuraScope）

---

## 進度總覽

- [x] Phase 1 — 品牌統一（Logo + 名稱）
- [x] Phase 2a — i18n 基礎設施
- [x] Phase 2b — 語言切換按鈕
- [x] Phase 2c — 全站翻譯（繁中 + 英文）
- [x] Phase 3a — 後端每步驟模型函數
- [x] Phase 3b — 前端 Settings 模型 UI 重設計
- [x] Phase 3c — 每步驟模型 API 驗證
- [x] Phase 4 — 教學頁面重建

---

## Phase 1 — 品牌統一

**目標：** 全站移除舊名「Morai」/「MurmuraScope」，統一為「Murmura」，並套用新 Logo。

**Logo 來源：** `/Volumes/4TB/francistam/Downloads/Gemini_Generated_Image_hs5xvjhs5xvjhs5x.png`

### 步驟

- [ ] **1.1** 複製 logo 圖片至前端資產目錄
  ```bash
  cp "/Volumes/4TB/francistam/Downloads/Gemini_Generated_Image_hs5xvjhs5xvjhs5x.png" \
     frontend/src/assets/logo.png
  ```

- [ ] **1.2** `frontend/index.html` — 更新頁面標題
  ```html
  <!-- 改前 -->
  <title>Morai</title>
  <!-- 改後 -->
  <title>Murmura</title>
  ```

- [ ] **1.3** `frontend/src/App.vue` — header 品牌區改用 Logo 圖片
  ```html
  <!-- 改前 -->
  <span class="logo">⬡</span>
  <span class="brand">Morai</span>

  <!-- 改後 -->
  <img src="@/assets/logo.png" class="brand-logo" alt="Murmura" />
  ```
  CSS 補充（`.brand-logo`）：
  ```css
  .brand-logo {
    height: 32px;
    width: auto;
    object-fit: contain;
  }
  ```

- [ ] **1.4** `frontend/src/views/Landing.vue` — 兩處改名
  - nav logo：`MORAI` → `MURMURA`
  - hero 文字：`Feed Morai a sentence` → `Feed Murmura a sentence`

- [ ] **1.5** `frontend/src/views/Home.vue` — hero 標題
  - `<h1 class="hero-title">Morai</h1>` → `<h1 class="hero-title">Murmura</h1>`

- [ ] **1.6** `frontend/src/views/Learn.vue` — subtitle
  - `了解 Morai 背後嘅原理` → `了解 Murmura 背後的原理`

- [ ] **1.7** 驗證：搜尋是否還有殘留
  ```bash
  grep -r "Morai\|MORAI\|MurmuraScope" frontend/src --include="*.vue" --include="*.js" --include="*.html"
  ```
  預期結果：**零筆**

**完成條件：** 啟動前端，目視確認 header、Landing、Home、Learn 頁面均顯示 Murmura + Logo

---

## Phase 2a — i18n 基礎設施

**目標：** 安裝 vue-i18n@9，建立翻譯結構，讓全站支援繁體中文與英文切換。

### 步驟

- [ ] **2a.1** 安裝 vue-i18n
  ```bash
  cd frontend && npm install vue-i18n@9
  ```

- [ ] **2a.2** 建立目錄結構
  ```
  frontend/src/i18n/
    index.js      ← createI18n 設定
    zh-TW.js      ← 繁體中文翻譯表
    en-US.js      ← 英文翻譯表
  ```

- [ ] **2a.3** 建立 `frontend/src/i18n/index.js`
  ```js
  import { createI18n } from 'vue-i18n'
  import zhTW from './zh-TW.js'
  import enUS from './en-US.js'

  const savedLocale = localStorage.getItem('murmura_locale') || 'zh-TW'

  export const i18n = createI18n({
    legacy: false,
    locale: savedLocale,
    fallbackLocale: 'zh-TW',
    messages: {
      'zh-TW': zhTW,
      'en-US': enUS,
    },
  })
  ```

- [ ] **2a.4** 建立 `frontend/src/i18n/zh-TW.js`（初始骨架）
  ```js
  export default {
    nav: {
      home: '首頁',
      workspace: '工作區',
      learn: '教學',
      about: '關於',
      settings: '設定',
    },
    // ... 各頁面翻譯在 Phase 2c 填入
  }
  ```

- [ ] **2a.5** 建立 `frontend/src/i18n/en-US.js`（初始骨架）
  ```js
  export default {
    nav: {
      home: 'Home',
      workspace: 'Workspace',
      learn: 'Learn',
      about: 'About',
      settings: 'Settings',
    },
    // ... 各頁面翻譯在 Phase 2c 填入
  }
  ```

- [ ] **2a.6** 在 `frontend/src/main.js` 注入 i18n
  ```js
  import { i18n } from './i18n/index.js'
  // ...
  app.use(i18n)
  ```

**完成條件：** `npm run dev` 無報錯，`$t('nav.home')` 可在 Vue DevTools 中解析

---

## Phase 2b — 語言切換按鈕

**目標：** 在導航欄加入 [繁中 | EN] 切換按鈕，點擊即時切換全站語言並持久化。

### 步驟

- [ ] **2b.1** `frontend/src/App.vue` — 加入語言切換邏輯
  ```js
  import { useI18n } from 'vue-i18n'

  const { locale } = useI18n()

  function setLocale(lang) {
    locale.value = lang
    localStorage.setItem('murmura_locale', lang)
  }
  ```

- [ ] **2b.2** `frontend/src/App.vue` — header-nav 加入按鈕
  ```html
  <!-- 放在 ⚙ 設定連結左側 -->
  <div class="lang-toggle">
    <button
      class="lang-btn"
      :class="{ active: locale === 'zh-TW' }"
      @click="setLocale('zh-TW')"
    >繁中</button>
    <span class="lang-divider">|</span>
    <button
      class="lang-btn"
      :class="{ active: locale === 'en-US' }"
      @click="setLocale('en-US')"
    >EN</button>
  </div>
  ```

- [ ] **2b.3** 加入樣式
  ```css
  .lang-toggle {
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .lang-btn {
    background: none;
    border: none;
    font-size: 13px;
    font-weight: 600;
    color: var(--text-muted);
    padding: 4px 6px;
    border-radius: var(--radius-sm);
    cursor: pointer;
    transition: color 0.15s;
  }
  .lang-btn:hover,
  .lang-btn.active {
    color: var(--text-primary);
  }
  .lang-btn.active {
    color: var(--accent);
  }
  .lang-divider {
    color: var(--border);
    font-size: 12px;
  }
  ```

- [ ] **2b.4** `frontend/src/views/Landing.vue` — 同樣加入語言切換按鈕（Landing 有獨立 nav）

**完成條件：** 點擊「EN」導航欄文字切換為英文；點擊「繁中」切換回中文；重新整理頁面後語言設定保留

---

## Phase 2c — 全站翻譯

**目標：** 將全站所有硬編碼字串替換為 `$t()` / `t()` 翻譯函數，並在 `zh-TW.js` 和 `en-US.js` 中補全所有翻譯條目。

**翻譯規範：**
- 繁體中文：標準書面語（非廣東話口語）
- 英文：清晰、簡潔、科技感
- key 命名：`模組.區塊.項目`（例如 `settings.model.agentProvider`）

### 2c-1 App.vue（導航欄）

- [ ] 替換所有 `<router-link>` 文字
  ```html
  <router-link to="/">{{ $t('nav.home') }}</router-link>
  <router-link to="/app">{{ $t('nav.workspace') }}</router-link>
  <router-link to="/learn">{{ $t('nav.learn') }}</router-link>
  <router-link to="/landing">{{ $t('nav.about') }}</router-link>
  ```
- [ ] 翻譯條目加入 `zh-TW.js` / `en-US.js`（`nav` 命名空間）

---

### 2c-2 Home.vue（首頁）

- [ ] 替換 hero 區所有文字（標題、副標題、按鈕、預設值標籤）
- [ ] 替換 DomainPack 選擇器文字
- [ ] 替換 preset 快速選擇標籤（快速、標準、深度）
- [ ] 替換錯誤訊息、拖放提示文字
- [ ] 翻譯條目加入 `home` 命名空間

---

### 2c-3 Landing.vue（關於頁）

- [ ] 替換 hero 文字（標題、副標題、CTA 按鈕）
- [ ] 替換 5 步驟說明（num、label、title、desc）
- [ ] 替換 features 卡片（title + desc，6 張）
- [ ] 替換統計數字說明文字
- [ ] 翻譯條目加入 `landing` 命名空間

---

### 2c-4 Process.vue（5步工作流）

- [ ] 替換步驟導航標籤（Step 1–5 標題）
- [ ] 替換各步驟內說明文字、按鈕、狀態文字
- [ ] 翻譯條目加入 `process` 命名空間

---

### 2c-5 Settings.vue（設定頁）

- [ ] 替換 Tab 標籤（API 金鑰、模型選擇、模擬預設、介面偏好、資料來源）
- [ ] 替換所有表單標籤、提示文字、狀態訊息
- [ ] 替換按鈕文字（儲存、測試、顯示/隱藏）
- [ ] 翻譯條目加入 `settings` 命名空間

---

### 2c-6 Workspace.vue

- [ ] 替換頁面標題、按鈕、空狀態文字
- [ ] 翻譯條目加入 `workspace` 命名空間

---

### 2c-7 Step 組件（Step1–5）

- [ ] `Step1GraphBuild.vue` — 所有 UI 文字
- [ ] `Step2EnvSetup.vue` — 所有 UI 文字
- [ ] `Step3Simulation.vue` — 所有 UI 文字
- [ ] `Step4Report.vue` — 所有 UI 文字
- [ ] `Step5Interaction.vue` — 所有 UI 文字
- [ ] 翻譯條目加入 `steps` 命名空間

---

### 2c-8 共用組件

- [ ] `SimulationHeader.vue`
- [ ] `StepProgress.vue`
- [ ] `PresetSelector.vue`
- [ ] `DemoModeBanner.vue`
- [ ] `EmptyState.vue`
- [ ] `OnboardingTooltip.vue`
- [ ] `DomainBuilder.vue`
- [ ] 翻譯條目加入 `components` 命名空間

---

### 2c-9 其他 Views

- [ ] `Workspace.vue`
- [ ] `Report.vue`
- [ ] `SimulationRun.vue`
- [ ] `GodViewTerminal.vue`（可保留部分英文技術詞彙）
- [ ] `GraphExplorer.vue`
- [ ] `Interaction.vue`
- [ ] `PublicReport.vue`
- [ ] 翻譯條目加入對應命名空間

---

### 2c-10 錯誤訊息 / 動態文字

- [ ] 所有 `ref('')` 驅動的錯誤訊息字串（如 `quickStartError.value = '不支援...'`）
- [ ] 所有 `alert()` / `console.warn()` 可見文字（如有）
- [ ] API 錯誤回顯文字
- [ ] 翻譯條目加入 `errors` 命名空間

**完成條件：**
```bash
# 切換語言後全站無任何硬編碼中文或英文殘留
# 執行以下檢查應零結果（翻譯 key 本身除外）
grep -r '>[^<{]*[\u4e00-\u9fff]' frontend/src --include="*.vue" | grep -v "i18n\|//\|<!--"
```

---

## Phase 3a — 後端每步驟模型函數

**目標：** 在後端加入每步驟模型解析邏輯，並將各服務接入對應步驟的模型設定。

### 步驟

- [ ] **3a.1** `backend/app/utils/llm_client.py` — 新增 `get_step_provider_model()`

  在 `get_report_provider_model()` 之後加入：
  ```python
  # Step keys mapping
  _STEP_KEYS: dict[int, str] = {
      1: "step1",   # Graph Build
      2: "step2",   # Env Setup
      3: "step3",   # Simulation (agent)
      4: "step4",   # Report
      5: "step5",   # Interaction
  }

  def get_step_provider_model(step: int) -> tuple[str, str]:
      """Return (provider, model) for the given workflow step.

      Priority: step-specific RuntimeSettings → step-global fallback:
        Steps 1, 2, 3, 5  → falls back to get_agent_provider_model()
        Step 4             → falls back to get_report_provider_model()
      """
      prefix = _STEP_KEYS.get(step)
      if prefix is None:
          return get_agent_provider_model()
      provider = _rs_get(f"{prefix}_llm_provider")
      model    = _rs_get(f"{prefix}_llm_model")
      if not provider or not model:
          return get_report_provider_model() if step == 4 else get_agent_provider_model()
      return provider, model


  def get_step3_lite_model() -> tuple[str, str]:
      """Return (provider, lite_model) for Step 3 background agents.

      Falls back to get_agent_model(is_stakeholder=False).
      """
      provider   = _rs_get("step3_llm_provider") or get_agent_provider_model()[0]
      lite_model = _rs_get("step3_llm_model_lite") or _rs_get("agent_llm_model_lite")
      if not lite_model:
          return get_agent_model(is_stakeholder=False)
      return provider, lite_model
  ```

- [ ] **3a.2** 接入 Step 1 — 知識圖譜建構

  影響文件：
  - `backend/app/services/entity_extractor.py`
  - `backend/app/services/implicit_stakeholder_service.py`

  改動模式：
  ```python
  # 改前
  provider, model = get_agent_provider_model()
  # 改後
  from backend.app.utils.llm_client import get_step_provider_model
  provider, model = get_step_provider_model(1)
  ```

- [ ] **3a.3** 接入 Step 2 — 環境設置

  影響文件：
  - `backend/app/services/zero_config_service.py`
  - `backend/app/services/kg_agent_factory.py`

  ```python
  provider, model = get_step_provider_model(2)
  ```

- [ ] **3a.4** 接入 Step 3 — 模擬運行

  影響文件：
  - `backend/app/services/cognitive_agent_engine.py`
  - `backend/app/services/simulation_hooks_kg.py`
  - `backend/app/services/simulation_hooks_hk.py`

  ```python
  # 主力 agent
  provider, model = get_step_provider_model(3)
  # 背景 agent (is_stakeholder=False 的位置)
  provider, model = get_step3_lite_model()
  ```

- [ ] **3a.5** 接入 Step 4 — 報告生成

  影響文件：
  - `backend/app/services/report_service.py`（或 `react_report.py`）

  ```python
  provider, model = get_step_provider_model(4)
  ```

- [ ] **3a.6** 接入 Step 5 — 互動

  影響文件：
  - `backend/app/services/interview_engine.py`
  - `backend/app/services/narrative_analyst.py`

  ```python
  provider, model = get_step_provider_model(5)
  ```

- [ ] **3a.7** 補充單元測試
  ```python
  # backend/tests/unit/test_step_model_routing.py
  # 測試：有 RuntimeSettings override → 返回 override 值
  # 測試：無 override → 正確 fallback 至 global 設定
  # 測試：step4 fallback → report model（非 agent model）
  ```

**完成條件：** `make test-file F=test_step_model_routing` 全部通過

---

## Phase 3b — 前端 Settings 模型 UI 重設計

**目標：** 將 Settings 頁面「模型選擇」Tab 改為每步驟卡片設計，支援即時儲存及連線驗證。

### 步驟

- [ ] **3b.1** `frontend/src/views/Settings.vue` — 擴展 `settings` 資料結構

  加入 `llm.steps` 物件（在 `useSettings.js` 或 Settings.vue script 中）：
  ```js
  const stepDefs = [
    { step: 1, label: 'Step 1：知識圖譜建構', hint: '建議：速度快的模型，如 deepseek-v3' },
    { step: 2, label: 'Step 2：環境設置', hint: '建議：推理能力強的模型' },
    { step: 3, label: 'Step 3：模擬運行', hint: '主力 agent 用強模型；背景 agent 可用精簡模型節省費用' },
    { step: 4, label: 'Step 4：報告生成', hint: '建議：長文生成能力強，如 Gemini Pro' },
    { step: 5, label: 'Step 5：互動', hint: '建議：對話能力佳的模型' },
  ]

  const stepDraft = ref(
    Object.fromEntries([1,2,3,4,5].map(s => [s, { provider: '', model: '', model_lite: '', testStatus: null, testMsg: '' }]))
  )
  ```

- [ ] **3b.2** 快速套用按鈕邏輯
  ```js
  const quickApplyPresets = {
    deepseek: { provider: 'openrouter', model: 'deepseek/deepseek-v3.2' },
    gemini:   { provider: 'google',     model: 'gemini-2.5-pro-preview' },
    gpt4o:    { provider: 'openai',     model: 'gpt-4o' },
  }

  function applyPreset(presetKey) {
    const p = quickApplyPresets[presetKey]
    for (const s of [1,2,3,4,5]) {
      stepDraft.value[s].provider = p.provider
      stepDraft.value[s].model    = p.model
    }
  }
  ```

- [ ] **3b.3** 「模型選擇」Tab 新 HTML 結構
  ```html
  <!-- 快速套用 -->
  <div class="quick-apply-bar">
    <span class="qa-label">{{ $t('settings.model.quickApply') }}</span>
    <button @click="applyPreset('deepseek')">DeepSeek 全套</button>
    <button @click="applyPreset('gemini')">Gemini 全套</button>
    <button @click="applyPreset('gpt4o')">GPT-4o 全套</button>
  </div>

  <!-- 每步驟卡片 -->
  <div v-for="def in stepDefs" :key="def.step" class="step-model-card">
    <div class="step-card-header">
      <span class="step-badge">{{ def.step }}</span>
      <h3>{{ def.label }}</h3>
    </div>
    <p class="step-hint">{{ def.hint }}</p>

    <div class="step-model-fields">
      <div class="form-field">
        <label>Provider</label>
        <select v-model="stepDraft[def.step].provider">
          <option v-for="opt in providerOptions" :value="opt.value">{{ opt.label }}</option>
        </select>
      </div>
      <div class="form-field">
        <label>Model</label>
        <input v-model="stepDraft[def.step].model" placeholder="e.g. deepseek/deepseek-v3.2" />
      </div>
      <!-- Step 3 額外顯示 Lite Model 欄 -->
      <div v-if="def.step === 3" class="form-field">
        <label>背景 Agent Model（精簡）</label>
        <input v-model="stepDraft[def.step].model_lite" placeholder="留空則沿用主力模型" />
      </div>
    </div>

    <div class="step-card-actions">
      <button class="btn-secondary" @click="testStepModel(def.step)">
        <span v-if="stepDraft[def.step].testStatus === 'testing'">⏳ 測試中…</span>
        <span v-else>測試連線</span>
      </button>
      <button class="btn-primary" @click="saveStepModel(def.step)">儲存</button>
    </div>

    <div v-if="stepDraft[def.step].testStatus" class="test-result" :class="`test-${stepDraft[def.step].testStatus}`">
      <span v-if="stepDraft[def.step].testStatus === 'ok'">✓ {{ stepDraft[def.step].testMsg }}</span>
      <span v-else-if="stepDraft[def.step].testStatus === 'error'">✗ {{ stepDraft[def.step].testMsg }}</span>
    </div>
  </div>
  ```

- [ ] **3b.4** `saveStepModel(step)` 函數
  ```js
  async function saveStepModel(step) {
    const d = stepDraft.value[step]
    const payload = {
      [`step${step}_llm_provider`]: d.provider,
      [`step${step}_llm_model`]:    d.model,
    }
    if (step === 3 && d.model_lite) {
      payload['step3_llm_model_lite'] = d.model_lite
    }
    // PUT /api/settings — 現有 saveSettings() 機制
    await saveSettings(payload)
  }
  ```

- [ ] **3b.5** `testStepModel(step)` 函數
  ```js
  async function testStepModel(step) {
    const d = stepDraft.value[step]
    d.testStatus = 'testing'
    d.testMsg = ''
    try {
      const res = await testApiKey(d.provider, null, d.model)  // Phase 3c 擴展
      d.testStatus = res.data.success ? 'ok' : 'error'
      d.testMsg    = res.data.message
    } catch (err) {
      d.testStatus = 'error'
      d.testMsg    = err.response?.data?.detail || '連線失敗'
    }
  }
  ```

- [ ] **3b.6** 頁面載入時從 `GET /api/settings` 填入已儲存的 step 設定
  ```js
  onMounted(async () => {
    await loadSettings()
    for (const s of [1,2,3,4,5]) {
      const p = settings.value?.[`step${s}_llm_provider`]
      const m = settings.value?.[`step${s}_llm_model`]
      if (p) stepDraft.value[s].provider = p
      if (m) stepDraft.value[s].model = m
    }
  })
  ```

**完成條件：** Settings > 模型選擇，每個步驟可獨立設定 Provider + Model，儲存後重啟後端仍保留設定

---

## Phase 3c — 每步驟模型 API 驗證擴展

**目標：** `POST /api/settings/test-key` 支援傳入 `model` 參數，驗證指定 provider + model 組合是否可用。

### 步驟

- [ ] **3c.1** 找到 `test-key` endpoint，擴展請求 schema
  ```python
  class TestKeyRequest(BaseModel):
      provider: str
      api_key: str | None = None   # None = 使用已儲存的 key
      model: str | None = None     # 若提供，驗證此 model 是否存在
  ```

- [ ] **3c.2** 驗證邏輯：若 `model` 不為 None，發送一個 minimal LLM 請求
  ```python
  async def _test_provider_model(provider: str, api_key: str, model: str) -> tuple[bool, str]:
      """Send a minimal 1-token request to verify model availability."""
      try:
          client = LLMClient(provider=provider, api_key=api_key, model=model)
          await client.chat([{"role": "user", "content": "hi"}], max_tokens=1)
          return True, f"Model {model} 驗證成功"
      except Exception as e:
          return False, f"Model 不可用：{str(e)[:100]}"
  ```

- [ ] **3c.3** 前端 `api/settings.js` 更新 `testApiKey()` 函數簽名
  ```js
  export async function testApiKey(provider, apiKey, model = null) {
    return axios.post('/api/settings/test-key', {
      provider,
      api_key: apiKey,
      model,
    })
  }
  ```

**完成條件：** 在 Settings 中輸入不存在的 model 名稱，點「測試連線」返回清晰錯誤訊息

---

## Phase 4 — 教學頁面重建

**目標：** 將所有課程由廣東話改為標準繁體中文，加入英文翻譯，並更新內容至最新版功能。

**翻譯語言規範：**
- 繁中：書面語，不用「咁」「喎」「唔」等粵語詞彙
- 英文：精確、科技感，技術術語用英文原文

### 步驟

- [ ] **4.1** `frontend/src/views/Learn.vue`
  - subtitle 改為 `$t('learn.subtitle')`（繁中：`了解 Murmura 背後的原理` / EN：`How Murmura Works`）
  - 課程 Tab 標題改用 `$t()` — 由 `useLessonData.js` 提供 key

- [ ] **4.2** `frontend/src/composables/useLessonData.js`
  - 課程標題改為翻譯 key：
    ```js
    export const lessonKeys = [
      { id: 0, key: 'lessons.overview',     icon: '🔮' },
      { id: 1, key: 'lessons.emergence',    icon: '🐦' },
      { id: 2, key: 'lessons.kg',           icon: '🕸️' },
      { id: 3, key: 'lessons.ner',          icon: '🔬' },
      { id: 4, key: 'lessons.shocks',       icon: '⚡' },
      { id: 5, key: 'lessons.percentiles',  icon: '📊' },
      { id: 6, key: 'lessons.uncertainty',  icon: '🎯' },
      { id: 7, key: 'lessons.challenges',   icon: '🤔' },
      { id: 8, key: 'lessons.mistakes',     icon: '⚠️' },
      { id: 9, key: 'lessons.datasources',  icon: '📊' },
      { id: 10, key: 'lessons.steps',       icon: '🗺️' },  // 新增
    ]
    ```

- [ ] **4.3** `LessonOverview.vue` — 更新 + 雙語化
  - 移除廣東話：「唔係問人」→「不是詢問」
  - 加入最新功能說明：OASIS 引擎、B2B 模式、5步工作流
  - 使用 `$t()` 翻譯所有文字

- [ ] **4.4** `LessonBoids.vue` — 雙語化
  - 廣東話 → 標準繁中
  - 英文版翻譯

- [ ] **4.5** `LessonKG.vue` — 雙語化
  - 廣東話 → 標準繁中
  - 英文版翻譯

- [ ] **4.6** `LessonNER.vue` — 雙語化
  - 廣東話 → 標準繁中

- [ ] **4.7** `LessonShocks.vue` — 更新 + 雙語化
  - 加入 B2B 供應鏈衝擊說明
  - 廣東話 → 標準繁中

- [ ] **4.8** `LessonPercentiles.vue` — 雙語化

- [ ] **4.9** `LessonUncertainty.vue` — 雙語化
  - 移除 `MurmuraScope` 舊名 → `Murmura`

- [ ] **4.10** `LessonChallenges.vue` — 更新 + 雙語化
  - 加入 Swarm Ensemble、Monte Carlo 說明

- [ ] **4.11** `LessonMistakes.vue` — 雙語化

- [ ] **4.12** `LessonDataSources.vue` — 更新 + 雙語化
  - 更新數據源：LanceDB（384-dim embeddings）、DuckDB（分析）、SQLite WAL（主要 DB）
  - 廣東話 → 標準繁中

- [ ] **4.13** 新增 `LessonSteps.vue` — 5步驟工作流詳細說明（雙語）
  - Step 1：Seed Text → Entity Extraction → Knowledge Graph
  - Step 2：Agent Factory → Profile Generation → Scenario Config
  - Step 3：OASIS Engine → Emergent Behavior → Round-by-Round Hooks
  - Step 4：ReACT Report → 3-Phase → PDF Export
  - Step 5：Interview Agents → Shock Injection → What-If Branches

- [ ] **4.14** 在 `zh-TW.js` / `en-US.js` 加入 `lessons` 命名空間的所有翻譯條目

- [ ] **4.15** 在 `Learn.vue` 的 `lessonComponents` 陣列加入 `LessonSteps`

**完成條件：** 切換語言後，所有課程標題和內容正確顯示對應語言；無廣東話口語殘留

---

## 附錄：快速驗證指令

```bash
# 確認無舊品牌名稱殘留
grep -r "Morai\|MORAI\|MurmuraScope" frontend/src --include="*.vue" --include="*.js"

# 確認無廣東話殘留（基本檢查）
grep -r "唔\|係咪\|喎\|咁\|囉\|囉\|啩" frontend/src --include="*.vue"

# 確認 i18n 覆蓋（中文硬編碼應接近零）
grep -rn '>\s*[^\s{<][^\x00-\x7F]' frontend/src --include="*.vue" | grep -v "<!--\|i18n"

# 確認後端每步驟模型函數存在
grep -n "get_step_provider_model\|get_step3_lite_model" backend/app/utils/llm_client.py

# 執行單元測試（模型路由）
make test-file F=test_step_model_routing

# 執行前端 build 確認無類型錯誤
cd frontend && npm run build
```

---

## 注意事項

1. **每個 Phase 完成後先 commit**，避免大改動混在一起難以回滾
2. **Phase 2c 工作量最大**，建議按頁面拆分多個 commit
3. **Phase 3a 後端改動**需注意不要破壞現有測試，先跑 `make test` 確認基線
4. **翻譯 key 統一格式**：`模組.區塊.項目`，加入翻譯前先確認 key 不重複
5. **Logo 顯示**：Landing 頁面有獨立 nav，需單獨處理 logo（不繼承 App.vue header）
