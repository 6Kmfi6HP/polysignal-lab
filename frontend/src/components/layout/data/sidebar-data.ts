/**
 * Input: {, { type NavGroup } from '../types', ../types, lucide-react
 * Output: sidebarData
 * Pos: UI Layer - UI components
 *
 * 🔄 Self-reference: When this file changes, update this header
 */









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
  navGroups: NavGroup[]
}

export const sidebarData: SidebarData = {
  navGroups: [
    {
      title: 'Dashboard',
      items: [
        { title: 'Overview', url: '/', icon: LayoutDashboard },
        { title: 'Signals', url: '/signals', icon: Radio },
        { title: 'Trading Reports', url: '/reporting', icon: Activity },
        { title: 'Leaderboard', url: '/leaderboard', icon: Trophy },
        { title: 'Strategy Status', url: '/strategy-status', icon: ListChecks },
        { title: 'System Health', url: '/system-health', icon: Gauge },
      ],
    },
  ],
}
