import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  usePositionsQuery,
  useReportOrdersQuery,
  useTradesQuery,
} from '@/lib/api/hooks'
import type {
  ReportOrder,
  ReportPosition,
  ReportTradeResult,
} from '@/lib/api/types'
import {
  formatDateTime,
  formatMoney,
  formatNumber,
  formatPercent,
  formatPrice,
} from '@/lib/format'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  DetailList,
  DetailSheet,
  EmptyState,
  ErrorState,
  Metric,
  MetricStrip,
  PageHeader,
  StatusBadge,
  TableFrame,
} from '@/components/dashboard'
import { Main } from '@/components/layout/main'

export function ReportingPage() {
  const { t } = useTranslation()
  const orders = useReportOrdersQuery()
  const positions = usePositionsQuery()
  const trades = useTradesQuery()
  const summary = useMemo(
    () => ({
      pnl: trades.data?.reduce((sum, trade) => sum + trade.pnl_usdc, 0) ?? 0,
      roi: trades.data?.length
        ? trades.data.reduce((sum, trade) => sum + trade.roi, 0) /
          trades.data.length
        : 0,
      open:
        positions.data?.filter((position) => position.status === 'OPEN')
          .length ?? 0,
      rejected:
        orders.data?.filter((order) => order.status === 'REJECTED').length ?? 0,
    }),
    [orders.data, positions.data, trades.data]
  )
  return (
    <>
      <Main>
        <PageHeader
          title={t('navigation.reporting')}
          description={t('pages.reporting.description')}
        />
        <MetricStrip>
          <Metric
            label={t('pages.reporting.totalPnl')}
            value={formatMoney(summary.pnl)}
            tone={summary.pnl >= 0 ? 'positive' : 'danger'}
          />
          <Metric
            label={t('pages.reporting.averageRoi')}
            value={formatPercent(summary.roi, true)}
            tone={summary.roi >= 0 ? 'positive' : 'danger'}
          />
          <Metric
            label={t('pages.reporting.closedTrades')}
            value={trades.data?.length ?? '...'}
          />
          <Metric
            label={t('pages.reporting.openPositions')}
            value={positions.data ? summary.open : '...'}
          />
          <Metric
            label={t('pages.reporting.rejectedOrders')}
            value={orders.data ? summary.rejected : '...'}
            tone={summary.rejected > 0 ? 'warning' : 'neutral'}
          />
        </MetricStrip>
        <section className='my-7' aria-labelledby='pnl-heading'>
          <h2 id='pnl-heading' className='mb-3 text-base font-semibold'>
            {t('pages.reporting.cumulativePnl')}
          </h2>
          <TableFrame>
            <div className='p-4'>
              {trades.isPending && <Skeleton className='h-64 w-full' />}
              {trades.isError && (
                <ErrorState
                  message={t('ui.loadFailed', {
                    resource: t('ui.trades'),
                    message: trades.error.message,
                  })}
                />
              )}
              {trades.data && <CumulativePnlChart trades={trades.data} />}
            </div>
          </TableFrame>
        </section>
        <Tabs defaultValue='trades'>
          <TabsList>
            <TabsTrigger value='trades'>
              {t('pages.reporting.trades')}
            </TabsTrigger>
            <TabsTrigger value='positions'>
              {t('pages.reporting.positions')}
            </TabsTrigger>
            <TabsTrigger value='orders'>
              {t('pages.reporting.orders')}
            </TabsTrigger>
          </TabsList>
          <TabsContent value='trades' className='mt-4'>
            {trades.isPending && <Skeleton className='h-64 w-full' />}
            {trades.isError && (
              <ErrorState
                message={t('ui.loadFailed', {
                  resource: t('ui.trades'),
                  message: trades.error.message,
                })}
              />
            )}
            {trades.data && <TradesTable trades={trades.data} />}
          </TabsContent>
          <TabsContent value='positions' className='mt-4'>
            {positions.isPending && <Skeleton className='h-64 w-full' />}
            {positions.isError && (
              <ErrorState
                message={t('ui.loadFailed', {
                  resource: t('ui.positions'),
                  message: positions.error.message,
                })}
              />
            )}
            {positions.data && <PositionsTable positions={positions.data} />}
          </TabsContent>
          <TabsContent value='orders' className='mt-4'>
            {orders.isPending && <Skeleton className='h-64 w-full' />}
            {orders.isError && (
              <ErrorState
                message={t('ui.loadFailed', {
                  resource: t('ui.orders'),
                  message: orders.error.message,
                })}
              />
            )}
            {orders.data && <OrdersTable orders={orders.data} />}
          </TabsContent>
        </Tabs>
      </Main>
    </>
  )
}

