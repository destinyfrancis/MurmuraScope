export default {
  nav: {
    home: '首頁',
    workspace: '工作區',
    learn: '教學',
    about: '關於',
    report: '報告生成',
    godView: '上帝視角',
    settings: '設定',
  },
  godView: {
    header: {
      terminal: '上帝視角終端 (GOD VIEW)',
      selectSession: '-- 選擇模擬會話 --',
      loading: '載入中...',
      refresh: '重新整理',
      autoOn: '自動更新 開',
      autoOff: '自動更新 關',
      autoDelayed: '自動更新 (延遲)'
    },
    status: {
      signals: '市場訊號',
      active: '有效',
      buyYes: '買入 YES',
      buyNo: '買入 NO',
      hold: '觀望',
      contracts: '合約數量',
      lastRefreshed: '最後更新'
    },
    tabs: {
      main: '市場訊號',
      ensemble: '集成預測',
      scenarios: '情景比較',
      sentiment: '情緒熱圖'
    },
    panels: {
      contracts: {
        title: 'POLYMARKET 相關合約',
        loading: '正在獲取相關合約...',
        empty: '此會話沒有匹配的合約。'
      },
      signals: {
        title: '交易訊號',
        loading: '正在根據代理共識計算訊號...',
        empty: '尚未產生訊號。請確保模擬已完成至少 5 輪。'
      },
      consensus: {
        title: '代理共識',
        sentimentTrend: '情緒趨勢',
        signalBreakdown: '訊號詳情',
        recentDecisions: '最近決策',
        noData: '暫無數據',
        awaiting: '等待代理人決策中...'
      },
      feed: {
        title: '實時代理動態',
        empty: '尚未有代理活動。',
        posts: '則動態'
      }
    },
    placeholders: {
      selectSession: '請選擇一個模擬會話以開始',
      godViewDesc: '上帝視角終端顯示基於代理人共識的實時 Polymarket 交易訊號'
    }
  },
  interaction: {
    welcome: '歡迎進入深度交互模式。你可以針對報告內容提問，或者同個別代理人對話。',
    noResponse: '（無回應）',
    sendFailed: '發送失敗：',
    settings: {
      title: '對話設定',
      target: '對話對象',
      analyst: '報告分析師',
      agent: '指定代理人',
      selectAgent: '選擇代理人',
      selectPlaceholder: '請選擇...',
      whatIf: 'What-If 參數',
      whatIfHint: '喺對話中描述假設情景，例如「如果失業率升到 8%」'
    },
    chat: {
      you: '你',
      ai: 'AI',
      system: '系統',
      error: '錯誤',
      placeholder: '輸入你嘅問題...',
      sending: '發送中...',
      send: '發送'
    }
  },
  lessons: {
    overview: {
      traditional: {
        title: '傳統民調',
        points: [
          '詢問 1,000 人的看法',
          '靜態快照 — 一次性',
          '忽略社交影響力',
          '無法模擬政策變化'
        ],
        verdict: '有限'
      },
      murmura: {
        title: 'Murmura',
        points: [
          '模擬 500 個 AI 代理人互動',
          '動態演化 — 30+ 輪模擬',
          'Echo Chamber + 信任網絡',
          '即時注入政策衝擊'
        ],
        verdict: '湧現式預測'
      },
      text1: 'Murmura 不是詢問人們「你在想什麼」，而是利用 AI 代理人模擬真實的社會互動過程。每個代理人都有自己的性格、記憶、信任圈子，他們會互相影響，最終<strong>湧現</strong>出群體趨勢。',
      text2: '我們追蹤的指標包括：房價信心、移民意向、消費模式、政治極化度等。'
    },
    uncertainty: {
      intro: 'Murmura 的預測不確定性來自四個主要來源。點擊每個來源了解更多：',
      closing: '透明地呈現不確定性是負責任 AI 預測的核心原則。Murmura 不是「預言機」，而是幫助思考多個可能未來的工具。',
      sources: {
        behavior: { label: '代理人行為隨機性', detail: '每個 AI 代理人的 LLM 決策具有內在隨機性，無法完全控制。' },
        macro: { label: '宏觀數據誤差', detail: 'GDP、失業率等宏觀數據存在測量誤差與修訂，直接影響初始條件。' },
        model: { label: '模型結構假設', detail: '消費函數、信任衰減率等參數是由校準數據估計，具有統計不確定性。' },
        shocks: { label: '外部衝擊不可預測性', detail: '地緣政治事件、自然災害等外生衝擊無法提前納入模型。' }
      }
    },
    kg: {
      intro: '知識圖譜將複雜議題拆解成 <strong>實體</strong>（節點）與 <strong>關係</strong>（邊）。將滑鼠移到節點上方查看描述。',
      closing: '模擬過程中，代理人的行動會更新圖譜上的邊權重 — 反映因果關係強度的變化。',
      types: {
        economic: '經濟',
        person: '人物',
        policy: '政策',
        organization: '組織',
        social: '社會',
        location: '地點'
      },
      nodes: {
        hibor: 'HIBOR利率',
        mortgage: '按揭利率',
        prices: '樓價指數',
        buyers: '首置買家',
        tax: '印花稅',
        bank: '匯豐銀行',
        hardlife: '上車難',
        migration: '移民潮',
        shatin: '沙田',
        fed: '美聯儲'
      }
    },
    boids: {
      intro: '代理人行為遵循三條簡單規則，類似於鳥群飛行（Boids 理論）：',
      rules: {
        alignment: { title: '對齊性', desc: '與鄰居朝向相同方向（社會共識）。' },
        cohesion: { title: '凝聚力', desc: '向鄰居的平均位置靠攏（信任建立）。' },
        separation: { title: '分離性', desc: '避免與衝突實體過於接近（同溫層/回聲筒）。' }
      },
      closing: '沒有任何一隻鳥知道「群體隊伍」的概念 — 但隊形自然湧現。這就是 <strong>湧現 (Emergence)</strong>。',
      murmura: 'Murmura 同理 — 每個代理人只按自己的性格和記憶做決策，但整體會湧現出可預測的社會趨勢。'
    },
    ner: {
      intro: '每段種子文本都會經歷以下處理管道，最終成為知識圖譜中的節點與邊：',
      steps: ['原始文本', '分詞', 'NER 命名體識別', '關係抽取', 'KG 節點'],
      example: {
        label: '示例：',
        text: '「<strong>聯儲局</strong>宣布<strong>加息</strong> 0.25厘，影響<strong>香港樓市</strong>」',
        org: '聯儲局 (組織)',
        hike: '加息 (事件)',
        market: '香港樓市 (經濟)',
        announced: '宣布',
        affecting: '影響'
      },
      closing: '這個過程由 DeepSeek V3.2 驅動，自動識別實體類型與因果關係，構建結構化知識表示。'
    },
    shocks: {
      intro: '政策衝擊是 Murmura 系統的「壓力測試」。你可以在運行中的模擬中注入以下事件：',
      events: {
        interest_rate: { title: '加息衝擊', desc: '按揭利率突然上升 1%' },
        tax: { title: '撤銷印花稅', desc: '政府取消所有樓宇印花稅' },
        immigration: { title: '移民政策變動', desc: '推出全新計分制移民政策' }
      },
      text: '當注入衝擊時，代理人會重新評估他們的信念和信任網絡，導致整個系統產生「瀑布式」連鎖反應。'
    },
    percentiles: {
      intro: 'Murmura 不只輸出一條預測線，而是整個概率分佈。拖動滑桿調整情景強度：',
      chartLabel: '樓價信心指數預測',
      mild: '溫和衝擊',
      extreme: '極端衝擊',
      intensity: '情景強度',
      p10_90: 'p10–p90',
      p25_75: 'p25–p75',
      p50: 'p50 (中位數)',
      quiz: {
        q1: '問題 1：p50 代表什麼？',
        q1_opts: [
          { value: 'p50', label: '中位數預測' },
          { value: 'avg', label: '平均值' },
          { value: 'best', label: '最佳情景' }
        ],
        q1_correct: '正確！p50 即中位數，一半模擬結果高於此值，一半低於。',
        q1_wrong: '錯誤，p50 是中位數（第 50 百分位數），不是平均值。',
        q2: '問題 2：p10-p90 區間越寬代表什麼？',
        q2_opts: [
          { value: 'wide', label: '不確定性更高' },
          { value: 'certain', label: '預測更準確' },
          { value: 'same', label: '結果相同' }
        ],
        q2_correct: '正確！更寬的區間反映更高的預測不確定性。',
        q2_wrong: '錯誤，更寬的區間意味不確定性更高，不是更準確。'
      }
    },
    challenges: {
      intro: '模擬結果不應該被盲目接受。以下是 5 步批判性評估清單 — 每完成一步就剔一個：',
      allChecked: '全部完成！你已經掌握了批判性評估模型的方法。',
      reset: '重置',
      closing: '養成這 5 步習慣，可以幫助你避免過度依賴模型輸出，做出更明智的判斷。',
      assumptions: { label: '檢查假設', detail: '模型的初始假設是否合理？' },
      history: { label: '對比歷史', detail: '過去類似情境的結果如何？' },
      boundary: { label: '邊界測試', detail: '極端參數會產生什麼結果？' },
      counterfactual: { label: '反事實推理', detail: '如果某個因素不存在，結果會如何變化？' },
      omission: { label: '尋找遺漏', detail: '是否有重要因素被忽略？' }
    },
    mistakes: {
      intro: '在解讀 Murmura 模擬時，請避免以下常見誤區：',
      list: [
        { wrong: '模型顯示 70% 機率會下跌，所以一定會下跌', correct: '70% 機率代表 10 次中大約有 7 次會發生' },
        { wrong: 'p50 預測是最準確的', correct: 'p50 是中位數，真實結果可能在 p10-p90 之間' },
        { wrong: '代理人數量越多越準確', correct: '代理人的多樣性比數量更重要' },
        { wrong: '模型預測了黑天鵝事件', correct: '模型只能捕捉已知風險，真正的黑天鵝無法預測' },
        { wrong: '兩次模擬結果不同代表模型不可靠', correct: '隨機性是模型的特徵，而非缺陷' }
      ]
    },
    dataSources: {
      intro: 'Murmura 結合了高頻市場數據與低頻統計指標，以此奠定模擬的基礎：',
      category: '類別',
      items: '關鍵項目',
      frequency: '更新頻率',
      lag: '數據延遲',
      gov: { category: '政府統計', items: ['人口普查', '就業數據', '零售銷售'], frequency: '每月更新', lag: '約 2 個月' },
      finance: { category: '金融市場', items: ['恒生指數 (HSI)', '板塊指數', '成交量'], frequency: '實時', lag: '< 15 分鐘' },
      rates: { category: '利率數據', items: ['HIBOR', '聯儲局基準利率', 'USD/HKD'], frequency: '每日', lag: '1 個工作日' },
      social: { category: '社交媒體', items: ['RTHK 新聞', '論壇帖文', '輿情分析'], frequency: '每小時', lag: '< 1 小時' },
      macro: { category: '宏觀經濟', items: ['中國 GDP', 'CPI', '出口數據'], frequency: '每季', lag: '約 3 個月' }
    },
    meta: {
      t0: '系統預測什麼？',
      t1: '什麼是湧現？',
      t2: '知識圖譜入門',
      t3: '從證據到結構',
      t4: '從情景到結果',
      t5: '解讀概率預測',
      t6: '信心與不確定性',
      t7: '如何挑戰模型',
      t8: '常見錯誤',
      t9: '數據來源與局限'
    }
  },
  learn: {
    subtitle: '了解 Murmura 背後的原理'
  },
  home: {
    subtitle: '通用預測引擎',
    description: '投放任何種子文字——新聞、劇本、地緣政治事件——AI 自動構建世界、生成代理人並開始模擬。結合多智能體系統、知識圖譜與宏觀預測，預見集體行為。',
    startTitle: '立即開始預測',
    startSubtitle: '上傳文件或輸入種子文字，AI 自動構建世界並開始模擬',
    dropLabel: '拖放文件至此，或點擊選擇',
    dropHint: '支援 PDF、TXT、Markdown · 最大 10 MB',
    or: '或',
    textareaPlaceholder: '輸入場景描述，例如：聯準會宣布升息200個基點，全球股市出現恐慌性拋售...',
    questionPlaceholder: '（選填）你想預測什麼？例如：哪個陣營最終會佔主導？社會情緒走向如何？',
    launchBtn: '一鍵預測',
    launching: '啟動中...',
    customDomain: '自定義領域包',
    dataConnector: '數據連接器',
    godView: '上帝視角',
    presets: {
      fast: '快速',
      fastHint: '100 位代理人 · 15 輪模擬 (~2 分鐘)',
      standard: '標準',
      standardHint: '300 位代理人 · 20 輪模擬 (~8 分鐘)',
      deep: '深度',
      deepHint: '500 位代理人 · 30 輪模擬 (~20 分鐘)'
    },
    errors: {
      format: '不支援 {ext} 格式，請上傳 PDF、TXT 或 Markdown',
      size: '檔案超過 10 MB 上限',
      launch: '啟動失敗，請重試'
    }
  },
  onboarding: {
    skip: '跳過',
    next: '下一步',
    finish: '完成',
    steps: {
      scenario: { title: '選擇預測場景', desc: '從首頁選擇一個社會議題作為模擬預測的起點。' },
      graph: { title: '知識圖譜', desc: '系統會自動建立知識圖譜，展示議題中的因果關係。' },
      simulation: { title: '運行模擬', desc: '觀察 AI 代理人如何互動、做決策、形成社會趨勢。' }
    }
  },
  landing: {
    nav: {
      howItWorks: '運作原理',
      features: '核心功能',
      launch: '啟動引擎 →'
    },
    hero: {
      eyebrow: '通用預測引擎',
      title: '投放任何文字。',
      titleAccent: '模擬任何世界。',
      sub: '餵給 Murmura 一句話、一份文件或一個場景 —— 它會自動構建知識圖譜、生成代理人、運行模擬並預測集體結果。',
      cta: '開始預測',
      workspace: '工作區',
      stats: {
        agents: '單次運行代理人',
        macro: '宏觀經濟指標',
        monteCarlo: '蒙地卡羅試驗',
        xai: '可解釋 AI 工具'
      }
    },
    workflow: {
      label: '運作原理',
      title: '五步工作流',
      steps: {
        graph: { label: '圖譜', title: '知識圖譜', desc: '種子文字 → 實體提取 → 因果網絡自動構建' },
        env: { label: '環境', title: '環境設定', desc: '代理人工廠依據圖譜節點生成配置，無需手動設定' },
        sim: { label: '模擬', title: '動態模擬', desc: 'OASIS 多智能體引擎運行，完整捕捉湧現行為' },
        report: { label: '報告', title: 'ReACT 報告', desc: '三階段 LLM：大綱 → 多路工具調用 → 文檔組裝' },
        interact: { label: '互動', title: '深度互動', desc: '訪談代理人、注入衝擊、開拓「What-If」分支場景' }
      }
    },
    features: {
      label: '引擎能力',
      title: '我們的核心功能',
      list: {
        universal: { title: '通用模式', desc: '支援任何種子文字 —— 新聞、小說、地緣政治。引擎自動推斷代理人、決策、指標與衝擊。' },
        kg: { title: '知識圖譜', desc: 'GraphRAG 追蹤實體關係與因果鏈。每 5 輪生成快照，隨互動持續演化。' },
        emergence: { title: '湧現引擎', desc: '派系形成、臨界點、同溫層、病毒式傳播 —— 全部為自主湧現，而非預設腳本。' },
        monteCarlo: { title: '蒙地卡羅', desc: '100 次 LHS + t-Copula 採樣。Wilson 得分置信區間。支援高達 10,000 次隨機試驗。' },
        macro: { title: '宏觀回饋', desc: '每輪更新 11 個宏觀指標。代理人的微觀決策即時回饋至宏觀狀態。' },
        scenarios: { title: '場景分支', desc: '在任何輪次分叉模擬。並排比較不同時間線的演化結果。' }
      }
    },
    useCases: {
      label: '應用領域',
      title: '適用於任何領域',
      list: {
        geopolitics: { tag: '地緣政治', desc: '台海局勢演變、伊以衝突模擬、貿易戰連鎖反應' },
        finance: { tag: '金融', desc: '聯準會升息外溢效應、加密貨幣恐慌、企業競爭對抗' },
        society: { tag: '社會', desc: '政策影響建模、社會運動動態、人口結構變遷' },
        fiction: { tag: '虛構作品', desc: '《紅樓夢》、哈利波特、任何敘事世界' }
      }
    },
    cta: {
      label: '準備好開始模擬了嗎？',
      title: '投放你的第一個場景',
      sub: '無需配置。粘貼任何文字，剩下的交給引擎處理。',
      btn: '啟動引擎 →'
    },
    footer: {
      desc: '通用預測引擎 · 基於代理人的模擬技術',
      copy: '構建技術：FastAPI · Vue 3 · OASIS · LanceDB'
    }
  },
  process: {
    nav: {
      steps: {
        graph: { label: '圖譜構建', navLabel: 'GRAPH' },
        env: { label: '環境搭建', navLabel: 'ENV' },
        sim: { label: '開始模擬', navLabel: 'SIM' },
        report: { label: '報告生成', navLabel: 'REPORT' },
        interact: { label: '深度交互', navLabel: 'INTERACT' }
      },
      expressBadge: '⚡ 快速模式 · 已自動配置'
    },
    errors: {
      graphFirst: '請先完成圖譜構建',
      envFirst: '請先完成環境設置並啟動模擬',
      simFirst: '模擬完成後才可生成報告',
      reportFirst: '請先生成報告',
      engineUnavailable: '模擬引擎不可用 — 請使用 Docker 以獲得完整功能'
    }
  },
  settings: {
    header: {
      title: '設定',
      subtitle: '管理 API 金鑰、模型選擇及系統偏好設定'
    },
    tabs: {
      api: {
        title: 'API 金鑰',
        desc: '設定各 LLM 服務提供商的 API 金鑰。金鑰已加密儲存，顯示時僅顯示尾部 4 碼。',
        empty: '— 未設定 —',
        testing: '⏳ 測試中…',
        test: '測試',
        save: '儲存',
        verifying: '⏳ 正在驗證金鑰…',
        connFailed: '連線失敗'
      },
      model: {
        title: '模型選擇',
        desc: '為每個工作流步驟獨立設定 LLM 模型。儲存後即時生效，無需重啟伺服器。',
        quickApply: '快速套用：',
        globalFallback: '全域預設（各步驟未設定時使用）',
        steps: {
          useGlobal: '使用全域預設',
          fillBoth: '請填寫 Provider 和 Model',
          step1: { label: 'Step 1：知識圖譜建構', hint: '建議使用速度快的模型（如 deepseek-v3），此步驟呼叫頻繁' },
          step2: { label: 'Step 2：環境設置', hint: '建議使用推理能力強的模型，用於代理人格設定與場景分析' },
          step3: { label: 'Step 3：模擬運行', hint: '主力模型用於關鍵角色，精簡模型用於背景代理（節省費用）' },
          step4: { label: 'Step 4：報告生成', hint: '建議使用長文生成能力強的模型（如 Gemini Pro、GPT-4o）' },
          step5: { label: 'Step 5：互動分析', hint: '建議使用對話能力強的模型，用於 Interview Engine' },
        },
        agent: {
          title: '代理決策 LLM（全域）',
          providerHint: '代理思考、決策、發文所用的 LLM 提供商',
          main: 'Agent Model（主力）',
          mainHint: '一般 background agents 使用此較便宜的模型（可選）',
          lite: 'Agent Model（精簡）',
          liteHint: '一般 background agents 使用此較便宜的模型（可選）'
        },
        report: {
          title: '報告生成 LLM（全域）',
          providerHint: '最終報告、摘要、圖表分析所用的 LLM',
          model: '報告模型 (Report Model)',
          modelHint: '留空則使用該提供商的預設模型'
        }
      },
      sim: {
        title: '模擬預設',
        desc: '設定新建模擬時的預設參數。',
        preset: '預設 Preset',
        agents: '預設代理數量',
        agentsUnit: '位代理人',
        agentsHint: '建立新模擬時的預設代理數量（5–500）',
        concurrency: '並行限制 (Concurrency)',
        concurrencyHint: '同時執行 LLM 請求的最大數量。建議 30–80',
        domain: '預設 Domain Pack',
        domainHint: '新模擬套用的預設 Domain Pack ID'
      },
      ui: {
        title: '介面偏好',
        desc: '以下偏好儲存於本機（localStorage），即時生效。',
        lang: 'UI 語言',
        itemsPerPage: '每頁顯示數量',
        autoOpen: '模擬完成後自動開啟報告',
        autoOpenHint: '完成 simulation 後自動跳轉至報告頁面'
      },
      data: {
        title: '資料來源',
        desc: '設定外部數據源 API 金鑰及整合選項。',
        empty: '— 未設定 —',
        test: '測試',
        save: '儲存',
        verifying: '⏳ 正在驗證…',
        ref: '來自',
        fred: 'FRED API 金鑰',
        fredHint: '來自 <a href="https://fred.stlouisfed.org/docs/api/api_key.html" target="_blank" rel="noopener">St. Louis Fed</a>，用於獲取宏觀經濟數據',
        externalFeed: '啟用外部數據源',
        externalFeedHint: '啟用後系統將從 FRED、World Bank 等源定時更新數據',
        refreshInterval: '更新頻率',
        seconds: '秒',
        refreshHint: '每次自動更新的間隔（300–86400 秒）'
      }
    }
  },
  workspace: {
    title: '工作區',
    subtitle: '所有預測模擬 Session',
    adminBtn: '效能管理',
    newBtn: '+ 新預測',
    loading: '載入中...',
    retry: '重試',
    empty: {
      title: '尚未有預測',
      description: '建立你的第一個社會模擬預測'
    },
    status: {
      completed: '已完成',
      running: '運行中',
      failed: '失敗',
      pending: '等待中',
      created: '已建立'
    },
    meta: {
      agents: '位代理人',
      rounds: '輪模擬'
    },
    evidence: '證據搜尋',
    loadMore: '載入更多'
  }
}
