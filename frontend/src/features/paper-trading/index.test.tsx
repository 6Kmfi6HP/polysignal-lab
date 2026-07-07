/**
 * Input: type { ReactNode } from 'react', { SearchProvider } from '@/context/search-provider', { ThemeProvider } from '@/context/theme-provider', * as client from '@/lib/api/client', {, { renderWithQueryClient } from '@/test-utils/render-with-query-client', { SidebarProvider } from '@/components/ui/sidebar', userEvent from '@testing-library/user-event', { afterEach, describe, expect, it, vi } from 'vitest', { PaperTradingPage } from './index'
 * Output: renderPaperTradingPage
 * Pos: Application code
 *
 * 🔄 Self-reference: When this file changes, update this header
 */





import type { ReactNode } from 'react'
import { SearchProvider } from '@/context/search-provider'
import { ThemeProvider } from '@/context/theme-provider'
import * as client from '@/lib/api/client'
import {
  makePaperOrder,
  makePaperPosition,
  makePaperTradeResult,
} from '@/test-utils/fixtures'
import { renderWithQueryClient } from '@/test-utils/render-with-query-client'
import { SidebarProvider } from '@/components/ui/sidebar'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PaperTradingPage } from './index'

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

function renderPaperTradingPage() {
  return renderWithQueryClient(
    <ThemeProvider>
      <SearchProvider>
        <SidebarProvider defaultOpen={false}>
          <PaperTradingPage />
        </SidebarProvider>
      </SearchProvider>
    </ThemeProvider>
  )
}

describe('PaperTradingPage', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders the trades table with stored paper trades and a cumulative PnL chart', async () => {
    vi.spyOn(client, 'getTrades').mockResolvedValue([
      makePaperTradeResult({
        paper_trade_id: 'pt-late',
        closed_at: '2026-06-30T00:10:00+00:00',
        pnl_usdc: 4,
      }),
      makePaperTradeResult({
        paper_trade_id: 'pt-early',
        closed_at: '2026-06-30T00:05:00+00:00',
        pnl_usdc: -1,
      }),
    ])
    vi.spyOn(client, 'getPositions').mockResolvedValue([makePaperPosition()])
    vi.spyOn(client, 'getPaperOrders').mockResolvedValue([makePaperOrder()])

    const view = renderPaperTradingPage()

    expect(await view.findByText('pt-late')).toBeInTheDocument()
    expect(view.getByText('pt-early')).toBeInTheDocument()
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
    vi.spyOn(client, 'getTrades').mockResolvedValue([makePaperTradeResult()])
    vi.spyOn(client, 'getPositions').mockResolvedValue([
      makePaperPosition({ paper_position_id: 'pp-1' }),
    ])
    vi.spyOn(client, 'getPaperOrders').mockResolvedValue([
      makePaperOrder({ paper_order_id: 'po-1' }),
    ])

    const user = userEvent.setup()
    const view = renderPaperTradingPage()

    await user.click(view.getByRole('tab', { name: 'Positions' }))
    expect(await view.findByText('pp-1')).toBeInTheDocument()

    await user.click(view.getByRole('tab', { name: 'Orders' }))
    expect(await view.findByText('po-1')).toBeInTheDocument()
  })

  it('renders empty states for trades, positions, and orders', async () => {
    vi.spyOn(client, 'getTrades').mockResolvedValue([])
    vi.spyOn(client, 'getPositions').mockResolvedValue([])
    vi.spyOn(client, 'getPaperOrders').mockResolvedValue([])

    const user = userEvent.setup()
    const view = renderPaperTradingPage()

    expect(await view.findAllByText('No closed paper trades yet.')).toHaveLength(2)

    await user.click(view.getByRole('tab', { name: 'Positions' }))
    expect(await view.findByText('No stored positions yet.')).toBeInTheDocument()

    await user.click(view.getByRole('tab', { name: 'Orders' }))
    expect(await view.findByText('No stored orders yet.')).toBeInTheDocument()
  })

  it('renders load errors for trades, positions, and orders', async () => {
    vi.spyOn(client, 'getTrades').mockRejectedValue(new Error('trades boom'))
    vi.spyOn(client, 'getPositions').mockRejectedValue(new Error('positions boom'))
    vi.spyOn(client, 'getPaperOrders').mockRejectedValue(new Error('orders boom'))

    const user = userEvent.setup()
    const view = renderPaperTradingPage()

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

  it('renders loading placeholders before paper trading data resolves', async () => {
    vi.spyOn(client, 'getTrades').mockReturnValue(Promise.race([]))
    vi.spyOn(client, 'getPositions').mockReturnValue(Promise.race([]))
    vi.spyOn(client, 'getPaperOrders').mockReturnValue(Promise.race([]))

    const user = userEvent.setup()
    const view = renderPaperTradingPage()

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
