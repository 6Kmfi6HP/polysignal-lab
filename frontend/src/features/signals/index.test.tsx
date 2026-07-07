/**
 * Input: { SearchProvider } from '@/context/search-provider', { ThemeProvider } from '@/context/theme-provider', * as client from '@/lib/api/client', { makeRejectedSignal, makeSignal } from '@/test-utils/fixtures', { renderWithQueryClient } from '@/test-utils/render-with-query-client', { SidebarProvider } from '@/components/ui/sidebar', { within } from '@testing-library/react', userEvent from '@testing-library/user-event', { afterEach, describe, expect, it, vi } from 'vitest', { SignalsPage } from './index'
 * Output: renderSignalsPage
 * Pos: Application code
 *
 * 🔄 Self-reference: When this file changes, update this header
 */







import { SearchProvider } from '@/context/search-provider'
import { ThemeProvider } from '@/context/theme-provider'
import * as client from '@/lib/api/client'
import { makeRejectedSignal, makeSignal } from '@/test-utils/fixtures'
import { renderWithQueryClient } from '@/test-utils/render-with-query-client'
import { SidebarProvider } from '@/components/ui/sidebar'
import { within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
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

    expect(await view.findByText('sig-accepted')).toBeInTheDocument()
    const acceptedTab = view.getByRole('tab', { name: 'Accepted' })
    expect(acceptedTab).toHaveAttribute('aria-selected', 'true')
    expect(view.queryByText('STALE_SPOT_PRICE')).not.toBeInTheDocument()

    const rejectedTab = view.getByRole('tab', { name: 'Rejected' })
    await user.click(rejectedTab)

    expect(rejectedTab).toHaveAttribute('aria-selected', 'true')
    expect(view.queryByText('sig-accepted')).not.toBeInTheDocument()
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

    expect(await view.findByText('No rejected signals yet.')).toBeInTheDocument()
  })
})
