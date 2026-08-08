import { useState } from 'react'
import { Check, Copy, Info } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useVersionQuery } from '@/lib/api/hooks'
import type { BuildInfoResponse } from '@/lib/api/types'
import { Button } from '@/components/ui/button'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip'

export function BuildVersion() {
  const { t } = useTranslation()
  const version = useVersionQuery()
  const summary = version.data
    ? [version.data.build_version, version.data.short_commit_sha]
        .filter(Boolean)
        .join(' · ')
    : t('version.unavailable')

  return (
    <Sheet>
      <Tooltip>
        <TooltipTrigger asChild>
          <SheetTrigger asChild>
            <Button
              variant='ghost'
              className='h-9 max-w-64 min-w-9 gap-2 px-2 text-muted-foreground'
              aria-label={t('version.open')}
            >
              <Info className='size-4 shrink-0 sm:hidden' aria-hidden='true' />
              <span className='hidden truncate font-mono text-xs sm:block'>
                {summary}
              </span>
            </Button>
          </SheetTrigger>
        </TooltipTrigger>
        <TooltipContent>{t('version.open')}</TooltipContent>
      </Tooltip>
      <SheetContent className='w-full sm:max-w-md'>
        <SheetHeader className='text-start'>
          <SheetTitle>{t('version.title')}</SheetTitle>
          <SheetDescription>{t('version.description')}</SheetDescription>
        </SheetHeader>
        <div className='overflow-y-auto px-4 pb-6'>
          {version.data ? (
            <BuildDetails build={version.data} />
          ) : (
            <p className='text-sm text-muted-foreground'>
              {t('version.unavailableDescription')}
            </p>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}

function BuildDetails({ build }: { build: BuildInfoResponse }) {
  const { t } = useTranslation()
  const rows: Array<[string, string | null]> = [
    [t('version.applicationVersion'), build.application_version],
    [t('version.buildVersion'), build.build_version],
    [t('version.channel'), build.channel],
    [t('version.sourceRef'), build.source_ref],
    [t('version.commitSha'), build.commit_sha],
    [t('version.immutableTag'), build.immutable_tag],
  ]

  return (
    <dl className='divide-y rounded-md border'>
      {rows.map(([label, value]) => (
        <div key={label} className='grid gap-1 px-3 py-3'>
          <dt className='text-xs font-medium text-muted-foreground'>{label}</dt>
          <dd className='flex min-w-0 items-start gap-2'>
            <code className='min-w-0 flex-1 text-xs leading-5 break-all'>
              {value ?? t('common.unavailable')}
            </code>
            {value && <CopyButton label={label} value={value} />}
          </dd>
        </div>
      ))}
    </dl>
  )
}

function CopyButton({ label, value }: { label: string; value: string }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    await navigator.clipboard.writeText(value)
    setCopied(true)
  }

  return (
    <Button
      type='button'
      size='icon'
      variant='ghost'
      className='size-7 shrink-0'
      aria-label={t('version.copy', { field: label })}
      onClick={copy}
    >
      {copied ? (
        <Check className='size-3.5' aria-hidden='true' />
      ) : (
        <Copy className='size-3.5' aria-hidden='true' />
      )}
    </Button>
  )
}
