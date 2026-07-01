import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'

export function StrategyStatusPage() {
  return (
    <>
      <Header>
        <div className='ml-auto flex items-center gap-2'>
          <Search />
          <ThemeSwitch />
        </div>
      </Header>
      <Main>
        <h1 className='text-2xl font-bold tracking-tight'>Strategy Status</h1>
      </Main>
    </>
  )
}
