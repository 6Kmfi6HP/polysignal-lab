import { useTranslation } from 'react-i18next'
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
  const { t } = useTranslation()
  const query = useLeaderboardQuery()
  return (
    <>
      <Main>
        <PageHeader
          title={t('navigation.leaderboard')}
          description={t('pages.leaderboard.description')}
        />
        {query.isPending && <Skeleton className='h-64 w-full rounded-xl' />}
        {query.isError && (
          <ErrorState
            message={t('ui.loadFailed', {
              resource: t('ui.leaderboard'),
              message: query.error.message,
            })}
          />
        )}
        {query.data && (
          <div className='space-y-7'>
            <section aria-labelledby='comparison-heading'>
              <h2
                id='comparison-heading'
                className='mb-3 text-base font-semibold'
              >
                {t('pages.leaderboard.pnlByStrategy')}
              </h2>
              <TableFrame>
                <div className='p-4'>
                  <PnlByStrategyChart rows={query.data.leaderboard} />
                </div>
              </TableFrame>
            </section>
            <section>
              <h2 className='mb-3 text-base font-semibold'>
                {t('pages.leaderboard.rankings')}
              </h2>
              <LeaderboardTable rows={query.data.leaderboard} />
            </section>
            <section>
              <h2 className='mb-3 text-base font-semibold'>
                {t('pages.leaderboard.calibration')}
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
  const { t } = useTranslation()
  if (!rows.length)
    return (
      <EmptyState
        title={t('ui.noReports')}
        description={t('ui.comparisonDescription')}
      />
    )
  return (
    <div
      role='img'
      aria-label={t('pages.leaderboard.pnlByStrategy')}
      className='h-64'
    >
      <ResponsiveContainer width='100%' height='100%'>
        <BarChart
          data={rows}
          margin={{ top: 8, right: 12, left: 8, bottom: 12 }}
        >
          <CartesianGrid vertical={false} stroke='var(--border)' />
          <XAxis dataKey='strategy' tick={{ fontSize: 11 }} interval={0} />
          <YAxis tick={{ fontSize: 11 }} />
          <Tooltip
            formatter={(value) => [
              formatMoney(Number(value)),
              t('pages.reporting.totalPnl'),
            ]}
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
  const { t } = useTranslation()
  if (!rows.length)
    return (
      <EmptyState
        title={t('ui.noReports')}
        description={t('ui.rankingsDescription')}
      />
    )
  const sorted = [...rows].sort((a, b) => b.total_pnl_usdc - a.total_pnl_usdc)
  return (
    <TableFrame>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t('fields.rank')}</TableHead>
            <TableHead>{t('fields.strategy')}</TableHead>
            <TableHead>{t('fields.sample')}</TableHead>
            <TableHead className='hidden lg:table-cell'>
              {t('fields.record')}
            </TableHead>
            <TableHead>{t('pages.overview.winRate')}</TableHead>
            <TableHead className='hidden lg:table-cell'>
              {t('pages.reporting.averageRoi')}
            </TableHead>
            <TableHead>{t('pages.reporting.totalPnl')}</TableHead>
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
  const { t } = useTranslation()
  if (!buckets.length)
    return (
      <EmptyState
        title={t('ui.noCalibration')}
        description={t('ui.calibrationDescription')}
      />
    )
  return (
    <TableFrame>
      <Table>
        <TableHeader>
          <TableRow>
            {[
              'strategy',
              'asset',
              'timeframe',
              'bucket',
              'sample',
              'record',
              'status',
            ].map((key) => (
              <TableHead key={key}>{t(`fields.${key}`)}</TableHead>
            ))}
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
