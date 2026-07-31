import {
  Activity,
  Gauge,
  LayoutDashboard,
  ListChecks,
  Radio,
  Trophy,
  type LucideIcon,
} from 'lucide-react'

export type NavigationItem = {
  titleKey:
    | 'navigation.overview'
    | 'navigation.signals'
    | 'navigation.reporting'
    | 'navigation.leaderboard'
    | 'navigation.strategyStatus'
    | 'navigation.systemHealth'
  url: string
  icon: LucideIcon
}

export const navigationData: NavigationItem[] = [
  { titleKey: 'navigation.overview', url: '/', icon: LayoutDashboard },
  { titleKey: 'navigation.signals', url: '/signals', icon: Radio },
  { titleKey: 'navigation.reporting', url: '/reporting', icon: Activity },
  { titleKey: 'navigation.leaderboard', url: '/leaderboard', icon: Trophy },
  {
    titleKey: 'navigation.strategyStatus',
    url: '/strategy-status',
    icon: ListChecks,
  },
  { titleKey: 'navigation.systemHealth', url: '/system-health', icon: Gauge },
]
