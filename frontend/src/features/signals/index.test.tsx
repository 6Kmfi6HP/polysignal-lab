import { makeRejectedSignal, makeSignal } from '@/test-utils/fixtures'
import { renderWithQueryClient } from '@/test-utils/render-with-query-client'
import { within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import * as client from '@/lib/api/client'
import { SearchProvider } from '@/context/search-provider'
import { ThemeProvider } from '@/context/theme-provider'
import { SidebarProvider } from '@/components/ui/sidebar'
import { SignalsPage } from './index'

function renderSignalsPage() {
  return renderWithQueryClient(
    <ThemeProvider>
      <SearchProvider>
        <SidebarProvider defaultOpen={false}>
          <SignalsPage />
        </SidebarProvider>
      </SearchProvider>
    </ThemeProvider>
  )
}

describe('SignalsPage', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('shows accepted signals by default and rejected signals on the rejected tab', async () => {
    vi.spyOn(client, 'getSignals').mockResolvedValue([
      makeSignal({ signal_id: 'sig-accepted' }),
    ])
    vi.spyOn(client, 'getRejectedSignals').mockResolvedValue([
      makeRejectedSignal({
        rejected_id: 'rej-1',
        reason_code: 'STALE_SPOT_PRICE',
      }),
    ])

    const user = userEvent.setup()
    const view = renderSignalsPage()

    expect(await view.findByText('BTC 5m')).toBeInTheDocument()
    const acceptedTab = view.getByRole('tab', { name: 'Accepted' })
    expect(acceptedTab).toHaveAttribute('aria-selected', 'true')
    expect(view.queryByText('STALE_SPOT_PRICE')).not.toBeInTheDocument()

    const rejectedTab = view.getByRole('tab', { name: 'Rejected' })
    await user.click(rejectedTab)

    expect(rejectedTab).toHaveAttribute('aria-selected', 'true')
    expect(
      await within(view.getByRole('tabpanel', { name: 'Rejected' })).findByText(
        'STALE_SPOT_PRICE'
      )
    ).toBeInTheDocument()
  })

  it('shows the accepted empty state', async () => {
    vi.spyOn(client, 'getSignals').mockResolvedValue([])
    vi.spyOn(client, 'getRejectedSignals').mockResolvedValue([])

    const view = renderSignalsPage()

    expect(await view.findByText('No stored signals yet.')).toBeInTheDocument()
  })

  it('opens and closes an accepted signal detail panel', async () => {
    vi.spyOn(client, 'getSignals').mockResolvedValue([
      makeSignal({ signal_id: 'sig-detail', market_slug: 'long-market-slug' }),
    ])
    vi.spyOn(client, 'getRejectedSignals').mockResolvedValue([])
    const user = userEvent.setup()
    const view = renderSignalsPage()

    await user.click(await view.findByRole('button', { name: 'View details' }))
    expect(view.getByRole('dialog')).toBeInTheDocument()
    expect(view.getAllByText('sig-detail')).toHaveLength(2)

    await user.keyboard('{Escape}')
    expect(view.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('shows accepted and rejected load errors', async () => {
    vi.spyOn(client, 'getSignals').mockRejectedValue(new Error('accepted boom'))
    vi.spyOn(client, 'getRejectedSignals').mockRejectedValue(
      new Error('rejected boom')
    )

    const user = userEvent.setup()
    const view = renderSignalsPage()

    expect(
      await view.findByText('Failed to load signals: accepted boom')
    ).toBeInTheDocument()

    await user.click(view.getByRole('tab', { name: 'Rejected' }))

    expect(
      await view.findByText('Failed to load rejected signals: rejected boom')
    ).toBeInTheDocument()
  })

  it('shows rejected empty and loading states', async () => {
    vi.spyOn(client, 'getSignals').mockResolvedValue([])
    vi.spyOn(client, 'getRejectedSignals').mockReturnValue(Promise.race([]))

    const user = userEvent.setup()
    const view = renderSignalsPage()

    expect(await view.findByText('No stored signals yet.')).toBeInTheDocument()

    await user.click(view.getByRole('tab', { name: 'Rejected' }))

    expect(
      view
        .getByRole('tabpanel', { name: 'Rejected' })
        .querySelector('[data-slot="skeleton"]')
    ).toBeInTheDocument()
  })

  it('shows the rejected empty state', async () => {
    vi.spyOn(client, 'getSignals').mockResolvedValue([])
    vi.spyOn(client, 'getRejectedSignals').mockResolvedValue([])

    const user = userEvent.setup()
    const view = renderSignalsPage()

    await user.click(view.getByRole('tab', { name: 'Rejected' }))

    expect(
      await view.findByText('No rejected signals yet.')
    ).toBeInTheDocument()
  })
})
