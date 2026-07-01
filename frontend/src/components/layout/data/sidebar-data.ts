import {
  Activity,
  Gauge,
  LayoutDashboard,
  ListChecks,
  Radio,
  Trophy,
} from 'lucide-react'
import { type NavGroup } from '../types'

type SidebarData = {
  user: {
    name: string
    email: string
    avatar: string
  }
  teams: {
    name: string
    logo: React.ElementType
    plan: string
  }[]
  navGroups: NavGroup[]
}

export const sidebarData: SidebarData = {
  user: {
    name: 'PolySignal Lab',
    email: 'read-only dashboard',
    avatar: '/avatars/shadcn.jpg',
  },
  teams: [
    {
      name: 'PolySignal Lab',
      logo: Gauge,
      plan: 'Read-only dashboard',
    },
  ],
  navGroups: [
    {
      title: 'Dashboard',
      items: [
        { title: 'Overview', url: '/', icon: LayoutDashboard },
        { title: 'Signals', url: '/signals', icon: Radio },
        { title: 'Paper Trading', url: '/paper-trading', icon: Activity },
        { title: 'Leaderboard', url: '/leaderboard', icon: Trophy },
        { title: 'Strategy Status', url: '/strategy-status', icon: ListChecks },
        { title: 'System Health', url: '/system-health', icon: Gauge },
      ],
    },
  ],
}
