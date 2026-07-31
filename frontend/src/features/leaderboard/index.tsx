import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useLeaderboardQuery } from '@/lib/api/hooks'
import type { CalibrationBucket, LeaderboardRow } from '@/lib/api/types'
import { formatMoney, formatPercent } from '@/lib/format'
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

export function LeaderboardPage() {
  const query = useLeaderboardQuery()
  return (
    <>
      <Main>
        <PageHeader
          title='Leaderboard'
          description='Realized strategy performance and calibration sample coverage.'
        />
        {query.isPending && <Skeleton className='h-64 w-full rounded-xl' />}
        {query.isError && (
          <ErrorState
            message={`Failed to load leaderboard: ${query.error.message}`}
          />
        )}
        {query.data && (
          <div className='space-y-7'>
            <section aria-labelledby='comparison-heading'>
              <h2
                id='comparison-heading'
                className='mb-3 text-base font-semibold'
              >
                Total PnL by strategy
              </h2>
              <TableFrame>
                <div className='p-4'>
                  <PnlByStrategyChart rows={query.data.leaderboard} />
                </div>
              </TableFrame>
            </section>
            <section>
              <h2 className='mb-3 text-base font-semibold'>Rankings</h2>
              <LeaderboardTable rows={query.data.leaderboard} />
            </section>
            <section>
              <h2 className='mb-3 text-base font-semibold'>
                Calibration breakdown
              </h2>
              <CalibrationTable
                buckets={Object.values(query.data.calibration_breakdown)}
              />
            </section>
          </div>
        )}
      </Main>
    </>
  )
}
function PnlByStrategyChart({ rows }: { rows: LeaderboardRow[] }) {
  if (!rows.length)
    return (
      <EmptyState
        title='No stored report rows yet.'
        description='Strategy comparisons appear after closed positions are reported.'
      />
    )
  return (
    <div role='img' aria-label='Total PnL by strategy chart' className='h-64'>
      <ResponsiveContainer width='100%' height='100%'>
        <BarChart
          data={rows}
          margin={{ top: 8, right: 12, left: 8, bottom: 12 }}
        >
          <CartesianGrid vertical={false} stroke='var(--border)' />
          <XAxis dataKey='strategy' tick={{ fontSize: 11 }} interval={0} />
          <YAxis tick={{ fontSize: 11 }} />
          <Tooltip
            formatter={(value) => [formatMoney(Number(value)), 'Total PnL']}
            contentStyle={{
              borderRadius: 12,
              borderColor: 'var(--border)',
              background: 'var(--popover)',
            }}
          />
          <ReferenceLine y={0} stroke='var(--muted-foreground)' />
          <Bar dataKey='total_pnl_usdc' radius={[4, 4, 0, 0]}>
            {rows.map((row) => (
              <Cell
                key={row.strategy}
                fill={
                  row.total_pnl_usdc >= 0
                    ? 'var(--positive)'
                    : 'var(--destructive)'
                }
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
function LeaderboardTable({ rows }: { rows: LeaderboardRow[] }) {
  if (!rows.length)
    return (
      <EmptyState
        title='No stored report rows yet.'
        description='Strategy rankings appear after closed positions are reported.'
      />
    )
  const sorted = [...rows].sort((a, b) => b.total_pnl_usdc - a.total_pnl_usdc)
  return (
    <TableFrame>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Rank</TableHead>
            <TableHead>Strategy</TableHead>
            <TableHead>Sample</TableHead>
            <TableHead className='hidden lg:table-cell'>Record</TableHead>
            <TableHead>Win rate</TableHead>
            <TableHead className='hidden lg:table-cell'>Average ROI</TableHead>
            <TableHead>Total PnL</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((row, index) => (
            <TableRow key={row.strategy}>
              <TableCell className='font-mono text-muted-foreground'>
                #{index + 1}
              </TableCell>
              <TableCell className='font-mono text-xs'>
                {row.strategy}
              </TableCell>
              <TableCell className='font-mono'>
                {row.closed_positions}
              </TableCell>
              <TableCell className='hidden font-mono text-xs lg:table-cell'>
                {row.win_count}W / {row.loss_count}L / {row.void_count}V
              </TableCell>
              <TableCell className='font-mono'>
                {formatPercent(row.win_rate)}
              </TableCell>
              <TableCell className='hidden font-mono lg:table-cell'>
                {formatPercent(row.average_roi, true)}
              </TableCell>
              <TableCell
                className={
                  row.total_pnl_usdc >= 0
                    ? 'font-mono text-positive'
                    : 'font-mono text-destructive'
                }
              >
                {formatMoney(row.total_pnl_usdc)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableFrame>
  )
}
function CalibrationTable({ buckets }: { buckets: CalibrationBucket[] }) {
  if (!buckets.length)
    return (
      <EmptyState
        title='No calibration data available.'
        description='Calibration status appears once confidence buckets have samples.'
      />
    )
  return (
    <TableFrame>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Strategy</TableHead>
            <TableHead>Asset</TableHead>
            <TableHead>Timeframe</TableHead>
            <TableHead>Bucket</TableHead>
            <TableHead>Sample</TableHead>
            <TableHead>Record</TableHead>
            <TableHead>Status</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {buckets.map((row, index) => (
            <TableRow
              key={`${row.strategy}-${row.asset}-${row.timeframe}-${row.confidence_bucket}-${index}`}
            >
              <TableCell className='font-mono text-xs'>
                {row.strategy}
              </TableCell>
              <TableCell>{row.asset}</TableCell>
              <TableCell>{row.timeframe}</TableCell>
              <TableCell className='font-mono'>
                {row.confidence_bucket}
              </TableCell>
              <TableCell className='font-mono'>{row.sample_size}</TableCell>
              <TableCell className='font-mono text-xs'>
                {row.wins}W / {row.losses}L
              </TableCell>
              <TableCell>
                <StatusBadge status={row.calibration_status} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableFrame>
  )
}
