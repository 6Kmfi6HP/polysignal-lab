import { describe, expect, it } from 'vitest'
import { navigationData } from './navigation-data'

describe('navigationData', () => {
  it('keeps the six operations routes in their established order', () => {
    expect(
      navigationData.map(({ titleKey, url }) => ({ titleKey, url }))
    ).toEqual([
      { titleKey: 'navigation.overview', url: '/' },
      { titleKey: 'navigation.signals', url: '/signals' },
      { titleKey: 'navigation.reporting', url: '/reporting' },
      { titleKey: 'navigation.leaderboard', url: '/leaderboard' },
      { titleKey: 'navigation.strategyStatus', url: '/strategy-status' },
      { titleKey: 'navigation.systemHealth', url: '/system-health' },
    ])
    expect(navigationData.every((item) => item.icon)).toBe(true)
  })
})
