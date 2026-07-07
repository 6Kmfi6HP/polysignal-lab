/**
 * Input: type { ReactElement } from 'react', { QueryClient, QueryClientProvider } from '@tanstack/react-query', { render } from '@testing-library/react', react, @tanstack/react-query, @testing-library/react
 * Output: renderWithQueryClient
 * Pos: Application code
 *
 * 🔄 Self-reference: When this file changes, update this header
 */





import type { ReactElement } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'

export function renderWithQueryClient(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchInterval: false },
    },
  })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}
