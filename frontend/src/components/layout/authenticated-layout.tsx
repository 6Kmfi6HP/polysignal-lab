import { Outlet } from '@tanstack/react-router'
import { SearchProvider } from '@/context/search-provider'
import { SkipToMain } from '@/components/skip-to-main'
import { AppHeader } from './app-header'

type AuthenticatedLayoutProps = {
  children?: React.ReactNode
}

export function AuthenticatedLayout({ children }: AuthenticatedLayoutProps) {
  return (
    <SearchProvider>
      <SkipToMain />
      <div className='@container/content flex min-h-svh min-w-0 flex-col overflow-x-clip'>
        <AppHeader />
        {children ?? <Outlet />}
      </div>
    </SearchProvider>
  )
}
