import { ref, onMounted } from 'vue'

const STORAGE_KEY = 'hksim_onboarding_dismissed'

export function useOnboarding() {
  const currentStep = ref(0)
  const dismissed = ref(false)

  const steps = [
    {
      id: 'scenario',
      title: '選擇預測場景',
      description: '從首頁選擇一個社會議題作為模擬預測嘅起點',
      target: '.scenario-grid',
    },
    {
      id: 'graph',
      title: '知識圖譜',
      description: '系統會自動建立知識圖譜，展示議題中嘅因果關係',
      target: '.graph-panel',
    },
    {
      id: 'simulation',
      title: '運行模擬',
      description: '觀察 AI 代理人如何互動、做決策、形成社會趨勢',
      target: '.sim-monitor',
    },
  ]

  onMounted(() => {
    dismissed.value = localStorage.getItem(STORAGE_KEY) === 'true'
  })

  function nextStep() {
    if (currentStep.value < steps.length - 1) {
      currentStep.value++
    } else {
      dismiss()
    }
  }

  function dismiss() {
    dismissed.value = true
    localStorage.setItem(STORAGE_KEY, 'true')
  }

  return {
    steps,
    currentStep,
    dismissed,
    nextStep,
    dismiss,
  }
}
