import { useState } from 'react'
import { Link, useLocation } from '@tanstack/react-router'
import { Menu } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import { BrandMark } from '@/components/brand-mark'
import { ConfigDrawer } from '@/components/config-drawer'
import { LanguageSwitch } from '@/components/language-switch'
import { Search } from '@/components/search'
import { navigationData } from './data/navigation-data'

export function AppHeader() {
  const { t } = useTranslation()
  const pathname = useLocation({ select: (location) => location.pathname })
  const [mobileOpen, setMobileOpen] = useState(false)

  return (
    <header className='sticky top-0 z-40 h-16 border-b bg-background/95 backdrop-blur'>
      <div className='mx-auto flex h-full max-w-[1400px] items-center gap-3 px-4 sm:px-6'>
        <Link
          to='/'
          aria-label={t('navigation.home')}
          className='flex shrink-0 items-center gap-2.5 rounded-lg'
        >
          <BrandMark className='size-8 text-primary' />
          <span className='hidden leading-tight sm:block'>
            <span className='block text-sm font-semibold tracking-tight'>
              PolySignal Lab
            </span>
            <span className='hidden text-[10px] font-medium tracking-[0.08em] text-muted-foreground uppercase sm:block'>
              {t('navigation.readOnly')}
            </span>
          </span>
        </Link>

        <nav
          aria-label={t('navigation.primary')}
          className='mx-auto hidden items-center gap-1 xl:flex'
        >
          {navigationData.map((item) => (
            <NavigationLink
              key={item.url}
              item={item}
              active={pathname === item.url}
            />
          ))}
        </nav>

        <div className='ml-auto flex shrink-0 items-center gap-1 sm:gap-2 xl:ml-0'>
          <Search />
          <LanguageSwitch />
          <ConfigDrawer />
          <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
            <SheetTrigger asChild>
              <Button
                variant='outline'
                className='h-9 gap-2 rounded-lg px-3 xl:hidden'
                aria-label={t('navigation.openMenu')}
              >
                <Menu className='size-4' aria-hidden='true' />
                <span>{t('common.menu')}</span>
              </Button>
            </SheetTrigger>
            <SheetContent side='top' className='gap-0 shadow-none'>
              <div className='mx-auto w-full max-w-[1400px] px-4 pb-5 sm:px-6'>
                <SheetHeader className='px-0 pb-4 text-start'>
                  <SheetTitle>{t('common.navigation')}</SheetTitle>
                  <SheetDescription>
                    {t('navigation.description')}
                  </SheetDescription>
                </SheetHeader>
                <nav
                  aria-label={t('navigation.mobile')}
                  className='grid gap-2 sm:grid-cols-2'
                >
                  {navigationData.map((item) => (
                    <NavigationLink
                      key={item.url}
                      item={item}
                      active={pathname === item.url}
                      onClick={() => setMobileOpen(false)}
                      mobile
                    />
                  ))}
                </nav>
              </div>
            </SheetContent>
          </Sheet>
        </div>
      </div>
    </header>
  )
}

function NavigationLink({
  item,
  active,
  mobile = false,
  onClick,
}: {
  item: (typeof navigationData)[number]
  active: boolean
  mobile?: boolean
  onClick?: () => void
}) {
  const { t } = useTranslation()
  const Icon = item.icon

  return (
    <Link
      to={item.url}
      onClick={onClick}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'relative flex items-center gap-2 rounded-lg text-sm font-medium text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring active:translate-y-px',
        mobile ? 'min-h-11 px-3 py-2.5' : 'h-9 px-3',
        active &&
          'bg-primary/10 text-foreground ring-1 ring-primary/20 ring-inset before:absolute before:inset-y-2 before:start-0 before:w-0.5 before:rounded-full before:bg-primary'
      )}
    >
      <Icon className='size-4 shrink-0' strokeWidth={1.75} aria-hidden='true' />
      <span>{t(item.titleKey)}</span>
    </Link>
  )
}
