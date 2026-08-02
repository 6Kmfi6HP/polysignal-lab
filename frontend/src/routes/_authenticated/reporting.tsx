/* eslint-disable react-refresh/only-export-components */
import {
  createFileRoute,
  useNavigate,
  useRouterState,
} from '@tanstack/react-router'
import type { NavigateFn } from '@/hooks/use-table-url-state'
import { ReportingPage } from '@/features/reporting'

function toOptionalInt(value: unknown): number | undefined {
  if (value === undefined || value === null || value === '') return undefined
  const parsed = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(parsed)) return undefined
  return Math.floor(parsed)
}

function toPage(value: unknown): number | undefined {
  const parsed = toOptionalInt(value)
  if (parsed === undefined) return undefined
  return Math.max(1, parsed)
}

function toPageSize(value: unknown): number | undefined {
  const parsed = toOptionalInt(value)
  if (parsed === undefined) return undefined
  return Math.min(100, Math.max(25, parsed))
}

function ReportingRoute() {
  const navigate = useNavigate()
  const search = useRouterState({
    select: (state) => state.location.search as Record<string, unknown>,
  })
  return (
    <ReportingPage
      search={search}
      navigate={navigate as unknown as NavigateFn}
    />
  )
}

export const Route = createFileRoute('/_authenticated/reporting')({
  validateSearch: (search: Record<string, unknown>) => ({
    ...search,
    tradesPage: toPage(search.tradesPage),
    tradesPageSize: toPageSize(search.tradesPageSize),
    positionsPage: toPage(search.positionsPage),
    positionsPageSize: toPageSize(search.positionsPageSize),
    ordersPage: toPage(search.ordersPage),
    ordersPageSize: toPageSize(search.ordersPageSize),
  }),
  component: ReportingRoute,
})
