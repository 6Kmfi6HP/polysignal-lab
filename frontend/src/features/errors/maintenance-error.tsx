import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { BrandMark } from '@/components/brand-mark'

export function MaintenanceError() {
  const { t } = useTranslation()
  return (
    <div className='h-svh'>
      <div className='m-auto flex h-full w-full flex-col items-center justify-center gap-2'>
        <BrandMark className='mb-4 size-12 text-primary' />
        <h1 className='text-[7rem] leading-tight font-bold'>503</h1>
        <span className='font-medium'>{t('errors.maintenance')}</span>
        <p className='text-center text-muted-foreground'>
          {t('errors.maintenanceDescription')}
        </p>
        <div className='mt-6 flex gap-4'>
          <Button variant='outline'>{t('errors.learnMore')}</Button>
        </div>
      </div>
    </div>
  )
}
