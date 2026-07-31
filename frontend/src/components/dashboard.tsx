import { AlertCircle, Inbox } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { humanize } from '@/lib/format'
import { cn } from '@/lib/utils'
import { i18n } from '@/context/locale-provider'
import { Badge } from '@/components/ui/badge'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'

export function PageHeader({
  title,
  description,
  meta,
}: {
  title: string
  description: string
  meta?: React.ReactNode
}) {
  return (
    <div className='mb-6 flex flex-col gap-3 border-b pb-5 sm:flex-row sm:items-end sm:justify-between'>
      <div>
        <h1 className='text-2xl font-semibold tracking-tight'>{title}</h1>
        <p className='mt-1 max-w-2xl text-sm text-muted-foreground'>
          {description}
        </p>
      </div>
      {meta && <div className='shrink-0'>{meta}</div>}
    </div>
  )
}

export function MetricStrip({ children }: { children: React.ReactNode }) {
  return (
    <dl className='grid border-y sm:grid-cols-2 lg:grid-cols-5'>{children}</dl>
  )
}

export function Metric({
  label,
  value,
  tone = 'neutral',
  detail,
}: {
  label: string
  value: React.ReactNode
  tone?: 'neutral' | 'positive' | 'warning' | 'danger'
  detail?: string
}) {
  return (
    <div className='border-b px-4 py-3 last:border-b-0 sm:border-e lg:border-b-0'>
      <dt className='text-xs font-medium text-muted-foreground'>{label}</dt>
      <dd
        className={cn(
          'mt-1 font-mono text-xl font-semibold tabular-nums',
          tone === 'positive' && 'text-positive',
          tone === 'warning' && 'text-warning',
          tone === 'danger' && 'text-destructive'
        )}
      >
        {value}
      </dd>
      {detail && (
        <dd className='mt-1 text-xs text-muted-foreground'>{detail}</dd>
      )}
    </div>
  )
}

const positiveStatuses = new Set([
  'ok',
  'active',
  'complete',
  'filled',
  'win',
  'calibrated',
  'closed',
  'up',
])
const warningStatuses = new Set([
  'pending',
  'resting',
  'partial',
  'incomplete',
  'uncalibrated',
  'insufficient_data',
  'unknown',
  'disabled',
  'inactive',
  'untradable',
  'down',
])
const dangerStatuses = new Set([
  'error',
  'failed',
  'rejected',
  'loss',
  'missing_data',
  'unsupported_market',
  'degraded',
])

export function StatusBadge({ status }: { status: string }) {
  const normalized = status.toLowerCase()
  return (
    <Badge
      variant='outline'
      className={cn(
        'max-w-full rounded-md font-medium',
        positiveStatuses.has(normalized) &&
          'border-positive/30 bg-positive/10 text-positive',
        warningStatuses.has(normalized) &&
          'border-warning/30 bg-warning/10 text-warning',
        dangerStatuses.has(normalized) &&
          'border-destructive/30 bg-destructive/10 text-destructive'
      )}
    >
      {i18n.exists(`status.${normalized}`)
        ? i18n.t(`status.${normalized}`)
        : humanize(status)}
    </Badge>
  )
}

export function EmptyState({
  title,
  description,
}: {
  title: string
  description: string
}) {
  return (
    <div className='flex min-h-40 flex-col items-center justify-center rounded-xl border border-dashed px-6 text-center'>
      <Inbox className='mb-3 size-5 text-muted-foreground' aria-hidden='true' />
      <p className='font-medium'>{title}</p>
      <p className='mt-1 max-w-md text-sm text-muted-foreground'>
        {description}
      </p>
    </div>
  )
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div
      role='alert'
      className='flex items-start gap-3 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive'
    >
      <AlertCircle className='mt-0.5 size-4 shrink-0' aria-hidden='true' />
      <span>{message}</span>
    </div>
  )
}

export function TableFrame({ children }: { children: React.ReactNode }) {
  return (
    <div className='overflow-hidden rounded-xl border bg-card'>{children}</div>
  )
}

export function DetailSheet({
  title,
  description,
  triggerLabel,
  children,
}: {
  title: string
  description: string
  triggerLabel?: string
  children: React.ReactNode
}) {
  const { t } = useTranslation()
  return (
    <Sheet>
      <SheetTrigger className='rounded-md px-2 py-1 text-xs font-medium text-accent-foreground underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-ring'>
        {triggerLabel ?? t('common.viewDetails')}
      </SheetTrigger>
      <SheetContent className='w-full overflow-y-auto sm:max-w-lg'>
        <SheetHeader className='border-b p-5 pe-12'>
          <SheetTitle>{title}</SheetTitle>
          <SheetDescription className='font-mono text-xs break-all'>
            {description}
          </SheetDescription>
        </SheetHeader>
        <div className='p-5'>{children}</div>
      </SheetContent>
    </Sheet>
  )
}

export function DetailList({ values }: { values: object }) {
  const { t } = useTranslation()
  return (
    <dl className='space-y-3'>
      {Object.entries(values).map(([key, value]) => (
        <div
          key={key}
          className='grid gap-1 border-b pb-3 sm:grid-cols-[9rem_1fr]'
        >
          <dt className='text-xs font-medium text-muted-foreground'>
            {i18n.exists(`fields.${key}`) ? t(`fields.${key}`) : humanize(key)}
          </dt>
          <dd className='font-mono text-xs break-all'>{renderValue(value)}</dd>
        </div>
      ))}
    </dl>
  )
}

function renderValue(value: unknown): React.ReactNode {
  if (value == null || value === '') return i18n.t('common.unavailable')
  if (typeof value === 'object')
    return (
      <pre className='whitespace-pre-wrap'>
        {JSON.stringify(value, null, 2)}
      </pre>
    )
  return String(value)
}
