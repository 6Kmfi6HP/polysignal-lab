import { useMemo } from 'react'
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
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'

export function ReportingPage() {
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
      <Header fixed>
        <div className='ml-auto flex items-center gap-2'>
          <Search />
          <ThemeSwitch />
        </div>
      </Header>
      <Main>
        <PageHeader
          title='Trading Reports'
          description='Paper execution, positions, and realized performance from stored projections.'
        />
        <MetricStrip>
          <Metric
            label='Total PnL'
            value={formatMoney(summary.pnl)}
            tone={summary.pnl >= 0 ? 'positive' : 'danger'}
          />
          <Metric
            label='Average ROI'
            value={formatPercent(summary.roi, true)}
            tone={summary.roi >= 0 ? 'positive' : 'danger'}
          />
          <Metric label='Closed trades' value={trades.data?.length ?? '...'} />
          <Metric
            label='Open positions'
            value={positions.data ? summary.open : '...'}
          />
          <Metric
            label='Rejected orders'
            value={orders.data ? summary.rejected : '...'}
            tone={summary.rejected > 0 ? 'warning' : 'neutral'}
          />
        </MetricStrip>
        <section className='my-7' aria-labelledby='pnl-heading'>
          <h2 id='pnl-heading' className='mb-3 text-base font-semibold'>
            Cumulative PnL
          </h2>
          <TableFrame>
            <div className='p-4'>
              {trades.isPending && <Skeleton className='h-64 w-full' />}
              {trades.isError && (
                <ErrorState
                  message={`Failed to load trades: ${trades.error.message}`}
                />
              )}
              {trades.data && <CumulativePnlChart trades={trades.data} />}
            </div>
          </TableFrame>
        </section>
        <Tabs defaultValue='trades'>
          <TabsList>
            <TabsTrigger value='trades'>Trades</TabsTrigger>
            <TabsTrigger value='positions'>Positions</TabsTrigger>
            <TabsTrigger value='orders'>Orders</TabsTrigger>
          </TabsList>
          <TabsContent value='trades' className='mt-4'>
            {trades.isPending && <Skeleton className='h-64 w-full' />}
            {trades.isError && (
              <ErrorState
                message={`Failed to load trades: ${trades.error.message}`}
              />
            )}
            {trades.data && <TradesTable trades={trades.data} />}
          </TabsContent>
          <TabsContent value='positions' className='mt-4'>
            {positions.isPending && <Skeleton className='h-64 w-full' />}
            {positions.isError && (
              <ErrorState
                message={`Failed to load positions: ${positions.error.message}`}
              />
            )}
            {positions.data && <PositionsTable positions={positions.data} />}
          </TabsContent>
          <TabsContent value='orders' className='mt-4'>
            {orders.isPending && <Skeleton className='h-64 w-full' />}
            {orders.isError && (
              <ErrorState
                message={`Failed to load orders: ${orders.error.message}`}
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
  cumulative_pnl: number
}
function CumulativePnlChart({ trades }: { trades: ReportTradeResult[] }) {
  const points = useMemo(() => buildCumulativePnlPoints(trades), [trades])
  if (!points.length)
    return (
      <EmptyState
        title='No closed trades yet.'
        description='The equity curve appears after a position is settled.'
      />
    )
  const last = points[points.length - 1]?.cumulative_pnl ?? 0
  return (
    <div role='img' aria-label='Cumulative PnL chart' className='h-64 w-full'>
      <ResponsiveContainer width='100%' height='100%'>
        <LineChart
          data={points}
          margin={{ top: 8, right: 12, left: 4, bottom: 4 }}
        >
          <CartesianGrid vertical={false} stroke='var(--border)' />
          <XAxis
            dataKey='closed_at'
            tickFormatter={(value) =>
              new Date(value).toLocaleDateString('en', {
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
            labelFormatter={(value) => formatDateTime(String(value))}
            formatter={(value) => [
              formatMoney(Number(value)),
              'Cumulative PnL',
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
      cumulative_pnl: (cumulative += trade.pnl_usdc),
    }))
}

function TradesTable({ trades }: { trades: ReportTradeResult[] }) {
  if (!trades.length)
    return (
      <EmptyState
        title='No closed trades yet.'
        description='Settled positions appear here with realized PnL.'
      />
    )
  return (
    <TableFrame>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Closed</TableHead>
            <TableHead>Market</TableHead>
            <TableHead>Side</TableHead>
            <TableHead>Result</TableHead>
            <TableHead>Entry</TableHead>
            <TableHead>Stake</TableHead>
            <TableHead>PnL</TableHead>
            <TableHead>ROI</TableHead>
            <TableHead>
              <span className='sr-only'>Details</span>
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
              <TableCell className='font-mono'>
                {formatPrice(trade.entry_price)}
              </TableCell>
              <TableCell className='font-mono'>
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
  if (!positions.length)
    return (
      <EmptyState
        title='No stored positions yet.'
        description='Positions appear after an order receives a fill.'
      />
    )
  return (
    <TableFrame>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Opened</TableHead>
            <TableHead>Market</TableHead>
            <TableHead>Side</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Entry</TableHead>
            <TableHead>Stake</TableHead>
            <TableHead>Shares</TableHead>
            <TableHead>
              <span className='sr-only'>Details</span>
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
              <TableCell className='font-mono'>
                {formatPrice(position.entry_price)}
              </TableCell>
              <TableCell className='font-mono'>
                {formatMoney(position.stake_usdc)}
              </TableCell>
              <TableCell className='font-mono'>
                {position.shares.toFixed(2)}
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
  if (!orders.length)
    return (
      <EmptyState
        title='No stored orders yet.'
        description='Projected paper orders appear after signal acceptance.'
      />
    )
  return (
    <TableFrame>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Created</TableHead>
            <TableHead>Market</TableHead>
            <TableHead>Side</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Limit</TableHead>
            <TableHead>Stake</TableHead>
            <TableHead className='whitespace-normal'>Reject reason</TableHead>
            <TableHead>
              <span className='sr-only'>Details</span>
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
