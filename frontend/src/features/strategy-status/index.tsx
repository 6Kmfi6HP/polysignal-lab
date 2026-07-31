import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useStrategyStatusQuery } from '@/lib/api/hooks'
import type { StrategyStatus } from '@/lib/api/types'
import { i18n } from '@/context/locale-provider'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  EmptyState,
  ErrorState,
  PageHeader,
  StatusBadge,
  TableFrame,
} from '@/components/dashboard'
import { Main } from '@/components/layout/main'

export function StrategyStatusPage() {
  const { t } = useTranslation()
  const query = useStrategyStatusQuery()
  const [filter, setFilter] = useState<StrategyStatus | 'all'>('all')
  const rows = useMemo(
    () =>
      query.data?.filter((row) => filter === 'all' || row.status === filter) ??
      [],
    [query.data, filter]
  )
  const statuses = useMemo(
    () => Array.from(new Set(query.data?.map((row) => row.status) ?? [])),
    [query.data]
  )
  return (
    <>
      <Main>
        <PageHeader
          title={t('navigation.strategyStatus')}
          description={t('pages.strategyStatus.description')}
          meta={
            query.data ? (
              <span className='font-mono text-sm text-muted-foreground'>
                {t('pages.strategyStatus.strategies', {
                  count: query.data.length,
                })}
              </span>
            ) : undefined
          }
        />
        {query.isPending && <Skeleton className='h-64 w-full rounded-xl' />}
        {query.isError && (
          <ErrorState
            message={t('ui.loadFailed', {
              resource: t('ui.strategyStatus'),
              message: query.error.message,
            })}
          />
        )}
        {query.data && query.data.length === 0 && (
          <EmptyState
            title={t('pages.strategyStatus.noRows')}
            description={t('ui.rowsDescription')}
          />
        )}
        {query.data && query.data.length > 0 && (
          <>
            <div
              className='mb-4 flex flex-wrap gap-2'
              aria-label={t('pages.strategyStatus.filter')}
            >
              <Button
                size='sm'
                variant={filter === 'all' ? 'default' : 'outline'}
                onClick={() => setFilter('all')}
              >
                {t('common.all')} ({query.data.length})
              </Button>
              {statuses.map((status) => (
                <Button
                  key={status}
                  size='sm'
                  variant={filter === status ? 'default' : 'outline'}
                  onClick={() => setFilter(status)}
                >
                  {i18n.resolvedLanguage === 'zh-CN'
                    ? t(`status.${status}`, {
                        defaultValue: status.replace(/_/g, ' '),
                      })
                    : status.replace(/_/g, ' ')}{' '}
                  ({query.data.filter((row) => row.status === status).length})
                </Button>
              ))}
            </div>
            {rows.length === 0 ? (
              <EmptyState
                title={t('pages.strategyStatus.noMatch')}
                description={t('ui.chooseFilter')}
              />
            ) : (
              <TableFrame>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t('fields.strategy')}</TableHead>
                      <TableHead>{t('fields.asset')}</TableHead>
                      <TableHead className='hidden md:table-cell'>
                        {t('fields.timeframe')}
                      </TableHead>
                      <TableHead>{t('fields.status')}</TableHead>
                      <TableHead className='whitespace-normal'>
                        {t('fields.reason')}
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {rows.map((row) => (
                      <TableRow
                        key={`${row.strategy}-${row.asset}-${row.timeframe}`}
                      >
                        <TableCell className='font-mono text-xs'>
                          {row.strategy}
                        </TableCell>
                        <TableCell>{row.asset}</TableCell>
                        <TableCell className='hidden md:table-cell'>
                          {row.timeframe}
                        </TableCell>
                        <TableCell>
                          <StatusBadge status={row.status} />
                        </TableCell>
                        <TableCell className='max-w-md whitespace-normal text-muted-foreground'>
                          {row.reason ?? '-'}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableFrame>
            )}
          </>
        )}
      </Main>
    </>
  )
}
