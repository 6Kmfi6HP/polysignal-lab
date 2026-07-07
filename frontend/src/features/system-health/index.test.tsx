/**
 * Input: { SearchProvider } from '@/context/search-provider', * as client from '@/lib/api/client', { makeHealthResponse } from '@/test-utils/fixtures', { renderWithQueryClient } from '@/test-utils/render-with-query-client', { SidebarProvider } from '@/components/ui/sidebar', { ThemeProvider } from '@/context/theme-provider', { afterEach, describe, expect, it, vi } from 'vitest', { SystemHealthPage } from './index', @/context/search-provider, @/lib/api/client
 * Output: renderSystemHealthPage
 * Pos: Application code
 *
 * 🔄 Self-reference: When this file changes, update this header
 */





import { SearchProvider } from '@/context/search-provider'
import * as client from '@/lib/api/client'
import { makeHealthResponse } from '@/test-utils/fixtures'
import { renderWithQueryClient } from '@/test-utils/render-with-query-client'
import { SidebarProvider } from '@/components/ui/sidebar'
import { ThemeProvider } from '@/context/theme-provider'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SystemHealthPage } from './index'

function renderSystemHealthPage() {
  return renderWithQueryClient(
    <ThemeProvider>
      <SearchProvider>
        <SidebarProvider defaultOpen={false}>
          <SystemHealthPage />
        </SidebarProvider>
      </SearchProvider>
    </ThemeProvider>
  )
}

describe('SystemHealthPage', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders component status badges from the health payload', async () => {
    vi.spyOn(client, 'getHealth').mockResolvedValue(
      makeHealthResponse({
        status: 'degraded',
        components: [
          {
            name: 'binance_ws',
            status: 'degraded',
            last_success_at: null,
            last_error_at: '2026-06-23T00:00:00+00:00',
            last_error: 'spot prices stale',
            metrics: { btc_spot_lag_ms: 61000 },
          },
          {
            name: 'sqlite',
            status: 'ok',
            last_success_at: '2026-06-23T00:01:00+00:00',
            last_error_at: null,
            last_error: null,
            metrics: {},
          },
        ],
      })
    )

    const view = renderSystemHealthPage()

    expect(await view.findByText('binance_ws')).toBeInTheDocument()
    expect(view.getByText('degraded')).toBeInTheDocument()
    expect(view.getByText('spot prices stale')).toBeInTheDocument()
    expect(view.getByText('sqlite')).toBeInTheDocument()
    expect(view.getByText('ok')).toBeInTheDocument()
    expect(view.getByText('No recent errors.')).toBeInTheDocument()
  })

  it('shows an empty component state when no health rows are recorded', async () => {
    vi.spyOn(client, 'getHealth').mockResolvedValue(makeHealthResponse())

    const view = renderSystemHealthPage()

    expect(
      await view.findByText('No component health rows recorded yet.')
    ).toBeInTheDocument()
  })

  it('renders recent system events and the empty event state', async () => {
    vi.spyOn(client, 'getHealth').mockResolvedValue(
      makeHealthResponse({
        recent_system_events: [
          { level: 'warning', message: 'scheduler lag detected' },
        ],
      })
    )

    const view = renderSystemHealthPage()

    expect(await view.findByText('Recent system events')).toBeInTheDocument()
    expect(
      view.getByText('{"level":"warning","message":"scheduler lag detected"}')
    ).toBeInTheDocument()

    vi.restoreAllMocks()
    vi.spyOn(client, 'getHealth').mockResolvedValue(makeHealthResponse())

    const emptyView = renderSystemHealthPage()

    expect(
      await emptyView.findByText('No system events recorded yet.')
    ).toBeInTheDocument()
  })

  it('shows a loading placeholder before health data resolves', () => {
    vi.spyOn(client, 'getHealth').mockReturnValue(Promise.race([]))

    const { container } = renderSystemHealthPage()

    expect(
      container.querySelector('[data-slot="skeleton"]')
    ).toBeInTheDocument()
  })

  it('renders an error message when health data fails to load', async () => {
    vi.spyOn(client, 'getHealth').mockRejectedValue(new Error('boom'))

    const view = renderSystemHealthPage()

    expect(await view.findByText('Failed to load health: boom')).toBeInTheDocument()
  })
})
