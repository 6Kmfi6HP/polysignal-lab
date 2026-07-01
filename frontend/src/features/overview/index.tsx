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
                  <dl className='grid gap-4 sm:grid-cols-2 lg:grid-cols-4'>
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
                        {overview.data.latest_report.total_pnl_usdc.toFixed(2)}{' '}
                        USDC
                      </dd>
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
