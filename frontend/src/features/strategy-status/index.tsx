import { useMemo, useState } from 'react'
import { useStrategyStatusQuery } from '@/lib/api/hooks'
import type { StrategyStatus } from '@/lib/api/types'
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
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'

export function StrategyStatusPage() {
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
      <Header fixed>
        <div className='ml-auto flex items-center gap-2'>
          <Search />
          <ThemeSwitch />
        </div>
      </Header>
      <Main>
        <PageHeader
          title='Strategy Status'
          description='Readiness and data support across every configured strategy.'
          meta={
            query.data ? (
              <span className='font-mono text-sm text-muted-foreground'>
                {query.data.length} strategies
              </span>
            ) : undefined
          }
        />
        {query.isPending && <Skeleton className='h-64 w-full rounded-xl' />}
        {query.isError && (
          <ErrorState
            message={`Failed to load strategy status: ${query.error.message}`}
          />
        )}
        {query.data && query.data.length === 0 && (
          <EmptyState
            title='No strategy readiness rows recorded yet.'
            description='Rows appear when strategy readiness evaluation has run.'
          />
        )}
        {query.data && query.data.length > 0 && (
          <>
            <div
              className='mb-4 flex flex-wrap gap-2'
              aria-label='Filter by status'
            >
              <Button
                size='sm'
                variant={filter === 'all' ? 'default' : 'outline'}
                onClick={() => setFilter('all')}
              >
                All ({query.data.length})
              </Button>
              {statuses.map((status) => (
                <Button
                  key={status}
                  size='sm'
                  variant={filter === status ? 'default' : 'outline'}
                  onClick={() => setFilter(status)}
                >
                  {status.replace(/_/g, ' ')} (
                  {query.data.filter((row) => row.status === status).length})
                </Button>
              ))}
            </div>
            {rows.length === 0 ? (
              <EmptyState
                title='No matching strategies'
                description='Choose another status filter to see readiness rows.'
              />
            ) : (
              <TableFrame>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Strategy</TableHead>
                      <TableHead>Asset</TableHead>
                      <TableHead className='hidden md:table-cell'>
                        Timeframe
                      </TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead className='whitespace-normal'>
                        Reason
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
