import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'

const PAGE_SIZE_OPTIONS = [25, 50, 100] as const

export type PaginationBarProps = {
  pageIndex: number
  pageSize: number
  total: number
  onPageChange: (pageIndex: number) => void
  onPageSizeChange: (pageSize: number) => void
}

export function PaginationBar({
  pageIndex,
  pageSize,
  total,
  onPageChange,
  onPageSizeChange,
}: PaginationBarProps) {
  const { t } = useTranslation()
  const pageCount = Math.max(1, Math.ceil(total / pageSize))
  const pageNumbers = getPageNumbers(pageCount, pageIndex + 1)
  const firstVisible = total === 0 ? 0 : pageIndex * pageSize + 1
  const lastVisible = Math.min(total, (pageIndex + 1) * pageSize)

  return (
    <div className='flex flex-col gap-3 border-t p-3 sm:flex-row sm:items-center sm:justify-between'>
      <p
        aria-live='polite'
        className='font-mono text-xs text-muted-foreground tabular-nums'
      >
        {t('ui.showingRows', {
          start: firstVisible,
          end: lastVisible,
          total,
        })}
      </p>
      <div className='flex flex-wrap items-center gap-2'>
        <Button
          variant='outline'
          size='icon'
          aria-label={t('ui.previousPage')}
          disabled={pageIndex <= 0}
          onClick={() => onPageChange(pageIndex - 1)}
        >
          <ChevronLeft aria-hidden='true' />
        </Button>
        {pageNumbers.map((page, index) =>
          page === 'ellipsis' ? (
            <span
              key={`ellipsis-${index}`}
              className='px-1 text-xs text-muted-foreground'
              aria-hidden='true'
            >
              …
            </span>
          ) : (
            <Button
              key={page}
              variant={page === pageIndex + 1 ? 'default' : 'outline'}
              size='sm'
              className={cn('min-w-8 px-2')}
              aria-current={page === pageIndex + 1 ? 'page' : undefined}
              aria-label={
                page === pageIndex + 1
                  ? t('ui.currentPage', { page })
                  : t('ui.pageNumber', { page })
              }
              onClick={() => onPageChange(page - 1)}
            >
              {page}
            </Button>
          )
        )}
        <Button
          variant='outline'
          size='icon'
          aria-label={t('ui.nextPage')}
          disabled={pageIndex >= pageCount - 1}
          onClick={() => onPageChange(pageIndex + 1)}
        >
          <ChevronRight aria-hidden='true' />
        </Button>
        <span className='ms-1 flex items-center gap-1 text-xs text-muted-foreground'>
          <span>{t('ui.rowsPerPage')}</span>
          <span className='inline-flex rounded-md border bg-background shadow-xs'>
            {PAGE_SIZE_OPTIONS.map((size) => (
              <button
                key={size}
                type='button'
                className={cn(
                  'h-7 rounded-md px-2 text-xs font-medium transition-colors',
                  size === pageSize
                    ? 'bg-primary text-primary-foreground'
                    : 'hover:bg-accent hover:text-accent-foreground'
                )}
                aria-pressed={size === pageSize}
                onClick={() => onPageSizeChange(size)}
              >
                {size}
              </button>
            ))}
          </span>
        </span>
      </div>
    </div>
  )
}

function getPageNumbers(
  pageCount: number,
  currentPage: number
): Array<number | 'ellipsis'> {
  if (pageCount <= 7) {
    return Array.from({ length: pageCount }, (_, index) => index + 1)
  }
  if (currentPage <= 4) {
    return [1, 2, 3, 4, 5, 'ellipsis', pageCount]
  }
  if (currentPage >= pageCount - 3) {
    return [
      1,
      'ellipsis',
      pageCount - 4,
      pageCount - 3,
      pageCount - 2,
      pageCount - 1,
      pageCount,
    ]
  }
  return [
    1,
    'ellipsis',
    currentPage - 1,
    currentPage,
    currentPage + 1,
    'ellipsis',
    pageCount,
  ]
}
