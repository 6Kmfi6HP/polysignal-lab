import { describe, expect, it } from 'vitest'
import { en, zhCN } from './resources'

function keys(value: object, prefix = ''): string[] {
  return Object.entries(value).flatMap(([key, child]) => {
    const path = prefix ? `${prefix}.${key}` : key
    return typeof child === 'object' ? keys(child, path) : path
  })
}

describe('translation resources', () => {
  it('keeps English and Simplified Chinese keys identical', () => {
    expect(keys(zhCN).sort()).toEqual(keys(en).sort())
  })

  it('translates UP and DOWN direction sides correctly in Chinese', () => {
    expect(zhCN.status.up).toBe('看涨')
    expect(zhCN.status.down).toBe('看跌')
  })
})

