/**
 * Input: { Header } from '@/components/layout/header', { Main } from '@/components/layout/main', { Search } from '@/components/search', { ThemeSwitch } from '@/components/theme-switch', { Badge } from '@/components/ui/badge', { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card', { Skeleton } from '@/components/ui/skeleton', { useHealthQuery } from '@/lib/api/hooks', @/components/layout/header, @/components/layout/main
 * Output: SystemHealthPage
 * Pos: Application code
 *
 * 🔄 Self-reference: When this file changes, update this header
 */





import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useHealthQuery } from '@/lib/api/hooks'

export function SystemHealthPage() {
  const health = useHealthQuery()

  return (
    <>
      <Header>
        <div className='ml-auto flex items-center gap-2'>
          <Search />
          <ThemeSwitch />
        </div>
      </Header>
      <Main>
        <h1 className='mb-4 text-2xl font-bold tracking-tight'>System Health</h1>

        {health.isPending && <Skeleton className='h-64 w-full' />}
        {health.isError && (
          <p className='text-destructive'>Failed to load health: {health.error.message}</p>
        )}

        {health.data && (
          <>
            <div className='mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3'>
              {health.data.components.map((component) => (
                <Card key={component.name}>
                  <CardHeader className='flex items-center justify-between pb-2'>
                    <CardTitle className='text-sm font-medium'>
                      {component.name}
                    </CardTitle>
                    <Badge variant={component.status === 'ok' ? 'default' : 'destructive'}>
                      {component.status}
                    </Badge>
                  </CardHeader>
                  <CardContent className='text-muted-foreground text-sm'>
                    {component.last_error ?? 'No recent errors.'}
                  </CardContent>
                </Card>
              ))}
              {health.data.components.length === 0 && (
                <p className='text-muted-foreground'>
                  No component health rows recorded yet.
                </p>
              )}
            </div>

            <Card>
              <CardHeader>
                <CardTitle>Recent system events</CardTitle>
              </CardHeader>
              <CardContent>
                {health.data.recent_system_events.length === 0 ? (
                  <p className='text-muted-foreground'>No system events recorded yet.</p>
                ) : (
                  <ul className='space-y-2'>
                    {health.data.recent_system_events.map((event, index) => (
                      <li key={index} className='font-mono text-xs'>
                        {JSON.stringify(event)}
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          </>
        )}
      </Main>
    </>
  )
}
