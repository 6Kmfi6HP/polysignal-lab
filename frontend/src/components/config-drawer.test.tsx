import { clearCookies } from '@/test-utils/cookies'
import { render, type RenderResult, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getCookie, setCookie } from '@/lib/cookies'
import { DirectionProvider } from '@/context/direction-provider'
import { ThemeProvider } from '@/context/theme-provider'
import { ConfigDrawer } from './config-drawer'

function renderConfigDrawer() {
  return render(
    <DirectionProvider>
      <ThemeProvider>
        <ConfigDrawer />
      </ThemeProvider>
    </DirectionProvider>
  )
}

async function openDrawer(view: RenderResult) {
  await userEvent.click(
    view.getByRole('button', { name: /^Open theme settings$/i })
  )
  return within(view.getByRole('dialog', { name: /theme settings/i }))
}

describe('ConfigDrawer', () => {
  beforeEach(() => {
    clearCookies()
    document.documentElement.classList.remove('light', 'dark')
    document.documentElement.removeAttribute('dir')
  })

  it('keeps appearance controls without retired sidebar and layout options', async () => {
    const drawer = await openDrawer(renderConfigDrawer())

    expect(drawer.getByText('Theme')).toBeInTheDocument()
    expect(drawer.getByText('Direction')).toBeInTheDocument()
    expect(drawer.queryByText('Sidebar')).not.toBeInTheDocument()
    expect(drawer.queryByText('Layout')).not.toBeInTheDocument()
  })

  it('applies the selected theme to the document and cookie', async () => {
    const view = renderConfigDrawer()
    await openDrawer(view)

    await userEvent.click(view.getByRole('radio', { name: /select dark/i }))

    await vi.waitFor(() => expect(document.documentElement).toHaveClass('dark'))
    expect(getCookie('vite-ui-theme')).toBe('dark')
  })

  it('applies the light theme', async () => {
    const view = renderConfigDrawer()
    await openDrawer(view)

    await userEvent.click(view.getByRole('radio', { name: /select light/i }))

    await vi.waitFor(() =>
      expect(document.documentElement).toHaveClass('light')
    )
    expect(getCookie('vite-ui-theme')).toBe('light')
  })

  it('stores and resolves the system theme', async () => {
    setCookie('vite-ui-theme', 'light')
    const view = renderConfigDrawer()
    await openDrawer(view)

    await userEvent.click(view.getByRole('radio', { name: /select system/i }))

    await vi.waitFor(() => expect(getCookie('vite-ui-theme')).toBe('system'))
    expect(
      document.documentElement.classList.contains('light') !==
        document.documentElement.classList.contains('dark')
    ).toBe(true)
  })

  it('resets theme from its section control', async () => {
    const view = renderConfigDrawer()
    await openDrawer(view)
    await userEvent.click(view.getByRole('radio', { name: /select dark/i }))

    await userEvent.click(
      view.getByRole('button', {
        name: /reset theme preference to default/i,
      })
    )

    await vi.waitFor(() => expect(getCookie('vite-ui-theme')).toBe('system'))
  })

  it('applies and resets text direction', async () => {
    const view = renderConfigDrawer()
    await openDrawer(view)

    await userEvent.click(
      view.getByRole('radio', { name: /select right to left/i })
    )
    await vi.waitFor(() =>
      expect(document.documentElement).toHaveAttribute('dir', 'rtl')
    )
    expect(getCookie('dir')).toBe('rtl')

    await userEvent.click(
      view.getByRole('button', {
        name: /reset text direction to default/i,
      })
    )
    await vi.waitFor(() =>
      expect(document.documentElement).toHaveAttribute('dir', 'ltr')
    )
    expect(getCookie('dir')).toBe('ltr')
  })

  it('resets theme and direction together', async () => {
    const view = renderConfigDrawer()
    await openDrawer(view)
    await userEvent.click(view.getByRole('radio', { name: /select dark/i }))
    await userEvent.click(
      view.getByRole('radio', { name: /select right to left/i })
    )

    await userEvent.click(
      view.getByRole('button', {
        name: /reset all settings to default values/i,
      })
    )

    await vi.waitFor(() => expect(getCookie('dir')).toBeUndefined())
    expect(getCookie('vite-ui-theme')).toBeUndefined()
    expect(document.documentElement).toHaveAttribute('dir', 'ltr')
  })
})
