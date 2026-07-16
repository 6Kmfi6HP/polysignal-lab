/**
 * Input: { useHealthQuery, useOverviewQuery } from '@/lib/api/hooks', { Badge } from '@/components/ui/badge', {, { Skeleton } from '@/components/ui/skeleton', { Header } from '@/components/layout/header', { Main } from '@/components/layout/main', { Search } from '@/components/search', { ThemeSwitch } from '@/components/theme-switch', @/lib/api/hooks, @/components/ui/badge
 * Output: OverviewPage
 * Pos: Application code
 *
 * 🔄 Self-reference: When this file changes, update this header
 */







import { useHealthQuery, useOverviewQuery } from '@/lib/api/hooks'
import { Badge } from '@/components/ui/badge'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'

function equitySourceLabel(
  source: 'portfolio' | 'account_balance' | 'starting_balance'
): string {
  if (source === 'portfolio') return 'Portfolio'
  if (source === 'account_balance') return 'Account balance'
  return 'Starting balance'
}

function telemetryStatusLabel(
  status: 'complete' | 'incomplete' | undefined
): string {
  if (status === 'complete') return 'Complete'
  if (status === 'incomplete') return 'Incomplete'
  return 'Status unavailable'
}

function telemetryReasonsLabel(reasons: string[] | undefined): string {
  if (reasons === undefined) return 'Reasons unavailable'
  if (reasons.length === 0) return 'No incomplete reasons reported'
  return `Reasons: ${reasons.join('; ')}`
}

export function OverviewPage() {
  const overview = useOverviewQuery()
  const health = useHealthQuery()

  return (
    <>
      <Header>
        <div className='ml-auto flex items-center gap-2'>
          <Search />
          <ThemeSwitch />
        </div>
      </Header>
      <Main>
        <div className='mb-4 flex items-center justify-between'>
          <h1 className='text-2xl font-bold tracking-tight'>Overview</h1>
          {health.data && (
            <Badge
              variant={health.data.status === 'ok' ? 'default' : 'destructive'}
            >
              {health.data.status}
            </Badge>
          )}
        </div>

        {overview.isPending && <Skeleton className='h-48 w-full' />}
        {overview.isError && (
          <p className='text-destructive'>
            Failed to load overview: {overview.error.message}
          </p>
        )}

        {overview.data && (
          <>
            <div className='grid gap-4 sm:grid-cols-2 lg:grid-cols-5'>
              {Object.entries(overview.data.counts).map(([table, count]) => (
                <Card key={table}>
                  <CardHeader className='pb-2'>
                    <CardDescription className='capitalize'>
                      {table.replace(/_/g, ' ')}
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <CardTitle className='text-2xl'>{count}</CardTitle>
                  </CardContent>
                </Card>
              ))}
            </div>

            <Card className='mt-6'>
              <CardHeader>
                <CardTitle>Latest daily report</CardTitle>
              </CardHeader>
              <CardContent>
                {overview.data.latest_report ? (
                  <dl className='grid gap-4 sm:grid-cols-2 lg:grid-cols-5'>
                    <div>
                      <dt className='text-sm text-muted-foreground'>
                        Report date
                      </dt>
                      <dd className='font-semibold'>
                        {overview.data.latest_report.report_date}
                      </dd>
                    </div>
                    <div>
                      <dt className='text-sm text-muted-foreground'>
                        Total signals
                      </dt>
                      <dd className='font-semibold'>
                        {overview.data.latest_report.total_signals}
                      </dd>
                    </div>
                    <div>
                      <dt className='text-sm text-muted-foreground'>
                        Closed positions
                      </dt>
                      <dd className='font-semibold'>
                        {overview.data.latest_report.closed_positions}
                      </dd>
                    </div>
                    <div>
                      <dt className='text-sm text-muted-foreground'>
                        Paper PnL
                      </dt>
                      <dd className='font-semibold'>
                        {overview.data.latest_report.paper_pnl.toFixed(2)}{' '}
                        {overview.data.latest_report.equity_currency ??
                          '(currency unavailable)'}
                      </dd>
                    </div>
                    {overview.data.latest_report.equity_source && (
                      <div>
                        <dt className='text-sm text-muted-foreground'>
                          Equity source
                        </dt>
                        <dd className='font-semibold'>
                          {equitySourceLabel(
                            overview.data.latest_report.equity_source
                          )}
                        </dd>
                      </div>
                    )}
                    <div>
                      <dt className='text-sm text-muted-foreground'>
                        Telemetry
                      </dt>
                      <dd className='font-semibold'>
                        {telemetryStatusLabel(
                          overview.data.latest_report.telemetry_status
                        )}
                      </dd>
                      {overview.data.latest_report.telemetry_status ===
                        'incomplete' && (
                        <dd className='text-sm text-muted-foreground'>
                          {telemetryReasonsLabel(
                            overview.data.latest_report
                              .telemetry_incomplete_reasons
                          )}
                        </dd>
                      )}
                    </div>
                  </dl>
                ) : (
                  <p className='text-muted-foreground'>
                    No daily report has been stored yet.
                  </p>
                )}
              </CardContent>
            </Card>
          </>
        )}
      </Main>
    </>
  )
}
