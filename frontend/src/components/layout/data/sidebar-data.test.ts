import { describe, expect, it } from 'vitest'
import { sidebarData } from './sidebar-data'

describe('sidebarData', () => {
  it('lists Task 4 navigation routes in order', () => {
    const urls = sidebarData.navGroups.flatMap((group) =>
      group.items.map((item) => item.url)
    )

    expect(urls).toEqual([
      '/',
      '/signals',
      '/paper-trading',
      '/leaderboard',
      '/strategy-status',
      '/system-health',
    ])
  })
})
