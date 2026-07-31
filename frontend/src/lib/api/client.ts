import type {
  HealthResponse,
  LeaderboardResponse,
  OverviewResponse,
  ReportOrder,
  ReportPosition,
  ReportSummary,
  ReportTradeResult,
  RejectedSignal,
  SignalCandidate,
  StrategyStatusRow,
} from './types'

const API_BASE = '/api'

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(
  path: string,
  params?: Record<string, string | number | undefined>
): Promise<T> {
  const url = new URL(path, window.location.origin)
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined) url.searchParams.set(key, String(value))
    }
  }
  const response = await fetch(url.toString())
  if (!response.ok) {
    throw new ApiError(
      response.status,
      `${path} failed with status ${response.status}`
    )
  }
  return response.json() as Promise<T>
}

export function getHealth() {
  return request<HealthResponse>('/health')
}

export function getOverview() {
  return request<OverviewResponse>(`${API_BASE}/overview`)
}

export function getSignals(limit = 100) {
  return request<SignalCandidate[]>(`${API_BASE}/signals`, { limit })
}

export function getRejectedSignals(limit = 100) {
  return request<RejectedSignal[]>(`${API_BASE}/rejected-signals`, { limit })
}

export function getReportOrders(status?: string, limit = 100) {
  return request<ReportOrder[]>(`${API_BASE}/report-orders`, { status, limit })
}

export function getPositions(status?: string, limit = 100) {
  return request<ReportPosition[]>(`${API_BASE}/positions`, { status, limit })
}

export function getTrades(limit = 100) {
  return request<ReportTradeResult[]>(`${API_BASE}/trades`, { limit })
}

export function getReportSummary() {
  return request<ReportSummary>(`${API_BASE}/report-summary`)
}

export function getLeaderboard(limit = 100) {
  return request<LeaderboardResponse>(`${API_BASE}/leaderboard`, { limit })
}

export function getStrategyStatus(limit = 100) {
  return request<StrategyStatusRow[]>(`${API_BASE}/strategy-status`, { limit })
}
