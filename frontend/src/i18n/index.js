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
