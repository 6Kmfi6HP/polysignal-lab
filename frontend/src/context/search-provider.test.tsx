/**
 * Input: { beforeEach, describe, expect, it, vi } from 'vitest', { act, fireEvent, render, type RenderResult } from '@testing-library/react', userEvent from '@testing-library/user-event', { SearchProvider } from '@/context/search-provider', vitest, @testing-library/react, @testing-library/user-event, @/context/search-provider
 * Output: renderWithSearchProvider, openCommandPalette
 * Pos: Application code
 *
 * 🔄 Self-reference: When this file changes, update this header
 */





import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, type RenderResult } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SearchProvider } from '@/context/search-provider'

const COMMAND_MENU_PLACEHOLDER = 'Type a command or search...'

const mocks = vi.hoisted(() => ({
  navigate: vi.fn(),
  setTheme: vi.fn(),
}))

vi.mock('@tanstack/react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-router')>()
  return {
    ...actual,
    useNavigate: () => mocks.navigate,
  }
})

vi.mock('@/context/theme-provider', () => ({
  useTheme: () => ({ setTheme: mocks.setTheme }),
}))

type ShortcutModifier = 'Control' | 'Meta'

async function renderWithSearchProvider() {
  return await render(<SearchProvider>{null}</SearchProvider>)
}

async function openCommandPalette(
  screen: RenderResult,
  modifier: ShortcutModifier = 'Control'
) {
  await act(async () => {
    fireEvent.keyDown(document, {
      key: 'k',
      ctrlKey: modifier === 'Control',
      metaKey: modifier === 'Meta',
    })
  })
  await screen.findByPlaceholderText(COMMAND_MENU_PLACEHOLDER)
}

describe('SearchProvider and CommandMenu', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the command palette when the palette is open', async () => {
    const screen = await renderWithSearchProvider()
    const { getByPlaceholderText, getByText } = screen

    await openCommandPalette(screen)

    expect(getByPlaceholderText(COMMAND_MENU_PLACEHOLDER))
      .toBeInTheDocument()
    expect(getByText('Theme')).toBeInTheDocument()
    expect(getByText('Light')).toBeInTheDocument()
    expect(getByText('Dark')).toBeInTheDocument()
    expect(getByText('System')).toBeInTheDocument()
    expect(getByText('Overview')).toBeInTheDocument()
  })

  it('does not show the dialog content when search is closed', async () => {
    const { queryByPlaceholderText } = await renderWithSearchProvider()

    expect(queryByPlaceholderText(COMMAND_MENU_PLACEHOLDER))
      .not.toBeInTheDocument()
  })

  it.each([
    ['Ctrl', 'Control'],
    ['Cmd', 'Meta'],
  ] as const)(
    'opens the command menu when %s + K is pressed',
    async (_label, modifier) => {
      const screen = await renderWithSearchProvider()

      expect(screen.queryByPlaceholderText(COMMAND_MENU_PLACEHOLDER))
        .not.toBeInTheDocument()

      await openCommandPalette(screen, modifier)

      expect(screen.getByPlaceholderText(COMMAND_MENU_PLACEHOLDER))
        .toBeInTheDocument()
    }
  )

  it('navigates to a top-level route and closes the palette when a nav item is selected', async () => {
    const screen = await renderWithSearchProvider()

    await openCommandPalette(screen)

    await userEvent.click(screen.getByText('Overview'))

    expect(mocks.navigate).toHaveBeenCalledWith({ to: '/' })
    expect(screen.queryByPlaceholderText(COMMAND_MENU_PLACEHOLDER))
      .not.toBeInTheDocument()
  })

  it('navigates to another top-level route and closes the palette when selected', async () => {
    const screen = await renderWithSearchProvider()
    const { getByRole } = screen

    await openCommandPalette(screen)

    await userEvent.click(getByRole('option', { name: 'Signals' }))

    expect(mocks.navigate).toHaveBeenCalledWith({ to: '/signals' })
    expect(screen.queryByPlaceholderText(COMMAND_MENU_PLACEHOLDER))
      .not.toBeInTheDocument()
  })

  it('applies theme and closes the palette when a theme command is chosen', async () => {
    const screen = await renderWithSearchProvider()

    await openCommandPalette(screen)

    await userEvent.click(screen.getByText('Dark'))

    expect(mocks.setTheme).toHaveBeenCalledWith('dark')
    expect(screen.queryByPlaceholderText(COMMAND_MENU_PLACEHOLDER))
      .not.toBeInTheDocument()
  })

  it('shows empty state when the filter matches nothing', async () => {
    const screen = await renderWithSearchProvider()

    await openCommandPalette(screen)

    await userEvent.type(
      screen.getByPlaceholderText(COMMAND_MENU_PLACEHOLDER),
      'zzzz-no-match-xxxx'
    )

    expect(screen.getByText('No results found.'))
      .toBeInTheDocument()
  })
})
