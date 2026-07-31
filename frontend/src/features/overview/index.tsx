import { useHealthQuery, useOverviewQuery } from '@/lib/api/hooks'
import {
  formatDateTime,
  formatFreshness,
  formatMoney,
  formatPercent,
} from '@/lib/format'
import { Skeleton } from '@/components/ui/skeleton'
import {
  EmptyState,
  ErrorState,
  Metric,
  MetricStrip,
  PageHeader,
  StatusBadge,
  TableFrame,
} from '@/components/dashboard'
import { Main } from '@/components/layout/main'

export function OverviewPage() {
  const overview = useOverviewQuery()
  const health = useHealthQuery()
  const report = overview.data?.latest_report

  return (
    <>
      <Main>
        <PageHeader
          title='Overview'
          description='Portfolio performance, telemetry quality, and strategy readiness at a glance.'
          meta={
            health.data ? (
              <StatusBadge status={health.data.status} />
            ) : undefined
          }
        />
        {overview.isPending && <Skeleton className='h-48 w-full rounded-xl' />}
        {overview.isError && (
          <ErrorState
            message={`Failed to load overview: ${overview.error.message}`}
          />
        )}
        {overview.data && (
          <div className='space-y-6'>
            {report ? (
              <MetricStrip>
                <Metric
                  label='Ending equity'
                  value={formatMoney(
                    report.ending_equity,
                    report.equity_currency ?? 'currency unavailable'
                  )}
                  detail={
                    report.equity_source
                      ? equitySourceLabel(report.equity_source)
                      : undefined
                  }
                />
                <Metric
                  label='Net PnL'
                  value={formatMoney(
                    report.net_pnl,
                    report.equity_currency ?? 'currency unavailable'
                  )}
                  tone={report.net_pnl >= 0 ? 'positive' : 'danger'}
                />
                <Metric
                  label='Return'
                  value={formatPercent(report.return_rate, true)}
                  tone={report.return_rate >= 0 ? 'positive' : 'danger'}
                />
                <Metric label='Open positions' value={report.open_positions} />
                <Metric
                  label='Win rate'
                  value={formatPercent(report.win_rate)}
                  detail={`${report.win_count} wins / ${report.loss_count} losses`}
                />
              </MetricStrip>
            ) : (
              <EmptyState
                title='No daily report has been stored yet.'
                description='Performance metrics appear after the first reporting cycle completes.'
              />
            )}

            <section aria-labelledby='activity-heading'>
              <h2 id='activity-heading' className='mb-3 text-sm font-semibold'>
                Stored activity
              </h2>
              <div className='flex flex-wrap gap-x-6 gap-y-2 border-y px-1 py-3'>
                {Object.entries(overview.data.counts).map(([table, count]) => (
                  <div key={table} className='flex items-baseline gap-2'>
                    <span className='text-sm text-muted-foreground capitalize'>
                      {table.replace(/_/g, ' ')}
                    </span>
                    <span className='font-mono font-semibold tabular-nums'>
                      {count}
                    </span>
                  </div>
                ))}
              </div>
            </section>

            {report && (
              <section aria-labelledby='report-heading'>
                <div className='mb-3 flex flex-wrap items-end justify-between gap-2'>
                  <div>
                    <h2 id='report-heading' className='text-base font-semibold'>
                      Latest daily report
                    </h2>
                    <p className='text-xs text-muted-foreground'>
                      {report.report_date} · updated{' '}
                      {formatDateTime(report.created_at)}
                    </p>
                  </div>
                  <StatusBadge
                    status={report.telemetry_status ?? 'status unavailable'}
                  />
                </div>
                <TableFrame>
                  <div className='grid gap-px bg-border sm:grid-cols-2 lg:grid-cols-4'>
                    {[
                      ['Signals', report.total_signals],
                      ['Rejected orders', report.rejected_order_count],
                      [
                        'Execution staleness',
                        formatFreshness(report.average_execution_staleness_ms),
                      ],
                      ['Max drawdown', formatPercent(report.max_drawdown)],
                      [
                        'Profit factor',
                        report.profit_factor?.toFixed(2) ?? 'Unavailable',
                      ],
                      ['Average ROI', formatPercent(report.average_roi, true)],
                      ['Closed positions', report.closed_positions],
                      ['Fills', report.fill_count],
                    ].map(([label, value]) => (
                      <div key={label} className='bg-card p-4'>
                        <p className='text-xs text-muted-foreground'>{label}</p>
                        <p className='mt-1 font-mono font-semibold tabular-nums'>
                          {value}
                        </p>
                      </div>
                    ))}
                  </div>
                </TableFrame>
                {report.telemetry_status === 'incomplete' && (
                  <p className='mt-3 text-sm text-warning'>
                    {telemetryReasonsLabel(report.telemetry_incomplete_reasons)}
                  </p>
                )}
              </section>
            )}

            <div className='grid gap-6 lg:grid-cols-2'>
              <OverviewList
                title='Calibration coverage'
                empty='No calibration rows available.'
                values={Object.values(overview.data.calibration_breakdown).map(
                  (row) => ({
                    label: `${row.strategy} / ${row.asset} / ${row.timeframe}`,
                    status: row.calibration_status,
                    detail: `${row.sample_size} samples`,
                  })
                )}
              />
              <OverviewList
                title='Strategy readiness'
                empty='No strategy readiness rows available.'
                values={overview.data.strategy_status.map((row) => ({
                  label: `${row.strategy} / ${row.asset} / ${row.timeframe}`,
                  status: row.status,
                  detail: row.reason ?? 'Ready',
                }))}
              />
            </div>
          </div>
        )}
      </Main>
    </>
  )
}

function OverviewList({
  title,
  empty,
  values,
}: {
  title: string
  empty: string
  values: { label: string; status: string; detail: string }[]
}) {
  return (
    <section>
      <h2 className='mb-3 text-base font-semibold'>{title}</h2>
      <TableFrame>
        {values.length ? (
          <div>
            {values.map((item) => (
              <div
                key={`${item.label}-${item.status}`}
                className='flex items-start justify-between gap-4 border-b p-3 last:border-0'
              >
                <div className='min-w-0'>
                  <p className='truncate font-mono text-xs'>{item.label}</p>
                  <p className='mt-1 text-xs text-muted-foreground'>
                    {item.detail}
                  </p>
                </div>
                <StatusBadge status={item.status} />
              </div>
            ))}
          </div>
        ) : (
          <div className='p-4 text-sm text-muted-foreground'>{empty}</div>
        )}
      </TableFrame>
    </section>
  )
}

function equitySourceLabel(
  source: 'portfolio' | 'account_balance' | 'starting_balance'
): string {
  return source === 'portfolio'
    ? 'Portfolio'
    : source === 'account_balance'
      ? 'Account balance'
      : 'Starting balance'
}

function telemetryReasonsLabel(reasons: string[] | undefined): string {
  if (reasons === undefined) return 'Reasons unavailable'
  if (reasons.length === 0) return 'No incomplete reasons reported'
  return `Reasons: ${reasons.join('; ')}`
}
