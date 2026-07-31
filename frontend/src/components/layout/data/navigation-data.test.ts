import { describe, expect, it } from 'vitest'
import { navigationData } from './navigation-data'

describe('navigationData', () => {
  it('keeps the six operations routes in their established order', () => {
    expect(navigationData.map(({ title, url }) => ({ title, url }))).toEqual([
      { title: 'Overview', url: '/' },
      { title: 'Signals', url: '/signals' },
      { title: 'Trading Reports', url: '/reporting' },
      { title: 'Leaderboard', url: '/leaderboard' },
      { title: 'Strategy Status', url: '/strategy-status' },
      { title: 'System Health', url: '/system-health' },
    ])
    expect(navigationData.every((item) => item.icon)).toBe(true)
  })
})
