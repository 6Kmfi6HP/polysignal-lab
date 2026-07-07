/**
 * Input: { useMemo } from 'react', {, { Header } from '@/components/layout/header', { Main } from '@/components/layout/main', { Search } from '@/components/search', { ThemeSwitch } from '@/components/theme-switch', { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card', { Skeleton } from '@/components/ui/skeleton', { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs', type { PaperOrder, PaperPosition, PaperTradeResult } from '@/lib/api/types'
 * Output: PaperTradingPage, CumulativePnlChart, buildCumulativePnlPoints, TradesTable, PositionsTable, OrdersTable
 * Pos: Application code
 *
 * 🔄 Self-reference: When this file changes, update this header
 */







import { useMemo } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from 'recharts'
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  usePaperOrdersQuery,
  usePositionsQuery,
  useTradesQuery,
} from '@/lib/api/hooks'
import type { PaperOrder, PaperPosition, PaperTradeResult } from '@/lib/api/types'

export function PaperTradingPage() {
  const orders = usePaperOrdersQuery()
  const positions = usePositionsQuery()
  const trades = useTradesQuery()

  return (
    <>
      <Header>
        <div className='ml-auto flex items-center gap-2'>
          <Search />
          <ThemeSwitch />
        </div>
      </Header>
      <Main>
        <h1 className='mb-4 text-2xl font-bold tracking-tight'>Paper Trading</h1>

        <Card className='mb-6'>
          <CardHeader>
            <CardTitle>Cumulative PnL</CardTitle>
          </CardHeader>
          <CardContent>
            {trades.isPending && <Skeleton className='h-64 w-full' />}
            {trades.data && <CumulativePnlChart trades={trades.data} />}
          </CardContent>
        </Card>

        <Tabs defaultValue='trades'>
          <TabsList>
            <TabsTrigger value='trades'>Trades</TabsTrigger>
            <TabsTrigger value='positions'>Positions</TabsTrigger>
            <TabsTrigger value='orders'>Orders</TabsTrigger>
          </TabsList>
          <TabsContent value='trades'>
            {trades.isPending && <Skeleton className='h-64 w-full' />}
            {trades.isError && (
              <p className='text-destructive'>
                Failed to load trades: {trades.error.message}
              </p>
            )}
            {trades.data && <TradesTable trades={trades.data} />}
          </TabsContent>
          <TabsContent value='positions'>
            {positions.isPending && <Skeleton className='h-64 w-full' />}
            {positions.isError && (
              <p className='text-destructive'>
                Failed to load positions: {positions.error.message}
              </p>
            )}
            {positions.data && <PositionsTable positions={positions.data} />}
          </TabsContent>
          <TabsContent value='orders'>
            {orders.isPending && <Skeleton className='h-64 w-full' />}
            {orders.isError && (
              <p className='text-destructive'>
                Failed to load orders: {orders.error.message}
              </p>
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

function CumulativePnlChart({ trades }: { trades: PaperTradeResult[] }) {
  const points = useMemo(() => buildCumulativePnlPoints(trades), [trades])

  if (points.length === 0) {
    return <p className='text-muted-foreground'>No closed paper trades yet.</p>
  }

  return (
    <div role='img' aria-label='Cumulative PnL chart'>
      <ResponsiveContainer width='100%' height={240}>
        <LineChart data={points}>
          <CartesianGrid strokeDasharray='3 3' />
          <XAxis dataKey='closed_at' tick={false} />
          <YAxis />
          <Line
            type='monotone'
            dataKey='cumulative_pnl'
            stroke='currentColor'
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

function buildCumulativePnlPoints(trades: PaperTradeResult[]): CumulativePnlPoint[] {
  const sorted = [...trades].sort(
    (a, b) => new Date(a.closed_at).getTime() - new Date(b.closed_at).getTime()
  )
  const points: CumulativePnlPoint[] = []
  let cumulative = 0

  for (const trade of sorted) {
    cumulative += trade.pnl_usdc
    points.push({ closed_at: trade.closed_at, cumulative_pnl: cumulative })
  }

  return points
}

function TradesTable({ trades }: { trades: PaperTradeResult[] }) {
  if (trades.length === 0) {
    return <p className='text-muted-foreground'>No closed paper trades yet.</p>
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Trade</TableHead>
          <TableHead>Strategy</TableHead>
          <TableHead>Result</TableHead>
          <TableHead>PnL</TableHead>
          <TableHead>ROI</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {trades.map((trade) => (
          <TableRow key={trade.paper_trade_id}>
            <TableCell className='font-mono text-xs'>{trade.paper_trade_id}</TableCell>
            <TableCell>{trade.strategy}</TableCell>
            <TableCell>{trade.result}</TableCell>
            <TableCell>{trade.pnl_usdc.toFixed(2)} USDC</TableCell>
            <TableCell>{(trade.roi * 100).toFixed(1)}%</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function PositionsTable({ positions }: { positions: PaperPosition[] }) {
  if (positions.length === 0) {
    return <p className='text-muted-foreground'>No stored positions yet.</p>
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Position</TableHead>
          <TableHead>Strategy</TableHead>
          <TableHead>Market</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Entry price</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {positions.map((position) => (
          <TableRow key={position.paper_position_id}>
            <TableCell className='font-mono text-xs'>
              {position.paper_position_id}
            </TableCell>
            <TableCell>{position.strategy}</TableCell>
            <TableCell>
              {position.asset} {position.timeframe}
            </TableCell>
            <TableCell>{position.status}</TableCell>
            <TableCell>{position.entry_price.toFixed(3)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function OrdersTable({ orders }: { orders: PaperOrder[] }) {
  if (orders.length === 0) {
    return <p className='text-muted-foreground'>No stored orders yet.</p>
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Order</TableHead>
          <TableHead>Strategy</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Reject reason</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {orders.map((order) => (
          <TableRow key={order.paper_order_id}>
            <TableCell className='font-mono text-xs'>{order.paper_order_id}</TableCell>
            <TableCell>{order.strategy}</TableCell>
            <TableCell>{order.status}</TableCell>
            <TableCell>{order.reject_reason ?? '-'}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
