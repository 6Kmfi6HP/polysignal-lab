/**
 * Input: { useQuery } from '@tanstack/react-query', * as api from './client', @tanstack/react-query, ./client
 * Output: LIVE_REFRESH_MS, HEALTH_REFRESH_MS, useHealthQuery, useOverviewQuery, useSignalsQuery, useRejectedSignalsQuery, usePaperOrdersQuery, usePositionsQuery, useTradesQuery, useLeaderboardQuery
 * Pos: Library - Shared code
 *
 * 🔄 Self-reference: When this file changes, update this header
 */







import { useQuery } from '@tanstack/react-query'
import * as api from './client'

export const LIVE_REFRESH_MS = 15_000
export const HEALTH_REFRESH_MS = 30_000

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

export function usePaperOrdersQuery(status?: string, limit = 100) {
  return useQuery({
    queryKey: ['paper-orders', status, limit],
    queryFn: () => api.getPaperOrders(status, limit),
    refetchInterval: LIVE_REFRESH_MS,
  })
}

export function usePositionsQuery(status?: string, limit = 100) {
  return useQuery({
    queryKey: ['positions', status, limit],
    queryFn: () => api.getPositions(status, limit),
    refetchInterval: LIVE_REFRESH_MS,
  })
}

export function useTradesQuery(limit = 100) {
  return useQuery({
    queryKey: ['trades', limit],
    queryFn: () => api.getTrades(limit),
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