interface CumulativePnlPoint {
  closed_at: string
  closed_at_ms: number
  cumulative_pnl: number
}
function CumulativePnlChart({ trades }: { trades: ReportTradeResult[] }) {
  const { t } = useTranslation()
  const points = useMemo(() => buildCumulativePnlPoints(trades), [trades])
  if (!points.length)
    return (
      <EmptyState title={t('ui.noClosed')} description={t('ui.equityCurve')} />
    )
  const last = points[points.length - 1]?.cumulative_pnl ?? 0
  return (
    <div
      role='img'
      aria-label={`${t('pages.reporting.cumulativePnl')} ${t('common.chart')}`}
      className='h-64 w-full'
    >
      <ResponsiveContainer width='100%' height='100%'>
        <LineChart
          data={points}
          margin={{ top: 8, right: 12, left: 4, bottom: 4 }}
        >
          <CartesianGrid vertical={false} stroke='var(--border)' />
          <XAxis
            dataKey='closed_at_ms'
            type='number'
            scale='time'
            domain={['dataMin', 'dataMax']}
            tickFormatter={(value) =>
              new Date(Number(value)).toLocaleDateString(undefined, {
                month: 'short',
                day: 'numeric',
              })
            }
            tick={{ fontSize: 11 }}
            minTickGap={24}
          />
          <YAxis
            tick={{ fontSize: 11 }}
            tickFormatter={(value) => `${value}`}
            width={48}
          />
          <Tooltip
            labelFormatter={(value) =>
              formatDateTime(new Date(Number(value)).toISOString())
            }
            formatter={(value) => [
              formatMoney(Number(value)),
              t('pages.reporting.cumulativePnl'),
            ]}
            contentStyle={{
              borderRadius: 12,
              borderColor: 'var(--border)',
              background: 'var(--popover)',
            }}
          />
          <ReferenceLine y={0} stroke='var(--muted-foreground)' />
          <Line
            type='monotone'
            dataKey='cumulative_pnl'
            stroke={last >= 0 ? 'var(--positive)' : 'var(--destructive)'}
            strokeWidth={2}
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
function buildCumulativePnlPoints(
  trades: ReportTradeResult[]
): CumulativePnlPoint[] {
  let cumulative = 0
  return [...trades]
    .sort(
      (a, b) =>
        new Date(a.closed_at).getTime() - new Date(b.closed_at).getTime()
    )
    .map((trade) => ({
      closed_at: trade.closed_at,
      closed_at_ms: new Date(trade.closed_at).getTime(),
      cumulative_pnl: (cumulative += trade.pnl_usdc),
    }))
}

function TradesTable({ trades }: { trades: ReportTradeResult[] }) {
  const { t } = useTranslation()
  if (!trades.length)
    return (
      <EmptyState
        title={t('ui.noClosed')}
        description={t('ui.settledPositions')}
      />
    )
  return (
    <TableFrame>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t('ui.closed')}</TableHead>
            <TableHead>{t('fields.market')}</TableHead>
            <TableHead>{t('fields.side')}</TableHead>
            <TableHead>{t('fields.result')}</TableHead>
            <TableHead className='hidden lg:table-cell'>
              {t('fields.entry')}
            </TableHead>
            <TableHead className='hidden lg:table-cell'>
              {t('fields.stake')}
            </TableHead>
            <TableHead>{t('fields.pnl')}</TableHead>
            <TableHead>{t('fields.roi')}</TableHead>
            <TableHead>
              <span className='sr-only'>{t('common.details')}</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {trades.map((trade) => (
            <TableRow key={trade.report_result_id}>
              <TableCell className='font-mono text-xs'>
                {formatDateTime(trade.closed_at)}
              </TableCell>
              <MarketCell
                asset={trade.asset}
                timeframe={trade.timeframe}
                slug={trade.market_slug}
              />
              <TableCell>
                <StatusBadge status={trade.side} />
              </TableCell>
              <TableCell>
                <StatusBadge status={trade.result} />
              </TableCell>
              <TableCell className='hidden font-mono lg:table-cell'>
                {formatPrice(trade.entry_price)}
              </TableCell>
              <TableCell className='hidden font-mono lg:table-cell'>
                {formatMoney(trade.stake_usdc)}
              </TableCell>
              <TableCell
                className={
                  trade.pnl_usdc >= 0
                    ? 'font-mono text-positive'
                    : 'font-mono text-destructive'
                }
              >
                {formatMoney(trade.pnl_usdc)}
              </TableCell>
              <TableCell className='font-mono'>
                {formatPercent(trade.roi, true)}
              </TableCell>
              <TableCell>
                <DetailSheet
                  title={`${trade.asset} trade`}
                  description={trade.report_result_id}
                >
                  <DetailList values={trade} />
                </DetailSheet>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableFrame>
  )
}
function PositionsTable({ positions }: { positions: ReportPosition[] }) {
  const { t } = useTranslation()
  if (!positions.length)
    return (
      <EmptyState
        title={t('ui.noPositions')}
        description={t('ui.positionsDescription')}
      />
    )
  return (
    <TableFrame>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t('fields.opened')}</TableHead>
            <TableHead>{t('fields.market')}</TableHead>
            <TableHead>{t('fields.side')}</TableHead>
            <TableHead>{t('fields.status')}</TableHead>
            <TableHead className='hidden lg:table-cell'>
              {t('fields.entry')}
            </TableHead>
            <TableHead className='hidden lg:table-cell'>
              {t('fields.stake')}
            </TableHead>
            <TableHead className='hidden xl:table-cell'>
              {t('fields.shares')}
            </TableHead>
            <TableHead>
              <span className='sr-only'>{t('common.details')}</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {positions.map((position) => (
            <TableRow key={position.report_position_id}>
              <TableCell className='font-mono text-xs'>
                {formatDateTime(position.opened_at)}
              </TableCell>
              <MarketCell
                asset={position.asset}
                timeframe={position.timeframe}
                slug={position.market_slug}
              />
              <TableCell>
                <StatusBadge status={position.side} />
              </TableCell>
              <TableCell>
                <StatusBadge status={position.status} />
              </TableCell>
              <TableCell className='hidden font-mono lg:table-cell'>
                {formatPrice(position.entry_price)}
              </TableCell>
              <TableCell className='hidden font-mono lg:table-cell'>
                {formatMoney(position.stake_usdc)}
              </TableCell>
              <TableCell className='hidden font-mono xl:table-cell'>
                {formatNumber(position.shares)}
              </TableCell>
              <TableCell>
                <DetailSheet
                  title={`${position.asset} position`}
                  description={position.report_position_id}
                >
                  <DetailList values={position} />
                </DetailSheet>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableFrame>
  )
}
function OrdersTable({ orders }: { orders: ReportOrder[] }) {
  const { t } = useTranslation()
  if (!orders.length)
    return (
      <EmptyState
        title={t('ui.noOrders')}
        description={t('ui.ordersDescription')}
      />
    )
  return (
    <TableFrame>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t('fields.created')}</TableHead>
            <TableHead>{t('fields.market')}</TableHead>
            <TableHead>{t('fields.side')}</TableHead>
            <TableHead>{t('fields.status')}</TableHead>
            <TableHead>{t('fields.limit')}</TableHead>
            <TableHead>{t('fields.stake')}</TableHead>
            <TableHead className='whitespace-normal'>
              {t('fields.rejectReason')}
            </TableHead>
            <TableHead>
              <span className='sr-only'>{t('common.details')}</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {orders.map((order) => (
            <TableRow key={order.report_order_id}>
              <TableCell className='font-mono text-xs'>
                {formatDateTime(order.created_at)}
              </TableCell>
              <MarketCell
                asset={order.asset}
                timeframe={order.timeframe}
                slug={order.market_slug}
              />
              <TableCell>
                <StatusBadge status={order.side} />
              </TableCell>
              <TableCell>
                <StatusBadge status={order.status} />
              </TableCell>
              <TableCell className='font-mono'>
                {formatPrice(order.limit_price)}
              </TableCell>
              <TableCell className='font-mono'>
                {formatMoney(order.stake_usdc)}
              </TableCell>
              <TableCell className='max-w-xs whitespace-normal text-muted-foreground'>
                {order.reject_reason ?? '-'}
              </TableCell>
              <TableCell>
                <DetailSheet
                  title={`${order.asset} order`}
                  description={order.report_order_id}
                >
                  <DetailList values={order} />
                </DetailSheet>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableFrame>
  )
}
function MarketCell({
  asset,
  timeframe,
  slug,
}: {
  asset: string
  timeframe: string
  slug: string
}) {
  return (
    <TableCell>
      <div className='font-medium'>
        {asset} {timeframe}
      </div>
      <div className='max-w-40 truncate font-mono text-xs text-muted-foreground'>
        {slug}
      </div>
    </TableCell>
  )
}
