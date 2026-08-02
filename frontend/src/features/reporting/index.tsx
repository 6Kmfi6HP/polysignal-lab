import { useEffect, useMemo } from 'react'
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
  useReportSummaryQuery,
  useTradesChartQuery,
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
import { type NavigateFn, useTableUrlState } from '@/hooks/use-table-url-state'
import { PaginationBar } from '@/components/ui/pagination'
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

export function ReportingPage({
  search,
  navigate,
}: {
  search: Record<string, unknown>
  navigate: NavigateFn
}) {
  const { t } = useTranslation()
  const tradesTable = useTableUrlState({
    search,
    navigate,
    pagination: {
      pageKey: 'tradesPage',
      pageSizeKey: 'tradesPageSize',
      defaultPage: 1,
      defaultPageSize: 25,
    },
    globalFilter: { enabled: false },
  })
  const positionsTable = useTableUrlState({
    search,
    navigate,
    pagination: {
      pageKey: 'positionsPage',
      pageSizeKey: 'positionsPageSize',
      defaultPage: 1,
      defaultPageSize: 25,
    },
    globalFilter: { enabled: false },
  })
  const ordersTable = useTableUrlState({
    search,
    navigate,
    pagination: {
      pageKey: 'ordersPage',
      pageSizeKey: 'ordersPageSize',
      defaultPage: 1,
      defaultPageSize: 25,
    },
    globalFilter: { enabled: false },
  })
  const orders = useReportOrdersQuery({
    pageIndex: ordersTable.pagination.pageIndex,
    pageSize: ordersTable.pagination.pageSize,
  })
  const positions = usePositionsQuery({
    pageIndex: positionsTable.pagination.pageIndex,
    pageSize: positionsTable.pagination.pageSize,
  })
  const trades = useTradesQuery({
    pageIndex: tradesTable.pagination.pageIndex,
    pageSize: tradesTable.pagination.pageSize,
  })
  const tradesChart = useTradesChartQuery(500)
  const openPositions = usePositionsQuery({
    status: 'OPEN',
    pageIndex: 0,
    pageSize: 1,
  })
  const rejectedOrders = useReportOrdersQuery({
    status: 'REJECTED',
    pageIndex: 0,
    pageSize: 1,
  })
  const reportSummary = useReportSummaryQuery()
  const activitySummary = useMemo(
    () => ({
      open: openPositions.data?.total ?? 0,
      rejected: rejectedOrders.data?.total ?? 0,
    }),
    [openPositions.data, rejectedOrders.data]
  )
  const tradesPageCount = trades.data
    ? Math.max(
        1,
        Math.ceil(trades.data.total / tradesTable.pagination.pageSize)
      )
    : null
  const positionsPageCount = positions.data
    ? Math.max(
        1,
        Math.ceil(positions.data.total / positionsTable.pagination.pageSize)
      )
    : null
  const ordersPageCount = orders.data
    ? Math.max(
        1,
        Math.ceil(orders.data.total / ordersTable.pagination.pageSize)
      )
    : null

  useEffect(() => {
    if (tradesPageCount == null) return
    tradesTable.ensurePageInRange(tradesPageCount, { resetTo: 'last' })
  }, [tradesPageCount, tradesTable])
  useEffect(() => {
    if (positionsPageCount == null) return
    positionsTable.ensurePageInRange(positionsPageCount, { resetTo: 'last' })
  }, [positionsPageCount, positionsTable])
  useEffect(() => {
    if (ordersPageCount == null) return
    ordersTable.ensurePageInRange(ordersPageCount, { resetTo: 'last' })
  }, [ordersPageCount, ordersTable])
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
            value={
              reportSummary.data
                ? formatMoney(reportSummary.data.total_pnl_usdc)
                : '...'
            }
            tone={
              (reportSummary.data?.total_pnl_usdc ?? 0) >= 0
                ? 'positive'
                : 'danger'
            }
          />
          <Metric
            label={t('pages.reporting.averageRoi')}
            value={
              reportSummary.data
                ? formatPercent(reportSummary.data.average_roi, true)
                : '...'
            }
            tone={
              (reportSummary.data?.average_roi ?? 0) >= 0
                ? 'positive'
                : 'danger'
            }
          />
          <Metric
            label={t('pages.reporting.closedTrades')}
            value={reportSummary.data?.closed_trades ?? '...'}
          />
          <Metric
            label={t('pages.reporting.openPositions')}
            value={openPositions.data ? activitySummary.open : '...'}
          />
          <Metric
            label={t('pages.reporting.rejectedOrders')}
            value={rejectedOrders.data ? activitySummary.rejected : '...'}
            tone={activitySummary.rejected > 0 ? 'warning' : 'neutral'}
          />
        </MetricStrip>
        {reportSummary.isError && (
          <ErrorState
            message={t('ui.loadFailed', {
              resource: t('navigation.reporting'),
              message: reportSummary.error.message,
            })}
          />
        )}
        <section className='my-7' aria-labelledby='pnl-heading'>
          <h2 id='pnl-heading' className='mb-3 text-base font-semibold'>
            {t('pages.reporting.cumulativePnl')}
          </h2>
          <TableFrame>
            <div className='p-4'>
              {tradesChart.isPending && <Skeleton className='h-64 w-full' />}
              {tradesChart.isError && (
                <ErrorState
                  message={t('ui.loadFailed', {
                    resource: t('ui.trades'),
                    message: tradesChart.error.message,
                  })}
                />
              )}
              {tradesChart.data && (
                <CumulativePnlChart trades={tradesChart.data.items} />
              )}
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
            {trades.isPending && <TableSkeleton />}
            {trades.isError && (
              <ErrorState
                message={t('ui.loadFailed', {
                  resource: t('ui.trades'),
                  message: trades.error.message,
                })}
              />
            )}
            {trades.data && (
              <TradesTable
                trades={trades.data.items}
                total={trades.data.total}
                pageIndex={tradesTable.pagination.pageIndex}
                pageSize={tradesTable.pagination.pageSize}
                onPageChange={(pageIndex) =>
                  tradesTable.onPaginationChange({
                    pageIndex,
                    pageSize: tradesTable.pagination.pageSize,
                  })
                }
                onPageSizeChange={(pageSize) =>
                  tradesTable.onPaginationChange({ pageIndex: 0, pageSize })
                }
              />
            )}
          </TabsContent>
          <TabsContent value='positions' className='mt-4'>
            {positions.isPending && <TableSkeleton />}
            {positions.isError && (
              <ErrorState
                message={t('ui.loadFailed', {
                  resource: t('ui.positions'),
                  message: positions.error.message,
                })}
              />
            )}
            {positions.data && (
              <PositionsTable
                positions={positions.data.items}
                total={positions.data.total}
                pageIndex={positionsTable.pagination.pageIndex}
                pageSize={positionsTable.pagination.pageSize}
                onPageChange={(pageIndex) =>
                  positionsTable.onPaginationChange({
                    pageIndex,
                    pageSize: positionsTable.pagination.pageSize,
                  })
                }
                onPageSizeChange={(pageSize) =>
                  positionsTable.onPaginationChange({ pageIndex: 0, pageSize })
                }
              />
            )}
          </TabsContent>
          <TabsContent value='orders' className='mt-4'>
            {orders.isPending && <TableSkeleton />}
            {orders.isError && (
              <ErrorState
                message={t('ui.loadFailed', {
                  resource: t('ui.orders'),
                  message: orders.error.message,
                })}
              />
            )}
            {orders.data && (
              <OrdersTable
                orders={orders.data.items}
                total={orders.data.total}
                pageIndex={ordersTable.pagination.pageIndex}
                pageSize={ordersTable.pagination.pageSize}
                onPageChange={(pageIndex) =>
                  ordersTable.onPaginationChange({
                    pageIndex,
                    pageSize: ordersTable.pagination.pageSize,
                  })
                }
                onPageSizeChange={(pageSize) =>
                  ordersTable.onPaginationChange({ pageIndex: 0, pageSize })
                }
              />
            )}
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

type TablePaginationProps = {
  total: number
  pageIndex: number
  pageSize: number
  onPageChange: (pageIndex: number) => void
  onPageSizeChange: (pageSize: number) => void
}

function TableSkeleton() {
  return (
    <TableFrame>
      <Table>
        <TableHeader>
          <TableRow>
            {Array.from({ length: 6 }, (_, index) => (
              <TableHead key={index}>
                <Skeleton className='h-3 w-16' />
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {Array.from({ length: 8 }, (_, index) => (
            <TableRow key={index}>
              <TableCell className='p-2' colSpan={6}>
                <Skeleton className='h-6 w-full' />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableFrame>
  )
}

function TradesTable({
  trades,
  total,
  pageIndex,
  pageSize,
  onPageChange,
  onPageSizeChange,
}: { trades: ReportTradeResult[] } & TablePaginationProps) {
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
                  title={t('pages.reporting.tradeDetail', {
                    asset: trade.asset,
                  })}
                  description={trade.report_result_id}
                >
                  <DetailList values={trade} />
                </DetailSheet>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <PaginationBar
        pageIndex={pageIndex}
        pageSize={pageSize}
        total={total}
        onPageChange={onPageChange}
        onPageSizeChange={onPageSizeChange}
      />
    </TableFrame>
  )
}

function PositionsTable({
  positions,
  total,
  pageIndex,
  pageSize,
  onPageChange,
  onPageSizeChange,
}: { positions: ReportPosition[] } & TablePaginationProps) {
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
                  title={t('pages.reporting.positionDetail', {
                    asset: position.asset,
                  })}
                  description={position.report_position_id}
                >
                  <DetailList values={position} />
                </DetailSheet>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <PaginationBar
        pageIndex={pageIndex}
        pageSize={pageSize}
        total={total}
        onPageChange={onPageChange}
        onPageSizeChange={onPageSizeChange}
      />
    </TableFrame>
  )
}
function OrdersTable({
  orders,
  total,
  pageIndex,
  pageSize,
  onPageChange,
  onPageSizeChange,
}: { orders: ReportOrder[] } & TablePaginationProps) {
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
                  title={t('pages.reporting.orderDetail', {
                    asset: order.asset,
                  })}
                  description={order.report_order_id}
                >
                  <DetailList values={order} />
                </DetailSheet>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <PaginationBar
        pageIndex={pageIndex}
        pageSize={pageSize}
        total={total}
        onPageChange={onPageChange}
        onPageSizeChange={onPageSizeChange}
      />
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
