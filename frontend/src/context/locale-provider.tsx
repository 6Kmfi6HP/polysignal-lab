/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { en, zhCN } from '@/i18n/resources'
import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import { getCookie, setCookie, removeCookie } from '@/lib/cookies'

export type LanguagePreference = 'auto' | 'en' | 'zh-CN'
export type ResolvedLocale = Exclude<LanguagePreference, 'auto'>

const COOKIE_NAME = 'polysignal-language'

void i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, 'zh-CN': { translation: zhCN } },
  lng: 'en',
  fallbackLng: 'en',
  supportedLngs: ['en', 'zh-CN'],
  interpolation: { escapeValue: false },
})

type LocaleContextValue = {
  preference: LanguagePreference
  locale: ResolvedLocale
  setPreference: (value: LanguagePreference) => void
  resetLanguage: () => void
}
const LocaleContext = createContext<LocaleContextValue | null>(null)

export function detectBrowserLocale(
  languages = navigator.languages
): ResolvedLocale {
  return languages[0]?.toLowerCase().startsWith('zh') ? 'zh-CN' : 'en'
}

function savedPreference(): LanguagePreference {
  const value = getCookie(COOKIE_NAME)
  return value === 'en' || value === 'zh-CN' ? value : 'auto'
}

export function LocaleProvider({ children }: { children: React.ReactNode }) {
  const [preference, setPreferenceState] =
    useState<LanguagePreference>(savedPreference)
  const [browserLocale, setBrowserLocale] = useState(detectBrowserLocale)
  const locale = preference === 'auto' ? browserLocale : preference

  useEffect(() => {
    if (preference !== 'auto') return
    const update = () => setBrowserLocale(detectBrowserLocale())
    window.addEventListener('languagechange', update)
    return () => window.removeEventListener('languagechange', update)
  }, [preference])

  useEffect(() => {
    void i18n.changeLanguage(locale)
    document.documentElement.lang = locale
    document.title = i18n.t('metadata.title')
    document
      .querySelector('meta[name="description"]')
      ?.setAttribute('content', i18n.t('metadata.description'))
  }, [locale])

  const value = useMemo(
    () => ({
      preference,
      locale,
      setPreference: (next: LanguagePreference) => {
        setPreferenceState(next)
        if (next === 'auto') {
          setBrowserLocale(detectBrowserLocale())
          removeCookie(COOKIE_NAME)
        } else setCookie(COOKIE_NAME, next, 60 * 60 * 24 * 365)
      },
      resetLanguage: () => {
        setBrowserLocale(detectBrowserLocale())
        setPreferenceState('auto')
        removeCookie(COOKIE_NAME)
      },
    }),
    [locale, preference]
  )

  return (
    <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>
  )
}

export function useLocale() {
  const context = useContext(LocaleContext)
  if (!context) throw new Error('useLocale must be used within LocaleProvider')
  return context
}

export { i18n }
