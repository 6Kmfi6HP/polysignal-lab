import { useTranslation } from 'react-i18next'
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
  const { t } = useTranslation()
  const signals = useSignalsQuery()
  const rejected = useRejectedSignalsQuery()
  return (
    <>
      <Main>
        <PageHeader
          title={t('navigation.signals')}
          description={t('pages.signals.description')}
        />
        <Tabs defaultValue='accepted'>
          <TabsList>
            <TabsTrigger value='accepted'>
              {t('pages.signals.accepted')}
            </TabsTrigger>
            <TabsTrigger value='rejected'>
              {t('pages.signals.rejected')}
            </TabsTrigger>
          </TabsList>
          <TabsContent value='accepted' className='mt-4'>
            {signals.isPending && (
              <Skeleton className='h-64 w-full rounded-xl' />
            )}
            {signals.isError && (
              <ErrorState
                message={t('ui.loadFailed', {
                  resource: t('ui.signals'),
                  message: signals.error.message,
                })}
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
                message={t('ui.loadFailed', {
                  resource: t('ui.rejectedSignals'),
                  message: rejected.error.message,
                })}
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
  const { t } = useTranslation()
  if (!signals.length)
    return (
      <EmptyState
        title={t('pages.signals.noSignals')}
        description={t('ui.acceptedDescription')}
      />
    )
  return (
    <TableFrame>
      <Table>
        <TableHeader>
          <TableRow>
            {['time', 'market', 'side', 'strategy', 'confidence'].map((key) => (
              <TableHead key={key}>{t(`fields.${key}`)}</TableHead>
            ))}
            <TableHead className='hidden lg:table-cell'>
              {t('fields.reference')}
            </TableHead>
            <TableHead className='hidden lg:table-cell'>
              {t('fields.maxEntry')}
            </TableHead>
            <TableHead className='hidden xl:table-cell'>
              {t('fields.freshness')}
            </TableHead>
            <TableHead className='hidden xl:table-cell'>
              {t('fields.toClose')}
            </TableHead>
            <TableHead>
              <span className='sr-only'>{t('common.details')}</span>
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
                  title={t('pages.signals.signalDetail', {
                    asset: signal.asset,
                    side: t(`status.${signal.side.toLowerCase()}`, {
                      defaultValue: signal.side,
                    }),
                  })}
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
  const { t } = useTranslation()
  if (!rejected.length)
    return (
      <EmptyState
        title={t('pages.signals.noRejected')}
        description={t('ui.rejectedDescription')}
      />
    )
  return (
    <TableFrame>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t('fields.rejected')}</TableHead>
            <TableHead>{t('fields.market')}</TableHead>
            <TableHead>{t('fields.strategy')}</TableHead>
            <TableHead>{t('fields.gate')}</TableHead>
            <TableHead className='whitespace-normal'>
              {t('fields.reasonCode')}
            </TableHead>
            <TableHead>
              <span className='sr-only'>{t('common.details')}</span>
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
                  title={t('pages.signals.rejectionDetail', {
                    gate: row.gate_name,
                  })}
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
