import type { ReactNode } from 'react'
import { makeLeaderboardResponse } from '@/test-utils/fixtures'
import { renderWithQueryClient } from '@/test-utils/render-with-query-client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import * as client from '@/lib/api/client'
import { LeaderboardPage } from './index'

vi.mock('recharts', () => ({
  Bar: () => null,
  Cell: () => null,
  ReferenceLine: () => null,
  Tooltip: () => null,
  CartesianGrid: () => null,
  XAxis: () => null,
  YAxis: () => null,
  ResponsiveContainer: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  BarChart: ({ children, data }: { children: ReactNode; data: unknown }) => (
    <div data-testid='pnl-chart-data'>
      {JSON.stringify(data)}
      {children}
    </div>
  ),
}))

function renderLeaderboardPage() {
  return renderWithQueryClient(<LeaderboardPage />)
}

describe('LeaderboardPage', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders the leaderboard table with stored strategy rows and a PnL chart', async () => {
    vi.spyOn(client, 'getLeaderboard').mockResolvedValue(
      makeLeaderboardResponse({
        leaderboard: [
          {
            strategy: 'late_consensus',
            closed_positions: 2,
            win_count: 1,
            loss_count: 0,
            void_count: 1,
            total_pnl_usdc: 4,
            average_roi: 0.12,
            win_rate: 0.5,
          },
        ],
      })
    )

    const view = renderLeaderboardPage()

    expect(await view.findByText('late_consensus')).toBeInTheDocument()
    expect(view.getByText('50.0%')).toBeInTheDocument()
    expect(view.getByText('+4.00 USDC')).toBeInTheDocument()
    expect(view.getByText('Total PnL by strategy')).toBeInTheDocument()
    expect(
      JSON.parse(view.getByTestId('pnl-chart-data').textContent ?? '[]')
    ).toEqual([
      {
        strategy: 'late_consensus',
        closed_positions: 2,
        win_count: 1,
        loss_count: 0,
        void_count: 1,
        total_pnl_usdc: 4,
        average_roi: 0.12,
        win_rate: 0.5,
      },
    ])
  })

  it('renders empty states when no leaderboard rows are stored', async () => {
    vi.spyOn(client, 'getLeaderboard').mockResolvedValue(
      makeLeaderboardResponse({ leaderboard: [] })
    )

    const view = renderLeaderboardPage()

    expect(await view.findAllByText('No stored report rows yet.')).toHaveLength(
      2
    )
  })

  it('renders a loading placeholder while leaderboard data loads', () => {
    vi.spyOn(client, 'getLeaderboard').mockReturnValue(Promise.race([]))

    const { container } = renderLeaderboardPage()

    expect(
      container.querySelector('[data-slot="skeleton"]')
    ).toBeInTheDocument()
  })

  it('renders an error message when leaderboard data fails to load', async () => {
    vi.spyOn(client, 'getLeaderboard').mockRejectedValue(new Error('boom'))

    const view = renderLeaderboardPage()

    expect(
      await view.findByText('Failed to load leaderboard: boom')
    ).toBeInTheDocument()
  })
})
