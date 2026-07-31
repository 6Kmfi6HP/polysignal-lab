export type Side = 'UP' | 'DOWN'
export type OrderStatus =
  'PENDING' | 'FILLED' | 'REJECTED' | 'RESTING' | 'CANCELLED' | 'PARTIAL'
export type PositionStatus = 'OPEN' | 'CLOSED'
export type TradeResultStatus = 'WIN' | 'LOSS' | 'VOID' | 'SPLIT' | 'UNKNOWN'
export type ExitMode =
  'RESOLUTION' | 'TAKE_PROFIT' | 'STOP_LOSS' | 'MAX_HOLD_TIME' | 'UNKNOWN'
export type CalibrationStatus = 'unknown' | 'insufficient_data' | 'calibrated'
export type StrategyStatus =
  | 'active'
  | 'disabled'
  | 'inactive'
  | 'unsupported_market'
  | 'missing_data'
  | 'untradable'
  | 'uncalibrated'

export interface SignalCandidate {
  schema_version: number
  signal_id: string
  created_at: string
  strategy: string
  asset: string
  timeframe: string
  market_id: string
  market_slug: string
  condition_id: string
  token_id: string
  action: string
  side: Side
  confidence: number
  entry_reference_price: number
  max_entry_price: number
  seconds_to_close: number | null
  data_freshness_ms: number | null
  reason_codes: string[]
  metrics: Record<string, unknown>
  dedupe_key: string
  snapshot_id: string | null
  source_signal_ids: string[]
  order_intent: string | null
  expiry_seconds: number | null
  pair_id: string | null
  hedge_leg: boolean
}

export interface RejectedSignal {
  schema_version: number
  rejected_id: string
  candidate: SignalCandidate
  rejected_at: string
  gate_name: string
  reason_code: string
  details: Record<string, unknown>
}

export interface ReportOrder {
  schema_version: number
  report_order_id: string
  signal_id: string
  created_at: string
  asset: string
  timeframe: string
  strategy: string
  market_id: string
  market_slug: string
  token_id: string
  side: Side
  order_type: string
  order_intent: string | null
  limit_price: number
  reference_price: number
  stake_usdc: number
  shares: number | null
  signal_confidence: number | null
  status: OrderStatus
  reject_reason: string | null
  metrics: Record<string, unknown>
}

export interface ReportPosition {
  schema_version: number
  report_position_id: string
  signal_id: string
  report_order_id: string
  report_fill_id: string
  strategy: string
  asset: string
  timeframe: string
  market_id: string
  market_slug: string
  token_id: string
  side: Side
  entry_price: number
  shares: number
  stake_usdc: number
  signal_confidence: number | null
  opened_at: string
  status: PositionStatus
  closed_at: string | null
}

export interface ReportTradeResult {
  schema_version: number
  report_result_id: string
  signal_id: string
  report_position_id: string
  strategy: string
  asset: string
  timeframe: string
  market_id: string
  market_slug: string
  side: Side
  entry_price: number
  shares: number
  stake_usdc: number
  exit_mode: ExitMode
  outcome_value: number
  settlement_value: number
  pnl_usdc: number
  roi: number
  result: TradeResultStatus
  opened_at: string
  closed_at: string
  details: Record<string, unknown>
}

export interface ReportSummary {
  total_pnl_usdc: number
  average_roi: number
  closed_trades: number
}

export interface CalibrationBucket {
  strategy: string
  asset: string
  timeframe: string
  confidence_bucket: string
  sample_size: number
  wins: number
  losses: number
  calibration_status: CalibrationStatus
  [key: string]: unknown
}

export interface DailyReport {
  report_id: string
  report_date: string
  revision: number
  starting_equity: number
  ending_equity: number
  equity_currency?: string
  equity_source?: 'portfolio' | 'account_balance' | 'starting_balance' | null
  net_pnl: number
  return_rate: number
  total_signals: number
  order_count: number
  fill_count: number
  rejected_order_count: number
  rejects_by_reason: Record<string, number>
  telemetry_status?: 'complete' | 'incomplete'
  telemetry_incomplete_reasons?: string[]
  average_execution_staleness_ms: number | null
  open_positions: number
  closed_positions: number
  win_count: number
  loss_count: number
  void_count: number
  win_rate: number
  total_pnl_usdc: number
  average_roi: number
  max_drawdown: number
  profit_factor: number | null
  strategy_breakdown: Record<string, unknown>
  calibration_breakdown: Record<string, CalibrationBucket>
  created_at: string
}

export interface StrategyStatusRow {
  strategy: string
  asset: string
  timeframe: string
  status: StrategyStatus
  reason: string | null
}

export interface LeaderboardRow {
  strategy: string
  closed_positions: number
  win_count: number
  loss_count: number
  void_count: number
  total_pnl_usdc: number
  average_roi: number
  win_rate: number
}

export interface OverviewResponse {
  counts: Record<string, number>
  latest_report: DailyReport | null
  calibration_breakdown: Record<string, CalibrationBucket>
  strategy_status: StrategyStatusRow[]
}

export interface LeaderboardResponse {
  leaderboard: LeaderboardRow[]
  calibration_breakdown: Record<string, CalibrationBucket>
}

export interface HealthComponent {
  name: string
  status: string
  last_success_at: string | null
  last_error_at: string | null
  last_error: string | null
  metrics: Record<string, unknown>
}

export interface HealthResponse {
  status: string
  generated_at: string | null
  components: HealthComponent[]
  counts: Record<string, number>
  recent_system_events: Record<string, unknown>[]
}
