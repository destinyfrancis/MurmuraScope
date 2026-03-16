import { ref } from 'vue'

export const lessons = [
  { id: 0, title: '系統預測咩？', icon: '🔮' },
  { id: 1, title: '咩係湧現？', icon: '🐦' },
  { id: 2, title: '知識圖譜入門', icon: '🕸️' },
  { id: 3, title: '從證據到結構', icon: '🔬' },
  { id: 4, title: '從情景到結果', icon: '⚡' },
  { id: 5, title: '讀概率預測', icon: '📊' },
  { id: 6, title: '信心同不確定性', icon: '🎯' },
  { id: 7, title: '點樣挑戰模型', icon: '🤔' },
  { id: 8, title: '常見錯誤', icon: '⚠️' },
  { id: 9, title: '數據來源同局限', icon: '📊' },
]

export const kgNodes = [
  { id: 1, label: 'HIBOR利率', type: 'economic', x: 150, y: 80 },
  { id: 2, label: '按揭利率', type: 'economic', x: 320, y: 60 },
  { id: 3, label: '樓價指數', type: 'economic', x: 450, y: 120 },
  { id: 4, label: '首置買家', type: 'person', x: 400, y: 250 },
  { id: 5, label: '印花稅', type: 'policy', x: 180, y: 220 },
  { id: 6, label: '滙豐銀行', type: 'organization', x: 100, y: 160 },
  { id: 7, label: '上車難', type: 'social', x: 300, y: 340 },
  { id: 8, label: '移民潮', type: 'social', x: 480, y: 320 },
  { id: 9, label: '沙田', type: 'location', x: 520, y: 200 },
  { id: 10, label: '美聯儲', type: 'economic', x: 50, y: 300 },
]

export const kgEdges = [
  { from: 1, to: 2 }, { from: 2, to: 3 }, { from: 3, to: 4 },
  { from: 5, to: 4 }, { from: 6, to: 2 }, { from: 3, to: 7 },
  { from: 7, to: 8 }, { from: 4, to: 9 }, { from: 10, to: 1 },
]

export const typeColors = {
  economic: '#059669',
  person: '#2563EB',
  policy: '#D97706',
  organization: '#7C3AED',
  social: '#0891B2',
  location: '#F59E0B',
}

export const percentileBands = [
  { label: 'p10–p90', color: 'rgba(78,204,163,0.12)', height: 80 },
  { label: 'p25–p75', color: 'rgba(78,204,163,0.25)', height: 50 },
  { label: 'p50 (中位)', color: '#4ecca3', height: 3 },
]

export const challengeChecklist = [
  { id: 'assumptions', label: '檢查假設', detail: '模型嘅前提條件合理嗎？', checked: false },
  { id: 'history', label: '對比歷史', detail: '過去類似情境嘅結果如何？', checked: false },
  { id: 'boundary', label: '邊界測試', detail: '極端參數會產生咩結果？', checked: false },
  { id: 'counterfactual', label: '反事實推理', detail: '如果某個因素唔存在，結果會點變？', checked: false },
  { id: 'omission', label: '尋找遺漏', detail: '有咩重要因素被忽略？', checked: false },
]

export const commonMistakes = [
  {
    wrong: '模型話 70% 機率會跌，所以一定會跌',
    correct: '70% 機率代表 10 次中大約 7 次會發生',
  },
  {
    wrong: 'p50 預測係最準確嘅',
    correct: 'p50 係中位數，真實結果可能喺 p10-p90 之間',
  },
  {
    wrong: '代理人數量越多越準',
    correct: '代理人多樣性比數量更重要',
  },
  {
    wrong: '模型預測咗黑天鵝事件',
    correct: '模型只能捕捉已知風險，真正嘅黑天鵝無法預測',
  },
  {
    wrong: '兩次模擬結果唔同代表模型唔可靠',
    correct: '隨機性係模型嘅特徵，唔係缺陷',
  },
]

export const dataSources = [
  {
    id: 'gov',
    category: '政府統計',
    source: 'data.gov.hk',
    icon: '🏛️',
    items: ['人口普查', '就業數據', '零售銷售'],
    frequency: '每月更新',
    lag: '約 2 個月',
    reliability: 4,
    expanded: false,
  },
  {
    id: 'finance',
    category: '金融市場',
    source: 'Yahoo Finance',
    icon: '📈',
    items: ['恒生指數 (HSI)', '板塊指數', '成交量'],
    frequency: '即時',
    lag: '< 15 分鐘',
    reliability: 5,
    expanded: false,
  },
  {
    id: 'rates',
    category: '利率數據',
    source: 'HKMA / FRED',
    icon: '🏦',
    items: ['HIBOR', '聯儲局基準利率', 'USD/HKD'],
    frequency: '每日',
    lag: '1 個工作日',
    reliability: 5,
    expanded: false,
  },
  {
    id: 'social',
    category: '社交媒體',
    source: 'RSS / Forum',
    icon: '💬',
    items: ['RTHK 新聞', '論壇帖文', '輿情分析'],
    frequency: '每小時',
    lag: '< 1 小時',
    reliability: 3,
    expanded: false,
  },
  {
    id: 'macro',
    category: '宏觀經濟',
    source: 'World Bank',
    icon: '🌍',
    items: ['中國 GDP', 'CPI', '出口數據'],
    frequency: '每季',
    lag: '約 3 個月',
    reliability: 4,
    expanded: false,
  },
]

/**
 * Composable for Lesson 7 (challenge checklist) interactive state.
 */
export function useChallengeChecklist() {
  const checklist = ref(challengeChecklist.map(item => ({ ...item })))
  const allChecked = ref(false)

  function toggleCheck(id) {
    checklist.value = checklist.value.map(item =>
      item.id === id ? { ...item, checked: !item.checked } : item
    )
    allChecked.value = checklist.value.every(item => item.checked)
  }

  function resetChecklist() {
    checklist.value = checklist.value.map(item => ({ ...item, checked: false }))
    allChecked.value = false
  }

  return { checklist, allChecked, toggleCheck, resetChecklist }
}

/**
 * Composable for Lesson 9 (data sources) interactive state.
 */
export function useDataSources() {
  const sources = ref(dataSources.map(s => ({ ...s })))

  function toggleSource(id) {
    sources.value = sources.value.map(s =>
      s.id === id ? { ...s, expanded: !s.expanded } : s
    )
  }

  return { sources, toggleSource }
}
