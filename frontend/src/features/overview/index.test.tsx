/**
 * Input: { makeHealthResponse, makeOverviewResponse } from '@/test-utils/fixtures', { renderWithQueryClient } from '@/test-utils/render-with-query-client', { afterEach, describe, expect, it, vi } from 'vitest', * as client from '@/lib/api/client', { SearchProvider } from '@/context/search-provider', { ThemeProvider } from '@/context/theme-provider', { SidebarProvider } from '@/components/ui/sidebar', { OverviewPage } from './index', @/test-utils/fixtures, @/test-utils/render-with-query-client
 * Output: renderOverviewPage
 * Pos: Application code
 *
 * 🔄 Self-reference: When this file changes, update this header
 */







import { makeHealthResponse, makeOverviewResponse } from '@/test-utils/fixtures'
import { renderWithQueryClient } from '@/test-utils/render-with-query-client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import * as client from '@/lib/api/client'
import { SearchProvider } from '@/context/search-provider'
import { ThemeProvider } from '@/context/theme-provider'
import { SidebarProvider } from '@/components/ui/sidebar'
import { OverviewPage } from './index'

const mocks = vi.hoisted(() => ({
  navigate: vi.fn(),
}))

vi.mock('@tanstack/react-router', () => ({
  useNavigate: () => mocks.navigate,
}))

function renderOverviewPage() {
  return renderWithQueryClient(
    <ThemeProvider>
      <SearchProvider>
        <SidebarProvider defaultOpen={false}>
          <OverviewPage />
        </SidebarProvider>
      </SearchProvider>
    </ThemeProvider>
  )
}

describe('OverviewPage', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders row counts, latest report details, and health status once data loads', async () => {
    vi.spyOn(client, 'getOverview').mockResolvedValue(
      makeOverviewResponse({
        counts: { signals: 42, rejected_signals: 7 },
      })
    )
    vi.spyOn(client, 'getHealth').mockResolvedValue(
      makeHealthResponse({ status: 'ok' })
    )

    const view = renderOverviewPage()

    expect(await view.findByText('42')).toBeInTheDocument()
    expect(view.getByText('signals')).toBeInTheDocument()
    expect(view.getByText('7')).toBeInTheDocument()
    expect(view.getByText('rejected signals')).toBeInTheDocument()
    expect(view.getByText('2026-06-30')).toBeInTheDocument()
    expect(view.getByText('3')).toBeInTheDocument()
    expect(view.getByText('1')).toBeInTheDocument()
    expect(view.getByText('4.00 USDC')).toBeInTheDocument()
    expect(view.getByText('ok')).toBeInTheDocument()
  })

  it('shows a loading placeholder before overview data resolves', () => {
    vi.spyOn(client, 'getOverview').mockReturnValue(Promise.race([]))
    vi.spyOn(client, 'getHealth').mockResolvedValue(makeHealthResponse())

    const { container } = renderOverviewPage()

    expect(
      container.querySelector('[data-slot="skeleton"]')
    ).toBeInTheDocument()
  })

  it('renders an error message when overview data fails to load', async () => {
    vi.spyOn(client, 'getOverview').mockRejectedValue(new Error('boom'))
    vi.spyOn(client, 'getHealth').mockResolvedValue(makeHealthResponse())

    const view = renderOverviewPage()

    expect(
      await view.findByText('Failed to load overview: boom')
    ).toBeInTheDocument()
  })

  it('renders an empty state when no latest report exists', async () => {
    vi.spyOn(client, 'getOverview').mockResolvedValue(
      makeOverviewResponse({ latest_report: null })
    )
    vi.spyOn(client, 'getHealth').mockResolvedValue(makeHealthResponse())

    const view = renderOverviewPage()

    expect(
      await view.findByText('No daily report has been stored yet.')
    ).toBeInTheDocument()
  })
})
