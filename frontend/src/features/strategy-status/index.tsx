/**
 * Input: { useStrategyStatusQuery } from '@/lib/api/hooks', { Badge } from '@/components/ui/badge', { Skeleton } from '@/components/ui/skeleton', {, { Header } from '@/components/layout/header', { Main } from '@/components/layout/main', { Search } from '@/components/search', { ThemeSwitch } from '@/components/theme-switch', @/lib/api/hooks, @/components/ui/badge
 * Output: StrategyStatusPage
 * Pos: Application code
 *
 * 🔄 Self-reference: When this file changes, update this header
 */





import { useStrategyStatusQuery } from '@/lib/api/hooks'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'

export function StrategyStatusPage() {
  const status = useStrategyStatusQuery()

  return (
    <>
      <Header>
        <div className='ml-auto flex items-center gap-2'>
          <Search />
          <ThemeSwitch />
        </div>
      </Header>
      <Main>
        <h1 className='mb-4 text-2xl font-bold tracking-tight'>
          Strategy Status
        </h1>

        {status.isPending && <Skeleton className='h-64 w-full' />}
        {status.isError && (
          <p className='text-destructive'>
            Failed to load strategy status: {status.error.message}
          </p>
        )}
        {status.data && status.data.length === 0 && (
          <p className='text-muted-foreground'>
            No strategy readiness rows recorded yet.
          </p>
        )}
        {status.data && status.data.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Strategy</TableHead>
                <TableHead>Asset</TableHead>
                <TableHead>Timeframe</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Reason</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {status.data.map((row) => (
                <TableRow key={`${row.strategy}-${row.asset}-${row.timeframe}`}>
                  <TableCell>{row.strategy}</TableCell>
                  <TableCell>{row.asset}</TableCell>
                  <TableCell>{row.timeframe}</TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        row.status === 'active' ? 'default' : 'secondary'
                      }
                    >
                      {row.status}
                    </Badge>
                  </TableCell>
                  <TableCell>{row.reason ?? '-'}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Main>
    </>
  )
}
