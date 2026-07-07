/**
 * Input: { type QueryClient } from '@tanstack/react-query', { createRootRouteWithContext, Outlet } from '@tanstack/react-router', { ReactQueryDevtools } from '@tanstack/react-query-devtools', { TanStackRouterDevtools } from '@tanstack/react-router-devtools', { Toaster } from '@/components/ui/sonner', { NavigationProgress } from '@/components/navigation-progress', { GeneralError } from '@/features/errors/general-error', { NotFoundError } from '@/features/errors/not-found-error', @tanstack/react-query, @tanstack/react-router
 * Output: Route
 * Pos: API Layer - Route definitions
 *
 * 🔄 Self-reference: When this file changes, update this header
 */





import { type QueryClient } from '@tanstack/react-query'
import { createRootRouteWithContext, Outlet } from '@tanstack/react-router'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'
import { TanStackRouterDevtools } from '@tanstack/react-router-devtools'
import { Toaster } from '@/components/ui/sonner'
import { NavigationProgress } from '@/components/navigation-progress'
import { GeneralError } from '@/features/errors/general-error'
import { NotFoundError } from '@/features/errors/not-found-error'

export const Route = createRootRouteWithContext<{
  queryClient: QueryClient
}>()({
  component: () => {
    return (
      <>
        <NavigationProgress />
        <Outlet />
        <Toaster duration={5000} />
        {import.meta.env.MODE === 'development' && (
          <>
            <ReactQueryDevtools buttonPosition='bottom-left' />
            <TanStackRouterDevtools position='bottom-right' />
          </>
        )}
      </>
    )
  },
  notFoundComponent: NotFoundError,
  errorComponent: GeneralError,
})
