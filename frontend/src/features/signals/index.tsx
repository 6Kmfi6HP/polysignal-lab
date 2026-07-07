/**
 * Input: { Header } from '@/components/layout/header', { Main } from '@/components/layout/main', { Search } from '@/components/search', { ThemeSwitch } from '@/components/theme-switch', { Skeleton } from '@/components/ui/skeleton', {, { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs', { useRejectedSignalsQuery, useSignalsQuery } from '@/lib/api/hooks', type { RejectedSignal, SignalCandidate } from '@/lib/api/types', @/components/layout/header
 * Output: SignalsPage, SignalsTable, RejectedSignalsTable
 * Pos: Application code
 *
 * 🔄 Self-reference: When this file changes, update this header
 */





import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
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
import { useRejectedSignalsQuery, useSignalsQuery } from '@/lib/api/hooks'
import type { RejectedSignal, SignalCandidate } from '@/lib/api/types'

export function SignalsPage() {
  const signals = useSignalsQuery()
  const rejected = useRejectedSignalsQuery()

  return (
    <>
      <Header>
        <div className='ml-auto flex items-center gap-2'>
          <Search />
          <ThemeSwitch />
        </div>
      </Header>
      <Main>
        <h1 className='mb-4 text-2xl font-bold tracking-tight'>Signals</h1>
        <Tabs defaultValue='accepted'>
          <TabsList>
            <TabsTrigger value='accepted'>Accepted</TabsTrigger>
            <TabsTrigger value='rejected'>Rejected</TabsTrigger>
          </TabsList>
          <TabsContent value='accepted'>
            {signals.isPending && <Skeleton className='h-64 w-full' />}
            {signals.isError && (
              <p className='text-destructive'>
                Failed to load signals: {signals.error.message}
              </p>
            )}
            {signals.data && <SignalsTable signals={signals.data} />}
          </TabsContent>
          <TabsContent value='rejected'>
            {rejected.isPending && <Skeleton className='h-64 w-full' />}
            {rejected.isError && (
              <p className='text-destructive'>
                Failed to load rejected signals: {rejected.error.message}
              </p>
            )}
            {rejected.data && <RejectedSignalsTable rejected={rejected.data} />}
          </TabsContent>
        </Tabs>
      </Main>
    </>
  )
}

function SignalsTable({ signals }: { signals: SignalCandidate[] }) {
  if (signals.length === 0) {
    return <p className='text-muted-foreground'>No stored signals yet.</p>
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Signal</TableHead>
          <TableHead>Strategy</TableHead>
          <TableHead>Market</TableHead>
          <TableHead>Side</TableHead>
          <TableHead>Confidence</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {signals.map((signal) => (
          <TableRow key={signal.signal_id}>
            <TableCell className='font-mono text-xs'>{signal.signal_id}</TableCell>
            <TableCell>{signal.strategy}</TableCell>
            <TableCell>
              {signal.asset} {signal.timeframe}
            </TableCell>
            <TableCell>{signal.side}</TableCell>
            <TableCell>{(signal.confidence * 100).toFixed(1)}%</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function RejectedSignalsTable({ rejected }: { rejected: RejectedSignal[] }) {
  if (rejected.length === 0) {
    return <p className='text-muted-foreground'>No rejected signals yet.</p>
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Signal</TableHead>
          <TableHead>Strategy</TableHead>
          <TableHead>Gate</TableHead>
          <TableHead>Reason</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rejected.map((row) => (
          <TableRow key={row.rejected_id}>
            <TableCell className='font-mono text-xs'>
              {row.candidate.signal_id}
            </TableCell>
            <TableCell>{row.candidate.strategy}</TableCell>
            <TableCell>{row.gate_name}</TableCell>
            <TableCell>{row.reason_code}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
