import type { ReactNode } from 'react'
import {
  makeReportOrder,
  makeReportPosition,
  makeReportTradeResult,
} from '@/test-utils/fixtures'
import { renderWithQueryClient } from '@/test-utils/render-with-query-client'
import { waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as client from '@/lib/api/client'
import type { NavigateFn } from '@/hooks/use-table-url-state'
import { ReportingPage } from './index'

type NavigateOpts = Parameters<NavigateFn>[0]

vi.mock('recharts', () => ({
  CartesianGrid: () => null,
  Line: () => null,
  ReferenceLine: () => null,
  Tooltip: () => null,
  XAxis: () => null,
  YAxis: () => null,
  ResponsiveContainer: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  LineChart: ({ children, data }: { children: ReactNode; data: unknown }) => (
    <div data-testid='line-chart-data'>
      {JSON.stringify(data)}
      {children}
    </div>
  ),
}))

function renderReportingPage(
  search: Record<string, unknown> = {},
  navigate = vi.fn()
) {
  return renderWithQueryClient(
    <ReportingPage
      search={search}
      navigate={navigate as unknown as NavigateFn}
    />
  )
}

function lastNavigateOpts(navigate: ReturnType<typeof vi.fn>) {
  const calls = navigate.mock.calls as Array<[NavigateOpts]>
  return calls[calls.length - 1]?.[0]
}

function applyLastSearchFn(
  navigate: ReturnType<typeof vi.fn>,
  prev: Record<string, unknown>
) {
  const opts = lastNavigateOpts(navigate)
  if (!opts) return undefined
  const s = opts.search
  if (typeof s === 'function') {
    return s(prev) as Record<string, unknown>
  }
  return s as Record<string, unknown>
}

describe('ReportingPage', () => {
  beforeEach(() => {
    vi.spyOn(client, 'getReportSummary').mockResolvedValue({
      total_pnl_usdc: 4,
      average_roi: 0.4,
      closed_trades: 1,
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders the trades table with stored report results and a cumulative PnL chart', async () => {
    vi.mocked(client.getReportSummary).mockResolvedValue({
      total_pnl_usdc: 25,
      average_roi: 0.125,
      closed_trades: 567,
    })
    vi.spyOn(client, 'getTrades').mockResolvedValue({
      items: [
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
      ],
      total: 2,
    })
    vi.spyOn(client, 'getPositions').mockResolvedValue({
      items: [makeReportPosition()],
      total: 1,
    })
    vi.spyOn(client, 'getReportOrders').mockResolvedValue({
      items: [makeReportOrder()],
      total: 1,
    })

    const view = renderReportingPage()

    expect(await view.findByText('+25.00 USDC')).toBeInTheDocument()
    expect(view.getByText('+12.5%')).toBeInTheDocument()
    expect(view.getByText('567')).toBeInTheDocument()
    expect(await view.findByText('+4.00 USDC')).toBeInTheDocument()
    expect(view.getByText('-1.00 USDC')).toBeInTheDocument()
    expect(
      JSON.parse(view.getByTestId('line-chart-data').textContent ?? '[]')
    ).toEqual([
      {
        closed_at: '2026-06-30T00:05:00+00:00',
        closed_at_ms: 1782777900000,
        cumulative_pnl: -1,
      },
      {
        closed_at: '2026-06-30T00:10:00+00:00',
        closed_at_ms: 1782778200000,
        cumulative_pnl: 3,
      },
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

  it('shows an error when the all-history summary cannot be loaded', async () => {
    vi.mocked(client.getReportSummary).mockRejectedValue(
      new Error('summary unavailable')
    )
    vi.spyOn(client, 'getTrades').mockResolvedValue({ items: [], total: 0 })
    vi.spyOn(client, 'getPositions').mockResolvedValue({ items: [], total: 0 })
    vi.spyOn(client, 'getReportOrders').mockResolvedValue({
      items: [],
      total: 0,
    })

    const view = renderReportingPage()

    expect(await view.findByText(/summary unavailable/i)).toBeInTheDocument()
  })

  it('renders positions and orders tables on their tabs', async () => {
    vi.spyOn(client, 'getTrades').mockResolvedValue({
      items: [makeReportTradeResult()],
      total: 1,
    })
    vi.spyOn(client, 'getPositions').mockResolvedValue({
      items: [makeReportPosition({ report_position_id: 'rp-1' })],
      total: 1,
    })
    vi.spyOn(client, 'getReportOrders').mockResolvedValue({
      items: [makeReportOrder({ report_order_id: 'ro-1' })],
      total: 1,
    })

    const user = userEvent.setup()
    const view = renderReportingPage()

    await user.click(view.getByRole('tab', { name: 'Positions' }))
    expect(await view.findByText('Open')).toBeInTheDocument()

    await user.click(view.getByRole('tab', { name: 'Orders' }))
    expect(await view.findByText('Filled')).toBeInTheDocument()
  })

  it('renders empty states for trades, positions, and orders', async () => {
    vi.spyOn(client, 'getTrades').mockResolvedValue({ items: [], total: 0 })
    vi.spyOn(client, 'getPositions').mockResolvedValue({ items: [], total: 0 })
    vi.spyOn(client, 'getReportOrders').mockResolvedValue({
      items: [],
      total: 0,
    })

    const user = userEvent.setup()
    const view = renderReportingPage()

    expect(await view.findAllByText('No closed trades yet.')).toHaveLength(2)

    await user.click(view.getByRole('tab', { name: 'Positions' }))
    expect(
      await view.findByText('No stored positions yet.')
    ).toBeInTheDocument()

    await user.click(view.getByRole('tab', { name: 'Orders' }))
    expect(await view.findByText('No stored orders yet.')).toBeInTheDocument()
  })

  it('renders load errors for trades, positions, and orders', async () => {
    vi.spyOn(client, 'getTrades').mockRejectedValue(new Error('trades boom'))
    vi.spyOn(client, 'getPositions').mockRejectedValue(
      new Error('positions boom')
    )
    vi.spyOn(client, 'getReportOrders').mockRejectedValue(
      new Error('orders boom')
    )

    const user = userEvent.setup()
    const view = renderReportingPage()

    expect(
      await view.findAllByText('Failed to load trades: trades boom')
    ).toHaveLength(2)

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

  it('uses offset/limit for the first table query and keeps the chart query independent', async () => {
    const getTrades = vi.spyOn(client, 'getTrades').mockResolvedValue({
      items: Array.from({ length: 25 }, (_, index) =>
        makeReportTradeResult({ report_result_id: `rr-${index}` })
      ),
      total: 100,
    })
    vi.spyOn(client, 'getPositions').mockResolvedValue({
      items: [makeReportPosition()],
      total: 1,
    })
    vi.spyOn(client, 'getReportOrders').mockResolvedValue({
      items: [makeReportOrder()],
      total: 1,
    })

    renderReportingPage({ tradesPage: 2, tradesPageSize: 25 })

    await waitFor(() => {
      expect(getTrades.mock.calls).toContainEqual([{ limit: 25, offset: 25 }])
      expect(getTrades.mock.calls).toContainEqual([{ limit: 500, offset: 0 }])
    })
  })

  it('writes trades pagination to the URL when next is clicked', async () => {
    vi.spyOn(client, 'getTrades').mockResolvedValue({
      items: Array.from({ length: 25 }, (_, index) =>
        makeReportTradeResult({ report_result_id: `rr-next-${index}` })
      ),
      total: 60,
    })
    vi.spyOn(client, 'getPositions').mockResolvedValue({
      items: [makeReportPosition()],
      total: 1,
    })
    vi.spyOn(client, 'getReportOrders').mockResolvedValue({
      items: [makeReportOrder()],
      total: 1,
    })
    const navigate = vi.fn()
    const user = userEvent.setup()
    const view = renderReportingPage({}, navigate)

    await user.click(
      await within(view.getByRole('tabpanel')).findByRole('button', {
        name: 'Next page',
      })
    )

    expect(
      applyLastSearchFn(navigate, { tradesPage: 1, tradesPageSize: 25 })
    ).toMatchObject({
      tradesPage: 2,
      tradesPageSize: undefined,
    })
  })

  it('resets the page when the page size changes', async () => {
    vi.spyOn(client, 'getTrades').mockResolvedValue({
      items: Array.from({ length: 25 }, (_, index) =>
        makeReportTradeResult({ report_result_id: `rr-size-${index}` })
      ),
      total: 101,
    })
    vi.spyOn(client, 'getPositions').mockResolvedValue({
      items: [makeReportPosition()],
      total: 1,
    })
    vi.spyOn(client, 'getReportOrders').mockResolvedValue({
      items: [makeReportOrder()],
      total: 1,
    })
    const navigate = vi.fn()
    const user = userEvent.setup()
    const view = renderReportingPage(
      { tradesPage: 3, tradesPageSize: 25 },
      navigate
    )

    await user.click(
      await within(view.getByRole('tabpanel')).findByRole('button', {
        name: '50',
      })
    )

    expect(
      applyLastSearchFn(navigate, { tradesPage: 3, tradesPageSize: 25 })
    ).toMatchObject({
      tradesPage: undefined,
      tradesPageSize: 50,
    })
  })

  it('resets an out-of-range page when the total shrinks', async () => {
    vi.spyOn(client, 'getTrades').mockResolvedValue({
      items: [makeReportTradeResult()],
      total: 1,
    })
    vi.spyOn(client, 'getPositions').mockResolvedValue({
      items: [makeReportPosition()],
      total: 1,
    })
    vi.spyOn(client, 'getReportOrders').mockResolvedValue({
      items: [makeReportOrder()],
      total: 1,
    })
    const navigate = vi.fn()
    renderReportingPage({ tradesPage: 3, tradesPageSize: 25 }, navigate)

    await waitFor(() => {
      expect(navigate).toHaveBeenCalled()
    })

    expect(
      applyLastSearchFn(navigate, { tradesPage: 3, tradesPageSize: 25 })
    ).toMatchObject({
      tradesPage: 1,
    })
  })
})
