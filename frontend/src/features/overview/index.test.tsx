/**
 * Input: { makeDailyReport, makeHealthResponse, makeOverviewResponse } from '@/test-utils/fixtures', { renderWithQueryClient } from '@/test-utils/render-with-query-client', { screen } from '@testing-library/react', { afterEach, describe, expect, it, vi } from 'vitest', * as client from '@/lib/api/client', { SearchProvider } from '@/context/search-provider', { ThemeProvider } from '@/context/theme-provider', { SidebarProvider } from '@/components/ui/sidebar', { OverviewPage } from './index'
 * Output: renderOverviewPage
 * Pos: Application code
 *
 * 🔄 Self-reference: When this file changes, update this header
 */







import {
  makeDailyReport,
  makeHealthResponse,
  makeOverviewResponse,
} from '@/test-utils/fixtures'
import { renderWithQueryClient } from '@/test-utils/render-with-query-client'
import { screen } from '@testing-library/react'
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

    renderOverviewPage()

    expect(await screen.findByText('42')).toBeInTheDocument()
    expect(screen.getByText('signals')).toBeInTheDocument()
    expect(screen.getByText('7')).toBeInTheDocument()
    expect(screen.getByText('rejected signals')).toBeInTheDocument()
    expect(screen.getByText('2026-06-30')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.getByText('1')).toBeInTheDocument()
    expect(screen.getByText('4.00 (currency unavailable)')).toBeInTheDocument()
    expect(screen.queryByText('Equity source')).not.toBeInTheDocument()
    expect(screen.getByText('Status unavailable')).toBeInTheDocument()
    expect(screen.getByText('ok')).toBeInTheDocument()
  })

  it('shows report currency and incomplete telemetry reasons', async () => {
    vi.spyOn(client, 'getOverview').mockResolvedValue(
      makeOverviewResponse({
        latest_report: makeDailyReport({
          paper_pnl: 7,
          total_pnl_usdc: 4,
          equity_currency: 'pUSD',
          equity_source: 'account_balance',
          telemetry_status: 'incomplete',
          telemetry_incomplete_reasons: [
            'paper_order_projection_invalid:1',
            'telemetry_queue_drops',
          ],
        }),
      })
    )
    vi.spyOn(client, 'getHealth').mockResolvedValue(makeHealthResponse())

    renderOverviewPage()

    expect(await screen.findByText('7.00 pUSD')).toBeInTheDocument()
    expect(screen.getByText('Account balance')).toBeInTheDocument()
    expect(screen.queryByText('4.00 USDC')).not.toBeInTheDocument()
    expect(screen.getByText('Incomplete')).toBeInTheDocument()
    expect(
      screen.getByText(
        'Reasons: paper_order_projection_invalid:1; telemetry_queue_drops'
      )
    ).toBeInTheDocument()
  })

  it('marks incomplete telemetry reasons unavailable when omitted', async () => {
    vi.spyOn(client, 'getOverview').mockResolvedValue(
      makeOverviewResponse({
        latest_report: makeDailyReport({ telemetry_status: 'incomplete' }),
      })
    )
    vi.spyOn(client, 'getHealth').mockResolvedValue(makeHealthResponse())

    const view = renderOverviewPage()

    expect(await view.findByText('Incomplete')).toBeInTheDocument()
    expect(view.getByText('Reasons unavailable')).toBeInTheDocument()
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
