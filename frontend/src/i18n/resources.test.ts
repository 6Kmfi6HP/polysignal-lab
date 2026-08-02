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

  it('keeps UP and DOWN direction labels untranslated', () => {
    expect(zhCN.status.up).toBe('UP')
    expect(zhCN.status.down).toBe('DOWN')
    expect(en.status.up).toBe('UP')
    expect(en.status.down).toBe('DOWN')
  })

  it('covers trade detail sheet field keys used by reporting payloads', () => {
    for (const key of [
      'closed_at',
      'opened_at',
      'entry_price',
      'stake_usdc',
      'pnl_usdc',
      'exit_mode',
      'exit_reason',
      'entry_fee',
      'fee_model',
      'report_result_id',
    ] as const) {
      expect(zhCN.fields[key]).toBeTruthy()
      expect(en.fields[key]).toBeTruthy()
    }
    expect(zhCN.status.take_profit).toBe('止盈')
    expect(zhCN.pages.reporting.tradeDetail).toContain('交易')
  })
})
