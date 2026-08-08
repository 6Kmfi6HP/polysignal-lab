import { useQuery } from '@tanstack/react-query'
import * as api from './client'

export const LIVE_REFRESH_MS = 15_000
export const HEALTH_REFRESH_MS = 30_000

export function useVersionQuery() {
  return useQuery({
    queryKey: ['version'],
    queryFn: api.getVersion,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    retry: false,
  })
}

export function useHealthQuery() {
  return useQuery({
    queryKey: ['health'],
    queryFn: api.getHealth,
    refetchInterval: HEALTH_REFRESH_MS,
  })
}

export function useOverviewQuery() {
  return useQuery({
    queryKey: ['overview'],
    queryFn: api.getOverview,
    refetchInterval: LIVE_REFRESH_MS,
  })
}

export function useSignalsQuery(limit = 100) {
  return useQuery({
    queryKey: ['signals', limit],
    queryFn: () => api.getSignals(limit),
    refetchInterval: LIVE_REFRESH_MS,
  })
}

export function useRejectedSignalsQuery(limit = 100) {
  return useQuery({
    queryKey: ['rejected-signals', limit],
    queryFn: () => api.getRejectedSignals(limit),
    refetchInterval: LIVE_REFRESH_MS,
  })
}

export function useReportOrdersQuery({
  status,
  pageIndex,
  pageSize,
}: {
  status?: string
  pageIndex: number
  pageSize: number
}) {
  return useQuery({
    queryKey: ['report-orders', status, pageIndex, pageSize],
    queryFn: () =>
      api.getReportOrders({
        status,
        limit: pageSize,
        offset: pageIndex * pageSize,
      }),
    refetchInterval: pageIndex === 0 ? LIVE_REFRESH_MS : false,
  })
}

export function usePositionsQuery({
  status,
  pageIndex,
  pageSize,
}: {
  status?: string
  pageIndex: number
  pageSize: number
}) {
  return useQuery({
    queryKey: ['positions', status, pageIndex, pageSize],
    queryFn: () =>
      api.getPositions({
        status,
        limit: pageSize,
        offset: pageIndex * pageSize,
      }),
    refetchInterval: pageIndex === 0 ? LIVE_REFRESH_MS : false,
  })
}

export function useTradesQuery({
  pageIndex,
  pageSize,
}: {
  pageIndex: number
  pageSize: number
}) {
  return useQuery({
    queryKey: ['trades', pageIndex, pageSize],
    queryFn: () =>
      api.getTrades({
        limit: pageSize,
        offset: pageIndex * pageSize,
      }),
    refetchInterval: pageIndex === 0 ? LIVE_REFRESH_MS : false,
  })
}

export function useTradesChartQuery(limit = 500) {
  return useQuery({
    queryKey: ['trades-chart', limit],
    queryFn: () => api.getTrades({ limit, offset: 0 }),
    refetchInterval: LIVE_REFRESH_MS,
  })
}

export function useReportSummaryQuery() {
  return useQuery({
    queryKey: ['report-summary'],
    queryFn: api.getReportSummary,
    refetchInterval: LIVE_REFRESH_MS,
  })
}

export function useLeaderboardQuery(limit = 100) {
  return useQuery({
    queryKey: ['leaderboard', limit],
    queryFn: () => api.getLeaderboard(limit),
    refetchInterval: LIVE_REFRESH_MS,
  })
}

export function useStrategyStatusQuery(limit = 100) {
  return useQuery({
    queryKey: ['strategy-status', limit],
    queryFn: () => api.getStrategyStatus(limit),
    refetchInterval: LIVE_REFRESH_MS,
  })
}
