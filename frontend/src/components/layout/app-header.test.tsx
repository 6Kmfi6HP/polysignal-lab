import { type ComponentProps } from 'react'
import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { DirectionProvider } from '@/context/direction-provider'
import { SearchProvider } from '@/context/search-provider'
import { ThemeProvider } from '@/context/theme-provider'
import { AppHeader } from './app-header'
import { AuthenticatedLayout } from './authenticated-layout'

const routerState = vi.hoisted(() => ({ pathname: '/signals', search: '' }))

vi.mock('@tanstack/react-router', () => ({
  Link: ({ to, onClick, ...props }: ComponentProps<'a'> & { to: string }) => (
    <a
      href={to}
      onClick={(event) => {
        event.preventDefault()
        onClick?.(event)
      }}
      {...props}
    />
  ),
  useLocation: ({
    select,
  }: {
    select: (value: typeof routerState) => string
  }) => select(routerState),
  useNavigate: () => vi.fn(),
}))

function renderHeader() {
  return render(
    <ThemeProvider>
      <DirectionProvider>
        <SearchProvider>
          <AppHeader />
        </SearchProvider>
      </DirectionProvider>
    </ThemeProvider>
  )
}

describe('AppHeader', () => {
  it('renders the ordered desktop links and marks the current pathname', () => {
    routerState.search = '?status=accepted'
    const view = renderHeader()
    const navigation = view.getByRole('navigation', {
      name: 'Primary navigation',
    })
    const links = Array.from(navigation.querySelectorAll('a'))

    expect(links.map((link) => link.textContent)).toEqual([
      'Overview',
      'Signals',
      'Trading Reports',
      'Leaderboard',
      'Strategy Status',
      'System Health',
    ])
    expect(links.map((link) => link.getAttribute('href'))).toEqual([
      '/',
      '/signals',
      '/reporting',
      '/leaderboard',
      '/strategy-status',
      '/system-health',
    ])
    expect(
      view.getByRole('link', { name: 'Signals', current: 'page' })
    ).toBeInTheDocument()
    expect(navigation.querySelectorAll('svg')).toHaveLength(6)
    expect(view.getByRole('button', { name: /^Search/ })).toBeInTheDocument()
    expect(
      view.getByRole('button', { name: 'Toggle theme' })
    ).toBeInTheDocument()
  })

  it('keeps one shared header when authenticated route content changes', () => {
    const first = (
      <ThemeProvider>
        <DirectionProvider>
          <AuthenticatedLayout>
            <div>Overview content</div>
          </AuthenticatedLayout>
        </DirectionProvider>
      </ThemeProvider>
    )
    const view = render(first)
    const header = view.getByRole('banner')

    view.rerender(
      <ThemeProvider>
        <DirectionProvider>
          <AuthenticatedLayout>
            <div>Signals content</div>
          </AuthenticatedLayout>
        </DirectionProvider>
      </ThemeProvider>
    )

    expect(view.getAllByRole('banner')).toHaveLength(1)
    expect(view.getByRole('banner')).toBe(header)
    expect(view.getByText('Signals content')).toBeInTheDocument()
  })

  it('opens and closes the mobile sheet, restoring focus to Menu', async () => {
    const user = userEvent.setup()
    const view = renderHeader()
    const menuButton = view.getByRole('button', {
      name: 'Open navigation menu',
    })

    await user.click(menuButton)
    expect(
      view.getByRole('navigation', { name: 'Mobile navigation' })
    ).toBeInTheDocument()
    expect(
      view.getByRole('link', { name: 'Signals', current: 'page' })
    ).toBeInTheDocument()

    await user.keyboard('{Escape}')
    expect(
      view.queryByRole('navigation', { name: 'Mobile navigation' })
    ).not.toBeInTheDocument()
    expect(menuButton).toHaveFocus()
  })

  it('closes the mobile sheet when a route is selected', async () => {
    const user = userEvent.setup()
    const view = renderHeader()

    await user.click(view.getByRole('button', { name: 'Open navigation menu' }))
    const mobileNavigation = view.getByRole('navigation', {
      name: 'Mobile navigation',
    })
    await user.click(
      mobileNavigation.querySelector('a[href="/reporting"]') as HTMLElement
    )

    expect(
      view.queryByRole('navigation', { name: 'Mobile navigation' })
    ).not.toBeInTheDocument()
  })
})
