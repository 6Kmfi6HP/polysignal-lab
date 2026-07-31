import { makeStrategyStatusRow } from '@/test-utils/fixtures'
import { renderWithQueryClient } from '@/test-utils/render-with-query-client'
import { within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import * as client from '@/lib/api/client'
import { StrategyStatusPage } from './index'

function renderStrategyStatusPage() {
  return renderWithQueryClient(<StrategyStatusPage />)
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

  it('filters readiness rows by status', async () => {
    vi.spyOn(client, 'getStrategyStatus').mockResolvedValue([
      makeStrategyStatusRow({ strategy: 'ready', status: 'active' }),
      makeStrategyStatusRow({ strategy: 'blocked', status: 'missing_data' }),
    ])
    const user = userEvent.setup()
    const view = renderStrategyStatusPage()

    await view.findByText('ready')
    await user.click(view.getByRole('button', { name: 'missing data (1)' }))

    expect(view.queryByText('ready')).not.toBeInTheDocument()
    expect(view.getByText('blocked')).toBeInTheDocument()
  })

  it('renders and filters an untradable market status', async () => {
    vi.spyOn(client, 'getStrategyStatus').mockResolvedValue([
      makeStrategyStatusRow({ strategy: 'ready', status: 'active' }),
      makeStrategyStatusRow({
        strategy: 'empty-book',
        status: 'untradable',
        reason: 'missing_quote_depth:DOWN',
      }),
    ])
    const user = userEvent.setup()
    const view = renderStrategyStatusPage()

    await view.findByText('empty-book')
    await user.click(view.getByRole('button', { name: 'untradable (1)' }))

    expect(view.queryByText('ready')).not.toBeInTheDocument()
    expect(view.getByText('Untradable')).toBeInTheDocument()
    expect(view.getByText('missing_quote_depth:DOWN')).toBeInTheDocument()
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
