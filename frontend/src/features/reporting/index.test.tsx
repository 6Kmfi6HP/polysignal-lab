/**
 * Input: type { ReactNode } from 'react', { SearchProvider } from '@/context/search-provider', { ThemeProvider } from '@/context/theme-provider', * as client from '@/lib/api/client', {, { renderWithQueryClient } from '@/test-utils/render-with-query-client', { SidebarProvider } from '@/components/ui/sidebar', userEvent from '@testing-library/user-event', { afterEach, describe, expect, it, vi } from 'vitest', { ReportingPage } from './index'
 * Output: renderReportingPage
 * Pos: Application code
 *
 * 🔄 Self-reference: When this file changes, update this header
 */







import type { ReactNode } from 'react'
import { SearchProvider } from '@/context/search-provider'
import { ThemeProvider } from '@/context/theme-provider'
import * as client from '@/lib/api/client'
import {
  makeReportOrder,
  makeReportPosition,
  makeReportTradeResult,
} from '@/test-utils/fixtures'
import { renderWithQueryClient } from '@/test-utils/render-with-query-client'
import { SidebarProvider } from '@/components/ui/sidebar'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ReportingPage } from './index'

vi.mock('recharts', () => ({
  CartesianGrid: () => null,
  Line: () => null,
  XAxis: () => null,
  YAxis: () => null,
  ResponsiveContainer: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  LineChart: ({
    children,
    data,
  }: {
    children: ReactNode
    data: unknown
  }) => (
    <div data-testid='line-chart-data'>
      {JSON.stringify(data)}
      {children}
    </div>
  ),
}))

function renderReportingPage() {
  return renderWithQueryClient(
    <ThemeProvider>
      <SearchProvider>
        <SidebarProvider defaultOpen={false}>
          <ReportingPage />
        </SidebarProvider>
      </SearchProvider>
    </ThemeProvider>
  )
}

describe('ReportingPage', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders the trades table with stored report results and a cumulative PnL chart', async () => {
    vi.spyOn(client, 'getTrades').mockResolvedValue([
      makeReportTradeResult({
        report_result_id: 'rr-late',
        closed_at: '2026-06-30T00:10:00+00:00',
        pnl_usdc: 4,
      }),
      makeReportTradeResult({
        report_result_id: 'rr-early',
        closed_at: '2026-06-30T00:05:00+00:00',
        pnl_usdc: -1,
      }),
    ])
    vi.spyOn(client, 'getPositions').mockResolvedValue([makeReportPosition()])
    vi.spyOn(client, 'getReportOrders').mockResolvedValue([makeReportOrder()])

    const view = renderReportingPage()

    expect(await view.findByText('rr-late')).toBeInTheDocument()
    expect(view.getByText('rr-early')).toBeInTheDocument()
    expect(view.getByText('4.00 USDC')).toBeInTheDocument()
    expect(JSON.parse(view.getByTestId('line-chart-data').textContent ?? '[]')).toEqual([
      { closed_at: '2026-06-30T00:05:00+00:00', cumulative_pnl: -1 },
      { closed_at: '2026-06-30T00:10:00+00:00', cumulative_pnl: 3 },
    ])
    expect(
      view.getByRole('img', { name: 'Cumulative PnL chart' })
    ).toBeInTheDocument()
    expect(view.getByRole('tab', { name: 'Trades' })).toHaveAttribute(
      'aria-selected',
      'true'
    )
    expect(view.getByRole('tab', { name: 'Positions' })).toBeInTheDocument()
    expect(view.getByRole('tab', { name: 'Orders' })).toBeInTheDocument()
  })

  it('renders positions and orders tables on their tabs', async () => {
    vi.spyOn(client, 'getTrades').mockResolvedValue([makeReportTradeResult()])
    vi.spyOn(client, 'getPositions').mockResolvedValue([
      makeReportPosition({ report_position_id: 'rp-1' }),
    ])
    vi.spyOn(client, 'getReportOrders').mockResolvedValue([
      makeReportOrder({ report_order_id: 'ro-1' }),
    ])

    const user = userEvent.setup()
    const view = renderReportingPage()

    await user.click(view.getByRole('tab', { name: 'Positions' }))
    expect(await view.findByText('rp-1')).toBeInTheDocument()

    await user.click(view.getByRole('tab', { name: 'Orders' }))
    expect(await view.findByText('ro-1')).toBeInTheDocument()
  })

  it('renders empty states for trades, positions, and orders', async () => {
    vi.spyOn(client, 'getTrades').mockResolvedValue([])
    vi.spyOn(client, 'getPositions').mockResolvedValue([])
    vi.spyOn(client, 'getReportOrders').mockResolvedValue([])

    const user = userEvent.setup()
    const view = renderReportingPage()

    expect(await view.findAllByText('No closed trades yet.')).toHaveLength(2)

    await user.click(view.getByRole('tab', { name: 'Positions' }))
    expect(await view.findByText('No stored positions yet.')).toBeInTheDocument()

    await user.click(view.getByRole('tab', { name: 'Orders' }))
    expect(await view.findByText('No stored orders yet.')).toBeInTheDocument()
  })

  it('renders load errors for trades, positions, and orders', async () => {
    vi.spyOn(client, 'getTrades').mockRejectedValue(new Error('trades boom'))
    vi.spyOn(client, 'getPositions').mockRejectedValue(new Error('positions boom'))
    vi.spyOn(client, 'getReportOrders').mockRejectedValue(new Error('orders boom'))

    const user = userEvent.setup()
    const view = renderReportingPage()

    expect(
      await view.findByText('Failed to load trades: trades boom')
    ).toBeInTheDocument()

    await user.click(view.getByRole('tab', { name: 'Positions' }))
    expect(
      await view.findByText('Failed to load positions: positions boom')
    ).toBeInTheDocument()

    await user.click(view.getByRole('tab', { name: 'Orders' }))
    expect(
      await view.findByText('Failed to load orders: orders boom')
    ).toBeInTheDocument()
  })

  it('renders loading placeholders before reporting data resolves', async () => {
    vi.spyOn(client, 'getTrades').mockReturnValue(Promise.race([]))
    vi.spyOn(client, 'getPositions').mockReturnValue(Promise.race([]))
    vi.spyOn(client, 'getReportOrders').mockReturnValue(Promise.race([]))

    const user = userEvent.setup()
    const view = renderReportingPage()

    expect(
      view.getByRole('tabpanel').querySelector('[data-slot="skeleton"]')
    ).toBeInTheDocument()

    await user.click(view.getByRole('tab', { name: 'Positions' }))
    expect(
      view.getByRole('tabpanel').querySelector('[data-slot="skeleton"]')
    ).toBeInTheDocument()

    await user.click(view.getByRole('tab', { name: 'Orders' }))
    expect(
      view.getByRole('tabpanel').querySelector('[data-slot="skeleton"]')
    ).toBeInTheDocument()
  })
})
