import { makeStrategyStatusRow } from '@/test-utils/fixtures'
import { renderWithQueryClient } from '@/test-utils/render-with-query-client'
import { within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import * as client from '@/lib/api/client'
import { SearchProvider } from '@/context/search-provider'
import { ThemeProvider } from '@/context/theme-provider'
import { SidebarProvider } from '@/components/ui/sidebar'
import { StrategyStatusPage } from './index'

function renderStrategyStatusPage() {
  return renderWithQueryClient(
    <ThemeProvider>
      <SearchProvider>
        <SidebarProvider defaultOpen={false}>
          <StrategyStatusPage />
        </SidebarProvider>
      </SearchProvider>
    </ThemeProvider>
  )
}

describe('StrategyStatusPage', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders one row per strategy/asset/timeframe combination', async () => {
    vi.spyOn(client, 'getStrategyStatus').mockResolvedValue([
      makeStrategyStatusRow({
        strategy: 'ptb_diff',
        asset: 'ETH',
        timeframe: '15m',
        status: 'unsupported_market',
        reason: 'UNSUPPORTED_ASSET',
      }),
      makeStrategyStatusRow({
        strategy: 'mean_reversion',
        asset: 'BTC',
        timeframe: '5m',
        status: 'active',
        reason: null,
      }),
    ])

    const view = renderStrategyStatusPage()

    const rows = await view.findAllByRole('row')
    expect(rows).toHaveLength(3)
    expect(within(rows[1]).getByText('ptb_diff')).toBeInTheDocument()
    expect(within(rows[1]).getByText('ETH')).toBeInTheDocument()
    expect(within(rows[1]).getByText('15m')).toBeInTheDocument()
    expect(within(rows[1]).getByText('Unsupported Market')).toBeInTheDocument()
    expect(within(rows[1]).getByText('UNSUPPORTED_ASSET')).toBeInTheDocument()
    expect(within(rows[2]).getByText('mean_reversion')).toBeInTheDocument()
    expect(within(rows[2]).getByText('BTC')).toBeInTheDocument()
    expect(within(rows[2]).getByText('5m')).toBeInTheDocument()
    expect(within(rows[2]).getByText('Active')).toBeInTheDocument()
    expect(within(rows[2]).getByText('-')).toBeInTheDocument()
  })

  it('shows an empty state when no rows are stored', async () => {
    vi.spyOn(client, 'getStrategyStatus').mockResolvedValue([])

    const view = renderStrategyStatusPage()

    expect(
      await view.findByText('No strategy readiness rows recorded yet.')
    ).toBeInTheDocument()
  })

  it('shows a loading placeholder before strategy status data resolves', () => {
    vi.spyOn(client, 'getStrategyStatus').mockReturnValue(Promise.race([]))

    const { container } = renderStrategyStatusPage()

    expect(
      container.querySelector('[data-slot="skeleton"]')
    ).toBeInTheDocument()
  })

  it('renders an error message when strategy status data fails to load', async () => {
    vi.spyOn(client, 'getStrategyStatus').mockRejectedValue(new Error('boom'))

    const view = renderStrategyStatusPage()

    expect(
      await view.findByText('Failed to load strategy status: boom')
    ).toBeInTheDocument()
  })
})
