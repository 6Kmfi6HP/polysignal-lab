/**
 * Input: { Bar, BarChart, CartesianGrid, ResponsiveContainer, XAxis, YAxis } from 'recharts', { Header } from '@/components/layout/header', { Main } from '@/components/layout/main', { Search } from '@/components/search', { ThemeSwitch } from '@/components/theme-switch', { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card', { Skeleton } from '@/components/ui/skeleton', {, { useLeaderboardQuery } from '@/lib/api/hooks', type { LeaderboardRow } from '@/lib/api/types'
 * Output: LeaderboardPage, PnlByStrategyChart, LeaderboardTable
 * Pos: Application code
 *
 * 🔄 Self-reference: When this file changes, update this header
 */





import { Bar, BarChart, CartesianGrid, ResponsiveContainer, XAxis, YAxis } from 'recharts'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useLeaderboardQuery } from '@/lib/api/hooks'
import type { LeaderboardRow } from '@/lib/api/types'

export function LeaderboardPage() {
  const leaderboard = useLeaderboardQuery()

  return (
    <>
      <Header>
        <div className='ml-auto flex items-center gap-2'>
          <Search />
          <ThemeSwitch />
        </div>
      </Header>
      <Main>
        <h1 className='mb-4 text-2xl font-bold tracking-tight'>Leaderboard</h1>

        {leaderboard.isPending && <Skeleton className='h-64 w-full' />}
        {leaderboard.isError && (
          <p className='text-destructive'>
            Failed to load leaderboard: {leaderboard.error.message}
          </p>
        )}

        {leaderboard.data && (
          <>
            <Card className='mb-6'>
              <CardHeader>
                <CardTitle>Total PnL by strategy</CardTitle>
              </CardHeader>
              <CardContent>
                <PnlByStrategyChart rows={leaderboard.data.leaderboard} />
              </CardContent>
            </Card>
            <LeaderboardTable rows={leaderboard.data.leaderboard} />
          </>
        )}
      </Main>
    </>
  )
}

function PnlByStrategyChart({ rows }: { rows: LeaderboardRow[] }) {
  if (rows.length === 0) {
    return <p className='text-muted-foreground'>No stored report rows yet.</p>
  }

  return (
    <ResponsiveContainer width='100%' height={240}>
      <BarChart data={rows}>
        <CartesianGrid strokeDasharray='3 3' />
        <XAxis dataKey='strategy' />
        <YAxis />
        <Bar dataKey='total_pnl_usdc' fill='currentColor' />
      </BarChart>
    </ResponsiveContainer>
  )
}

function LeaderboardTable({ rows }: { rows: LeaderboardRow[] }) {
  if (rows.length === 0) {
    return <p className='text-muted-foreground'>No stored report rows yet.</p>
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Strategy</TableHead>
          <TableHead>Closed</TableHead>
          <TableHead>Win rate</TableHead>
          <TableHead>Total PnL</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.strategy}>
            <TableCell className='font-mono text-xs'>{row.strategy}</TableCell>
            <TableCell>{row.closed_positions}</TableCell>
            <TableCell>{(row.win_rate * 100).toFixed(1)}%</TableCell>
            <TableCell>{row.total_pnl_usdc.toFixed(2)} USDC</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
