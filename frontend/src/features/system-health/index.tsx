import { useHealthQuery } from '@/lib/api/hooks'
import { formatDateTime, humanize } from '@/lib/format'
import { Skeleton } from '@/components/ui/skeleton'
import {
  DetailList,
  DetailSheet,
  EmptyState,
  ErrorState,
  PageHeader,
  StatusBadge,
  TableFrame,
} from '@/components/dashboard'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'

export function SystemHealthPage() {
  const health = useHealthQuery()
  return (
    <>
      <Header fixed>
        <div className='ml-auto flex items-center gap-2'>
          <Search />
          <ThemeSwitch />
        </div>
      </Header>
      <Main>
        <PageHeader
          title='System Health'
          description='Component freshness, recent failures, and structured system events.'
          meta={
            health.data ? (
              <StatusBadge status={health.data.status} />
            ) : undefined
          }
        />
        {health.isPending && <Skeleton className='h-64 w-full rounded-xl' />}
        {health.isError && (
          <ErrorState
            message={`Failed to load health: ${health.error.message}`}
          />
        )}
        {health.data && (
          <div className='space-y-7'>
            <section>
              <div className='mb-3 flex items-baseline justify-between gap-3'>
                <h2 className='text-base font-semibold'>Components</h2>
                <span className='text-xs text-muted-foreground'>
                  Generated {formatDateTime(health.data.generated_at)}
                </span>
              </div>
              {health.data.components.length === 0 ? (
                <EmptyState
                  title='No component health rows recorded yet.'
                  description='Component checks appear after health probes have run.'
                />
              ) : (
                <div className='grid gap-3 lg:grid-cols-2'>
                  {health.data.components.map((component) => (
                    <article
                      key={component.name}
                      className='rounded-xl border bg-card p-4'
                    >
                      <div className='flex items-start justify-between gap-3'>
                        <h3 className='font-medium'>{component.name}</h3>
                        <StatusBadge status={component.status} />
                      </div>
                      <dl className='mt-4 grid gap-3 text-sm sm:grid-cols-2'>
                        <div>
                          <dt className='text-xs text-muted-foreground'>
                            Last success
                          </dt>
                          <dd className='mt-1 font-mono text-xs'>
                            {formatDateTime(component.last_success_at)}
                          </dd>
                        </div>
                        <div>
                          <dt className='text-xs text-muted-foreground'>
                            Last error
                          </dt>
                          <dd className='mt-1 font-mono text-xs'>
                            {formatDateTime(component.last_error_at)}
                          </dd>
                        </div>
                      </dl>
                      <p className='mt-3 text-sm text-muted-foreground'>
                        {component.last_error ?? 'No recent errors.'}
                      </p>
                      {Object.keys(component.metrics).length > 0 && (
                        <div className='mt-3'>
                          <DetailSheet
                            title={`${component.name} metrics`}
                            description='Current component measurements'
                          >
                            <DetailList values={component.metrics} />
                          </DetailSheet>
                        </div>
                      )}
                    </article>
                  ))}
                </div>
              )}
            </section>
            <section>
              <h2 className='mb-3 text-base font-semibold'>
                Recent system events
              </h2>
              {health.data.recent_system_events.length === 0 ? (
                <EmptyState
                  title='No system events recorded yet.'
                  description='Operational events will appear here in reverse chronological order.'
                />
              ) : (
                <TableFrame>
                  <div>
                    {health.data.recent_system_events.map((event, index) => {
                      const meta = eventMeta(event)
                      return (
                        <article
                          key={String(event.id ?? `${meta.time}-${index}`)}
                          className='grid gap-2 border-b p-4 last:border-0 sm:grid-cols-[10rem_1fr_auto] sm:items-center'
                        >
                          <time className='font-mono text-xs text-muted-foreground'>
                            {formatDateTime(meta.time)}
                          </time>
                          <div className='min-w-0'>
                            <p className='truncate font-medium'>
                              {humanize(meta.type)}
                            </p>
                            <p className='truncate text-xs text-muted-foreground'>
                              {meta.identifier}
                            </p>
                          </div>
                          <div className='flex items-center gap-2'>
                            <StatusBadge status={meta.severity} />
                            <DetailSheet
                              title={humanize(meta.type)}
                              description={meta.identifier}
                            >
                              <DetailList values={event} />
                            </DetailSheet>
                          </div>
                        </article>
                      )
                    })}
                  </div>
                </TableFrame>
              )}
            </section>
          </div>
        )}
      </Main>
    </>
  )
}

function eventMeta(event: Record<string, unknown>) {
  const get = (...keys: string[]) =>
    keys.map((key) => event[key]).find((value) => typeof value === 'string') as
      string | undefined
  return {
    time: get('created_at', 'timestamp', 'time', 'occurred_at'),
    type: get('event_type', 'type', 'name') ?? 'unknown event',
    severity: get('severity', 'level', 'status') ?? 'unknown',
    identifier:
      get(
        'message',
        'reason',
        'component',
        'strategy',
        'signal_id',
        'order_id'
      ) ?? 'No primary identifier',
  }
}
