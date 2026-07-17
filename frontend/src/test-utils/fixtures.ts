/**
 * Input: type {, @/lib/api/types
 * Output: makeSignal, makeRejectedSignal, makeReportOrder, makeReportPosition, makeReportTradeResult, makeDailyReport, makeOverviewResponse, makeHealthResponse, makeStrategyStatusRow, makeLeaderboardResponse
 * Pos: Application code
 *
 * 🔄 Self-reference: When this file changes, update this header
 */









import type {
  DailyReport,
  HealthResponse,
  LeaderboardResponse,
  OverviewResponse,
  ReportOrder,
  ReportPosition,
  ReportTradeResult,
  RejectedSignal,
  SignalCandidate,
  StrategyStatusRow,
} from '@/lib/api/types'

export function makeSignal(overrides: Partial<SignalCandidate> = {}): SignalCandidate {
  return {
    schema_version: 1,
    signal_id: 'sig-1',
    created_at: '2026-06-30T00:00:00+00:00',
    strategy: 'ptb_diff',
    asset: 'BTC',
    timeframe: '5m',
    market_id: 'mkt-1',
    market_slug: 'btc-updown-5m',
    condition_id: 'cond-1',
    token_id: 'token-up',
    action: 'BUY',
    side: 'UP',
    confidence: 0.7,
    entry_reference_price: 0.5,
    max_entry_price: 0.55,
    seconds_to_close: 120,
    data_freshness_ms: 50,
    reason_codes: [],
    metrics: {},
    dedupe_key: 'BTC:5m:mkt-1:UP:ptb_diff',
    snapshot_id: null,
    source_signal_ids: [],
    order_intent: null,
    expiry_seconds: null,
    pair_id: null,
    hedge_leg: false,
    ...overrides,
  }
}

export function makeRejectedSignal(
  overrides: Partial<RejectedSignal> = {}
): RejectedSignal {
  return {
    schema_version: 1,
    rejected_id: 'rej-1',
    candidate: makeSignal(),
    rejected_at: '2026-06-30T00:00:00+00:00',
    gate_name: 'freshness_gate',
    reason_code: 'STALE_SPOT_PRICE',
    details: {},
    ...overrides,
  }
}

export function makeReportOrder(overrides: Partial<ReportOrder> = {}): ReportOrder {
  return {
    schema_version: 1,
    report_order_id: 'ro-1',
    signal_id: 'sig-1',
    created_at: '2026-06-30T00:00:00+00:00',
    asset: 'BTC',
    timeframe: '5m',
    strategy: 'ptb_diff',
    market_id: 'mkt-1',
    market_slug: 'btc-updown-5m',
    token_id: 'token-up',
    side: 'UP',
    order_type: 'SIMULATED_MARKETABLE_LIMIT',
    order_intent: null,
    limit_price: 0.55,
    reference_price: 0.5,
    stake_usdc: 10,
    shares: 18,
    signal_confidence: 0.7,
    status: 'FILLED',
    reject_reason: null,
    metrics: {},
    ...overrides,
  }
}

export function makeReportPosition(
  overrides: Partial<ReportPosition> = {}
): ReportPosition {
  return {
    schema_version: 1,
    report_position_id: 'rp-1',
    signal_id: 'sig-1',
    report_order_id: 'ro-1',
    report_fill_id: 'rf-1',
    strategy: 'ptb_diff',
    asset: 'BTC',
    timeframe: '5m',
    market_id: 'mkt-1',
    market_slug: 'btc-updown-5m',
    token_id: 'token-up',
    side: 'UP',
    entry_price: 0.5,
    shares: 18,
    stake_usdc: 10,
    signal_confidence: 0.7,
    opened_at: '2026-06-30T00:00:00+00:00',
    status: 'OPEN',
    closed_at: null,
    ...overrides,
  }
}

export function makeReportTradeResult(
  overrides: Partial<ReportTradeResult> = {}
): ReportTradeResult {
  return {
    schema_version: 1,
    report_result_id: 'rr-1',
    signal_id: 'sig-1',
    report_position_id: 'rp-1',
    strategy: 'ptb_diff',
    asset: 'BTC',
    timeframe: '5m',
    market_id: 'mkt-1',
    market_slug: 'btc-updown-5m',
    side: 'UP',
    entry_price: 0.5,
    shares: 18,
    stake_usdc: 10,
    exit_mode: 'RESOLUTION',
    outcome_value: 1,
    settlement_value: 1,
    pnl_usdc: 4,
    roi: 0.4,
    result: 'WIN',
    opened_at: '2026-06-30T00:00:00+00:00',
    closed_at: '2026-06-30T00:05:00+00:00',
    details: {},
    ...overrides,
  }
}

export function makeDailyReport(overrides: Partial<DailyReport> = {}): DailyReport {
  return {
    report_id: 'dr-1',
    report_date: '2026-06-30',
    revision: 1,
    starting_equity: 1000,
    ending_equity: 1004,
    net_pnl: 4,
    return_rate: 0.004,
    total_signals: 3,
    order_count: 3,
    fill_count: 3,
    rejected_order_count: 0,
    rejects_by_reason: {},
    average_execution_staleness_ms: 25,
    open_positions: 0,
    closed_positions: 1,
    win_count: 1,
    loss_count: 0,
    void_count: 0,
    win_rate: 1,
    total_pnl_usdc: 4,
    average_roi: 0.12,
    max_drawdown: 0,
    profit_factor: null,
    strategy_breakdown: {},
    calibration_breakdown: {},
    created_at: '2026-06-30T00:00:00+00:00',
    ...overrides,
  }
}

export function makeOverviewResponse(
  overrides: Partial<OverviewResponse> = {}
): OverviewResponse {
  return {
    counts: {
      signals: 3,
      rejected_signals: 1,
      report_positions: 1,
      report_results: 1,
      daily_reports: 1,
    },
    latest_report: makeDailyReport(),
    calibration_breakdown: {},
    strategy_status: [],
    ...overrides,
  }
}

export function makeHealthResponse(
  overrides: Partial<HealthResponse> = {}
): HealthResponse {
  return {
    status: 'ok',
    generated_at: null,
    components: [],
    counts: {},
    recent_system_events: [],
    ...overrides,
  }
}

export function makeStrategyStatusRow(
  overrides: Partial<StrategyStatusRow> = {}
): StrategyStatusRow {
  return {
    strategy: 'ptb_diff',
    asset: 'ETH',
    timeframe: '5m',
    status: 'unsupported_market',
    reason: 'UNSUPPORTED_ASSET',
    ...overrides,
  }
}

export function makeLeaderboardResponse(
  overrides: Partial<LeaderboardResponse> = {}
): LeaderboardResponse {
  return {
    leaderboard: [
      {
        strategy: 'ptb_diff',
        closed_positions: 2,
        win_count: 1,
        loss_count: 1,
        void_count: 0,
        total_pnl_usdc: 4,
        average_roi: 0.12,
        win_rate: 0.5,
      },
    ],
    calibration_breakdown: {},
    ...overrides,
  }
}
