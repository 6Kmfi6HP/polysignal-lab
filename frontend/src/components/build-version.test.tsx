import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/lib/api/client'
import { LocaleProvider } from '@/context/locale-provider'
import { BuildVersion } from './build-version'

const build = {
  application_version: '1.0.0',
  build_version: '1.0.0-main.185+abcdef123456',
  channel: 'main',
  source_ref: 'main',
  commit_sha: 'abcdef1234567890abcdef1234567890abcdef12',
  short_commit_sha: 'abcdef123456',
  immutable_tag: 'sha-abcdef1234567890abcdef1234567890abcdef12',
}

function renderVersion() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <LocaleProvider>
        <BuildVersion />
      </LocaleProvider>
    </QueryClientProvider>
  )
}

describe('BuildVersion', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('shows a compact identity and opens complete build details', async () => {
    vi.spyOn(api, 'getVersion').mockResolvedValue(build)
    const user = userEvent.setup()
    const view = renderVersion()

    expect(
      await view.findByText('1.0.0-main.185+abcdef123456 · abcdef123456')
    ).toBeInTheDocument()

    await user.click(
      view.getByRole('button', { name: 'View build information' })
    )

    expect(view.getByRole('dialog')).toBeInTheDocument()
    expect(view.getByText(build.commit_sha)).toBeInTheDocument()
    expect(view.getByText(build.immutable_tag)).toBeInTheDocument()
  })

  it('copies a source value from the detail sheet', async () => {
    vi.spyOn(api, 'getVersion').mockResolvedValue(build)
    const user = userEvent.setup()
    const writeText = vi
      .spyOn(navigator.clipboard, 'writeText')
      .mockResolvedValue(undefined)
    const view = renderVersion()

    await user.click(
      await view.findByRole('button', { name: 'View build information' })
    )
    await user.click(view.getByRole('button', { name: 'Copy Commit SHA' }))

    expect(writeText).toHaveBeenCalledWith(build.commit_sha)
  })

  it('degrades only the version entry when the endpoint is unavailable', async () => {
    vi.spyOn(api, 'getVersion').mockRejectedValue(new Error('offline'))
    const user = userEvent.setup()
    const view = renderVersion()

    await waitFor(() =>
      expect(view.getByText('Version unavailable')).toBeInTheDocument()
    )
    await user.click(
      view.getByRole('button', { name: 'View build information' })
    )

    expect(
      view.getByText('Build information could not be loaded.')
    ).toBeInTheDocument()
  })
})
