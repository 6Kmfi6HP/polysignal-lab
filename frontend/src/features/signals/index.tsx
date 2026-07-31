import { useRejectedSignalsQuery, useSignalsQuery } from '@/lib/api/hooks'
import type { RejectedSignal, SignalCandidate } from '@/lib/api/types'
import {
  formatDateTime,
  formatDuration,
  formatFreshness,
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
  PageHeader,
  StatusBadge,
  TableFrame,
} from '@/components/dashboard'
import { Main } from '@/components/layout/main'

export function SignalsPage() {
  const signals = useSignalsQuery()
  const rejected = useRejectedSignalsQuery()
  return (
    <>
      <Main>
        <PageHeader
          title='Signals'
          description='Accepted candidates and gate rejections from the live strategy pipeline.'
        />
        <Tabs defaultValue='accepted'>
          <TabsList>
            <TabsTrigger value='accepted'>Accepted</TabsTrigger>
            <TabsTrigger value='rejected'>Rejected</TabsTrigger>
          </TabsList>
          <TabsContent value='accepted' className='mt-4'>
            {signals.isPending && (
              <Skeleton className='h-64 w-full rounded-xl' />
            )}
            {signals.isError && (
              <ErrorState
                message={`Failed to load signals: ${signals.error.message}`}
              />
            )}
            {signals.data && <SignalsTable signals={signals.data} />}
          </TabsContent>
          <TabsContent value='rejected' className='mt-4'>
            {rejected.isPending && (
              <Skeleton className='h-64 w-full rounded-xl' />
            )}
            {rejected.isError && (
              <ErrorState
                message={`Failed to load rejected signals: ${rejected.error.message}`}
              />
            )}
            {rejected.data && <RejectedSignalsTable rejected={rejected.data} />}
          </TabsContent>
        </Tabs>
      </Main>
    </>
  )
}

function SignalsTable({ signals }: { signals: SignalCandidate[] }) {
  if (!signals.length)
    return (
      <EmptyState
        title='No stored signals yet.'
        description='Accepted candidates appear after strategy evaluation passes every gate.'
      />
    )
  return (
    <TableFrame>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Time</TableHead>
            <TableHead>Market</TableHead>
            <TableHead>Side</TableHead>
            <TableHead>Strategy</TableHead>
            <TableHead>Confidence</TableHead>
            <TableHead className='hidden lg:table-cell'>Reference</TableHead>
            <TableHead className='hidden lg:table-cell'>Max entry</TableHead>
            <TableHead className='hidden xl:table-cell'>Freshness</TableHead>
            <TableHead className='hidden xl:table-cell'>To close</TableHead>
            <TableHead>
              <span className='sr-only'>Details</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {signals.map((signal) => (
            <TableRow key={signal.signal_id}>
              <TableCell className='font-mono text-xs'>
                {formatDateTime(signal.created_at)}
              </TableCell>
              <TableCell>
                <div className='font-medium'>
                  {signal.asset} {signal.timeframe}
                </div>
                <div className='max-w-44 truncate font-mono text-xs text-muted-foreground'>
                  {signal.market_slug}
                </div>
              </TableCell>
              <TableCell>
                <StatusBadge status={signal.side} />
              </TableCell>
              <TableCell className='font-mono text-xs'>
                {signal.strategy}
              </TableCell>
              <TableCell className='font-mono tabular-nums'>
                {formatPercent(signal.confidence)}
              </TableCell>
              <TableCell className='hidden font-mono lg:table-cell'>
                {formatPrice(signal.entry_reference_price)}
              </TableCell>
              <TableCell className='hidden font-mono lg:table-cell'>
                {formatPrice(signal.max_entry_price)}
              </TableCell>
              <TableCell className='hidden font-mono xl:table-cell'>
                {formatFreshness(signal.data_freshness_ms)}
              </TableCell>
              <TableCell className='hidden font-mono xl:table-cell'>
                {formatDuration(signal.seconds_to_close)}
              </TableCell>
              <TableCell>
                <DetailSheet
                  title={`${signal.asset} ${signal.side} signal`}
                  description={signal.signal_id}
                >
                  <DetailList
                    values={{
                      signal_id: signal.signal_id,
                      market_slug: signal.market_slug,
                      condition_id: signal.condition_id,
                      token_id: signal.token_id,
                      reason_codes: signal.reason_codes,
                      order_intent: signal.order_intent,
                      expiry_seconds: signal.expiry_seconds,
                      pair_id: signal.pair_id,
                      hedge_leg: signal.hedge_leg,
                      source_signal_ids: signal.source_signal_ids,
                      metrics: signal.metrics,
                    }}
                  />
                </DetailSheet>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableFrame>
  )
}

function RejectedSignalsTable({ rejected }: { rejected: RejectedSignal[] }) {
  if (!rejected.length)
    return (
      <EmptyState
        title='No rejected signals yet.'
        description='Gate failures and their diagnostic context appear here.'
      />
    )
  return (
    <TableFrame>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Rejected</TableHead>
            <TableHead>Market</TableHead>
            <TableHead>Strategy</TableHead>
            <TableHead>Gate</TableHead>
            <TableHead className='whitespace-normal'>Reason code</TableHead>
            <TableHead>
              <span className='sr-only'>Details</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rejected.map((row) => (
            <TableRow key={row.rejected_id}>
              <TableCell className='font-mono text-xs'>
                {formatDateTime(row.rejected_at)}
              </TableCell>
              <TableCell>
                <div className='font-medium'>
                  {row.candidate.asset} {row.candidate.timeframe}
                </div>
                <div className='max-w-44 truncate font-mono text-xs text-muted-foreground'>
                  {row.candidate.market_slug}
                </div>
              </TableCell>
              <TableCell className='font-mono text-xs'>
                {row.candidate.strategy}
              </TableCell>
              <TableCell>{row.gate_name}</TableCell>
              <TableCell className='max-w-xs whitespace-normal text-destructive'>
                {row.reason_code}
              </TableCell>
              <TableCell>
                <DetailSheet
                  title={`${row.gate_name} rejection`}
                  description={row.rejected_id}
                >
                  <DetailList
                    values={{
                      rejected_id: row.rejected_id,
                      signal_id: row.candidate.signal_id,
                      market_slug: row.candidate.market_slug,
                      gate_name: row.gate_name,
                      reason_code: row.reason_code,
                      details: row.details,
                      reason_codes: row.candidate.reason_codes,
                      order_intent: row.candidate.order_intent,
                      expiry_seconds: row.candidate.expiry_seconds,
                      metrics: row.candidate.metrics,
                    }}
                  />
                </DetailSheet>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableFrame>
  )
}
