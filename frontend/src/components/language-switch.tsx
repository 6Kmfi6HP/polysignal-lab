import { Check, Languages } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { type LanguagePreference, useLocale } from '@/context/locale-provider'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

const options: { value: LanguagePreference; label: string }[] = [
  { value: 'auto', label: '自动 / Automatic' },
  { value: 'en', label: 'English' },
  { value: 'zh-CN', label: '简体中文' },
]

export function LanguageSwitch() {
  const { t } = useTranslation()
  const { preference, setPreference } = useLocale()
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant='ghost'
          size='icon'
          className='rounded-full'
          aria-label={t('settings.selectLanguage')}
        >
          <Languages aria-hidden='true' />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align='end'>
        {options.map((option) => (
          <DropdownMenuItem
            key={option.value}
            onSelect={() => setPreference(option.value)}
          >
            <span className='w-4'>
              {preference === option.value && (
                <Check className='size-4' aria-hidden='true' />
              )}
            </span>
            {option.label}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
