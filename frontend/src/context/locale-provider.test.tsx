import { clearCookies } from '@/test-utils/cookies'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useTranslation } from 'react-i18next'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getCookie, setCookie } from '@/lib/cookies'
import { LanguageSwitch } from '@/components/language-switch'
import {
  detectBrowserLocale,
  LocaleProvider,
  useLocale,
} from './locale-provider'

function Probe() {
  const { t } = useTranslation()
  const { preference, locale } = useLocale()
  return (
    <>
      <span>
        {preference}:{locale}
      </span>
      <span>{t('navigation.overview')}</span>
      <LanguageSwitch />
    </>
  )
}

describe('LocaleProvider', () => {
  beforeEach(() => {
    clearCookies()
    document.head.innerHTML = '<meta name="description" content="">'
  })

  it('maps any Chinese browser preference to zh-CN and otherwise falls back to English', () => {
    expect(detectBrowserLocale(['zh-Hant', 'fr-FR'])).toBe('zh-CN')
    expect(detectBrowserLocale(['en-US', 'zh-CN'])).toBe('en')
    expect(detectBrowserLocale(['de-DE', 'fr-FR'])).toBe('en')
  })

  it('uses a saved override and synchronizes document metadata', async () => {
    setCookie('polysignal-language', 'zh-CN')
    render(
      <LocaleProvider>
        <Probe />
      </LocaleProvider>
    )
    expect(await screen.findByText('zh-CN:zh-CN')).toBeInTheDocument()
    expect(document.documentElement.lang).toBe('zh-CN')
    expect(
      document
        .querySelector('meta[name="description"]')
        ?.getAttribute('content')
    ).toContain('投资组合')
  })

  it('switches without reload and auto clears the override', async () => {
    const user = userEvent.setup()
    render(
      <LocaleProvider>
        <Probe />
      </LocaleProvider>
    )
    await user.click(screen.getByRole('button', { name: 'Select language' }))
    await user.click(screen.getByRole('menuitem', { name: /简体中文/ }))
    expect(await screen.findByText('zh-CN:zh-CN')).toBeInTheDocument()
    expect(screen.getByText('概览')).toBeInTheDocument()
    expect(document.documentElement.lang).toBe('zh-CN')
    expect(document.title).toContain('控制面板')
    expect(getCookie('polysignal-language')).toBe('zh-CN')

    await user.click(screen.getByRole('button', { name: '选择语言' }))
    await user.keyboard('{ArrowDown}{Enter}')
    expect(await screen.findByText(/^auto:/)).toBeInTheDocument()
    expect(getCookie('polysignal-language')).toBeUndefined()
  })

  it('responds to browser language changes in automatic mode', async () => {
    const languages = vi.spyOn(window.navigator, 'languages', 'get')
    languages.mockReturnValue(['en-US'])
    render(
      <LocaleProvider>
        <Probe />
      </LocaleProvider>
    )
    expect(screen.getByText('auto:en')).toBeInTheDocument()
    languages.mockReturnValue(['zh-CN'])
    window.dispatchEvent(new Event('languagechange'))
    expect(await screen.findByText('auto:zh-CN')).toBeInTheDocument()
    languages.mockRestore()
  })
})
