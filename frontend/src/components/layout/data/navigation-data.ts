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
  title: string
  url: string
  icon: LucideIcon
}

export const navigationData: NavigationItem[] = [
  { title: 'Overview', url: '/', icon: LayoutDashboard },
  { title: 'Signals', url: '/signals', icon: Radio },
  { title: 'Trading Reports', url: '/reporting', icon: Activity },
  { title: 'Leaderboard', url: '/leaderboard', icon: Trophy },
  { title: 'Strategy Status', url: '/strategy-status', icon: ListChecks },
  { title: 'System Health', url: '/system-health', icon: Gauge },
]
