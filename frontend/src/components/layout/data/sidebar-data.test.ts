/**
 * Input: { describe, expect, it } from 'vitest', { sidebarData } from './sidebar-data', vitest, ./sidebar-data
 * Output: None
 * Pos: UI Layer - UI components
 *
 * 🔄 Self-reference: When this file changes, update this header
 */







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
