import { useTranslation } from 'react-i18next'
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
import { Main } from '@/components/layout/main'

export function SystemHealthPage() {
  const { t } = useTranslation()
  const health = useHealthQuery()
  return (
    <>
      <Main>
        <PageHeader
          title={t('navigation.systemHealth')}
          description={t('pages.systemHealth.description')}
          meta={
            health.data ? (
              <StatusBadge status={health.data.status} />
            ) : undefined
          }
        />
        {health.isPending && <Skeleton className='h-64 w-full rounded-xl' />}
        {health.isError && (
          <ErrorState
            message={t('ui.loadFailed', {
              resource: t('ui.health'),
              message: health.error.message,
            })}
          />
        )}
        {health.data && (
          <div className='space-y-7'>
            <section>
              <div className='mb-3 flex items-baseline justify-between gap-3'>
                <h2 className='text-base font-semibold'>
                  {t('pages.systemHealth.components')}
                </h2>
                <span className='text-xs text-muted-foreground'>
                  {t('common.generated')}{' '}
                  {formatDateTime(health.data.generated_at)}
                </span>
              </div>
              {health.data.components.length === 0 ? (
                <EmptyState
                  title={t('ui.noComponents')}
                  description={t('ui.componentsDescription')}
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
                            {t('pages.systemHealth.lastSuccess')}
                          </dt>
                          <dd className='mt-1 font-mono text-xs'>
                            {formatDateTime(component.last_success_at)}
                          </dd>
                        </div>
                        <div>
                          <dt className='text-xs text-muted-foreground'>
                            {t('pages.systemHealth.lastError')}
                          </dt>
                          <dd className='mt-1 font-mono text-xs'>
                            {formatDateTime(component.last_error_at)}
                          </dd>
                        </div>
                      </dl>
                      <p className='mt-3 text-sm text-muted-foreground'>
                        {component.last_error ??
                          t('pages.systemHealth.noErrors')}
                      </p>
                      {Object.keys(component.metrics).length > 0 && (
                        <div className='mt-3'>
                          <DetailSheet
                            title={`${component.name} metrics`}
                            description={t('ui.measurements')}
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
                {t('pages.systemHealth.recentEvents')}
              </h2>
              {health.data.recent_system_events.length === 0 ? (
                <EmptyState
                  title={t('ui.noEvents')}
                  description={t('ui.eventsDescription')}
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
